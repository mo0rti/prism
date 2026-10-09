"""The journey fixtures of scripts/e2e are valid states of the real board: lint, preflight and the connected skills accept them."""

from __future__ import annotations

from datetime import date
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from uuid import uuid4

E2E_DIR = Path(__file__).resolve().parents[1] / "scripts" / "e2e"
sys.dont_write_bytecode = True
sys.path.insert(0, str(E2E_DIR))

from prism_e2e import config, workspace as e2e  # noqa: E402

from prism_cli.board_service import BoardService  # noqa: E402
from prism_cli.wiki_lint import lint_wiki  # noqa: E402
from prism_cli.wiki_transitions import build_transition_preflight  # noqa: E402
from prism_cli.workflow_install import apply_install, plan_install  # noqa: E402
from tests.board_approval import apply_preview, human_with_roles  # noqa: E402
from tests.core_workflow_fixture import create_core_workflow_fixture  # noqa: E402
from tests import real_temp  # noqa: F401

TODAY = date(2026, 10, 5)
FIXTURE_SETS = {"default": None, "api-work": config.API_WORK_FIXTURES_DIR}
FEATURE = "knowledge/wiki/features/F-001-review-summary-export.md"
CONTRACT = "knowledge/wiki/api-contracts/F-001.md"


class JourneyFixtureTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = create_core_workflow_fixture(Path(temporary.name) / "ws")
        shutil.rmtree(self.root / "knowledge" / "intake" / "pending")
        (self.root / "knowledge" / "intake" / "pending").mkdir()
        self.assertEqual("applied", apply_install(self.root, plan_install(self.root, name="Doc review", apps=["backend"]))["status"])

    def seed(self, step: str | None, fixture_set: Path | None) -> None:
        e2e.seed_state(self.root, step, fixture_set)

    def start(self) -> None:
        self.service = BoardService(self.root).start()
        self.addCleanup(self.service.close)
        self.agent = self.service.authenticate(self.service.create_participant("Fixture agent", "agent", True)["token"])
        self.human = human_with_roles(self.service, "Fixture owner")  # every role, in a board session

    def proposal(self, step: str, fixture_set: Path | None) -> list[dict[str, str]]:
        """What the step's agent proposes: the files its fixture folders write, byte for byte (no newline translation)."""

        paths = {
            relative: path
            for root in [config.FIXTURES_DIR / step, *([fixture_set / step] if fixture_set else [])]
            if root.is_dir()
            for relative, path in ((p.relative_to(root).as_posix(), p) for p in sorted(root.rglob("*")) if p.is_file())
        }
        return [{"path": relative, "content": path.read_bytes().decode("utf-8")} for relative, path in sorted(paths.items())]

    def test_every_state_of_both_sets_lints_clean_apart_from_the_open_dev_question_after_the_handoff(self) -> None:
        for name, fixture_set in FIXTURE_SETS.items():
            for step in config.STEPS[:-1]:
                with self.subTest(fixture_set=name, step=step.id):
                    self.seed(step.id, fixture_set)
                    result = lint_wiki(self.root, today=TODAY)
                    codes = sorted({item.code for item in result.diagnostics if item.severity == "error"})
                    self.assertEqual(sorted(e2e.ALLOWED_LINT_CODES.get(step.id, frozenset()) & set(codes)), codes, f"{step.id}: {codes}")

    def test_the_api_work_handoff_is_a_valid_design_handoff_proposal_and_dev_start_then_passes(self) -> None:
        self.seed("design-clarify", config.API_WORK_FIXTURES_DIR)
        self.start()
        changes = self.proposal("design-handoff", config.API_WORK_FIXTURES_DIR)
        self.assertIn(CONTRACT, [item["path"] for item in changes])
        preview = self.service.preview_skill(self.agent, "design-handoff", changes, None, _revisions(self.service, self.agent, "design-handoff", changes))
        self.assertEqual(("design-handoff", "ready", True), (preview["action"], preview["classification"], preview["applicable"]), preview["checks"])
        self.assertEqual("applied", apply_preview(self.service, self.agent, preview, str(uuid4()), approver=self.human)["state"])

        transition = build_transition_preflight(self.root, "F-001", action="dev-start")["facts"]["transition"]
        self.assertEqual("pass", next(item for item in transition["checks"] if item["code"] == "api-contract")["status"])

    def test_the_default_handoff_is_a_valid_proposal_without_a_contract(self) -> None:
        self.seed("design-clarify", None)
        self.start()
        changes = self.proposal("design-handoff", None)
        self.assertNotIn(CONTRACT, [item["path"] for item in changes])
        preview = self.service.preview_skill(self.agent, "design-handoff", changes, None, _revisions(self.service, self.agent, "design-handoff", changes))
        self.assertEqual(("ready", True), (preview["classification"], preview["applicable"]), preview["checks"])

    def test_the_api_work_dev_done_proposal_marks_the_contract_implemented(self) -> None:
        self.seed("dev-start", config.API_WORK_FIXTURES_DIR)
        self.start()
        changes = self.proposal("dev-done", config.API_WORK_FIXTURES_DIR)
        self.assertEqual(
            ["knowledge/wiki/api-contracts/F-001.md", "knowledge/wiki/app-requirements/F-001-backend.md", FEATURE],
            sorted(item["path"] for item in changes),
        )
        preview = self.service.preview_skill(self.agent, "dev-done", changes, None, _revisions(self.service, self.agent, "dev-done", changes))
        self.assertEqual(("dev-done", "ready", True), (preview["action"], preview["classification"], preview["applicable"]), preview["checks"])

    def test_the_api_work_dev_start_state_passes_the_dev_start_preflight(self) -> None:
        for name, fixture_set in FIXTURE_SETS.items():
            with self.subTest(fixture_set=name):
                self.seed("dev-clarify", fixture_set)
                transition = build_transition_preflight(self.root, "F-001", action="dev-start")["facts"]["transition"]
                self.assertEqual("ready", transition["classification"], transition["checks"])
                self.assertEqual("pass", next(item for item in transition["checks"] if item["code"] == "api-contract")["status"])


    def test_the_qa_pass_and_release_done_proposals_of_both_sets_are_valid_and_the_reopen_route_follows(self) -> None:
        for name, fixture_set in FIXTURE_SETS.items():
            with self.subTest(fixture_set=name):
                self.seed("dev-done", fixture_set)
                self.start()
                self.assertEqual(("qa-pass", "ready"), self.preview_of("qa-pass", fixture_set)[:2])
                self.apply_proposal("qa-pass", fixture_set)
                preview = self.preview_of("release-done", fixture_set)
                self.assertEqual(("release-done", "ready"), preview[:2], preview[2])
                self.apply_proposal("release-done", fixture_set)
                self.assertEqual(["REL-001.md"], sorted(path.name for path in (self.root / "knowledge/wiki/releases").glob("REL-*.md")))
                transition = build_transition_preflight(self.root, "F-001", action="reopen-dev")["facts"]["transition"]
                self.assertEqual(("ready", "in-dev", "dev"), (transition["classification"], transition["target_status"], transition["target_owner"]))
                self.service.close()

    def stamped(self, step: str, fixture_set: Path | None) -> list[dict[str, str]]:
        """The proposal of a step as the agent writes it: the fixture's recorded day and operation become today and `pending`."""

        recorded_day, recorded_operation = "2026-10-09", "6f1c2d84-5b0e-4c7a-9a3d-0e2b7f19a5c3"
        return [
            {"path": item["path"], "content": item["content"].replace(recorded_day, date.today().isoformat()).replace(recorded_operation, "pending")}
            for item in self.proposal(step, fixture_set)
        ]

    def preview_of(self, step: str, fixture_set: Path | None) -> tuple[str, str, object]:
        changes = self.stamped(step, fixture_set)
        preview = self.service.preview_skill(self.agent, step, changes, None, _revisions(self.service, self.agent, step, changes))
        return preview["action"], preview["classification"], preview["checks"]

    def apply_proposal(self, step: str, fixture_set: Path | None) -> None:
        changes = self.stamped(step, fixture_set)
        preview = self.service.preview_skill(self.agent, step, changes, None, _revisions(self.service, self.agent, step, changes))
        self.assertEqual("applied", apply_preview(self.service, self.agent, preview, str(uuid4()), approver=self.human)["state"])


def _revisions(service: BoardService, actor: object, skill: str, changes: list[dict[str, str]]) -> dict[str, str]:
    from tests.test_board_service import _read_revisions

    return _read_revisions(service, actor, skill, changes)


if __name__ == "__main__":
    unittest.main()
