"""The `nextjs-web` pack: its pins and lockfile, its slice, and two web apps of one stack in one workspace.

The static tests read the pack's own files. The generated tests run the Prism CLI against a copy of the
working tree (real Copier) and read what each web app and the workspace layer contain. Installing and
running the generated apps (`npm ci`, lint, typecheck, test, build) is the job of the pack's own
workflow and of the web job of `.github/workflows/template-validation.yml`.
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

import yaml
from jinja2 import Environment, StrictUndefined

from prism_cli.packs import PACK_STACKS, pack_answers
from tests import real_temp  # noqa: F401
from tests.layered_support import generate_default_apps, run_cli

REPO_ROOT = Path(__file__).resolve().parents[1]
PACK = REPO_ROOT / "packs" / "nextjs-web"
PACK_APP = PACK / "{{ app_path }}"
LOCK_NAME = "{{ project_slug }}-{{ app_id }}"
ADMIN_APP = {"id": "admin", "name": "Admin App", "stack": "nextjs-web", "repository": "workspace", "path": "admin", "audience": "internal", "generation": "scaffolded"}
PARTNER_APP = {"id": "partner-portal", "name": "Partner Portal", "stack": "nextjs-web", "repository": "workspace", "path": "apps/partner", "audience": "partners", "generation": "scaffolded"}
WEB_AUDIENCE = "B2C"


def pins() -> dict[str, str]:
    data = yaml.safe_load((REPO_ROOT / "packs" / "versions.yml").read_text(encoding="utf-8"))
    return {key: str(value) for key, value in data["nextjs-web"].items()}


def render_package_json(app_path: str = "web", port: int = 3000) -> dict:
    template = Environment(undefined=StrictUndefined, keep_trailing_newline=True).from_string((PACK_APP / "package.json.jinja").read_text(encoding="utf-8"))
    return json.loads(template.render(versions=pins(), project_slug="demo", app_id="web", app_path=app_path, port=port))


def lock() -> dict:
    return json.loads((PACK_APP / "package-lock.json.jinja").read_text(encoding="utf-8"))


def load_refresh_script():
    spec = importlib.util.spec_from_file_location("refresh_nextjs_web_lock", REPO_ROOT / "scripts" / "refresh-nextjs-web-lock.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PinsAndLockfileTests(unittest.TestCase):
    def test_the_stack_has_a_pack_and_pins(self) -> None:
        self.assertIn("nextjs-web", PACK_STACKS)
        self.assertTrue(PACK.is_dir())
        for key in ("node", "next", "react", "typescript", "vitest", "openapi_typescript", "openapi_fetch", "testing_library_react", "jsdom"):
            self.assertIn(key, pins())

    def test_package_json_reads_every_dependency_version_from_the_pins(self) -> None:
        package = render_package_json()
        declared = {**package["dependencies"], **package["devDependencies"]}
        used = set(declared.values()) | {package["engines"]["node"].lstrip(">=")}
        pinned = pins()
        self.assertEqual({pinned[key] for key in pinned}, used, "every pin is used and nothing else is declared")
        self.assertEqual(pinned["next"], package["dependencies"]["next"])
        self.assertEqual(pinned["react"], package["dependencies"]["react"])
        self.assertEqual(pinned["react"], package["dependencies"]["react-dom"])
        for version in declared.values():
            self.assertRegex(version, r"^\d+\.\d+\.\d+$", "an exact version, so the lockfile and the pin cannot drift apart")

    def test_the_lockfile_matches_package_json_and_the_pins(self) -> None:
        package = render_package_json()
        data = lock()
        self.assertEqual(3, data["lockfileVersion"])
        root = data["packages"][""]
        self.assertEqual(package["dependencies"], root["dependencies"])
        self.assertEqual(package["devDependencies"], root["devDependencies"])
        self.assertEqual(package["engines"], root["engines"])
        for name, version in {**package["dependencies"], **package["devDependencies"]}.items():
            with self.subTest(package=name):
                self.assertEqual(version, data["packages"][f"node_modules/{name}"]["version"], "the lockfile resolves a direct dependency to its pin")

    def test_the_lockfile_names_the_app_and_nothing_else_is_templated(self) -> None:
        text = (PACK_APP / "package-lock.json.jinja").read_text(encoding="utf-8")
        data = json.loads(text)
        self.assertEqual(LOCK_NAME, data["name"])
        self.assertEqual(LOCK_NAME, data["packages"][""]["name"])
        self.assertEqual(2, text.count(LOCK_NAME), "the name of the root and of its package entry are the only expressions")
        remainder = text.replace(LOCK_NAME, "")
        for marker in ("{{", "{%", "{#"):
            self.assertNotIn(marker, remainder)

    def test_the_lockfile_is_reproducible_on_a_clean_runner(self) -> None:
        data = lock()["packages"]
        offenders = [
            name
            for name, entry in data.items()
            if name and not (entry["resolved"].startswith("https://registry.npmjs.org/") and entry["integrity"].startswith("sha512-"))
        ]
        self.assertEqual([], offenders, "every package resolves from the public registry with an integrity hash")
        # A lockfile written on Windows still has to install on the Linux runner, so the native packages of every platform are recorded.
        for native in ("@next/swc-linux-x64-gnu", "@next/swc-win32-x64-msvc", "@next/swc-darwin-arm64", "@rolldown/binding-linux-x64-gnu"):
            self.assertIn(f"node_modules/{native}", data, native)

    def test_the_refresh_script_renders_the_package_json_the_lockfile_records(self) -> None:
        script = load_refresh_script()
        rendered = json.loads(script.render_package_json())
        root = lock()["packages"][""]
        self.assertEqual(script.NAME_MARK, rendered["name"])
        self.assertEqual(LOCK_NAME, script.NAME_EXPRESSION)
        for key in ("dependencies", "devDependencies", "engines"):
            self.assertEqual(rendered[key], root[key], key)


class PackFilesTests(unittest.TestCase):
    def pack_files(self):
        return [path for path in sorted(PACK.rglob("*")) if path.is_file() and not path.name.startswith("package-lock.json")]

    def test_the_pack_follows_the_pack_conventions(self) -> None:
        relative = {path.relative_to(PACK).as_posix() for path in PACK.rglob("*") if path.is_file()}
        self.assertIn(".github/workflows/{{ app_id }}.yml.jinja", relative)
        self.assertIn(".cursor/rules/{{ app_id }}.mdc.jinja", relative)
        self.assertIn("{{ _copier_conf.answers_file }}.jinja", relative)
        for path in relative:
            self.assertTrue(
                path.startswith("{{ app_path }}/") or path in {".github/workflows/{{ app_id }}.yml.jinja", ".cursor/rules/{{ app_id }}.mdc.jinja", "{{ _copier_conf.answers_file }}.jinja"},
                f"{path} must be under {{{{ app_path }}}}/",
            )

    def test_the_slice_files_exist(self) -> None:
        for relative in (
            "app/sign-in/page.tsx",
            "app/api/session/route.ts",
            "app/page.tsx",
            "app/layout.tsx",
            "lib/api/client.ts",
            "lib/api/config.ts.jinja",
            "lib/auth/session.ts.jinja",
            "lib/app-info.ts.jinja",
            "components/sign-in-form.tsx",
            "components/sign-out-button.tsx",
            "components/profile-card.tsx",
            "tests/session-route.test.ts",
            "tests/sign-in-page.test.tsx",
            "tests/profile-page.test.tsx",
            "tests/api-client.test.ts.jinja",
            "vitest.config.mts",
            "package-lock.json.jinja",
            "AGENTS.md.jinja",
            "CLAUDE.md.jinja",
            "README.md.jinja",
            "docs/guide.md.jinja",
        ):
            with self.subTest(file=relative):
                self.assertTrue((PACK_APP / relative).is_file())

    def test_the_sign_in_is_the_local_development_sign_in_and_never_complete_authentication(self) -> None:
        page = (PACK_APP / "app" / "sign-in" / "page.tsx").read_text(encoding="utf-8")
        self.assertIn("<h1>Local development sign-in</h1>", page)
        self.assertIn("not complete authentication", page)
        route = (PACK_APP / "app" / "api" / "session" / "route.ts").read_text(encoding="utf-8")
        self.assertIn("response.cookies.set(SESSION_COOKIE", route)
        session = (PACK_APP / "lib" / "auth" / "session.ts.jinja").read_text(encoding="utf-8")
        self.assertIn("httpOnly: true", session)

    def test_the_client_calls_the_two_contract_operations_through_the_generated_types(self) -> None:
        client = (PACK_APP / "lib" / "api" / "client.ts").read_text(encoding="utf-8")
        self.assertIn('from "./generated/schema"', client)
        self.assertIn('.GET("/api/me")', client)
        self.assertIn('.POST("/api/dev-identity/token"', client)
        self.assertNotIn("axios", client)
        scripts = render_package_json()["scripts"]
        self.assertTrue(scripts["generate:api"].startswith("openapi-typescript ../shared/api-contracts/openapi.yml"))
        for script in ("predev", "prebuild", "prelint", "pretypecheck", "pretest"):
            self.assertEqual("npm run generate:api", scripts[script], script)
        self.assertIn("lib/api/generated/", (PACK_APP / ".gitignore.jinja").read_text(encoding="utf-8"))

    def test_no_pack_file_carries_a_retired_sample_or_an_auth_library(self) -> None:
        for path in self.pack_files():
            text = path.read_text(encoding="utf-8", errors="ignore")
            with self.subTest(file=path.relative_to(PACK).as_posix()):
                for retired in ("next-auth", "NextAuth", "next-intl", "web-user-app", "web-admin-portal", "AUTH_SECRET"):
                    self.assertNotIn(retired, text)

    def test_every_path_the_pack_guidance_cites_exists_in_the_pack(self) -> None:
        cited = re.compile(r"`((?:app|components|lib|tests)/[A-Za-z0-9_./\[\]()-]+\.[a-z]+)`")
        documents = [
            PACK_APP / "AGENTS.md.jinja",
            PACK_APP / "README.md.jinja",
            PACK_APP / "docs" / "guide.md.jinja",
            REPO_ROOT / "template-skills" / "web-conventions" / "skill.md",
        ]
        checked = 0
        for document in documents:
            for relative in sorted(set(cited.findall(document.read_text(encoding="utf-8")))):
                if relative.startswith("lib/api/generated/"):
                    continue  # written by `npm run generate:api`
                checked += 1
                with self.subTest(document=document.name, path=relative):
                    self.assertTrue((PACK_APP / relative).is_file() or (PACK_APP / f"{relative}.jinja").is_file(), relative)
        self.assertGreater(checked, 25)

    def test_the_old_web_samples_and_their_helpers_are_gone(self) -> None:
        for path in ("template/web-user-app", "template/web-admin-portal", "template/_templates", "scripts/check-web-auth.mjs", "template-skills/cursor-web", "template/.cursor/rules/web.mdc.jinja"):
            self.assertFalse((REPO_ROOT / path).exists(), path)
        for workflow in ("web-user-app.yml.jinja", "web-admin-portal.yml.jinja"):
            self.assertFalse((REPO_ROOT / "template" / ".github" / "workflows" / workflow).exists(), workflow)

    def test_the_web_skill_exists_for_the_stack_and_cites_the_slice(self) -> None:
        skill = (REPO_ROOT / "template-skills" / "web-conventions" / "skill.md").read_text(encoding="utf-8")
        self.assertIn("stacks: [nextjs-web]", skill)
        for cited in ("app/sign-in/page.tsx", "app/api/session/route.ts", "lib/api/client.ts", "tests/session-route.test.ts"):
            self.assertIn(f"`{cited}`", skill)
        self.assertIn("not complete authentication", skill)
        for layer in (".agents/skills", ".claude/skills"):
            self.assertTrue((REPO_ROOT / "template" / layer / "web-conventions" / "SKILL.md.jinja").is_file(), layer)

    def test_the_pack_answers_for_two_web_apps_differ_only_in_their_own_identifiers(self) -> None:
        project = {"project_name": "Demo", "project_slug": "demo", "package_identifier": "com.example.demo"}
        web = pack_answers(project, {"id": "web", "stack": "nextjs-web", "path": "web", "audience": "B2C"}, port=3000)
        admin = pack_answers(project, {"id": "admin", "stack": "nextjs-web", "path": "admin", "audience": "internal"}, port=3001)
        differing = {key for key in web if web[key] != admin[key]}
        self.assertEqual(
            {"app_id", "app_name", "app_path", "audience", "port", "app_package_segment", "app_package", "app_package_path", "app_module_name", "ci_workflow_name", "ci_paths"},
            differing,
        )


class GeneratedWebAppsTests(unittest.TestCase):
    """A workspace with a backend and three web apps of one stack: two at the default paths and one nested."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory(prefix="prism-web-pack-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.scratch = Path(cls.temporary.name)
        cls.root = cls.scratch / "generated"
        generate_default_apps(
            cls.root,
            ["backend", "web"],
            cls.scratch,
            project_name="Layered Web",
            extra_apps=[ADMIN_APP, PARTNER_APP],
        )
        # The default web app carries an audience too, as the preset and the questionnaire let it.
        cls.apps = {
            "web": {"path": "web", "port": 3000, "name": "Web App"},
            "admin": {"path": "admin", "port": 3001, "name": "Admin App"},
            "partner-portal": {"path": "apps/partner", "port": 3002, "name": "Partner Portal"},
        }

    def text(self, relative: str) -> str:
        return (self.root / relative).read_text(encoding="utf-8")

    def answers(self, app: str) -> dict:
        return yaml.safe_load(self.text(f"{self.apps[app]['path']}/.copier-answers.yml"))

    def test_each_app_is_its_own_layer_with_its_own_identity(self) -> None:
        packages: set[str] = set()
        cookies: set[str] = set()
        for app, info in self.apps.items():
            with self.subTest(app=app):
                answers = self.answers(app)
                self.assertEqual(("nextjs-web", app, info["path"], info["port"]), (answers["prism_layer"], answers["app_id"], answers["app_path"], answers["port"]))
                package = json.loads(self.text(f"{info['path']}/package.json"))
                self.assertEqual(f"layered-web-{app}", package["name"])
                self.assertIn(f"--port {info['port']}", package["scripts"]["dev"])
                self.assertIn(f"--port {info['port']}", package["scripts"]["start"])
                packages.add(package["name"])
                self.assertEqual(f"layered-web-{app}", json.loads(self.text(f"{info['path']}/package-lock.json"))["name"])
                session = self.text(f"{info['path']}/lib/auth/session.ts")
                cookie = re.search(r'SESSION_COOKIE = "([^"]+)"', session).group(1)
                self.assertEqual(f"{app.replace('-', '_')}_session", cookie)
                cookies.add(cookie)
                self.assertTrue((self.root / ".github" / "workflows" / f"{app}.yml").is_file())
                self.assertTrue((self.root / ".cursor" / "rules" / f"{app}.mdc").is_file())
        self.assertEqual(3, len(packages), "distinct package names")
        self.assertEqual(3, len(cookies), "distinct session cookies, because localhost shares one cookie jar across ports")
        self.assertEqual({3000, 3001, 3002}, {info["port"] for info in self.apps.values()})

    def test_the_display_name_and_audience_are_text_in_app_info_only(self) -> None:
        expected = {"web": ("Web App", ""), "admin": ("Admin App", "internal"), "partner-portal": ("Partner Portal", "partners")}
        for app, (name, audience) in expected.items():
            with self.subTest(app=app):
                info = self.text(f"{self.apps[app]['path']}/lib/app-info.ts")
                self.assertIn(f'export const APP_NAME = "{name}"', info)
                self.assertIn(f'export const APP_AUDIENCE = "{audience}"', info)
        # Only the layout shows the audience: no route, check or permission reads it.
        readers = sorted(
            path.relative_to(self.root / "admin").as_posix()
            for path in (self.root / "admin").rglob("*")
            if path.suffix in {".ts", ".tsx"} and "node_modules" not in path.parts and "APP_AUDIENCE" in path.read_text(encoding="utf-8")
        )
        self.assertEqual(["app/layout.tsx", "lib/app-info.ts"], readers)

    def test_every_web_app_runs_the_same_ci_steps_scoped_to_its_path(self) -> None:
        for app, info in self.apps.items():
            with self.subTest(app=app):
                data = yaml.safe_load(self.text(f".github/workflows/{app}.yml"))
                self.assertEqual(f"{info['name']} CI ({app})", data["name"], "the display name is unique per app")
                triggers = data.get("on", data.get(True))
                for event in ("push", "pull_request"):
                    self.assertEqual([f"{info['path']}/**", "shared/api-contracts/**", f".github/workflows/{app}.yml"], triggers[event]["paths"])
                job = data["jobs"]["verify"]
                self.assertEqual("ubuntu-latest", job["runs-on"])
                self.assertEqual(info["path"], data["env"]["APP_PATH"], "the app's path reaches the workflow once, as a variable")
                self.assertEqual("${{ env.APP_PATH }}", job["defaults"]["run"]["working-directory"])
                runs = [step["run"] for step in job["steps"] if "run" in step]
                self.assertEqual(["npm ci", "npm run lint", "npm run typecheck", "npm test", "npm run build"], runs)
                setup = next(step for step in job["steps"] if str(step.get("uses", "")).startswith("actions/setup-node"))
                self.assertEqual(pins()["node"], str(setup["with"]["node-version"]))
                self.assertEqual("npm", setup["with"]["cache"])
                self.assertEqual("${{ env.APP_PATH }}/package-lock.json", setup["with"]["cache-dependency-path"])
                text = self.text(f".github/workflows/{app}.yml")
                for deploy in ("secrets.", "wrangler", "environment:"):
                    self.assertNotIn(deploy, text)

    def test_a_nested_app_reaches_the_contract_and_the_docs_from_its_own_depth(self) -> None:
        package = json.loads(self.text("apps/partner/package.json"))
        self.assertIn("openapi-typescript ../../shared/api-contracts/openapi.yml", package["scripts"]["generate:api"])
        guide = self.text("apps/partner/docs/guide.md")
        self.assertIn("(../../../docs/architecture.md)", guide)
        self.assertTrue((self.root / "shared" / "api-contracts" / "openapi.yml").is_file())
        self.assertIn("../shared/api-contracts/openapi.yml", json.loads(self.text("web/package.json"))["scripts"]["generate:api"])

    def test_the_rendered_contract_defines_the_two_operations_the_slice_calls(self) -> None:
        contract = yaml.safe_load(self.text("shared/api-contracts/openapi.yml"))
        token = contract["paths"]["/api/dev-identity/token"]["post"]
        self.assertEqual("createDevToken", token["operationId"])
        self.assertTrue(token["x-prism-dev-only"])
        self.assertEqual([], token["security"], "the dev identity needs no token to ask for one")
        me = contract["paths"]["/api/me"]["get"]
        self.assertEqual("getMe", me["operationId"])
        self.assertEqual([{"bearerAuth": []}], me.get("security", contract["security"]), "getMe uses the contract's default bearer security")

        def properties(operation: dict, where: str) -> set[str]:
            content = operation["requestBody"] if where == "request" else operation["responses"]["200"]
            ref = content["content"]["application/json"]["schema"]["$ref"].rsplit("/", 1)[1]
            return set(contract["components"]["schemas"][ref]["properties"])

        self.assertLessEqual({"email", "displayName"}, properties(token, "request"))
        self.assertLessEqual({"accessToken", "tokenType", "expiresIn"}, properties(token, "response"))
        self.assertLessEqual({"id", "displayName", "email", "createdAt"}, properties(me, "response"))

    def test_no_pack_file_is_left_with_jinja_or_placeholders(self) -> None:
        for app, info in self.apps.items():
            for path in sorted((self.root / info["path"]).rglob("*")):
                if not path.is_file() or path.suffix in {".png"}:
                    continue
                text = path.read_text(encoding="utf-8", errors="ignore")
                with self.subTest(app=app, file=path.relative_to(self.root).as_posix()):
                    self.assertNotIn("{%", text)
                    self.assertNotIn("{{ app_", text)
                    self.assertNotIn("{{ project_", text)
                    self.assertNotIn("{{ versions", text)

    def test_the_workspace_layer_wires_every_web_app(self) -> None:
        taskfile = yaml.safe_load(self.text("Taskfile.yml"))
        for app, info in self.apps.items():
            with self.subTest(app=app):
                self.assertEqual({"taskfile": f"./{info['path']}/Taskfile.yml", "dir": f"./{info['path']}"}, taskfile["includes"][app])
                self.assertIn({"task": f"{app}:generate-api"}, taskfile["tasks"]["generate-clients"]["cmds"])
                self.assertIn({"task": f"{app}:lint"}, taskfile["tasks"]["lint"]["cmds"])
                self.assertIn({"task": f"{app}:typecheck"}, taskfile["tasks"]["lint"]["cmds"])
                self.assertIn({"task": f"{app}:test"}, taskfile["tasks"]["test"]["cmds"])
                self.assertIn(f"{info['path']}/ -> Next.js", self.text("AGENTS.md"))
                self.assertIn(f"`task {app}:dev`", self.text("AGENTS.md"))
                self.assertIn(f"({info['path']}/docs/guide.md)", self.text("README.md"))
                self.assertIn(f"`{app}.yml`", self.text("docs/deployment/ci-cd.md"))
        self.assertNotIn("generate-client-typescript", self.text("Taskfile.yml"))
        self.assertNotIn("typescript-axios", self.text("Taskfile.yml"))

    def test_the_gitignore_of_the_workspace_has_no_web_section_and_each_app_ignores_its_own_output(self) -> None:
        self.assertNotIn("node_modules", self.text(".gitignore"))
        for info in self.apps.values():
            ignored = self.text(f"{info['path']}/.gitignore").splitlines()
            for entry in ("node_modules/", ".next/", "lib/api/generated/", "next-env.d.ts"):
                self.assertIn(entry, ignored)

    def test_the_manifest_records_each_web_app_as_scaffolded(self) -> None:
        manifest = yaml.safe_load(self.text("prism.workspace.yml"))
        apps = {app["id"]: app for app in manifest["apps"]}
        for app, info in self.apps.items():
            self.assertEqual(("nextjs-web", info["path"], "scaffolded"), (apps[app]["stack"], apps[app]["path"], apps[app]["generation"]))
            self.assertEqual("provisional", manifest["app_maturity"][app]["level"])
            self.assertIn(f".github/workflows/{app}.yml", manifest["expected_surfaces"]["workflows"])
        self.assertEqual("internal", apps["admin"]["audience"])

    def test_the_agent_guidance_of_every_web_app_states_the_dev_identity_limits(self) -> None:
        for app, info in self.apps.items():
            with self.subTest(app=app):
                agents = self.text(f"{info['path']}/AGENTS.md")
                self.assertIn("The dev identity is not authentication", agents)
                self.assertIn("`local` profile", agents)
                self.assertEqual("@AGENTS.md", self.text(f"{info['path']}/CLAUDE.md").splitlines()[0])
                rule = self.text(f".cursor/rules/{app}.mdc")
                self.assertIn(f'globs: "{info["path"]}/**"', rule)
                self.assertIn("not complete authentication", rule)
        self.assertIn("Local development sign-in", self.text("web/README.md"))


class AudienceTests(unittest.TestCase):
    def test_changing_the_audience_changes_display_text_and_nothing_else(self) -> None:
        entry = {"id": "web", "name": "Web App", "stack": "nextjs-web", "repository": "workspace", "path": "web", "generation": "scaffolded"}
        with tempfile.TemporaryDirectory(prefix="prism-web-audience-") as temporary:
            scratch = Path(temporary)
            roots = {
                audience: generate_default_apps(scratch / f"workspace-{index}", [], scratch, project_name="Audience Check", extra_apps=[{**entry, "audience": audience}])
                for index, audience in enumerate(("B2C", "internal staff"))
            }
            first, second = roots["B2C"] / "web", roots["internal staff"] / "web"

            def files(root: Path) -> list[str]:
                return sorted(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file())

            self.assertEqual(files(first), files(second), "the audience adds and removes no file")
            differing = 0
            for relative in files(first):
                one = (first / relative).read_text(encoding="utf-8", errors="ignore").splitlines()
                two = (second / relative).read_text(encoding="utf-8", errors="ignore").splitlines()
                with self.subTest(file=relative):
                    self.assertEqual(len(one), len(two), "the audience adds and removes no line")
                    for left, right in zip(one, two):
                        if left != right:
                            differing += 1
                            self.assertTrue("B2C" in left and "internal staff" in right, (left, right))
            self.assertGreater(differing, 0, "the audience is shown somewhere")


class PresetTests(unittest.TestCase):
    def test_the_backend_web_preset_scaffolds_a_backend_and_one_web_app(self) -> None:
        with tempfile.TemporaryDirectory(prefix="prism-web-preset-") as temporary:
            destination = Path(temporary) / "preset"
            code, out, err = run_cli("new", "--preset", "backend-web", "--project-name", "Preset Web", "--dest", str(destination), "--yes")
            self.assertEqual(0, code, out + err)
            manifest = yaml.safe_load((destination / "prism.workspace.yml").read_text(encoding="utf-8"))
            self.assertEqual(["backend", "web"], [app["id"] for app in manifest["apps"]])
            self.assertEqual(["spring-backend", "nextjs-web"], [app["stack"] for app in manifest["apps"]])
            answers = yaml.safe_load((destination / "web" / ".copier-answers.yml").read_text(encoding="utf-8"))
            self.assertEqual((3000, "nextjs-web"), (answers["port"], answers["prism_layer"]))
            self.assertFalse((destination / "web-user-app").exists())
            self.assertFalse((destination / "web-admin-portal").exists())
            self.assertTrue((destination / "web" / "package-lock.json").is_file())


if __name__ == "__main__":
    unittest.main()
