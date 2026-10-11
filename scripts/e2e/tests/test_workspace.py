"""Workspace helpers that need no product, host or network: fixtures, seeding, page parsing."""

import json
from pathlib import Path
import re
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prism_e2e import config, workspace as ws  # noqa: E402
from prism_e2e.procs import ProcessResult  # noqa: E402
from prism_e2e.tokens import TokenRegistry  # noqa: E402

INDEX = """# Feature Status Board

This file is maintained by the AI agent. Do not edit directly.

| ID | Feature | Status | Owner | Board Review | Design tracks | App stages | Open bugs |
|----|---------|--------|-------|--------------|---------------|------------|-----------|
| F-009 | Old row | raw | po | not-needed | — | — | — |
"""

PAGE = """---
id: F-001
title: Review summary export
status: ready-for-dev
owner: dev
apps:
- backend
advisory-review: not-needed
---

## Summary
Text.

## Open questions
| # | Question | Owner | Status |
|---|----------|-------|--------|
| 1 | First? | po | resolved: yes |
| 2 | Second | designer | open |

## App scope
- **backend**: x
"""


class PageParsingTests(unittest.TestCase):
    def test_front_matter_keeps_flat_values_and_ignores_list_items(self):
        front = ws.parse_front_matter(PAGE)
        self.assertEqual(front["status"], "ready-for-dev")
        self.assertEqual(front["owner"], "dev")
        self.assertEqual(front["advisory-review"], "not-needed")
        self.assertNotIn("- backend", front)

    def test_questions_come_only_from_the_open_questions_table(self):
        questions = ws.parse_questions(PAGE)
        self.assertEqual([q.number for q in questions], ["1", "2"])
        self.assertEqual([q.is_open for q in questions], [False, True])
        self.assertEqual(questions[1].owner, "designer")

    def test_status_with_a_resolution_text_is_not_open(self):
        question = ws.Question("1", "Q", "po", "resolved: open items remain elsewhere")
        self.assertFalse(question.is_open)

    def test_design_tracks_are_read_from_the_front_matter(self):
        tracks = "design-tracks:\n  ui: not-applicable\n  technical: done\n  ui-reason: No app in scope has a UI.\ndesign-reaffirm: []\n"
        page = PAGE.replace("---\n\n", tracks + "---\n\n", 1)
        self.assertEqual({"ui": "not-applicable", "technical": "done"}, ws.design_tracks(page))
        self.assertEqual({}, ws.design_tracks(PAGE))


class StatusBoardTests(unittest.TestCase):
    def test_rewrite_status_board_replaces_the_feature_rows_and_keeps_everything_else(self):
        row = ws.feature_row(ws.parse_front_matter(PAGE), PAGE)
        self.assertEqual(row, "| F-001 | Review summary export | ready-for-dev | dev | not-needed | — | — | — |")
        rewritten = ws.rewrite_status_board(INDEX, row)
        self.assertIn(row, rewritten)
        self.assertNotIn("F-009", rewritten)
        self.assertIn("This file is maintained by the AI agent.", rewritten)
        self.assertEqual(rewritten.count("|----|"), 1)

    def test_rewrite_status_board_without_a_row_leaves_an_empty_table(self):
        rewritten = ws.rewrite_status_board(INDEX, None)
        self.assertNotIn("F-009", rewritten)
        self.assertIn("|----|---------|", rewritten)


class OperationsTableTests(unittest.TestCase):
    RECORD = (
        "---\nid: REL-00{n}\n---\n\n## Delivery\n| Item | App | Target | Version | Attempt | Outcome | Evidence | Basis |\n|---|---|---|---|---|---|---|---|\n"
        "| F-001 | backend | production | `v` | release-1 | {outcome} | deployment: https://x.example | checked |\n\n## Notes\nNone.\n"
    )

    def test_a_board_without_the_table_gains_it_and_one_with_it_has_its_rows_replaced(self):
        rows = ["| backend | production | F-001 | REL-001 | released | — | — |"]
        added = ws.rewrite_operations(INDEX, rows)
        self.assertIn("## Operations", added)
        self.assertIn(rows[0], added)
        replaced = ws.rewrite_operations(added, ["| worker | production | — | REL-002 | failed | — | — |"])
        self.assertNotIn("| backend |", replaced)
        self.assertIn("| App | Delivery target |", replaced)
        self.assertEqual(replaced.count("|-----|"), 1)
        self.assertEqual(INDEX, ws.rewrite_operations(INDEX, []))

    def test_the_rows_follow_the_released_stages_and_the_latest_record_of_each_app(self):
        with tempfile.TemporaryDirectory() as folder:
            workspace = Path(folder)
            records = workspace / "knowledge/wiki/releases"
            records.mkdir(parents=True)
            (records / "REL-001.md").write_text(self.RECORD.format(n=1, outcome="released"), encoding="utf-8")
            (records / "REL-002.md").write_text(self.RECORD.format(n=2, outcome="rolled-back"), encoding="utf-8")
            (records / "_FORMAT.md").write_text("format", encoding="utf-8")
            self.assertEqual(["| backend | production | F-001 | REL-002 | rolled-back | — | — |"], ws.operations_rows(workspace, "backend: released"))
            self.assertEqual(["| backend | production | — | REL-002 | rolled-back | — | — |"], ws.operations_rows(workspace, "backend: ready-for-release"))
            self.assertEqual([], ws.operations_rows(workspace / "empty", "—"))


class FixtureTests(unittest.TestCase):
    def feature_status_after(self, step):
        files = ws.fixture_files(ws.fixture_steps_through(step))
        page = next(path for relative, path in files.items() if relative.startswith("knowledge/wiki/features/F-001-"))
        front = ws.parse_front_matter(page.read_text(encoding="utf-8"))
        return front["status"], front["owner"]

    def test_each_fixture_state_matches_the_step_table(self):
        for step in config.STEPS[:-1]:
            with self.subTest(step=step.id):
                self.assertEqual(self.feature_status_after(step.id), (step.status, step.owner))

    def test_the_design_tracks_follow_the_step(self):
        expected = {
            "po-handoff": {},
            "design-start": {"ui": "not-applicable", "technical": "pending"},
            "design-clarify": {"ui": "not-applicable", "technical": "pending"},
            "tech-design-done": {"ui": "not-applicable", "technical": "done"},
            "design-handoff": {"ui": "not-applicable", "technical": "done"},
            "dev-clarify": {"ui": "not-applicable", "technical": "done"},
            "dev-start": {"ui": "not-applicable", "technical": "done"},
            "dev-done": {"ui": "not-applicable", "technical": "done"},
        }
        for step, tracks in expected.items():
            with self.subTest(step=step):
                files = ws.fixture_files(ws.fixture_steps_through(step))
                page = next(path for relative, path in files.items() if relative.startswith("knowledge/wiki/features/F-001-"))
                self.assertEqual(tracks, ws.design_tracks(page.read_text(encoding="utf-8")))
                has_technical = any(relative.startswith("knowledge/wiki/technical-design/") for relative in files)
                self.assertEqual(tracks.get("technical") == "done", has_technical)

    def test_the_baseline_has_no_fixture_files(self):
        self.assertEqual(ws.fixture_files(ws.fixture_steps_through(None)), {})

    def test_a_later_step_replaces_an_earlier_steps_file(self):
        early = ws.fixture_files(ws.fixture_steps_through("po-intake"))
        late = ws.fixture_files(ws.fixture_steps_through("dev-done"))
        page = "knowledge/wiki/features/F-001-review-summary-export.md"
        self.assertNotEqual(early[page], late[page])
        self.assertIn("knowledge/wiki/app-requirements/F-001-backend.md", late)
        self.assertNotIn("knowledge/wiki/app-requirements/F-001-backend.md", early)

    def test_the_question_table_in_each_state_matches_the_journey(self):
        expectations = {
            "po-intake": (5, ["1", "2", "3", "4", "5"]),
            "ask": (6, ["1", "2", "3", "4", "5", "6"]),
            "po-clarify": (6, ["4", "5"]),
            "design-clarify": (6, ["5"]),
            "dev-clarify": (6, []),
        }
        for step, (count, open_numbers) in expectations.items():
            with self.subTest(step=step):
                files = ws.fixture_files(ws.fixture_steps_through(step))
                page = files["knowledge/wiki/features/F-001-review-summary-export.md"]
                questions = ws.parse_questions(page.read_text(encoding="utf-8"))
                self.assertEqual(len(questions), count)
                self.assertEqual([q.number for q in questions if q.is_open], open_numbers)

    def test_seed_state_rebuilds_the_files_and_the_index_row(self):
        with tempfile.TemporaryDirectory() as folder:
            workspace = Path(folder)
            (workspace / "knowledge/wiki/features").mkdir(parents=True)
            (workspace / "knowledge/wiki/features/_FORMAT.md").write_text("format", encoding="utf-8")
            (workspace / "knowledge/wiki/features/F-007-stale.md").write_text("stale", encoding="utf-8")
            (workspace / "knowledge/wiki/status-board.md").write_text(INDEX, encoding="utf-8")
            written = ws.seed_state(workspace, "po-specify")
            self.assertTrue((workspace / "knowledge/wiki/features/_FORMAT.md").is_file(), "the installed template stays")
            self.assertFalse((workspace / "knowledge/wiki/features/F-007-stale.md").exists(), "a stale journey page is removed")
            self.assertIn("knowledge/wiki/personas/legal-operations-reviewer.md", written)
            feature = ws.read_feature(workspace)
            self.assertEqual((feature.status, feature.owner, feature.board_status, feature.board_owner), ("specified", "po", "specified", "po"))
            self.assertEqual(len(feature.questions), 6)
            # Seeding the baseline clears the journey again.
            ws.seed_state(workspace, None)
            self.assertIsNone(ws.read_feature(workspace))
            self.assertNotIn("F-001", (workspace / "knowledge/wiki/status-board.md").read_text(encoding="utf-8"))

    def test_place_pending_brief_copies_the_intake_brief(self):
        with tempfile.TemporaryDirectory() as folder:
            ws.place_pending_brief(Path(folder))
            brief = (Path(folder) / ws.PENDING_INTAKE / "brief.md").read_text(encoding="utf-8")
            self.assertIn("# PO Brief - Review summary export", brief)


FEATURE_FILE = "knowledge/wiki/features/F-001-review-summary-export.md"
CONTRACT_FILE = "knowledge/wiki/api-contracts/F-001.md"
REQUIREMENT_FILE = "knowledge/wiki/app-requirements/F-001-backend.md"
API_SET = config.API_WORK_FIXTURES_DIR
AFTER_SPECIFY = list(config.STEP_IDS[config.STEP_IDS.index("po-specify"):-1])  # po-specify through ingest-incident; feature-reopen is the last step


def text_of(files, relative):
    return files[relative].read_text(encoding="utf-8")


class ApiSurfaceTests(unittest.TestCase):
    def test_api_work_is_declared_by_any_text_other_than_an_empty_section_or_a_statement_of_none(self):
        def page(section):
            return f"## Summary\nText.\n\n## API surface\n{section}\n## Board review summary\nNot needed.\n"

        for section in ("", "None.", "none", "No API changes identified.", "N/A", "Not applicable."):
            with self.subTest(section=section):
                self.assertFalse(ws.declares_api_work(page(section)))
        self.assertTrue(ws.declares_api_work(page("A new endpoint `GET /api/v1/reviews`.\n")))
        self.assertFalse(ws.declares_api_work("## Summary\nText.\n"), "no section declares nothing")
        self.assertEqual(ws.api_surface_section(page("One line.\n")).strip(), "One line.")


class FixtureSetTests(unittest.TestCase):
    def files(self, step, fixture_set=API_SET):
        return ws.fixture_files(ws.fixture_steps_through(step), fixture_set)

    def test_the_default_set_declares_no_api_work_and_holds_no_contract(self):
        for step in AFTER_SPECIFY:
            with self.subTest(step=step):
                files = self.files(step, None)
                self.assertFalse(ws.declares_api_work(text_of(files, FEATURE_FILE)))
                self.assertNotIn(CONTRACT_FILE, files)

    def test_the_api_work_set_matches_the_step_table_and_declares_api_work_from_po_specify(self):
        for step in config.STEPS[:-1]:
            with self.subTest(step=step.id):
                files = self.files(step.id)
                front = ws.parse_front_matter(text_of(files, FEATURE_FILE))
                self.assertEqual((front["status"], front["owner"]), (step.status, step.owner))
                self.assertEqual(ws.declares_api_work(text_of(files, FEATURE_FILE)), step.id in AFTER_SPECIFY)

    def test_the_steps_before_po_specify_are_the_default_states(self):
        for step in ("po-intake", "ask", "po-clarify"):
            with self.subTest(step=step):
                self.assertEqual(self.files(step), self.files(step, None))

    def test_the_question_tables_of_the_api_work_set_equal_the_default_tables(self):
        for step in AFTER_SPECIFY:
            with self.subTest(step=step):
                api = ws.parse_questions(text_of(self.files(step), FEATURE_FILE))
                default = ws.parse_questions(text_of(self.files(step, None), FEATURE_FILE))
                self.assertEqual([(q.number, q.text, q.owner, q.status) for q in api], [(q.number, q.text, q.owner, q.status) for q in default])

    def test_the_states_after_design_handoff_hold_the_agreed_contract_and_the_requirement_that_links_it(self):
        agreed = {"tech-design-done", "design-handoff", "dev-clarify", "dev-start", "qa-fail", "bug-start", "bug-fixed"}
        steps = [step.id for step in config.STEPS[config.STEP_IDS.index("tech-design-done"):-1]]
        for step in steps:
            with self.subTest(step=step):
                files = self.files(step)
                contract = text_of(files, CONTRACT_FILE)
                front = ws.parse_front_matter(contract)
                self.assertEqual((front["feature-id"], front["version"]), ("F-001", "1"))
                self.assertEqual(front["status"], "agreed" if step in agreed else "implemented")
                if step == "tech-design-done":
                    continue  # the requirement page is generated by the handoff
                for heading in ("## Endpoints", "## Data models", "## Authentication requirements", "## Notes"):
                    self.assertIn(heading, contract)
                requirement = text_of(files, REQUIREMENT_FILE)
                reference = requirement.split("## API contract reference", 1)[1].split("\n## ", 1)[0]
                self.assertIn("(../api-contracts/F-001.md)", reference)
                self.assertNotIn("no API contract page", requirement)

    def test_no_contract_exists_before_the_technical_design_is_settled(self):
        for step in ("po-specify", "po-handoff", "design-start", "design-clarify"):
            with self.subTest(step=step):
                self.assertNotIn(CONTRACT_FILE, self.files(step))

    def test_every_contract_endpoint_is_named_by_the_api_surface(self):
        files = self.files("design-handoff")
        surface = ws.api_surface_section(text_of(files, FEATURE_FILE))
        endpoints = re.findall(r"`((?:GET|POST|PUT|PATCH|DELETE) /[^`]+)`", text_of(files, CONTRACT_FILE).split("## Data models")[0])
        self.assertTrue(endpoints)
        for endpoint in endpoints:
            self.assertIn(endpoint, surface)

    def test_an_overlay_file_replaces_the_default_file_of_the_same_step_and_path(self):
        default = ws.fixture_files(ws.fixture_steps_through("design-handoff"), None)
        api = ws.fixture_files(ws.fixture_steps_through("design-handoff"), API_SET)
        self.assertNotEqual(default[REQUIREMENT_FILE], api[REQUIREMENT_FILE])
        self.assertEqual(api[REQUIREMENT_FILE].parts[-5], "design-handoff")
        self.assertTrue(str(api[REQUIREMENT_FILE]).startswith(str(API_SET)))
        self.assertTrue(str(api["knowledge/wiki/personas/legal-operations-reviewer.md"]).startswith(str(config.FIXTURES_DIR)), "an unchanged file comes from the default set")

    def test_seed_state_with_the_set_writes_the_contract_and_the_baseline_clears_it(self):
        with tempfile.TemporaryDirectory() as folder:
            workspace = Path(folder)
            (workspace / "knowledge/wiki").mkdir(parents=True)
            (workspace / "knowledge/wiki/status-board.md").write_text(INDEX, encoding="utf-8")
            written = ws.seed_state(workspace, "design-handoff", API_SET)
            self.assertIn(CONTRACT_FILE, written)
            self.assertEqual(ws.read_api_contract(workspace)["status"], "agreed")
            feature = ws.read_feature(workspace)
            self.assertEqual((feature.status, feature.owner, feature.board_status, feature.board_owner), ("ready-for-dev", "dev", "ready-for-dev", "dev"))
            ws.seed_state(workspace, "design-handoff")
            self.assertIsNone(ws.read_api_contract(workspace), "the default set leaves no contract page")
            ws.seed_state(workspace, "dev-done", API_SET)
            self.assertEqual(ws.read_api_contract(workspace)["status"], "implemented")
            ws.seed_state(workspace, None, API_SET)
            self.assertIsNone(ws.read_api_contract(workspace))

    def test_the_pending_brief_comes_from_the_set_when_it_holds_one_and_otherwise_from_the_default(self):
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as set_folder:
            brief = Path(set_folder) / "po-intake" / ws.PROCESSED_BRIEF
            brief.parent.mkdir(parents=True)
            brief.write_text("# PO Brief - Another feature\n", encoding="utf-8")
            ws.place_pending_brief(Path(folder), Path(set_folder))
            self.assertIn("Another feature", (Path(folder) / ws.PENDING_INTAKE / "brief.md").read_text(encoding="utf-8"))
            ws.place_pending_brief(Path(folder), API_SET)
            self.assertIn("Review summary export", (Path(folder) / ws.PENDING_INTAKE / "brief.md").read_text(encoding="utf-8"))


class AppStagesCellTests(unittest.TestCase):
    PAGE = (
        "---\nid: F-001\nstatus: {status}\napps: [backend, worker]\n---\n\n"
        "## Delivery evidence\n| App | Artifact | Contract | Implementation | Tests | Basis |\n|---|---|---|---|---|---|\n{delivery}\n"
        "## QA verification\n| Row | Criteria | Method | Artifact | Environment | Attempt | Result | Evidence | Basis |\n|---|---|---|---|---|---|---|---|---|\n{qa}\n"
        "## Release\n| App | Target | Version | Attempt | Outcome | Record | Basis |\n|---|---|---|---|---|---|---|\n{release}\n"
    )

    def cell(self, status, delivery="", qa="", release=""):
        text = self.PAGE.format(status=status, delivery=delivery, qa=qa, release=release)
        return ws.app_stages_cell(ws.parse_front_matter(text), text)

    def test_each_app_takes_the_stage_its_rows_show(self):
        delivery = "| backend | `a` | none | x | y | checked |\n| worker | `a` | none | x | y | checked |"
        self.assertEqual(self.cell("in-dev"), "backend: in-dev; worker: in-dev")
        self.assertEqual(self.cell("in-dev", delivery="| backend | `a` | none | x | y | checked |"), "backend: ready-for-qa; worker: in-dev")
        qa = "| backend | AC-1 | automated | `a` | ci | qa-1 | pass | e | checked |"
        self.assertEqual(self.cell("in-qa", delivery, qa), "backend: in-qa; worker: ready-for-qa")
        pending = "| backend | \u2014 | `a` | release-1 | pending | \u2014 | \u2014 |"
        self.assertEqual(self.cell("in-qa", delivery, qa, pending), "backend: ready-for-release; worker: ready-for-qa")
        released = "| backend | production | `a` | release-1 | released | [REL-001](../releases/REL-001.md) | checked |"
        self.assertEqual(self.cell("in-qa", delivery, qa, released), "backend: released; worker: ready-for-qa")

    def test_a_feature_before_development_has_no_stages(self):
        self.assertEqual(self.cell("specified"), "\u2014")


class GrantTests(unittest.TestCase):
    TOKEN = "T" * 40

    def issue(self, kind, roles=()):
        captured = {}

        def fake_run(command, **kwargs):
            captured["command"] = list(command)
            return ProcessResult(0, json.dumps({"token": self.TOKEN, "participant": {"participant_id": "pid-1"}}), "", 0.1, False)

        registry, log = TokenRegistry(), []
        with patch.object(ws, "run_captured", fake_run):
            participant = ws.issue_grant(SimpleNamespace(prism=Path("prism"), workspace=Path(".")), registry, "label", "Name", kind, log, roles)
        return participant, captured["command"], registry, log

    def test_a_human_grant_is_issued_with_exactly_its_roles(self):
        participant, command, registry, log = self.issue("human", ("tech-lead",))
        self.assertEqual(participant, "pid-1")
        self.assertEqual(command[command.index("--role") + 1], "tech-lead")
        self.assertIn("--write", command)
        self.assertEqual(registry.get("label"), self.TOKEN)
        self.assertIn("--role tech-lead", log[0])
        self.assertNotIn(self.TOKEN, "\n".join(log))

    def test_several_roles_are_one_comma_separated_value_and_an_agent_grant_has_none(self):
        _participant, command, _registry, _log = self.issue("human", ("po", "qa"))
        self.assertEqual(command[command.index("--role") + 1], "po,qa")
        _participant, command, _registry, log = self.issue("agent")
        self.assertNotIn("--role", command)
        self.assertNotIn("--role", log[0])


class LintResultTests(unittest.TestCase):
    def test_allowed_codes_are_tolerated_and_others_are_not(self):
        lint = ws.LintResult(1, 0, 3, ["unresolved-open-questions"])
        self.assertFalse(lint.unexpected(ws.ALLOWED_LINT_CODES["design-handoff"]))
        self.assertTrue(lint.unexpected())
        self.assertTrue(ws.LintResult(2, 0, 3, ["unresolved-open-questions", "broken-link"]).unexpected(ws.ALLOWED_LINT_CODES["design-handoff"]))
        self.assertTrue(ws.LintResult(-1, -1, 1).unexpected())
        self.assertFalse(ws.LintResult(0, 2, 0).unexpected())

    def test_only_the_design_handoff_may_leave_an_error_behind(self):
        self.assertEqual(set(ws.ALLOWED_LINT_CODES), {"design-handoff"})


STATUS_BOARD_TEMPLATE = (config.REPO_ROOT / "template" / "knowledge" / "wiki" / "status-board.md").read_text(encoding="utf-8")


def bug_text(bug_id="BUG-001", status="open", owner="dev", apps="[backend]", feature="F-001", blocking="true", title="Summary lacks a count"):
    return (
        f"---\nid: {bug_id}\ntitle: {title}\nstatus: {status}\nowner: {owner}\nseverity: high\nblocking: {blocking}\napps: {apps}\n"
        f"feature: {feature}\nfound-in: commit:3f9c2ab\nenvironment: ci\nsources: []\n---\n\n## Summary\nText.\n"
    )


def incident_text(incident_id="INC-001", status="open", apps="[backend]"):
    return f"---\nid: {incident_id}\ntitle: Blank page\ndate: 2026-10-09\nstatus: {status}\nseverity: high\napps: {apps}\nreleases: [REL-002]\nfollow-ups: []\n---\n\n## Impact\nText.\n"


class BugAndIncidentViewTests(unittest.TestCase):
    def workspace(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / "knowledge/wiki/bugs").mkdir(parents=True)
        (root / "knowledge/wiki/incidents").mkdir(parents=True)
        (root / "knowledge/wiki/status-board.md").write_text(STATUS_BOARD_TEMPLATE, encoding="utf-8")
        return root

    def put(self, root, folder, name, text):
        (root / "knowledge/wiki" / folder / name).write_text(text, encoding="utf-8")

    def test_the_bugs_table_lists_the_bugs_that_are_not_released_or_closed_in_number_order(self):
        root = self.workspace()
        self.put(root, "bugs", "BUG-010-late.md", bug_text("BUG-010", "fixed", "qa", title="Pipe | in title"))
        self.put(root, "bugs", "BUG-002-early.md", bug_text("BUG-002", "in-fix", blocking="false"))
        self.put(root, "bugs", "BUG-003-done.md", bug_text("BUG-003", "released", "none"))
        self.put(root, "bugs", "BUG-004-closed.md", bug_text("BUG-004", "closed", "none"))
        rows = ws.bug_rows(root)
        self.assertEqual([row["id"] for row in rows], ["BUG-002", "BUG-010"])
        self.assertEqual(ws.format_bug_row(rows[0]), "| BUG-002 | Summary lacks a count | in-fix | dev | backend | F-001 | no |")
        self.assertIn("Pipe &#124; in title", ws.format_bug_row(rows[1]))
        self.assertEqual(ws.open_bugs_cell(root), "BUG-002, BUG-010")
        self.assertEqual(ws.open_bugs_cell(root, "F-002"), "—")

    def test_rewriting_the_bugs_table_leaves_the_operations_table_and_the_feature_table_alone(self):
        board = ws.rewrite_operations(ws.rewrite_status_board(STATUS_BOARD_TEMPLATE, "| F-001 | T | raw | po | not-needed | — | — | — |"), ["| backend | production | F-001 | REL-001 | released | — | — |"])
        rewritten = ws.rewrite_bugs(board, ["| BUG-001 | B | open | dev | backend | F-001 | yes |"])
        self.assertIn("| BUG-001 | B | open | dev | backend | F-001 | yes |", rewritten)
        self.assertIn("| backend | production | F-001 | REL-001 | released | — | — |", rewritten)
        self.assertIn("| F-001 | T | raw |", rewritten)
        self.assertEqual(rewritten.count("|----|-----|--------|-------|------|---------|----------|"), 1)
        self.assertEqual(rewritten.count("| App | Delivery target |"), 1, "the Operations header survives")
        cleared = ws.rewrite_bugs(rewritten, [])
        self.assertNotIn("BUG-001", cleared)
        self.assertIn("| backend | production | F-001 | REL-001 |", cleared)

    def test_an_app_with_an_open_bug_or_incident_has_an_operations_row_without_a_release(self):
        root = self.workspace()
        self.put(root, "bugs", "BUG-001-a.md", bug_text())
        self.put(root, "incidents", "INC-001-a.md", incident_text())
        self.put(root, "incidents", "INC-002-b.md", incident_text("INC-002", "resolved"))
        self.assertEqual(ws.open_incidents(root), [("INC-001", ["backend"])])
        self.assertEqual(ws.operations_rows(root, "—"), ["| backend | — | — | — | — | BUG-001 | INC-001 |"])

    def test_seeding_rebuilds_the_bugs_table_the_open_bugs_cell_and_the_incident_columns(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "knowledge/wiki").mkdir(parents=True)
            board = root / "knowledge/wiki/status-board.md"
            board.write_text(STATUS_BOARD_TEMPLATE, encoding="utf-8")
            ws.seed_state(root, "bug-fixed")
            text = board.read_text(encoding="utf-8")
            self.assertIn("| BUG-001 | Summary does not say how many comments are not shown | fixed | qa | backend | F-001 | yes |", text)
            self.assertRegex(text, r"\| F-001 \| Review summary export \| in-dev \| dev \| not-needed \| ui: not-applicable; technical: done \| backend: in-dev \| BUG-001 \|")
            self.assertIn("| backend | — | — | — | — | BUG-001 | — |", text)
            ws.seed_state(root, "release-done")
            text = board.read_text(encoding="utf-8")
            self.assertIn("| backend | production | — | REL-001 | failed | BUG-001 | — |", text, "a failed attempt is the latest outcome and releases nothing")
            ws.seed_state(root, "ingest-incident")
            text = board.read_text(encoding="utf-8")
            self.assertIn("| backend | production | F-001 | REL-002 | released | — | INC-001 |", text)
            self.assertNotIn("| BUG-001 |", text, "a released bug leaves the Bugs table")
            ws.seed_state(root, "po-intake")
            self.assertNotIn("INC-001", board.read_text(encoding="utf-8"))


class PendingInputTests(unittest.TestCase):
    def test_the_ingest_steps_find_their_input_in_their_own_fixtures(self):
        self.assertEqual(set(ws.PENDING_INPUTS), {"po-intake", "ingest-incident"})
        for step, (folder, name) in ws.PENDING_INPUTS.items():
            with self.subTest(step=step):
                self.assertFalse(config.STEPS_BY_ID[step].gated and step == "po-intake")
                self.assertTrue((config.FIXTURES_DIR / step / "knowledge/intake/processed" / folder / name).is_file())
                self.assertTrue((config.FIXTURES_DIR / step / "knowledge/intake/processed" / folder / "MANIFEST.md").is_file())

    def test_placing_an_input_copies_it_to_the_pending_folder_and_seeding_removes_it(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            placed = ws.place_pending_input(root, "ingest-incident")
            self.assertEqual(placed, root / "knowledge/intake/pending/2026-10-09-release-incident/report.md")
            self.assertIn("# Incident report", placed.read_text(encoding="utf-8"))
            self.assertEqual(ws.pending_folder("po-intake"), ws.PENDING_INTAKE)
            ws.place_pending_brief(root)
            ws.reset_journey_files(root)
            self.assertFalse((root / "knowledge/intake/pending/2026-10-09-release-incident").exists())
            self.assertFalse((root / ws.PENDING_INTAKE).exists())

    def test_the_incident_report_names_the_release_the_record_cites(self):
        report = (config.FIXTURES_DIR / "ingest-incident/knowledge/intake/processed/2026-10-09-release-incident/report.md").read_text(encoding="utf-8")
        self.assertIn("REL-002", report)
        self.assertIn("right-to-left", report)


class PageHelperTests(unittest.TestCase):
    TEXT = (
        "---\nid: F-001\nstatus: in-qa\n---\n\n## Acceptance criteria\n- [ ] AC-1 [backend] First.\n- [x] **Decided:** AC-3 [backend] Third.\n\n"
        "## QA verification\n| Row | Criteria | Result |\n|---|---|---|\n| backend | AC-1@v1:aa, AC-3@v1:bb | pass |\n\n## Release\nNone.\n"
    )

    def test_a_page_gives_its_front_matter_sections_and_table_rows(self):
        page = ws.Page(Path("x.md"), ws.parse_front_matter(self.TEXT), self.TEXT)
        self.assertEqual(page.front["status"], "in-qa")
        self.assertEqual(page.section("Release").strip(), "None.")
        self.assertEqual(page.section("Missing"), "")
        self.assertEqual(page.rows("QA verification"), [["backend", "AC-1@v1:aa, AC-3@v1:bb", "pass"]])
        self.assertEqual(page.rows("Release"), [])

    def test_front_matter_lists_are_read_in_flow_and_block_style(self):
        text = "---\napps: [backend, worker]\nreleases:\n- REL-001\n- 'REL-002'\nbugs: []\nstatus: open\n---\n\n## Body\n- not an item\n"
        page = ws.Page(Path("x.md"), ws.parse_front_matter(text), text)
        self.assertEqual(page.front_list("apps"), ["backend", "worker"])
        self.assertEqual(page.front_list("releases"), ["REL-001", "REL-002"])
        self.assertEqual(page.front_list("bugs"), [])
        self.assertEqual(page.front_list("missing"), [])

    def test_criterion_text_finds_a_criterion_by_its_exact_number(self):
        text = "## Acceptance criteria\n- [ ] AC-1 [backend] First.\n- [ ] AC-10 [backend] Tenth.\n- [x] **Decided:** AC-2 [backend] Second.\n"
        self.assertEqual(ws.criterion_text(text, 1), "[backend] First.")
        self.assertEqual(ws.criterion_text(text, 10), "[backend] Tenth.")
        self.assertEqual(ws.criterion_text(text, 2), "[backend] Second.")
        self.assertEqual(ws.criterion_text(text, 3), "")

    def test_criterion_numbers_and_the_numbers_a_row_cites(self):
        self.assertEqual(ws.criterion_numbers(self.TEXT), [1, 3])
        self.assertEqual(ws.cited_numbers("AC-1@v1:aa, AC-3@v1:bb"), {1, 3})
        self.assertEqual(ws.cited_numbers("none"), set())

    def test_read_page_finds_a_page_by_its_file_prefix(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "knowledge/wiki/releases").mkdir(parents=True)
            (root / "knowledge/wiki/releases/REL-002.md").write_text("---\nid: REL-002\noutcome: released\n---\n\n## Summary\nx\n", encoding="utf-8")
            self.assertEqual(ws.read_page(root, "releases", "REL-002").front["outcome"], "released")
            self.assertIsNone(ws.read_page(root, "releases", "REL-001"))
            self.assertIsNone(ws.read_page(root, "bugs", "BUG-001"))

    def test_a_board_row_is_found_by_its_table_and_key(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "knowledge/wiki").mkdir(parents=True)
            board = ws.rewrite_operations(ws.rewrite_bugs(STATUS_BOARD_TEMPLATE, ["| BUG-001 | B | open | dev | backend | F-001 | yes |"]), ["| backend | production | F-001 | REL-002 | released | — | INC-001 |"])
            (root / "knowledge/wiki/status-board.md").write_text(board, encoding="utf-8")
            self.assertEqual(ws.board_row_cells(root, "Operations", "backend")[-1], "INC-001")
            self.assertEqual(ws.board_row_cells(root, "Bugs", "BUG-001")[2], "open")
            self.assertIsNone(ws.board_row_cells(root, "Operations", "worker"))


class JourneyNarrativeTests(unittest.TestCase):
    """The states after the QA, bug, release and incident steps tell the story the step table says."""

    def page(self, step, relative, fixture_set=None):
        files = ws.fixture_files(ws.fixture_steps_through(step), fixture_set)
        path = files.get(relative)
        if path is None:
            return None
        text = path.read_text(encoding="utf-8")
        return ws.Page(path, ws.parse_front_matter(text), text)

    def feature(self, step, fixture_set=None):
        return self.page(step, FEATURE_FILE, fixture_set)

    def bug(self, step):
        return self.page(step, "knowledge/wiki/bugs/BUG-001-summary-lacks-hidden-comment-count.md")

    def test_the_bug_goes_from_open_to_released_with_the_evidence_of_each_step(self):
        expected = {
            "qa-verify": ("open", "dev"), "qa-fail": ("open", "dev"), "bug-start": ("in-fix", "dev"), "bug-fixed": ("fixed", "qa"),
            "dev-redeliver": ("fixed", "qa"), "bug-verify": ("verified", "release"), "qa-pass": ("verified", "release"),
            "release-done": ("verified", "release"), "release-retry": ("released", "none"), "ingest-incident": ("released", "none"),
        }
        for step, pair in expected.items():
            with self.subTest(step=step):
                bug = self.bug(step)
                self.assertEqual((bug.front["status"], bug.front["owner"]), pair)
                self.assertEqual(len(bug.rows("Fix")), 1 if pair[0] not in {"open"} and step not in {"qa-verify", "qa-fail", "bug-start"} else 0)
                self.assertEqual(len(bug.rows("Verification")), 1 if step in {"bug-verify", "qa-pass", "release-done", "release-retry", "ingest-incident"} else 0)
        self.assertEqual([row[4] for row in self.bug("release-done").rows("Release")], ["failed"])
        self.assertEqual([row[4] for row in self.bug("release-retry").rows("Release")], ["released"])
        self.assertIsNone(self.bug("dev-start"))

    def test_the_first_qa_attempt_fails_one_criterion_and_the_second_passes_every_one(self):
        first = self.feature("qa-verify")
        rows = first.rows("QA verification")
        self.assertEqual(sorted(row[6] for row in rows), ["fail", "pass"])
        self.assertEqual({row[5] for row in rows}, {"qa-1"})
        failing = next(row for row in rows if row[6] == "fail")
        (number,) = ws.cited_numbers(failing[1])
        self.assertIn("how many more comments are not shown", ws.criterion_text(first.text, number), "the failing criterion is the one about the comments left out")
        self.assertEqual(ws.cited_numbers(next(row for row in rows if row[6] == "pass")[1]), set(ws.criterion_numbers(first.text)) - {number})
        self.assertEqual(first.rows("Delivery evidence")[0][1], "commit:3f9c2ab")
        failed = self.feature("qa-fail")
        self.assertEqual((failed.rows("Delivery evidence"), failed.rows("QA verification"), failed.rows("Release")), ([], [], []))
        self.assertEqual(failed.text.count("### 2026-10-09 - qa-fail"), 1)
        self.assertIn("app-revalidation:", failed.text)
        second = self.feature("qa-pass")
        (row,) = second.rows("QA verification")
        self.assertEqual((row[5], row[6], row[3]), ("qa-2", "pass", "`commit:5d7a1e4`"))
        self.assertEqual(ws.cited_numbers(row[1]), set(ws.criterion_numbers(second.text)))
        self.assertEqual(second.rows("Release")[0][3:5], ["release-1", "pending"])
        self.assertEqual(second.rows("Delivery evidence")[0][1], "commit:5d7a1e4")

    def test_the_first_release_attempt_fails_and_the_retry_releases_both_records_staying(self):
        failed = self.feature("release-done")
        self.assertEqual(failed.rows("Release")[0][3:6], ["release-1", "failed", "[REL-001](../releases/REL-001.md)"])
        self.assertEqual((failed.front["status"], failed.front["owner"]), ("ready-for-release", "release"))
        first = self.page("release-done", "knowledge/wiki/releases/REL-001.md")
        self.assertEqual((first.front["outcome"], first.front["bugs"]), ("failed", "[BUG-001]"))
        self.assertIn("rolled back", first.section("Rollback"))
        self.assertIsNone(self.page("release-done", "knowledge/wiki/releases/REL-002.md"))
        released = self.feature("release-retry")
        self.assertEqual(released.rows("Release")[0][3:6], ["release-2", "released", "[REL-002](../releases/REL-002.md)"])
        retry = self.page("release-retry", "knowledge/wiki/releases/REL-002.md")
        self.assertEqual((retry.front["outcome"], retry.front["retry-of"]), ("released", "REL-001"))
        self.assertEqual(self.page("release-retry", "knowledge/wiki/releases/REL-001.md").front["outcome"], "failed", "a record is never rewritten")

    def test_the_operations_row_follows_the_releases_and_the_incident_opens_after_the_retry(self):
        incident = self.page("ingest-incident", "knowledge/wiki/incidents/INC-001-blank-summary-for-right-to-left-comments.md")
        self.assertEqual((incident.front["status"], incident.front["releases"], incident.front["apps"]), ("open", "[REL-002]", "[backend]"))
        self.assertTrue(incident.section("Cause").strip().startswith("**Unknown:**"))
        self.assertIsNone(self.page("release-retry", "knowledge/wiki/incidents/INC-001-blank-summary-for-right-to-left-comments.md"))
        manifest = self.page("ingest-incident", "knowledge/intake/processed/2026-10-09-release-incident/MANIFEST.md")
        self.assertIn("INC-001", manifest.text)

    def test_the_api_work_set_cites_the_contract_and_toggles_its_status_with_the_delivery(self):
        for step, status in (("dev-done", "implemented"), ("qa-fail", "agreed"), ("dev-redeliver", "implemented"), ("feature-reopen", "agreed")):
            with self.subTest(step=step):
                contract = self.page(step, CONTRACT_FILE, API_SET)
                self.assertEqual(contract.front["status"], status)
        for step in ("dev-done", "dev-redeliver", "qa-pass"):
            self.assertTrue(self.feature(step, API_SET).rows("Delivery evidence")[0][2].startswith("F-001@v1:c1:"), step)
        record = self.page("release-retry", "knowledge/wiki/releases/REL-002.md", API_SET)
        self.assertIn("F-001@v1:c1:", record.section("Contracts"))
        self.assertEqual(self.page("release-retry", "knowledge/wiki/releases/REL-002.md").section("Contracts").strip(), "None.")

    def test_the_sets_agree_on_everything_but_the_api_surface_and_the_contract(self):
        for step in ("qa-verify", "qa-fail", "qa-pass", "release-done", "release-retry", "ingest-incident"):
            with self.subTest(step=step):
                default = self.feature(step)
                api = self.feature(step, API_SET)
                self.assertEqual((default.front["status"], default.front["owner"]), (api.front["status"], api.front["owner"]))
                self.assertTrue(ws.declares_api_work(api.text) and not ws.declares_api_work(default.text))
                self.assertEqual([row[3:] for row in default.rows("QA verification")], [row[3:] for row in api.rows("QA verification")])


if __name__ == "__main__":
    unittest.main()
