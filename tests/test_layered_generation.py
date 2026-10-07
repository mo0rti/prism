"""Two-layer generation, scaffolding and updates, with real Copier against a disposable, tagged copy of the template.

Each class builds its own template repository under a temporary folder (see `layered_support`), so a tag
can be added without touching the repository under test, and the workspaces record a real `_commit`.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import yaml

from prism_cli import cli
from prism_cli.app_model import normalize_manifest
from tests import real_temp  # noqa: F401
from tests.layered_support import (
    build_template_repo,
    commit_workspace,
    generate_workspace,
    git,
    read_yaml,
    remove_tree,
    run_cli,
    tag_template_change,
    template_url,
    write_answers,
)

BACKEND = {"id": "backend", "stack": "spring-backend", "name": "Spring Boot Backend"}
API_TWO = {"id": "api-two", "stack": "spring-backend", "name": "Second API", "path": "services/api-two"}
PACK_AGENTS = "packs/spring-backend/{{ app_path }}/AGENTS.md.jinja"
WORKSPACE_DOCS = "template/docs/README.md.jinja"


def text_files(root: Path):
    for path in sorted(root.rglob("*")):
        if path.is_file() and ".git" not in path.relative_to(root).parts and path.suffix not in {".jar", ".png", ".webp"}:
            yield path


class LayeredTestCase(unittest.TestCase):
    """A scratch folder, a template repository at v1.0.0 and helpers to generate from it."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory(prefix="prism-layers-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        cls.repo = build_template_repo(cls.root / "template-repo")

    def generate(self, name: str, apps: list[dict], **answers: object) -> Path:
        destination = self.root / name
        code, out, err = generate_workspace(self.repo, destination, {"project_name": "Layered App", "apps": apps, **answers}, self.root)
        self.assertEqual(0, code, out + err)
        return destination


class WorkspaceAndBackendTests(LayeredTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.workspace = cls.root / "preset"
        code, out, err = run_cli(
            "new", "--template", template_url(cls.repo), "--trust-template", "--preset", "backend-only",
            "--project-name", "Layered App", "--dest", str(cls.workspace), "--yes",
        )
        if code != 0:
            raise AssertionError(out + err)

    def test_the_workspace_layer_holds_no_app_code_and_the_backend_is_the_pack(self) -> None:
        ws = self.workspace
        self.assertTrue((ws / "backend" / "build.gradle.kts").is_file())
        self.assertTrue((ws / "backend" / "src" / "main" / "kotlin" / "com" / "example" / "layeredapp" / "backend" / "Application.kt").is_file())
        self.assertFalse((ws / "backend" / "src" / "main" / "kotlin" / "com" / "example" / "layeredapp" / "modules").exists(), "the full backend sample is not generated")
        for name in ("web", "mobile-android", "mobile-ios"):
            self.assertFalse((ws / name).exists(), name)
        self.assertTrue((ws / "knowledge" / "wiki" / "SCHEMA.md").is_file())
        self.assertTrue((ws / "shared" / "api-contracts" / "openapi.yml").is_file())

    def test_each_layer_keeps_its_own_answers_file_with_the_template_revision(self) -> None:
        workspace = read_yaml(self.workspace / ".copier-answers.yml")
        app = read_yaml(self.workspace / "backend" / ".copier-answers.yml")
        self.assertEqual("workspace", workspace["prism_layer"])
        self.assertEqual("spring-backend", app["prism_layer"])
        self.assertEqual(["spring-backend"], workspace["stacks"])
        self.assertEqual(["backend"], [entry["id"] for entry in workspace["apps"]])
        for answers in (workspace, app):
            self.assertEqual("v1.0.0", answers["_commit"])
            self.assertEqual(template_url(self.repo), answers["_src_path"])
        self.assertEqual("backend", app["app_id"])
        self.assertEqual(8080, app["port"])
        self.assertEqual("com.example.layeredapp.backend", app["app_package"])
        self.assertNotIn("versions", app, "the pinned versions are read from the template, never remembered")
        self.assertNotIn("pack_versions", workspace)

    def test_the_manifest_records_the_app_as_scaffolded(self) -> None:
        manifest = read_yaml(self.workspace / "prism.workspace.yml")
        model, diagnostics = normalize_manifest(manifest, path=Path("prism.workspace.yml"))
        self.assertEqual([], diagnostics)
        app = model.app("backend")
        self.assertTrue(app.scaffolded)
        self.assertEqual("scaffolded", app.generation)
        self.assertEqual({"level": "baseline", "caveat": ""}, model.maturity("backend"))
        self.assertEqual([".github/workflows/backend.yml"], manifest["expected_surfaces"]["workflows"])

    def test_the_root_files_list_the_backend_app(self) -> None:
        ws = self.workspace
        compose = yaml.safe_load((ws / "docker-compose.yml").read_text(encoding="utf-8"))
        self.assertEqual({"backend", "db"}, set(compose["services"]))
        self.assertEqual(["127.0.0.1:8080:8080"], compose["services"]["backend"]["ports"], "a published port stays on this machine")
        self.assertNotIn("SPRING_PROFILES_ACTIVE", (ws / "docker-compose.yml").read_text(encoding="utf-8"), "no default profile")
        taskfile = yaml.safe_load((ws / "Taskfile.yml").read_text(encoding="utf-8"))
        self.assertEqual("./backend/Taskfile.yml", taskfile["includes"]["backend"]["taskfile"])
        self.assertIn("backend/", (ws / "AGENTS.md").read_text(encoding="utf-8"))
        self.assertTrue((ws / ".github" / "workflows" / "backend.yml").is_file())
        self.assertTrue((ws / ".github" / "workflows" / "api-contracts.yml").is_file())
        rule = (ws / ".cursor" / "rules" / "backend.mdc").read_text(encoding="utf-8")
        self.assertIn('globs: "backend/**"', rule)

    def test_the_backend_workflow_and_rule_are_scoped_to_the_apps_path(self) -> None:
        workflow = yaml.safe_load((self.workspace / ".github" / "workflows" / "backend.yml").read_text(encoding="utf-8"))
        triggers = workflow.get("on", workflow.get(True))
        self.assertEqual(["backend/**", "shared/api-contracts/**", ".github/workflows/backend.yml"], triggers["push"]["paths"])
        self.assertEqual("Spring Boot Backend CI (backend)", workflow["name"])
        text = (self.workspace / ".github" / "workflows" / "backend.yml").read_text(encoding="utf-8")
        self.assertIn('APP_PATH: "backend"', text)
        self.assertIn("working-directory: ${{ env.APP_PATH }}", text)

    def test_no_generated_file_keeps_a_template_placeholder(self) -> None:
        for path in text_files(self.workspace):
            if path.name == "gradlew" or ".agents" in path.parts or ".claude" in path.parts:
                continue
            content = path.read_text(encoding="utf-8", errors="ignore")
            with self.subTest(path=path.relative_to(self.workspace).as_posix()):
                self.assertNotIn("{%", content)
                self.assertNotRegex(content, r"\{\{ (app_|project_|versions|package_)")

    def test_the_generated_workspace_validates(self) -> None:
        code, out, err = run_cli("validate", str(self.workspace))
        self.assertEqual(0, code, out + err)


class TwoBackendsTests(LayeredTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.workspace = cls.root / "two"
        code, out, err = generate_workspace(cls.repo, cls.workspace, {"project_name": "Layered App", "apps": [BACKEND, API_TWO]}, cls.root)
        if code != 0:
            raise AssertionError(out + err)

    def test_the_two_apps_differ_in_every_derived_identifier(self) -> None:
        first = read_yaml(self.workspace / "backend" / ".copier-answers.yml")
        second = read_yaml(self.workspace / "services" / "api-two" / ".copier-answers.yml")
        self.assertEqual((8080, 8081), (first["port"], second["port"]))
        self.assertEqual(("com.example.layeredapp.backend", "com.example.layeredapp.apitwo"), (first["app_package"], second["app_package"]))
        self.assertEqual(("Backend", "ApiTwo"), (first["app_module_name"], second["app_module_name"]))
        self.assertEqual(("Spring Boot Backend CI (backend)", "Second API CI (api-two)"), (first["ci_workflow_name"], second["ci_workflow_name"]))
        for path, package in (("backend", "backend"), ("services/api-two", "apitwo")):
            self.assertTrue((self.workspace / path / "src" / "main" / "kotlin" / "com" / "example" / "layeredapp" / package / "Application.kt").is_file(), path)
        settings = (self.workspace / "services" / "api-two" / "settings.gradle.kts").read_text(encoding="utf-8")
        self.assertIn('rootProject.name = "api-two"', settings)
        self.assertIn("port: ${PORT:8081}", (self.workspace / "services" / "api-two" / "src" / "main" / "resources" / "application.yml").read_text(encoding="utf-8"))

    def test_each_app_has_its_own_workflow_and_rule_scoped_to_its_path(self) -> None:
        workflows = sorted(path.name for path in (self.workspace / ".github" / "workflows").iterdir())
        self.assertEqual(["api-contracts.yml", "api-two.yml", "backend.yml"], workflows)
        text = (self.workspace / ".github" / "workflows" / "api-two.yml").read_text(encoding="utf-8")
        self.assertIn('"services/api-two/**"', text)
        self.assertIn('APP_PATH: "services/api-two"', text)
        self.assertIn("working-directory: ${{ env.APP_PATH }}", text)
        self.assertIn('globs: "services/api-two/**"', (self.workspace / ".cursor" / "rules" / "api-two.mdc").read_text(encoding="utf-8"))

    def test_the_workspace_layer_lists_both_apps(self) -> None:
        compose = yaml.safe_load((self.workspace / "docker-compose.yml").read_text(encoding="utf-8"))
        self.assertEqual({"backend", "api-two", "db"}, set(compose["services"]))
        self.assertEqual(["127.0.0.1:8081:8081"], compose["services"]["api-two"]["ports"])
        self.assertEqual("./services/api-two", compose["services"]["api-two"]["build"]["context"])
        taskfile = yaml.safe_load((self.workspace / "Taskfile.yml").read_text(encoding="utf-8"))
        self.assertEqual({"backend", "api-two"}, set(taskfile["includes"]))
        self.assertEqual("./services/api-two/Taskfile.yml", taskfile["includes"]["api-two"]["taskfile"])
        self.assertIn("task: api-two:test", (self.workspace / "Taskfile.yml").read_text(encoding="utf-8"))
        guide = (self.workspace / "services" / "api-two" / "docs" / "guide.md").read_text(encoding="utf-8")
        self.assertIn("(../../../docs/architecture.md)", guide, "the links climb out of the app's own depth")

    def test_the_manifest_records_both_apps_and_their_workflows(self) -> None:
        manifest = read_yaml(self.workspace / "prism.workspace.yml")
        model, diagnostics = normalize_manifest(manifest, path=Path("prism.workspace.yml"))
        self.assertEqual([], diagnostics)
        self.assertEqual(["backend", "api-two"], model.active_app_ids)
        self.assertEqual(["services/api-two"], [app.path for app in model.apps if app.id == "api-two"])
        self.assertEqual({"backend", "api-two"}, set(manifest["app_maturity"]))
        self.assertEqual([".github/workflows/backend.yml", ".github/workflows/api-two.yml"], manifest["expected_surfaces"]["workflows"])


class PackStacksTests(LayeredTestCase):
    """Every stack with a pack is generated as an app layer of its own; a stack without a pack is only registered."""

    def test_the_four_stacks_are_packs_with_layers_of_their_own(self) -> None:
        apps = [
            BACKEND,
            {"id": "web", "stack": "nextjs-web", "name": "Web App"},
            {"id": "mobile-android", "stack": "android-compose", "name": "Android (Kotlin/Compose)"},
            {"id": "mobile-ios", "stack": "ios-swiftui", "name": "iOS (Swift/SwiftUI)"},
        ]
        ws = self.generate("packs", apps)
        for name in ("backend", "web", "mobile-android", "mobile-ios"):
            self.assertTrue((ws / name / ".copier-answers.yml").is_file(), f"{name} is a pack with a layer of its own")
        self.assertTrue((ws / "mobile-android" / "app" / "build.gradle.kts").is_file())
        self.assertTrue((ws / "mobile-ios" / "project.yml").is_file())
        self.assertTrue((ws / ".github" / "workflows" / "mobile-ios.yml").is_file())
        self.assertTrue((ws / ".cursor" / "rules" / "mobile-ios.mdc").is_file())
        self.assertEqual("ios-swiftui", read_yaml(ws / "mobile-ios" / ".copier-answers.yml")["prism_layer"])
        self.assertTrue((ws / "web" / "package-lock.json").is_file())
        self.assertTrue((ws / ".github" / "workflows" / "web.yml").is_file())
        self.assertTrue((ws / ".cursor" / "rules" / "web.mdc").is_file())
        workspace = read_yaml(ws / ".copier-answers.yml")
        self.assertEqual(["android-compose", "ios-swiftui", "nextjs-web", "spring-backend"], workspace["stacks"])
        self.assertEqual(["backend", "web", "mobile-android", "mobile-ios"], [entry["id"] for entry in workspace["apps"]])
        manifest = read_yaml(ws / "prism.workspace.yml")
        self.assertEqual({"backend", "web", "mobile-android", "mobile-ios"}, set(manifest["app_maturity"]))
        self.assertEqual("experimental", manifest["app_maturity"]["mobile-ios"]["level"])
        self.assertEqual("provisional", manifest["app_maturity"]["web"]["level"])

    def test_an_app_of_a_stack_without_a_pack_cannot_be_scaffolded(self) -> None:
        answers = write_answers(self.root / "custom.yml", {"project_name": "Custom", "apps": [{"id": "customer-tool", "stack": "other", "generation": "scaffolded"}]})
        code, _out, err = run_cli("new", "--template", template_url(self.repo), "--trust-template", "--answers", str(answers), "--dest", str(self.root / "custom"), "--yes")
        self.assertEqual(3, code)
        self.assertIn("App `customer-tool` cannot be `scaffolded`", err)
        self.assertIn("registers the others", err)
        self.assertFalse((self.root / "custom").exists())

    def test_two_android_apps_are_two_app_layers_with_their_own_identifiers(self) -> None:
        apps = [
            BACKEND,
            {"id": "mobile-android", "stack": "android-compose", "name": "Customer App", "audience": "B2C"},
            {"id": "partner-android", "stack": "android-compose", "name": "Partner App", "path": "apps/partner", "audience": "partners"},
        ]
        ws = self.generate("two-android", apps)
        identifiers = {}
        for app_id, path, segment in (("mobile-android", "mobile-android", "mobileandroid"), ("partner-android", "apps/partner", "partnerandroid")):
            answers = read_yaml(ws / path / ".copier-answers.yml")
            self.assertEqual(("android-compose", app_id, path, f"com.example.layeredapp.{segment}", 0), (answers["prism_layer"], answers["app_id"], answers["app_path"], answers["app_package"], answers["port"]))
            package_dir = ws / path / "app" / "src" / "main" / "kotlin" / "com" / "example" / "layeredapp" / segment
            self.assertTrue((package_dir / "ui" / "signin" / "SignInScreen.kt").is_file(), app_id)
            self.assertTrue((ws / path / "app" / "src" / "test" / "kotlin" / "com" / "example" / "layeredapp" / segment / "ui" / "signin" / "SignInScreenTest.kt").is_file(), app_id)
            gradle = (ws / path / "app" / "build.gradle.kts").read_text(encoding="utf-8")
            self.assertIn(f'namespace = "com.example.layeredapp.{segment}"', gradle)
            self.assertIn(f'applicationId = "com.example.layeredapp.{segment}"', gradle)
            self.assertIn(f'rootProject.name = "{app_id}"', (ws / path / "settings.gradle.kts").read_text(encoding="utf-8"))
            workflow = (ws / ".github" / "workflows" / f"{app_id}.yml").read_text(encoding="utf-8")
            self.assertIn(f'APP_PATH: "{path}"', workflow)
            self.assertIn("working-directory: ${{ env.APP_PATH }}", workflow)
            self.assertIn("./gradlew assembleDebug testDebugUnitTest", workflow)
            self.assertIn(f"{path}/**", workflow)
            rule = (ws / ".cursor" / "rules" / f"{app_id}.mdc").read_text(encoding="utf-8")
            self.assertIn(f'globs: "{path}/**"', rule)
            identifiers[app_id] = (answers["app_package"], f"{app_id}.yml", gradle)
        self.assertEqual(2, len({value[0] for value in identifiers.values()}), "two apps never share an application ID")
        self.assertEqual(2, len({value[2] for value in identifiers.values()}), "two apps never share a build file")
        workspace = read_yaml(ws / ".copier-answers.yml")
        self.assertEqual(["android-compose", "spring-backend"], workspace["stacks"])
        taskfile = (ws / "Taskfile.yml").read_text(encoding="utf-8")
        self.assertIn('taskfile: "./mobile-android/Taskfile.yml"', taskfile)
        self.assertIn('taskfile: "./apps/partner/Taskfile.yml"', taskfile)
        self.assertFalse((ws / "mobile-android" / "local.config.properties").exists(), "the retired sample's local config is gone")
        self.assertFalse((ws / "mobile-android" / "fastlane").exists())
        manifest = read_yaml(ws / "prism.workspace.yml")
        self.assertEqual({"backend", "mobile-android", "partner-android"}, set(manifest["app_maturity"]))

    def test_a_custom_web_app_is_scaffolded_at_its_own_path_by_the_pack(self) -> None:
        apps = [BACKEND, {"id": "customer-portal", "stack": "nextjs-web", "name": "Customer Portal", "path": "apps/portal", "audience": "customers"}]
        ws = self.generate("portal", apps)
        self.assertTrue((ws / "apps" / "portal" / "package.json").is_file())
        answers = read_yaml(ws / "apps" / "portal" / ".copier-answers.yml")
        self.assertEqual(("nextjs-web", "customer-portal", "apps/portal", 3000, "customers"), (answers["prism_layer"], answers["app_id"], answers["app_path"], answers["port"], answers["audience"]))
        self.assertTrue((ws / ".github" / "workflows" / "customer-portal.yml").is_file())
        self.assertTrue((ws / ".cursor" / "rules" / "customer-portal.mdc").is_file())
        self.assertFalse((ws / "customer-portal").exists())

    def test_a_registered_app_generates_no_code_and_no_layer(self) -> None:
        apps = [BACKEND, {"id": "partner-web", "stack": "nextjs-web", "generation": "registered", "path": "apps/partner"}]
        ws = self.generate("registered", apps)
        self.assertFalse((ws / "apps").exists())
        manifest = read_yaml(ws / "prism.workspace.yml")
        entries = {app["id"]: app for app in manifest["apps"]}
        self.assertEqual("registered", entries["partner-web"]["generation"])
        self.assertNotIn("partner-web", manifest["app_maturity"])
        self.assertEqual([".github/workflows/backend.yml"], manifest["expected_surfaces"]["workflows"])
        self.assertEqual(["backend"], [entry["id"] for entry in read_yaml(ws / ".copier-answers.yml")["apps"]])


class AnswersValidationTests(LayeredTestCase):
    def refused(self, apps: list[dict], message: str, name: str = "refused") -> None:
        answers = write_answers(self.root / f"{name}.yml", {"project_name": "Refused", "apps": apps})
        destination = self.root / name
        code, _out, err = run_cli("new", "--template", template_url(self.repo), "--trust-template", "--answers", str(answers), "--dest", str(destination), "--yes")
        self.assertEqual(3, code, err)
        self.assertIn(message, err)
        self.assertFalse(destination.exists(), "nothing is generated when the app list is refused")

    def test_two_apps_at_one_path_are_refused(self) -> None:
        self.refused([BACKEND, {**API_TWO, "path": "backend"}], "app-path-conflict", "samepath")

    def test_a_path_that_belongs_to_the_workspace_is_refused(self) -> None:
        self.refused([{**BACKEND, "path": "docs/api"}], "belongs to the workspace", "docspath")

    def test_hyphen_colliding_ids_are_refused(self) -> None:
        self.refused([{"id": "my-app", "stack": "spring-backend"}, {"id": "myapp", "stack": "spring-backend", "path": "myapp"}], "would share the package segment `myapp`", "collide")

    def test_a_keyword_id_is_refused(self) -> None:
        self.refused([{"id": "package", "stack": "spring-backend"}], "package segment `package`", "keyword")

    def test_the_app_list_is_required(self) -> None:
        answers = write_answers(self.root / "noapps.yml", {"project_name": "No Apps"})
        code, _out, err = run_cli("new", "--template", template_url(self.repo), "--trust-template", "--answers", str(answers), "--dest", str(self.root / "noapps"), "--yes")
        self.assertEqual(3, code)
        self.assertIn("The app list is missing", err)

    def test_an_empty_app_list_generates_the_workspace_layer_alone(self) -> None:
        ws = self.generate("empty", [])
        self.assertFalse((ws / "docker-compose.yml").exists())
        self.assertFalse((ws / "backend").exists())
        self.assertEqual([], read_yaml(ws / ".copier-answers.yml")["apps"])
        self.assertIn("no app code yet", (ws / "AGENTS.md").read_text(encoding="utf-8"))
        self.assertEqual(0, run_cli("validate", str(ws))[0])

    def test_an_existing_non_empty_destination_is_refused_for_the_app_layer_too(self) -> None:
        """The workspace destination keeps its refusal, and an app's own path must be empty or absent."""

        ws = self.generate("occupied", [BACKEND])
        commit_workspace(ws)
        (ws / "services" / "api-two").mkdir(parents=True)
        (ws / "services" / "api-two" / "keep.txt").write_text("mine", encoding="utf-8")
        code, _out, err = run_cli("app", "add", "api-two", "--stack", "spring-backend", "--path", "services/api-two", "--scaffold", str(ws))
        self.assertEqual(3, code)
        self.assertIn("already holds files", err)
        self.assertEqual("mine", (ws / "services" / "api-two" / "keep.txt").read_text(encoding="utf-8"))
        code, _out, err = run_cli("new", "--template", template_url(self.repo), "--trust-template", "--preset", "backend-only", "--project-name", "X", "--dest", str(ws), "--yes")
        self.assertEqual(3, code)
        self.assertIn("already contains a generated Prism project", err)


class ScaffoldTests(LayeredTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.base = cls.root / "base"
        code, out, err = generate_workspace(cls.repo, cls.base, {"project_name": "Layered App", "apps": [BACKEND]}, cls.root)
        if code != 0:
            raise AssertionError(out + err)
        commit_workspace(cls.base)

    def copy(self, name: str) -> Path:
        destination = self.root / name
        shutil.copytree(self.base, destination)
        return destination

    def add(self, ws: Path, *extra: str) -> tuple[int, str, str]:
        return run_cli("app", "add", "api-two", "--stack", "spring-backend", "--path", "services/api-two", "--scaffold", *extra, str(ws))

    def test_a_preview_changes_nothing_and_names_the_plan(self) -> None:
        ws = self.copy("preview")
        code, out, err = self.add(ws)
        self.assertEqual(0, code, err)
        self.assertIn("Scaffolds `api-two` (spring-backend) at `services/api-two` on port 8081", out)
        self.assertIn("package `com.example.layeredapp.apitwo`", out)
        self.assertIn("at v1.0.0", out)
        self.assertIn("prism-scaffold-api-two", out)
        self.assertEqual("", git(ws, "status", "--porcelain").stdout)
        self.assertFalse((ws / "services").exists())

    def test_the_json_preview_carries_the_scaffold_plan(self) -> None:
        ws = self.copy("jsonpreview")
        code, out, err = self.add(ws, "--json")
        self.assertEqual(0, code, err)
        plan = json.loads(out)
        self.assertEqual("api-two", plan["app"]["id"])
        self.assertEqual("scaffolded", plan["app"]["generation"])
        self.assertEqual(8081, plan["scaffold"]["port"])
        self.assertEqual("v1.0.0", plan["scaffold"]["ref"])
        self.assertEqual("com.example.layeredapp.apitwo", plan["scaffold"]["package"])
        self.assertEqual([], plan["conflicts"])

    def test_applying_scaffolds_on_a_branch_with_one_commit_per_layer(self) -> None:
        ws = self.copy("applied")
        code, out, err = self.add(ws, "--apply", "--yes", "--trust-template")
        self.assertEqual(0, code, out + err)
        self.assertIn("Scaffolded app `api-two`", out)
        self.assertEqual("prism-scaffold-api-two", git(ws, "symbolic-ref", "--short", "HEAD").stdout.strip())
        subjects = git(ws, "log", "--format=%s", "main..HEAD").stdout.split("\n")
        self.assertEqual(["Scaffold api-two: app layer and manifest", "Scaffold api-two: workspace layer"], [item for item in subjects if item])
        self.assertEqual("", git(ws, "status", "--porcelain").stdout)
        self.assertEqual("main", git(ws, "rev-parse", "--abbrev-ref", "main").stdout.strip())

        answers = read_yaml(ws / "services" / "api-two" / ".copier-answers.yml")
        self.assertEqual((8081, "v1.0.0", "com.example.layeredapp.apitwo", "spring-backend"), (answers["port"], answers["_commit"], answers["app_package"], answers["prism_layer"]))
        manifest = read_yaml(ws / "prism.workspace.yml")
        model, diagnostics = normalize_manifest(manifest, path=Path("prism.workspace.yml"))
        self.assertEqual([], diagnostics)
        self.assertTrue(model.app("api-two").scaffolded)
        self.assertEqual("services/api-two", model.app("api-two").path)
        self.assertIn(".github/workflows/api-two.yml", manifest["expected_surfaces"]["workflows"])
        self.assertIn("api-two", manifest["app_maturity"])
        compose = yaml.safe_load((ws / "docker-compose.yml").read_text(encoding="utf-8"))
        self.assertEqual({"backend", "api-two", "db"}, set(compose["services"]))
        self.assertEqual({"backend", "api-two"}, set(yaml.safe_load((ws / "Taskfile.yml").read_text(encoding="utf-8"))["includes"]))
        self.assertEqual(["backend", "api-two"], [entry["id"] for entry in read_yaml(ws / ".copier-answers.yml")["apps"]])
        self.assertTrue((ws / ".github" / "workflows" / "api-two.yml").is_file())
        # The branch merges without conflict: the original branch is an ancestor.
        git(ws, "switch", "-q", "main")
        git(ws, "merge", "--ff-only", "-q", "prism-scaffold-api-two")

    def test_the_app_comes_from_the_recorded_tag_not_the_latest_one(self) -> None:
        ws = self.copy("recorded")
        tag_template_change(self.repo, "v2.0.0", (PACK_AGENTS, "append", "\nTemplate v2 note.\n"))
        self.addCleanup(lambda: git(self.repo, "tag", "-d", "v2.0.0"))
        code, out, err = self.add(ws, "--apply", "--yes", "--trust-template")
        self.assertEqual(0, code, out + err)
        agents = (ws / "services" / "api-two" / "AGENTS.md").read_text(encoding="utf-8")
        self.assertNotIn("Template v2 note.", agents)
        self.assertEqual("v1.0.0", read_yaml(ws / "services" / "api-two" / ".copier-answers.yml")["_commit"])
        self.assertEqual("v1.0.0", read_yaml(ws / ".copier-answers.yml")["_commit"])

    def test_a_web_app_scaffolds_on_the_first_free_web_port_with_its_pack(self) -> None:
        ws = self.copy("webapp")
        code, out, err = run_cli("app", "add", "web", "--stack", "nextjs-web", "--audience", "B2C", "--scaffold", "--apply", "--yes", "--trust-template", str(ws))
        self.assertEqual(0, code, out + err)
        answers = read_yaml(ws / "web" / ".copier-answers.yml")
        self.assertEqual((3000, "v1.0.0", "nextjs-web", "B2C"), (answers["port"], answers["_commit"], answers["prism_layer"], answers["audience"]))
        self.assertTrue((ws / "web" / "package-lock.json").is_file())
        self.assertTrue((ws / ".github" / "workflows" / "web.yml").is_file())
        self.assertEqual({"backend", "web"}, set(yaml.safe_load((ws / "Taskfile.yml").read_text(encoding="utf-8"))["includes"]))
        self.assertIn("web", read_yaml(ws / "prism.workspace.yml")["app_maturity"])
        subjects = git(ws, "log", "--format=%s", "main..HEAD").stdout.split("\n")
        self.assertEqual(["Scaffold web: app layer and manifest", "Scaffold web: workspace layer"], [item for item in subjects if item])

    def test_the_json_receipt_is_clean(self) -> None:
        ws = self.copy("jsonapplied")
        code, out, err = self.add(ws, "--apply", "--yes", "--trust-template", "--json")
        self.assertEqual(0, code, err)
        receipt = json.loads(out)
        self.assertEqual("applied", receipt["status"])
        self.assertEqual("prism-scaffold-api-two", receipt["branch"])
        self.assertEqual(2, len(receipt["commits"]))

    def test_a_dirty_tree_blocks_the_scaffold(self) -> None:
        ws = self.copy("dirty")
        (ws / "notes.txt").write_text("uncommitted", encoding="utf-8")
        code, _out, err = self.add(ws)
        self.assertEqual(3, code)
        self.assertIn("clean git working tree", err)

    def test_a_workspace_that_is_not_a_git_repository_blocks_the_scaffold(self) -> None:
        ws = self.copy("nogit")
        remove_tree(ws / ".git")
        code, _out, err = self.add(ws)
        self.assertEqual(3, code)
        self.assertIn("its own git repository", err)

    def test_a_custom_template_needs_explicit_trust_to_scaffold(self) -> None:
        ws = self.copy("untrusted")
        code, out, err = self.add(ws, "--apply", "--yes")
        self.assertEqual(3, code, out)
        self.assertIn("pass `--trust-template`", err)
        self.assertEqual("main", git(ws, "symbolic-ref", "--short", "HEAD").stdout.strip(), "no branch is created")

    def test_an_existing_branch_blocks_the_scaffold(self) -> None:
        ws = self.copy("branch")
        git(ws, "branch", "prism-scaffold-api-two")
        code, _out, err = self.add(ws, "--apply", "--yes", "--trust-template")
        self.assertEqual(3, code)
        self.assertIn("already exists", err)

    def test_a_stack_without_a_pack_is_registered_not_scaffolded(self) -> None:
        ws = self.copy("nopack")
        code, _out, err = run_cli("app", "add", "tool", "--stack", "other", "--has-ui", "false", "--serves-api", "false", "--scaffold", str(ws))
        self.assertEqual(3, code)
        self.assertIn("cannot be scaffolded", err)

    def test_scaffold_does_not_combine_with_an_external_repository(self) -> None:
        ws = self.copy("external")
        code, _out, err = run_cli(
            "app", "add", "api-two", "--stack", "spring-backend", "--scaffold", "--repository", "other", "--remote", "https://example.com/acme/other.git", str(ws)
        )
        self.assertEqual(3, code)
        self.assertIn("do not pass --repository or --remote", err)

    def test_a_colliding_identifier_is_refused_before_anything_is_generated(self) -> None:
        ws = self.copy("collision")
        code, _out, err = run_cli("app", "add", "back-end", "--stack", "spring-backend", "--path", "services/back-end", "--scaffold", str(ws))
        self.assertEqual(3, code)
        self.assertIn("would share the package segment `backend`", err)
        self.assertFalse((ws / "services").exists())

    def test_registering_without_scaffold_stays_a_manifest_edit(self) -> None:
        ws = self.copy("register")
        code, out, err = run_cli("app", "add", "api-two", "--stack", "spring-backend", "--path", "services/api-two", "--apply", "--yes", str(ws))
        self.assertEqual(0, code, err)
        self.assertFalse((ws / "services").exists())
        self.assertEqual("main", git(ws, "symbolic-ref", "--short", "HEAD").stdout.strip())
        entry = next(app for app in read_yaml(ws / "prism.workspace.yml")["apps"] if app["id"] == "api-two")
        self.assertNotIn("generation", entry, "a registered app records no generation; the default is registered")


class WebUpdateTests(LayeredTestCase):
    """`prism update` brings two web apps of one stack to a new tag, each from its own answers file."""

    WEB_AGENTS = "packs/nextjs-web/{{ app_path }}/AGENTS.md.jinja"
    WEB = {"id": "web", "stack": "nextjs-web", "name": "Web App", "audience": "B2C"}
    ADMIN = {"id": "admin", "stack": "nextjs-web", "name": "Admin App", "audience": "internal"}

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.workspace = cls.root / "base"
        code, out, err = generate_workspace(cls.repo, cls.workspace, {"project_name": "Layered App", "apps": [BACKEND, cls.WEB, cls.ADMIN]}, cls.root)
        if code != 0:
            raise AssertionError(out + err)
        commit_workspace(cls.workspace)
        cls.updated = cls.root / "updated"
        shutil.copytree(cls.workspace, cls.updated)
        tag_template_change(cls.repo, "v2.0.0", (cls.WEB_AGENTS, "append", "\nTemplate v2 note for {{ app_id }}.\n"), (WORKSPACE_DOCS, "append", "\nTemplate v2 workspace note.\n"))
        cls.result = run_cli("update", str(cls.updated), "--yes", "--trust-template")

    def test_each_web_app_is_updated_in_its_own_commit(self) -> None:
        code, out, err = self.result
        self.assertEqual(0, code, out + err)
        ws = self.updated
        self.assertEqual("prism-update-v2.0.0", git(ws, "symbolic-ref", "--short", "HEAD").stdout.strip())
        subjects = [item for item in git(ws, "log", "--format=%s", "main..HEAD").stdout.split("\n") if item]
        self.assertEqual(["Update app admin to v2.0.0", "Update app web to v2.0.0", "Update app backend to v2.0.0", "Update workspace layer to v2.0.0"], subjects)
        for app in ("web", "admin"):
            self.assertIn(f"app {app}: updated", out)
            self.assertIn(f"Template v2 note for {app}.", (ws / app / "AGENTS.md").read_text(encoding="utf-8"))
        self.assertNotIn("Template v2 note", (ws / "backend" / "AGENTS.md").read_text(encoding="utf-8"), "the web pack's change reaches only the web apps")

    def test_the_apps_keep_their_identity_port_and_dependencies(self) -> None:
        for app, port, audience in (("web", 3000, "B2C"), ("admin", 3001, "internal")):
            with self.subTest(app=app):
                answers = read_yaml(self.updated / app / ".copier-answers.yml")
                self.assertEqual(("v2.0.0", "nextjs-web", port, audience), (answers["_commit"], answers["prism_layer"], answers["port"], answers["audience"]))
                for relative in ("package.json", "package-lock.json", "lib/auth/session.ts", "lib/app-info.ts"):
                    self.assertEqual((self.workspace / app / relative).read_bytes(), (self.updated / app / relative).read_bytes(), relative)
        manifest = read_yaml(self.updated / "prism.workspace.yml")
        model, diagnostics = normalize_manifest(manifest, path=Path("prism.workspace.yml"))
        self.assertEqual([], diagnostics)
        self.assertEqual(["backend", "web", "admin"], model.active_app_ids)
        self.assertTrue(all(app.scaffolded for app in model.apps))


class UpdateTests(LayeredTestCase):
    """`prism update` across a tag, one commit per layer, and a conflict that stops it."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.workspace = cls.root / "base"
        code, out, err = generate_workspace(cls.repo, cls.workspace, {"project_name": "Layered App", "apps": [BACKEND, API_TWO]}, cls.root)
        if code != 0:
            raise AssertionError(out + err)
        commit_workspace(cls.workspace)
        cls.clean = cls.root / "clean"
        cls.conflicted = cls.root / "conflicted"
        shutil.copytree(cls.workspace, cls.clean)
        shutil.copytree(cls.workspace, cls.conflicted)
        # The user edits the first line of one app's guidance on the conflicted copy.
        agents = cls.conflicted / "services" / "api-two" / "AGENTS.md"
        lines = agents.read_text(encoding="utf-8").split("\n")
        lines[0] = "# api-two, edited by the user"
        agents.write_text("\n".join(lines), encoding="utf-8")
        git(cls.conflicted, "commit", "-qam", "User edit")
        # Version 2 changes a pack file and a workspace file without touching what the user changed.
        tag_template_change(cls.repo, "v2.0.0", (PACK_AGENTS, "append", "\nTemplate v2 note for {{ app_id }}.\n"), (WORKSPACE_DOCS, "append", "\nTemplate v2 workspace note.\n"))
        cls.clean_result = run_cli("update", str(cls.clean), "--yes", "--trust-template")
        # Version 3 changes the line the user edited.
        tag_template_change(cls.repo, "v3.0.0", (PACK_AGENTS, "first-line", "# {{ app_name }} changed by the template"))
        cls.conflict_result = run_cli("update", str(cls.conflicted), "--yes", "--trust-template")

    def test_a_clean_update_commits_each_layer_on_a_branch_and_leaves_it_for_review(self) -> None:
        code, out, err = self.clean_result
        self.assertEqual(0, code, out + err)
        ws = self.clean
        self.assertEqual("prism-update-v2.0.0", git(ws, "symbolic-ref", "--short", "HEAD").stdout.strip())
        subjects = [item for item in git(ws, "log", "--format=%s", "main..HEAD").stdout.split("\n") if item]
        self.assertEqual(["Update app api-two to v2.0.0", "Update app backend to v2.0.0", "Update workspace layer to v2.0.0"], subjects)
        self.assertEqual("", git(ws, "status", "--porcelain").stdout)
        self.assertEqual("main", git(ws, "rev-parse", "--abbrev-ref", "main").stdout.strip(), "the original branch is not touched")
        self.assertIn("one commit per layer", out)
        self.assertIn("workspace layer: updated", out)
        self.assertIn("app backend: updated", out)
        self.assertIn("app api-two: updated", out)

    def test_every_layer_reached_the_new_tag_with_its_own_answers_file(self) -> None:
        ws = self.clean
        for relative in (".copier-answers.yml", "backend/.copier-answers.yml", "services/api-two/.copier-answers.yml"):
            with self.subTest(answers=relative):
                self.assertEqual("v2.0.0", read_yaml(ws / relative)["_commit"])
        for relative in ("backend/AGENTS.md", "services/api-two/AGENTS.md"):
            self.assertIn("Template v2 note for", (ws / relative).read_text(encoding="utf-8"))
        self.assertIn("Template v2 workspace note.", (ws / "docs" / "README.md").read_text(encoding="utf-8"))
        # The apps keep the identity and port they were scaffolded with.
        second = read_yaml(ws / "services" / "api-two" / ".copier-answers.yml")
        self.assertEqual((8081, "com.example.layeredapp.apitwo"), (second["port"], second["app_package"]))
        self.assertEqual(["backend", "api-two"], [entry["id"] for entry in read_yaml(ws / ".copier-answers.yml")["apps"]])

    def test_the_manifest_merge_keeps_both_apps(self) -> None:
        manifest = read_yaml(self.clean / "prism.workspace.yml")
        model, diagnostics = normalize_manifest(manifest, path=Path("prism.workspace.yml"))
        self.assertEqual([], diagnostics)
        self.assertEqual(["backend", "api-two"], model.active_app_ids)
        self.assertTrue(all(app.scaffolded for app in model.apps))

    def test_a_conflict_in_one_app_is_reported_and_stops_the_merge(self) -> None:
        code, out, err = self.conflict_result
        self.assertEqual(cli.EXIT_UPDATE_CONFLICT, code, out + err)
        self.assertIn("app api-two: CONFLICT in 1 file(s)", out)
        self.assertIn("services/api-two/AGENTS.md", out)
        self.assertIn("app backend: updated", out)
        self.assertIn("workspace layer: updated", out)
        self.assertIn("Update stopped before merging: app `api-two` conflicted", err)
        ws = self.conflicted
        self.assertEqual("prism-update-v3.0.0", git(ws, "symbolic-ref", "--short", "HEAD").stdout.strip())
        text = (ws / "services" / "api-two" / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("<<<<<<< before updating", text)
        self.assertIn("# api-two, edited by the user", text)
        self.assertIn(">>>>>>> after updating", text)
        # The unconflicted layers are intact, and the original branch is where the user left it.
        self.assertNotIn("<<<<<<<", (ws / "backend" / "AGENTS.md").read_text(encoding="utf-8"))
        self.assertEqual("User edit", git(ws, "log", "-1", "--format=%s", "main").stdout.strip())
        subjects = [item for item in git(ws, "log", "--format=%s", "main..HEAD").stdout.split("\n") if item]
        self.assertEqual(3, len(subjects))
        message = git(ws, "log", "-1", "--format=%B").stdout
        self.assertIn("Unresolved conflicts in 1 file(s)", message)

    def test_an_update_refuses_a_scaffolded_app_whose_answers_file_is_missing(self) -> None:
        ws = self.root / "missing"
        shutil.copytree(self.workspace, ws)
        (ws / "services" / "api-two" / ".copier-answers.yml").unlink()
        git(ws, "commit", "-qam", "Remove the app's answers file")
        code, _out, err = run_cli("update", str(ws), "--yes", "--trust-template")
        self.assertEqual(3, code)
        self.assertIn("App `api-two` is scaffolded, but `services/api-two/.copier-answers.yml` is missing", err)
        self.assertIn("retire it (`prism app retire api-two`)", err, "the message names the way out")
        self.assertIn("drop its entry from prism.workspace.yml", err)
        self.assertEqual("main", git(ws, "symbolic-ref", "--short", "HEAD").stdout.strip(), "nothing changed")

    def test_the_clean_tree_precondition_stays(self) -> None:
        ws = self.root / "dirtyupdate"
        shutil.copytree(self.workspace, ws)
        (ws / "notes.txt").write_text("uncommitted", encoding="utf-8")
        code, _out, err = run_cli("update", str(ws), "--yes", "--trust-template")
        self.assertEqual(3, code)
        self.assertIn("clean git working tree", err)

    def test_a_retired_app_keeps_its_layer_out_of_the_update(self) -> None:
        ws = self.root / "retired"
        shutil.copytree(self.workspace, ws)
        code, _out, err = run_cli("app", "retire", "api-two", "--apply", "--yes", str(ws))
        self.assertEqual(0, code, err)
        git(ws, "commit", "-qam", "Retire api-two")
        layers, problems = cli.plan_update_layers(ws)
        self.assertEqual([], problems)
        self.assertEqual(["workspace", "backend"], [layer.name for layer in layers])


if __name__ == "__main__":
    unittest.main()
