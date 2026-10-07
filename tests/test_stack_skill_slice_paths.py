"""The stack skills cite the slice files they teach from, and every cited path exists in a generated app.

A stack skill has one section titled `Slice files`. Each backticked item in a bullet of it that names a file
(its last segment has an extension) or a folder (it ends with `/`) is a path inside the app's folder, and
`<package path>` stands for the app's package written with slashes. The test generates a workspace with all
four stacks and a second Android app at another path, then checks every cited path in every app of the
skill's stack, in the Claude and in the Codex layer.
"""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path
from typing import Any

import yaml

from prism_cli.app_model import GENERATION_SCAFFOLDED
from tests import real_temp  # noqa: F401
from tests.layered_support import generate_default_apps

REPO_ROOT = Path(__file__).resolve().parents[1]
SECTION_TITLE = "## Slice files"
PLACEHOLDER = "<package path>"
SKILL_LAYERS = (".claude/skills", ".agents/skills")

# The skills that must cite slice files, by the stack whose apps hold them. Every skill source that names one
# stack in its `stacks` condition belongs here too, except the skills that teach tasks and no slice code.
REQUIRED = {
    "spring-backend": ("spring-boot-conventions", "testing-patterns", "error-handling", "security-auth"),
    "nextjs-web": ("web-conventions",),
    "android-compose": (
        "android-conventions",
        "android-testing",
        "android-contract-alignment",
        "android-feature-delivery",
        "compose-design-system",
    ),
    "ios-swiftui": ("ios-conventions", "ios-testing", "ios-contract-alignment", "ios-feature-delivery", "swiftui-design-system"),
}
TASK_SKILLS = {"android-build-verify", "ios-build-verify", "deploy-device"}
SECOND_ANDROID = {
    "id": "partner-android",
    "name": "Partner App",
    "stack": "android-compose",
    "repository": "workspace",
    "path": "apps/partner",
    "audience": "B2B",
    "generation": GENERATION_SCAFFOLDED,
}


def slice_section(text: str) -> str | None:
    """The body of the `Slice files` section of a rendered skill, or None when it has none."""

    lines = text.replace("\r\n", "\n").split("\n")
    for index, line in enumerate(lines):
        if line.strip() == SECTION_TITLE:
            body = []
            for following in lines[index + 1 :]:
                if following.startswith("## "):
                    break
                body.append(following)
            return "\n".join(body)
    return None


def cited_paths(section: str, package_path: str) -> list[str]:
    """The paths the section cites, with `<package path>` expanded. Anything with a space left is prose."""

    paths: list[str] = []
    bullets = "\n".join(line for line in section.split("\n") if line.startswith("- "))
    for token in re.findall(r"`([^`\n]+)`", bullets):
        path = token.replace(PLACEHOLDER, package_path)
        if re.search(r"\s", path):
            continue
        if path.endswith("/") or re.search(r"\.[A-Za-z0-9]+$", path.rsplit("/", 1)[-1]):
            paths.append(path)
    return paths


def missing_paths(section: str, app_root: Path, package_path: str) -> list[str]:
    """The cited paths that do not exist under the app's folder."""

    return [path for path in cited_paths(section, package_path) if not (app_root / path.rstrip("/")).exists()]


class SliceFilePathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory(prefix="prism-slice-paths-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name) / "generated"
        generate_default_apps(
            cls.root,
            ["backend", "web", "mobile-android", "mobile-ios"],
            Path(cls.temporary.name),
            project_name="Slice Paths",
            extra_apps=[SECOND_ANDROID],
        )
        manifest = yaml.safe_load((cls.root / "prism.workspace.yml").read_text(encoding="utf-8"))
        cls.package_identifier: str = manifest["project"]["package_identifier"]
        cls.apps: list[dict[str, Any]] = manifest["apps"]

    def apps_of(self, stack: str) -> list[dict[str, Any]]:
        return [app for app in self.apps if app["stack"] == stack]

    def package_path(self, app: dict[str, Any]) -> str:
        return f"{self.package_identifier}.{app['id'].replace('-', '')}".replace(".", "/")

    def test_the_workspace_has_the_apps_the_test_needs(self) -> None:
        self.assertEqual(
            {"spring-backend": 1, "nextjs-web": 1, "android-compose": 2, "ios-swiftui": 1},
            {stack: len(self.apps_of(stack)) for stack in REQUIRED},
        )

    def test_every_required_stack_skill_cites_slice_files_that_exist_in_every_app_of_its_stack(self) -> None:
        checked = 0
        for stack, skills in REQUIRED.items():
            for name in skills:
                for layer in SKILL_LAYERS:
                    path = self.root / layer / name / "SKILL.md"
                    with self.subTest(skill=name, layer=layer):
                        self.assertTrue(path.is_file(), f"{name} must ship to a workspace with a {stack} app")
                        section = slice_section(path.read_text(encoding="utf-8"))
                        self.assertIsNotNone(section, f"{name} needs a `{SECTION_TITLE}` section")
                        for app in self.apps_of(stack):
                            package_path = self.package_path(app)
                            cited = cited_paths(section or "", package_path)
                            self.assertGreaterEqual(len(cited), 3, f"{name} cites too few slice files: {cited}")
                            self.assertEqual([], missing_paths(section or "", self.root / app["path"], package_path), f"{name} in app {app['id']}")
                            checked += len(cited)
        self.assertGreater(checked, 100)

    def test_every_rendered_slice_files_section_is_checked_not_only_the_required_ones(self) -> None:
        required = {name for skills in REQUIRED.values() for name in skills}
        stacks_of = {name: stack for stack, skills in REQUIRED.items() for name in skills}
        for layer in SKILL_LAYERS:
            for skill in sorted((self.root / layer).iterdir()):
                file = skill / "SKILL.md"
                if not file.is_file():
                    continue
                section = slice_section(file.read_text(encoding="utf-8"))
                if section is None:
                    continue
                with self.subTest(skill=skill.name, layer=layer):
                    self.assertIn(skill.name, required, "a skill with a Slice files section belongs to REQUIRED, with its stack")
                    for app in self.apps_of(stacks_of[skill.name]):
                        self.assertEqual([], missing_paths(section, self.root / app["path"], self.package_path(app)))

    def test_the_two_layers_cite_the_same_files(self) -> None:
        for name in (name for skills in REQUIRED.values() for name in skills):
            with self.subTest(skill=name):
                sections = [slice_section((self.root / layer / name / "SKILL.md").read_text(encoding="utf-8")) for layer in SKILL_LAYERS]
                self.assertEqual(sections[0], sections[1])

    def test_a_cited_path_that_does_not_exist_is_reported(self) -> None:
        app = self.apps_of("android-compose")[0]
        package_path = self.package_path(app)
        section = "- `app/src/main/kotlin/<package path>/ui/signin/SignInScreen.kt` exists\n- `app/src/main/kotlin/<package path>/ui/Missing.kt` does not\n- `GET /api/me` is prose\n"
        self.assertEqual(["app/src/main/kotlin/<package path>/ui/Missing.kt".replace(PLACEHOLDER, package_path)], missing_paths(section, self.root / app["path"], package_path))
        self.assertEqual([], missing_paths("- `app/src/main/kotlin/<package path>/ui/signin/` is a folder\n", self.root / app["path"], package_path))
        self.assertEqual(["gone/"], missing_paths("- `gone/` is a missing folder\n", self.root / app["path"], package_path))


class SkillSourceTests(unittest.TestCase):
    def test_every_skill_source_that_names_one_stack_is_required_or_a_task_skill(self) -> None:
        required = {name for skills in REQUIRED.values() for name in skills}
        for source in sorted((REPO_ROOT / "template-skills").glob("*/skill.md")):
            text = source.read_text(encoding="utf-8").replace("\r\n", "\n")
            front = yaml.safe_load(text.split("---\n", 2)[1])
            stacks = front.get("stacks") or []
            name = source.parent.name
            if len(stacks) != 1:
                continue
            with self.subTest(skill=name):
                if name in TASK_SKILLS:
                    self.assertNotIn(name, required)
                    continue
                self.assertIn(name, REQUIRED[stacks[0]], f"{name} is a {stacks[0]} skill: cite its slice files and list it in REQUIRED")

    def test_every_required_source_has_the_section(self) -> None:
        for stack, skills in REQUIRED.items():
            for name in skills:
                with self.subTest(skill=name):
                    text = (REPO_ROOT / "template-skills" / name / "skill.md").read_text(encoding="utf-8")
                    self.assertIsNotNone(slice_section(text), f"{name} needs a `{SECTION_TITLE}` section")


if __name__ == "__main__":
    unittest.main()
