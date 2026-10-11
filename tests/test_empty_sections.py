"""Empty evidence sections have the same meaning in board previews and wiki lint."""

from __future__ import annotations

import unittest

from prism_cli.board_service import BoardError
from prism_cli.wiki_lint import lint_wiki
from prism_cli.wiki_model import section_is_empty, section_text
from tests.qa_pages import format_bug_page
from tests.qa_support import FEATURE, QaBoard, app_row, fix_row, integration_row, release_row, verification_row
from tests.test_board_service import _read_revisions, _replace_body_section_text
from tests.test_lifecycle_model import RELEASE_HEADER, table
from tests import test_qa_fail

BUG = "knowledge/wiki/bugs/BUG-001-summary-export-drops-comments.md"


class EmptySectionTests(unittest.TestCase):
    def test_only_comments_and_header_separator_pairs_are_empty(self) -> None:
        header = "| App | Artifact |\n|---|:---:|"
        for text in ("", " \n", "<!-- comment\nwith text -->", header, f"<!-- before -->\n{header}\n<!-- after -->", f"{header}\n\n{header}", "App | Artifact\n--- | ---", "| App | A\\|B |\n| --- | --- |", "| App | Artifact |\n| - | :-: |"):
            with self.subTest(text=text):
                self.assertTrue(section_is_empty(text))
        for text in ("Evidence exists.", f"{header}\n| worker | build:worker#1 |", f"{header}\ntext", f"text\n{header}", "| App | Artifact |", "|---|---|", "| App | Artifact |\n|---|", "| App | Artifact |\n|---|text|", "```\n" + header + "\n```", "<!-- comment -->\n## Nested heading"):
            with self.subTest(text=text):
                self.assertFalse(section_is_empty(text))


class BugCreationParityTests(QaBoard):
    def creation(self, skill: str, content: str) -> tuple[list[dict[str, str]], list[dict[str, str]] | None]:
        if skill == "ingest":
            folder = "2026-10-08-defect-report"
            self.put(f"knowledge/intake/pending/{folder}/report.md", "# Defect\nThe export drops comments.\n")
            content = self.frontmatter_with(content, sources=[f"knowledge/intake/processed/{folder}/report.md"])
            changes = [{"path": BUG, "content": content}, {"path": f"knowledge/intake/processed/{folder}/MANIFEST.md", "content": f"# Manifest\n\n- {BUG} (BUG-001)\n"}]
            return changes, [{"source": f"knowledge/intake/pending/{folder}", "destination": f"knowledge/intake/processed/{folder}"}]
        if skill == "qa-fail":
            changes = test_qa_fail.QaFailTests.fail_changes(self, ["worker"], linked="BUG-001")
        elif skill == "qa-pass":
            feature = self.qa_table([app_row("backend"), integration_row(), app_row("worker", result="fail")])
            feature = self.with_status("in-qa", "qa", self.release_table([release_row("backend")], feature))
            changes = [{"path": FEATURE, "content": feature}]
        else:
            changes = [{"path": FEATURE, "content": self.qa_table([app_row("worker", result="fail")])}]
        return [*changes, {"path": BUG, "content": content}], None

    def preview_creation(self, skill: str, content: str) -> dict:
        changes, moves = self.creation(skill, content)
        return self.service.preview_skill(self.agent, skill, changes, moves, _read_revisions(self.service, self.agent, skill, changes, moves))

    def bug_errors(self, content: str) -> list[str]:
        self.put(BUG, content)
        errors = [item.message for item in lint_wiki(self.root).diagnostics if item.severity == "error" and item.path.replace("\\", "/").endswith(BUG)]
        (self.root / BUG).unlink()
        from tests.wiki_files import refresh_status_board

        refresh_status_board(self.root)
        return errors

    def test_the_documented_empty_tables_are_accepted_by_every_creation_route_and_lint(self) -> None:
        content = format_bug_page()
        for skill in ("qa-verify", "qa-pass", "qa-fail", "ingest"):
            with self.subTest(skill=skill):
                preview = self.preview_creation(skill, content)
                self.assertEqual(("ready", True), (preview["classification"], preview["applicable"]), preview["checks"])
        self.assertEqual([], self.bug_errors(content))

    def test_multiple_empty_tables_and_comments_have_lint_parity(self) -> None:
        content = format_bug_page()
        for heading in ("Fix", "Verification", "Release"):
            header = section_text(content, heading).strip()
            content = _replace_body_section_text(content, heading, f"<!-- before -->\n{header}\n\n{header}\n<!-- after -->")
        self.assertEqual("ready", self.preview_creation("qa-verify", content)["classification"])
        self.assertEqual([], self.bug_errors(content))

    def test_rows_and_prose_are_refused_by_every_creation_route(self) -> None:
        content = format_bug_page()
        rows = {
            "Fix": fix_row(),
            "Verification": verification_row(),
            "Release": release_row("worker"),
            "Evidence history": "Evidence has already been recorded.",
        }
        for heading, row in rows.items():
            for text in (section_text(content, heading).rstrip() + "\n" + row, "None yet."):
                invalid = _replace_body_section_text(content, heading, text)
                for skill in ("qa-verify", "qa-pass", "qa-fail", "ingest"):
                    with self.subTest(heading=heading, text=text, skill=skill):
                        with self.assertRaises(BoardError) as caught:
                            self.preview_creation(skill, invalid)
                        self.assertEqual("bug_creation_invalid", caught.exception.code)
                        self.assertIn(f"`{heading}` hold rows or text and must be empty on a new bug", caught.exception.message)

    def test_inactive_bug_fix_and_verification_accept_prose_but_lint_refuses_rows(self) -> None:
        for status in ("open", "in-fix"):
            content = format_bug_page(status=status)
            for heading, row in (("Fix", fix_row()), ("Verification", verification_row())):
                with self.subTest(status=status, heading=heading):
                    self.assertEqual([], self.bug_errors(_replace_body_section_text(content, heading, "None yet.")))
                    populated = section_text(content, heading).rstrip() + "\n" + row
                    errors = self.bug_errors(_replace_body_section_text(content, heading, populated))
                    self.assertIn(f"A `{status}` bug has no active Fix or Verification rows; they are archived in Evidence history.", errors)

    def test_lint_preserves_open_release_rows_and_history_prose_acceptance(self) -> None:
        content = format_bug_page()
        release = section_text(content, "Release").rstrip() + "\n" + release_row("worker")
        self.assertEqual([], self.bug_errors(_replace_body_section_text(content, "Release", release)))
        self.assertEqual([], self.bug_errors(_replace_body_section_text(content, "Release", "None yet.")))
        self.assertEqual([], self.bug_errors(_replace_body_section_text(content, "Evidence history", "None yet.")))

    def test_the_message_names_only_the_filled_sections(self) -> None:
        content = format_bug_page(fix="A fix already exists.", release=table(RELEASE_HEADER, [release_row("worker")]))
        with self.assertRaises(BoardError) as caught:
            self.preview_creation("qa-verify", content)
        self.assertIn("the section(s) `Fix`, `Release` hold rows or text and must be empty on a new bug", caught.exception.message)


if __name__ == "__main__":
    unittest.main()
