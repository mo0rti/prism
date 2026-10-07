"""The `ios-swiftui` pack: its pins, its slice, and several iOS apps of one stack in one workspace.

The static tests read the pack's own files. The generated tests run the Prism CLI against a copy of the
working tree (real Copier) and read what each iOS app and the workspace layer contain. Building and
testing the generated apps (XcodeGen, `xcodebuild build`, `xcodebuild test`) needs macOS and Xcode: it is
the job of the pack's own workflow and of the `ios-build` job of `.github/workflows/template-validation.yml`.
"""

from __future__ import annotations

import plistlib
import re
import tempfile
import unittest
from pathlib import Path

import yaml
from jinja2 import Environment, StrictUndefined

from prism_cli.packs import PACK_STACKS, pack_answers
from tests import real_temp  # noqa: F401
from tests.layered_support import generate_default_apps

REPO_ROOT = Path(__file__).resolve().parents[1]
PACK = REPO_ROOT / "packs" / "ios-swiftui"
PACK_APP = PACK / "{{ app_path }}"
PARTNER_APP = {"id": "partner-ios", "name": "Partner App", "stack": "ios-swiftui", "repository": "workspace", "path": "apps/partner-ios", "audience": "internal", "generation": "scaffolded"}
RND_APP = {"id": "rnd-ios", "name": "R&D <Lab> App", "stack": "ios-swiftui", "repository": "workspace", "path": "apps/rnd", "audience": "A&B <staff>", "generation": "scaffolded"}


def pins() -> dict[str, str]:
    data = yaml.safe_load((REPO_ROOT / "packs" / "versions.yml").read_text(encoding="utf-8"))
    return {key: str(value) for key, value in data["ios-swiftui"].items()}


def render(relative: str, **context: object) -> str:
    template = Environment(undefined=StrictUndefined, keep_trailing_newline=True).from_string((PACK_APP / relative).read_text(encoding="utf-8"))
    return template.render(versions=pins(), **context)


def contract_paths() -> set[str]:
    text = (REPO_ROOT / "template" / "shared" / "api-contracts" / "openapi.yml.jinja").read_text(encoding="utf-8")
    return set(re.findall(r"^  (/\S+):\s*$", text, re.M))


def endpoint_paths(swift: str) -> list[str]:
    return re.findall(r'APIEndpoint\(\s*path:\s*"([^"]+)"', swift)


class PinsTests(unittest.TestCase):
    def test_the_stack_has_a_pack_and_pins(self) -> None:
        self.assertIn("ios-swiftui", PACK_STACKS)
        self.assertTrue(PACK.is_dir())
        self.assertEqual({"xcode", "swift", "ios_deployment_target"}, set(pins()))

    def test_project_yml_reads_every_pin_from_versions_yml(self) -> None:
        text = render("project.yml.jinja", app_module_name="Demo", app_package="com.example.demo.demo")
        data = yaml.safe_load(text)
        self.assertEqual(pins()["ios_deployment_target"], data["options"]["deploymentTarget"]["iOS"])
        self.assertEqual(pins()["xcode"], data["options"]["xcodeVersion"])
        self.assertEqual(pins()["swift"], data["settings"]["base"]["SWIFT_VERSION"])
        for value in pins().values():
            self.assertEqual(1, len(re.findall(r"(?<![0-9.])" + re.escape(value) + r"(?![0-9.])", text)), f"{value} is rendered once, from the pin")


class PackFilesTests(unittest.TestCase):
    def pack_files(self) -> list[Path]:
        return [path for path in sorted(PACK.rglob("*")) if path.is_file()]

    def swift_sources(self) -> list[Path]:
        return sorted((PACK_APP / "Sources").rglob("*.swift*"))

    def test_the_pack_follows_the_pack_conventions(self) -> None:
        relative = {path.relative_to(PACK).as_posix() for path in PACK.rglob("*") if path.is_file()}
        owned = {".github/workflows/{{ app_id }}.yml.jinja", ".cursor/rules/{{ app_id }}.mdc.jinja", "{{ _copier_conf.answers_file }}.jinja"}
        self.assertLessEqual(owned, relative)
        for path in relative:
            self.assertTrue(path.startswith("{{ app_path }}/") or path in owned, f"{path} must be under {{{{ app_path }}}}/")

    def test_the_slice_files_exist(self) -> None:
        for relative in (
            "project.yml.jinja",
            "Sources/App.swift.jinja",
            "Sources/Info.plist.jinja",
            "Sources/AppInfo.swift",
            "Sources/RootView.swift",
            "Sources/SignIn/SignInView.swift",
            "Sources/SignIn/SignInViewModel.swift",
            "Sources/Profile/ProfileView.swift",
            "Sources/Profile/ProfileViewModel.swift",
            "Sources/Networking/APIClient.swift",
            "Sources/Networking/APIEndpoint.swift",
            "Sources/Networking/APIError.swift",
            "Sources/Networking/APIURL.swift",
            "Sources/Session/TokenStore.swift",
            "Sources/Session/SessionModel.swift",
            "Sources/Models/Models.swift",
            "Tests/SignInViewModelTests.swift.jinja",
            "Tests/ProfileViewModelTests.swift.jinja",
            "Tests/APIClientTests.swift.jinja",
            "Tests/Support/FakeAPIClient.swift.jinja",
            "UITests/SignInUITests.swift",
            "Taskfile.yml.jinja",
            "scripts/select-simulator.sh",
            "AGENTS.md.jinja",
            "CLAUDE.md.jinja",
            "README.md.jinja",
            "docs/guide.md.jinja",
        ):
            with self.subTest(file=relative):
                self.assertTrue((PACK_APP / relative).is_file())

    def test_the_sign_in_is_the_local_development_sign_in_and_never_complete_authentication(self) -> None:
        view = (PACK_APP / "Sources" / "SignIn" / "SignInView.swift").read_text(encoding="utf-8")
        self.assertIn('Text("Local development sign-in")', view)
        self.assertIn("not complete authentication", view)
        model = (PACK_APP / "Sources" / "SignIn" / "SignInViewModel.swift").read_text(encoding="utf-8")
        self.assertIn("@MainActor", model)
        self.assertIn("@Observable", model)

    def test_the_client_calls_only_the_two_contract_operations(self) -> None:
        swift = (PACK_APP / "Sources" / "Networking" / "APIEndpoint.swift").read_text(encoding="utf-8")
        self.assertEqual(["/api/dev-identity/token", "/api/me"], endpoint_paths(swift))
        self.assertLessEqual(set(endpoint_paths(swift)), contract_paths())
        client = (PACK_APP / "Sources" / "Networking" / "APIClient.swift").read_text(encoding="utf-8")
        self.assertIn("func createDevToken(", client)
        self.assertIn("func getMe(", client)
        self.assertIn('"Bearer \\(token)"', client)

    def test_the_token_is_kept_in_memory_and_never_logged_or_persisted(self) -> None:
        for path in self.swift_sources():
            text = path.read_text(encoding="utf-8")
            with self.subTest(file=path.relative_to(PACK_APP).as_posix()):
                self.assertIsNone(re.search(r"\b(print|NSLog|os_log|debugPrint|dump|Logger)\(", text), "no logging call can print a token")
                for persisted in ("UserDefaults", "SecItem", "FileManager", "AppStorage", "SceneStorage"):
                    self.assertNotIn(persisted, text)
        store = (PACK_APP / "Sources" / "Session" / "TokenStore.swift").read_text(encoding="utf-8")
        self.assertIn("actor InMemoryTokenStore", store)

    def test_ui_tests_wait_until_an_element_is_hittable_and_allow_thirty_seconds(self) -> None:
        text = (PACK_APP / "UITests" / "SignInUITests.swift").read_text(encoding="utf-8")
        self.assertIn("TimeInterval = 30", text)
        self.assertIn("exists == true AND hittable == true", text)
        self.assertIn("waitForExistence(timeout: screenTimeout)", text)
        self.assertIn("Local development sign-in", text)

    def test_unit_tests_cover_both_view_models_with_a_fake_client(self) -> None:
        sign_in = (PACK_APP / "Tests" / "SignInViewModelTests.swift.jinja").read_text(encoding="utf-8")
        profile = (PACK_APP / "Tests" / "ProfileViewModelTests.swift.jinja").read_text(encoding="utf-8")
        for text in (sign_in, profile):
            self.assertIn("FakeAPIClient()", text)
            self.assertIn("@testable import {{ app_module_name }}", text)
            self.assertNotIn("URLSession", text, "the view model tests never reach the network")
        self.assertIn("SignInViewModel(", sign_in)
        self.assertIn("ProfileViewModel(", profile)
        self.assertEqual(7, len(re.findall(r"func test\w+\(", sign_in)))
        self.assertEqual(6, len(re.findall(r"func test\w+\(", profile)))

    def test_the_workflow_generates_builds_and_tests_on_macos_without_xcpretty(self) -> None:
        text = (PACK / ".github" / "workflows" / "{{ app_id }}.yml.jinja").read_text(encoding="utf-8")
        self.assertIn("runs-on: macos-latest", text)
        self.assertIn("xcodegen generate", text)
        self.assertIn("xcodebuild build", text)
        self.assertIn("xcodebuild test", text)
        self.assertNotIn("xcpretty", text)
        self.assertNotIn("secrets.", text)
        self.assertIn("grep -E '^ +iPhone '", text, "the simulator selection stays")

    def test_no_pack_file_carries_a_retired_sample_or_an_auth_answer(self) -> None:
        for path in self.pack_files():
            text = path.read_text(encoding="utf-8", errors="ignore")
            with self.subTest(file=path.relative_to(PACK).as_posix()):
                for retired in ("auth_methods", "SwiftData", "DependencyContainer", "xcconfig", "ios_module_name", "TokenStorage", "oauthCallback"):
                    self.assertNotIn(retired, text)

    def test_every_path_the_pack_guidance_cites_exists_in_the_pack(self) -> None:
        cited = re.compile(r"`((?:Sources|Tests|UITests|scripts)/[A-Za-z0-9_./-]+\.[A-Za-z.]+)`")
        documents = [
            PACK_APP / "AGENTS.md.jinja",
            PACK_APP / "README.md.jinja",
            PACK_APP / "docs" / "guide.md.jinja",
            REPO_ROOT / "template-skills" / "ios-conventions" / "skill.md",
            REPO_ROOT / "template-skills" / "ios-contract-alignment" / "skill.md",
            REPO_ROOT / "template-skills" / "ios-testing" / "skill.md",
            REPO_ROOT / "template-skills" / "swiftui-design-system" / "skill.md",
            REPO_ROOT / "template-skills" / "ios-conventions" / "references" / "swift6-observation-and-di.md",
        ]
        checked = 0
        for document in documents:
            for relative in sorted(set(cited.findall(document.read_text(encoding="utf-8")))):
                checked += 1
                with self.subTest(document=document.name, path=relative):
                    self.assertTrue((PACK_APP / relative).is_file() or (PACK_APP / f"{relative}.jinja").is_file(), relative)
        self.assertGreater(checked, 30)

    def test_the_old_ios_sample_and_its_helpers_are_gone(self) -> None:
        for path in (
            "template/mobile-ios",
            "template/.github/workflows/mobile-ios.yml.jinja",
            "template/.cursor/rules/mobile-ios.mdc.jinja",
            "template-skills/cursor-mobile-ios",
            "template/_templates",
            "template/.agents/skills/ios-conventions/references/swiftdata-patterns.md",
        ):
            self.assertFalse((REPO_ROOT / path).exists(), path)
        copier = (REPO_ROOT / "copier.yml").read_text(encoding="utf-8")
        for retired in ("mobile-ios/Config", "'mobile-ios' not in app_ids", "ios-view.swift", ".cursor/rules/mobile-ios.mdc"):
            self.assertNotIn(retired, copier)
        for path in ("template/.agents/skills/ios-conventions/references/navigation.md", "template/.agents/skills/ios-contract-alignment/references/token-refresh-patterns.md"):
            self.assertFalse((REPO_ROOT / path).exists(), path)

    def test_the_ios_skills_describe_the_slice(self) -> None:
        for name in ("ios-conventions", "ios-build-verify", "ios-contract-alignment", "ios-feature-delivery", "ios-testing", "swiftui-design-system"):
            text = (REPO_ROOT / "template-skills" / name / "skill.md").read_text(encoding="utf-8")
            with self.subTest(skill=name):
                self.assertIn("stacks: [ios-swiftui]", text)
                for retired in ("DependencyContainer", "TokenStorage", "AppRouter", "SwiftData", "xcconfig", "mobile-ios:", "Data/Repository", "UI/Theme"):
                    self.assertNotIn(retired, text)
        conventions = (REPO_ROOT / "template-skills" / "ios-conventions" / "skill.md").read_text(encoding="utf-8")
        self.assertIn("It works in the simulator only", conventions)
        self.assertIn("not complete authentication", conventions)

    def test_the_pack_answers_for_two_ios_apps_differ_only_in_their_own_identifiers(self) -> None:
        project = {"project_name": "Demo", "project_slug": "demo", "package_identifier": "com.example.demo"}
        one = pack_answers(project, {"id": "mobile-ios", "stack": "ios-swiftui", "path": "mobile-ios", "audience": "B2C"}, port=None)
        two = pack_answers(project, {"id": "partner-ios", "stack": "ios-swiftui", "path": "apps/partner-ios", "audience": "internal"}, port=None)
        differing = {key for key in one if one[key] != two[key]}
        self.assertEqual(
            {"app_id", "app_name", "app_path", "audience", "app_package_segment", "app_package", "app_package_path", "app_module_name", "ci_workflow_name", "ci_paths"},
            differing,
        )
        self.assertEqual(("MobileIos", "PartnerIos"), (one["app_module_name"], two["app_module_name"]))
        self.assertEqual(("com.example.demo.mobileios", "com.example.demo.partnerios"), (one["app_package"], two["app_package"]))


class GeneratedIosAppsTests(unittest.TestCase):
    """A workspace with a backend and three iOS apps of one stack: the default one, one nested and one whose text needs escaping."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory(prefix="prism-ios-pack-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.scratch = Path(cls.temporary.name)
        cls.root = cls.scratch / "generated"
        generate_default_apps(cls.root, ["backend", "mobile-ios"], cls.scratch, project_name="Layered Ios", extra_apps=[PARTNER_APP, RND_APP])
        cls.apps = {
            "mobile-ios": {"path": "mobile-ios", "module": "MobileIos", "name": "iOS (Swift/SwiftUI)", "audience": ""},
            "partner-ios": {"path": "apps/partner-ios", "module": "PartnerIos", "name": "Partner App", "audience": "internal"},
            "rnd-ios": {"path": "apps/rnd", "module": "RndIos", "name": "R&D <Lab> App", "audience": "A&B <staff>"},
        }

    def text(self, relative: str) -> str:
        return (self.root / relative).read_text(encoding="utf-8")

    def answers(self, app: str) -> dict:
        return yaml.safe_load(self.text(f"{self.apps[app]['path']}/.copier-answers.yml"))

    def test_each_app_is_its_own_layer_with_its_own_identity(self) -> None:
        identities: dict[str, set[str]] = {"module": set(), "bundle": set(), "workflow": set()}
        for app, info in self.apps.items():
            with self.subTest(app=app):
                answers = self.answers(app)
                self.assertEqual(("ios-swiftui", app, info["path"], 0, info["module"]), (answers["prism_layer"], answers["app_id"], answers["app_path"], answers["port"], answers["app_module_name"]))
                project = yaml.safe_load(self.text(f"{info['path']}/project.yml"))
                module = info["module"]
                self.assertEqual(module, project["name"], "the Xcode project is named after the module")
                self.assertEqual([module, f"{module}Tests", f"{module}UITests"], list(project["targets"]))
                bundle = project["targets"][module]["settings"]["base"]["PRODUCT_BUNDLE_IDENTIFIER"]
                self.assertEqual(f"com.example.layeredios.{app.replace('-', '')}", bundle)
                self.assertEqual(f"{bundle}.tests", project["targets"][f"{module}Tests"]["settings"]["base"]["PRODUCT_BUNDLE_IDENTIFIER"])
                self.assertEqual(f"{bundle}.uitests", project["targets"][f"{module}UITests"]["settings"]["base"]["PRODUCT_BUNDLE_IDENTIFIER"])
                self.assertEqual(module, project["targets"][f"{module}UITests"]["settings"]["base"]["TEST_TARGET_NAME"])
                self.assertEqual([f"{module}Tests", f"{module}UITests"], project["targets"][module]["scheme"]["testTargets"])
                identities["module"].add(module)
                identities["bundle"].add(bundle)
                identities["workflow"].add(f".github/workflows/{app}.yml")
                self.assertTrue((self.root / ".github" / "workflows" / f"{app}.yml").is_file())
                self.assertTrue((self.root / ".cursor" / "rules" / f"{app}.mdc").is_file())
        for kind, values in identities.items():
            self.assertEqual(3, len(values), f"distinct {kind} per app")

    def test_the_project_follows_the_pins_and_calls_the_local_backend_in_debug(self) -> None:
        for app, info in self.apps.items():
            with self.subTest(app=app):
                project = yaml.safe_load(self.text(f"{info['path']}/project.yml"))
                self.assertEqual(pins()["ios_deployment_target"], project["options"]["deploymentTarget"]["iOS"])
                self.assertEqual(pins()["swift"], project["settings"]["base"]["SWIFT_VERSION"])
                configs = project["targets"][info["module"]]["settings"]["configs"]
                self.assertEqual("http://localhost:8080", configs["Debug"]["API_BASE_URL"])
                self.assertEqual("", configs["Release"]["API_BASE_URL"], "a release build names its own backend")
                self.assertEqual("Sources/Info.plist", project["targets"][info["module"]]["settings"]["base"]["INFOPLIST_FILE"])

    def test_the_display_name_and_audience_are_plist_text_with_their_characters_escaped(self) -> None:
        for app, info in self.apps.items():
            with self.subTest(app=app):
                plist = plistlib.loads((self.root / info["path"] / "Sources" / "Info.plist").read_bytes())
                self.assertEqual(info["name"], plist["CFBundleDisplayName"])
                self.assertEqual(info["name"], plist["CFBundleName"])
                self.assertEqual(info["audience"], plist["PrismAppAudience"])
                self.assertEqual("$(API_BASE_URL)", plist["API_BASE_URL"])
                self.assertEqual({"NSAllowsLocalNetworking": True}, plist["NSAppTransportSecurity"], "plain HTTP to local networking only")
        # The names reach no Swift source: the app reads them from its Info.plist.
        for path in (self.root / "apps" / "rnd" / "Sources").rglob("*.swift"):
            self.assertNotIn("R&D", path.read_text(encoding="utf-8"), path.name)

    def test_each_app_has_its_own_app_type_and_tests_import_its_module(self) -> None:
        for app, info in self.apps.items():
            with self.subTest(app=app):
                module = info["module"]
                self.assertIn(f"struct {module}App: App", self.text(f"{info['path']}/Sources/App.swift"))
                for test in ("SignInViewModelTests", "ProfileViewModelTests", "APIClientTests", "Support/FakeAPIClient"):
                    self.assertIn(f"@testable import {module}\n", self.text(f"{info['path']}/Tests/{test}.swift"))
                taskfile = self.text(f"{info['path']}/Taskfile.yml")
                self.assertIn(f"-project {module}.xcodeproj -scheme {module} ", taskfile)
                fastfile = self.text(f"{info['path']}/fastlane/Fastfile")
                self.assertIn(f'project: "{module}.xcodeproj"', fastfile)
                self.assertIn(f'scheme: "{module}"', fastfile)

    def test_every_ios_app_runs_the_same_ci_steps_scoped_to_its_path(self) -> None:
        for app, info in self.apps.items():
            with self.subTest(app=app):
                data = yaml.safe_load(self.text(f".github/workflows/{app}.yml"))
                self.assertEqual(f"{info['name']} CI", data["name"])
                triggers = data.get("on", data.get(True))
                for event in ("push", "pull_request"):
                    self.assertEqual([f"{info['path']}/**", "shared/api-contracts/**", f".github/workflows/{app}.yml"], triggers[event]["paths"])
                job = data["jobs"]["verify"]
                self.assertEqual("macos-latest", job["runs-on"])
                self.assertEqual(info["path"], job["defaults"]["run"]["working-directory"])
                steps = [step["name"] for step in job["steps"] if "name" in step]
                self.assertEqual(["Install XcodeGen", "Generate Xcode project", "Select iPhone simulator", "Build", "Test", "Upload test results"], steps)
                text = self.text(f".github/workflows/{app}.yml")
                module = info["module"]
                self.assertIn("run: xcodegen generate", text)
                self.assertEqual(2, text.count(f'-project "{module}.xcodeproj"'), "the build and the test name the project of this app")
                self.assertEqual(2, text.count(f'-scheme "{module}"'))
                for forbidden in ("xcpretty", "secrets.", "environment:", "fastlane"):
                    self.assertNotIn(forbidden, text)

    def test_the_client_of_every_app_calls_only_paths_the_rendered_contract_defines(self) -> None:
        rendered = yaml.safe_load(self.text("shared/api-contracts/openapi.yml"))
        for app, info in self.apps.items():
            with self.subTest(app=app):
                paths = endpoint_paths(self.text(f"{info['path']}/Sources/Networking/APIEndpoint.swift"))
                self.assertEqual(["/api/dev-identity/token", "/api/me"], paths)
                self.assertLessEqual(set(paths), set(rendered["paths"]))
        token = rendered["paths"]["/api/dev-identity/token"]["post"]
        self.assertEqual("createDevToken", token["operationId"])
        self.assertEqual([], token["security"])
        me = rendered["paths"]["/api/me"]["get"]
        self.assertEqual("getMe", me["operationId"])
        self.assertEqual([{"bearerAuth": []}], me.get("security", rendered["security"]))

    def test_no_pack_file_is_left_with_jinja_or_placeholders(self) -> None:
        for app, info in self.apps.items():
            for path in sorted((self.root / info["path"]).rglob("*")):
                if not path.is_file():
                    continue
                text = path.read_text(encoding="utf-8", errors="ignore")
                with self.subTest(app=app, file=path.relative_to(self.root).as_posix()):
                    self.assertNotIn("{%", text)
                    self.assertNotIn("{#", text)
                    for placeholder in ("{{ app_", "{{ project_", "{{ versions", "{{ audience", "{{ package_"):
                        self.assertNotIn(placeholder, text)
                    if path.name != "Taskfile.yml":
                        self.assertNotIn("{{", text)

    def test_the_workspace_layer_wires_every_ios_app(self) -> None:
        taskfile = yaml.safe_load(self.text("Taskfile.yml"))
        for app, info in self.apps.items():
            with self.subTest(app=app):
                self.assertEqual({"taskfile": f"./{info['path']}/Taskfile.yml", "dir": f"./{info['path']}"}, taskfile["includes"][app])
                self.assertIn(f"{info['path']}/ -> Swift", self.text("AGENTS.md"))
                self.assertIn(f"`task {app}:build`", self.text("AGENTS.md"))
                self.assertIn(f"`task {app}:test`", self.text("AGENTS.md"))
                self.assertIn(f"({info['path']}/docs/guide.md)", self.text("README.md"))
                self.assertIn(f"`{app}.yml`", self.text("docs/deployment/ci-cd.md"))
                self.assertIn(f"`{info['path']}/AGENTS.md`", self.text("AGENTS.md"))
        # The iOS client is hand-written, so no step generates one, and iOS builds run on a Mac, outside the root `task test`.
        self.assertNotIn("generate-client-mobile-ios", self.text("Taskfile.yml"))
        self.assertNotIn("swift6", self.text("Taskfile.yml"))
        for task in ("lint", "test"):
            for command in taskfile["tasks"][task]["cmds"]:
                self.assertNotIn("ios", str(command))
        self.assertNotIn("xcodeproj", self.text(".gitignore"))
        self.assertNotIn("Config/Debug.xcconfig", self.text(".gitignore"))
        for info in self.apps.values():
            ignored = self.text(f"{info['path']}/.gitignore").splitlines()
            for entry in ("*.xcodeproj/", "build/", "DerivedData/"):
                self.assertIn(entry, ignored)

    def test_the_manifest_records_each_ios_app_as_scaffolded_and_experimental(self) -> None:
        manifest = yaml.safe_load(self.text("prism.workspace.yml"))
        apps = {app["id"]: app for app in manifest["apps"]}
        for app, info in self.apps.items():
            self.assertEqual(("ios-swiftui", info["path"], "scaffolded"), (apps[app]["stack"], apps[app]["path"], apps[app]["generation"]))
            self.assertEqual("experimental", manifest["app_maturity"][app]["level"])
            self.assertIn(f".github/workflows/{app}.yml", manifest["expected_surfaces"]["workflows"])
        self.assertEqual("internal", apps["partner-ios"]["audience"])

    def test_the_agent_guidance_of_every_ios_app_states_the_dev_identity_limits(self) -> None:
        for app, info in self.apps.items():
            with self.subTest(app=app):
                agents = self.text(f"{info['path']}/AGENTS.md")
                self.assertIn("The dev identity is not authentication, and it works in the simulator only", agents)
                self.assertIn("`local` profile", agents)
                self.assertIn("physical device", agents)
                self.assertIn("loopback", agents)
                self.assertEqual("@AGENTS.md", self.text(f"{info['path']}/CLAUDE.md").splitlines()[0])
                rule = self.text(f".cursor/rules/{app}.mdc")
                self.assertIn(f'globs: "{info["path"]}/**"', rule)
                self.assertIn("not complete authentication", rule)
                self.assertIn("simulator", rule)
                readme = self.text(f"{info['path']}/README.md")
                self.assertIn("Local development sign-in", readme)
                self.assertIn("It works in the simulator only", readme)

    def test_a_nested_app_reaches_the_docs_from_its_own_depth(self) -> None:
        guide = self.text("apps/partner-ios/docs/guide.md")
        self.assertIn("(../../../docs/architecture.md)", guide)
        self.assertIn("(../../docs/architecture.md)", self.text("mobile-ios/docs/guide.md"))
        self.assertTrue((self.root / "shared" / "api-contracts" / "openapi.yml").is_file())

    def test_the_ios_skills_are_generated_for_the_workspace(self) -> None:
        for layer in (".agents/skills", ".claude/skills"):
            for name in ("ios-conventions", "ios-build-verify", "ios-contract-alignment", "ios-feature-delivery", "ios-testing", "swiftui-design-system"):
                self.assertTrue((self.root / layer / name / "SKILL.md").is_file(), f"{layer}/{name}")
            conventions = self.text(f"{layer}/ios-conventions/SKILL.md")
            for app in self.apps.values():
                self.assertIn(f"`{app['path']}/`", conventions)
            self.assertFalse((self.root / layer / "ios-conventions" / "references" / "navigation.md").exists())
        build = self.text(".claude/skills/ios-build-verify/SKILL.md")
        self.assertIn("task <app-id>:build", build)
        self.assertIn("`partner-ios` (`apps/partner-ios/`)", build)
        self.assertNotIn("{%", build)
        generate = self.text(".claude/commands/generate-clients.md")
        for app in self.apps:
            self.assertIn(f"`task {app}:build` (Mac only)", generate)
        self.assertNotIn("Generated/", generate)
        store = self.text(".agents/skills/deployment/references/mobile-store-release.md")
        self.assertIn("## iOS: TestFlight", store)
        self.assertNotIn("xcconfig", store)


if __name__ == "__main__":
    unittest.main()
