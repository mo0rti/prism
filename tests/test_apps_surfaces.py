"""Apps in every workspace-level surface, ``prism app``, and workspaces with no apps."""

from __future__ import annotations

import contextlib
import io
import json
import os
from argparse import Namespace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator
import yaml

from prism_cli import cli
from prism_cli.app_cli import IDENTITY_NOTICE, plan_app_add
from prism_cli.app_model import GENERATED_PLATFORM_STACKS, WORKSPACE_REPOSITORY_ID, normalize_manifest
from prism_cli.board_reads import query
from prism_cli.board_service import BoardService
from prism_cli.cli import (
    build_doctor_checks,
    choose_next_doctor_result,
    evaluate_doctor_checks,
    preset_stacks,
)
from prism_cli.presets import PRESETS
from prism_cli.render import format_apps_table
from prism_cli.status import build_status
from prism_cli.wiki_lint import lint_wiki
from prism_cli.workflow_install import apply_install, plan_install
from prism_cli.workspace import MANIFEST_FILE, inspect_workspace, load_workspace
from tests import app_model_baseline
from tests import real_temp  # noqa: F401


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = REPO_ROOT / "prism_cli" / "schemas"
REMOTE = "https://example.com/acme/mobile-apps.git"
BOM = bytes([0xEF, 0xBB, 0xBF])
APP_FIELDS = {"id", "name", "stack", "repository", "path", "audience", "status", "capabilities", "maturity"}


def run_cli(*argv: str) -> tuple[int, str, str]:
    """Run the CLI in process and return its exit code, stdout and stderr."""

    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        try:
            code = cli.main(list(argv))
        except SystemExit as exit_request:
            code = exit_request.code if isinstance(exit_request.code, int) else 1
    return code, stdout.getvalue(), stderr.getvalue()


def run_json(*argv: str, allowed: tuple[int, ...] = (0,)) -> dict:
    code, stdout, stderr = run_cli(*argv)
    if code not in allowed:
        raise AssertionError(f"prism {' '.join(argv)} exited {code}: {stderr}")
    return json.loads(stdout)


def schema(name: str) -> dict:
    return json.loads((SCHEMA_ROOT / name).read_text(encoding="utf-8"))


def manifest_data(root: Path) -> dict:
    return yaml.safe_load((root / MANIFEST_FILE).read_text(encoding="utf-8"))


class WorkspaceCase(unittest.TestCase):
    """A disposable workflow workspace installed through the CLI."""

    install_apps: tuple[str, ...] = ("backend",)

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "ws"
        self.root.mkdir()
        argv = ["workflow", "install", str(self.root), "--name", "Apps workspace", "--apply", "--yes"]
        for app in self.install_apps:
            argv.extend(["--app", app])
        code, _out, err = run_cli(*argv)
        self.assertEqual(0, code, err)

    def manifest_bytes(self) -> bytes:
        return (self.root / MANIFEST_FILE).read_bytes()

    def add(self, *args: str, apply: bool = False) -> tuple[int, str, str]:
        argv = ["app", "add", *args, str(self.root)]
        if apply:
            argv.extend(["--apply", "--yes"])
        return run_cli(*argv)


class StatusAppsShapeTests(unittest.TestCase):
    def test_status_json_reports_apps_and_repositories_and_validates_against_the_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = app_model_baseline.build_full_workspace(Path(temporary).resolve() / "ws")
            envelope = run_json("status", str(root), "--json")
        Draft202012Validator(schema("status-v1.json")).validate(envelope)
        workspace = envelope["workspace"]
        self.assertNotIn("platforms", workspace)
        self.assertNotIn("platform_maturity", workspace)
        self.assertEqual(["backend", "web-user-app", "web-admin-portal", "mobile-android", "mobile-ios"], [app["id"] for app in workspace["apps"]])
        for app in workspace["apps"]:
            self.assertEqual(APP_FIELDS, set(app))
        backend, web_user, _admin, android, ios = workspace["apps"]
        self.assertEqual(
            {
                "id": "backend",
                "name": "Spring Boot Backend",
                "stack": "spring-backend",
                "repository": "workspace",
                "path": "backend",
                "audience": None,
                "status": "active",
                "capabilities": {"has-ui": False, "serves-api": True},
                "maturity": {"level": "baseline", "caveat": ""},
            },
            backend,
        )
        self.assertEqual({"has-ui": True, "serves-api": False}, web_user["capabilities"])
        self.assertEqual("provisional", web_user["maturity"]["level"])
        self.assertEqual(("android-compose", "mobile-android"), (android["stack"], android["path"]))
        self.assertEqual("experimental", ios["maturity"]["level"])
        self.assertEqual([{"id": "workspace", "remote": None}], workspace["repositories"])

    def test_the_envelope_and_the_other_read_schemas_validate_the_app_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = app_model_baseline.build_workflow_only_workspace(Path(temporary).resolve() / "ws")
            lint = run_json("wiki", "lint", str(root), "--json", allowed=(0, 3))
            blockers = run_json("wiki", "blockers", str(root), "--json", allowed=(0, 3))
            platform = run_json("wiki", "platform", "backend", str(root), "--json", allowed=(0, 3))
        for name, envelope in (("wiki-lint-v1.json", lint), ("envelope-v1.json", blockers), ("wiki-query-v1.json", platform)):
            with self.subTest(schema=name):
                Draft202012Validator(schema(name)).validate(envelope)
                self.assertNotIn("platforms", envelope["workspace"])
                self.assertEqual(["backend", "mobile-android"], [app["id"] for app in envelope["workspace"]["apps"]])

    def test_the_schemas_reject_the_old_platforms_shape_and_a_malformed_app(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = app_model_baseline.build_workflow_only_workspace(Path(temporary).resolve() / "ws")
            envelope = run_json("status", str(root), "--json")
        validator = Draft202012Validator(schema("status-v1.json"))
        old_shape = json.loads(json.dumps(envelope))
        del old_shape["workspace"]["apps"]
        old_shape["workspace"]["platforms"] = ["backend"]
        self.assertFalse(validator.is_valid(old_shape))
        no_repositories = json.loads(json.dumps(envelope))
        del no_repositories["workspace"]["repositories"]
        self.assertFalse(validator.is_valid(no_repositories))
        bad_capability = json.loads(json.dumps(envelope))
        bad_capability["workspace"]["apps"][0]["capabilities"]["has-ui"] = "maybe"
        self.assertFalse(validator.is_valid(bad_capability))
        missing_field = json.loads(json.dumps(envelope))
        del missing_field["workspace"]["apps"][0]["maturity"]
        self.assertFalse(validator.is_valid(missing_field))

    def test_an_external_repository_reports_its_checkout_but_never_the_local_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            root = base / "ws"
            root.mkdir()
            self.assertEqual(0, run_cli("workflow", "install", str(root), "--name", "Two repos", "--app", "backend", "--apply", "--yes")[0])
            self.assertEqual(0, run_cli("app", "add", "partner-android", "--stack", "android-compose", "--repository", "mobile-apps", "--remote", REMOTE, "--path", "apps/partner", str(root), "--apply", "--yes")[0])
            unresolved = run_json("status", str(root), "--json")
            checkout = base / "mobile-apps-checkout"
            checkout.mkdir()
            (root / "prism.local.yml").write_text(yaml.safe_dump({"repositories": {"mobile-apps": str(checkout)}}), encoding="utf-8")
            resolved = run_json("status", str(root), "--json")
        external = {"id": "mobile-apps", "remote": REMOTE}
        self.assertEqual([{"id": "workspace", "remote": None}, {**external, "checkout": "unresolved"}], unresolved["workspace"]["repositories"])
        self.assertEqual([{"id": "workspace", "remote": None}, {**external, "checkout": "resolved"}], resolved["workspace"]["repositories"])
        self.assertNotIn(str(checkout), json.dumps(resolved))
        self.assertNotIn(checkout.as_posix(), json.dumps(resolved))
        Draft202012Validator(schema("status-v1.json")).validate(resolved)

    def test_human_status_shows_an_apps_table_and_the_checkout_line(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            root = base / "ws"
            root.mkdir()
            self.assertEqual(0, run_cli("workflow", "install", str(root), "--name", "Two repos", "--app", "backend", "--apply", "--yes")[0])
            self.assertEqual(0, run_cli("app", "add", "partner-android", "--stack", "android-compose", "--repository", "mobile-apps", "--remote", REMOTE, "--path", "apps/partner", str(root), "--apply", "--yes")[0])
            _code, unresolved, _err = run_cli("status", str(root))
            checkout = base / "checkout"
            checkout.mkdir()
            (root / "prism.local.yml").write_text(yaml.safe_dump({"repositories": {"mobile-apps": str(checkout)}}), encoding="utf-8")
            _code, resolved, _err = run_cli("status", str(root))
        for text in (unresolved, resolved):
            self.assertIn("Apps: backend, partner-android", text)
            header = next(line for line in text.splitlines() if line.startswith("ID"))
            self.assertEqual(["ID", "Name", "Stack", "Repository", "Path", "Status", "Maturity"], header.split())
            self.assertRegex(text, r"backend\s+Spring Boot Backend\s+spring-backend\s+workspace\s+backend\s+active\s+-")
            self.assertRegex(text, r"partner-android\s+partner-android\s+android-compose\s+mobile-apps\s+apps/partner\s+active\s+-")
        self.assertIn("Repository mobile-apps: checkout unresolved (add it to prism.local.yml)", unresolved)
        self.assertIn("Repository mobile-apps: checkout resolved", resolved)
        self.assertNotIn(str(checkout), resolved)
        self.assertNotIn("Platforms:", unresolved)

    def test_the_apps_table_aligns_columns_and_shows_maturity_levels(self) -> None:
        rows = format_apps_table(
            [
                {"id": "a", "name": "Alpha app", "stack": "other", "repository": "workspace", "path": "a", "status": "active", "maturity": {"level": "baseline"}},
                {"id": "long-id", "name": "B", "stack": "nextjs-web", "repository": "r", "path": "apps/b", "status": "retired", "maturity": None},
            ]
        )
        self.assertEqual(3, len(rows))
        self.assertEqual(["ID", "Name", "Stack", "Repository", "Path", "Status", "Maturity"], rows[0].split())
        self.assertEqual(["a", "Alpha", "app", "other", "workspace", "a", "active", "baseline"], rows[1].split())
        self.assertEqual("retired", rows[2].split()[-2])
        self.assertEqual("-", rows[2].split()[-1])
        self.assertEqual(rows[0].index("Stack"), rows[1].index("other"))
        self.assertEqual(rows[0].index("Stack"), rows[2].index("nextjs-web"))


class AppListTests(WorkspaceCase):
    def test_list_json_reports_the_same_apps_and_repositories_as_status(self) -> None:
        self.assertEqual(0, self.add("partner-android", "--stack", "android-compose", "--repository", "mobile-apps", "--remote", REMOTE, "--path", "apps/partner", apply=True)[0])
        listed = run_json("app", "list", str(self.root), "--json")
        status = run_json("status", str(self.root), "--json")
        self.assertEqual(status["workspace"]["apps"], listed["apps"])
        self.assertEqual(status["workspace"]["repositories"], listed["repositories"])
        self.assertEqual(["backend", "partner-android"], [app["id"] for app in listed["apps"]])
        self.assertEqual(1, listed["schema_version"])
        self.assertEqual("app list", listed["command"])
        self.assertEqual(["external-repository-unresolved"], [item["code"] for item in listed["diagnostics"]])

    def test_list_shows_the_table_and_the_checkout_line(self) -> None:
        self.assertEqual(0, self.add("partner-android", "--stack", "android-compose", "--repository", "mobile-apps", "--remote", REMOTE, "--path", "apps/partner", apply=True)[0])
        code, out, _err = run_cli("app", "list", str(self.root))
        self.assertEqual(0, code)
        self.assertRegex(out, r"backend\s+Spring Boot Backend\s+spring-backend\s+workspace\s+backend\s+active")
        self.assertRegex(out, r"partner-android\s+partner-android\s+android-compose\s+mobile-apps\s+apps/partner\s+active")
        self.assertIn("Repository mobile-apps: checkout unresolved", out)

    def test_list_with_no_apps_says_how_to_add_one(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "ws"
            root.mkdir()
            self.assertEqual(0, run_cli("workflow", "install", str(root), "--name", "None", "--apply", "--yes")[0])
            code, out, _err = run_cli("app", "list", str(root))
            listed = run_json("app", "list", str(root), "--json")
        self.assertEqual(0, code)
        self.assertIn("No apps declared. Register one with `prism app add <id> --stack <stack>`.", out)
        self.assertEqual([], listed["apps"])
        self.assertEqual([{"id": "workspace", "remote": None}], listed["repositories"])

    def test_list_without_a_usable_manifest_fails_and_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            code, _out, err = run_cli("app", "list", str(root))
            self.assertEqual(3, code)
            self.assertIn("No usable prism.workspace.yml", err)
            self.assertEqual([], list(root.iterdir()))


class AppAddTests(WorkspaceCase):
    def test_without_apply_it_plans_the_manifest_change_and_writes_nothing(self) -> None:
        before = self.manifest_bytes()
        code, out, err = self.add("customer-android", "--stack", "android-compose", "--path", "apps/customer")
        self.assertEqual(0, code, err)
        self.assertEqual(before, self.manifest_bytes())
        self.assertIn("+- id: customer-android", out)
        self.assertIn("+  stack: android-compose", out)
        self.assertIn("+  path: apps/customer", out)
        self.assertIn("Warning: Path `apps/customer` does not exist yet", out)
        self.assertIn(IDENTITY_NOTICE, out)
        self.assertIn("Preview only. Run again with --apply to confirm this change.", out)

    def test_the_plan_exits_with_the_same_code_as_a_workflow_install_plan(self) -> None:
        install_code, _out, _err = run_cli("workflow", "upgrade", str(self.root))
        add_code, _out, _err = self.add("customer-android", "--stack", "android-compose")
        self.assertEqual(install_code, add_code)
        self.assertEqual(0, add_code)

    def test_apply_with_yes_writes_the_app_and_keeps_every_unrelated_field(self) -> None:
        before = manifest_data(self.root)
        code, out, err = self.add(
            "customer-android",
            "--stack",
            "android-compose",
            "--name",
            "Customer app",
            "--audience",
            "B2C",
            "--path",
            "apps/customer",
            apply=True,
        )
        self.assertEqual(0, code, err)
        self.assertIn("Registered app `customer-android`", out)
        self.assertIn(IDENTITY_NOTICE, out)
        after = manifest_data(self.root)
        self.assertEqual({key: value for key, value in before.items() if key != "apps"}, {key: value for key, value in after.items() if key != "apps"})
        self.assertEqual(before["apps"], after["apps"][:1])
        self.assertEqual(
            {
                "id": "customer-android",
                "name": "Customer app",
                "stack": "android-compose",
                "repository": "workspace",
                "path": "apps/customer",
                "audience": "B2C",
            },
            after["apps"][1],
        )
        model, diagnostics = normalize_manifest(after, path=Path(MANIFEST_FILE))
        self.assertEqual([], diagnostics)
        self.assertEqual(["backend", "customer-android"], model.active_app_ids)
        self.assertEqual([], [path.name for path in self.root.iterdir() if path.name.endswith(".prism-tmp")])
        self.assertFalse((self.root / "apps").exists(), "registering an app never generates code")

    def test_the_default_name_and_path_come_from_the_id_and_the_stack(self) -> None:
        self.assertEqual(0, self.add("mobile-android", "--stack", "android-compose", apply=True)[0])
        self.assertEqual(0, self.add("reports", "--stack", "nextjs-web", apply=True)[0])
        apps = {item["id"]: item for item in manifest_data(self.root)["apps"]}
        self.assertEqual(("mobile-android", "mobile-android"), (apps["mobile-android"]["path"], apps["mobile-android"]["name"]))
        self.assertEqual(("reports", "reports"), (apps["reports"]["path"], apps["reports"]["name"]))

    def test_an_existing_in_workspace_path_is_not_a_warning(self) -> None:
        (self.root / "apps" / "customer").mkdir(parents=True)
        code, out, _err = self.add("customer-android", "--stack", "android-compose", "--path", "apps/customer")
        self.assertEqual(0, code)
        self.assertNotIn("does not exist yet", out)

    def test_a_missing_path_is_a_warning_in_the_json_plan_and_not_an_error(self) -> None:
        plan = run_json("app", "add", "customer-android", "--stack", "android-compose", "--path", "apps/customer", str(self.root), "--json")
        self.assertEqual([], plan["conflicts"])
        self.assertEqual(1, len(plan["warnings"]))
        self.assertIn("does not exist yet", plan["warnings"][0])
        self.assertTrue(plan["board_identity_changed"])
        self.assertEqual(IDENTITY_NOTICE, plan["notice"])
        self.assertEqual("customer-android", plan["app"]["id"])

    def test_capability_flags_are_written_as_overrides_and_read_back(self) -> None:
        self.assertEqual(0, self.add("kiosk", "--stack", "android-compose", "--has-ui", "false", "--serves-api", "unknown", apply=True)[0])
        entry = manifest_data(self.root)["apps"][1]
        self.assertEqual({"has-ui": False, "serves-api": "unknown"}, entry["capabilities"])
        apps = {app["id"]: app for app in run_json("app", "list", str(self.root), "--json")["apps"]}
        self.assertEqual({"has-ui": False, "serves-api": "unknown"}, apps["kiosk"]["capabilities"])

    def test_an_external_repository_with_a_remote_is_declared_with_the_app(self) -> None:
        code, out, err = self.add("partner-android", "--stack", "android-compose", "--repository", "mobile-apps", "--remote", REMOTE, "--path", "apps/partner")
        self.assertEqual(0, code, err)
        self.assertIn(f"+  remote: {REMOTE}", out)
        self.assertIn("External repository `mobile-apps` has no checkout on this machine", out)
        self.assertNotIn("does not exist yet", out, "an external app's path is not looked up on this machine")
        self.assertEqual(0, self.add("partner-android", "--stack", "android-compose", "--repository", "mobile-apps", "--remote", REMOTE, "--path", "apps/partner", apply=True)[0])
        data = manifest_data(self.root)
        self.assertEqual([{"id": "mobile-apps", "remote": REMOTE}], data["repositories"])
        self.assertEqual("mobile-apps", data["apps"][1]["repository"])
        self.assertEqual([], [item for item in load_workspace(self.root).diagnostics if item.severity == "error"])

    def test_a_second_app_in_an_already_declared_repository_needs_no_remote(self) -> None:
        self.assertEqual(0, self.add("partner-android", "--stack", "android-compose", "--repository", "mobile-apps", "--remote", REMOTE, "--path", "apps/partner", apply=True)[0])
        self.assertEqual(0, self.add("partner-ios", "--stack", "ios-swiftui", "--repository", "mobile-apps", "--path", "apps/ios", apply=True)[0])
        data = manifest_data(self.root)
        self.assertEqual(1, len(data["repositories"]))
        self.assertEqual(["backend", "partner-android", "partner-ios"], [item["id"] for item in data["apps"]])

    def assert_refused(self, args: tuple[str, ...], expected: str) -> None:
        before = self.manifest_bytes()
        code, _out, err = self.add(*args)
        self.assertEqual(3, code, err)
        self.assertIn(expected, err)
        applied_code, _out, applied_err = self.add(*args, apply=True)
        self.assertEqual(3, applied_code, applied_err)
        self.assertEqual(before, self.manifest_bytes(), "nothing is written on an error")
        self.assertEqual([], [path.name for path in self.root.iterdir() if path.name.endswith(".prism-tmp")])

    def test_every_validation_error_writes_nothing(self) -> None:
        cases = {
            "duplicate id": (("backend", "--stack", "spring-backend", "--path", "other"), "duplicate-app-id"),
            "invalid id": (("Customer", "--stack", "android-compose"), "invalid-app-id"),
            "shared path": (("second-backend", "--stack", "spring-backend"), "app-path-conflict"),
            "overlapping path": (("nested", "--stack", "android-compose", "--path", "backend/nested"), "app-path-conflict"),
            "absolute path": (("abs", "--stack", "android-compose", "--path", "/srv/abs"), "invalid-app-path"),
            "parent path": (("up", "--stack", "android-compose", "--path", "../up"), "invalid-app-path"),
            "backslash path": (("bs", "--stack", "android-compose", "--path", "apps\\bs"), "invalid-app-path"),
            "dot path in the workspace": (("dot", "--stack", "android-compose", "--path", "."), "invalid-app-path"),
            "remote without repository": (("r", "--stack", "android-compose", "--remote", REMOTE), "--remote needs --repository"),
            "remote for a declared repository": (("r", "--stack", "android-compose", "--repository", "workspace", "--remote", REMOTE), "--remote is allowed only for a repository that is not declared yet"),
            "undeclared repository without a remote": (("r", "--stack", "android-compose", "--repository", "mobile-apps"), "Repository `mobile-apps` is not declared; add --remote URL"),
            "local path as remote": (("r", "--stack", "android-compose", "--repository", "mobile-apps", "--remote", "/srv/git/mobile-apps"), "invalid-repository-remote"),
            "file remote": (("r", "--stack", "android-compose", "--repository", "mobile-apps", "--remote", "file:///srv/git/mobile-apps"), "invalid-repository-remote"),
            "invalid repository id": (("r", "--stack", "android-compose", "--repository", "Mobile Apps", "--remote", REMOTE), "invalid-repository"),
            "blank name": (("r", "--stack", "android-compose", "--name", " "), "invalid-app-declaration"),
        }
        for label, (args, expected) in cases.items():
            with self.subTest(case=label):
                self.assert_refused(args, expected)

    def test_a_retired_app_id_is_never_reused(self) -> None:
        data = manifest_data(self.root)
        data["apps"][0]["status"] = "retired"
        (self.root / MANIFEST_FILE).write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        self.assert_refused(("backend", "--stack", "spring-backend", "--path", "api"), "duplicate-app-id")

    def test_an_unknown_stack_is_refused_by_the_parser(self) -> None:
        before = self.manifest_bytes()
        code, _out, err = self.add("x", "--stack", "cobol")
        self.assertEqual(2, code)
        self.assertIn("--stack", err)
        self.assertEqual(before, self.manifest_bytes())

    def test_the_stack_option_is_required(self) -> None:
        code, _out, err = run_cli("app", "add", "x", str(self.root))
        self.assertEqual(2, code)
        self.assertIn("--stack", err)

    def test_an_other_app_must_declare_both_capabilities(self) -> None:
        self.assert_refused(("tool", "--stack", "other"), "needs --has-ui and --serves-api")
        self.assert_refused(("tool", "--stack", "other", "--has-ui", "true"), "needs --serves-api")
        self.assert_refused(("tool", "--stack", "other", "--serves-api", "false"), "needs --has-ui")
        self.assertEqual(0, self.add("tool", "--stack", "other", "--has-ui", "false", "--serves-api", "unknown", apply=True)[0])
        entry = manifest_data(self.root)["apps"][1]
        self.assertEqual({"has-ui": False, "serves-api": "unknown"}, entry["capabilities"])
        self.assertEqual("tool", entry["path"], "an `other` app has no default path, so its ID is used")

    def test_apply_without_yes_needs_a_terminal_and_writes_nothing(self) -> None:
        before = self.manifest_bytes()
        with patch("sys.stdin.isatty", return_value=False):
            code, _out, err = run_cli("app", "add", "customer-android", "--stack", "android-compose", str(self.root), "--apply")
        self.assertEqual(2, code)
        self.assertIn("Applying non-interactively requires --apply --yes", err)
        self.assertEqual(before, self.manifest_bytes())

    def test_an_interactive_confirmation_applies_or_cancels(self) -> None:
        before = self.manifest_bytes()
        for answer, expected_apps in (("n", ["backend"]), ("y", ["backend", "customer-android"])):
            with self.subTest(answer=answer), patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=answer):
                code, out, _err = run_cli("app", "add", "customer-android", "--stack", "android-compose", str(self.root), "--apply")
            self.assertEqual(0, code)
            self.assertEqual(expected_apps, [item["id"] for item in manifest_data(self.root)["apps"]])
            if answer == "n":
                self.assertIn("Canceled; no files changed.", out)
                self.assertEqual(before, self.manifest_bytes())

    def test_apply_with_json_returns_a_receipt_with_the_plan(self) -> None:
        receipt = run_json("app", "add", "customer-android", "--stack", "android-compose", str(self.root), "--apply", "--yes", "--json")
        self.assertEqual("applied", receipt["status"])
        self.assertEqual("customer-android", receipt["app"]["id"])
        self.assertEqual(IDENTITY_NOTICE, receipt["notice"])
        self.assertEqual([], receipt["plan"]["conflicts"])
        self.assertEqual(["backend", "customer-android"], [item["id"] for item in manifest_data(self.root)["apps"]])

    def test_a_manifest_that_changed_after_the_preview_is_not_overwritten(self) -> None:
        from prism_cli.app_cli import apply_app_add

        plan = plan_app_add(self.root, "customer-android", "android-compose")
        self.assertEqual([], plan["conflicts"])
        edited = self.manifest_bytes() + b"# edited after preview\n"
        (self.root / MANIFEST_FILE).write_bytes(edited)
        receipt = apply_app_add(self.root, plan)
        self.assertEqual("conflict", receipt["status"])
        self.assertIn("changed after preview", receipt["conflicts"][0])
        self.assertEqual(edited, self.manifest_bytes())

    def test_a_symlinked_manifest_is_rejected(self) -> None:
        real = self.root / "real-manifest.yml"
        manifest = self.root / MANIFEST_FILE
        manifest.replace(real)
        try:
            os.symlink(real, manifest)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlinks are unavailable here: {exc}")
        before = real.read_bytes()
        code, _out, err = self.add("customer-android", "--stack", "android-compose", apply=True)
        self.assertEqual(3, code)
        self.assertIn("symlink", err)
        self.assertEqual(before, real.read_bytes())
        self.assertTrue(manifest.is_symlink())

    def test_a_manifest_with_a_byte_order_mark_keeps_it(self) -> None:
        manifest = self.root / MANIFEST_FILE
        manifest.write_bytes(BOM + manifest.read_bytes())
        self.assertEqual(0, self.add("customer-android", "--stack", "android-compose", apply=True)[0])
        written = manifest.read_bytes()
        self.assertTrue(written.startswith(BOM))
        self.assertEqual(["backend", "customer-android"], [item["id"] for item in yaml.safe_load(written.decode("utf-8-sig"))["apps"]])

    def test_a_workspace_without_a_manifest_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            code, _out, err = run_cli("app", "add", "x", "--stack", "android-compose", str(root), "--apply", "--yes")
            self.assertEqual(3, code)
            self.assertIn("prism.workspace.yml is missing", err)
            self.assertEqual([], list(root.iterdir()))

    def test_registering_an_app_changes_the_board_identity_of_a_running_service(self) -> None:
        service = BoardService(self.root).start()
        self.addCleanup(service.close)
        actor = service.authenticate(service.create_participant("Writer", "human", writable=True)["token"])
        self.assertEqual(0, self.add("customer-android", "--stack", "android-compose", apply=True)[0])
        from prism_cli.board_service import BoardError

        with self.assertRaises(BoardError) as error:
            service.discover(actor)
        self.assertEqual("workspace_identity_changed", error.exception.code)
        service.close()
        restarted = BoardService(self.root).start()
        self.addCleanup(restarted.close)
        restarted_actor = restarted.authenticate(restarted.create_participant("Writer 2", "human", writable=True)["token"])
        self.assertEqual(["backend", "customer-android"], [app["id"] for app in restarted.discover(restarted_actor)["board"]["apps"]])


class WorkflowAppOptionTests(unittest.TestCase):
    def new_root(self) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name) / "ws"
        root.mkdir()
        return root

    def test_app_registers_the_named_generated_apps(self) -> None:
        root = self.new_root()
        code, _out, err = run_cli("workflow", "install", str(root), "--name", "Two", "--app", "web-user-app", "--app", "backend", "--apply", "--yes")
        self.assertEqual(0, code, err)
        self.assertEqual(["backend", "web-user-app"], [item["id"] for item in manifest_data(root)["apps"]])

    def test_the_platform_option_is_gone(self) -> None:
        root = self.new_root()
        for command in ("install", "upgrade"):
            with self.subTest(command=command):
                code, _out, err = run_cli("workflow", command, str(root), "--name", "Old", "--platform", "backend")
                self.assertEqual(2, code)
                self.assertIn("unrecognized arguments: --platform", err)
        self.assertEqual([], list(root.iterdir()))

    def test_only_the_five_generated_app_ids_are_accepted(self) -> None:
        root = self.new_root()
        code, _out, err = run_cli("workflow", "install", str(root), "--name", "Bad", "--app", "desktop")
        self.assertEqual(2, code)
        for app_id in ("backend", "web-user-app", "web-admin-portal", "mobile-android", "mobile-ios"):
            self.assertIn(app_id, err)

    def test_a_new_workspace_without_app_has_no_apps(self) -> None:
        root = self.new_root()
        code, out, err = run_cli("workflow", "install", str(root), "--name", "No apps", "--json")
        self.assertEqual(0, code, err)
        plan = json.loads(out)
        self.assertEqual([], plan["conflicts"])
        self.assertEqual([], plan["apps"])
        self.assertNotIn("platforms", plan)
        self.assertEqual(0, run_cli("workflow", "install", str(root), "--name", "No apps", "--apply", "--yes")[0])
        data = manifest_data(root)
        self.assertEqual([], data["apps"])
        self.assertEqual(2, data["schema_version"])
        self.assertEqual("workflow", data["workflow"]["mode"])

    def test_the_plan_and_receipt_report_apps(self) -> None:
        root = self.new_root()
        plan = plan_install(root, name="Plan", platforms=["backend", "mobile-ios"])
        self.assertEqual(["backend", "mobile-ios"], plan["apps"])
        receipt = apply_install(root, plan)
        self.assertEqual(["backend", "mobile-ios"], receipt["apps"])
        self.assertNotIn("platforms", receipt)

    def test_the_launcher_workflow_action_passes_app(self) -> None:
        captured: list[list[str]] = []

        class Parsed:
            func = staticmethod(lambda parsed: 0)

        parser = Namespace(parse_args=lambda command: captured.append(command) or Parsed())
        with patch("prism_cli.cli.prompt_text", return_value="Launcher"), patch("prism_cli.cli.prompt_multiselect", return_value=["backend", "mobile-ios"]):
            self.assertEqual(0, cli.dispatch_home_action("workflow", parser))
        self.assertEqual([["workflow", "install", "--name", "Launcher", "--apply", "--app", "backend", "--app", "mobile-ios"]], captured)
        captured.clear()
        with patch("prism_cli.cli.prompt_text", return_value="Launcher"), patch("prism_cli.cli.prompt_multiselect", return_value=[]):
            cli.dispatch_home_action("workflow", parser)
        self.assertEqual([["workflow", "install", "--name", "Launcher", "--apply"]], captured)


class DoctorStackTests(unittest.TestCase):
    """Doctor decides relevance from stacks and keeps today's results for the five generated apps."""

    # What each stack-aware check was declared with before it was keyed by stack.
    LEGACY_PLATFORMS = {"Docker": ("backend",), "JDK": ("backend", "mobile-android"), "Xcode CLI": ("mobile-ios",)}
    PLATFORMS = ("backend", "web-user-app", "web-admin-portal", "mobile-android", "mobile-ios")

    def subsets(self):
        for mask in range(1 << len(self.PLATFORMS)):
            yield {platform for index, platform in enumerate(self.PLATFORMS) if mask >> index & 1}

    def legacy_labels(self, checks, target_platforms: set[str]) -> list[str]:
        return [
            check.label
            for check in checks
            if not (self.LEGACY_PLATFORMS.get(check.label) and target_platforms and not set(self.LEGACY_PLATFORMS[check.label]).intersection(target_platforms))
        ]

    def test_checks_are_keyed_by_stack_ids_from_the_registry(self) -> None:
        from prism_cli.app_model import STACKS

        by_label = {check.label: check.stacks for check in build_doctor_checks(incubation_mode=True) if check.stacks}
        self.assertEqual({"Docker": ("spring-backend",), "JDK": ("spring-backend", "android-compose"), "Xcode CLI": ("ios-swiftui",)}, by_label)
        for stacks in by_label.values():
            self.assertTrue(set(stacks) <= set(STACKS))
        self.assertFalse(hasattr(build_doctor_checks(incubation_mode=True)[0], "platforms"))

    @patch("prism_cli.cli.shutil.which", return_value=None)
    def test_relevance_by_stack_equals_relevance_by_platform_for_every_selection_of_the_five_apps(self, _which: object) -> None:
        checks = build_doctor_checks(incubation_mode=True)
        for target in self.subsets():
            stacks = {GENERATED_PLATFORM_STACKS[platform] for platform in target}
            with self.subTest(apps=sorted(target)):
                results = evaluate_doctor_checks(checks, "Windows", stacks)
                self.assertEqual(self.legacy_labels(checks, target), [result.check.label for result in results])
                missing = [result for result in results if result.status == "missing"]
                legacy_next = self.legacy_next(missing, target)
                new_next = choose_next_doctor_result(results, stacks)
                self.assertEqual(legacy_next, new_next.check.label if new_next else None)

    def legacy_next(self, missing, target_platforms: set[str]) -> str | None:
        if not missing:
            return None

        def key(result):
            relevant = bool(target_platforms) and bool(set(self.LEGACY_PLATFORMS.get(result.check.label, ())).intersection(target_platforms))
            category = 0 if result.check.blocking else 1 if relevant else 2 if result.check.category == "workflow" else 3
            return (category, 0 if relevant else 1, result.check.label)

        return sorted(missing, key=key)[0].check.label

    def test_a_preset_uses_the_stacks_of_its_platforms(self) -> None:
        for preset in PRESETS:
            with self.subTest(preset=preset.slug):
                platforms = preset.answers.get("platforms", [])
                self.assertEqual({GENERATED_PLATFORM_STACKS[item] for item in platforms}, preset_stacks(preset))

    def test_with_no_target_stacks_every_check_applies(self) -> None:
        checks = build_doctor_checks(incubation_mode=True)
        with patch("prism_cli.cli.shutil.which", return_value=None):
            results = evaluate_doctor_checks(checks, "Windows", set())
        self.assertEqual([check.label for check in checks], [result.check.label for result in results])

    def test_only_the_active_apps_in_this_repository_set_the_workspace_stacks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "ws"
            root.mkdir()
            self.assertEqual(0, run_cli("workflow", "install", str(root), "--name", "Stacks", "--app", "backend", "--apply", "--yes")[0])
            self.assertEqual({"spring-backend"}, build_status(root).workspace_stacks)
            self.assertEqual(0, run_cli("app", "add", "partner-ios", "--stack", "ios-swiftui", "--repository", "apple", "--remote", REMOTE, str(root), "--apply", "--yes")[0])
            self.assertEqual({"spring-backend"}, build_status(root).workspace_stacks, "an external app's tools are not this machine's concern")
            self.assertEqual(0, run_cli("app", "add", "tablet", "--stack", "android-compose", str(root), "--apply", "--yes")[0])
            self.assertEqual({"spring-backend", "android-compose"}, build_status(root).workspace_stacks)
            data = manifest_data(root)
            data["apps"][0]["status"] = "retired"
            (root / MANIFEST_FILE).write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
            self.assertEqual({"android-compose"}, build_status(root).workspace_stacks, "a retired app needs no tools")

    @patch("prism_cli.cli.shutil.which", return_value=None)
    def test_doctor_for_a_workspace_lists_the_apps_and_checks_only_their_tools(self, _which: object) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "ws"
            root.mkdir()
            self.assertEqual(0, run_cli("workflow", "install", str(root), "--name", "Doctor", "--app", "backend", "--apply", "--yes")[0])
            # A workflow-only workspace checks Python only, so use the full checks with the stacks the apps give.
            status = build_status(root)
        checks = build_doctor_checks(incubation_mode=True)
        labels = [result.check.label for result in evaluate_doctor_checks(checks, "Windows", status.workspace_stacks)]
        self.assertIn("Docker", labels)
        self.assertIn("JDK", labels)
        self.assertNotIn("Xcode CLI", labels)

    def test_doctor_workspace_output_says_apps_and_lists_their_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "ws"
            root.mkdir()
            self.assertEqual(0, run_cli("workflow", "install", str(root), "--name", "Doctor", "--app", "backend", "--app", "mobile-android", "--apply", "--yes")[0])
            _code, out, _err = run_cli("doctor", "--workspace", str(root))
        self.assertIn("Apps: backend, mobile-android", out)
        self.assertRegex(out, r"mobile-android\s+Android \(Kotlin/Compose\)\s+android-compose")
        self.assertNotIn("Platforms:", out)


class ZeroAppWorkspaceTests(unittest.TestCase):
    """A workflow workspace may declare no apps: it loads, lints, reports status and is served writable."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "ws"
        self.root.mkdir()
        self.assertEqual(0, run_cli("workflow", "install", str(self.root), "--name", "No apps", "--apply", "--yes")[0])

    def test_it_loads_lints_and_reports_status_without_findings(self) -> None:
        result = load_workspace(self.root)
        self.assertEqual([], result.diagnostics)
        self.assertEqual((), result.manifest.apps)
        inspection = inspect_workspace(self.root)
        self.assertEqual([], inspection.apps)
        self.assertEqual([], [item for item in inspection.contract_diagnostics if item.severity == "error"])
        self.assertEqual(0, lint_wiki(self.root).error_count)
        envelope = run_json("status", str(self.root), "--json")
        Draft202012Validator(schema("status-v1.json")).validate(envelope)
        self.assertEqual([], envelope["workspace"]["apps"])
        self.assertEqual("high", envelope["confidence"])
        code, out, _err = run_cli("status", str(self.root))
        self.assertEqual(0, code)
        self.assertIn("Apps: none declared", out)
        self.assertEqual(0, run_cli("wiki", "lint", str(self.root))[0])

    def test_the_board_serves_it_writable_and_discover_lists_no_apps(self) -> None:
        service = BoardService(self.root).start()
        self.addCleanup(service.close)
        self.assertEqual({"read_only": False, "reason": None}, service.compatibility())
        actor = service.authenticate(service.create_participant("Writer", "human", writable=True)["token"])
        self.assertTrue(actor.writable)
        self.assertEqual([], service.discover(actor)["board"]["apps"])
        code, out, _err = run_cli("board", "status", str(self.root))
        self.assertEqual(0, code)
        self.assertTrue(json.loads(out)["compatible"])

    def test_no_active_app_is_not_a_reason_for_the_board_to_be_read_only(self) -> None:
        data = manifest_data(self.root)
        data["apps"] = [{"id": "backend", "stack": "spring-backend", "status": "retired"}]
        (self.root / MANIFEST_FILE).write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        service = BoardService(self.root)
        self.addCleanup(service.close)
        self.assertEqual({"read_only": False, "reason": None}, service.compatibility())
        self.assertEqual([], service._platforms)

    def test_the_old_read_only_reason_is_gone(self) -> None:
        service = BoardService(self.root)
        self.addCleanup(service.close)
        self.assertNotIn("nonempty app scope", json.dumps(service.compatibility()))
        data = manifest_data(self.root)
        data["project"]["name"] = " "
        (self.root / MANIFEST_FILE).write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        blank = BoardService(self.root)
        self.addCleanup(blank.close)
        self.assertEqual({"read_only": True, "reason": "A project name is required."}, blank.compatibility())

    def write_specified_feature(self) -> None:
        (self.root / "knowledge" / "wiki" / "SETTINGS.md").write_text("---\nwiki-stale-after-days: 36500\n---\n", encoding="utf-8")
        relative, page = app_model_baseline._feature("F-001", "Outcome capture", "specified", "po", ["backend"])
        (self.root / relative).parent.mkdir(parents=True, exist_ok=True)
        (self.root / relative).write_text(page, encoding="utf-8")
        (self.root / "knowledge" / "wiki" / "index.md").write_text(
            "# Feature Status Board\n\n| ID | Feature | Status | Owner | Board Review | Introduced |\n"
            "|----|---------|--------|-------|--------------|------------|\n"
            "| F-001 | Outcome capture | specified | po | not-needed | 2026-09-22 |\n",
            encoding="utf-8",
        )

    def test_a_scoped_lifecycle_operation_fails_at_its_gate_and_names_the_missing_apps(self) -> None:
        self.write_specified_feature()
        service = BoardService(self.root).start()
        self.addCleanup(service.close)
        actor = service.authenticate(service.create_participant("Writer", "human", writable=True)["token"])
        facts = query(service, actor, "transition-preflight", "F-001", "po-handoff")["facts"]["transition"]
        checks = {check["code"]: check for check in facts["checks"]}
        self.assertEqual("pass", checks["workspace-identity"]["status"], "the identity gate no longer needs an app")
        scope = checks["platform-scope"]
        self.assertEqual("blocked", scope["status"])
        self.assertIn("backend", scope["message"])
        self.assertIn("This workspace declares no apps; register them with `prism app add`.", scope["message"])
        self.assertNotEqual("ready", facts["classification"])
        preview = service.preview_transition(actor, "F-001", "po-handoff", {"semantic_review_acknowledged": True})
        self.assertFalse(preview["applicable"])
        self.assertNotEqual("ready", preview["classification"])
        self.assertTrue(any(check["code"] == "platform-scope" and check["status"] == "blocked" for check in preview["checks"]))

    def test_a_feature_cannot_be_scoped_while_the_board_has_no_apps(self) -> None:
        from prism_cli.board_service import BoardError

        service = BoardService(self.root).start()
        self.addCleanup(service.close)
        page = (
            "---\nid: F-001\ntitle: Outcome\nstatus: raw\nowner: po\nintroduced: 2026-09-22\nlast-updated: 2026-09-22\n"
            "platforms:\n- backend\nsources: []\nadvisory-review: not-needed\n---\n\n## Summary\nx\n"
        )
        with self.assertRaises(BoardError) as error:
            service._validate_feature_output("knowledge/wiki/features/F-001-outcome.md", page, "po-intake")
        self.assertEqual("invalid_feature_output", error.exception.code)
        self.assertIn("this board has no apps", error.exception.message)
        self.assertIn("prism app add", error.exception.message)

    def test_adding_the_first_app_to_a_zero_app_workspace_works(self) -> None:
        code, _out, err = run_cli("app", "add", "backend", "--stack", "spring-backend", str(self.root), "--apply", "--yes")
        self.assertEqual(0, code, err)
        self.assertEqual(["backend"], [item["id"] for item in manifest_data(self.root)["apps"]])
        service = BoardService(self.root)
        self.addCleanup(service.close)
        self.assertEqual({"read_only": False, "reason": None}, service.compatibility())


class LocalOverrideIgnoreTests(unittest.TestCase):
    """`prism.local.yml` is untracked: the generated project and the workflow installer both ignore it."""

    def test_the_generated_project_gitignore_lists_it(self) -> None:
        text = (REPO_ROOT / "template" / ".gitignore.jinja").read_text(encoding="utf-8")
        lines = [line.strip() for line in text.splitlines()]
        self.assertIn("prism.local.yml", lines)
        self.assertIn("# Prism per-machine repository checkouts (never commit)", lines)

    def plan_gitignore(self, existing: str | None) -> dict[str, str | None] | None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "ws"
            root.mkdir()
            if existing is not None:
                (root / ".gitignore").write_text(existing, encoding="utf-8", newline="")
            plan = plan_install(root, name="Ignore", platforms=["backend"])
        return next((change for change in plan["changes"] if change["path"] == ".gitignore"), None)

    def test_a_new_gitignore_gets_both_rules(self) -> None:
        change = self.plan_gitignore(None)
        self.assertEqual(
            "# Prism local workflow state\n.prism/state/\n# Prism per-machine repository checkouts\nprism.local.yml\n",
            change["after"],
        )

    def test_an_existing_gitignore_receives_only_the_missing_rule(self) -> None:
        change = self.plan_gitignore("node_modules/\n.prism/state/\n")
        self.assertEqual("node_modules/\n.prism/state/\n# Prism per-machine repository checkouts\nprism.local.yml\n", change["after"])
        change = self.plan_gitignore("node_modules/\nprism.local.yml\n")
        self.assertEqual("node_modules/\nprism.local.yml\n# Prism local workflow state\n.prism/state/\n", change["after"])

    def test_an_existing_gitignore_with_both_rules_is_unchanged(self) -> None:
        self.assertIsNone(self.plan_gitignore(".prism/state/\n/prism.local.yml\n"))

    def test_a_negated_rule_does_not_count_and_crlf_is_kept(self) -> None:
        change = self.plan_gitignore("prism.local.yml\n!prism.local.yml\n.prism/state/\n")
        self.assertIn("# Prism per-machine repository checkouts\nprism.local.yml\n", change["after"])
        change = self.plan_gitignore("a\r\n")
        self.assertEqual(
            "a\r\n# Prism local workflow state\r\n.prism/state/\r\n# Prism per-machine repository checkouts\r\nprism.local.yml\r\n",
            change["after"],
        )

    def test_a_workflow_install_writes_the_rules_and_a_second_run_changes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "ws"
            root.mkdir()
            self.assertEqual(0, run_cli("workflow", "install", str(root), "--name", "Ignore", "--app", "backend", "--apply", "--yes")[0])
            lines = (root / ".gitignore").read_text(encoding="utf-8").splitlines()
            self.assertIn("prism.local.yml", lines)
            self.assertIn(".prism/state/", lines)
            plan = plan_install(root, name="Ignore", platforms=["backend"])
            self.assertIn(".gitignore", plan["unchanged"])


class BoardPageAppsTests(unittest.TestCase):
    def test_the_board_page_reads_apps_and_lists_their_ids(self) -> None:
        html = (REPO_ROOT / "prism_cli" / "assets" / "graph_template.html").read_text(encoding="utf-8")
        self.assertNotIn("ws.platforms", html)
        self.assertNotIn("workspace.platforms", html)
        self.assertIn("Workspace apps: ${promptLiteral(appIds)}", html)
        self.assertIn("apps: ${boundedText(apps, 180)}", html)


class ContractAcceptanceThroughTheCliTests(unittest.TestCase):
    """Contract section 8: two apps of one stack in two repositories, plus a backend, through the commands only."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.root = self.base / "ws"
        self.root.mkdir()
        steps = (
            ("workflow", "install", str(self.root), "--name", "Two apps", "--app", "backend", "--apply", "--yes"),
            ("app", "add", "customer-android", "--stack", "android-compose", "--path", "apps/customer", str(self.root), "--apply", "--yes"),
            (
                "app",
                "add",
                "partner-android",
                "--stack",
                "android-compose",
                "--repository",
                "mobile-apps",
                "--remote",
                REMOTE,
                "--path",
                "apps/partner",
                str(self.root),
                "--apply",
                "--yes",
            ),
        )
        for argv in steps:
            code, _out, err = run_cli(*argv)
            self.assertEqual(0, code, f"{argv}: {err}")

    def test_status_json_lists_the_three_apps_with_their_stacks_and_repositories(self) -> None:
        envelope = run_json("status", str(self.root), "--json")
        Draft202012Validator(schema("status-v1.json")).validate(envelope)
        apps = {app["id"]: app for app in envelope["workspace"]["apps"]}
        self.assertEqual(["backend", "customer-android", "partner-android"], list(apps))
        self.assertEqual(
            {"backend": ("spring-backend", "workspace"), "customer-android": ("android-compose", "workspace"), "partner-android": ("android-compose", "mobile-apps")},
            {key: (app["stack"], app["repository"]) for key, app in apps.items()},
        )
        self.assertEqual(("apps/customer", "apps/partner"), (apps["customer-android"]["path"], apps["partner-android"]["path"]))
        self.assertEqual(
            [{"id": "workspace", "remote": None}, {"id": "mobile-apps", "remote": REMOTE, "checkout": "unresolved"}],
            envelope["workspace"]["repositories"],
        )

    def test_the_board_discover_payload_lists_the_same_apps(self) -> None:
        status_apps = run_json("status", str(self.root), "--json")["workspace"]["apps"]
        service = BoardService(self.root).start()
        self.addCleanup(service.close)
        self.assertEqual({"read_only": False, "reason": None}, service.compatibility())
        actor = service.authenticate(service.create_participant("Writer", "human", writable=True)["token"])
        self.assertEqual(status_apps, service.discover(actor)["board"]["apps"])

    def test_without_prism_local_yml_status_shows_one_unresolved_warning_and_a_checkout_clears_it(self) -> None:
        def unresolved() -> list[dict]:
            envelope = run_json("status", str(self.root), "--json")
            return [item for item in envelope["diagnostics"] if item["code"] == "external-repository-unresolved"]

        warnings = unresolved()
        self.assertEqual(1, len(warnings))
        self.assertEqual("warning", warnings[0]["severity"])
        self.assertIn("mobile-apps", warnings[0]["message"])
        self.assertEqual([], [item for item in run_json("status", str(self.root), "--json")["diagnostics"] if item["severity"] == "error"])
        checkout = self.base / "mobile-apps"
        checkout.mkdir()
        (self.root / "prism.local.yml").write_text(yaml.safe_dump({"repositories": {"mobile-apps": str(checkout)}}), encoding="utf-8")
        self.assertEqual([], unresolved())
        self.assertEqual("resolved", run_json("status", str(self.root), "--json")["workspace"]["repositories"][1]["checkout"])

    def test_lint_passes_for_the_two_app_workspace(self) -> None:
        envelope = run_json("wiki", "lint", str(self.root), "--json")
        Draft202012Validator(schema("wiki-lint-v1.json")).validate(envelope)
        self.assertEqual(["backend", "customer-android", "partner-android"], [app["id"] for app in envelope["workspace"]["apps"]])
        self.assertEqual(0, envelope["facts"]["error_count"])

    def test_a_generated_five_app_workspace_reads_like_the_baseline_apart_from_the_field_names(self) -> None:
        """The deep comparison is the baseline snapshot test; this checks the renamed fields against the same workspace."""

        with tempfile.TemporaryDirectory() as temporary:
            root = app_model_baseline.build_full_workspace(Path(temporary).resolve() / "ws")
            status = run_json("status", str(root), "--json")
            lint = run_json("wiki", "lint", str(root), "--json", allowed=(0, 3))
            service = BoardService(root).start()
            try:
                actor = service.authenticate(service.create_participant("Reader", "human", writable=True)["token"])
                board_apps = service.discover(actor)["board"]["apps"]
                compatibility = service.compatibility()
            finally:
                service.close()
        ids = ["backend", "web-user-app", "web-admin-portal", "mobile-android", "mobile-ios"]
        self.assertEqual(ids, [app["id"] for app in status["workspace"]["apps"]])
        self.assertEqual(ids, [app["id"] for app in lint["workspace"]["apps"]])
        self.assertEqual(ids, [app["id"] for app in board_apps])
        self.assertEqual({"read_only": False, "reason": None}, compatibility)
        self.assertEqual(WORKSPACE_REPOSITORY_ID, status["workspace"]["repositories"][0]["id"])


if __name__ == "__main__":
    unittest.main()
