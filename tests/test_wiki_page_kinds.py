"""The page kinds beyond the feature pipeline: topics, research, plans, direction and roadmap.

Each kind has a valid page, front-matter errors, the evidence-label and history-date lint, and a `_FORMAT.md` or a
SCHEMA.md definition in the template.
"""

from __future__ import annotations

import re
import shutil
import tempfile
import unittest
from pathlib import Path

from prism_cli.wiki_index import GENERAL_PAGE_KINDS, GENERAL_PAGE_SECTIONS, GENERAL_PAGE_STATUSES
from prism_cli.wiki_lint import lint_wiki
from prism_cli.wiki_model import HISTORY_DATE_FIELDS
from tests import real_temp  # noqa: F401
from tests.manifest_fixtures import manifest_text
from tests.wiki_files import copy_template_knowledge, write_index

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_WIKI = REPO_ROOT / "template" / "knowledge" / "wiki"
SOURCE = "../../intake/processed/2026-10-06-client-call/notes.md"

PAGES = {
    "topics/payment-flows.md": (
        "---\nkind: topic\ntitle: Payment flows\nstatus: current\nsources:\n- knowledge/intake/processed/2026-10-06-client-call/notes.md\n---\n\n"
        f"## Summary\nPayments settle within one business day.\n\n## Key points\n- **Observed:** Settlement takes one business day ([notes]({SOURCE})).\n"
        "- **Assumed:** Weekends are excluded.\n\n## Related pages\nNone yet.\n"
    ),
    "research/offline-sync.md": (
        "---\nkind: research\ntitle: Offline sync options\nstatus: open\nsources:\n- https://example.com/survey\n---\n\n"
        "## Question\nWhich sync model fits offline editing?\n\n## Summary\nA last-writer-wins model fits the current needs.\n\n"
        "## Findings\n- **Observed:** Two vendors support it ([survey](https://example.com/survey)).\n\n## Gaps\n- **Unknown:** The cost at scale.\n"
    ),
    "plans/launch.md": (
        "---\nkind: plan\ntitle: Launch\nstatus: active\nsources: []\n---\n\n"
        "## Summary\nThe launch is in its second phase.\n\n## Goal\nShip to all customers.\n\n## Current status\nThe beta runs.\n\n"
        "## Next steps\n- **Proposed:** Invite the first hundred customers.\n\n## Blockers\nNo blockers.\n"
    ),
    "direction.md": (
        "---\nkind: direction\nsources: []\n---\n\n## Summary\nThe product serves reviewers first.\n\n"
        "## Direction\n- **Proposed:** Reviewers come first.\n\n## Principles\n- Keep records.\n"
    ),
    "roadmap.md": (
        "---\nkind: roadmap\nsources: []\n---\n\n## Summary\nThe next release ships the export.\n\n"
        "## Next\n- The export ships on 2026-12-01.\n\n## Later\n- Offline editing.\n"
    ),
}


class PageKindCase(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        copy_template_knowledge(self.root / "knowledge")
        (self.root / "prism.workspace.yml").write_text(manifest_text("Kinds", ["backend"], slug="kinds"), encoding="utf-8")
        (self.root / "backend").mkdir()
        # The processed source that the pages link and list in `sources`.
        note = self.root / "knowledge" / "intake" / "processed" / "2026-10-06-client-call" / "notes.md"
        note.parent.mkdir(parents=True)
        note.write_text("Captured: 2026-10-06\n\nThe client call.\n", encoding="utf-8")
        (note.parent / "MANIFEST.md").write_text("# Processed intake\n\nNo pages extracted.\n", encoding="utf-8")
        self.wiki = self.root / "knowledge" / "wiki"

    def write(self, relative: str, text: str) -> None:
        path = self.wiki / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")

    def lint(self):
        write_index(self.root)
        return lint_wiki(self.root)

    def diagnostics(self, code: str) -> list:
        return [item for item in self.lint().diagnostics if item.code == code]

    def codes(self) -> list[str]:
        return [item.code for item in self.lint().diagnostics]


class ValidPageTests(PageKindCase):
    def test_every_new_kind_has_a_valid_page_that_lints_clean(self) -> None:
        for relative, text in PAGES.items():
            with self.subTest(page=relative):
                self.write(relative, text)
        result = self.lint()
        self.assertEqual([], [item.to_dict() for item in result.diagnostics])

    def test_the_shipped_direction_and_roadmap_pages_are_valid_and_empty(self) -> None:
        self.assertEqual([], self.codes())
        self.assertIn("No direction is recorded yet.", (self.wiki / "direction.md").read_text(encoding="utf-8"))
        self.assertIn("No roadmap is recorded yet.", (self.wiki / "roadmap.md").read_text(encoding="utf-8"))

    def test_a_roadmap_may_state_a_date_about_the_world(self) -> None:
        self.write("roadmap.md", PAGES["roadmap.md"])
        self.assertEqual([], self.codes())
        self.assertIn("2026-12-01", (self.wiki / "roadmap.md").read_text(encoding="utf-8"))


class FrontMatterErrorTests(PageKindCase):
    def mutated(self, relative: str, old: str, new: str) -> None:
        text = PAGES[relative]
        self.assertIn(old, text)
        self.write(relative, text.replace(old, new, 1))

    def test_a_page_without_front_matter_is_malformed(self) -> None:
        for relative in PAGES:
            with self.subTest(page=relative):
                self.write(relative, PAGES[relative].split("---\n", 2)[2])
                found = self.diagnostics("malformed-page")
                self.assertEqual([Path(relative).name], [Path(item.path).name for item in found])
                self.write(relative, PAGES[relative])

    def test_the_kind_must_be_the_kind_of_the_folder(self) -> None:
        cases = {
            "topics/payment-flows.md": ("kind: topic", "kind: research", "invalid-topic-kind"),
            "research/offline-sync.md": ("kind: research", "kind: topic", "invalid-research-kind"),
            "plans/launch.md": ("kind: plan", "kind: roadmap", "invalid-plan-kind"),
            "direction.md": ("kind: direction", "kind: roadmap", "invalid-direction-kind"),
            "roadmap.md": ("kind: roadmap", "kind: direction", "invalid-roadmap-kind"),
        }
        for relative, (old, new, code) in cases.items():
            with self.subTest(page=relative):
                self.mutated(relative, old, new)
                self.assertEqual(1, len(self.diagnostics(code)))
                self.write(relative, PAGES[relative])

    def test_a_missing_kind_is_reported_per_kind(self) -> None:
        cases = {
            "topics/payment-flows.md": "missing-topic-kind",
            "research/offline-sync.md": "missing-research-kind",
            "plans/launch.md": "missing-plan-kind",
            "direction.md": "missing-direction-kind",
            "roadmap.md": "missing-roadmap-kind",
        }
        for relative, code in cases.items():
            with self.subTest(page=relative):
                self.write(relative, re.sub(r"kind: \w+\n", "", PAGES[relative], count=1))
                self.assertEqual(1, len(self.diagnostics(code)))
                self.write(relative, PAGES[relative])

    def test_a_topic_research_page_or_plan_needs_a_title(self) -> None:
        for relative, kind in (("topics/payment-flows.md", "topic"), ("research/offline-sync.md", "research"), ("plans/launch.md", "plan")):
            with self.subTest(page=relative):
                self.write(relative, re.sub(r"title: .*\n", "", PAGES[relative], count=1))
                self.assertEqual(1, len(self.diagnostics(f"missing-{kind}-frontmatter")))
                self.write(relative, re.sub(r"title: .*\n", "title: ''\n", PAGES[relative], count=1))
                self.assertEqual(1, len(self.diagnostics(f"invalid-{kind}-title")))
                self.write(relative, PAGES[relative])

    def test_the_status_is_one_of_the_values_of_its_kind(self) -> None:
        for relative, kind in (("topics/payment-flows.md", "topic"), ("research/offline-sync.md", "research"), ("plans/launch.md", "plan")):
            with self.subTest(page=relative):
                self.write(relative, re.sub(r"status: \w+\n", "status: unknown\n", PAGES[relative], count=1))
                self.assertEqual(1, len(self.diagnostics(f"invalid-{kind}-status")))
                self.write(relative, re.sub(r"status: \w+\n", "", PAGES[relative], count=1))
                self.assertEqual(1, len(self.diagnostics(f"missing-{kind}-status")))
                for status in GENERAL_PAGE_STATUSES[kind]:
                    self.write(relative, re.sub(r"status: \w+\n", f"status: {status}\n", PAGES[relative], count=1))
                    self.assertEqual([], self.codes(), status)
                self.write(relative, PAGES[relative])

    def test_a_status_value_of_another_kind_is_rejected(self) -> None:
        self.mutated("topics/payment-flows.md", "status: current", "status: active")
        self.assertEqual(1, len(self.diagnostics("invalid-topic-status")))

    def test_direction_and_roadmap_have_no_title_or_status(self) -> None:
        for relative in ("direction.md", "roadmap.md"):
            with self.subTest(page=relative):
                self.write(relative, PAGES[relative].replace("sources: []", "title: Extra\nstatus: current\nsources: []"))
                self.assertEqual([], self.codes())
                self.write(relative, PAGES[relative])

    def test_sources_is_required_and_must_be_a_list_of_strings(self) -> None:
        for relative, kind in (("topics/payment-flows.md", "topic"), ("research/offline-sync.md", "research"), ("plans/launch.md", "plan"), ("direction.md", "direction"), ("roadmap.md", "roadmap")):
            with self.subTest(page=relative):
                self.write(relative, re.sub(r"sources:(?:\n- .*|.*)\n", "", PAGES[relative], count=1, flags=re.M))
                self.assertEqual(1, len(self.diagnostics(f"missing-{kind}-frontmatter")), relative)
                self.write(relative, re.sub(r"sources:(?:\n- .*|.*)\n", "sources: just text\n", PAGES[relative], count=1, flags=re.M))
                self.assertEqual(1, len(self.diagnostics(f"invalid-{kind}-sources")), relative)
                self.write(relative, PAGES[relative])

    def test_an_empty_sources_list_is_valid(self) -> None:
        self.write("plans/launch.md", PAGES["plans/launch.md"])
        self.assertEqual([], self.codes())


class SharedLintTests(PageKindCase):
    def test_a_history_date_field_is_an_error_on_every_new_kind(self) -> None:
        for relative in PAGES:
            with self.subTest(page=relative):
                self.write(relative, PAGES[relative].replace("sources:", "updated: 2026-10-06\nsources:", 1))
                found = self.diagnostics("history-date-on-page")
                self.assertEqual([Path(relative).name], [Path(item.path).name for item in found])
                self.assertEqual("error", found[0].severity)
                self.write(relative, PAGES[relative])

    def test_evidence_labels_are_checked_on_every_new_kind(self) -> None:
        for relative in PAGES:
            with self.subTest(page=relative):
                self.write(relative, PAGES[relative] + "\n- **Decided:** A claim with no link.\n- **Maybe:** Not a label.\n")
                self.assertEqual(1, len(self.diagnostics("unlinked-claim")))
                self.assertEqual(1, len(self.diagnostics("unknown-evidence-label")))
                self.write(relative, PAGES[relative])

    def test_a_broken_relative_link_is_an_error_on_every_new_kind(self) -> None:
        for relative in PAGES:
            with self.subTest(page=relative):
                prefix = "" if "/" not in relative else "../"
                self.write(relative, PAGES[relative] + f"\nSee [the rule]({prefix}business-rules/BR-404-missing.md).\n")
                self.assertEqual(1, len(self.diagnostics("broken-link")))
                self.write(relative, PAGES[relative])

    def test_a_superseded_decision_cited_by_a_topic_is_a_warning(self) -> None:
        self.write(
            "decisions/ADR-001-old.md",
            "---\nid: ADR-001\ntitle: Old\ndate: 2026-09-01\nstatus: superseded\nsuperseded-by: ADR-002\n---\n\n## Decision\nOld.\n",
        )
        self.write("decisions/ADR-002-new.md", "---\nid: ADR-002\ntitle: New\ndate: 2026-10-01\nstatus: accepted\nsupersedes: ADR-001\n---\n\n## Decision\nNew.\n")
        self.write("topics/payment-flows.md", PAGES["topics/payment-flows.md"] + "\nWe follow [ADR-001](../decisions/ADR-001-old.md).\n")
        self.assertEqual(1, len(self.diagnostics("superseded-decision-cited")))

    def test_a_link_from_a_feature_to_a_topic_is_not_a_dangling_graph_reference(self) -> None:
        from prism_cli.wiki_graph import build_graph

        self.write("topics/payment-flows.md", PAGES["topics/payment-flows.md"])
        self.write(
            "features/F-001-login.md",
            "---\nid: F-001\ntitle: Login\nstatus: raw\nowner: po\napps: [backend]\nsources: []\nadvisory-review: not-needed\n---\n\n"
            "## Summary\nUsers sign in. See [payment flows](../topics/payment-flows.md) and [a missing page](../topics/missing.md).\n",
        )
        (self.wiki / "status-board.md").write_text(
            "# Feature Status Board\n\n| ID | Feature | Status | Owner | Board Review | Design tracks | App stages | Open bugs |\n|----|---------|--------|-------|--------------|---------------|------------|-----------|\n| F-001 | Login | raw | po | not-needed | — | — | — |\n",
            encoding="utf-8",
        )
        write_index(self.root)
        references = [item["reference"] for item in build_graph(self.root)["facts"]["dangling_references"]]
        self.assertNotIn("../topics/payment-flows.md", references)
        self.assertIn("../topics/missing.md", references)


class TemplateDefinitionTests(unittest.TestCase):
    def test_each_page_folder_has_a_format_file_with_the_required_fields(self) -> None:
        for folder, kind in (("topics", "topic"), ("research", "research"), ("plans", "plan")):
            with self.subTest(folder=folder):
                text = (TEMPLATE_WIKI / folder / "_FORMAT.md").read_text(encoding="utf-8")
                block = text.split("```markdown\n", 1)[1].split("```", 1)[0]
                front = block.split("---\n")[1]
                self.assertIn(f"kind: {kind}", front)
                self.assertIn("title:", front)
                self.assertIn("status: " + " | ".join(GENERAL_PAGE_STATUSES[kind]), front)
                self.assertIn("sources:", front)
                self.assertTrue((TEMPLATE_WIKI / folder / ".gitkeep").is_file())
                for section in GENERAL_PAGE_SECTIONS[kind]:
                    self.assertIn(f"## {section}\n", block)

    def test_every_format_carries_no_history_date_and_uses_the_evidence_labels(self) -> None:
        for folder in ("topics", "research", "plans"):
            with self.subTest(folder=folder):
                text = (TEMPLATE_WIKI / folder / "_FORMAT.md").read_text(encoding="utf-8")
                front = text.split("```markdown\n", 1)[1].split("---\n")[1]
                self.assertEqual([], [line for line in front.splitlines() if line.split(":", 1)[0].strip().lower() in HISTORY_DATE_FIELDS])
                self.assertRegex(text, r"\*\*(Observed|Decided|Proposed|Assumed|Unknown):\*\*")

    def test_schema_defines_every_new_kind_the_index_and_the_status_board(self) -> None:
        schema = (TEMPLATE_WIKI / "SCHEMA.md").read_text(encoding="utf-8")
        for folder, heading in (("topics", "# Topic page format"), ("research", "# Research page format"), ("plans", "# Plan page format")):
            self.assertIn(heading, (TEMPLATE_WIKI / folder / "_FORMAT.md").read_text(encoding="utf-8"))
            self.assertIn(f"[`{folder}/_FORMAT.md`]({folder}/_FORMAT.md)", schema)
        for heading in (
            "## Direction page format",
            "## Roadmap page format",
            "## Ingest: any role, any page kind",
            "## index.md conventions",
            "## status-board.md conventions",
        ):
            self.assertIn(heading, schema)
        for name in ("topics/", "research/", "plans/", "direction.md", "roadmap.md", "status-board.md"):
            self.assertIn(name, schema.split("## Page kinds")[0])
        for code in ("missing-index-entry", "orphan-index-entry", "duplicate-index-entry"):
            self.assertIn(code, schema)
        self.assertEqual({"topic", "research", "plan", "direction", "roadmap"}, set(GENERAL_PAGE_KINDS))

    def test_the_roadmap_format_allows_domain_dates_and_the_plan_format_holds_current_status(self) -> None:
        schema = (TEMPLATE_WIKI / "SCHEMA.md").read_text(encoding="utf-8")
        roadmap = schema.split("## Roadmap page format", 1)[1].split("\n---\n", 1)[0]
        self.assertIn("domain fact", roadmap)
        plan = (TEMPLATE_WIKI / "plans" / "_FORMAT.md").read_text(encoding="utf-8")
        self.assertIn("current status of one plan", plan)
        self.assertIn("does not keep the plan's history", plan.replace("\n", " "))


if __name__ == "__main__":
    unittest.main()
