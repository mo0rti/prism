"""Every client knows the address of the backend it calls: with two backends, a client generated against the second one points at its port.

The logic tests need no Copier. The generation tests run the Prism CLI against a disposable, tagged copy of the template
and read what each client contains, as `test_layered_generation` does.
"""

from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
import unittest

import yaml

from prism_cli.app_model import normalize_manifest
from prism_cli.packs import (
    DEFAULT_BACKEND_PORT,
    backend_of,
    backend_port_in_workspace,
    backend_port_of,
    layer_answers_problems,
    pack_answers,
    parse_app_list,
)
from tests import real_temp  # noqa: F401
from tests.layered_support import build_template_repo, commit_workspace, generate_workspace, git, read_yaml, run_cli

BACKEND = {"id": "backend", "stack": "spring-backend", "generation": "scaffolded"}
BILLING = {"id": "billing-api", "stack": "spring-backend", "generation": "scaffolded", "path": "services/billing-api"}
PROJECT = {"project_name": "Demo", "project_slug": "demo", "package_identifier": "com.example.demo"}


def web(**fields: object) -> dict:
    return {"id": "web", "stack": "nextjs-web", "generation": "scaffolded", **fields}


class BackendChoiceTests(unittest.TestCase):
    def test_a_client_calls_the_first_scaffolded_backend_unless_it_names_another(self) -> None:
        apps = [BACKEND, BILLING, web()]
        self.assertEqual("backend", backend_of(apps[2], apps)["id"])
        self.assertEqual("billing-api", backend_of(web(backend="billing-api"), apps)["id"])
        self.assertIsNone(backend_of(web(backend="ghost"), apps))
        self.assertIsNone(backend_of(BACKEND, apps), "a backend calls no backend")
        registered = {"id": "legacy", "stack": "spring-backend", "generation": "registered"}
        self.assertEqual("backend", backend_of(web(), [registered, BACKEND, web()])["id"], "only a backend that Prism scaffolds is the default")

    def test_the_port_is_the_backends_own_and_falls_back_to_the_first_port_of_the_range(self) -> None:
        ports = {"backend": 8080, "billing-api": 8081}
        apps = [BACKEND, BILLING, web()]
        self.assertEqual(8080, backend_port_of(web(), apps, ports))
        self.assertEqual(8081, backend_port_of(web(backend="billing-api"), apps, ports))
        self.assertEqual(DEFAULT_BACKEND_PORT, backend_port_of(web(), [web()], {}), "no backend in the workspace")
        self.assertEqual(DEFAULT_BACKEND_PORT, backend_port_of(web(backend="billing-api"), apps, {}), "a port that is not remembered")

    def test_only_a_client_stack_gets_the_answer_and_it_is_a_loopback_url_without_a_slash(self) -> None:
        for stack, expected in (("nextjs-web", True), ("android-compose", True), ("ios-swiftui", True), ("python-agent-service", True), ("spring-backend", False)):
            with self.subTest(stack=stack):
                answers = pack_answers(PROJECT, {"id": "app", "stack": stack, "path": "app"}, port=3000, backend_port=8081)
                self.assertEqual(expected, "backend_base_url" in answers)
                if expected:
                    self.assertEqual("http://localhost:8081", answers["backend_base_url"])
        self.assertEqual("http://localhost:8080", pack_answers(PROJECT, web(path="web"), port=3000)["backend_base_url"])

    def test_an_answers_file_may_name_the_backend_of_a_client_and_the_name_is_checked(self) -> None:
        entries, _repositories, errors = parse_app_list([{"id": "backend", "stack": "spring-backend"}, {"id": "billing-api", "stack": "spring-backend", "path": "services/billing-api"}, {"id": "web", "stack": "nextjs-web", "backend": "billing-api"}])
        self.assertEqual([], errors)
        self.assertEqual("billing-api", entries[2]["backend"])
        self.assertNotIn("backend", entries[0])
        for backend, message in (("ghost", "unknown-app-backend"), ("web", "unknown-app-backend")):
            with self.subTest(backend=backend):
                _entries, _repositories, errors = parse_app_list([{"id": "backend", "stack": "spring-backend"}, {"id": "web", "stack": "nextjs-web", "backend": backend}])
                self.assertTrue(any(message in error for error in errors), errors)
        _entries, _repositories, errors = parse_app_list([{"id": "backend", "stack": "spring-backend", "backend": "backend"}])
        self.assertTrue(any("invalid-app-backend" in error for error in errors), errors)

    def test_the_manifest_normalizer_checks_the_backend_field(self) -> None:
        def codes(*apps: dict) -> list[str]:
            data = {"schema_version": 2, "project": {"name": "Demo"}, "apps": list(apps)}
            return sorted(item.code for item in normalize_manifest(data, path=Path("prism.workspace.yml"))[1])

        backend = {"id": "backend", "stack": "spring-backend", "path": "backend"}
        self.assertEqual([], codes(backend, {"id": "web", "stack": "nextjs-web", "path": "web", "backend": "backend"}))
        self.assertEqual(["unknown-app-backend"], codes(backend, {"id": "web", "stack": "nextjs-web", "path": "web", "backend": "ghost"}))
        self.assertEqual(["invalid-app-backend"], codes(backend, {"id": "api", "stack": "spring-backend", "path": "api", "backend": "backend"}))
        self.assertEqual(["invalid-app-backend"], codes(backend, {"id": "web", "stack": "nextjs-web", "path": "web", "backend": "Not A Slug"}))

    def test_a_remembered_address_must_be_loopback(self) -> None:
        workspace = {**PROJECT}
        app = {"id": "web", "name": "web", "stack": "nextjs-web", "path": "web", "audience": ""}
        base = {**pack_answers(PROJECT, app, port=3000), "_src_path": "git+https://example.test/t.git", "_commit": "v1.0.0", "port": 3000, "prism_layer": "nextjs-web"}
        self.assertEqual([], layer_answers_problems(base, workspace, app, approved_source="git+https://example.test/t.git"))
        for url in ("http://backend.internal:8080", "https://api.example.com", "http://localhost:80/path", "http://localhost.evil.test:8080", "javascript:alert(1)"):
            with self.subTest(url=url):
                problems = layer_answers_problems({**base, "backend_base_url": url}, workspace, app, approved_source="git+https://example.test/t.git")
                self.assertTrue(any("loopback" in problem for problem in problems), problems)
        self.assertEqual([], layer_answers_problems({**base, "backend_base_url": "http://localhost:8081/"}, workspace, app, approved_source="git+https://example.test/t.git"), "another port is the point")


class LayeredBackendTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory(prefix="prism-backend-address-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        cls.repo = build_template_repo(cls.root / "template-repo")


class TwoBackendsGenerationTests(LayeredBackendTestCase):
    """One workspace, two backends, and a client of each kind generated against the second one."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.workspace = cls.root / "ws"
        apps = [
            {"id": "backend", "stack": "spring-backend", "name": "Core API"},
            {"id": "billing-api", "stack": "spring-backend", "name": "Billing API", "path": "services/billing-api"},
            {"id": "web", "stack": "nextjs-web", "backend": "billing-api"},
            {"id": "web-two", "stack": "nextjs-web", "path": "web-two"},
            {"id": "mobile-android", "stack": "android-compose", "backend": "billing-api"},
            {"id": "mobile-ios", "stack": "ios-swiftui"},
            {"id": "agent-service", "stack": "python-agent-service", "backend": "billing-api"},
        ]
        code, out, err = generate_workspace(cls.repo, cls.workspace, {"project_name": "Two Backends", "apps": apps}, cls.root)
        if code != 0:
            raise AssertionError(out + err)

    def text(self, relative: str) -> str:
        return (self.workspace / relative).read_text(encoding="utf-8")

    def test_the_backends_hold_their_own_ports(self) -> None:
        self.assertEqual(8080, read_yaml(self.workspace / "backend" / ".copier-answers.yml")["port"])
        self.assertEqual(8081, read_yaml(self.workspace / "services" / "billing-api" / ".copier-answers.yml")["port"])

    def test_a_web_app_generated_against_the_second_backend_points_at_its_port(self) -> None:
        self.assertIn('export const DEFAULT_API_BASE_URL = "http://localhost:8081"', self.text("web/lib/api/config.ts"))
        self.assertIn("API_BASE_URL=http://localhost:8081\n", self.text("web/.env.example"))
        self.assertIn('toBe("http://localhost:8081/api/me")', self.text("web/tests/api-client.test.ts"))
        self.assertNotIn("8080", self.text("web/lib/api/config.ts") + self.text("web/.env.example"))
        self.assertEqual("http://localhost:8081", read_yaml(self.workspace / "web" / ".copier-answers.yml")["backend_base_url"])

    def test_a_web_app_with_no_backend_named_points_at_the_first_backend(self) -> None:
        self.assertIn('DEFAULT_API_BASE_URL = "http://localhost:8080"', self.text("web-two/lib/api/config.ts"))
        self.assertIn("API_BASE_URL=http://localhost:8080\n", self.text("web-two/.env.example"))

    def test_the_agent_service_calls_the_second_backend(self) -> None:
        self.assertIn('backend_base_url: str = "http://localhost:8081"', self.text("agent-service/app/config.py"))
        self.assertIn("AGENT_BACKEND_BASE_URL=http://localhost:8081\n", self.text("agent-service/.env.example"))
        self.assertIn("http://localhost:8081/api/dev-identity/token", self.text("agent-service/README.md"))

    def test_the_android_app_calls_and_reverses_the_second_backends_port(self) -> None:
        self.assertIn("\napiBaseUrl=http://localhost:8081/\n", self.text("mobile-android/gradle.properties"))
        self.assertEqual("8081", yaml.safe_load(self.text("mobile-android/Taskfile.yml"))["vars"]["BACKEND_PORT"])
        self.assertIn("http://localhost:8081/", self.text("mobile-android/AGENTS.md"))
        self.assertIn("adb reverse tcp:8081 tcp:8081", self.text(".cursor/rules/mobile-android.mdc"))

    def test_the_ios_app_with_no_backend_named_calls_the_first_backend(self) -> None:
        data = yaml.safe_load(self.text("mobile-ios/project.yml"))
        self.assertEqual("http://localhost:8080", data["targets"]["MobileIos"]["settings"]["configs"]["Debug"]["API_BASE_URL"])

    def test_the_shared_contract_lists_every_backend(self) -> None:
        contract = yaml.safe_load(self.text("shared/api-contracts/openapi.yml"))
        self.assertEqual(["http://localhost:8080", "http://localhost:8081"], [server["url"] for server in contract["servers"]])
        self.assertEqual(["backend (local development)", "billing-api (local development)"], [server["description"] for server in contract["servers"]])
        conventions = self.text("docs/api/conventions.md")
        self.assertIn("`http://localhost:8080` (`backend`), `http://localhost:8081` (`billing-api`)", conventions)
        self.assertIn("`AGENT_BACKEND_BASE_URL`", conventions)

    def test_the_manifest_records_only_the_backends_a_client_names(self) -> None:
        manifest = read_yaml(self.workspace / "prism.workspace.yml")
        named = {app["id"]: app.get("backend") for app in manifest["apps"]}
        self.assertEqual({"backend": None, "billing-api": None, "web": "billing-api", "web-two": None, "mobile-android": "billing-api", "mobile-ios": None, "agent-service": "billing-api"}, named)
        self.assertEqual([], normalize_manifest(manifest, path=Path("prism.workspace.yml"))[1])

    def test_no_default_address_is_left_hard_coded(self) -> None:
        for relative in ("web/lib/api/config.ts", "web/.env.example", "agent-service/app/config.py", "agent-service/.env.example", "mobile-android/gradle.properties"):
            with self.subTest(file=relative):
                self.assertNotRegex(self.text(relative), r"localhost:8080")

    def test_the_generated_workspace_validates(self) -> None:
        code, out, err = run_cli("validate", str(self.workspace))
        self.assertEqual(0, code, out + err)

    def test_every_generated_value_is_a_valid_loopback_address(self) -> None:
        for relative in ("web", "web-two", "mobile-android", "mobile-ios", "agent-service"):
            answers = read_yaml(self.workspace / relative / ".copier-answers.yml")
            with self.subTest(app=relative):
                self.assertRegex(answers["backend_base_url"], r"^http://localhost:80[0-9]{2}$")
                self.assertNotIn("backend_port", answers, "the port is derived, never remembered separately")


class ScaffoldAClientOfTheSecondBackendTests(LayeredBackendTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.base = cls.root / "base"
        apps = [{"id": "backend", "stack": "spring-backend"}, {"id": "billing-api", "stack": "spring-backend", "path": "services/billing-api"}]
        code, out, err = generate_workspace(cls.repo, cls.base, {"project_name": "Two Backends", "apps": apps}, cls.root)
        if code != 0:
            raise AssertionError(out + err)
        commit_workspace(cls.base)

    def copy(self, name: str) -> Path:
        destination = self.root / name
        shutil.copytree(self.base, destination)
        return destination

    def test_a_preview_names_the_backend_the_new_app_calls(self) -> None:
        ws = self.copy("preview")
        code, out, err = run_cli("app", "add", "web", "--stack", "nextjs-web", "--backend", "billing-api", "--scaffold", str(ws))
        self.assertEqual(0, code, err)
        self.assertIn("It calls the backend at `http://localhost:8081`", out)
        self.assertEqual("", git(ws, "status", "--porcelain").stdout)

    def test_apply_scaffolds_the_client_against_the_backend_it_names(self) -> None:
        ws = self.copy("applied")
        code, out, err = run_cli("app", "add", "web", "--stack", "nextjs-web", "--backend", "billing-api", "--scaffold", "--apply", "--yes", "--trust-template", str(ws))
        self.assertEqual(0, code, out + err)
        self.assertEqual("http://localhost:8081", read_yaml(ws / "web" / ".copier-answers.yml")["backend_base_url"])
        self.assertIn('DEFAULT_API_BASE_URL = "http://localhost:8081"', (ws / "web" / "lib" / "api" / "config.ts").read_text(encoding="utf-8"))
        manifest = read_yaml(ws / "prism.workspace.yml")
        self.assertEqual("billing-api", next(app for app in manifest["apps"] if app["id"] == "web")["backend"])
        self.assertEqual("", git(ws, "status", "--porcelain").stdout)

    def test_a_client_that_names_no_backend_calls_the_first_one(self) -> None:
        ws = self.copy("default")
        code, out, err = run_cli("app", "add", "mobile-android", "--stack", "android-compose", "--scaffold", "--apply", "--yes", "--trust-template", str(ws))
        self.assertEqual(0, code, out + err)
        self.assertEqual("http://localhost:8080", read_yaml(ws / "mobile-android" / ".copier-answers.yml")["backend_base_url"])
        self.assertIn("\napiBaseUrl=http://localhost:8080/\n", (ws / "mobile-android" / "gradle.properties").read_text(encoding="utf-8"))
        manifest = read_yaml(ws / "prism.workspace.yml")
        self.assertNotIn("backend", next(app for app in manifest["apps"] if app["id"] == "mobile-android"))

    def test_a_backend_that_is_not_a_backend_app_is_refused(self) -> None:
        ws = self.copy("refused")
        code, _out, err = run_cli("app", "add", "web", "--stack", "nextjs-web", "--backend", "nobody", "--scaffold", str(ws))
        self.assertEqual(3, code)
        self.assertIn("unknown-app-backend", err)
        self.assertFalse((ws / "web").exists())

    def test_the_port_comes_from_the_backends_answers_file(self) -> None:
        apps = [{"id": item["id"], "stack": "spring-backend", "path": item["path"], "generation": "scaffolded"} for item in ({"id": "backend", "path": "backend"}, {"id": "billing-api", "path": "services/billing-api"})]
        client = {"id": "web", "stack": "nextjs-web", "backend": "billing-api"}
        self.assertEqual(8081, backend_port_in_workspace(self.base, client, apps))
        self.assertEqual(8080, backend_port_in_workspace(self.base, {"id": "web", "stack": "nextjs-web"}, apps))


if __name__ == "__main__":
    unittest.main()
