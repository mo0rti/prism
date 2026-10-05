"""The application model: stack registry, manifest normalizer and local repository checkouts."""

from __future__ import annotations

import copy
import os
from pathlib import Path
import tempfile
import unittest

import yaml

from prism_cli import app_model
from prism_cli.app_model import (
    ALL_PLATFORM_CHOICES,
    GENERATED_PLATFORM_DIRS,
    GENERATED_PLATFORM_STACKS,
    STACKS,
    App,
    apps_from_platforms,
    normalize_manifest,
    resolve_local_repositories,
)
from prism_cli.wiki_model import UI_PLATFORM_IDS, VALID_PLATFORM_IDS
from prism_cli.workspace import PLATFORM_DIRS
from tests import real_temp  # noqa: F401


MANIFEST_PATH = Path("prism.workspace.yml")


def v2_manifest(**overrides: object) -> dict:
    """A valid version-2 manifest with one app of every default stack kind, then the overrides."""

    manifest: dict = {
        "schema_version": 2,
        "project": {"name": "Two apps"},
        "repositories": [
            {"id": "workspace"},
            {"id": "mobile-apps", "remote": "https://example.com/acme/mobile-apps.git"},
        ],
        "apps": [
            {"id": "customer-android", "name": "Customer app", "stack": "android-compose", "repository": "workspace", "path": "mobile-android", "audience": "B2C"},
            {"id": "partner-android", "name": "Partner app", "stack": "android-compose", "repository": "mobile-apps", "path": "apps/partner", "audience": "B2B"},
            {"id": "backend", "name": "API", "stack": "spring-backend"},
        ],
        "app_maturity": {"customer-android": {"level": "provisional", "caveat": "Beta."}},
    }
    manifest.update(overrides)
    return manifest


def codes(diagnostics: list) -> list[str]:
    return [item.code for item in diagnostics]


def normalized(data: dict) -> tuple[app_model.WorkspaceModel, list]:
    return normalize_manifest(copy.deepcopy(data), path=MANIFEST_PATH)


class StackRegistryTests(unittest.TestCase):
    def test_registry_matches_the_contract(self) -> None:
        expected = {
            "spring-backend": (True, {"has-ui": False, "serves-api": True}, "backend"),
            "nextjs-web": (True, {"has-ui": True, "serves-api": False}, None),
            "android-compose": (True, {"has-ui": True, "serves-api": False}, "mobile-android"),
            "ios-swiftui": (True, {"has-ui": True, "serves-api": False}, "mobile-ios"),
            "other": (False, {}, None),
        }
        self.assertEqual(list(expected), list(STACKS))
        for stack_id, (generated, capabilities, default_path) in expected.items():
            with self.subTest(stack=stack_id):
                stack = STACKS[stack_id]
                self.assertEqual(generated, stack.generated)
                self.assertEqual(capabilities, dict(stack.default_capabilities))
                self.assertEqual(default_path, stack.default_path)

    def test_derived_constants_keep_their_names_values_and_order(self) -> None:
        self.assertEqual(
            {
                "backend": "backend",
                "mobile-android": "mobile-android",
                "mobile-ios": "mobile-ios",
                "web-user-app": "web-user-app",
                "web-admin-portal": "web-admin-portal",
            },
            PLATFORM_DIRS,
        )
        self.assertEqual(["backend", "mobile-android", "mobile-ios", "web-user-app", "web-admin-portal"], list(PLATFORM_DIRS))
        self.assertEqual({"backend", "mobile-android", "mobile-ios", "web-user-app", "web-admin-portal"}, VALID_PLATFORM_IDS)
        self.assertEqual({"mobile-android", "mobile-ios", "web-user-app", "web-admin-portal"}, UI_PLATFORM_IDS)
        self.assertEqual(
            (
                ("backend", "Spring Boot Backend"),
                ("web-user-app", "User-Facing Web App"),
                ("web-admin-portal", "Admin Web Portal"),
                ("mobile-android", "Android (Kotlin/Compose)"),
                ("mobile-ios", "iOS (Swift/SwiftUI)"),
            ),
            ALL_PLATFORM_CHOICES,
        )

    def test_labels_have_one_source(self) -> None:
        from prism_cli import cli, presets

        self.assertIs(app_model.ALL_PLATFORM_CHOICES, cli.ALL_PLATFORM_CHOICES)
        self.assertFalse(hasattr(presets, "ALL_PLATFORM_CHOICES"))

    def test_ui_platforms_come_from_the_has_ui_capability(self) -> None:
        for platform_id, stack_id in GENERATED_PLATFORM_STACKS.items():
            with self.subTest(platform=platform_id):
                self.assertEqual(STACKS[stack_id].default_capabilities["has-ui"], platform_id in UI_PLATFORM_IDS)


class GeneratedPlatformTests(unittest.TestCase):
    def test_each_generated_platform_becomes_an_app_of_its_stack(self) -> None:
        expected = {
            "backend": ("Spring Boot Backend", "spring-backend", "backend"),
            "web-user-app": ("User-Facing Web App", "nextjs-web", "web-user-app"),
            "web-admin-portal": ("Admin Web Portal", "nextjs-web", "web-admin-portal"),
            "mobile-android": ("Android (Kotlin/Compose)", "android-compose", "mobile-android"),
            "mobile-ios": ("iOS (Swift/SwiftUI)", "ios-swiftui", "mobile-ios"),
        }
        for platform_id, (label, stack, path) in expected.items():
            with self.subTest(platform=platform_id):
                entries = apps_from_platforms([platform_id])
                self.assertEqual([{"id": platform_id, "name": label, "stack": stack, "repository": "workspace", "path": path}], entries)
                self.assertEqual(GENERATED_PLATFORM_DIRS[platform_id], path)
                model, diagnostics = normalized(v2_manifest(apps=entries, app_maturity={}))
                self.assertEqual([], diagnostics)
                self.assertEqual([platform_id], model.active_app_ids)

    def test_the_order_given_is_kept_and_unknown_ids_are_refused(self) -> None:
        self.assertEqual(["mobile-ios", "backend"], [item["id"] for item in apps_from_platforms(["mobile-ios", "backend"])])
        self.assertEqual([], apps_from_platforms([]))
        with self.assertRaisesRegex(ValueError, "bogus"):
            apps_from_platforms(["backend", "bogus"])


class SchemaVersionTests(unittest.TestCase):
    def test_version_one_is_the_unsupported_version_error(self) -> None:
        model, diagnostics = normalized({"schema_version": 1, "project": {"name": "Old", "platforms": ["backend"]}})
        self.assertEqual((), model.apps)
        self.assertEqual(["unsupported-workspace-manifest-schema"], codes(diagnostics))
        self.assertEqual("error", diagnostics[0].severity)
        self.assertIn("supports only 2", diagnostics[0].message)
        self.assertIn("Recreate or reinstall", diagnostics[0].message)

    def test_every_other_version_is_the_unsupported_version_error(self) -> None:
        for version in (0, -1, 3, 99):
            with self.subTest(version=version):
                model, diagnostics = normalized({"schema_version": version, "apps": [{"id": "backend", "stack": "spring-backend"}]})
                self.assertEqual((), model.apps)
                self.assertEqual(["unsupported-workspace-manifest-schema"], codes(diagnostics))
        for version in (True, 2.0, "2", None):
            with self.subTest(version=version):
                _, diagnostics = normalized({"schema_version": version})
                self.assertEqual(["invalid-workspace-manifest-schema"], codes(diagnostics))

    def test_the_normalizer_does_not_change_its_input(self) -> None:
        data = v2_manifest()
        before = copy.deepcopy(data)
        normalize_manifest(data, path=MANIFEST_PATH)
        self.assertEqual(before, data)


class VersionTwoModelTests(unittest.TestCase):
    def test_valid_manifest_loads_apps_in_order_with_their_fields(self) -> None:
        model, diagnostics = normalized(v2_manifest())
        self.assertEqual([], diagnostics)
        self.assertEqual(2, model.schema_version)
        self.assertEqual(["customer-android", "partner-android", "backend"], model.active_app_ids)
        self.assertEqual(
            [app_model.Repository("workspace"), app_model.Repository("mobile-apps", "https://example.com/acme/mobile-apps.git")],
            list(model.repositories),
        )
        customer, partner, backend = model.apps
        self.assertEqual(("Customer app", "android-compose", "workspace", "mobile-android", "B2C", "active"), (customer.name, customer.stack, customer.repository, customer.path, customer.audience, customer.status))
        self.assertEqual(("Partner app", "mobile-apps", "apps/partner", "B2B"), (partner.name, partner.repository, partner.path, partner.audience))
        self.assertEqual("backend", backend.path)
        self.assertTrue(customer.in_workspace)
        self.assertFalse(partner.in_workspace)
        self.assertEqual((app_model.Repository("mobile-apps", "https://example.com/acme/mobile-apps.git"),), model.external_repositories)
        self.assertEqual(("customer-android", "backend"), tuple(app.id for app in model.workspace_apps()))

    def test_app_maturity_is_keyed_by_app_id(self) -> None:
        model, _ = normalized(v2_manifest(app_maturity={"customer-android": {"level": "provisional"}, "partner-android": {"level": "baseline"}}))
        self.assertEqual({"customer-android": {"level": "provisional"}, "partner-android": {"level": "baseline"}}, {key: dict(value) for key, value in model.app_maturity.items()})

    def test_name_and_path_defaults(self) -> None:
        manifest = v2_manifest(apps=[{"id": "api", "stack": "spring-backend"}, {"id": "site", "stack": "nextjs-web", "path": "sites/main"}], app_maturity={})
        model, diagnostics = normalized(manifest)
        self.assertEqual([], diagnostics)
        self.assertEqual(("api", "backend"), (model.apps[0].name, model.apps[0].path))
        self.assertEqual("sites/main", model.apps[1].path)

    def test_zero_apps_is_valid(self) -> None:
        for manifest in (v2_manifest(apps=[], app_maturity={}), {"schema_version": 2, "project": {"name": "Knowledge only"}}):
            with self.subTest(manifest=sorted(manifest)):
                model, diagnostics = normalized(manifest)
                self.assertEqual([], diagnostics)
                self.assertEqual([], model.active_app_ids)

    def test_retired_apps_are_not_active(self) -> None:
        manifest = v2_manifest()
        manifest["apps"][1]["status"] = "retired"
        model, diagnostics = normalized(manifest)
        self.assertEqual([], diagnostics)
        self.assertEqual(["customer-android", "backend"], model.active_app_ids)
        self.assertEqual(3, len(model.apps))
        self.assertFalse(model.app("partner-android").active)

    def assert_error(self, code: str, manifest: dict, *, only: bool = True) -> None:
        _, diagnostics = normalized(manifest)
        self.assertIn(code, codes(diagnostics))
        if only:
            self.assertEqual([code], codes(diagnostics), [item.message for item in diagnostics])
        self.assertTrue(all(item.severity == "error" and item.path == str(MANIFEST_PATH) and item.message for item in diagnostics))

    def test_project_platforms_conflict_with_apps(self) -> None:
        manifest = v2_manifest()
        manifest["project"]["platforms"] = ["backend"]
        self.assert_error("conflicting-app-declarations", manifest)
        manifest["project"]["platforms"] = []
        self.assert_error("conflicting-app-declarations", manifest)

    def test_invalid_and_duplicate_app_ids(self) -> None:
        for bad in ("Customer", "customer_android", "1app", "-a", "a--b", "a-", "", None, 5, ["x"]):
            with self.subTest(app_id=bad):
                manifest = v2_manifest()
                manifest["apps"][0]["id"] = bad
                self.assert_error("invalid-app-id", manifest, only=False)
        manifest = v2_manifest()
        manifest["apps"][1]["id"] = "customer-android"
        manifest["apps"][1]["path"] = "elsewhere"
        self.assert_error("duplicate-app-id", manifest, only=False)

    def test_legacy_ids_are_valid_app_ids(self) -> None:
        manifest = v2_manifest(
            repositories=[],
            apps=[
                {"id": "backend", "stack": "spring-backend"},
                {"id": "web-user-app", "stack": "nextjs-web", "path": "web-user-app"},
                {"id": "web-admin-portal", "stack": "nextjs-web", "path": "web-admin-portal"},
                {"id": "mobile-android", "stack": "android-compose"},
                {"id": "mobile-ios", "stack": "ios-swiftui"},
            ],
            app_maturity={},
        )
        model, diagnostics = normalized(manifest)
        self.assertEqual([], diagnostics)
        self.assertEqual(["backend", "web-user-app", "web-admin-portal", "mobile-android", "mobile-ios"], model.active_app_ids)

    def test_unknown_app_stack(self) -> None:
        for stack in ("android", "Android-Compose", "", None, 7):
            with self.subTest(stack=stack):
                manifest = v2_manifest()
                manifest["apps"][0]["stack"] = stack
                self.assert_error("unknown-app-stack", manifest)
        manifest = v2_manifest()
        del manifest["apps"][0]["stack"]
        self.assert_error("unknown-app-stack", manifest)

    def test_unknown_app_repository(self) -> None:
        for repository in ("nowhere", "", None, 3):
            with self.subTest(repository=repository):
                manifest = v2_manifest()
                manifest["apps"][1]["repository"] = repository
                self.assert_error("unknown-app-repository", manifest)

    def test_invalid_app_path(self) -> None:
        for bad in ("/abs/path", "../up", "a/../b", "a\\b", "C:\\work\\app", "C:/work/app", "c:app", "", "  ", "a//b", "a/./b", ".", 4, ["a"], "x\x00y"):
            with self.subTest(path=bad):
                manifest = v2_manifest()
                manifest["apps"][0]["path"] = bad
                self.assert_error("invalid-app-path", manifest)

    def test_a_path_is_required_when_the_stack_has_no_default(self) -> None:
        manifest = v2_manifest(apps=[{"id": "site", "stack": "nextjs-web"}], app_maturity={})
        self.assert_error("invalid-app-path", manifest)

    def test_the_repository_root_is_a_valid_path_only_outside_the_workspace(self) -> None:
        manifest = v2_manifest(apps=[{"id": "partner-android", "stack": "android-compose", "repository": "mobile-apps", "path": "."}], app_maturity={})
        model, diagnostics = normalized(manifest)
        self.assertEqual([], diagnostics)
        self.assertEqual(".", model.apps[0].path)
        manifest["apps"][0]["repository"] = "workspace"
        self.assert_error("invalid-app-path", manifest)

    def test_trailing_slash_is_normalized(self) -> None:
        manifest = v2_manifest()
        manifest["apps"][1]["path"] = "apps/partner/"
        model, diagnostics = normalized(manifest)
        self.assertEqual([], diagnostics)
        self.assertEqual("apps/partner", model.app("partner-android").path)

    def test_app_path_conflicts_within_one_repository(self) -> None:
        cases = {
            "duplicate": ("apps/partner", "apps/partner"),
            "duplicate differing in case": ("apps/Partner", "apps/partner"),
            "nested": ("apps", "apps/partner"),
            "nested the other way": ("apps/partner", "apps"),
            "root with another app": (".", "apps/partner"),
        }
        for label, (first, second) in cases.items():
            with self.subTest(case=label):
                manifest = v2_manifest(
                    apps=[
                        {"id": "one", "stack": "android-compose", "repository": "mobile-apps", "path": first},
                        {"id": "two", "stack": "ios-swiftui", "repository": "mobile-apps", "path": second},
                    ],
                    app_maturity={},
                )
                self.assert_error("app-path-conflict", manifest)

    def test_the_same_path_in_different_repositories_is_not_a_conflict(self) -> None:
        manifest = v2_manifest(
            repositories=[{"id": "one", "remote": "https://example.com/a/one.git"}, {"id": "two", "remote": "https://example.com/a/two.git"}],
            apps=[
                {"id": "app-a", "stack": "android-compose", "repository": "one", "path": "app"},
                {"id": "app-b", "stack": "android-compose", "repository": "two", "path": "app"},
                {"id": "app-c", "stack": "android-compose", "repository": "workspace", "path": "app"},
            ],
            app_maturity={},
        )
        self.assertEqual([], normalized(manifest)[1])

    def test_sibling_paths_with_a_shared_prefix_do_not_overlap(self) -> None:
        manifest = v2_manifest(
            apps=[
                {"id": "one", "stack": "android-compose", "path": "app"},
                {"id": "two", "stack": "ios-swiftui", "path": "app-ios"},
            ],
            app_maturity={},
        )
        self.assertEqual([], normalized(manifest)[1])

    def test_invalid_repository(self) -> None:
        for bad in (["workspace", "x"], [5], [{"remote": "https://example.com/a/b.git"}], [{"id": "Bad_Id", "remote": "https://example.com/a/b.git"}], [{"id": None}]):
            with self.subTest(repositories=bad):
                self.assert_error("invalid-repository", v2_manifest(repositories=bad, apps=[], app_maturity={}), only=False)
        self.assert_error("invalid-repository", v2_manifest(repositories="workspace", apps=[], app_maturity={}))

    def test_duplicate_repository_id(self) -> None:
        remote = "https://example.com/a/b.git"
        manifest = v2_manifest(repositories=[{"id": "mobile-apps", "remote": remote}, {"id": "mobile-apps", "remote": remote}], apps=[], app_maturity={})
        self.assert_error("duplicate-repository-id", manifest)
        self.assert_error("duplicate-repository-id", v2_manifest(repositories=[{"id": "workspace"}, {"id": "workspace"}], apps=[], app_maturity={}))

    def test_repository_remote_is_required_except_for_the_workspace(self) -> None:
        self.assert_error("repository-remote-required", v2_manifest(repositories=[{"id": "mobile-apps"}], apps=[], app_maturity={}))
        self.assert_error("repository-remote-required", v2_manifest(repositories=[{"id": "mobile-apps", "remote": None}], apps=[], app_maturity={}))
        model, diagnostics = normalized(v2_manifest(repositories=[{"id": "workspace"}], apps=[], app_maturity={}))
        self.assertEqual([], diagnostics)
        self.assertIsNone(model.repository("workspace").remote)

    def test_invalid_repository_remote(self) -> None:
        for bad in (
            "../mobile-apps",
            "/srv/git/mobile-apps.git",
            "C:\\repos\\mobile-apps",
            "C:/repos/mobile-apps",
            "file:///srv/git/mobile-apps.git",
            "FILE:///srv/git/mobile-apps.git",
            "http://example.com/a/b.git",
            "https://",
            "https://user:token@example.com/a/b.git",
            "git@example.com:/abs/path.git",
            "git@example.com",
            "mobile-apps",
            "https://example.com/a b.git",
            " https://example.com/a/b.git",
            "",
            12,
            ["https://example.com/a/b.git"],
        ):
            with self.subTest(remote=bad):
                self.assert_error("invalid-repository-remote", v2_manifest(repositories=[{"id": "mobile-apps", "remote": bad}], apps=[], app_maturity={}))

    def test_canonical_remote_forms_are_accepted(self) -> None:
        for good in (
            "https://example.com/acme/mobile-apps.git",
            "https://example.com/acme/mobile-apps",
            "HTTPS://example.com/acme/mobile-apps.git",
            "ssh://git@example.com/acme/mobile-apps.git",
            "ssh://example.com:2222/acme/mobile-apps.git",
            "git@example.com:acme/mobile-apps.git",
            "git@git.example.co.uk:acme/team/mobile-apps.git",
            "https://user@example.com/acme/mobile-apps.git",
        ):
            with self.subTest(remote=good):
                _, diagnostics = normalized(v2_manifest(repositories=[{"id": "mobile-apps", "remote": good}], apps=[], app_maturity={}))
                self.assertEqual([], diagnostics)

    def test_an_other_app_must_declare_both_capabilities(self) -> None:
        base = {"id": "legacy-tool", "stack": "other", "path": "tools/legacy"}
        manifest = v2_manifest(apps=[dict(base)], app_maturity={})
        _, diagnostics = normalized(manifest)
        self.assertEqual(["undeclared-app-capability", "undeclared-app-capability"], codes(diagnostics))
        manifest = v2_manifest(apps=[{**base, "capabilities": {"has-ui": False}}], app_maturity={})
        _, diagnostics = normalized(manifest)
        self.assertEqual(["undeclared-app-capability"], codes(diagnostics))
        self.assertIn("serves-api", diagnostics[0].message)
        for declared in ({"has-ui": True, "serves-api": False}, {"has-ui": "unknown", "serves-api": "unknown"}):
            with self.subTest(declared=declared):
                _, diagnostics = normalized(v2_manifest(apps=[{**base, "capabilities": declared}], app_maturity={}))
                self.assertEqual([], diagnostics)

    def test_invalid_app_capability(self) -> None:
        for bad in ({"has-ui": "yes"}, {"has-ui": 1}, {"has-ui": None}, {"serves-api": "maybe"}, {"is-fast": True}, {1: True}, "has-ui", ["has-ui"]):
            with self.subTest(capabilities=bad):
                manifest = v2_manifest()
                manifest["apps"][0]["capabilities"] = bad
                self.assert_error("invalid-app-capability", manifest)

    def test_invalid_app_status(self) -> None:
        for bad in ("paused", "Active", "", None, True):
            with self.subTest(status=bad):
                manifest = v2_manifest()
                manifest["apps"][0]["status"] = bad
                self.assert_error("invalid-app-status", manifest)

    def test_invalid_app_maturity(self) -> None:
        self.assert_error("invalid-app-maturity", v2_manifest(app_maturity={"ghost": {"level": "baseline"}}))
        self.assert_error("invalid-app-maturity", v2_manifest(app_maturity={"mobile-android": {"level": "baseline"}}))
        self.assert_error("invalid-app-maturity", v2_manifest(app_maturity={"customer-android": "baseline"}))
        self.assert_error("invalid-app-maturity", v2_manifest(app_maturity=["customer-android"]))
        self.assert_error("invalid-app-maturity", v2_manifest(app_maturity={3: {"level": "baseline"}}))

    def test_invalid_app_declaration(self) -> None:
        for bad in ("backend", 7, None):
            with self.subTest(app=bad):
                self.assert_error("invalid-app-declaration", v2_manifest(apps=[bad], app_maturity={}))
        self.assert_error("invalid-app-declaration", v2_manifest(apps={"id": "backend"}, app_maturity={}))
        manifest = v2_manifest()
        manifest["apps"][0]["name"] = ["Customer app"]
        self.assert_error("invalid-app-declaration", manifest)
        manifest = v2_manifest()
        manifest["apps"][0]["audience"] = 5
        self.assert_error("invalid-app-declaration", manifest)

    def test_an_invalid_app_does_not_cascade_into_maturity_errors(self) -> None:
        manifest = v2_manifest()
        manifest["apps"][0]["stack"] = "nope"
        _, diagnostics = normalized(manifest)
        self.assertEqual(["unknown-app-stack"], codes(diagnostics))

    def test_slug_rule_is_the_project_slug_rule(self) -> None:
        for good in ("backend", "web-user-app", "a1", "customer-android-2"):
            self.assertTrue(app_model.is_slug(good), good)
        for bad in ("Backend", "1a", "a_b", "a--b", "a-", "-a", "", "a b", "é", 3, None):
            self.assertFalse(app_model.is_slug(bad), bad)


class CapabilityResolutionTests(unittest.TestCase):
    def test_stack_defaults(self) -> None:
        for stack_id, ui, api in (("spring-backend", False, True), ("nextjs-web", True, False), ("android-compose", True, False), ("ios-swiftui", True, False)):
            with self.subTest(stack=stack_id):
                app = App(id="x", name="X", stack=stack_id, path="x")
                self.assertEqual({"has-ui": ui, "serves-api": api}, app.capabilities)
                self.assertIs(ui, app.capability("has-ui"))
                self.assertIs(api, app.capability("serves-api"))

    def test_overrides_win_over_defaults(self) -> None:
        app = App(id="web", name="Web", stack="nextjs-web", path="web", capability_overrides={"serves-api": True, "has-ui": False})
        self.assertEqual({"has-ui": False, "serves-api": True}, app.capabilities)

    def test_override_to_unknown(self) -> None:
        app = App(id="web", name="Web", stack="nextjs-web", path="web", capability_overrides={"serves-api": "unknown"})
        self.assertEqual("unknown", app.capability("serves-api"))
        self.assertIs(True, app.capability("has-ui"))

    def test_an_other_app_has_no_defaults(self) -> None:
        bare = App(id="tool", name="Tool", stack="other", path="tool")
        self.assertEqual({"has-ui": "unknown", "serves-api": "unknown"}, bare.capabilities)
        declared = App(id="tool", name="Tool", stack="other", path="tool", capability_overrides={"has-ui": False, "serves-api": "unknown"})
        self.assertEqual({"has-ui": False, "serves-api": "unknown"}, declared.capabilities)

    def test_a_gate_treats_unknown_as_true(self) -> None:
        app = App(id="tool", name="Tool", stack="other", path="tool", capability_overrides={"has-ui": False, "serves-api": "unknown"})
        self.assertFalse(app.gate_capability("has-ui"))
        self.assertTrue(app.gate_capability("serves-api"))

    def test_resolved_capabilities_from_a_normalized_manifest(self) -> None:
        manifest = v2_manifest(
            apps=[
                {"id": "site", "stack": "nextjs-web", "path": "site", "capabilities": {"serves-api": True}},
                {"id": "tool", "stack": "other", "path": "tool", "capabilities": {"has-ui": "unknown", "serves-api": False}},
            ],
            app_maturity={},
        )
        model, diagnostics = normalized(manifest)
        self.assertEqual([], diagnostics)
        self.assertEqual({"has-ui": True, "serves-api": True}, model.app("site").capabilities)
        self.assertEqual({"has-ui": "unknown", "serves-api": False}, model.app("tool").capabilities)


class LocalRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "workspace"
        self.root.mkdir()
        self.checkout = Path(temporary.name) / "mobile-apps"
        self.checkout.mkdir()
        self.model, _ = normalized(v2_manifest())

    def write_local(self, text: str) -> None:
        (self.root / "prism.local.yml").write_text(text, encoding="utf-8")

    def test_a_declared_external_repository_resolves_to_its_checkout(self) -> None:
        self.write_local(yaml.safe_dump({"repositories": {"mobile-apps": str(self.checkout)}}))
        result = resolve_local_repositories(self.root, self.model)
        self.assertEqual({"mobile-apps": self.checkout}, dict(result.paths))
        self.assertEqual((), result.diagnostics)

    def test_a_missing_file_is_one_warning_per_external_repository_and_not_an_error(self) -> None:
        result = resolve_local_repositories(self.root, self.model)
        self.assertEqual({}, dict(result.paths))
        self.assertEqual(["external-repository-unresolved"], codes(list(result.diagnostics)))
        self.assertEqual("warning", result.diagnostics[0].severity)
        self.assertIn("`mobile-apps`", result.diagnostics[0].message)
        self.assertIn("prism.local.yml", result.diagnostics[0].message)

    def test_a_missing_entry_is_unresolved(self) -> None:
        self.write_local("repositories: {}\n")
        result = resolve_local_repositories(self.root, self.model)
        self.assertEqual(["external-repository-unresolved"], codes(list(result.diagnostics)))

    def test_a_missing_path_is_unresolved(self) -> None:
        self.write_local(yaml.safe_dump({"repositories": {"mobile-apps": str(self.checkout / "gone")}}))
        result = resolve_local_repositories(self.root, self.model)
        self.assertEqual({}, dict(result.paths))
        self.assertEqual(["external-repository-unresolved"], codes(list(result.diagnostics)))

    def test_a_file_in_place_of_a_directory_is_unresolved(self) -> None:
        target = self.checkout / "file.txt"
        target.write_text("x", encoding="utf-8")
        self.write_local(yaml.safe_dump({"repositories": {"mobile-apps": str(target)}}))
        self.assertEqual(["external-repository-unresolved"], codes(list(resolve_local_repositories(self.root, self.model).diagnostics)))

    def test_a_relative_path_is_invalid(self) -> None:
        self.write_local("repositories:\n  mobile-apps: ../mobile-apps\n")
        result = resolve_local_repositories(self.root, self.model)
        self.assertEqual({}, dict(result.paths))
        self.assertEqual(["invalid-local-repository-path"], codes(list(result.diagnostics)))
        self.assertEqual("warning", result.diagnostics[0].severity)

    def test_an_empty_or_non_string_path_is_invalid(self) -> None:
        for value in ("", None, 5, ["x"]):
            with self.subTest(value=value):
                self.write_local(yaml.safe_dump({"repositories": {"mobile-apps": value}}))
                self.assertEqual(["invalid-local-repository-path"], codes(list(resolve_local_repositories(self.root, self.model).diagnostics)))

    def test_an_unknown_id_is_a_warning(self) -> None:
        self.write_local(yaml.safe_dump({"repositories": {"mobile-apps": str(self.checkout), "other-repo": str(self.checkout), "workspace": str(self.checkout)}}))
        result = resolve_local_repositories(self.root, self.model)
        self.assertEqual({"mobile-apps": self.checkout}, dict(result.paths))
        self.assertEqual(["unknown-local-repository", "unknown-local-repository"], codes(list(result.diagnostics)))
        self.assertEqual({"warning"}, {item.severity for item in result.diagnostics})

    def test_an_unreadable_file_is_not_an_error(self) -> None:
        for text in ("repositories: [", "- just\n- a list\n", "repositories: [a, b]\n", "repositories:\n  1: /x\n"):
            with self.subTest(text=text):
                self.write_local(text)
                result = resolve_local_repositories(self.root, self.model)
                self.assertEqual({}, dict(result.paths))
                self.assertNotIn("error", {item.severity for item in result.diagnostics})
                self.assertIn("external-repository-unresolved", codes(list(result.diagnostics)))
        (self.root / "prism.local.yml").write_bytes(b"\xff\xfe\x00")
        result = resolve_local_repositories(self.root, self.model)
        self.assertEqual({"warning"}, {item.severity for item in result.diagnostics})

    def test_a_file_without_a_repositories_key_is_empty(self) -> None:
        self.write_local("other: 1\n")
        self.assertEqual(["external-repository-unresolved"], codes(list(resolve_local_repositories(self.root, self.model).diagnostics)))

    def test_a_workspace_without_external_repositories_has_nothing_to_resolve(self) -> None:
        model, _ = normalized(v2_manifest(repositories=[], apps=[], app_maturity={}))
        self.assertEqual((), resolve_local_repositories(self.root, model).diagnostics)

    def test_one_warning_per_unresolved_repository(self) -> None:
        manifest = v2_manifest(
            repositories=[
                {"id": "one", "remote": "https://example.com/a/one.git"},
                {"id": "two", "remote": "https://example.com/a/two.git"},
                {"id": "three", "remote": "https://example.com/a/three.git"},
            ],
            apps=[],
            app_maturity={},
        )
        model, _ = normalized(manifest)
        self.write_local(yaml.safe_dump({"repositories": {"two": str(self.checkout)}}))
        result = resolve_local_repositories(self.root, model)
        self.assertEqual(["external-repository-unresolved", "external-repository-unresolved"], codes(list(result.diagnostics)))
        self.assertEqual({"two": self.checkout}, dict(result.paths))
        self.assertTrue("`one`" in result.diagnostics[0].message and "`three`" in result.diagnostics[1].message)

    def test_a_symlinked_override_file_is_ignored(self) -> None:
        real = self.root.parent / "elsewhere.yml"
        real.write_text(yaml.safe_dump({"repositories": {"mobile-apps": str(self.checkout)}}), encoding="utf-8")
        try:
            os.symlink(real, self.root / "prism.local.yml")
        except (OSError, NotImplementedError):
            self.skipTest("Symbolic links are not available here.")
        result = resolve_local_repositories(self.root, self.model)
        self.assertEqual({}, dict(result.paths))
        self.assertEqual({"unreadable-local-repositories", "external-repository-unresolved"}, set(codes(list(result.diagnostics))))

    def test_a_symlinked_checkout_is_not_followed(self) -> None:
        link = self.root.parent / "linked-checkout"
        try:
            os.symlink(self.checkout, link, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("Symbolic links are not available here.")
        self.write_local(yaml.safe_dump({"repositories": {"mobile-apps": str(link)}}))
        result = resolve_local_repositories(self.root, self.model)
        self.assertEqual({}, dict(result.paths))
        self.assertEqual(["external-repository-unresolved"], codes(list(result.diagnostics)))

    def test_resolution_writes_nothing(self) -> None:
        self.write_local(yaml.safe_dump({"repositories": {"mobile-apps": str(self.checkout)}}))
        before = sorted(path.relative_to(self.root.parent).as_posix() for path in self.root.parent.rglob("*"))
        resolve_local_repositories(self.root, self.model)
        self.assertEqual(before, sorted(path.relative_to(self.root.parent).as_posix() for path in self.root.parent.rglob("*")))
        self.assertEqual([], list(self.checkout.iterdir()))


if __name__ == "__main__":
    unittest.main()
