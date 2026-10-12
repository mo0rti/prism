"""The incident report is dated on the day of REL-002, so a live run and the fixture replay both find their report where the step looks."""

import dataclasses
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prism_e2e import config, report as reports, runner, workspace as ws  # noqa: E402
from prism_e2e.runner import Journey, build_preview_prompt, load_prompt  # noqa: E402
import test_approval as approval_tests  # noqa: E402
from test_approval import PREVIEW, JourneyCase  # noqa: E402

STEP = config.STEPS_BY_ID["ingest-incident"]
LIVE_DAY = "2026-10-12"
FIXTURE_DAY = "2026-10-09"
RECORD = config.FIXTURES_DIR / "release-retry/knowledge/wiki/releases/REL-002.md"
REPORT = config.FIXTURES_DIR / "ingest-incident/knowledge/intake/processed/2026-10-09-release-incident/report.md"
STATUS_BOARD = config.REPO_ROOT / "template/knowledge/wiki/status-board.md"


def write_release_record(workspace: Path, day: str) -> None:
    """The record REL-002 as the fixtures hold it, dated ``day``."""

    text = RECORD.read_bytes().decode("utf-8")
    assert f"date: {FIXTURE_DAY}" in text
    target = workspace / "knowledge/wiki/releases/REL-002.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(text.replace(f"date: {FIXTURE_DAY}", f"date: {day}").encode("utf-8"))


class TemporaryWorkspace(unittest.TestCase):
    def workspace(self) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return Path(temporary.name)


class ReleaseDayTests(TemporaryWorkspace):
    def test_the_day_is_the_date_of_the_release_record_in_the_workspace(self):
        for day in (LIVE_DAY, FIXTURE_DAY):
            with self.subTest(day=day):
                root = self.workspace()
                write_release_record(root, day)
                self.assertEqual(ws.release_day(root), day)
                self.assertEqual(ws.intake_day(root, "ingest-incident"), day)

    def test_only_the_incident_step_follows_the_release(self):
        root = self.workspace()
        write_release_record(root, LIVE_DAY)
        self.assertIsNone(ws.intake_day(root, "po-intake"))
        self.assertEqual(ws.pending_folder("po-intake", LIVE_DAY), ws.PENDING_INTAKE)

    def test_a_missing_record_or_a_date_that_is_not_a_day_is_a_setup_error(self):
        root = self.workspace()
        with self.assertRaises(ws.SetupError):
            ws.release_day(root)
        write_release_record(root, "yesterday")
        with self.assertRaises(ws.SetupError):
            ws.release_day(root)

    def test_the_folders_are_named_for_the_day_and_the_recorded_day_gives_the_fixture_folders(self):
        self.assertEqual(ws.pending_folder("ingest-incident", LIVE_DAY), "knowledge/intake/pending/2026-10-12-release-incident")
        self.assertEqual(ws.processed_folder("ingest-incident", LIVE_DAY), "knowledge/intake/processed/2026-10-12-release-incident")
        self.assertEqual(ws.pending_folder("ingest-incident"), "knowledge/intake/pending/2026-10-09-release-incident")
        self.assertEqual(ws.pending_folder("ingest-incident", FIXTURE_DAY), ws.pending_folder("ingest-incident"))
        self.assertEqual(ws.PENDING_INPUTS["ingest-incident"][0], "2026-10-09-release-incident")

    def test_the_manifest_path_follows_the_day(self):
        paths = ws.localize_paths(sorted(ws.fixture_files(["ingest-incident"])), "ingest-incident", LIVE_DAY)
        self.assertIn("knowledge/intake/processed/2026-10-12-release-incident/MANIFEST.md", paths)
        self.assertFalse([path for path in paths if "2026-10-09" in path])
        recorded = sorted(ws.fixture_files(["ingest-incident"]))
        self.assertEqual(ws.localize_paths(recorded, "ingest-incident", FIXTURE_DAY), recorded)
        self.assertEqual(ws.localize_paths(recorded, "ingest-incident"), recorded)
        self.assertEqual(ws.localize_paths(["knowledge/wiki/log.md"], "release-retry", LIVE_DAY), ["knowledge/wiki/log.md"])


class PlacedReportTests(TemporaryWorkspace):
    def test_with_the_day_of_the_run_the_report_says_that_day_and_nothing_else_changes(self):
        root = self.workspace()
        placed = ws.place_pending_input(root, "ingest-incident", None, LIVE_DAY)
        self.assertEqual(placed, root / "knowledge/intake/pending/2026-10-12-release-incident/report.md")
        recorded = REPORT.read_bytes().decode("utf-8")
        text = placed.read_bytes().decode("utf-8")
        self.assertIn("Reported by support on 2026-10-12.", text)
        self.assertNotIn(FIXTURE_DAY, text)
        self.assertEqual(text, recorded.replace("Reported by support on 2026-10-09.", "Reported by support on 2026-10-12."))
        self.assertIn("about forty minutes after release REL-002", text, "the times stay relative to the release")
        self.assertIn("- 09:10: Support received the first report", text, "the timeline keeps its clock times")
        self.assertFalse((root / "knowledge/intake/pending/2026-10-09-release-incident").exists())

    def test_with_the_recorded_day_the_report_is_the_fixture_byte_for_byte(self):
        for day in (FIXTURE_DAY, None):
            with self.subTest(day=day):
                root = self.workspace()
                placed = ws.place_pending_input(root, "ingest-incident", None, day)
                self.assertEqual(placed, root / "knowledge/intake/pending/2026-10-09-release-incident/report.md")
                self.assertEqual(placed.read_bytes(), REPORT.read_bytes())

    def test_a_fixture_set_report_without_the_line_cannot_be_dated_for_another_day(self):
        root = self.workspace()
        with tempfile.TemporaryDirectory() as folder:
            report = Path(folder) / "ingest-incident/knowledge/intake/processed/2026-10-09-release-incident/report.md"
            report.parent.mkdir(parents=True)
            report.write_text("# Incident report - Another\n", encoding="utf-8")
            with self.assertRaises(ws.SetupError):
                ws.place_pending_input(root, "ingest-incident", Path(folder), LIVE_DAY)
            placed = ws.place_pending_input(root, "ingest-incident", Path(folder), FIXTURE_DAY)
            self.assertIn("Another", placed.read_text(encoding="utf-8"))

    def test_a_reset_removes_the_pending_report_of_any_day(self):
        for day in (LIVE_DAY, FIXTURE_DAY):
            with self.subTest(day=day):
                root = self.workspace()
                ws.place_pending_input(root, "ingest-incident", None, day)
                ws.place_pending_brief(root)
                keep = root / "knowledge/intake/pending/.gitkeep"
                keep.write_text("", encoding="utf-8")
                ws.reset_journey_files(root)
                self.assertEqual(sorted(path.name for path in (root / "knowledge/intake/pending").iterdir()), [".gitkeep"])


class PromptTests(unittest.TestCase):
    def test_the_prompt_names_the_folder_of_the_run(self):
        prompt = build_preview_prompt("ingest-incident", None, None, LIVE_DAY)
        self.assertIn("`knowledge/intake/pending/2026-10-12-release-incident`", prompt)
        self.assertNotIn(FIXTURE_DAY, prompt)
        self.assertNotIn(runner.INTAKE_FOLDER_PLACEHOLDER, prompt)
        self.assertNotIn("{", prompt)

    def test_with_the_recorded_day_the_prompt_is_as_it_was_written_for_the_fixtures(self):
        for day in (FIXTURE_DAY, None):
            with self.subTest(day=day):
                prompt = build_preview_prompt("ingest-incident", None, None, day)
                self.assertIn("`knowledge/intake/pending/2026-10-09-release-incident`", prompt)
                self.assertEqual(prompt, load_prompt("ingest-incident").replace("{intake_folder}", "2026-10-09-release-incident"))

    def test_only_the_folder_name_is_substituted(self):
        template = load_prompt("ingest-incident")
        self.assertEqual(template.count(runner.INTAKE_FOLDER_PLACEHOLDER), 1)
        before, after = template.split(runner.INTAKE_FOLDER_PLACEHOLDER)
        prompt = build_preview_prompt("ingest-incident", None, None, LIVE_DAY)
        self.assertTrue(prompt.startswith(before) and prompt.endswith(after))
        self.assertEqual(prompt, before + "2026-10-12-release-incident" + after)


class RunTests(JourneyCase):
    """The runner reads REL-002 in the workspace before the step, and everything it derives follows that day."""

    def put_record(self, day: str) -> Path:
        workspace = self.journey.env.workspace
        write_release_record(workspace, day)
        return workspace

    def launch_prompt(self, day: str) -> tuple[Path, str, reports.StepResult]:
        workspace = self.put_record(day)
        prompts: list[str] = []
        result = reports.StepResult(step=STEP.id, kind=STEP.kind, host="claude")

        def launch(*args, **kwargs):
            prompts.append(args[2])
            args[6].append(approval_tests.host_run("claude", "preview", final="", calls=[], exit_code=1))
            return args[6][-1]

        with patch.object(Journey, "_launch", side_effect=launch), patch.object(ws, "read_feature", return_value=None):
            self.journey.run_agent_step(STEP, 4, "claude", result)
        self.assertEqual(len(prompts), 1)
        return workspace, prompts[0], result

    def test_a_run_dated_2026_10_12_places_the_report_and_names_the_folder_for_that_day(self):
        workspace, prompt, _result = self.launch_prompt(LIVE_DAY)
        report = workspace / "knowledge/intake/pending/2026-10-12-release-incident/report.md"
        self.assertIn("Reported by support on 2026-10-12.", report.read_text(encoding="utf-8"))
        self.assertIn("`knowledge/intake/pending/2026-10-12-release-incident`", prompt)
        self.assertEqual([path.name for path in (workspace / "knowledge/intake/pending").iterdir()], ["2026-10-12-release-incident"])

    def test_a_run_on_the_fixture_record_places_the_fixture_report_and_names_the_fixture_folder(self):
        workspace, prompt, _result = self.launch_prompt(FIXTURE_DAY)
        placed = workspace / "knowledge/intake/pending/2026-10-09-release-incident/report.md"
        self.assertEqual(placed.read_bytes(), REPORT.read_bytes())
        self.assertIn("`knowledge/intake/pending/2026-10-09-release-incident`", prompt)

    def test_a_step_without_a_release_record_fails_with_the_reason(self):
        self.journey.env.workspace.mkdir(parents=True, exist_ok=True)
        result = reports.StepResult(step=STEP.id, kind=STEP.kind, host="claude")
        with patch.object(Journey, "_launch") as launch, patch.object(ws, "read_feature", return_value=None):
            self.journey.run_agent_step(STEP, 4, "claude", result)
        launch.assert_not_called()
        self.assertEqual(result.status, "failed")
        self.assertIn("REL-002", result.reason)

    def approved_expectations(self, day: str) -> dict:
        """The expectations the runner binds an approval to, for the incident step as if it were gated."""

        self.put_record(day)
        gated = dataclasses.replace(STEP, roles=("release",))
        captured: list[dict] = []
        result = reports.StepResult(step=STEP.id, kind=STEP.kind, host="codex")
        with patch.object(ws, "fetch_preview", return_value={}), patch.object(
            runner, "check_preview", side_effect=lambda preview, preview_id, expected: captured.append(expected)
        ):
            self.journey._approve_in_board(gated, 5, "codex", PREVIEW, result)
        return captured[0]

    def test_the_permitted_move_and_paths_follow_the_day_of_the_release(self):
        expected = self.approved_expectations(LIVE_DAY)
        self.assertEqual(
            expected["permitted_moves"],
            [{"source": "knowledge/intake/pending/2026-10-12-release-incident", "destination": "knowledge/intake/processed/2026-10-12-release-incident"}],
        )
        self.assertIn("knowledge/intake/processed/2026-10-12-release-incident/MANIFEST.md", expected["permitted_paths"])
        self.assertFalse([path for path in expected["permitted_paths"] if "2026-10-09" in path])

    def test_with_the_fixture_record_the_permitted_move_and_paths_are_the_recorded_ones(self):
        expected = self.approved_expectations(FIXTURE_DAY)
        self.assertEqual(
            expected["permitted_moves"],
            [{"source": "knowledge/intake/pending/2026-10-09-release-incident", "destination": "knowledge/intake/processed/2026-10-09-release-incident"}],
        )
        self.assertEqual(expected["permitted_paths"], sorted(set(ws.fixture_files(["ingest-incident"])) | {"knowledge/wiki/status-board.md", "knowledge/wiki/index.md", "knowledge/wiki/log.md"}))


class IntakeCheckTests(unittest.TestCase):
    """The ``intake_moved`` check looks for the manifest in the folder named for the day of REL-002."""

    def workspace(self) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / "knowledge/wiki").mkdir(parents=True)
        (root / "knowledge/wiki/status-board.md").write_text(STATUS_BOARD.read_text(encoding="utf-8"), encoding="utf-8")
        return root

    def intake_moved(self, root: Path) -> reports.Check:
        journey = Journey.__new__(Journey)
        journey.env = SimpleNamespace(workspace=root)
        result = reports.StepResult(step=STEP.id, kind=STEP.kind, host="claude")
        journey._step_specific_checks(STEP, result, None, ws.read_feature(root))
        return next(check for check in result.checks if check.name == "intake_moved")

    def test_the_check_holds_on_the_fixture_state(self):
        root = self.workspace()
        ws.seed_state(root, "ingest-incident")
        self.assertTrue(self.intake_moved(root).ok)

    def test_a_release_dated_2026_10_12_needs_the_folder_of_that_day(self):
        root = self.workspace()
        ws.seed_state(root, "ingest-incident")
        write_release_record(root, LIVE_DAY)
        self.assertFalse(self.intake_moved(root).ok, "the manifest is in the folder of the recorded day")
        (root / "knowledge/intake/processed/2026-10-09-release-incident").rename(root / "knowledge/intake/processed/2026-10-12-release-incident")
        check = self.intake_moved(root)
        self.assertTrue(check.ok, check.detail)
        self.assertIn("2026-10-12-release-incident", check.detail)
        ws.place_pending_input(root, "ingest-incident", None, LIVE_DAY)
        self.assertFalse(self.intake_moved(root).ok, "the report is still pending")


if __name__ == "__main__":
    unittest.main()
