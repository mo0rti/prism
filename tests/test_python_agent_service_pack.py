"""The `python-agent-service` pack: its pins and lockfile, its slice, and two agent services in one workspace.

The static tests read the pack's own files. The generated tests run the Prism CLI against a copy of the working
tree (real Copier) and read what each agent app and the workspace layer contain. Installing and running the
generated services (`uv sync --locked`, lint, typecheck, tests, the evaluation) is the job of the pack's own
workflow and of the `agent-service` job of `.github/workflows/template-validation.yml`.
"""

from __future__ import annotations

import importlib.util
import py_compile
import re
import tempfile
import unittest
from pathlib import Path

import yaml
from jinja2 import Environment, StrictUndefined

from prism_cli.packs import PACK_STACKS, pack_answers
from tests import real_temp  # noqa: F401
from tests.layered_support import build_template_repo, commit_workspace, generate_default_apps, generate_workspace, git, read_yaml, run_cli

REPO_ROOT = Path(__file__).resolve().parents[1]
PACK = REPO_ROOT / "packs" / "python-agent-service"
PACK_APP = PACK / "{{ app_path }}"
LOCK_NAME = "{{ project_slug }}-{{ app_id }}"
AGENT_APP = {
    "id": "agent-service",
    "name": "Portfolio Assistant",
    "stack": "python-agent-service",
    "repository": "workspace",
    "path": "agent-service",
    "generation": "scaffolded",
}
SECOND_AGENT = {
    "id": "import-helper",
    "name": "Import Helper",
    "stack": "python-agent-service",
    "repository": "workspace",
    "path": "services/import-helper",
    "audience": "investors",
    "generation": "scaffolded",
}
# The direct dependencies of pyproject.toml.jinja, by distribution name, and the pin each reads.
RUNTIME = {
    "anthropic": "anthropic",
    "fastapi": "fastapi",
    "httpx": "httpx",
    "pydantic": "pydantic",
    "pydantic-settings": "pydantic_settings",
    "pyjwt": "pyjwt",
    "uvicorn": "uvicorn",
}
DEV = {"mypy": "mypy", "pytest": "pytest", "pyyaml": "pyyaml", "ruff": "ruff", "types-pyyaml": "types_pyyaml"}


def pins() -> dict[str, str]:
    data = yaml.safe_load((REPO_ROOT / "packs" / "versions.yml").read_text(encoding="utf-8"))
    return {key: str(value) for key, value in data["python-agent-service"].items()}


def render_pyproject(project_slug: str = "demo", app_id: str = "agent") -> str:
    template = Environment(undefined=StrictUndefined, keep_trailing_newline=True).from_string((PACK_APP / "pyproject.toml.jinja").read_text(encoding="utf-8"))
    return template.render(versions=pins(), project_slug=project_slug, app_id=app_id, app_name="Agent", project_name="Demo")


def lock_text() -> str:
    return (PACK_APP / "uv.lock.jinja").read_text(encoding="utf-8").replace("\r\n", "\n")


def lock_packages() -> dict[str, str]:
    """The name and version of every package the lock resolves."""

    return {name: version for name, version in re.findall(r'\[\[package\]\]\nname = "([^"]+)"\nversion = "([^"]+)"', lock_text())}


def load_refresh_script():
    spec = importlib.util.spec_from_file_location("refresh_python_agent_service_lock", REPO_ROOT / "scripts" / "refresh-python-agent-service-lock.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def declared(pyproject: str, group: str) -> dict[str, str]:
    """`name -> exact version` of the dependency list that follows `group = [` in a rendered pyproject.toml."""

    block = re.search(rf"^{group} = \[\n(.*?)^\]", pyproject, re.DOTALL | re.MULTILINE)
    assert block, group
    found = re.findall(r'"([A-Za-z0-9_.-]+)(?:\[[a-z]+\])?==([0-9][^"]*)"', block.group(1))
    return {name.lower(): version for name, version in found}


class PinsAndLockfileTests(unittest.TestCase):
    def test_the_stack_has_a_pack_and_pins(self) -> None:
        self.assertIn("python-agent-service", PACK_STACKS)
        self.assertTrue(PACK.is_dir())
        for key in (*RUNTIME.values(), *DEV.values(), "python", "uv"):
            self.assertIn(key, pins())

    def test_pyproject_reads_every_dependency_version_from_the_pins(self) -> None:
        pyproject = render_pyproject()
        runtime = declared(pyproject, "dependencies")
        dev = declared(pyproject, "dev")
        pinned = pins()
        self.assertEqual({name: pinned[key] for name, key in RUNTIME.items()}, runtime)
        self.assertEqual({name: pinned[key] for name, key in DEV.items()}, dev)
        self.assertIn(f'requires-python = ">={pinned["python"]}"', pyproject)
        self.assertIn(f'required-version = ">={pinned["uv"]}"', pyproject)
        self.assertEqual(set(pinned), set(RUNTIME.values()) | set(DEV.values()) | {"python", "uv"}, "every pin is used and nothing else is pinned")
        for version in (*runtime.values(), *dev.values()):
            self.assertRegex(version, r"^\d+\.\d+(\.\d+)*$", "an exact version, so the lock and the pin cannot drift apart")

    def test_the_lockfile_resolves_every_direct_dependency_to_its_pin(self) -> None:
        packages = lock_packages()
        for name, version in {**declared(render_pyproject(), "dependencies"), **declared(render_pyproject(), "dev")}.items():
            with self.subTest(package=name):
                self.assertEqual(version, packages[name], "the lock resolves a direct dependency to its pin")
        self.assertIn(f'requires-python = ">={pins()["python"]}"', lock_text())
        # The extra of `pyjwt[crypto]` pulls in the cryptography package.
        self.assertIn("cryptography", packages)

    def test_the_lockfile_names_the_app_and_nothing_else_is_templated(self) -> None:
        text = lock_text()
        self.assertEqual(1, text.count(LOCK_NAME), "the root package name is the only expression")
        self.assertIn(f'name = "{LOCK_NAME}"\nversion = "0.1.0"\nsource = {{ virtual = "." }}', text)
        remainder = text.replace(LOCK_NAME, "")
        for marker in ("{{", "{%", "{#"):
            self.assertNotIn(marker, remainder)

    def test_the_lockfile_is_reproducible_on_a_clean_runner(self) -> None:
        blocks = lock_text().split("[[package]]\n")[1:]
        self.assertGreater(len(blocks), 30)
        for block in blocks:
            name = re.search(r'name = "([^"]+)"', block).group(1)
            if name == LOCK_NAME:
                continue
            with self.subTest(package=name):
                self.assertIn('source = { registry = "https://pypi.org/simple" }', block)
                self.assertRegex(block, r'hash = "sha256:[0-9a-f]{64}"')

    def test_the_lockfile_records_the_dependencies_pyproject_declares(self) -> None:
        text = lock_text()
        metadata = re.search(r"\[package\.metadata\]\nrequires-dist = \[\n(.*?)\n\]", text, re.DOTALL)
        self.assertIsNotNone(metadata)
        recorded = dict(re.findall(r'\{ name = "([a-z0-9-]+)"(?:, extras = \["[a-z]+"\])?, specifier = "==([^"]+)" \}', metadata.group(1)))
        self.assertEqual(declared(render_pyproject(), "dependencies"), recorded)

    def test_the_refresh_script_renders_the_pyproject_the_lock_records(self) -> None:
        script = load_refresh_script()
        rendered = script.render_pyproject()
        self.assertIn(f'name = "{script.NAME_MARK}"', rendered)
        self.assertEqual(LOCK_NAME, script.NAME_EXPRESSION)
        self.assertEqual(declared(render_pyproject(), "dependencies"), declared(rendered, "dependencies"))
        self.assertEqual(declared(render_pyproject(), "dev"), declared(rendered, "dev"))


class PackFilesTests(unittest.TestCase):
    def pack_files(self):
        return [path for path in sorted(PACK.rglob("*")) if path.is_file() and not path.name.startswith("uv.lock")]

    def test_the_pack_follows_the_pack_conventions(self) -> None:
        relative = {path.relative_to(PACK).as_posix() for path in PACK.rglob("*") if path.is_file()}
        owned = {".github/workflows/{{ app_id }}.yml.jinja", ".cursor/rules/{{ app_id }}.mdc.jinja", "{{ _copier_conf.answers_file }}.jinja"}
        self.assertLessEqual(owned, relative)
        for path in relative:
            self.assertTrue(path.startswith("{{ app_path }}/") or path in owned, f"{path} must be under {{{{ app_path }}}}/")

    def test_the_slice_files_exist(self) -> None:
        for relative in (
            "pyproject.toml.jinja",
            "uv.lock.jinja",
            "openapi.yml.jinja",
            "Taskfile.yml.jinja",
            "AGENTS.md.jinja",
            "CLAUDE.md.jinja",
            "README.md.jinja",
            "docs/guide.md.jinja",
            ".gitignore",
            ".env.example",
            "app/main.py",
            "app/config.py",
            "app/auth/startup.py",
            "app/auth/verifier.py",
            "app/auth/keys.py",
            "app/agent/turn.py",
            "app/agent/service.py",
            "app/agent/prompts.py",
            "app/providers/base.py",
            "app/providers/fake.py",
            "app/providers/claude.py",
            "app/tools/backend_profile.py",
            "app/safety/untrusted.py",
            "app/safety/budget.py",
            "app/safety/audit.py",
            "app/safety/notice.py",
            "app/routes/assist.py",
            "app/routes/health.py",
            "tests/test_auth.py",
            "tests/test_agent_turn.py",
            "tests/test_claude_provider.py",
            "tests/test_contract.py",
            "tests/test_evals.py",
            "evals/run.py",
            "evals/cases/profile-question.toml",
        ):
            with self.subTest(file=relative):
                self.assertTrue((PACK_APP / relative).is_file())

    def test_no_pack_file_holds_an_api_key(self) -> None:
        key = re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}")
        assignment = re.compile(r"^\s*(?:export\s+)?ANTHROPIC_API_KEY\s*[:=]\s*[^\s#]", re.MULTILINE)
        for path in self.pack_files():
            text = path.read_text(encoding="utf-8", errors="ignore")
            with self.subTest(file=path.relative_to(PACK).as_posix()):
                self.assertIsNone(key.search(text))
                self.assertIsNone(assignment.search(text))
        env_example = (PACK_APP / ".env.example").read_text(encoding="utf-8")
        self.assertIn("# ANTHROPIC_API_KEY=\n", env_example, "the key variable is named, never given a value")

    def test_the_service_never_reads_the_environment_outside_the_settings_or_imports_the_sdk_outside_the_adapter(self) -> None:
        for path in sorted((PACK_APP / "app").rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            relative = path.relative_to(PACK_APP).as_posix()
            with self.subTest(file=relative):
                self.assertNotIn("os.environ", text)
                self.assertNotIn("getenv", text)
                if relative != "app/providers/claude.py":
                    self.assertNotRegex(text, r"^\s*(import|from) anthropic", "the vendor SDK stays behind the Claude adapter")

    def test_the_service_has_no_dev_identity_of_its_own_and_no_switch_that_turns_authentication_off(self) -> None:
        for path in sorted((PACK_APP / "app").rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            with self.subTest(file=path.relative_to(PACK_APP).as_posix()):
                self.assertNotIn("/api/dev-identity/token", text)
                self.assertNotIn("def issue", text)
                self.assertNotIn("PRIVATE KEY", text)
        startup = (PACK_APP / "app" / "auth" / "startup.py").read_text(encoding="utf-8")
        self.assertIn("never runs unauthenticated", startup)
        self.assertIn("cannot run with a real identity provider", startup)

    def test_the_workflow_runs_lint_typecheck_test_and_the_fake_provider_evaluation(self) -> None:
        text = (PACK / ".github" / "workflows" / "{{ app_id }}.yml.jinja").read_text(encoding="utf-8")
        for step in (
            "uv sync --locked",
            "uv run --locked ruff check .",
            "uv run --locked ruff format --check .",
            "uv run --locked mypy",
            "uv run --locked pytest",
            "uv run --locked python -m evals.run --provider fake",
        ):
            self.assertIn(step, text)
        for forbidden in ("secrets.", "ANTHROPIC_API_KEY", "--provider claude"):
            self.assertNotIn(forbidden, text)

    def test_every_path_the_pack_guidance_cites_exists_in_the_pack(self) -> None:
        cited = re.compile(r"`((?:app|tests|evals)/[A-Za-z0-9_./-]+\.[a-z]+)`")
        documents = [
            PACK_APP / "AGENTS.md.jinja",
            PACK_APP / "README.md.jinja",
            PACK_APP / "docs" / "guide.md.jinja",
            PACK / ".cursor" / "rules" / "{{ app_id }}.mdc.jinja",
        ] + sorted((REPO_ROOT / "template-skills").glob("a*/skill.md"))
        checked = 0
        for document in documents:
            text = document.read_text(encoding="utf-8")
            if document.parent.parent.name == "template-skills" and "stacks: [python-agent-service]" not in text:
                continue
            for relative in sorted(set(cited.findall(text))):
                checked += 1
                with self.subTest(document=document.parent.name + "/" + document.name, path=relative):
                    self.assertTrue((PACK_APP / relative).is_file(), relative)
        self.assertGreater(checked, 40)

    def test_the_four_skills_exist_for_the_stack(self) -> None:
        for name in ("agent-conventions", "add-tool", "add-evaluation-case", "agent-safety"):
            skill = (REPO_ROOT / "template-skills" / name / "skill.md").read_text(encoding="utf-8")
            with self.subTest(skill=name):
                self.assertIn("stacks: [python-agent-service]", skill)
                self.assertIn("## Slice files", skill)
                for layer in (".agents/skills", ".claude/skills"):
                    self.assertTrue((REPO_ROOT / "template" / layer / name / "SKILL.md.jinja").is_file(), layer)

    def test_the_notice_adaptation_is_taught(self) -> None:
        skill = (REPO_ROOT / "template-skills" / "agent-safety" / "skill.md").read_text(encoding="utf-8")
        self.assertIn("## Adapt the notice to your domain", skill)
        self.assertIn("`NOTICE` in `app/safety/notice.py`", skill)

    def test_the_pack_answers_for_two_agent_apps_differ_only_in_their_own_identifiers(self) -> None:
        project = {"project_name": "Demo", "project_slug": "demo", "package_identifier": "com.example.demo"}
        first = pack_answers(project, {"id": "agent", "stack": "python-agent-service", "path": "agent"}, port=8200)
        second = pack_answers(project, {"id": "helper", "stack": "python-agent-service", "path": "services/helper", "audience": "x"}, port=8201)
        differing = {key for key in first if first[key] != second[key]}
        self.assertEqual(
            {"app_id", "app_name", "app_path", "audience", "port", "app_package_segment", "app_package", "app_package_path", "app_module_name", "ci_workflow_name", "ci_paths"},
            differing,
        )


class GeneratedAgentServicesTests(unittest.TestCase):
    """A workspace with a backend and two agent services of one stack: one at the default path and one nested."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory(prefix="prism-agent-pack-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.scratch = Path(cls.temporary.name)
        cls.root = cls.scratch / "generated"
        generate_default_apps(cls.root, ["backend"], cls.scratch, project_name="Layered Agent", extra_apps=[AGENT_APP, SECOND_AGENT])
        cls.apps = {
            "agent-service": {"path": "agent-service", "port": 8200, "name": "Portfolio Assistant"},
            "import-helper": {"path": "services/import-helper", "port": 8201, "name": "Import Helper"},
        }

    def text(self, relative: str) -> str:
        return (self.root / relative).read_text(encoding="utf-8")

    def test_each_app_is_its_own_layer_with_its_own_identity(self) -> None:
        names: set[str] = set()
        for app, info in self.apps.items():
            with self.subTest(app=app):
                answers = yaml.safe_load(self.text(f"{info['path']}/.copier-answers.yml"))
                self.assertEqual(("python-agent-service", app, info["path"], info["port"]), (answers["prism_layer"], answers["app_id"], answers["app_path"], answers["port"]))
                pyproject = self.text(f"{info['path']}/pyproject.toml")
                name = re.search(r'^name = "([^"]+)"', pyproject, re.MULTILINE).group(1)
                self.assertEqual(f"layered-agent-{app}", name)
                names.add(name)
                self.assertIn(f'name = "layered-agent-{app}"\nversion = "0.1.0"\nsource = {{ virtual = "." }}', self.text(f"{info['path']}/uv.lock"))
                self.assertTrue((self.root / ".github" / "workflows" / f"{app}.yml").is_file())
                self.assertTrue((self.root / ".cursor" / "rules" / f"{app}.mdc").is_file())
                taskfile = yaml.safe_load(self.text(f"{info['path']}/Taskfile.yml"))
                self.assertIn(f"--port {info['port']}", taskfile["tasks"]["dev"]["cmds"][0])
                self.assertEqual("local", taskfile["tasks"]["dev"]["env"]["AGENT_PROFILE"])
        self.assertEqual(2, len(names), "distinct project names")

    def test_the_rendered_files_are_valid_and_carry_no_placeholder(self) -> None:
        for app, info in self.apps.items():
            folder = self.root / info["path"]
            with self.subTest(app=app):
                for path in folder.rglob("*"):
                    if not path.is_file() or path.name == "uv.lock":
                        continue
                    text = path.read_text(encoding="utf-8", errors="ignore")
                    for marker in ("{{", "{%"):
                        self.assertNotIn(marker, text, path.relative_to(self.root).as_posix())
                    if path.suffix == ".py":
                        py_compile.compile(str(path), doraise=True, cfile=str(self.scratch / "compiled.pyc"))
                contract = yaml.safe_load((folder / "openapi.yml").read_text(encoding="utf-8"))
                self.assertEqual(f"http://localhost:{info['port']}", contract["servers"][0]["url"])
                self.assertEqual({"/api/health", "/api/assist"}, set(contract["paths"]))

    def test_every_agent_app_runs_the_same_ci_steps_scoped_to_its_path(self) -> None:
        for app, info in self.apps.items():
            with self.subTest(app=app):
                data = yaml.safe_load(self.text(f".github/workflows/{app}.yml"))
                self.assertEqual(f"{info['name']} CI", data["name"])
                triggers = data.get("on", data.get(True))
                for event in ("push", "pull_request"):
                    self.assertEqual([f"{info['path']}/**", "shared/api-contracts/**", f".github/workflows/{app}.yml"], triggers[event]["paths"])
                job = data["jobs"]["verify"]
                self.assertEqual(info["path"], job["defaults"]["run"]["working-directory"])
                setup = next(step for step in job["steps"] if str(step.get("uses", "")).startswith("astral-sh/setup-uv"))
                self.assertEqual(pins()["uv"], str(setup["with"]["version"]))
                self.assertEqual(pins()["python"], str(setup["with"]["python-version"]))
                self.assertEqual(f"{info['path']}/uv.lock", setup["with"]["cache-dependency-glob"])
                runs = [step["run"] for step in job["steps"] if "run" in step]
                self.assertEqual("uv sync --locked", runs[0])
                self.assertIn("uv run --locked python -m evals.run --provider fake", runs[-1])

    def test_the_workspace_taskfile_runs_the_agent_apps_in_lint_and_test(self) -> None:
        taskfile = yaml.safe_load(self.text("Taskfile.yml"))
        for app, info in self.apps.items():
            self.assertEqual(f"./{info['path']}/Taskfile.yml", taskfile["includes"][app]["taskfile"])
            for task in (f"{app}:lint", f"{app}:typecheck"):
                self.assertIn({"task": task}, taskfile["tasks"]["lint"]["cmds"])
            for task in (f"{app}:test", f"{app}:eval"):
                self.assertIn({"task": task}, taskfile["tasks"]["test"]["cmds"])

    def test_the_workspace_guidance_names_the_agent_apps_and_the_manifest_records_them(self) -> None:
        agents = self.text("AGENTS.md")
        readme = self.text("README.md")
        for app, info in self.apps.items():
            self.assertIn(f"`task {app}:dev`", agents)
            self.assertIn(f"`{info['path']}/AGENTS.md`", agents)
            self.assertIn(f"[{info['name']} Guide]({info['path']}/docs/guide.md)", readme)
        manifest = yaml.safe_load(self.text("prism.workspace.yml"))
        apps = {app["id"]: app for app in manifest["apps"]}
        for app, info in self.apps.items():
            self.assertEqual(("python-agent-service", "scaffolded", info["path"]), (apps[app]["stack"], apps[app]["generation"], apps[app]["path"]))
            self.assertEqual("provisional", manifest["app_maturity"][app]["level"])
        for skill in ("agent-conventions", "add-tool", "add-evaluation-case", "agent-safety"):
            for layer in (".agents/skills", ".claude/skills"):
                self.assertTrue((self.root / layer / skill / "SKILL.md").is_file(), f"{layer}/{skill}")

    def test_the_backend_contract_publishes_the_dev_identity_key_as_dev_only(self) -> None:
        contract = yaml.safe_load(self.text("shared/api-contracts/openapi.yml"))
        jwks = contract["paths"]["/api/dev-identity/jwks"]["get"]
        self.assertIs(True, jwks["x-prism-dev-only"])
        self.assertEqual([], jwks["security"])
        self.assertIs(True, contract["paths"]["/api/dev-identity/token"]["post"]["x-prism-dev-only"])
        self.assertNotIn("/api/assist", contract["paths"], "the agent service owns its contract")

    def test_a_workspace_without_a_backend_still_scaffolds_an_agent_service(self) -> None:
        root = self.scratch / "agent-only"
        generate_default_apps(root, [], self.scratch, project_name="Agent Only", extra_apps=[AGENT_APP])
        self.assertTrue((root / "agent-service" / "app" / "main.py").is_file())
        self.assertFalse((root / "docker-compose.yml").exists(), "the compose file belongs to backend apps")
        self.assertIn("task agent-service:dev", (root / "AGENTS.md").read_text(encoding="utf-8"))


class ScaffoldAnAgentServiceTests(unittest.TestCase):
    """`prism app add --scaffold` adds an agent service to a committed workspace, at the recorded template tag."""

    def test_an_agent_service_is_scaffolded_into_an_existing_workspace_with_its_own_port_and_maturity(self) -> None:
        with tempfile.TemporaryDirectory(prefix="prism-agent-scaffold-") as temporary:
            root = Path(temporary)
            repo = build_template_repo(root / "template-repo")
            workspace = root / "workspace"
            code, out, err = generate_workspace(repo, workspace, {"project_name": "Layered Agent", "apps": [{"id": "backend", "stack": "spring-backend", "name": "Backend"}]}, root)
            self.assertEqual(0, code, out + err)
            commit_workspace(workspace)

            preview_code, preview, preview_err = run_cli("app", "add", "agent-service", "--stack", "python-agent-service", "--scaffold", str(workspace))
            self.assertEqual(0, preview_code, preview_err)
            self.assertIn("Scaffolds `agent-service` (python-agent-service) at `agent-service` on port 8200", preview)
            self.assertFalse((workspace / "agent-service").exists(), "a preview changes nothing")

            code, out, err = run_cli("app", "add", "agent-service", "--stack", "python-agent-service", "--scaffold", "--apply", "--yes", "--trust-template", str(workspace))
            self.assertEqual(0, code, out + err)
            answers = read_yaml(workspace / "agent-service" / ".copier-answers.yml")
            self.assertEqual((8200, "v1.0.0", "python-agent-service"), (answers["port"], answers["_commit"], answers["prism_layer"]))
            manifest = read_yaml(workspace / "prism.workspace.yml")
            entry = next(app for app in manifest["apps"] if app["id"] == "agent-service")
            self.assertEqual(("python-agent-service", "scaffolded", "agent-service"), (entry["stack"], entry["generation"], entry["path"]))
            self.assertEqual("provisional", manifest["app_maturity"]["agent-service"]["level"])
            self.assertIn(".github/workflows/agent-service.yml", manifest["expected_surfaces"]["workflows"])
            self.assertEqual({"backend", "agent-service"}, set(yaml.safe_load((workspace / "Taskfile.yml").read_text(encoding="utf-8"))["includes"]))
            self.assertEqual("", git(workspace, "status", "--porcelain").stdout)
            # A second agent service takes the next free port of the stack's range.
            git(workspace, "switch", "-q", "main")
            git(workspace, "merge", "--ff-only", "-q", "prism-scaffold-agent-service")
            code, out, err = run_cli("app", "add", "import-helper", "--stack", "python-agent-service", "--path", "services/import-helper", "--scaffold", "--apply", "--yes", "--trust-template", str(workspace))
            self.assertEqual(0, code, out + err)
            self.assertEqual(8201, read_yaml(workspace / "services" / "import-helper" / ".copier-answers.yml")["port"])


if __name__ == "__main__":
    unittest.main()
