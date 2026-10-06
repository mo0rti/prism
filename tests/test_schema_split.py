"""The wiki schema is split into a core `SCHEMA.md` and a `LIFECYCLE.md` protocol file.

The split is a pure move: no section may be dropped, and every reader that names
`SCHEMA.md` before a lifecycle operation also names `LIFECYCLE.md`.
"""

from __future__ import annotations

import json
import re
import unittest
from collections import Counter
from pathlib import Path

from prism_cli.workflow_assets import get_skill, list_skills

REPO_ROOT = Path(__file__).resolve().parents[1]
WIKI_TEMPLATE = REPO_ROOT / "template" / "knowledge" / "wiki"
HEADINGS_FIXTURE = Path(__file__).parent / "fixtures" / "schema-split-headings.json"
HEADING = re.compile(r"#{1,6} ")
# The only heading the split adds: the title of `LIFECYCLE.md`.
LIFECYCLE_TITLE = "# Wiki lifecycle protocol - features, board and advisory files"


def _after_front_matter(text: str) -> str:
    """The text below the leading `---` front matter block of a wiki file."""

    return text.split("---", 2)[2] if text.startswith("---") else text


def _headings(path: Path) -> list[str]:
    return [line for line in path.read_text(encoding="utf-8").splitlines() if HEADING.match(line)]


class SchemaSplitTests(unittest.TestCase):
    def test_every_heading_of_the_original_schema_lives_in_exactly_one_of_the_two_files(self) -> None:
        expected = json.loads(HEADINGS_FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual({"SCHEMA.md", "LIFECYCLE.md"}, set(expected))
        self.assertEqual(expected["SCHEMA.md"], _headings(WIKI_TEMPLATE / "SCHEMA.md"))
        self.assertEqual([LIFECYCLE_TITLE, *expected["LIFECYCLE.md"]], _headings(WIKI_TEMPLATE / "LIFECYCLE.md"))

    def test_no_heading_is_dropped_or_duplicated_across_the_pair(self) -> None:
        expected = json.loads(HEADINGS_FIXTURE.read_text(encoding="utf-8"))
        original = Counter(expected["SCHEMA.md"]) + Counter(expected["LIFECYCLE.md"])
        current = Counter(_headings(WIKI_TEMPLATE / "SCHEMA.md")) + Counter(_headings(WIKI_TEMPLATE / "LIFECYCLE.md"))
        self.assertEqual(Counter({LIFECYCLE_TITLE: 1}), current - original)
        self.assertEqual(Counter(), original - current)

    def test_each_file_points_at_the_other(self) -> None:
        schema = (WIKI_TEMPLATE / "SCHEMA.md").read_text(encoding="utf-8")
        lifecycle = (WIKI_TEMPLATE / "LIFECYCLE.md").read_text(encoding="utf-8")
        self.assertIn("`LIFECYCLE.md` holds the feature, board and advisory protocol", " ".join(_after_front_matter(schema).split("---")[0].split()))
        self.assertIn("This file extends `SCHEMA.md`, which is read first.", " ".join(_after_front_matter(lifecycle).split("---")[0].split()))
        # The lifecycle protocol never points at itself as "this schema", and the core never claims lifecycle sections.
        self.assertNotIn("read this schema,", lifecycle)
        for heading in ("### Lifecycle action registry", "### Status and owner lifecycle", "## Feature page format"):
            self.assertNotIn(heading, schema)

    def test_skills_and_guidance_that_name_the_schema_also_name_the_lifecycle_file(self) -> None:
        template = REPO_ROOT / "template"
        sources = [
            *sorted((template / ".agents" / "skills").glob("*/SKILL.md.jinja")),
            *sorted((template / ".claude" / "commands").glob("*.md.jinja")),
            *sorted((template / ".claude" / "skills").glob("*/SKILL.md.jinja")),
            template / "AGENTS.md.jinja",
            template / "README.md.jinja",
            template / "docs" / "ai-agents.md.jinja",
            template / "docs" / "README.md.jinja",
            template / "knowledge" / "wiki" / "CONNECTED.md",
        ]
        checked = 0
        for path in sources:
            text = path.read_text(encoding="utf-8")
            if "SCHEMA" not in text:
                continue
            checked += 1
            with self.subTest(path=path.relative_to(REPO_ROOT).as_posix()):
                self.assertIn("LIFECYCLE", text)
        self.assertGreater(checked, 30)

    def test_packaged_skills_that_name_the_schema_reference_the_lifecycle_file(self) -> None:
        references_lifecycle = set()
        for listed in list_skills():
            skill = get_skill(listed["name"])
            paths = [item["path"] for item in skill["references"]]
            self.assertIn("knowledge/wiki/SCHEMA.md", paths)
            if "knowledge/wiki/LIFECYCLE.md" in paths:
                references_lifecycle.add(listed["name"])
            if "SCHEMA" in skill["instructions"]:
                with self.subTest(skill=listed["name"]):
                    self.assertIn("knowledge/wiki/LIFECYCLE.md", paths)
        self.assertTrue({"po-intake", "po-handoff", "dev-done", "feature-reopen", "board-review"} <= references_lifecycle)
        # Read-only query skills keep the core schema only.
        self.assertTrue({"wiki-show", "wiki-query", "wiki-owner", "wiki-app", "ask"}.isdisjoint(references_lifecycle))


if __name__ == "__main__":
    unittest.main()
