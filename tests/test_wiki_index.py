"""The general wiki index: which files are pages, the derived line of each kind, parsing and merging, lint, and index-first search."""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from prism_cli import cli
from prism_cli.wiki_index import (
    GROUPS,
    INDEX_HEADER,
    build_index,
    general_page_kind,
    index_line,
    index_target,
    is_page_path,
    page_group,
    parse_index_entries,
    remove_index_lines,
    render_index_lines,
)
from prism_cli.wiki_lint import lint_wiki
from prism_cli.wiki_model import parse_markdown_text
from prism_cli.wiki_query import wiki_search
from tests import real_temp  # noqa: F401
from tests.manifest_fixtures import manifest_text
from tests.wiki_files import write_index, write_status_board

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_KNOWLEDGE = REPO_ROOT / "template" / "knowledge"
SOURCE = "../../intake/processed/2026-10-06-client-call/notes.md"

TOPIC = (
    "---\nkind: topic\ntitle: Payment flows\nstatus: current\nsources:\n- knowledge/intake/processed/2026-10-06-client-call/notes.md\n---\n\n"
    "## Summary\nPayments settle within one business day. Refunds follow a separate path.\n\n"
    f"## Key points\n- **Observed:** Settlement takes one business day ([call notes]({SOURCE})).\n\n"
    "## Related pages\nNone yet.\n"
)


def workspace(root: Path) -> Path:
    """The template knowledge tree with a manifest and one app: a clean, fully indexed wiki."""

    shutil.copytree(TEMPLATE_KNOWLEDGE, root / "knowledge")
    (root / "prism.workspace.yml").write_text(manifest_text("Index test", ["backend"], slug="index-test"), encoding="utf-8")
    (root / "backend").mkdir()
    return root


class PageClassificationTests(unittest.TestCase):
    def test_pages_sit_in_the_wiki_root_or_one_page_folder_deep(self) -> None:
        for relative in ("SCHEMA.md", "direction.md", "status-board.md", "features/F-001-x.md", "topics/a.md", "advisory/BOARD.md", "plans/p.md"):
            with self.subTest(page=relative):
                self.assertTrue(is_page_path(relative))
        for relative in (
            "index.md",
            "log.md",
            "WIKI_REPORT.md",
            "features/_FORMAT.md",
            "features/.gitkeep",
            "features/nested/F-001.md",
            "unknown-folder/a.md",
            "topics/a.txt",
            "",
        ):
            with self.subTest(not_a_page=relative):
                self.assertFalse(is_page_path(relative))

    def test_every_page_has_one_group_and_the_groups_are_ordered(self) -> None:
        expected = {
            "direction.md": "direction",
            "roadmap.md": "direction",
            "plans/a.md": "plans",
            "topics/a.md": "topics",
            "research/a.md": "research",
            "features/F-001-a.md": "features",
            "personas/a.md": "personas",
            "business-rules/BR-001-a.md": "business-rules",
            "design/F-001-a.md": "design",
            "app-requirements/F-001-backend.md": "app-requirements",
            "api-contracts/F-001.md": "api-contracts",
            "decisions/ADR-001-a.md": "decisions",
            "advisory/BOARD.md": "advisory",
            "SCHEMA.md": "meta",
            "status-board.md": "meta",
        }
        for relative, group in expected.items():
            with self.subTest(page=relative):
                self.assertEqual(group, page_group(relative))
        self.assertIsNone(page_group("index.md"))
        self.assertEqual(sorted(set(expected.values())), sorted(key for key, _heading in GROUPS))

    def test_the_general_page_kind_is_read_from_the_path(self) -> None:
        self.assertEqual("topic", general_page_kind("topics/a.md"))
        self.assertEqual("research", general_page_kind("research/a.md"))
        self.assertEqual("plan", general_page_kind("plans/a.md"))
        self.assertEqual("direction", general_page_kind("direction.md"))
        self.assertEqual("roadmap", general_page_kind("roadmap.md"))
        self.assertIsNone(general_page_kind("features/F-001-a.md"))
        self.assertIsNone(general_page_kind("topics/_FORMAT.md"))


class IndexLineTests(unittest.TestCase):
    def line(self, relative: str, text: str) -> str:
        page = parse_markdown_text(Path(relative), text)
        return index_line(relative, page.frontmatter, page.body)

    def test_a_topic_line_is_its_title_and_the_first_sentence_of_its_summary(self) -> None:
        self.assertEqual("- [Payment flows](topics/payment-flows.md): Payments settle within one business day.", self.line("topics/payment-flows.md", TOPIC))

    def test_each_kind_names_its_page_and_states_it_in_one_sentence(self) -> None:
        cases = {
            "features/F-001-login.md": (
                "---\nid: F-001\ntitle: User login\n---\n\n## Summary\n- **Observed:** Users sign in with an email address ([notes](x.md)). They also reset passwords.\n",
                "- [F-001 User login](features/F-001-login.md): Users sign in with an email address.",
            ),
            "personas/reviewer.md": (
                "---\nid: P-001\nname: Reviewer\n---\n\n## Who they are\nA person assigned to review a document.\n",
                "- [P-001 Reviewer](personas/reviewer.md): A person assigned to review a document.",
            ),
            "business-rules/BR-001-retain.md": (
                "---\nid: BR-001\ntitle: Retain outcome\n---\n\n## Rule\nA review keeps its outcome.\n",
                "- [BR-001 Retain outcome](business-rules/BR-001-retain.md): A review keeps its outcome.",
            ),
            "decisions/ADR-001-auth.md": (
                "---\nid: ADR-001\ntitle: Auth strategy\n---\n\n## Context\nWhy.\n\n## Decision\nUse signed tokens.\n",
                "- [ADR-001 Auth strategy](decisions/ADR-001-auth.md): Use signed tokens.",
            ),
            "decisions/ADR-001-old.md": (
                "---\nid: ADR-001\ntitle: Old auth\nstatus: superseded\nsuperseded-by: ADR-002\n---\n\n## Decision\nUse sessions.\n",
                "- [ADR-001 Old auth](decisions/ADR-001-old.md): ADR-002 supersedes this decision.",
            ),
            "design/F-001-login.md": (
                "---\nfeature-id: F-001\ntitle: Login design\n---\n\n## Summary\nThe sign-in form is one screen.\n",
                "- [Login design](design/F-001-login.md): The sign-in form is one screen.",
            ),
            "app-requirements/F-001-backend.md": (
                "---\nfeature-id: F-001\napp: backend\nstatus: pending\n---\n\n## What to build\nStore it.\n",
                "- [F-001 backend](app-requirements/F-001-backend.md): Requirements of F-001 for the backend app.",
            ),
            "api-contracts/F-001.md": (
                "---\nfeature-id: F-001\nversion: 1\nstatus: agreed\n---\n\n## Endpoints\nGET /x\n",
                "- [F-001 API contract](api-contracts/F-001.md): API contract of F-001.",
            ),
            "advisory/F-001-review.md": (
                "---\nfeature-id: F-001\n---\n\n## 1. Conflicts\nNone.\n",
                "- [F-001 board review](advisory/F-001-review.md): Board review of F-001.",
            ),
            "direction.md": (
                "---\nkind: direction\nsources: []\n---\n\n## Summary\nThe product serves reviewers first.\n",
                "- [Direction](direction.md): The product serves reviewers first.",
            ),
        }
        for relative, (text, expected) in cases.items():
            with self.subTest(page=relative):
                self.assertEqual(expected, self.line(relative, text))

    def test_a_page_without_a_summary_has_a_line_without_one(self) -> None:
        self.assertEqual("- [Plain](topics/plain.md)", self.line("topics/plain.md", "---\nkind: topic\ntitle: Plain\n---\n\n## Other\nText.\n"))

    def test_the_label_never_breaks_the_link(self) -> None:
        text = "---\nkind: topic\ntitle: 'A [b] c'\n---\n\n## Summary\nOne.\n"
        self.assertEqual("- [A (b) c](topics/a.md): One.", self.line("topics/a.md", text))

    def test_a_long_summary_is_cut_and_a_list_marker_and_label_are_dropped(self) -> None:
        long = "word " * 80
        line = self.line("topics/a.md", f"---\nkind: topic\ntitle: A\n---\n\n## Summary\n- **Decided:** {long}\n")
        self.assertTrue(line.endswith("..."))
        self.assertNotIn("Decided", line)
        self.assertLessEqual(len(line.split(": ", 1)[1]), 200)


class IndexParsingTests(unittest.TestCase):
    def test_only_list_items_that_start_with_a_link_are_lines(self) -> None:
        text = (
            "# Wiki index\n\nSee [the schema](SCHEMA.md) first.\n\n## Topics\n"
            "- [A](topics/a.md): One.\n"
            "* [B](<topics/b.md>): Two.\n"
            "- plain text\n"
            "- [External](https://example.com/x.md)\n"
            "- [Up](../outside.md)\n"
            "```\n- [Fenced](topics/fenced.md)\n```\n"
        )
        self.assertEqual(["topics/a.md", "topics/b.md"], [entry.target for entry in parse_index_entries(text)])

    def test_a_target_is_normalized_and_a_target_outside_the_wiki_is_not_one(self) -> None:
        self.assertEqual("topics/a.md", index_target("./topics/../topics/a.md"))
        self.assertEqual("a b.md", index_target("a%20b.md#part"))
        for target in ("../x.md", "/x.md", "https://example.com/a.md", "", "."):
            with self.subTest(target=target):
                self.assertIsNone(index_target(target))


class IndexMergeTests(unittest.TestCase):
    LINE_A = "- [A](topics/a.md): One."
    LINE_C = "- [C](topics/c.md): Three."

    def test_a_new_line_goes_into_its_group_in_path_order(self) -> None:
        text = f"# Wiki index\n\n## Topics\n{self.LINE_A}\n{self.LINE_C}\n\n## Features\n- [F](features/F-001-f.md): Feature.\n"
        merged = render_index_lines(text, {"topics/b.md": "- [B](topics/b.md): Two."})
        self.assertEqual(["topics/a.md", "topics/b.md", "topics/c.md", "features/F-001-f.md"], [e.target for e in parse_index_entries(merged)])

    def test_a_changed_line_is_replaced_where_it_stands(self) -> None:
        text = f"# Wiki index\n\n## Topics\n{self.LINE_A}\n{self.LINE_C}\n"
        merged = render_index_lines(text, {"topics/a.md": "- [A](topics/a.md): One, rewritten."})
        self.assertEqual(text.replace("One.", "One, rewritten."), merged)

    def test_a_missing_group_heading_is_created_in_group_order(self) -> None:
        text = "# Wiki index\n\n## Plans\n- [P](plans/p.md): Plan.\n\n## Features\n- [F](features/F-001-f.md): Feature.\n\n## Meta\n- [SCHEMA.md](SCHEMA.md): Rules.\n"
        merged = render_index_lines(text, {"topics/a.md": self.LINE_A, "research/r.md": "- [R](research/r.md): Research."})
        headings = [line for line in merged.splitlines() if line.startswith("## ")]
        self.assertEqual(["## Plans", "## Topics", "## Research", "## Features", "## Meta"], headings)
        self.assertEqual(["plans/p.md", "topics/a.md", "research/r.md", "features/F-001-f.md", "SCHEMA.md"], [e.target for e in parse_index_entries(merged)])

    def test_a_heading_with_no_later_group_is_appended_at_the_end(self) -> None:
        merged = render_index_lines("# Wiki index\n", {"SCHEMA.md": "- [SCHEMA.md](SCHEMA.md): Rules.", "topics/a.md": self.LINE_A})
        self.assertEqual("# Wiki index\n\n## Topics\n- [A](topics/a.md): One.\n\n## Meta\n- [SCHEMA.md](SCHEMA.md): Rules.\n", merged)

    def test_the_merge_is_idempotent_and_keeps_unrelated_text(self) -> None:
        text = f"# Wiki index\n\nIntro text kept as it is.\n\n## Topics\n{self.LINE_A}\n"
        after = {"topics/b.md": "- [B](topics/b.md): Two.", "topics/a.md": "- [A](topics/a.md): One again."}
        once = render_index_lines(text, after)
        self.assertEqual(once, render_index_lines(once, after))
        self.assertTrue(once.startswith("# Wiki index\n\nIntro text kept as it is.\n\n## Topics\n"))
        self.assertEqual(1, once.count("topics/a.md"))

    def test_line_endings_are_kept(self) -> None:
        text = f"# Wiki index\r\n\r\n## Topics\r\n{self.LINE_A}\r\n"
        merged = render_index_lines(text, {"topics/b.md": "- [B](topics/b.md): Two.", "topics/a.md": "- [A](topics/a.md): Changed."})
        self.assertNotIn("\n", merged.replace("\r\n", ""))
        self.assertIn("Changed.", merged)

    def test_a_path_that_is_not_a_page_is_refused_and_lines_can_be_removed(self) -> None:
        with self.assertRaises(ValueError):
            render_index_lines("# Wiki index\n", {"features/_FORMAT.md": "- [x](features/_FORMAT.md)"})
        text = f"# Wiki index\n\n## Topics\n{self.LINE_A}\n{self.LINE_C}\n"
        removed = remove_index_lines(text, ["topics/a.md"])
        self.assertEqual(["topics/c.md"], [e.target for e in parse_index_entries(removed)])

    def test_the_template_index_is_what_the_derivation_builds_from_the_template_pages(self) -> None:
        wiki = TEMPLATE_KNOWLEDGE / "wiki"
        self.assertEqual((wiki / "index.md").read_text(encoding="utf-8"), build_index(wiki))
        self.assertTrue(build_index(wiki).startswith(INDEX_HEADER))


class IndexLintTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = workspace(Path(temporary.name))
        self.wiki = self.root / "knowledge" / "wiki"

    def write(self, relative: str, text: str) -> Path:
        path = self.wiki / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        return path

    def codes(self, *, severity: str | None = None) -> list[str]:
        return [item.code for item in lint_wiki(self.root).diagnostics if severity in (None, item.severity)]

    def test_the_template_workspace_has_one_line_per_page_and_lints_clean(self) -> None:
        self.assertEqual([], self.codes())

    def test_a_page_with_no_line_is_a_warning_on_the_index_that_names_it(self) -> None:
        self.write("topics/payment-flows.md", TOPIC)
        found = [item for item in lint_wiki(self.root).diagnostics if item.code == "missing-index-entry"]
        self.assertEqual(1, len(found))
        self.assertEqual(("warning", "index.md"), (found[0].severity, Path(found[0].path).name))
        self.assertIn("`topics/payment-flows.md`", found[0].message)
        self.assertIsNone(found[0].feature_id)
        self.assertTrue(lint_wiki(self.root).is_clean, "a missing line is a warning, never an error")
        write_index(self.root)
        self.assertEqual([], self.codes())

    def test_a_line_for_no_page_is_an_orphan(self) -> None:
        text = (self.wiki / "index.md").read_text(encoding="utf-8")
        (self.wiki / "index.md").write_text(text + "\n## Topics\n- [Gone](topics/gone.md): Missing.\n", encoding="utf-8", newline="\n")
        found = [item for item in lint_wiki(self.root).diagnostics if item.code == "orphan-index-entry"]
        self.assertEqual(1, len(found))
        self.assertIn("`topics/gone.md`", found[0].message)
        self.assertEqual("warning", found[0].severity)
        self.assertNotIn("broken-wiki-link", self.codes(), "the index is not also reported as a broken link")

    def test_a_second_line_for_one_page_is_a_duplicate(self) -> None:
        text = (self.wiki / "index.md").read_text(encoding="utf-8")
        (self.wiki / "index.md").write_text(text + "- [Again](SCHEMA.md): Twice.\n", encoding="utf-8", newline="\n")
        found = [item for item in lint_wiki(self.root).diagnostics if item.code == "duplicate-index-entry"]
        self.assertEqual(1, len(found))
        self.assertIn("`SCHEMA.md`", found[0].message)
        self.assertIn("2 lines", found[0].message)

    def test_a_line_that_leaves_the_wiki_or_names_a_non_page_file_is_not_an_orphan(self) -> None:
        text = (self.wiki / "index.md").read_text(encoding="utf-8")
        (self.wiki / "index.md").write_text(
            text + "\n## Meta\n- [Docs](../../docs/guide.md): Outside the wiki.\n- [Log](log.md): The ledger is not a page.\n", encoding="utf-8", newline="\n"
        )
        self.assertEqual([], self.codes())

    def test_an_unreadable_index_is_an_error_and_a_missing_one_is_a_missing_required_file(self) -> None:
        (self.wiki / "index.md").write_bytes(b"\xff\xfe\xfa")
        self.assertIn("malformed-index", self.codes(severity="error"))
        (self.wiki / "index.md").unlink()
        self.assertIn("missing-required-wiki-file", self.codes(severity="error"))
        self.assertNotIn("missing-index-entry", self.codes())

    def test_a_missing_status_board_is_a_missing_required_file(self) -> None:
        (self.wiki / "status-board.md").unlink()
        found = [item for item in lint_wiki(self.root).diagnostics if item.code == "missing-required-wiki-file"]
        self.assertEqual(["status-board.md"], [Path(item.path).name for item in found])

    def test_the_status_board_rows_must_match_the_features(self) -> None:
        self.write(
            "features/F-001-login.md",
            "---\nid: F-001\ntitle: Login\nstatus: raw\nowner: po\napps: [backend]\nsources: []\nadvisory-review: not-needed\n---\n\n## Summary\nUsers sign in.\n",
        )
        write_index(self.root)
        self.assertIn("feature-missing-from-status-board", self.codes(severity="error"))
        write_status_board(self.root, "| F-001 | Login | specified | po | not-needed |\n| F-002 | Ghost | raw | po | not-needed |\n")
        write_index(self.root)
        codes = self.codes(severity="error")
        self.assertIn("status-board-frontmatter-drift", codes)
        self.assertIn("status-board-missing-feature", codes)
        (self.wiki / "status-board.md").write_text("# Feature Status Board\n\nNo table.\n", encoding="utf-8")
        self.assertIn("malformed-status-board", self.codes(severity="error"))

    def test_a_missing_index_line_does_not_block_a_lifecycle_preflight(self) -> None:
        from prism_cli.wiki_transitions import build_transition_preflight
        from tests.test_core_workflow_fixture import _feature_page

        for name in (".agents/skills/po-handoff/SKILL.md", ".claude/commands/po-handoff.md"):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("<!-- prism:po-handoff-contract:v1 -->\nUse po-handoff.\n", encoding="utf-8")
        page = _feature_page().replace("status: raw", "status: specified")
        self.write("features/F-001-document-review.md", page)
        write_status_board(self.root, "| F-001 | Document review | specified | po | not-needed |\n")
        # No index line for the feature: lint warns, and the transition is not made unknown by it.
        self.assertIn("missing-index-entry", self.codes(severity="warning"))
        transition = build_transition_preflight(self.root, "F-001", action="po-handoff")["facts"]["transition"]
        self.assertNotIn("source-integrity:missing-index-entry", [check["code"] for check in transition["checks"]])


class IndexFirstSearchTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = workspace(Path(temporary.name))
        self.wiki = self.root / "knowledge" / "wiki"
        self.topic = self.wiki / "topics" / "settlement.md"
        self.topic.write_text(
            TOPIC.replace("Payment flows", "Settlement").replace("Payments settle within one business day.", "Money moves by wire transfer."),
            encoding="utf-8",
            newline="\n",
        )
        write_index(self.root)

    def test_a_page_whose_index_line_matches_is_found_without_its_text_matching_first(self) -> None:
        # The page text says "wire transfer"; only its index line says "Settlement" in the label.
        result = wiki_search(self.root, "settlement")
        facts = result["facts"]
        self.assertEqual(1, facts["index_match_count"])
        first = facts["results"][0]
        self.assertEqual("topic", first["type"])
        self.assertEqual(self.topic.name, Path(first["path"]).name)
        self.assertIn("index", first["matched_fields"])
        self.assertEqual("- [Settlement](topics/settlement.md): Money moves by wire transfer.", first["index_line"])
        self.assertEqual(str(self.wiki / "index.md"), result["sources"][1])

    def test_the_index_hit_comes_before_a_page_found_only_by_its_own_text(self) -> None:
        other = self.wiki / "topics" / "a-notes.md"
        other.write_text(TOPIC.replace("Payment flows", "Notes").replace("Refunds follow a separate path.", "See the settlement guide."), encoding="utf-8", newline="\n")
        # `other` is not in the index; its body mentions the term.
        results = wiki_search(self.root, "settlement")["facts"]["results"]
        self.assertEqual(["settlement.md", "a-notes.md"], [Path(item["path"]).name for item in results])
        self.assertIn("index_line", results[0])
        self.assertNotIn("index_line", results[1])
        self.assertNotIn("index", results[1]["matched_fields"])

    def test_the_new_page_kinds_are_searched_by_their_own_fields_too(self) -> None:
        (self.wiki / "plans").joinpath("launch.md").write_text(
            "---\nkind: plan\ntitle: Launch\nstatus: active\nsources: []\n---\n\n## Summary\nThe launch uses a canary rollout.\n", encoding="utf-8", newline="\n"
        )
        results = wiki_search(self.root, "canary")["facts"]["results"]
        self.assertEqual([("plan", "launch.md")], [(item["type"], Path(item["path"]).name) for item in results])

    def test_the_cli_search_reports_the_index_first_facts(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = cli.main(["wiki", "search", "settlement", str(self.root), "--json"])
        self.assertEqual(0, code)
        data = json.loads(buffer.getvalue())
        self.assertEqual(1, data["facts"]["index_match_count"])
        self.assertIn("index", data["facts"]["results"][0]["matched_fields"])
        self.assertIn("topics/settlement.md", data["facts"]["results"][0]["index_line"])

    def test_a_workspace_without_an_index_is_still_searched(self) -> None:
        (self.wiki / "index.md").unlink()
        facts = wiki_search(self.root, "wire transfer")["facts"]
        self.assertEqual(0, facts["index_match_count"])
        self.assertEqual(["settlement.md"], [Path(item["path"]).name for item in facts["results"]])


if __name__ == "__main__":
    unittest.main()
