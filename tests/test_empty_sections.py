"""Empty evidence sections of a new bug, and the evidence parser that no longer treats separators as emptiness."""

from __future__ import annotations

import itertools
import re
import unittest
from unittest import mock

from prism_cli import wiki_incidents, wiki_model
from prism_cli.board_service import BoardError
from prism_cli.wiki_bugs import FIX_COLUMNS, VERIFICATION_COLUMNS
from prism_cli.wiki_lint import lint_wiki
from prism_cli.wiki_model import (
    RELEASE_COLUMNS,
    _strip_line_comments,
    _visible_evidence_table_lines,
    _visible_markdown_lines,
    read_feature_evidence,
    remove_html_comments,
    section_is_empty,
    section_text,
)
from tests.qa_pages import format_bug_page
from tests.qa_support import FEATURE, QaBoard, app_row, fix_row, integration_row, release_row, verification_row
from tests.test_board_service import _parse_markdown, _read_revisions, _replace_body_section_text
from tests.test_lifecycle_model import RELEASE_HEADER, table
from tests import test_qa_fail

BUG = "knowledge/wiki/bugs/BUG-001-summary-export-drops-comments.md"
SECTION_COLUMNS = {"Fix": FIX_COLUMNS, "Verification": VERIFICATION_COLUMNS, "Release": RELEASE_COLUMNS}


def header_of(columns: tuple[str, ...]) -> str:
    return "| " + " | ".join(column.capitalize() for column in columns) + " |"


def separator_of(columns: tuple[str, ...]) -> str:
    return "|" + "|".join("---" for _ in columns) + "|"


class _CountingText(str):
    """A string that counts its `find` calls, to show how much work a scan does."""

    def __new__(cls, value: str) -> "_CountingText":
        counted = super().__new__(cls, value)
        counted.finds = 0
        return counted

    def find(self, *args: object) -> int:  # type: ignore[override]
        self.finds += 1
        return super().find(*args)  # type: ignore[arg-type]


class EmptySectionTests(unittest.TestCase):
    def test_blank_text_and_comments_are_empty_for_every_section(self) -> None:
        for text in ("", " \n", "\n\n", "<!-- comment\nwith text -->", "<!-- a -->\n<!-- b -->", "<!----> <!-- x -->"):
            for columns in (None, *SECTION_COLUMNS.values()):
                with self.subTest(text=text, columns=columns):
                    self.assertTrue(section_is_empty(text, columns))

    def test_only_the_documented_header_and_separator_are_an_empty_table(self) -> None:
        for heading, columns in SECTION_COLUMNS.items():
            header, separator = header_of(columns), separator_of(columns)
            for text in (
                f"{header}\n{separator}",
                f"{header}\n{separator}\n",
                f"\n{header}\n\n{separator}\n\n",
                f"<!-- before -->\n{header}\n{separator}\n<!-- after -->",
                f"{header}\n<!-- between\nlines -->\n{separator}",
                f"   {header}\n   {separator}",
                f"{header.upper()}\n{separator}",
                "| " + " | ".join(f"**{column.capitalize()}**" for column in columns) + " |\n|" + "|".join(":---:" for _ in columns) + "|",
                f"{header}\n| " + " | ".join("-" for _ in columns) + " |",
            ):
                with self.subTest(heading=heading, text=text):
                    self.assertTrue(section_is_empty(text, columns))

    def test_anything_else_is_not_empty(self) -> None:
        columns = FIX_COLUMNS
        header, separator = header_of(columns), separator_of(columns)
        row = "| worker | `build:worker#2` | Reviewed | `pytest` | checked |"
        for text in (
            "Evidence exists.",
            "None yet.",
            f"{header}\n{separator}\n{row}",
            f"{header}\n{separator}\n{row}\n{separator}",
            f"{row}\n{separator}",
            f"{header}\n{separator}\n{header}\n{separator}",
            f"{header}\n{separator}\n\n{header}\n{separator}",
            f"{header}\n{separator}\n{separator}",
            f"{separator}\n{header}",
            f"{separator}\n{separator}",
            f"{header}\n{separator}\ntext",
            f"text\n{header}\n{separator}",
            header,
            separator,
            f"{header}\n|---|---|",
            f"{header}\n" + separator.replace("---", "text", 1),
            f"{header}\n||||||",
            header_of(VERIFICATION_COLUMNS) + "\n" + separator_of(VERIFICATION_COLUMNS),
            "| App | Artifact | Implementation | Tests |\n|---|---|---|---|",
            f"    {header}\n    {separator}",
            f"{header}\n    {separator}",
            f"\t{header}\n\t{separator}",
            f"```\n{header}\n{separator}\n```",
            f"~~~\n{header}\n{separator}\n~~~",
            f"<!-- unterminated\n{header}\n{separator}",
            f"<!-- terminated -->\n<!-- unterminated\n{header}\n{separator}",
            f"<!--{header}\n{separator}",
            "<!-- comment -->\n## Nested heading",
        ):
            with self.subTest(text=text):
                self.assertFalse(section_is_empty(text, columns))

    def test_a_missing_columns_argument_accepts_no_table(self) -> None:
        for text in (header_of(FIX_COLUMNS) + "\n" + separator_of(FIX_COLUMNS), "Evidence exists.", "| a |", "<!-- open"):
            with self.subTest(text=text):
                self.assertFalse(section_is_empty(text))
                self.assertFalse(section_is_empty(text, None))

    def test_comment_removal_keeps_the_result_for_terminated_comments(self) -> None:
        for text in ("a<!-- x -->b", "<!---->", "<!-->x-->y", "<!-- a --> mid <!-- b\nc -->tail", "no comment", "x<!--y-->-->z", "", "<!-- a --><!-- b -->"):
            with self.subTest(text=text):
                self.assertEqual(re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL), remove_html_comments(text))
        self.assertEqual(" b <!-- open <!-- c", remove_html_comments("<!-- a --> b <!-- open <!-- c"))
        self.assertEqual("a<!-- open", remove_html_comments("a<!-- open"))

    def test_comment_removal_is_one_forward_pass(self) -> None:
        # An unterminated `<!--` ends the scan: one search for the opener and one for its `-->`, however many follow.
        unterminated = _CountingText("<!--" * (512 * 1024 // 4))
        self.assertEqual(512 * 1024, len(unterminated))
        self.assertEqual(str(unterminated), remove_html_comments(unterminated))
        self.assertEqual(2, unterminated.finds)
        self.assertFalse(section_is_empty(unterminated, FIX_COLUMNS))
        self.assertFalse(section_is_empty(unterminated, None))
        # Terminated comments cost two searches each, plus the two that find no further comment.
        terminated = _CountingText("<!-- a -->\n" * 4000 + "<!-- open")
        self.assertEqual("\n" * 4000 + "<!-- open", remove_html_comments(terminated))
        self.assertEqual(2 * 4000 + 2, terminated.finds)


def _reference_visible_markdown_lines(text: str) -> list[str]:
    """`_visible_markdown_lines` as it was before the comment scan became linear (it rebuilds the line per comment)."""

    visible: list[str] = []
    fenced = False
    in_comment = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("```") or line.startswith("~~~"):
            fenced = not fenced
            continue
        if fenced:
            continue
        if in_comment:
            if "-->" in line:
                in_comment = False
                line = line.split("-->", 1)[1].strip()
            else:
                continue
        while "<!--" in line:
            before, remainder = line.split("<!--", 1)
            if "-->" in remainder:
                line = before + remainder.split("-->", 1)[1]
            else:
                line = before
                in_comment = True
                break
        line = line.strip()
        if line:
            visible.append(line)
    return visible


def _reference_strip_line(line: str) -> tuple[str, bool]:
    while "<!--" in line:
        before, remainder = line.split("<!--", 1)
        if "-->" in remainder:
            line = before + remainder.split("-->", 1)[1]
        else:
            return before, True
    return line, False


class CommentScanTests(unittest.TestCase):
    MIXED = (
        "",
        "plain text",
        "| App | Artifact |\n|---|---|\n| a | b |",
        "<!-- one --> | App |\n<!-- two\nlines -->\n|---|\n| x | y | <!-- c --> z",
        "a <!-- b --> c <!-- d --> e",
        "<!-- unterminated\n| App |\n|---|\n--> | after |",
        "| a | <!-- open\n| hidden |\n| hidden |",
        "```\n<!-- in a fence\n```\n| App |\n~~~\n--> not a close\n~~~\n| row |",
        "<!<!-- a -->-- tail and <!-- b --> end",
        "<!-<!-- a -->-> not-a-comment",
        "<<!-- a -->!-- spliced --> end",
        "<!--x--><!--y--><!--z",
        "<!-->|a|<!--->|b|-->|c|",
        "-->|stray close|<!-- ok -->|row|",
        "   <!-- indented -->   |  x  |   ",
        "|a|\r\n<!-- c -->\r\n|b|",
    )

    def test_the_linear_scan_equals_the_rebuilding_scan_on_mixed_inputs(self) -> None:
        for text in self.MIXED:
            with self.subTest(text=text):
                self.assertEqual(_reference_visible_markdown_lines(text), _visible_markdown_lines(text))
                self.assertEqual(
                    [line for line in _reference_visible_markdown_lines(text) if line.startswith("|")],
                    _visible_evidence_table_lines(text),
                )

    def test_the_linear_scan_equals_the_rebuilding_scan_on_every_short_token_sequence(self) -> None:
        tokens = ("<!--", "-->", "<!", "--", "-", "<", ">", "a", "\n", "```")
        for length in range(0, 6):
            for sequence in itertools.product(tokens, repeat=length):
                text = "".join(sequence)
                if _visible_markdown_lines(text) != _reference_visible_markdown_lines(text):
                    self.fail(f"The comment scan differs for {text!r}.")
        single = ("<!--", "-->", "<!", "--", "-", "<", ">", "a", " ")
        for length in range(0, 7):
            for sequence in itertools.product(single, repeat=length):
                text = "".join(sequence)
                if _strip_line_comments(text) != _reference_strip_line(text):
                    self.fail(f"The line scan differs for {text!r}.")
                if remove_html_comments(text) != re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL):
                    self.fail(f"The comment removal differs for {text!r}.")

    def test_a_line_of_terminated_comments_is_scanned_in_one_pass(self) -> None:
        count = 512 * 1024 // len("<!--x-->")
        line = _CountingText("<!--x-->" * count)
        self.assertEqual(512 * 1024, len(line))
        self.assertEqual(("", False), _strip_line_comments(line))
        # One search for each opener and one for each closer, plus the search that finds no further opener.
        self.assertEqual(2 * count + 1, line.finds)
        self.assertEqual([], _visible_markdown_lines(str(line)))
        self.assertEqual([], _visible_evidence_table_lines(str(line)))
        kept = _CountingText("| a |" + "<!--x-->" * count + "| b |<!-- open")
        self.assertEqual(("| a || b |", True), _strip_line_comments(kept))
        self.assertEqual(2 * count + 2, kept.finds)
        self.assertEqual(["| a || b |"], _visible_markdown_lines(str(kept)))

    def test_comments_that_splice_into_new_openers_stay_linear_and_equal(self) -> None:
        for depth in range(1, 7):
            text = "<!" * depth + "<!-- a -->--" * depth
            with self.subTest(depth=depth):
                self.assertEqual(_reference_strip_line(text), _strip_line_comments(text))
        depth = 20000
        text = _CountingText("<!" * depth + "<!-- a -->--" * depth)
        _strip_line_comments(text)
        self.assertLessEqual(text.finds, 2 * depth + 2)

    def test_an_unterminated_comment_on_a_long_line_is_scanned_once(self) -> None:
        line = _CountingText("<!--" * (512 * 1024 // 4))
        self.assertEqual(("", True), _strip_line_comments(line))
        self.assertEqual(2, line.finds)

    def test_incident_pages_remove_comments_with_the_linear_scan(self) -> None:
        text = "<!--" * (512 * 1024 // 4)
        counted: list[_CountingText] = []
        real = wiki_incidents.remove_html_comments

        def counting(value: str) -> str:
            wrapped = _CountingText(value)
            counted.append(wrapped)
            return real(wrapped)

        body = f"## Impact\nA\n\n## Timeline\n{text}\n\n## Cause\n{text}\n"
        with mock.patch.object(wiki_incidents, "remove_html_comments", counting):
            self.assertFalse(wiki_incidents.section_is_blank(body, "Timeline"))
            self.assertFalse(wiki_incidents.cause_is_unknown(body))
            wiki_incidents.timeline_items(body)
        self.assertEqual(3, len(counted))
        self.assertTrue(all(item.finds <= 2 for item in counted), [item.finds for item in counted])
        self.assertTrue(wiki_incidents.cause_is_unknown("## Cause\n<!-- a -->**Unknown:** later\n"))


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

    def assert_refused(self, skill: str, content: str, heading: str) -> None:
        with self.assertRaises(BoardError) as caught:
            self.preview_creation(skill, content)
        self.assertEqual("bug_creation_invalid", caught.exception.code)
        self.assertIn(f"`{heading}` hold rows or text and must be empty on a new bug", caught.exception.message)

    def test_the_documented_empty_tables_are_accepted_by_every_creation_route_and_lint(self) -> None:
        content = format_bug_page()
        for heading, columns in SECTION_COLUMNS.items():
            self.assertEqual(f"{header_of(columns)}\n{separator_of(columns)}", section_text(content, heading).strip())
        for skill in ("qa-verify", "qa-pass", "qa-fail", "ingest"):
            with self.subTest(skill=skill):
                preview = self.preview_creation(skill, content)
                self.assertEqual(("ready", True), (preview["classification"], preview["applicable"]), preview["checks"])
        self.assertEqual([], self.bug_errors(content))

    def test_comments_around_the_documented_tables_are_accepted_with_lint_parity(self) -> None:
        content = format_bug_page()
        for heading in SECTION_COLUMNS:
            header = section_text(content, heading).strip()
            content = _replace_body_section_text(content, heading, f"<!-- before -->\n{header}\n<!-- after -->")
        content = _replace_body_section_text(content, "Evidence history", "<!-- Nothing archived yet. -->")
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
                        self.assert_refused(skill, invalid, heading)

    def test_fix_shapes_that_are_not_the_documented_empty_table_are_refused_by_every_creation_route(self) -> None:
        content = format_bug_page()
        header, separator = header_of(FIX_COLUMNS), separator_of(FIX_COLUMNS)
        row = fix_row()
        shapes = {
            "a data row between separators": f"{header}\n{separator}\n{row}\n{separator}",
            "a data row and a separator with no header": f"{row}\n{separator}",
            "two header-only tables": f"{header}\n{separator}\n\n{header}\n{separator}",
            "a header and separator indented four spaces": f"    {header}\n    {separator}",
            "a header and separator inside a code fence": f"```\n{header}\n{separator}\n```",
            "an unterminated comment before the header": f"<!-- note\n{header}\n{separator}",
            "the Verification header": f"{header_of(VERIFICATION_COLUMNS)}\n{separator_of(VERIFICATION_COLUMNS)}",
            "a stray separator": f"{header}\n{separator}\n{separator}",
        }
        for label, text in shapes.items():
            invalid = _replace_body_section_text(content, "Fix", text)
            for skill in ("qa-verify", "qa-pass", "qa-fail", "ingest"):
                with self.subTest(shape=label, skill=skill):
                    self.assert_refused(skill, invalid, "Fix")

    def test_every_section_refuses_a_row_behind_its_own_separator(self) -> None:
        content = format_bug_page()
        rows = {"Fix": fix_row(), "Verification": verification_row(), "Release": release_row("worker")}
        for heading, columns in SECTION_COLUMNS.items():
            populated = f"{header_of(columns)}\n{separator_of(columns)}\n{rows[heading]}\n{separator_of(columns)}"
            with self.subTest(heading=heading):
                self.assert_refused("qa-verify", _replace_body_section_text(content, heading, populated), heading)
        for text in (f"{header_of(FIX_COLUMNS)}\n{separator_of(FIX_COLUMNS)}", "<!-- open"):
            with self.subTest(history=text):
                self.assert_refused("qa-verify", _replace_body_section_text(content, "Evidence history", text), "Evidence history")

    def test_inactive_bug_fix_and_verification_accept_prose_but_lint_refuses_rows(self) -> None:
        for status in ("open", "in-fix"):
            content = format_bug_page(status=status)
            for heading, row in (("Fix", fix_row()), ("Verification", verification_row())):
                with self.subTest(status=status, heading=heading):
                    self.assertEqual([], self.bug_errors(_replace_body_section_text(content, heading, "None yet.")))
                    populated = section_text(content, heading).rstrip() + "\n" + row
                    errors = self.bug_errors(_replace_body_section_text(content, heading, populated))
                    self.assertIn(f"A `{status}` bug has no active Fix or Verification rows; they are archived in Evidence history.", errors)

    def test_a_row_behind_a_separator_is_still_a_row_for_inactive_bug_lint(self) -> None:
        content = format_bug_page(status="open")
        header, separator = header_of(FIX_COLUMNS), separator_of(FIX_COLUMNS)
        hidden = _replace_body_section_text(content, "Fix", f"{header}\n{separator}\n{fix_row()}\n{separator}")
        self.assertIn("A `open` bug has no active Fix or Verification rows; they are archived in Evidence history.", self.bug_errors(hidden))

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


class FeatureEvidenceScanTests(QaBoard):
    def test_lint_of_an_unterminated_comment_section_does_no_emptiness_scan(self) -> None:
        section = "<!--" * (512 * 1024 // 4)
        changed = _replace_body_section_text(self.read(FEATURE), "Delivery evidence", section)
        self.put(FEATURE, changed)
        # The evidence parser reads the section line by line and never asks the emptiness helper about it.
        with mock.patch.object(wiki_model, "section_is_empty", side_effect=AssertionError("the parser must not scan for emptiness")):
            read = read_feature_evidence(_parse_markdown(changed)[1])
            report = lint_wiki(self.root)
        self.assertEqual((), tuple(read.delivery))
        self.assertIsNotNone(report)


if __name__ == "__main__":
    unittest.main()
