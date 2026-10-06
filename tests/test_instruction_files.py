"""One source of agent instructions in a generated workspace: AGENTS.md holds the rules, CLAUDE.md imports it."""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from prism_cli.wiki_index import is_project_doc_target, parse_index_entries
from prism_cli.wiki_lint import lint_wiki
from tests import real_temp  # noqa: F401

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = REPO_ROOT / "template"
APPS = ("backend", "web-user-app", "web-admin-portal", "mobile-android", "mobile-ios")
IMPORT_LINE = "@AGENTS.md"

# Rules that must be written once across a folder's AGENTS.md and CLAUDE.md, with whitespace collapsed.
ROOT_RULES = (
    "**Do not implement features without a wiki page.**",
    "there is no second board approval queue",
    "a human performs `po-handoff`, `design-start` and `dev-start` directly after reviewing the exact changes",
    "Wiki pages state the current state and carry no date about the page itself.",
    "an incoming source that contradicts a page is quarantined with a `CONFLICT.md`",
    "no action is a generic status setter",
    "Generated projects must not hard-depend on an installed Prism CLI.",
    "at most 2 more times, and never widen the change",
    "Mark each claim Decided, Observed, Proposed, Assumed or Unknown",
    "**API-first**: Define endpoints in OpenAPI -> generate clients -> implement",
    "Separate facts from advice in every response.",
)
STACK_RULES = {
    "backend": (
        "`controller -> repository` imports (controllers call services, never repositories directly)",
        "Spring beans must inject `tools.jackson.databind.ObjectMapper`",
        "`runBlocking` in MVC controllers",
    ),
    "web-user-app": ("Keep dashboard routes product-focused, not admin-focused.",),
    "web-admin-portal": ("Treat role checks and audit visibility as first-class requirements.",),
    "mobile-android": (
        "`AppResult<T>` instead of `kotlin.Result`",
        "Cleartext HTTP is allowed only in debug builds",
        "update `docs/networking-and-di.md`",
    ),
    "mobile-ios": (
        "ViewModels that drive SwiftUI state should be `@MainActor @Observable` by default.",
        "Keep the Claude project skills in `.claude/skills/` semantically aligned with these Codex skills",
    ),
}


def flat(text: str) -> str:
    return " ".join(text.split())


class TemplateSourceTests(unittest.TestCase):
    """The template files, without generating a workspace."""

    def test_there_is_no_context_file_in_the_template(self) -> None:
        self.assertFalse((TEMPLATE / "CONTEXT.md.jinja").exists())
        self.assertFalse((TEMPLATE / "CONTEXT.md").exists())

    def test_every_claude_file_imports_the_agents_file_next_to_it(self) -> None:
        claude_files = sorted(TEMPLATE.glob("CLAUDE.md.jinja")) + sorted(TEMPLATE.glob("*/CLAUDE.md.jinja"))
        self.assertEqual(1 + len(APPS), len(claude_files))
        for path in claude_files:
            with self.subTest(path=path.relative_to(TEMPLATE).as_posix()):
                self.assertTrue((path.parent / "AGENTS.md.jinja").is_file())
                text = path.read_text(encoding="utf-8")
                self.assertEqual(IMPORT_LINE, text.splitlines()[0])
                self.assertEqual(1, text.count(IMPORT_LINE))

    def test_the_root_claude_file_is_only_the_import(self) -> None:
        self.assertEqual(IMPORT_LINE + "\n", (TEMPLATE / "CLAUDE.md.jinja").read_text(encoding="utf-8"))

    def test_the_cursor_rules_are_the_project_pointer_and_the_scoped_stack_rules(self) -> None:
        rules = sorted(path.name for path in (TEMPLATE / ".cursor" / "rules").iterdir())
        self.assertEqual(
            [
                "advisory-review.mdc.jinja",
                "api-conventions.mdc.jinja",
                "backend.mdc.jinja",
                "mobile-android.mdc.jinja",
                "mobile-ios.mdc.jinja",
                "project.mdc.jinja",
                "web.mdc.jinja",
            ],
            rules,
        )
        project = (TEMPLATE / ".cursor" / "rules" / "project.mdc.jinja").read_text(encoding="utf-8")
        self.assertTrue(project.startswith("---\nalwaysApply: true\n---\n"))
        self.assertEqual(1, project.count("@AGENTS.md"))

    def test_the_instruction_guidance_no_longer_names_the_context_file(self) -> None:
        for path in sorted(TEMPLATE.rglob("*")):
            if not path.is_file() or path.suffix in {".png", ".jar", ".ico"}:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            with self.subTest(path=path.relative_to(TEMPLATE).as_posix()):
                self.assertNotIn("CONTEXT.md", text)


@unittest.skipUnless(shutil.which("copier"), "Copier is required for rendered template checks")
class GeneratedInstructionTests(unittest.TestCase):
    """A generated workspace with all five apps."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory(prefix="prism-instruction-files-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name) / "generated"
        result = subprocess.run(
            [
                "copier",
                "copy",
                "--trust",
                "--vcs-ref",
                "HEAD",
                "--defaults",
                "--data",
                "project_name=Instruction Files",
                "--data",
                "project_slug=instruction-files",
                "--data",
                f"platforms=[{', '.join(APPS)}]",
                "--data",
                "auth_methods=[password]",
                str(REPO_ROOT),
                str(cls.root),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            raise AssertionError(f"Copier generation failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")

    def text(self, relative: str) -> str:
        return (self.root / relative).read_text(encoding="utf-8")

    def test_there_is_no_context_file_and_nothing_names_one(self) -> None:
        self.assertFalse((self.root / "CONTEXT.md").exists())
        for path in sorted(self.root.rglob("*.md")):
            with self.subTest(path=path.relative_to(self.root).as_posix()):
                self.assertNotIn("CONTEXT.md", path.read_text(encoding="utf-8"))

    def test_claude_files_import_agents_files_and_the_root_one_is_only_the_import(self) -> None:
        self.assertEqual(IMPORT_LINE + "\n", self.text("CLAUDE.md"))
        for app in APPS:
            with self.subTest(app=app):
                claude = self.text(f"{app}/CLAUDE.md")
                self.assertEqual(IMPORT_LINE, claude.splitlines()[0])
                self.assertTrue((self.root / app / "AGENTS.md").is_file())
        for path in sorted(self.root.glob("**/CLAUDE.md")):
            if "node_modules" in path.parts:
                continue
            with self.subTest(path=path.relative_to(self.root).as_posix()):
                for line in path.read_text(encoding="utf-8").splitlines():
                    if line.startswith("@"):
                        self.assertTrue((path.parent / line[1:]).is_file(), f"the import {line} must resolve next to {path.name}")

    def test_each_root_rule_appears_exactly_once_across_agents_and_claude(self) -> None:
        combined = flat(self.text("AGENTS.md") + "\n" + self.text("CLAUDE.md"))
        for rule in ROOT_RULES:
            with self.subTest(rule=rule):
                self.assertEqual(1, combined.count(rule))

    def test_each_platform_rule_appears_exactly_once_across_its_agents_and_claude_files(self) -> None:
        root = flat(self.text("AGENTS.md"))
        for app, rules in STACK_RULES.items():
            combined = flat(self.text(f"{app}/AGENTS.md") + "\n" + self.text(f"{app}/CLAUDE.md"))
            for rule in rules:
                with self.subTest(app=app, rule=rule):
                    self.assertEqual(1, combined.count(rule))
                    self.assertNotIn(rule, root, "a platform rule is not repeated in the root file")

    def test_no_long_line_is_repeated_between_the_files_a_tool_loads_together(self) -> None:
        # Working in a platform folder loads the root files and that folder's two files.
        repeated: list[str] = []
        for app in APPS:
            seen: dict[str, str] = {}
            for relative in ("AGENTS.md", "CLAUDE.md", f"{app}/AGENTS.md", f"{app}/CLAUDE.md"):
                lines = {flat(line) for line in self.text(relative).splitlines() if len(flat(line)) >= 60 and not line.startswith(("|", "- `", "```"))}
                for line in lines:
                    if line in seen:
                        repeated.append(f"{relative} repeats a line of {seen[line]}: {line[:80]}")
                    seen[line] = relative
        self.assertEqual([], repeated)

    def test_root_guidance_leaves_room_for_the_largest_platform_file_under_the_codex_limit(self) -> None:
        # Codex concatenates AGENTS.md from the repository root down and stops at 32 KiB.
        root = len(self.text("AGENTS.md").encode("utf-8"))
        largest = max(len(self.text(f"{app}/AGENTS.md").encode("utf-8")) for app in APPS)
        self.assertLess(root + largest, 32 * 1024)

    def test_the_cursor_rules_point_at_the_source_and_repeat_none_of_it(self) -> None:
        rules = self.root / ".cursor" / "rules"
        self.assertFalse((rules / "wiki.mdc").exists())
        project = (rules / "project.mdc").read_text(encoding="utf-8")
        self.assertIn("alwaysApply: true", project)
        self.assertEqual(1, project.count("@AGENTS.md"))
        agents_lines = {flat(line) for line in self.text("AGENTS.md").splitlines() if len(flat(line)) >= 60}
        for path in sorted(rules.glob("*.mdc")):
            with self.subTest(rule=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertTrue(text.startswith("---\n"))
                self.assertNotIn("{{", text)
                repeated = [line for line in (flat(item) for item in text.splitlines()) if line in agents_lines]
                self.assertEqual([], repeated)
        for name, folders in (
            ("backend.mdc", ("backend",)),
            ("mobile-android.mdc", ("mobile-android",)),
            ("mobile-ios.mdc", ("mobile-ios",)),
            ("web.mdc", ("web-user-app", "web-admin-portal")),
        ):
            with self.subTest(scoped=name):
                globs = re.search(r'^globs: "([^"]+)"', (rules / name).read_text(encoding="utf-8"), re.M)
                self.assertIsNotNone(globs)
                self.assertEqual(sorted(f"{folder}/**" for folder in folders), sorted(globs.group(1).split(",")))
                for folder in folders:
                    self.assertTrue((self.root / folder).is_dir())

    def test_every_docs_page_is_listed_in_the_wiki_index_and_lint_is_clean(self) -> None:
        index = self.text("knowledge/wiki/index.md")
        listed = [entry.target for entry in parse_index_entries(index) if is_project_doc_target(entry.target)]
        docs = sorted(f"../../docs/{path.relative_to(self.root / 'docs').as_posix()}" for path in (self.root / "docs").rglob("*.md"))
        self.assertGreaterEqual(len(docs), 5)
        self.assertEqual(docs, sorted(listed))
        self.assertEqual(len(listed), len(set(listed)), "one line per docs page")
        for target in listed:
            self.assertTrue((self.root / "knowledge" / "wiki" / target).resolve().is_file(), target)
        result = lint_wiki(self.root)
        self.assertEqual([], [(item.code, item.message) for item in result.diagnostics])

    def test_the_readme_carries_the_overview_that_the_context_file_held(self) -> None:
        readme = self.text("README.md")
        for term in ("Working With AI Agents", "Claude Code:", "Codex:", "Cursor:", "`setup-project`", "`po-intake [folder]`", "AGENTS.md"):
            self.assertIn(term, readme)
        self.assertIn("`$endpoint`", readme)

    def test_the_manifest_expects_the_instruction_files_that_exist(self) -> None:
        manifest = self.text("prism.workspace.yml")
        self.assertNotIn("CONTEXT.md", manifest)
        for relative in ("AGENTS.md", "CLAUDE.md", ".cursor/rules", "README.md"):
            self.assertIn(relative, manifest)
            self.assertTrue((self.root / relative).exists(), relative)


if __name__ == "__main__":
    unittest.main()
