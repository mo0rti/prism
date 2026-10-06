"""Every skill is written once in template-skills/ and generated into the layout of each tool.

The source tests need no Copier. The discovery tests generate a workspace through the CLI, once with all
five apps and once with one app, and check how Codex, Claude Code and Cursor each find the skills.
"""

from __future__ import annotations

import importlib.util
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

import yaml

from prism_cli import cli
from tests import real_temp  # noqa: F401
from tests.layered_support import generate_default_apps

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = REPO_ROOT / "template"
ALL_APPS = ("backend", "web-user-app", "web-admin-portal", "mobile-android", "mobile-ios")
ONE_APP = ("backend",)
SKILL_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
CODEX_INTERFACE_KEYS = {"display_name", "short_description", "icon_small", "icon_large", "brand_color", "default_prompt"}
CLAUDE_SKILL_KEYS = {
    "name",
    "description",
    "when_to_use",
    "argument-hint",
    "arguments",
    "disable-model-invocation",
    "user-invocable",
    "allowed-tools",
    "disallowed-tools",
    "model",
    "effort",
    "context",
    "agent",
    "background",
    "hooks",
    "paths",
    "shell",
    "metadata",
    "license",
    "compatibility",
}
CLAUDE_BOOLEAN_KEYS = ("disable-model-invocation", "user-invocable", "background")
# Placeholders the guidance writes in place of a skill name.
PLACEHOLDER_NAMES = {"operation"}


def load_generator():
    spec = importlib.util.spec_from_file_location("build_skill_layers", REPO_ROOT / "scripts" / "build-skill-layers.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["build_skill_layers"] = module
    spec.loader.exec_module(module)
    return module


GENERATOR = load_generator()


def front_matter(text: str, label: str) -> dict:
    match = re.match(r"---\n(.*?)\n---\n", text.replace("\r\n", "\n"), re.DOTALL)
    if not match:
        raise AssertionError(f"{label} has no front matter")
    data = yaml.safe_load(match.group(1))
    if not isinstance(data, dict):
        raise AssertionError(f"{label} front matter is not a mapping")
    return data


def write_source(root: Path, name: str, front: str, body: str) -> None:
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "skill.md").write_text("---\n" + textwrap.dedent(front).strip("\n") + "\n---\n\n" + textwrap.dedent(body).strip("\n") + "\n", encoding="utf-8", newline="\n")


class GeneratorTests(unittest.TestCase):
    """The generator and its source format."""

    def test_the_generated_layers_match_their_sources(self) -> None:
        skills = GENERATOR.load_sources()
        self.assertEqual([], GENERATOR.differences(skills))

    def test_the_check_command_passes_on_this_repository(self) -> None:
        result = subprocess.run(
            [sys.executable, "-B", str(REPO_ROOT / "scripts" / "build-skill-layers.py"), "--check"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("PASS", result.stdout)

    def test_a_layer_file_edited_without_its_source_fails_the_check(self) -> None:
        skills = GENERATOR.load_sources()
        with tempfile.TemporaryDirectory(prefix="prism-skill-layers-") as temporary:
            template = Path(temporary) / "template"
            for managed in GENERATOR.MANAGED_ROOTS:
                shutil.copytree(TEMPLATE / managed, template / managed)
            copier = Path(temporary) / "copier.yml"
            shutil.copyfile(REPO_ROOT / "copier.yml", copier)
            self.assertEqual([], GENERATOR.differences(skills, template, copier))

            codex = template / ".agents" / "skills" / "ask" / "SKILL.md.jinja"
            codex.write_text(codex.read_text(encoding="utf-8") + "\nAn edit that has no source.\n", encoding="utf-8")
            command = template / ".claude" / "commands" / "po-handoff.md.jinja"
            command.write_text(command.read_text(encoding="utf-8").replace("exactly one", "exactly two", 1), encoding="utf-8")
            cursor = template / ".cursor" / "rules" / "mobile-android.mdc.jinja"
            cursor.write_text(cursor.read_text(encoding="utf-8") + "- one more fact\n", encoding="utf-8")
            (template / ".agents" / "skills" / "ask" / "agents" / "openai.yaml").write_text("interface: {}\n", encoding="utf-8")
            reference = template / ".claude" / "skills" / "compose-design-system" / "references" / "compose-components.md"
            reference.write_text(reference.read_text(encoding="utf-8") + "extra\n", encoding="utf-8")
            problems = GENERATOR.differences(skills, template, copier)
            for path in (
                ".agents/skills/ask/SKILL.md.jinja",
                ".claude/commands/po-handoff.md.jinja",
                ".cursor/rules/mobile-android.mdc.jinja",
                ".agents/skills/ask/agents/openai.yaml",
                ".claude/skills/compose-design-system/references/compose-components.md",
            ):
                self.assertIn(f"differs from its source: template/{path}", problems)
            self.assertEqual(5, len(problems), problems)

    def test_a_missing_or_stale_layer_file_fails_the_check(self) -> None:
        skills = GENERATOR.load_sources()
        with tempfile.TemporaryDirectory(prefix="prism-skill-layers-") as temporary:
            template = Path(temporary) / "template"
            for managed in GENERATOR.MANAGED_ROOTS:
                shutil.copytree(TEMPLATE / managed, template / managed)
            copier = Path(temporary) / "copier.yml"
            shutil.copyfile(REPO_ROOT / "copier.yml", copier)
            (template / ".claude" / "commands" / "ask.md.jinja").unlink()
            (template / ".claude" / "skills" / "orphan").mkdir()
            (template / ".claude" / "skills" / "orphan" / "SKILL.md.jinja").write_text("---\nname: orphan\ndescription: no source\n---\n", encoding="utf-8")
            (template / ".cursor" / "rules" / "project.mdc.jinja").write_text("---\nalwaysApply: true\n---\n@AGENTS.md\n", encoding="utf-8")
            problems = GENERATOR.differences(skills, template, copier)
            self.assertIn("missing: template/.claude/commands/ask.md.jinja", problems)
            self.assertIn("no source produces: template/.claude/skills/orphan/SKILL.md.jinja", problems)
            self.assertIn("no source produces: template/.cursor/rules/project.mdc.jinja", problems)
            self.assertEqual(3, len(problems), problems)

    def test_a_hand_edited_exclude_block_fails_the_check(self) -> None:
        skills = GENERATOR.load_sources()
        with tempfile.TemporaryDirectory(prefix="prism-skill-layers-") as temporary:
            template = Path(temporary) / "template"
            for managed in GENERATOR.MANAGED_ROOTS:
                shutil.copytree(TEMPLATE / managed, template / managed)
            copier = Path(temporary) / "copier.yml"
            text = (REPO_ROOT / "copier.yml").read_text(encoding="utf-8")
            copier.write_text(text.replace(".agents/skills/android-testing", ".agents/skills/android-testing-x", 1), encoding="utf-8")
            self.assertEqual(["differs from its sources: the generated _exclude block of copier.yml"], GENERATOR.differences(skills, template, copier))

    def test_the_exclude_block_keeps_the_stack_conditions(self) -> None:
        lines = GENERATOR.exclude_lines(GENERATOR.load_sources())

        def condition(path: str, *items: str, variable: str = "stacks") -> str:
            test = " and ".join(f"'{item}' not in {variable}" for item in items)
            return f'  - "{{% if prism_layer == \'workspace\' and {test} %}}{path}{{% endif %}}"'

        for layer in (".agents/skills", ".claude/skills"):
            for name in ("android-build-verify", "android-contract-alignment", "android-conventions", "android-feature-delivery", "android-testing", "compose-design-system"):
                self.assertIn(condition(f"{layer}/{name}", "android-compose"), lines)
            for name in ("ios-build-verify", "ios-contract-alignment", "ios-conventions", "ios-feature-delivery", "ios-testing", "swiftui-design-system"):
                self.assertIn(condition(f"{layer}/{name}", "ios-swiftui"), lines)
        self.assertIn(condition(".claude/skills/deploy-device", "android-compose", "ios-swiftui"), lines)
        # The backend's Cursor rule belongs to its pack, per app, so no source and no exclusion names it.
        self.assertFalse([line for line in lines if ".cursor/rules/backend.mdc" in line])
        self.assertIn(condition(".cursor/rules/web.mdc", "nextjs-web"), lines)
        self.assertIn(condition(".cursor/rules/mobile-android.mdc", "android-compose"), lines)
        self.assertIn(condition(".cursor/rules/mobile-ios.mdc", "ios-swiftui"), lines)
        for layer in (".agents/skills", ".claude/skills"):
            base = f"{layer}/deployment/references"
            self.assertIn(condition(f"{base}/azure", "spring-backend"), lines)
            self.assertIn(condition(f"{base}/azure-setup.md", "spring-backend"), lines)
            self.assertIn(condition(f"{base}/cloudflare", "nextjs-web"), lines)
            self.assertIn(condition(f"{base}/cloudflare/wrangler.web-user-app.jsonc", "web-user-app", variable="app_ids"), lines)
            self.assertIn(condition(f"{base}/cloudflare/wrangler.web-admin-portal.jsonc", "web-admin-portal", variable="app_ids"), lines)
            self.assertIn(condition(f"{base}/mobile-store-release.md", "android-compose", "ios-swiftui"), lines)
        # Skills that ship with every workspace carry no condition.
        self.assertFalse([line for line in lines if "/ask" in line or "board-review" in line or "advisory-review" in line or "api-conventions" in line])

    def test_the_catalog_ships_each_workflow_skill_to_codex_and_claude_commands(self) -> None:
        asset_spec = importlib.util.spec_from_file_location("build_workflow_assets", REPO_ROOT / "scripts" / "build-workflow-assets.py")
        assets = importlib.util.module_from_spec(asset_spec)
        asset_spec.loader.exec_module(assets)
        by_name = {skill.name: skill for skill in GENERATOR.load_sources()}
        for name in assets.SKILL_NAMES:
            with self.subTest(skill=name):
                self.assertTrue(by_name[name].has("codex"))
                self.assertTrue(by_name[name].has("command"))
        for name in ("document-entity", "generate-clients"):
            self.assertTrue(by_name[name].has("codex") and by_name[name].has("command"))
        self.assertEqual({"codex", "command", "claude-skill", "cursor"}, set(by_name["board-review"].layers))
        self.assertEqual("advisory-review", by_name["board-review"].cursor_file)

    def test_an_invocation_takes_the_form_of_each_host(self) -> None:
        with tempfile.TemporaryDirectory(prefix="prism-skill-sources-") as temporary:
            root = Path(temporary)
            write_source(
                root,
                "demo",
                """
                name: demo
                description: A demo.
                layers: [codex, command, claude-skill, cursor]
                codex: {display_name: Demo, short_description: Demo, default_prompt: Use @@invoke:demo@@ now., implicit: true}
                cursor: {always-apply: false}
                """,
                """
                # Demo

                Run `@@invoke:demo@@` or use `@@invoke:other@@`.

                ::: only codex
                Codex line.
                :::
                ::: only claude
                Claude line.
                :::
                ::: only command, cursor
                Command or Cursor line.
                :::
                Shared line.
                """,
            )
            write_source(
                root,
                "other",
                """
                name: other
                description: Another.
                layers: [codex, command, claude-skill]
                codex: {display_name: Other, short_description: Other, default_prompt: Use it., implicit: false}
                """,
                "# Other\n\nBody.",
            )
            skills = GENERATOR.load_sources(root)
            files = GENERATOR.render_layers(skills)
            text = {path: data.decode("utf-8") for path, data in files.items()}
            codex = text[".agents/skills/demo/SKILL.md.jinja"]
            self.assertIn("Run `$demo` or use `$other`.", codex)
            self.assertIn("Codex line.", codex)
            self.assertNotIn("Claude line.", codex)
            self.assertNotIn("Command or Cursor line.", codex)
            self.assertIn('default_prompt: "Use $demo now."', text[".agents/skills/demo/agents/openai.yaml"])
            command = text[".claude/commands/demo.md.jinja"]
            self.assertIn("Run `/demo` or use `/other`.", command)
            self.assertIn("Claude line.", command)
            self.assertIn("Command or Cursor line.", command)
            self.assertNotIn("Codex line.", command)
            self.assertFalse(command.replace(command.split("\n", 1)[0], "").lstrip().startswith("---"), "a command has no front matter unless its source asks for it")
            claude_skill = text[".claude/skills/demo/SKILL.md.jinja"]
            self.assertIn("Run `demo` or use `other`.", claude_skill)
            self.assertIn("Claude line.", claude_skill)
            self.assertNotIn("Command or Cursor line.", claude_skill)
            cursor = text[".cursor/rules/demo.mdc.jinja"]
            self.assertIn("alwaysApply: false", cursor)
            self.assertIn("Run `demo` or use `other`.", cursor)
            self.assertIn("Command or Cursor line.", cursor)
            for rendered in text.values():
                self.assertNotIn("@@", rendered)
                self.assertNotIn(":::", rendered)

    def test_a_broken_source_is_rejected(self) -> None:
        good = textwrap.dedent(
            """
            name: demo
            description: A demo.
            layers: [codex]
            codex: {display_name: Demo, short_description: Demo, default_prompt: Use it., implicit: true}
            """
        ).strip()
        cases = {
            "unknown layer": (good.replace("[codex]", "[codex, vscode]"), "# Demo\n\nBody.", "layers must be"),
            "folder name": (good.replace("name: demo", "name: other"), "# Demo\n\nBody.", "name must equal"),
            "missing codex fields": (good.replace("short_description: Demo, ", ""), "# Demo\n\nBody.", "codex needs"),
            "unknown key": (good + "\nflavour: x", "# Demo\n\nBody.", "unknown front matter keys"),
            "bad stack": (good + "\nstacks: [watchos]", "# Demo\n\nBody.", "stacks must be"),
            "bad reference app": (good + "\nreference-apps: {references/extra: [watchos]}", "# Demo\n\nBody.", "reference-apps[references/extra] must be"),
            "the retired platforms key": (good + "\nplatforms: [backend]", "# Demo\n\nBody.", "unknown front matter keys"),
            "unclosed block": (good, "# Demo\n\n::: only codex\nText.\n", "not closed"),
            "stray close": (good, "# Demo\n\n:::\n", "without an open block"),
            "unknown layer in block": (good, "# Demo\n\n::: only vscode\nText.\n:::\n", "unknown layer"),
            "unknown token": (good, "# Demo\n\n@@wat:demo@@\n", "'@@' token"),
            "missing invoke target": (good, "# Demo\n\n@@invoke:ghost@@\n", "names no skill"),
            "cursor needs a scope": (good.replace("[codex]", "[codex, cursor]"), "# Demo\n\nBody.", "exactly one of globs or always-apply"),
            "empty body": (good, "", "body is empty"),
        }
        for label, (front, body, message) in cases.items():
            with self.subTest(case=label), tempfile.TemporaryDirectory(prefix="prism-skill-sources-") as temporary:
                root = Path(temporary)
                if label == "empty body":
                    folder = root / "demo"
                    folder.mkdir()
                    (folder / "skill.md").write_text("---\n" + textwrap.dedent(front).strip("\n") + "\n---\n", encoding="utf-8")
                else:
                    write_source(root, "demo", front, body)
                with self.assertRaises(GENERATOR.SkillError) as raised:
                    GENERATOR.render_layers(GENERATOR.load_sources(root))
                self.assertIn(message, str(raised.exception))

    def test_references_are_carried_to_both_skill_folders_and_need_a_skill_layer(self) -> None:
        with tempfile.TemporaryDirectory(prefix="prism-skill-sources-") as temporary:
            root = Path(temporary)
            write_source(
                root,
                "demo",
                """
                name: demo
                description: A demo.
                layers: [codex, claude-skill]
                stacks: [spring-backend]
                reference-stacks: {references/extra: [ios-swiftui]}
                reference-apps: {references/extra: [web-user-app]}
                codex: {display_name: Demo, short_description: Demo, default_prompt: Use it., implicit: true}
                """,
                "# Demo\n\nBody.",
            )
            (root / "demo" / "references" / "extra").mkdir(parents=True)
            (root / "demo" / "references" / "extra" / "notes.md").write_text("Notes.\r\n", encoding="utf-8", newline="")
            skills = GENERATOR.load_sources(root)
            files = GENERATOR.render_layers(skills)
            self.assertEqual(b"Notes.\n", files[".agents/skills/demo/references/extra/notes.md"])
            self.assertEqual(files[".agents/skills/demo/references/extra/notes.md"], files[".claude/skills/demo/references/extra/notes.md"])
            lines = GENERATOR.exclude_lines(skills)
            self.assertIn("  - \"{% if prism_layer == 'workspace' and 'spring-backend' not in stacks %}.agents/skills/demo{% endif %}\"", lines)
            self.assertIn("  - \"{% if prism_layer == 'workspace' and 'ios-swiftui' not in stacks %}.claude/skills/demo/references/extra{% endif %}\"", lines)
            self.assertIn("  - \"{% if prism_layer == 'workspace' and 'web-user-app' not in app_ids %}.claude/skills/demo/references/extra{% endif %}\"", lines)
        with tempfile.TemporaryDirectory(prefix="prism-skill-sources-") as temporary:
            root = Path(temporary)
            write_source(
                root,
                "ruleonly",
                """
                name: ruleonly
                description: A rule.
                layers: [cursor]
                cursor: {globs: "x/**"}
                """,
                "# Rule\n\nBody.",
            )
            (root / "ruleonly" / "references").mkdir()
            (root / "ruleonly" / "references" / "notes.md").write_text("Notes.\n", encoding="utf-8")
            with self.assertRaises(GENERATOR.SkillError):
                GENERATOR.load_sources(root)


def owner(skills, rendered: str):
    """The skill whose source produces this rendered file."""

    for skill in skills:
        owned = (
            f".agents/skills/{skill.name}/",
            f".claude/skills/{skill.name}/",
            f".claude/commands/{skill.name}.md",
            f".cursor/rules/{skill.cursor_file}.mdc",
        )
        if any(rendered == item or rendered.startswith(item) for item in owned):
            return skill
    raise AssertionError(f"no source produces {rendered}")


STACK_OF_APP = {"backend": "spring-backend", "web-user-app": "nextjs-web", "web-admin-portal": "nextjs-web", "mobile-android": "android-compose", "mobile-ios": "ios-swiftui"}
# The Cursor rule of a pack's app is the pack's own file, so no skill source names it.
PACK_APP_RULES = {".cursor/rules/backend.mdc"}


def rendered_names(skills, app_ids) -> set[str]:
    """The files a workspace with these apps carries in the four managed folders, by their rendered names."""

    stacks = {STACK_OF_APP[app] for app in app_ids}
    names: set[str] = set()
    for path in GENERATOR.render_layers(skills):
        rendered = path[: -len(".jinja")] if path.endswith(".jinja") else path
        skill = owner(skills, rendered)
        if skill.stacks and not set(skill.stacks) & stacks:
            continue
        skipped = False
        for scopes, present in ((skill.reference_stacks, stacks), (skill.reference_apps, set(app_ids))):
            for relative, only in scopes.items():
                for folder in (".agents/skills", ".claude/skills"):
                    base = f"{folder}/{skill.name}/{relative}"
                    if (rendered == base or rendered.startswith(base + "/")) and not set(only) & present:
                        skipped = True
        if not skipped:
            names.add(rendered)
    return names


class RenderedWorkspace:
    """Mixin for the discovery tests: one render per class, through the CLI."""

    app_ids: tuple[str, ...] = ALL_APPS
    root: Path
    skills: list

    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory(prefix="prism-skill-discovery-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name) / "generated"
        cls.skills = GENERATOR.load_sources()
        generate_default_apps(cls.root, list(cls.app_ids), Path(cls.temporary.name), project_name="Skill Discovery", auth_methods=["password"])

    def files(self, *folders: str) -> set[str]:
        found: set[str] = set()
        for folder in folders:
            base = self.root / folder
            if base.is_dir():
                found.update(path.relative_to(self.root).as_posix() for path in base.rglob("*") if path.is_file())
        return found

    # ------------------------------------------------------------------ Codex

    def test_codex_finds_every_skill_with_its_front_matter_and_interface(self) -> None:
        base = self.root / ".agents" / "skills"
        folders = sorted(path for path in base.iterdir() if path.is_dir())
        self.assertTrue(folders)
        for folder in folders:
            with self.subTest(skill=folder.name):
                self.assertTrue(SKILL_NAME.match(folder.name) and len(folder.name) <= 64)
                skill_file = folder / "SKILL.md"
                self.assertTrue(skill_file.is_file(), "SKILL.md is the file Codex loads")
                meta = front_matter(skill_file.read_text(encoding="utf-8"), f"{folder.name}/SKILL.md")
                self.assertEqual({"name", "description"}, set(meta))
                self.assertEqual(folder.name, meta["name"])
                self.assertIsInstance(meta["description"], str)
                self.assertTrue(meta["description"].strip())
                self.assertLessEqual(len(meta["description"]), 1024)
                self.assertNotIn("\n", meta["description"])
                interface_file = folder / "agents" / "openai.yaml"
                self.assertTrue(interface_file.is_file(), "every skill declares its interface")
                data = yaml.safe_load(interface_file.read_text(encoding="utf-8"))
                self.assertEqual({"interface", "policy"}, set(data))
                interface = data["interface"]
                self.assertTrue({"display_name", "short_description", "default_prompt"} <= set(interface))
                self.assertLessEqual(set(interface), CODEX_INTERFACE_KEYS)
                for key in ("display_name", "short_description", "default_prompt"):
                    self.assertIsInstance(interface[key], str)
                    self.assertTrue(interface[key].strip())
                self.assertIn(f"${folder.name}", interface["default_prompt"])
                self.assertEqual({"allow_implicit_invocation"}, set(data["policy"]))
                self.assertIsInstance(data["policy"]["allow_implicit_invocation"], bool)

    def test_codex_skill_references_exist(self) -> None:
        for skill_file in sorted((self.root / ".agents" / "skills").glob("*/SKILL.md")):
            text = skill_file.read_text(encoding="utf-8")
            for reference in sorted(set(re.findall(r"references/[A-Za-z0-9_./-]+\.[A-Za-z0-9]+", text))):
                with self.subTest(skill=skill_file.parent.name, reference=reference):
                    self.assertTrue((skill_file.parent / reference).is_file())

    # ------------------------------------------------------------------ Claude Code

    def test_claude_code_finds_every_command_at_its_path(self) -> None:
        base = self.root / ".claude" / "commands"
        entries = sorted(base.iterdir())
        self.assertTrue(entries)
        for path in entries:
            with self.subTest(command=path.name):
                self.assertTrue(path.is_file(), "commands are flat files")
                self.assertTrue(path.name.endswith(".md"))
                self.assertTrue(SKILL_NAME.match(path.name[:-3]))
                text = path.read_text(encoding="utf-8")
                self.assertTrue(text.strip())
                if text.startswith("---\n"):
                    meta = front_matter(text, path.name)
                    self.assertFalse({"name", "paths"} & set(meta), "a command takes its name from its file")

    def test_claude_code_finds_every_skill_with_the_front_matter_it_reads(self) -> None:
        base = self.root / ".claude" / "skills"
        folders = sorted(path for path in base.iterdir() if path.is_dir())
        self.assertTrue(folders)
        for folder in folders:
            with self.subTest(skill=folder.name):
                self.assertTrue(SKILL_NAME.match(folder.name))
                skill_file = folder / "SKILL.md"
                self.assertTrue(skill_file.is_file())
                meta = front_matter(skill_file.read_text(encoding="utf-8"), f"{folder.name}/SKILL.md")
                self.assertEqual(folder.name, meta["name"])
                self.assertIsInstance(meta["description"], str)
                self.assertTrue(meta["description"].strip())
                self.assertLessEqual(set(meta), CLAUDE_SKILL_KEYS)
                for key in CLAUDE_BOOLEAN_KEYS:
                    if key in meta:
                        self.assertIsInstance(meta[key], bool)
                for key in ("argument-hint", "allowed-tools"):
                    if key in meta:
                        self.assertIsInstance(meta[key], str)

    # ------------------------------------------------------------------ Cursor

    def test_cursor_finds_every_rule_with_valid_front_matter(self) -> None:
        base = self.root / ".cursor" / "rules"
        entries = sorted(base.iterdir())
        self.assertTrue(entries)
        self.assertFalse((base / "project.mdc").exists(), "Cursor reads AGENTS.md itself")
        for path in entries:
            with self.subTest(rule=path.name):
                self.assertTrue(path.name.endswith(".mdc"), "Cursor ignores a plain .md rule")
                text = path.read_text(encoding="utf-8")
                meta = front_matter(text, path.name)
                self.assertLessEqual(set(meta), {"description", "globs", "alwaysApply"})
                self.assertIsInstance(meta["description"], str)
                self.assertTrue(meta["description"].strip())
                if "globs" in meta:
                    self.assertNotIn("alwaysApply", meta)
                    self.assertIsInstance(meta["globs"], str)
                    for pattern in meta["globs"].split(","):
                        self.assertTrue(pattern.strip())
                else:
                    self.assertIsInstance(meta.get("alwaysApply"), bool)
                self.assertNotIn("{{", text)
                self.assertNotIn("@AGENTS.md", text)

    # ------------------------------------------------------------------ the layers agree

    def test_the_workspace_carries_exactly_the_files_the_sources_name(self) -> None:
        expected = rendered_names(self.skills, self.app_ids)
        actual = self.files(".agents/skills", ".claude/commands", ".claude/skills", ".cursor/rules") - PACK_APP_RULES
        self.assertEqual([], sorted(expected - actual), "a layer the sources claim is missing")
        self.assertEqual([], sorted(actual - expected), "a layer file has no source")

    def test_references_are_the_same_file_in_both_skill_folders(self) -> None:
        for skill in self.skills:
            if not (skill.has("codex") and skill.has("claude-skill")):
                continue
            codex = self.files(f".agents/skills/{skill.name}/references")
            claude = self.files(f".claude/skills/{skill.name}/references")
            self.assertEqual({path.replace(".agents/", ".claude/", 1) for path in codex}, claude)
            for path in sorted(codex):
                with self.subTest(file=path):
                    twin = self.root / path.replace(".agents/", ".claude/", 1)
                    self.assertEqual((self.root / path).read_text(encoding="utf-8").splitlines(), twin.read_text(encoding="utf-8").splitlines())

    def test_a_skill_listed_in_the_guidance_exists_in_the_layer_it_names(self) -> None:
        codex_names = {path.name for path in (self.root / ".agents" / "skills").iterdir() if path.is_dir()}
        command_names = {path.name[:-3] for path in (self.root / ".claude" / "commands").iterdir()}
        claude_skill_names = {path.name for path in (self.root / ".claude" / "skills").iterdir() if path.is_dir()}
        known = {skill.name for skill in self.skills if skill.has("codex") or skill.has("command") or skill.has("claude-skill")}
        documents = [self.root / "AGENTS.md", self.root / "CLAUDE.md", self.root / "README.md"]
        documents += sorted((self.root / "docs").glob("*.md"))
        for app in ALL_APPS:
            documents += [self.root / app / "AGENTS.md", self.root / app / "CLAUDE.md"]
        checked = 0
        for document in documents:
            if not document.is_file():
                continue
            text = document.read_text(encoding="utf-8")
            relative = document.relative_to(self.root).as_posix()
            for name in sorted(set(re.findall(r"`\$([a-z][a-z0-9-]*)(?=[ `])", text))):
                if name in PLACEHOLDER_NAMES:
                    continue
                checked += 1
                with self.subTest(document=relative, codex=name):
                    self.assertIn(name, codex_names, "guidance names a Codex skill that is not generated")
            for name in sorted(set(re.findall(r"`/([a-z][a-z0-9-]*)(?=[ `<\[])", text))):
                if name not in known:
                    continue
                checked += 1
                with self.subTest(document=relative, claude=name):
                    self.assertTrue(name in command_names or name in claude_skill_names, "guidance names a Claude command or skill that is not generated")
        self.assertGreater(checked, 20)

    def test_no_generated_layer_file_carries_a_source_mechanism_or_unrendered_jinja(self) -> None:
        for path in sorted(self.files(".agents/skills", ".claude/commands", ".claude/skills", ".cursor/rules")):
            if path.endswith((".sh", ".ts", ".example", ".jsonc")) or "/references/" in path:
                continue
            with self.subTest(file=path):
                text = (self.root / path).read_text(encoding="utf-8")
                self.assertNotIn("@@", text)
                self.assertNotIn("{%", text)
                self.assertNotIn("{#", text)
                self.assertNotIn("Generated from template-skills", text)
                self.assertFalse(re.search(r"(?m)^:::", text))


class AllAppsDiscoveryTests(RenderedWorkspace, unittest.TestCase):
    app_ids = ALL_APPS

    def test_every_stack_skill_is_generated_for_its_app(self) -> None:
        for layer in (".agents/skills", ".claude/skills"):
            for name in ("android-conventions", "compose-design-system", "ios-conventions", "swiftui-design-system", "spring-boot-conventions", "deployment"):
                self.assertTrue((self.root / layer / name / "SKILL.md").is_file(), f"{layer}/{name}")
        self.assertTrue((self.root / ".claude" / "skills" / "deploy-device" / "SKILL.md").is_file())
        self.assertTrue((self.root / ".cursor" / "rules" / "web.mdc").is_file())
        self.assertTrue((self.root / ".agents" / "skills" / "deployment" / "references" / "cloudflare" / "open-next.config.ts").is_file())

    def test_a_workflow_skill_has_one_body_in_the_codex_and_claude_layouts(self) -> None:
        names = {skill.name for skill in self.skills}
        sigil = re.compile(r"(?<![\w/.\-])[$/](" + "|".join(sorted(map(re.escape, names), key=len, reverse=True)) + r")(?![\w/.\-])")
        for name in ("dev-done", "wiki-query", "ask", "ingest"):
            with self.subTest(skill=name):
                codex = (self.root / ".agents" / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
                command = (self.root / ".claude" / "commands" / f"{name}.md").read_text(encoding="utf-8")
                codex_body = codex.split("\n---\n", 1)[1]
                self.assertIn(f"`${name}", codex_body)
                self.assertIn(f"`/{name}", command)
                self.assertEqual(sigil.sub(r"\1", codex_body).split(), sigil.sub(r"\1", command).split())


class OneAppDiscoveryTests(RenderedWorkspace, unittest.TestCase):
    app_ids = ONE_APP

    def test_an_app_that_is_not_selected_brings_none_of_its_skills(self) -> None:
        for layer in (".agents/skills", ".claude/skills"):
            for name in ("android-conventions", "android-testing", "compose-design-system", "ios-conventions", "swiftui-design-system"):
                self.assertFalse((self.root / layer / name).exists(), f"{layer}/{name}")
        self.assertFalse((self.root / ".claude" / "skills" / "deploy-device").exists())
        for rule in ("web.mdc", "mobile-android.mdc", "mobile-ios.mdc"):
            self.assertFalse((self.root / ".cursor" / "rules" / rule).exists(), rule)
        self.assertTrue((self.root / ".cursor" / "rules" / "backend.mdc").is_file())
        references = self.root / ".agents" / "skills" / "deployment" / "references"
        self.assertTrue((references / "azure").is_dir())
        self.assertFalse((references / "cloudflare").exists())
        self.assertFalse((references / "mobile-store-release.md").exists())


if __name__ == "__main__":
    unittest.main()
