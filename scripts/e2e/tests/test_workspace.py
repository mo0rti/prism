"""Workspace helpers that need no product, host or network: fixtures, seeding, page parsing."""

from pathlib import Path
import re
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prism_e2e import config, workspace as ws  # noqa: E402

INDEX = """# Feature Status Board

This file is maintained by the AI agent. Do not edit directly.

| ID | Feature | Status | Owner | Board Review |
|----|---------|--------|-------|--------------|
| F-009 | Old row | raw | po | not-needed |
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


class StatusBoardTests(unittest.TestCase):
    def test_rewrite_status_board_replaces_the_feature_rows_and_keeps_everything_else(self):
        row = ws.feature_row(ws.parse_front_matter(PAGE))
        self.assertEqual(row, "| F-001 | Review summary export | ready-for-dev | dev | not-needed |")
        rewritten = ws.rewrite_status_board(INDEX, row)
        self.assertIn(row, rewritten)
        self.assertNotIn("F-009", rewritten)
        self.assertIn("This file is maintained by the AI agent.", rewritten)
        self.assertEqual(rewritten.count("|----|"), 1)

    def test_rewrite_status_board_without_a_row_leaves_an_empty_table(self):
        rewritten = ws.rewrite_status_board(INDEX, None)
        self.assertNotIn("F-009", rewritten)
        self.assertIn("|----|---------|", rewritten)


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
AFTER_SPECIFY = [step.id for step in config.STEPS[3:11]]  # po-specify through dev-done


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
        for step in ("design-handoff", "dev-clarify", "dev-start", "dev-done"):
            with self.subTest(step=step):
                files = self.files(step)
                contract = text_of(files, CONTRACT_FILE)
                front = ws.parse_front_matter(contract)
                self.assertEqual((front["feature-id"], front["version"]), ("F-001", "1"))
                self.assertEqual(front["status"], "implemented" if step == "dev-done" else "agreed")
                for heading in ("## Endpoints", "## Data models", "## Authentication requirements", "## Notes"):
                    self.assertIn(heading, contract)
                requirement = text_of(files, REQUIREMENT_FILE)
                reference = requirement.split("## API contract reference", 1)[1].split("\n## ", 1)[0]
                self.assertIn("(../api-contracts/F-001.md)", reference)
                self.assertNotIn("no API contract page", requirement)

    def test_no_contract_exists_before_design_handoff(self):
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


if __name__ == "__main__":
    unittest.main()
