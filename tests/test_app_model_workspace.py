"""Version-2 manifests through every reader, and the version-1 compatibility proof."""

from __future__ import annotations

import contextlib
import io
import json
from argparse import Namespace
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import yaml

from prism_cli import __version__, cli
from prism_cli.board_service import BoardError, BoardService, BoardServiceIdentity
from prism_cli.app_model import apps_from_platforms, normalize_manifest
from prism_cli.manifest_update import (
    ManifestMergeConflict,
    ManifestUpdateError,
    load_workspace_manifest,
    merge_workspace_manifest,
    prepare_manifest_update,
    read_workspace_manifest,
)
from prism_cli.status import build_status
from prism_cli.wiki_transitions import _board_workspace_identity_checks
from prism_cli.workflow_assets import asset_digest
from prism_cli.workflow_install import apply_install, plan_install
from prism_cli.workspace import (
    MANIFEST_FILE,
    WorkspaceManifest,
    detect_workspace_kind,
    inspect_workspace,
    load_workspace,
    write_workspace_manifest,
)
from tests import app_model_baseline
from tests.manifest_fixtures import manifest_data as fixture_manifest
from tests import real_temp  # noqa: F401


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "app_model_baseline"

REPOSITORIES = [
    {"id": "workspace"},
    {"id": "mobile-apps", "remote": "https://example.com/acme/mobile-apps.git"},
]
APPS = [
    {"id": "customer-android", "name": "Customer app", "stack": "android-compose", "repository": "workspace", "path": "mobile-android", "audience": "B2C"},
    {"id": "partner-android", "name": "Partner app", "stack": "android-compose", "repository": "mobile-apps", "path": "apps/partner", "audience": "B2B"},
    {"id": "backend", "name": "API", "stack": "spring-backend", "repository": "workspace", "path": "backend"},
]
MATURITY = {
    "customer-android": {"level": "provisional", "caveat": "Beta."},
    "partner-android": {"level": "experimental", "caveat": "Built outside this repository."},
}


def install_workflow(root: Path, *, name: str = "Two apps", platforms: tuple[str, ...] = ("backend",)) -> None:
    receipt = apply_install(root, plan_install(root, name=name, apps=list(platforms)))
    if receipt["status"] != "applied":
        raise AssertionError(f"Workflow install did not apply: {receipt}")


def manifest_data(root: Path) -> dict:
    return yaml.safe_load((root / MANIFEST_FILE).read_text(encoding="utf-8"))


def write_manifest(root: Path, data: dict) -> None:
    (root / MANIFEST_FILE).write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def declare_two_apps(root: Path, **changes: object) -> None:
    """Replace the installed workspace's apps with the two-app declaration, plus any other changes."""

    data = manifest_data(root)
    data["repositories"] = [dict(item) for item in REPOSITORIES]
    data["apps"] = [dict(item) for item in APPS]
    data["app_maturity"] = {key: dict(value) for key, value in MATURITY.items()}
    data.update(changes)
    write_manifest(root, data)


def top_level_block(text: str, key: str) -> str:
    """The text of one top-level key of a manifest written by ``yaml.safe_dump``."""

    lines = text.splitlines(keepends=True)
    start = next(index for index, line in enumerate(lines) if line.startswith(f"{key}:"))
    end = next((index for index in range(start + 1, len(lines)) if lines[index][:1] not in (" ", "-", "\t", "\n")), len(lines))
    return "".join(lines[start:end])


def error_diagnostics(diagnostics: list) -> list:
    return [item for item in diagnostics if item.severity == "error"]


class TwoAppWorkspaceCase(unittest.TestCase):
    """A disposable version-2 workspace with installed workflow assets and two apps of one stack."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "ws"
        self.root.mkdir()
        install_workflow(self.root)
        declare_two_apps(self.root)

    def start_service(self) -> BoardService:
        service = BoardService(self.root).start()
        self.addCleanup(service.close)
        return service


class TwoAppModelTests(TwoAppWorkspaceCase):
    def test_both_apps_load_distinct_with_their_own_maturity(self) -> None:
        result = load_workspace(self.root)

        self.assertIsNotNone(result.manifest)
        self.assertEqual(2, result.manifest_schema_version)
        self.assertEqual([], error_diagnostics(result.diagnostics))
        apps = {app.id: app for app in result.manifest.apps}
        self.assertEqual(["customer-android", "partner-android", "backend"], list(apps))
        self.assertEqual("android-compose", apps["customer-android"].stack)
        self.assertEqual("android-compose", apps["partner-android"].stack)
        self.assertEqual(("workspace", "mobile-android"), (apps["customer-android"].repository, apps["customer-android"].path))
        self.assertEqual(("mobile-apps", "apps/partner"), (apps["partner-android"].repository, apps["partner-android"].path))
        self.assertEqual(MATURITY, result.manifest.app_maturity)
        self.assertNotEqual(result.manifest.app_maturity["customer-android"], result.manifest.app_maturity["partner-android"])

    def test_inspection_lists_all_three_app_ids(self) -> None:
        inspection = inspect_workspace(self.root)
        self.assertEqual(["customer-android", "partner-android", "backend"], inspection.app_ids)
        self.assertEqual(["customer-android", "partner-android", "backend"], inspection.manifest.app_ids)
        self.assertEqual([], error_diagnostics(inspection.contract_diagnostics))

    def test_status_reports_each_apps_maturity(self) -> None:
        status = build_status(self.root)
        self.assertEqual(["customer-android", "partner-android", "backend"], [app["id"] for app in status.apps])
        self.assertEqual(MATURITY, {app["id"]: app["maturity"] for app in status.apps if app["maturity"] is not None})
        self.assertEqual(
            [{"id": "workspace", "remote": None}, {"id": "mobile-apps", "remote": "https://example.com/acme/mobile-apps.git", "checkout": "unresolved"}],
            status.repositories,
        )

    def test_without_prism_local_yml_the_workspace_loads_with_exactly_one_unresolved_warning(self) -> None:
        result = load_workspace(self.root)
        unresolved = [item for item in result.diagnostics if item.code == "external-repository-unresolved"]
        self.assertEqual(1, len(unresolved))
        self.assertEqual("warning", unresolved[0].severity)
        self.assertIn("mobile-apps", unresolved[0].message)
        self.assertEqual({}, dict(result.local_repositories))
        inspection = inspect_workspace(self.root)
        self.assertEqual(1, len([item for item in inspection.contract_diagnostics if item.code == "external-repository-unresolved"]))
        self.assertEqual([], error_diagnostics(inspection.contract_diagnostics))

    def test_a_resolved_checkout_removes_the_warning(self) -> None:
        checkout = self.root.parent / "mobile-apps"
        checkout.mkdir()
        (self.root / "prism.local.yml").write_text(yaml.safe_dump({"repositories": {"mobile-apps": str(checkout)}}), encoding="utf-8")
        result = load_workspace(self.root)
        self.assertEqual([], [item for item in result.diagnostics if item.code == "external-repository-unresolved"])
        self.assertEqual({"mobile-apps": checkout}, dict(result.local_repositories))

    def test_reading_writes_nothing(self) -> None:
        def snapshot() -> dict[str, bytes]:
            return {path.relative_to(self.root).as_posix(): path.read_bytes() for path in sorted(self.root.rglob("*")) if path.is_file()}

        before = snapshot()
        load_workspace(self.root)
        inspect_workspace(self.root)
        build_status(self.root)
        self.assertEqual(before, snapshot())

    def test_the_workspace_kind_and_identity_checks_accept_version_two(self) -> None:
        self.assertEqual("workflow-project", detect_workspace_kind(self.root))
        checks = _board_workspace_identity_checks(self.root, inspect_workspace(self.root))
        self.assertEqual(["pass"], [item["status"] for item in checks])

    def test_a_workflow_workspace_may_have_zero_apps(self) -> None:
        declare_two_apps(self.root, apps=[], app_maturity={})
        result = load_workspace(self.root)
        self.assertEqual([], [item for item in result.diagnostics if item.code == "missing-workflow-scope"])
        self.assertEqual([], error_diagnostics(result.diagnostics))
        inspection = inspect_workspace(self.root)
        self.assertEqual([], inspection.app_ids)
        self.assertEqual([], error_diagnostics(inspection.contract_diagnostics))

    def test_project_platforms_in_a_version_two_manifest_is_an_error(self) -> None:
        data = manifest_data(self.root)
        data["project"]["platforms"] = ["backend"]
        write_manifest(self.root, data)
        diagnostics = load_workspace(self.root).diagnostics
        self.assertEqual(["conflicting-app-declarations"], [item.code for item in error_diagnostics(diagnostics)])

    def test_version_one_is_refused_and_the_inspection_falls_back_to_the_filesystem(self) -> None:
        write_manifest(self.root, {"schema_version": 1, "project": {"name": "Old", "platforms": ["backend"]}})
        result = load_workspace(self.root)
        self.assertIsNone(result.manifest)
        self.assertEqual(["unsupported-workspace-manifest-schema"], [item.code for item in result.diagnostics])
        service = BoardService(self.root)
        self.addCleanup(service.close)
        self.assertEqual("The workspace manifest schema is missing or unsupported; connected writes are read-only.", service.compatibility()["reason"])
        self.assertIsNone(BoardServiceIdentity(self.root))


class VersionTwoFilesystemTests(unittest.TestCase):
    """Apps in this repository are compared with the workspace at their paths; external apps never are."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "generated"
        self.root.mkdir()
        self.manifest = {
            "schema_version": 2,
            "project": {"name": "Generated two apps"},
            "repositories": [dict(item) for item in REPOSITORIES],
            "apps": [dict(item) for item in APPS],
        }
        write_manifest(self.root, self.manifest)

    def drift(self) -> list:
        return [item for item in inspect_workspace(self.root).contract_diagnostics if item.code == "manifest-filesystem-drift"]

    def test_present_in_workspace_apps_and_an_unchecked_external_app_have_no_drift(self) -> None:
        (self.root / "mobile-android").mkdir()
        (self.root / "backend").mkdir()
        self.assertFalse((self.root / "apps").exists())
        self.assertEqual([], self.drift())

    def test_a_missing_in_workspace_app_directory_is_an_error_naming_the_app(self) -> None:
        (self.root / "backend").mkdir()
        drift = self.drift()
        self.assertEqual([("error", "customer-android")], [(item.severity, item.message.split("`")[1]) for item in drift])
        self.assertTrue(item_path_endswith(drift[0].path, "mobile-android"))

    def test_a_retired_app_is_not_required_on_disk(self) -> None:
        self.manifest["apps"][0]["status"] = "retired"
        write_manifest(self.root, self.manifest)
        (self.root / "backend").mkdir()
        self.assertEqual([], self.drift())

    def test_an_undeclared_legacy_directory_is_a_warning(self) -> None:
        for name in ("mobile-android", "backend", "web"):
            (self.root / name).mkdir()
        drift = self.drift()
        self.assertEqual(["warning"], [item.severity for item in drift])
        self.assertTrue(item_path_endswith(drift[0].path, "web"))

    def test_an_app_at_a_custom_path_counts_as_declared(self) -> None:
        self.manifest["apps"][2]["path"] = "services/api"
        write_manifest(self.root, self.manifest)
        (self.root / "mobile-android").mkdir()
        (self.root / "services" / "api").mkdir(parents=True)
        self.assertEqual([], self.drift())

    def test_a_workflow_only_manifest_skips_the_comparison(self) -> None:
        self.manifest["workflow"] = {"version": "1", "mode": "workflow", "board_id": "6f1c1b0e-3d2a-4a43-9c55-0d0a5b0e7a11"}
        write_manifest(self.root, self.manifest)
        self.assertEqual([], self.drift())


def item_path_endswith(path: str, name: str) -> bool:
    return Path(path).name == name


class TwoAppBoardTests(TwoAppWorkspaceCase):
    def test_the_board_service_starts_writable_with_every_app_in_its_platform_list(self) -> None:
        service = self.start_service()

        self.assertEqual({"read_only": False, "reason": None}, service.compatibility())
        self.assertEqual(["customer-android", "partner-android", "backend"], service._app_ids)
        grant = service.create_participant("Writer", "human", writable=True)
        actor = service.authenticate(grant["token"])
        self.assertTrue(actor.writable)
        board = service.discover(actor)["board"]
        self.assertEqual(["customer-android", "partner-android", "backend"], [app["id"] for app in board["apps"]])
        self.assertNotIn("platforms", board)
        self.assertEqual("Two apps", board["project_name"])

    def test_the_identity_binds_schema_version_two_and_each_active_app(self) -> None:
        identity = BoardServiceIdentity(self.root)

        self.assertIsNotNone(identity)
        self.assertEqual(
            (
                ("customer-android", "android-compose", "workspace", "mobile-android"),
                ("partner-android", "android-compose", "mobile-apps", "apps/partner"),
                ("backend", "spring-backend", "workspace", "backend"),
            ),
            identity[5],
        )
        self.assertEqual(2, identity[6])
        self.assertEqual(identity, self.start_service()._identity_facts)

    def test_changing_an_apps_stack_repository_or_path_changes_the_identity_and_blocks_grants(self) -> None:
        service = self.start_service()
        actor = service.authenticate(service.create_participant("Writer", "human", writable=True)["token"])
        baseline = BoardServiceIdentity(self.root)
        changes = (
            ("path", lambda apps: apps[1].update(path="apps/partner-v2")),
            ("repository", lambda apps: apps[0].update(repository="mobile-apps", path="apps/customer")),
            ("stack", lambda apps: apps[2].update(stack="other", capabilities={"has-ui": False, "serves-api": True})),
            ("added app", lambda apps: apps.append({"id": "tablet", "stack": "android-compose", "path": "tablet"})),
        )
        for label, change in changes:
            with self.subTest(change=label):
                data = manifest_data(self.root)
                change(data["apps"])
                write_manifest(self.root, data)
                changed = BoardServiceIdentity(self.root)
                self.assertNotEqual(baseline, changed)
                with self.assertRaises(BoardError) as error:
                    service.discover(actor)
                self.assertEqual("workspace_identity_changed", error.exception.code)
                declare_two_apps(self.root)
                self.assertEqual(baseline, BoardServiceIdentity(self.root))
                service.discover(actor)

    def test_retiring_an_app_changes_the_identity_and_leaves_the_platform_list(self) -> None:
        baseline = BoardServiceIdentity(self.root)
        data = manifest_data(self.root)
        data["apps"][1]["status"] = "retired"
        write_manifest(self.root, data)
        self.assertNotEqual(baseline, BoardServiceIdentity(self.root))
        service = BoardService(self.root)
        self.addCleanup(service.close)
        self.assertEqual(["customer-android", "backend"], service._app_ids)

    def test_renaming_an_app_changes_only_its_name(self) -> None:
        baseline = BoardServiceIdentity(self.root)
        data = manifest_data(self.root)
        data["apps"][0]["name"] = "Customer Android"
        data["apps"][0]["audience"] = "Everyone"
        write_manifest(self.root, data)
        self.assertEqual(baseline, BoardServiceIdentity(self.root))

    def test_invalid_declarations_leave_the_board_read_only_with_the_problem_codes(self) -> None:
        data = manifest_data(self.root)
        data["apps"][1]["stack"] = "nope"
        data["app_maturity"]["ghost"] = {"level": "baseline"}
        write_manifest(self.root, data)

        service = BoardService(self.root)
        self.addCleanup(service.close)
        compatibility = service.compatibility()
        self.assertTrue(compatibility["read_only"])
        self.assertIn("unknown-app-stack", compatibility["reason"])
        self.assertIn("invalid-app-maturity", compatibility["reason"])
        with self.assertRaises(BoardError) as error:
            service.start()
        self.assertEqual("workspace_read_only", error.exception.code)
        self.assertIsNone(BoardServiceIdentity(self.root))

    def test_a_version_two_manifest_with_no_active_app_is_writable(self) -> None:
        declare_two_apps(self.root, apps=[], app_maturity={})
        service = self.start_service()
        self.assertEqual({"read_only": False, "reason": None}, service.compatibility())
        self.assertEqual([], service._app_ids)
        actor = service.authenticate(service.create_participant("Writer", "human", writable=True)["token"])
        self.assertTrue(actor.writable)
        self.assertEqual([], service.discover(actor)["board"]["apps"])

    def test_unsupported_schema_versions_stay_read_only(self) -> None:
        for version in (3, 99, True, "2", 2.0):
            with self.subTest(version=version):
                data = manifest_data(self.root)
                data["schema_version"] = version
                write_manifest(self.root, data)
                service = BoardService(self.root)
                self.addCleanup(service.close)
                self.assertEqual("The workspace manifest schema is missing or unsupported; connected writes are read-only.", service.compatibility()["reason"])
                self.assertIsNone(BoardServiceIdentity(self.root))

    def test_validate_graph_inputs_covers_the_apps_paths_in_this_repository(self) -> None:
        service = self.start_service()
        data = manifest_data(self.root)
        data["apps"].append({"id": "kiosk", "stack": "android-compose", "path": "devices/kiosk"})
        write_manifest(self.root, data)
        service2 = BoardService(self.root)
        self.addCleanup(service2.close)
        checked: list[str] = []
        original = service2._reject_reparse_below

        def record(root: Path, path: Path, seen: set) -> None:
            checked.append(path.relative_to(root).as_posix())
            return original(root, path, seen)

        with patch.object(service2, "_reject_reparse_below", side_effect=record):
            service2.validate_graph_inputs()
        self.assertIn("devices/kiosk", checked)
        self.assertIn("mobile-android", checked)
        self.assertNotIn("apps/partner", checked)
        self.assertNotIn("web", checked)
        service.validate_graph_inputs()


class SingleAppBoardIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "ws"
        self.root.mkdir()
        install_workflow(self.root, name="One platform", platforms=("backend", "mobile-android"))

    def reason(self) -> str | None:
        service = BoardService(self.root)
        self.addCleanup(service.close)
        return service.compatibility()["reason"]

    def test_the_identity_is_the_workflow_pin_and_the_normalized_active_apps(self) -> None:
        data = manifest_data(self.root)
        expected_paths = tuple(sorted(data["paths"].items()))

        identity = BoardServiceIdentity(self.root)

        self.assertEqual(
            (
                data["workflow"]["board_id"],
                "1",
                "workflow",
                asset_digest("1"),
                "One platform",
                (("backend", "spring-backend", "workspace", "backend"), ("mobile-android", "android-compose", "workspace", "mobile-android")),
                2,
                (expected_paths, (), data["min_prism_cli_version"]),
            ),
            identity,
        )
        service = BoardService(self.root)
        self.addCleanup(service.close)
        self.assertEqual(identity, service._identity_facts)
        self.assertEqual(["backend", "mobile-android"], service._app_ids)
        self.assertEqual({"read_only": False, "reason": None}, service.compatibility())

    def test_invalid_app_scopes_leave_the_board_read_only(self) -> None:
        cases = {
            "apps not a list": ("backend", "invalid-app-declaration"),
            "unknown stack": ([{"id": "backend", "stack": "nope"}], "unknown-app-stack"),
            "duplicate id": ([{"id": "backend", "stack": "spring-backend"}, {"id": "backend", "stack": "spring-backend", "path": "other"}], "duplicate-app-id"),
            "invalid id": ([{"id": "Backend", "stack": "spring-backend"}], "invalid-app-id"),
        }
        for label, (apps, expected) in cases.items():
            with self.subTest(case=label):
                data = manifest_data(self.root)
                data["apps"] = apps
                write_manifest(self.root, data)
                self.assertIn(expected, self.reason() or "")
                self.assertIsNone(BoardServiceIdentity(self.root))
        data = manifest_data(self.root)
        data["project"]["name"] = "  "
        data["apps"] = [dict(item) for item in APPS[2:]]
        write_manifest(self.root, data)
        self.assertEqual("A project name is required.", self.reason())

    def test_project_platforms_makes_the_board_read_only(self) -> None:
        data = manifest_data(self.root)
        data["project"]["platforms"] = ["backend"]
        write_manifest(self.root, data)
        self.assertIn("conflicting-app-declarations", self.reason() or "")

    def test_manifest_properties_are_the_normalized_apps(self) -> None:
        manifest = WorkspaceManifest(
            path=Path(MANIFEST_FILE),
            data={"schema_version": 2, "apps": [{"id": "backend", "stack": "spring-backend"}], "app_maturity": {"backend": {"level": "baseline", "n": 1}}},
        )
        self.assertEqual(["backend"], manifest.app_ids)
        self.assertEqual({"backend": {"level": "baseline"}}, manifest.app_maturity)
        self.assertFalse(hasattr(manifest, "platform_maturity"))
        self.assertEqual(["backend"], manifest.model.active_app_ids)


class WorkflowInstallAppsTests(TwoAppWorkspaceCase):
    FIELDS = ("repositories", "apps", "app_maturity")

    def stale_pin(self) -> None:
        data = manifest_data(self.root)
        data["workflow"]["asset_digest"] = "0" * 64
        write_manifest(self.root, data)

    def test_upgrade_repins_the_workflow_and_keeps_the_version_two_fields_untouched(self) -> None:
        self.stale_pin()
        before = (self.root / MANIFEST_FILE).read_text(encoding="utf-8")
        before_data = manifest_data(self.root)

        plan = plan_install(self.root, upgrade=True)

        self.assertEqual([], plan["conflicts"])
        self.assertEqual(["customer-android", "partner-android", "backend"], plan["apps"])
        self.assertNotIn("platforms", plan)
        receipt = apply_install(self.root, plan)
        self.assertEqual("applied", receipt["status"])
        after = (self.root / MANIFEST_FILE).read_text(encoding="utf-8")
        after_data = manifest_data(self.root)

        for field in self.FIELDS:
            with self.subTest(field=field):
                self.assertEqual(top_level_block(before, field), top_level_block(after, field))
                self.assertEqual(before_data[field], after_data[field])
        self.assertEqual(2, after_data["schema_version"])
        self.assertNotIn("platforms", after_data["project"])
        self.assertEqual(asset_digest("1"), after_data["workflow"]["asset_digest"])
        self.assertEqual(before_data["workflow"]["board_id"], after_data["workflow"]["board_id"])
        self.assertEqual({"read_only": False, "reason": None}, BoardService(self.root).compatibility())

    def test_upgrade_of_a_current_version_two_workspace_changes_nothing(self) -> None:
        before = (self.root / MANIFEST_FILE).read_bytes()
        plan = plan_install(self.root, upgrade=True)
        self.assertEqual([], plan["conflicts"])
        self.assertEqual([], [item["path"] for item in plan["changes"]])
        apply_install(self.root, plan)
        self.assertEqual(before, (self.root / MANIFEST_FILE).read_bytes())

    def test_an_app_scope_that_would_change_the_apps_is_a_conflict(self) -> None:
        self.stale_pin()
        before = (self.root / MANIFEST_FILE).read_bytes()
        for upgrade in (True, False):
            with self.subTest(upgrade=upgrade):
                plan = plan_install(self.root, apps=["backend"], upgrade=upgrade)
                self.assertTrue(any("`--app` cannot change the apps of this workspace" in item and "`prism app add`" in item for item in plan["conflicts"]), plan["conflicts"])
                self.assertEqual("conflict", apply_install(self.root, plan)["status"])
        self.assertEqual(before, (self.root / MANIFEST_FILE).read_bytes())

    def test_naming_the_apps_the_workspace_already_has_is_not_a_conflict(self) -> None:
        data = manifest_data(self.root)
        data["apps"] = apps_from_platforms(["backend", "mobile-ios"])
        data["app_maturity"] = {}
        data["repositories"] = []
        data["workflow"]["asset_digest"] = "0" * 64
        write_manifest(self.root, data)
        plan = plan_install(self.root, apps=["mobile-ios", "backend"], upgrade=True)
        self.assertEqual([], plan["conflicts"])
        self.assertEqual(["backend", "mobile-ios"], plan["apps"])

    def test_the_app_option_fails_through_the_command(self) -> None:
        self.stale_pin()
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = cli.main(["workflow", "upgrade", str(self.root), "--app", "backend", "--apply", "--yes"])
        self.assertEqual(3, code)
        self.assertIn("Conflict: `--app` cannot change the apps of this workspace", stderr.getvalue())
        self.assertIn("prism app add", stderr.getvalue())

    def test_invalid_version_two_declarations_block_the_upgrade(self) -> None:
        self.stale_pin()
        data = manifest_data(self.root)
        data["project"]["platforms"] = ["backend"]
        write_manifest(self.root, data)
        plan = plan_install(self.root, upgrade=True)
        self.assertTrue(any("conflicting-app-declarations" in item for item in plan["conflicts"]), plan["conflicts"])

    def test_a_zero_app_version_two_workspace_can_be_upgraded(self) -> None:
        declare_two_apps(self.root, apps=[], app_maturity={})
        self.stale_pin()
        plan = plan_install(self.root, upgrade=True)
        self.assertEqual([], plan["conflicts"])
        self.assertEqual([], plan["apps"])
        self.assertEqual("applied", apply_install(self.root, plan)["status"])
        self.assertEqual([], manifest_data(self.root)["apps"])

    def test_new_installs_write_the_chosen_platforms_as_apps(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            install_workflow(root, name="Fresh", platforms=("mobile-ios", "backend", "web"))
            data = manifest_data(root)
        self.assertEqual(2, data["schema_version"])
        self.assertNotIn("platforms", data["project"])
        self.assertEqual(apps_from_platforms(["backend", "mobile-ios", "web"]), data["apps"])
        self.assertNotIn("repositories", data)
        model, diagnostics = normalize_manifest(data, path=Path(MANIFEST_FILE))
        self.assertEqual([], diagnostics)
        self.assertEqual(["backend", "mobile-ios", "web"], model.active_app_ids)

    def test_other_schema_versions_are_still_rejected_for_adoption(self) -> None:
        data = manifest_data(self.root)
        data["schema_version"] = 3
        write_manifest(self.root, data)
        plan = plan_install(self.root, upgrade=True)
        self.assertTrue(any("must use schema_version 2" in item for item in plan["conflicts"]), plan["conflicts"])
        write_manifest(self.root, {"schema_version": 1, "project": {"name": "Old", "platforms": ["backend"]}})
        plan = plan_install(self.root, upgrade=True)
        self.assertTrue(any("must use schema_version 2" in item and "recreate or reinstall" in item for item in plan["conflicts"]), plan["conflicts"])


class ManifestUpdateAppsTests(TwoAppWorkspaceCase):
    def test_the_update_readers_read_the_apps_through_the_normalizer(self) -> None:
        manifest, source = read_workspace_manifest(self.root / MANIFEST_FILE, "workspace")
        self.assertEqual(2, manifest["schema_version"])
        self.assertEqual(["customer-android", "partner-android", "backend"], [item["id"] for item in manifest["apps"]])
        self.assertEqual(source, (self.root / MANIFEST_FILE).read_bytes())
        self.assertEqual(manifest, load_workspace_manifest(self.root / MANIFEST_FILE))

    def test_invalid_declarations_stop_the_update_before_anything_is_merged(self) -> None:
        data = manifest_data(self.root)
        data["apps"][0]["stack"] = "nope"
        write_manifest(self.root, data)
        with self.assertRaisesRegex(ManifestUpdateError, "unknown-app-stack"):
            load_workspace_manifest(self.root / MANIFEST_FILE)

    def test_a_version_one_manifest_stops_the_update(self) -> None:
        write_manifest(self.root, {"schema_version": 1, "project": {"name": "Old", "platforms": ["backend"]}})
        with self.assertRaisesRegex(ManifestUpdateError, "unsupported schema_version 1"):
            load_workspace_manifest(self.root / MANIFEST_FILE)

    def test_the_merge_keeps_workspace_edited_apps_and_applies_template_only_changes(self) -> None:
        previous = fixture_manifest("Example", ["backend"])
        previous["min_prism_cli_version"] = "0.3.0"
        latest = {**previous, "min_prism_cli_version": "0.4.0"}
        current = {**previous, "apps": previous["apps"] + [{"id": "partner-android", "stack": "android-compose", "repository": "mobile-apps", "path": "apps/partner"}],
                   "repositories": [{"id": "mobile-apps", "remote": "https://example.com/acme/mobile-apps.git"}]}

        merged = merge_workspace_manifest(previous, current, latest)

        self.assertEqual("0.4.0", merged["min_prism_cli_version"])
        self.assertEqual(current["apps"], merged["apps"])
        self.assertEqual(current["repositories"], merged["repositories"])

    def test_competing_edits_to_the_apps_are_a_conflict(self) -> None:
        previous = fixture_manifest("Example", ["backend"])
        current = fixture_manifest("Example", ["backend", "mobile-ios"])
        latest = fixture_manifest("Example", ["backend", "web"])
        with self.assertRaises(ManifestMergeConflict) as raised:
            merge_workspace_manifest(previous, current, latest)
        self.assertEqual(["apps"], raised.exception.fields)

    def test_a_workspace_with_two_apps_is_not_refused_by_the_update_command(self) -> None:
        args = Namespace(path=str(self.root), strategy="auto", yes=True, trust_template=True, from_launcher=False)
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            patch.object(cli, "detect_validation_target", return_value="generated-project"),
            patch.object(cli, "inspect_git_worktree", return_value={"is_repo": True, "is_dirty": False, "repo_root": str(self.root)}),
            patch.object(cli, "is_direct_git_worktree", return_value=True),
            patch.object(cli, "ensure_template_trust", return_value=True),
            patch.object(cli, "run_copier_update", return_value=0) as run_update,
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            (self.root / ".copier-answers.yml").write_text("_src_path: git+https://example.invalid/t.git\n_commit: v1.0.0\nproject_name: Two apps\n", encoding="utf-8")
            result = cli.cmd_update(args)
        self.assertEqual(0, result, stderr.getvalue())
        run_update.assert_called_once()


class WriteWorkspaceManifestTests(unittest.TestCase):
    ANSWERS = {"project_name": "Gen", "project_slug": "gen"}
    APPS = apps_from_platforms(["mobile-ios", "backend"], generation="scaffolded")

    def test_the_questionnaire_apps_enter_the_manifest_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = write_workspace_manifest(root, self.ANSWERS, prism_cli_version="0.3.0", apps=self.APPS)
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            self.assertEqual(2, data["schema_version"])
            self.assertEqual(self.APPS, data["apps"])
            self.assertEqual({"mobile-ios", "backend"}, set(data["app_maturity"]))
            self.assertEqual("experimental", data["app_maturity"]["mobile-ios"]["level"])
            self.assertEqual([".github/workflows/mobile-ios.yml", ".github/workflows/backend.yml"], data["expected_surfaces"]["workflows"] if "expected_surfaces" in data else [".github/workflows/mobile-ios.yml", ".github/workflows/backend.yml"])
            self.assertNotIn("platforms", data["project"])
            data["apps"].append({"id": "extra", "stack": "other", "path": "extra", "capabilities": {"has-ui": False, "serves-api": False}})
            path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

            write_workspace_manifest(root, self.ANSWERS, prism_cli_version="0.3.1", apps=apps_from_platforms(["backend"], generation="scaffolded"))

            kept = yaml.safe_load(path.read_text(encoding="utf-8"))
            self.assertEqual(["mobile-ios", "backend", "extra"], [item["id"] for item in kept["apps"]])
            self.assertEqual("0.3.1", kept["generated_by"]["prism_cli_version"])

    def test_the_apps_come_after_the_project_with_their_repositories_and_workflows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / MANIFEST_FILE).write_text(
                yaml.safe_dump({"schema_version": 2, "project": {"name": "Gen"}, "paths": {"wiki_root": "knowledge/wiki"}, "expected_surfaces": {"workflows": []}}, sort_keys=False),
                encoding="utf-8",
            )
            apps = [
                {"id": "backend", "name": "Backend", "stack": "spring-backend", "repository": "workspace", "path": "backend", "generation": "scaffolded"},
                {"id": "partner", "name": "Partner", "stack": "android-compose", "repository": "mobile", "path": "apps/partner", "generation": "registered"},
            ]
            path = write_workspace_manifest(root, self.ANSWERS, prism_cli_version="0.3.0", apps=apps, repositories=[{"id": "mobile", "remote": "https://example.com/acme/mobile.git"}])
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            keys = list(data)
            self.assertLess(keys.index("project"), keys.index("repositories"))
            self.assertLess(keys.index("repositories"), keys.index("apps"))
            self.assertEqual({"backend"}, set(data["app_maturity"]), "only a scaffolded app has a maturity")
            self.assertEqual([".github/workflows/backend.yml"], data["expected_surfaces"]["workflows"])
            model, diagnostics = normalize_manifest(data, path=Path(MANIFEST_FILE))
            self.assertEqual([], diagnostics)
            self.assertEqual(["scaffolded", "registered"], [app.generation for app in model.apps])

    def test_the_minimum_cli_version_is_the_running_cli_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = write_workspace_manifest(root, self.ANSWERS, prism_cli_version="0.0.1", apps=self.APPS)
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            self.assertEqual(__version__, data["min_prism_cli_version"])
            self.assertEqual("0.0.1", data["generated_by"]["prism_cli_version"])

    def test_workflow_adoption_records_the_running_cli_version_as_the_minimum(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            install_workflow(root)
            self.assertEqual(__version__, manifest_data(root)["min_prism_cli_version"])

    def test_an_existing_version_one_manifest_is_not_rewritten(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / MANIFEST_FILE).write_text("schema_version: 1\nproject:\n  name: Old\n", encoding="utf-8")
            before = (root / MANIFEST_FILE).read_bytes()
            with self.assertRaisesRegex(ValueError, "recreate or reinstall"):
                write_workspace_manifest(root, self.ANSWERS, prism_cli_version="0.3.0")
            self.assertEqual(before, (root / MANIFEST_FILE).read_bytes())


def copy_manifest_template_source(temporary: str) -> Path:
    """A template source with the layer root, the answers-file template, the manifest template and the pinned versions."""

    repository = Path(__file__).resolve().parents[1]
    source = Path(temporary) / "source"
    (source / "template").mkdir(parents=True)
    (source / "packs").mkdir()
    for relative in ("copier.yml", "template/{{ _copier_conf.answers_file }}.jinja", "template/prism.workspace.yml.jinja", "packs/versions.yml"):
        (source / relative).write_bytes((repository / relative).read_bytes())
    return source


class TemplateManifestTests(unittest.TestCase):
    """The Copier template renders the manifest of the workspace layer; the CLI records the apps."""

    def render(self, cli_version: str | None = None) -> dict:
        from copier import run_copy

        with tempfile.TemporaryDirectory() as temporary:
            source = copy_manifest_template_source(temporary)
            destination = Path(temporary) / "out"
            run_copy(
                str(source),
                str(destination),
                data={
                    "project_name": "Rendered",
                    "project_slug": "rendered",
                    "auth_methods": ["password"],
                    **({"_prism_cli_version": cli_version} if cli_version else {}),
                },
                defaults=True,
                unsafe=True,
                quiet=True,
            )
            return yaml.safe_load((destination / MANIFEST_FILE).read_text(encoding="utf-8"))

    def test_the_minimum_cli_version_is_the_version_the_cli_passes(self) -> None:
        data = self.render(cli_version=__version__)
        self.assertEqual(__version__, data["min_prism_cli_version"])
        self.assertEqual(__version__, data["generated_by"]["prism_cli_version"])

    def test_a_run_without_the_cli_names_no_minimum(self) -> None:
        data = self.render()
        self.assertEqual("0.0.0", data["min_prism_cli_version"])

    def test_the_template_renders_no_apps_and_the_manifest_is_valid(self) -> None:
        data = self.render()
        self.assertEqual(2, data["schema_version"])
        for key in ("apps", "app_maturity", "repositories"):
            self.assertNotIn(key, data, f"the CLI records `{key}`, not the template")
        self.assertEqual([], data["expected_surfaces"]["workflows"])
        self.assertNotIn("platforms", data["project"])
        self.assertNotIn("platform_maturity", data)
        model, diagnostics = normalize_manifest(data, path=Path(MANIFEST_FILE))
        self.assertEqual([], diagnostics)
        self.assertEqual([], model.active_app_ids)

    def test_the_cli_records_the_apps_of_all_the_default_platforms(self) -> None:
        platforms = ["backend", "web", "mobile-android", "mobile-ios"]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = write_workspace_manifest(root, {"project_name": "Rendered"}, prism_cli_version=__version__, apps=apps_from_platforms(platforms, generation="scaffolded"))
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        self.assertEqual(platforms, list(data["app_maturity"]))
        model, diagnostics = normalize_manifest(data, path=Path(MANIFEST_FILE))
        self.assertEqual([], diagnostics)
        self.assertEqual(platforms, model.active_app_ids)


class WorkspaceLayerRootTests(unittest.TestCase):
    """`render_template_manifest` resolves the workspace layer's root itself and never reads the raw `_subdirectory`."""

    def git(self, source: Path, *arguments: str) -> None:
        subprocess.run(["git", "-c", "user.name=Prism test", "-c", "user.email=test@example.invalid", "-c", "core.autocrlf=false", *arguments], cwd=source, check=True, capture_output=True, text=True)

    def build_repository(self, temporary: str) -> Path:
        source = copy_manifest_template_source(temporary)
        for arguments in (("init", "-q"), ("add", "-A"), ("commit", "-qm", "one"), ("tag", "v1.0.0")):
            self.git(source, *arguments)
        return source

    def worker(self, source: Path, destination: Path, vcs_ref: str = "v1.0.0", **data):
        from copier._main import Worker

        return Worker(src_path=str(source), dst_path=destination, vcs_ref=vcs_ref, data={"project_name": "Layered", "project_slug": "layered", "auth_methods": ["password"], "_prism_cli_version": __version__, **data}, defaults=True, skip_tasks=True, unsafe=True, quiet=True)

    def test_the_root_is_the_rendered_workspace_layer_whatever_layer_the_worker_holds(self) -> None:
        from prism_cli.manifest_update import render_template_manifest, workspace_layer_root

        with tempfile.TemporaryDirectory() as temporary:
            source = self.build_repository(temporary)
            for layer in ("workspace", "spring-backend"):
                with self.subTest(worker_layer=layer), self.worker(source, Path(temporary) / f"out-{layer}", prism_layer=layer, app_id="api") as worker:
                    worker._ask()
                    self.assertIn("{{", worker.template.subdirectory, "the template's own value is an expression, not a path")
                    self.assertEqual("template", workspace_layer_root(worker))
                    manifest = render_template_manifest(worker)
                    self.assertEqual("Layered", manifest["project"]["name"])
                    self.assertEqual(__version__, manifest["min_prism_cli_version"])

    def test_the_render_never_runs_template_tasks_and_names_a_missing_manifest(self) -> None:
        from prism_cli.manifest_update import render_template_manifest

        with tempfile.TemporaryDirectory() as temporary:
            source = self.build_repository(temporary)
            (source / "template" / "prism.workspace.yml.jinja").unlink()
            for arguments in (("add", "-A"), ("commit", "-qm", "two"), ("tag", "v2.0.0")):
                self.git(source, *arguments)
            with self.worker(source, Path(temporary) / "out", vcs_ref="v2.0.0", prism_layer="workspace") as worker:
                worker._ask()
                with self.assertRaisesRegex(ManifestUpdateError, "Unable to render prism.workspace.yml"):
                    render_template_manifest(worker)


class TemplateMinimumVersionUpdateTests(unittest.TestCase):
    """`prism update` renders the minimum version the way `prism new` did."""

    def git(self, cwd: Path, *arguments: str) -> None:
        subprocess.run(
            ["git", "-c", "user.name=Prism test", "-c", "user.email=test@example.invalid", *arguments],
            cwd=cwd, check=True, capture_output=True, text=True,
        )

    def build(self, temporary: str) -> Path:
        """Return a workspace generated from template version one, with version two tagged."""

        from copier import run_copy

        source = copy_manifest_template_source(temporary)
        self.git(source, "init", "-q")
        self.git(source, "add", ".")
        self.git(source, "commit", "-qm", "version one")
        self.git(source, "tag", "v1.0.0")
        destination = Path(temporary) / "workspace"
        run_copy(
            str(source),
            str(destination),
            data={"project_name": "Update", "project_slug": "update", "auth_methods": ["password"], "_prism_cli_version": __version__},
            vcs_ref="v1.0.0",
            defaults=True,
            unsafe=True,
            quiet=True,
        )
        self.assertEqual(__version__, manifest_data(destination)["min_prism_cli_version"])
        # The CLI records its own version as it writes the manifest.
        write_workspace_manifest(destination, {}, prism_cli_version=__version__)
        manifest_template = source / "template" / "prism.workspace.yml.jinja"
        text = manifest_template.read_bytes().decode("utf-8")
        text, replaced = re.subn(r"^min_prism_cli_version:[^\r\n]*", 'min_prism_cli_version: "99.1.0"', text, count=1, flags=re.MULTILINE)
        self.assertEqual(1, replaced)
        manifest_template.write_bytes(text.encode("utf-8"))
        self.git(source, "add", ".")
        self.git(source, "commit", "-qm", "version two")
        self.git(source, "tag", "v2.0.0")
        return destination

    def test_an_unedited_minimum_advances_with_the_template(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            plan = prepare_manifest_update(self.build(temporary), "v1.0.0")
        self.assertEqual("99.1.0", plan.manifest["min_prism_cli_version"])
        self.assertEqual("v2.0.0", plan.target_label)

    def test_a_workspace_edited_minimum_conflicts_with_a_template_change(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = self.build(temporary)
            data = manifest_data(destination)
            data["min_prism_cli_version"] = "98.0.0"
            write_manifest(destination, data)
            with self.assertRaises(ManifestMergeConflict) as raised:
                prepare_manifest_update(destination, "v1.0.0")
        self.assertEqual(["min_prism_cli_version"], raised.exception.fields)

    def test_the_apps_the_cli_recorded_survive_the_merge(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = self.build(temporary)
            data = manifest_data(destination)
            data["apps"] = apps_from_platforms(["backend"], generation="scaffolded")
            write_manifest(destination, data)
            plan = prepare_manifest_update(destination, "v1.0.0")
        self.assertEqual(["backend"], [app["id"] for app in plan.manifest["apps"]])
        self.assertEqual("scaffolded", plan.manifest["apps"][0]["generation"])


class BaselineCompatibilityTests(unittest.TestCase):
    """Version-1 workspaces read the same as before the application model existed.

    The golden files were captured from the same workspaces with the code that
    had its own manifest parsing in every reader. Volatile values (absolute
    paths, timestamps, UUIDs and digests) are normalized on both sides.
    """

    def check(self, name: str, build) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = build(Path(temporary).resolve() / "ws")
            captured = json.loads(json.dumps(app_model_baseline.capture_workspace(root)))
        expected = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(expected), sorted(captured))
        for section in expected:
            with self.subTest(workspace=name, section=section):
                self.assertEqual(expected[section], captured[section])

    def test_a_generated_workspace_with_all_the_default_platforms_reads_identically(self) -> None:
        self.check("full", app_model_baseline.build_full_workspace)

    def test_a_workflow_only_workspace_with_two_platforms_reads_identically(self) -> None:
        self.check("workflow-only", app_model_baseline.build_workflow_only_workspace)

    def test_the_captures_cover_every_read_surface(self) -> None:
        expected = json.loads((FIXTURES / "full.json").read_text(encoding="utf-8"))
        self.assertEqual({"board", "cli", "inspection", "lint", "status"}, set(expected))
        self.assertEqual({"doctor-workspace", "status-json", "validate", "wiki-lint-json"}, set(expected["cli"]))
        self.assertEqual(["backend", "web", "mobile-android", "mobile-ios"], expected["inspection"]["app_ids"])
        self.assertEqual(["backend", "web", "mobile-android", "mobile-ios"], expected["board"]["identity-app-ids"])
        workflow_only = json.loads((FIXTURES / "workflow-only.json").read_text(encoding="utf-8"))
        self.assertEqual(["backend", "mobile-android"], workflow_only["board"]["identity-app-ids"])
        self.assertEqual({"read_only": False, "reason": None}, expected["board"]["compatibility"])


if __name__ == "__main__":
    unittest.main()
