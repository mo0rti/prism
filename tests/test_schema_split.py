"""The wiki instruction files are split by topic, and the split is a pure move.

`SCHEMA.md` keeps the core rules and lists each page kind with a link to the `_FORMAT.md` of its folder,
`LIFECYCLE.md` keeps the lifecycle protocol, and `ACTIONS.md` holds the action registry. No rule heading and no
error code of the two files before the split may be missing from the standard files, and every reader that names
`SCHEMA.md` before a lifecycle operation also names `LIFECYCLE.md`.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from prism_cli.wiki_transitions import ACTION_SPECS
from prism_cli.workflow_assets import get_skill, list_skills

REPO_ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE = REPO_ROOT / "template" / "knowledge"
WIKI_TEMPLATE = KNOWLEDGE / "wiki"
RULES_FIXTURE = Path(__file__).parent / "fixtures" / "instruction-split-rules.json"
HEADING = re.compile(r"^#{1,6} +(.*\S)\s*$")
ACTIONS_REFERENCE = "knowledge/wiki/ACTIONS.md"

# Where each section that left `LIFECYCLE.md` or `SCHEMA.md` lives now.
MOVED_TO_ACTIONS = (
    "Lifecycle action registry",
    "Common action protocol",
    "Specification and handoff boundaries",
    "PO handoff transition contract",
)
MOVED_TO_FORMAT = {
    "Persona page format": "personas/_FORMAT.md",
    "Business rule page format": "business-rules/_FORMAT.md",
    "Design page format": "design/_FORMAT.md",
    "Technical design page format": "technical-design/_FORMAT.md",
    "App requirements page format": "app-requirements/_FORMAT.md",
    "API contract page format": "api-contracts/_FORMAT.md",
    "Architecture Decision Record (ADR) format": "decisions/_FORMAT.md",
    "Topic page format": "topics/_FORMAT.md",
    "Research page format": "research/_FORMAT.md",
    "Plan page format": "plans/_FORMAT.md",
}


def _after_front_matter(text: str) -> str:
    """The text below the leading `---` front matter block of a wiki file."""

    return text.split("---", 2)[2] if text.startswith("---") else text


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def _headings(text: str, *, outside_code: bool = False) -> list[str]:
    """The heading texts of a Markdown file, optionally without the headings of its code blocks."""

    found: list[str] = []
    fenced = False
    for line in text.split("\n"):
        if line.startswith("```"):
            fenced = not fenced
            continue
        match = HEADING.match(line)
        if match and not (outside_code and fenced):
            found.append(match.group(1))
    return found


def _standard_files() -> dict[str, str]:
    """Every Markdown file the template ships under `knowledge/`, by path relative to it."""

    return {path.relative_to(KNOWLEDGE).as_posix(): _read(path) for path in sorted(KNOWLEDGE.rglob("*.md"))}


class RulePreservationTests(unittest.TestCase):
    """The rule headings and error codes of `LIFECYCLE.md` and `SCHEMA.md` as of the commit in the fixture."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.expected = json.loads(RULES_FIXTURE.read_text(encoding="utf-8"))
        cls.files = _standard_files()
        cls.all_headings = {heading for text in cls.files.values() for heading in _headings(text)}
        cls.all_text = "\n".join(cls.files.values())

    def test_the_fixture_lists_both_files(self) -> None:
        self.assertEqual({"LIFECYCLE.md", "SCHEMA.md"}, set(self.expected["headings"]))
        self.assertEqual({"LIFECYCLE.md", "SCHEMA.md"}, set(self.expected["codes"]))
        for name in ("LIFECYCLE.md", "SCHEMA.md"):
            self.assertGreater(len(self.expected["headings"][name]), 40, name)
            self.assertGreater(len(self.expected["codes"][name]), 30, name)

    def test_every_rule_heading_of_the_two_files_before_the_split_appears_in_a_standard_file(self) -> None:
        for name, headings in self.expected["headings"].items():
            for heading in headings:
                with self.subTest(file=name, heading=heading):
                    self.assertIn(heading, self.all_headings)

    def test_every_error_code_of_the_two_files_before_the_split_appears_in_a_standard_file(self) -> None:
        for name, codes in self.expected["codes"].items():
            for code in codes:
                with self.subTest(file=name, code=code):
                    self.assertIn(f"`{code}`", self.all_text)

    def test_a_section_that_moved_lives_in_exactly_one_file_and_left_the_old_one(self) -> None:
        lifecycle = _headings(self.files["wiki/LIFECYCLE.md"], outside_code=True)
        schema = _headings(self.files["wiki/SCHEMA.md"], outside_code=True)
        for heading in MOVED_TO_ACTIONS:
            with self.subTest(heading=heading):
                self.assertNotIn(heading, lifecycle)
                holders = [path for path, text in self.files.items() if heading in _headings(text, outside_code=True)]
                self.assertEqual(["wiki/ACTIONS.md"], holders)
        for heading, relative in MOVED_TO_FORMAT.items():
            with self.subTest(heading=heading):
                self.assertNotIn(heading, schema)
                holders = [path for path, text in self.files.items() if heading in _headings(text, outside_code=True)]
                self.assertEqual([f"wiki/{relative}"], holders)

    def test_the_rule_sections_that_stayed_are_still_where_they_were(self) -> None:
        for name in ("LIFECYCLE.md", "SCHEMA.md"):
            moved = set(MOVED_TO_ACTIONS) | set(MOVED_TO_FORMAT)
            stayed = [heading for heading in _headings(_read(WIKI_TEMPLATE / name), outside_code=True) if heading in set(self.expected["headings"][name]) - moved]
            self.assertGreater(len(stayed), 10, name)

    def test_schema_lists_every_page_kind_with_a_link_to_its_format(self) -> None:
        schema = _read(WIKI_TEMPLATE / "SCHEMA.md")
        formats = sorted(path.relative_to(WIKI_TEMPLATE).as_posix() for path in WIKI_TEMPLATE.glob("*/_FORMAT.md"))
        self.assertGreaterEqual(len(formats), 13)
        for relative in formats:
            with self.subTest(format=relative):
                self.assertEqual(1, schema.count(f"[`{relative}`]({relative})"))

    def test_lifecycle_links_the_action_registry_wherever_a_section_names_an_action(self) -> None:
        names = set()
        for spec in ACTION_SPECS:
            if spec.subject == "feature":
                names.update((spec.action, spec.command))
        names.discard("operation-repair")
        pattern = re.compile(r"(?<![\w-])(" + "|".join(sorted(map(re.escape, names), key=len, reverse=True)) + r")(?![\w-])")
        sections: list[tuple[str, list[str]]] = [("(top)", [])]
        fenced = False
        for line in _read(WIKI_TEMPLATE / "LIFECYCLE.md").split("\n"):
            if line.startswith("```"):
                fenced = not fenced
            if not fenced and HEADING.match(line):
                sections.append((line, []))
                continue
            sections[-1][1].append(line)
        named = 0
        for heading, body in sections:
            text = "\n".join(body)
            found = sorted(set(pattern.findall(text)))
            if not found:
                continue
            named += 1
            with self.subTest(section=heading, actions=found):
                self.assertIn("](ACTIONS.md)", text)
        self.assertGreater(named, 8)


class PointerTests(unittest.TestCase):
    def test_each_file_points_at_the_other(self) -> None:
        schema = (WIKI_TEMPLATE / "SCHEMA.md").read_text(encoding="utf-8")
        lifecycle = (WIKI_TEMPLATE / "LIFECYCLE.md").read_text(encoding="utf-8")
        actions = (WIKI_TEMPLATE / "ACTIONS.md").read_text(encoding="utf-8")
        introduction = " ".join(_after_front_matter(schema).split("---")[0].split())
        self.assertIn("`LIFECYCLE.md` holds the feature, board and advisory protocol", introduction)
        self.assertIn("`ACTIONS.md` holds the lifecycle action registry", introduction)
        self.assertIn("This file extends `SCHEMA.md`, which is read first.", " ".join(_after_front_matter(lifecycle).split("---")[0].split()))
        self.assertIn("(ACTIONS.md)", " ".join(_after_front_matter(lifecycle).split("---")[0].split()))
        self.assertIn("This file extends `SCHEMA.md` and `LIFECYCLE.md`, which are read first.", " ".join(_after_front_matter(actions).split("---")[0].split()))
        # The lifecycle protocol never points at itself as "this schema", and the core never claims lifecycle sections.
        self.assertNotIn("read this schema,", lifecycle)
        for heading in ("### Lifecycle action registry", "### Status and owner lifecycle", "## Feature page format"):
            self.assertNotIn(heading, schema)
        for heading in ("### Lifecycle action registry", "### Status and owner lifecycle"):
            self.assertNotIn(heading, actions)

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

    def test_the_guidance_that_names_the_lifecycle_actions_also_names_the_action_registry(self) -> None:
        template = REPO_ROOT / "template"
        for path in (template / "AGENTS.md.jinja", template / "README.md.jinja", template / "docs" / "ai-agents.md.jinja", template / "docs" / "README.md.jinja", template / "knowledge" / "wiki" / "CONNECTED.md"):
            with self.subTest(path=path.relative_to(REPO_ROOT).as_posix()):
                self.assertIn("ACTIONS.md", path.read_text(encoding="utf-8"))

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

    def test_exactly_the_skills_that_run_a_registry_action_reference_the_action_registry(self) -> None:
        action_skills = {spec.command for spec in ACTION_SPECS if spec.subject == "feature"}
        packaged = {listed["name"] for listed in list_skills()}
        expected = action_skills & packaged
        self.assertTrue({"po-specify", "po-handoff", "design-start", "dev-done", "qa-pass", "feature-reopen", "feature-scope"} <= expected)
        referencing = set()
        for listed in list_skills():
            skill = get_skill(listed["name"])
            paths = [item["path"] for item in skill["references"]]
            if ACTIONS_REFERENCE in paths:
                referencing.add(listed["name"])
                with self.subTest(skill=listed["name"]):
                    self.assertIn("knowledge/wiki/LIFECYCLE.md", paths)
                    self.assertIn("ACTIONS", skill["instructions"])
        self.assertEqual(expected, referencing)


if __name__ == "__main__":
    unittest.main()
