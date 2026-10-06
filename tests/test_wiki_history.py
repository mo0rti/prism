"""History lives in log.md: no history dates on current-state pages, a structured log, a schema version."""

from __future__ import annotations

import re
import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path

from prism_cli.board_service import BoardError, BoardService, _render_status_board
from prism_cli.workflow_install import apply_install, plan_install
from prism_cli.wiki_lint import lint_wiki
from prism_cli.wiki_model import HISTORY_DATE_FIELDS, load_markdown_page, parse_status_board_rows
from tests import real_temp  # noqa: F401
from tests.test_core_workflow_fixture import _feature_page, _write_index

FIXTURES = Path(__file__).parent / "fixtures" / "wiki_contract"
TEMPLATE_WIKI = Path(__file__).resolve().parents[1] / "template" / "knowledge" / "wiki"
CHECK_DATE = date(2026, 9, 8)

LOG_HEADER = "# Wiki log\n\nAppend-only.\n\n"
GOOD_ENTRY = (
    "## 2026-09-01 po-intake | F-001\n"
    "- paths: knowledge/wiki/features/F-001-checkout.md, knowledge/wiki/status-board.md\n"
    "- evidence: knowledge/intake/processed/checkout-brief\n"
    "- by: Claude Code (confirmed by Riley)\n"
)


class WorkspaceCase(unittest.TestCase):
    """A copy of the healthy wiki-contract workspace to add pages and log entries to."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        shutil.copytree(FIXTURES / "healthy", self.root, dirs_exist_ok=True)
        self.wiki = self.root / "knowledge" / "wiki"

    def write(self, relative: str, text: str) -> Path:
        path = self.wiki / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        return path

    def lint(self):
        return lint_wiki(self.root, today=CHECK_DATE)

    def diagnostics(self, code: str) -> list:
        return [item for item in self.lint().diagnostics if item.code == code]


class HistoryDateOnPageTests(WorkspaceCase):
    def test_healthy_workspace_has_no_history_date_findings(self) -> None:
        result = self.lint()
        self.assertEqual([], [item for item in result.diagnostics if item.code == "history-date-on-page"])
        self.assertTrue(result.is_clean, [item.to_dict() for item in result.diagnostics if item.severity == "error"])

    def test_each_history_field_is_an_error_on_a_feature_page(self) -> None:
        feature = self.wiki / "features" / "F-001-checkout.md"
        original = feature.read_text(encoding="utf-8")
        for field_name in ("introduced", "last-updated", "created", "updated", "date-updated"):
            with self.subTest(field=field_name):
                feature.write_text(original.replace("apps:", f"{field_name}: 2026-01-01\napps:", 1), encoding="utf-8", newline="\n")
                found = self.diagnostics("history-date-on-page")
                self.assertEqual(1, len(found), found)
                self.assertEqual("error", found[0].severity)
                self.assertEqual(feature.resolve(), Path(found[0].path).resolve())
                self.assertEqual("F-001", found[0].feature_id)
                self.assertIn(f"`{field_name}`", found[0].message)
                self.assertIn("log.md", found[0].message)
                self.assertFalse(self.lint().is_clean)

    def test_a_field_is_reported_whatever_its_spelling(self) -> None:
        feature = self.wiki / "features" / "F-001-checkout.md"
        feature.write_text(feature.read_text(encoding="utf-8").replace("apps:", "Last_Updated: 2026-01-01\napps:", 1), encoding="utf-8", newline="\n")
        found = self.diagnostics("history-date-on-page")
        self.assertEqual(["`Last_Updated`"], [re.search(r"`[^`]+`", item.message).group(0) for item in found])

    def test_history_fields_are_reported_on_every_other_page_kind(self) -> None:
        pages = {
            "personas/operator.md": "---\nid: P-001\nname: Operator\nsources: []\nintroduced: 2026-01-01\n---\n\n## Who they are\nAn operator.\n",
            "business-rules/BR-001-rule.md": "---\nid: BR-001\ntitle: Rule\nsource: brief\ncreated: 2026-01-01\n---\n\n## Rule\nA rule.\n",
            "design/F-001-checkout.md": "---\nfeature-id: F-001\ntitle: Checkout design\nfigma: not applicable\ndate: 2026-01-01\n---\n\n## Summary\nDesign.\n",
            "api-contracts/F-001.md": "---\nfeature-id: F-001\nversion: 1\nstatus: draft\nlast-updated: 2026-01-01\n---\n\n## Endpoints\nGET /x\n",
            "app-requirements/F-001-backend.md": "---\nfeature-id: F-001\napp: backend\nstatus: pending\nupdated: 2026-01-01\n---\n\n## What to build\nX.\n",
        }
        for relative, text in pages.items():
            self.write(relative, text)
        found = {Path(item.path).resolve().relative_to(self.wiki.resolve()).as_posix(): item for item in self.diagnostics("history-date-on-page")}
        self.assertEqual(set(pages), set(found))
        for item in found.values():
            self.assertEqual("error", item.severity)
            self.assertIn("log.md", item.message)

    def test_a_dated_record_keeps_its_own_date(self) -> None:
        self.write("decisions/ADR-001-auth.md", "---\nid: ADR-001\ntitle: Auth\ndate: 2026-01-01\nstatus: accepted\n---\n\n## Context\nWhy.\n")
        self.write("advisory/F-001-review.md", "---\nfeature-id: F-001\nreviewed: 2026-01-02\nboard-members-consulted: [Riley]\n---\n\n## 1. Conflicts\nNone.\n")
        result = self.lint()
        self.assertEqual([], [item for item in result.diagnostics if item.code == "history-date-on-page"])
        self.assertTrue(result.is_clean, [item.to_dict() for item in result.diagnostics if item.severity == "error"])

    def test_a_record_does_not_excuse_another_history_field(self) -> None:
        self.write("decisions/ADR-001-auth.md", "---\nid: ADR-001\ntitle: Auth\ndate: 2026-01-01\nlast-updated: 2026-02-01\nstatus: accepted\n---\n\n## Context\nWhy.\n")
        found = self.diagnostics("history-date-on-page")
        self.assertEqual(["`last-updated`"], [re.search(r"`[^`]+`", item.message).group(0) for item in found])

    def test_a_domain_date_under_its_own_name_is_not_history(self) -> None:
        feature = self.wiki / "features" / "F-001-checkout.md"
        feature.write_text(feature.read_text(encoding="utf-8").replace("apps:", "effective-date: 2026-12-01\napps:", 1), encoding="utf-8", newline="\n")
        self.assertEqual([], self.diagnostics("history-date-on-page"))
        self.assertNotIn("effective-date", HISTORY_DATE_FIELDS)

    def test_page_age_is_not_a_finding(self) -> None:
        # Dates on pages no longer drive any age check; stale-page is gone.
        result = lint_wiki(self.root, today=date(2040, 1, 1))
        self.assertEqual([], [item for item in result.diagnostics if item.code in {"stale-page", "invalid-wiki-date"}])


class LogFormatTests(WorkspaceCase):
    def write_log(self, text: str) -> Path:
        return self.write("log.md", text)

    def malformed(self) -> list:
        return self.diagnostics("malformed-log-entry")

    def test_entries_in_the_log_format_are_clean(self) -> None:
        self.write_log(
            LOG_HEADER
            + GOOD_ENTRY
            + "\n## 2026-09-02 board-po-handoff | F-001\n"
            "- paths: knowledge/wiki/features/F-001-checkout.md\n"
            "- evidence: none\n"
            "- by: Riley (human)\n"
            "Moved to design after the board review.\n"
            "<!-- prism:board-actor:v1 {\"kind\": \"human\"} -->\n"
        )
        self.assertEqual([], self.malformed())

    def test_a_missing_or_empty_log_is_clean(self) -> None:
        self.assertEqual([], self.malformed())
        self.write_log(LOG_HEADER)
        self.assertEqual([], self.malformed())

    def test_html_comment_markers_and_fenced_examples_are_ignored(self) -> None:
        self.write_log(
            "# Wiki log\n\n```text\n## YYYY-MM-DD <operation> | <subject>\n- paths: <changed paths>\n```\n\n"
            "<!-- prism:board-history:v1 preview=abc -->\n" + GOOD_ENTRY + "<!-- prism:board-actor:v1 {} -->\n"
        )
        self.assertEqual([], self.malformed())

    def test_each_departure_from_the_format_is_a_warning(self) -> None:
        cases = {
            "old bracketed heading": "## 2026-09-01 [po-intake] | F-001\n- paths: a.md\n- evidence: none\n- by: x\n",
            "heading without a date": "## [project-creation-date] init | Wiki initialized\n- paths: a.md\n- evidence: none\n- by: x\n",
            "impossible date": "## 2026-13-45 po-intake | F-001\n- paths: a.md\n- evidence: none\n- by: x\n",
            "heading without a subject": "## 2026-09-01 po-intake\n- paths: a.md\n- evidence: none\n- by: x\n",
            "free text instead of fields": "## 2026-09-01 po-intake | F-001\nBrief description of what changed and why.\n",
            "missing evidence line": "## 2026-09-01 po-intake | F-001\n- paths: a.md\n- by: x\n",
            "fields out of order": "## 2026-09-01 po-intake | F-001\n- by: x\n- paths: a.md\n- evidence: none\n",
            "empty value": "## 2026-09-01 po-intake | F-001\n- paths:\n- evidence: none\n- by: x\n",
            "two text lines": "## 2026-09-01 po-intake | F-001\n- paths: a.md\n- evidence: none\n- by: x\nOne line.\nAnother line.\n",
            "a bullet after the by line": "## 2026-09-01 po-intake | F-001\n- paths: a.md\n- evidence: none\n- by: x\n- note: extra\n",
        }
        for name, entry in cases.items():
            with self.subTest(case=name):
                self.write_log(LOG_HEADER + entry)
                found = self.malformed()
                self.assertEqual(1, len(found), found)
                self.assertEqual("warning", found[0].severity)
                self.assertEqual((self.wiki / "log.md").resolve(), Path(found[0].path).resolve())
                self.assertIn("line 5", found[0].message)

    def test_only_the_bad_entry_is_reported_and_the_log_is_never_rewritten(self) -> None:
        text = LOG_HEADER + GOOD_ENTRY + "\n## 2026-09-02 [old] | F-001\nFree text.\n\n" + GOOD_ENTRY.replace("2026-09-01", "2026-09-03")
        log = self.write_log(text)
        before = log.read_bytes()
        result = self.lint()
        found = [item for item in result.diagnostics if item.code == "malformed-log-entry"]
        self.assertEqual(1, len(found), found)
        self.assertIn("2026-09-02 [old]", found[0].message)
        self.assertTrue(result.is_clean, "a malformed log entry is a warning, never an error")
        self.assertEqual(before, log.read_bytes())

    def test_template_log_and_conventions_describe_the_format(self) -> None:
        log = (TEMPLATE_WIKI / "log.md").read_text(encoding="utf-8")
        schema = (TEMPLATE_WIKI / "SCHEMA.md").read_text(encoding="utf-8")
        self.write_log(log)
        self.assertEqual([], self.malformed())
        for needle in ("## YYYY-MM-DD <operation> | <subject>", "- paths:", "- evidence:", "- by:", "append-only", "only home for history", "malformed-log-entry"):
            self.assertIn(needle, schema.replace("`", ""), needle)


class SchemaVersionTests(WorkspaceCase):
    def test_both_files_declare_the_version(self) -> None:
        self.assertEqual([], self.diagnostics("missing-schema-version"))

    def test_each_file_without_the_version_is_an_error(self) -> None:
        for name in ("SCHEMA.md", "LIFECYCLE.md"):
            with self.subTest(file=name):
                original = (self.wiki / name).read_text(encoding="utf-8")
                for text in ("# Fixture\n", "---\nother: 1\n---\n\n# Fixture\n", "---\nschema-version: 2\n---\n\n# Fixture\n", "---\nschema-version: '1'\n---\n\n# Fixture\n"):
                    (self.wiki / name).write_text(text, encoding="utf-8", newline="\n")
                    found = self.diagnostics("missing-schema-version")
                    self.assertEqual(1, len(found), (text, found))
                    self.assertEqual("error", found[0].severity)
                    self.assertEqual((self.wiki / name).resolve(), Path(found[0].path).resolve())
                    self.assertIn("schema-version: 1", found[0].message)
                (self.wiki / name).write_text(original, encoding="utf-8", newline="\n")
        self.assertEqual([], self.diagnostics("missing-schema-version"))

    def test_an_absent_file_is_the_missing_file_error_only(self) -> None:
        (self.wiki / "LIFECYCLE.md").unlink()
        self.assertEqual([], self.diagnostics("missing-schema-version"))
        self.assertEqual(1, len(self.diagnostics("missing-required-wiki-file")))

    def test_the_template_files_start_with_the_version(self) -> None:
        for name in ("SCHEMA.md", "LIFECYCLE.md"):
            with self.subTest(file=name):
                page = load_markdown_page(TEMPLATE_WIKI / name)
                self.assertEqual({"schema-version": 1}, dict(page.frontmatter))
                self.assertTrue((TEMPLATE_WIKI / name).read_text(encoding="utf-8").startswith("---"))


class StatusBoardColumnsTests(unittest.TestCase):
    def test_the_template_status_board_and_index_have_no_dates(self) -> None:
        board = (TEMPLATE_WIKI / "status-board.md").read_text(encoding="utf-8")
        self.assertIn("| ID | Feature | Status | Owner | Board Review |\n", board.replace("\r\n", "\n"))
        index = (TEMPLATE_WIKI / "index.md").read_text(encoding="utf-8")
        for text in (board, index):
            self.assertNotIn("Introduced", text)
            self.assertNotIn("| Date |", text)
            self.assertIsNone(re.search(r"\d{4}-\d{2}-\d{2}", text))

    def test_the_template_formats_carry_no_history_dates_outside_records(self) -> None:
        for relative in ("features/_FORMAT.md", "personas/_FORMAT.md", "business-rules/_FORMAT.md", "design/_FORMAT.md", "LIFECYCLE.md", "SCHEMA.md"):
            text = (TEMPLATE_WIKI / relative).read_text(encoding="utf-8")
            for match in re.finditer(r"^---\n(.*?)\n---$", text.replace("\r\n", "\n"), re.S | re.M):
                for line in match.group(1).splitlines():
                    key = line.split(":", 1)[0].strip().lower()
                    if relative in {"SCHEMA.md", "LIFECYCLE.md"} and key in {"date", "reviewed"}:
                        continue  # the ADR (`date`) and advisory review (`reviewed`) records
                    self.assertNotIn(key, HISTORY_DATE_FIELDS, f"{relative}: {line}")

    def test_the_status_board_parser_reads_the_five_column_board_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            index = Path(temporary) / "status-board.md"
            index.write_text("# Board\n\n| ID | Feature | Status | Owner | Board Review |\n|----|----|----|----|----|\n| F-001 | A | raw | po | not-needed |\n", encoding="utf-8")
            rows, errors = parse_status_board_rows(index)
            self.assertEqual([], errors)
            self.assertEqual([("F-001", "A", "raw", "po", "not-needed")], [(r.feature_id, r.title, r.status, r.owner, r.advisory_review) for r in rows])
            index.write_text("# Board\n\n| ID | Feature | Status | Owner | Board Review | Introduced |\n|----|----|----|----|----|----|\n| F-001 | A | raw | po | not-needed | 2026-01-01 |\n", encoding="utf-8")
            rows, errors = parse_status_board_rows(index)
            self.assertEqual([], rows)
            self.assertEqual(["status-board.md is missing the feature status board table."], errors)

    def test_the_board_renders_rows_without_a_date_and_refuses_a_dated_table(self) -> None:
        board = "# Feature Status Board\n\n| ID | Feature | Status | Owner | Board Review |\n|----|---------|--------|-------|--------------|\n"
        row = {"id": "F-001", "title": "Checkout", "status": "specified", "owner": "po", "advisory_review": "not-needed"}
        rendered = _render_status_board(board, {"F-001": None}, {"F-001": row})
        self.assertIn("| F-001 | Checkout | specified | po | not-needed |\n", rendered)
        replaced = _render_status_board(rendered, {"F-001": row}, {"F-001": {**row, "status": "in-design", "owner": "designer"}})
        self.assertEqual(rendered.replace("specified | po", "in-design | designer"), replaced)
        dated = board.replace("Board Review |", "Board Review | Introduced |").replace("--------------|", "--------------|------------|")
        with self.assertRaises(BoardError) as raised:
            _render_status_board(dated, {"F-001": None}, {"F-001": row})
        self.assertEqual("invalid_status_board", raised.exception.code)


class BoardHistoryTests(unittest.TestCase):
    """A board transition writes no date into the feature page and logs in the SCHEMA.md format."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        apply_install(self.root, plan_install(self.root, name="Document review", apps=["backend"]))
        self.feature = "knowledge/wiki/features/F-001-document-review.md"
        source = self.root / "knowledge/intake/processed/2026-10-06-document-review-brief/brief.md"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"# Document review\nRecord a summary and outcome.\n")
        page = _feature_page().replace("status: raw", "status: ready-for-design").replace("owner: po", "owner: designer").replace("| po | open |", "| po | resolved: Summarize key points. |")
        (self.root / self.feature).parent.mkdir(parents=True, exist_ok=True)
        (self.root / self.feature).write_bytes(page.encode("utf-8"))
        _write_index(self.root, "ready-for-design", "designer")
        self.service = BoardService(self.root).start()
        self.addCleanup(lambda: self.service.close())
        grant = self.service.create_participant("Reviewer", "human", True)
        self.actor = self.service.authenticate(grant["token"])

    def read(self, relative: str) -> str:
        return (self.root / relative).read_bytes().decode("utf-8")

    def test_a_transition_writes_no_date_and_appends_a_structured_log_entry(self) -> None:
        before_fields = dict(load_markdown_page(self.root / self.feature).frontmatter)
        before_body = load_markdown_page(self.root / self.feature).body
        log_before = self.read("knowledge/wiki/log.md")
        preview = self.service.preview_transition(self.actor, "F-001", "design-start", {"semantic_review_acknowledged": True})
        self.assertTrue(preview["applicable"], preview)
        receipt = self.service.apply(self.actor, preview["preview_id"], "history-operation")
        self.assertEqual("applied", receipt["state"], receipt)

        after = load_markdown_page(self.root / self.feature)
        self.assertEqual({**before_fields, "status": "in-design"}, dict(after.frontmatter))
        self.assertEqual(before_body, after.body)
        self.assertEqual([], [name for name in after.frontmatter if name in HISTORY_DATE_FIELDS])
        board = self.read("knowledge/wiki/status-board.md")
        self.assertIn("| F-001 | Document review | in-design | designer | not-needed |", board)
        self.assertNotIn("Introduced", board)

        log_after = self.read("knowledge/wiki/log.md")
        self.assertTrue(log_after.startswith(log_before.rstrip("\n")), "The log is append-only.")
        entry = log_after[len(log_before):]
        today = date.today().isoformat()
        self.assertRegex(
            entry,
            r"\A\n*<!-- prism:board-history:v1 preview=" + re.escape(preview["preview_id"]) + r" -->\n"
            rf"## {today} board-design-start \| F-001\n"
            r"- paths: knowledge/wiki/features/F-001-document-review\.md, knowledge/wiki/status-board\.md\n"
            r"- evidence: board preview " + re.escape(preview["preview_id"]) + r"\n"
            r"- by: Reviewer \(human\)\n"
            r"<!-- prism:board-actor:v1 \{[^\n]*\} -->\n\Z",
        )
        result = lint_wiki(self.root)
        self.assertEqual([], [item for item in result.diagnostics if item.code in {"malformed-log-entry", "history-date-on-page", "missing-schema-version"}])

    def test_an_installed_workspace_lints_clean_for_history(self) -> None:
        result = lint_wiki(self.root)
        self.assertEqual([], [item for item in result.diagnostics if item.code in {"malformed-log-entry", "history-date-on-page", "missing-schema-version"}])
        self.assertEqual({"schema-version": 1}, dict(load_markdown_page(self.root / "knowledge/wiki/SCHEMA.md").frontmatter))


if __name__ == "__main__":
    unittest.main()
