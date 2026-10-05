from __future__ import annotations

import contextlib
import io
import os
import shutil
import socket
import sqlite3
import subprocess
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import yaml

from prism_cli import board_server
from prism_cli import cli
from prism_cli import render
from prism_cli import __version__
from prism_cli.board_service import BoardService
from prism_cli.fs_safety import CLOUD_SYNC_MESSAGE
from prism_cli.status import build_status
from prism_cli.workflow_install import apply_install, plan_install
from tests.test_fs_safety import CLOUD_TAG, JUNCTION_TAG, fake_reparse
from prism_cli.workspace import (
    MANIFEST_FILE,
    MANIFEST_SCHEMA_VERSION,
    inspect_workspace,
    load_workspace,
    write_workspace_manifest,
)
from tests.manifest_fixtures import manifest_data
from tests import real_temp  # noqa: F401


def write_workspace(root: Path, *, manifest: dict | None = None, answers: dict | None = None) -> None:
    wiki = root / "knowledge" / "wiki"
    for directory in ("features", "personas", "business-rules", "design", "api-contracts", "decisions", "platform-requirements", "advisory"):
        (wiki / directory).mkdir(parents=True, exist_ok=True)
    (root / "knowledge" / "intake" / "pending").mkdir(parents=True, exist_ok=True)
    (root / "knowledge" / "intake" / "quarantined").mkdir(parents=True, exist_ok=True)
    (wiki / "SCHEMA.md").write_text("# Schema\n", encoding="utf-8")
    (wiki / "SETTINGS.md").write_text("---\nwiki-stale-after-days: 21\n---\n", encoding="utf-8")
    (wiki / "index.md").write_text(
        "# Feature Status Board\n\n"
        "| ID | Feature | Status | Owner | Board Review | Introduced |\n"
        "|----|---------|--------|-------|--------------|------------|\n",
        encoding="utf-8",
    )
    (wiki / "advisory" / "BOARD.md").write_text("# Advisory Board\n", encoding="utf-8")
    if manifest is not None:
        (root / MANIFEST_FILE).write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    if answers is not None:
        (root / ".copier-answers.yml").write_text(yaml.safe_dump(answers, sort_keys=False), encoding="utf-8")


class WorkspaceSchemaContractTests(unittest.TestCase):
    def test_missing_manifest_is_degraded_and_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            result = load_workspace(root)

        self.assertIsNone(result.manifest)
        self.assertFalse(result.manifest_exists)
        self.assertEqual("missing-workspace-manifest", result.diagnostics[0].code)

    def test_version_one_is_refused_without_interpreting_fields_or_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data = {"schema_version": 1, "project": {"name": "Older", "platforms": ["backend"]}}
            path = root / MANIFEST_FILE
            path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
            before = path.read_bytes()

            result = load_workspace(root)

            self.assertIsNone(result.manifest)
            self.assertEqual(1, result.manifest_schema_version)
            self.assertEqual(["unsupported-workspace-manifest-schema"], [item.code for item in result.diagnostics])
            self.assertIn("Recreate or reinstall", result.diagnostics[0].message)
            self.assertEqual(before, path.read_bytes())

    def test_newer_schema_is_refused_without_interpreting_fields_or_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / MANIFEST_FILE
            path.write_text("schema_version: 99\nproject:\n  name: Future\n", encoding="utf-8")
            before = path.read_bytes()

            result = load_workspace(root)

            self.assertIsNone(result.manifest)
            self.assertTrue(result.manifest_exists)
            self.assertEqual(99, result.manifest_schema_version)
            self.assertEqual("unsupported-workspace-manifest-schema", result.diagnostics[0].code)
            self.assertEqual(before, path.read_bytes())

    def test_invalid_yaml_and_unicode_are_reported_as_unreadable_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / MANIFEST_FILE
            path.write_text("schema_version: [", encoding="utf-8")
            invalid = load_workspace(root)
            self.assertEqual("invalid-workspace-manifest-yaml", invalid.diagnostics[0].code)

            path.write_text("schema_version: 1\ngenerated_at: 2026-99-99\n", encoding="utf-8")
            invalid_timestamp = load_workspace(root)
            self.assertEqual("invalid-workspace-manifest-yaml", invalid_timestamp.diagnostics[0].code)

            path.write_bytes(b"\xff")
            unreadable = load_workspace(root)
            self.assertEqual("unreadable-workspace-manifest", unreadable.diagnostics[0].code)

    def test_template_renders_quoted_project_identity_as_valid_yaml(self) -> None:
        name = 'Quote "Project" \\ Sample'
        with tempfile.TemporaryDirectory(prefix="prism-template-quoted-contract-") as temp_dir:
            output = Path(temp_dir) / "output"
            result = subprocess.run(
                [
                    "copier",
                    "copy",
                    "--trust",
                    "--defaults",
                    "--data",
                    f"project_name={name}",
                    "--data",
                    "project_slug=quote-project",
                    "--data",
                    "platforms=[backend]",
                    "--data",
                    "auth_methods=[password]",
                    "--data",
                    "supporting_services=[]",
                    ".",
                    str(output),
                ],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, result.returncode, result.stderr[-2000:])
            manifest = yaml.safe_load((output / MANIFEST_FILE).read_text(encoding="utf-8"))
            self.assertEqual(name, manifest["project"]["name"])


class WorkspaceInspectionTests(unittest.TestCase):
    def test_newer_generator_preserves_template_minimum_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_workspace(root, manifest={**manifest_data("Test", ["backend"]), "min_prism_cli_version": "0.2.0"})
            path = write_workspace_manifest(root, {"project_name": "Test", "platforms": ["backend"]}, prism_cli_version="0.9.0")
            result = yaml.safe_load(path.read_text(encoding="utf-8"))
            self.assertEqual("0.2.0", result["min_prism_cli_version"])
            self.assertEqual("0.9.0", result["generated_by"]["prism_cli_version"])

    def test_unreadable_board_is_unknown_and_completed_board_comment_is_initialized(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_workspace(root)
            board = root / "knowledge/wiki/advisory/BOARD.md"
            board.write_bytes(b"\xff\xfe")
            self.assertEqual("unknown", build_status(root).setup_state)
            board.write_text("# Advisory Board\n\n<!-- generated by /setup-project -->\n## Confirmed Member\n", encoding="utf-8")
            self.assertEqual("initialized", build_status(root).setup_state)

    def test_generated_workspace_without_answers_is_explicitly_degraded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_workspace(root, manifest=manifest_data("Generated", ["backend"]))
            (root / "backend").mkdir()

            inspection = inspect_workspace(root)
            status = build_status(root)

        self.assertIn("missing-copier-answers", {item.code for item in inspection.contract_diagnostics})
        self.assertEqual("degraded", status.confidence)

    def test_inspection_compares_answers_and_filesystem_and_checks_minimum_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_workspace(
                root,
                manifest={**manifest_data("Manifest Name", ["backend"]), "min_prism_cli_version": "99.0.0"},
                answers={"_src_path": "template", "project_name": "Answers Name", "platforms": ["mobile-ios"]},
            )
            (root / "backend").mkdir()

            inspection = inspect_workspace(root)
            codes = {item.code for item in inspection.contract_diagnostics}

        self.assertIn("manifest-answers-drift", codes)
        self.assertIn("minimum-prism-cli-version-not-met", codes)
        self.assertEqual("Manifest Name", inspection.project_name)
        self.assertEqual(["backend"], inspection.platforms)
        self.assertEqual(["backend"], inspection.filesystem_platforms)

    def test_inspection_falls_back_to_answers_and_filesystem_when_manifest_is_unsupported(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_workspace(root, manifest={**manifest_data("Future", ["mobile-ios"]), "schema_version": 3}, answers={"_src_path": "template", "project_name": "Current", "platforms": ["backend"]})
            (root / "backend").mkdir()
            inspection = inspect_workspace(root)

        self.assertIsNone(inspection.manifest)
        self.assertEqual("Current", inspection.project_name)
        self.assertEqual(["backend"], inspection.platforms)
        self.assertIn("unsupported-workspace-manifest-schema", {item.code for item in inspection.contract_diagnostics})

    def test_write_manifest_records_known_provenance_and_excludes_unknown_answers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = write_workspace_manifest(
                root,
                {
                    "project_name": "Safe Project",
                    "project_slug": "safe-project",
                    "platforms": ["backend"],
                    "secret_token": "must-not-be-rendered",
                },
                prism_cli_version=__version__,
                template_source=r"C:\templates\prism",
                template_version="v0.3.0",
                template_commit="abc123",
                generated_at="2026-09-08T12:00:00+00:00",
            )
            data = yaml.safe_load(path.read_text(encoding="utf-8"))

        self.assertEqual(2, data["schema_version"])
        self.assertEqual(["backend"], [app["id"] for app in data["apps"]])
        self.assertEqual("spring-backend", data["apps"][0]["stack"])
        self.assertNotIn("platforms", data["project"])
        self.assertEqual("0.3.0", data["min_prism_cli_version"])
        self.assertEqual("0.3.0", data["generated_by"]["prism_cli_version"])
        self.assertEqual("v0.3.0", data["generated_by"]["template_version"])
        self.assertEqual("Safe Project", data["project"]["name"])
        self.assertNotIn("secret_token", yaml.safe_dump(data))

    def test_write_manifest_does_not_replace_an_unreadable_existing_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / MANIFEST_FILE
            path.write_text("schema_version: [", encoding="utf-8")
            before = path.read_bytes()

            with self.assertRaises(ValueError):
                write_workspace_manifest(root, {"project_name": "Project"}, prism_cli_version=__version__)

            self.assertEqual(before, path.read_bytes())


class WorkspaceStatusContractTests(unittest.TestCase):
    def test_full_status_contains_settings_generation_review_and_template_facts_without_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_workspace(
                root,
                manifest={
                    **manifest_data("Safe Project", ["backend"]),
                    "min_prism_cli_version": "0.2.0",
                    "generated_by": {
                        "prism_cli_version": "0.3.0",
                        "template_source": "https://github.com/mo0rti/prism.git",
                        "template_version": "v0.3.0",
                        "template_commit": "abc123",
                        "generated_at": "2026-09-08T12:00:00Z",
                    },
                },
                answers={
                    "_src_path": "https://github.com/mo0rti/prism.git",
                    "_commit": "abc123",
                    "project_name": "Safe Project",
                    "platforms": ["backend"],
                    "secret_token": "do-not-display",
                },
            )
            (root / "backend").mkdir()
            status = build_status(root)
            data = status.to_dict()

        self.assertEqual("healthy", data["facts"]["settings"]["health"])
        self.assertEqual(21, data["facts"]["settings"]["stale_after_days"])
        self.assertEqual([], data["facts"]["advisory_review"]["pending_feature_ids"])
        self.assertEqual("Safe Project", data["facts"]["generation"]["answers"]["project_name"])
        self.assertEqual("v0.3.0", data["facts"]["generation"]["template"]["template_version"])
        self.assertNotIn("secret_token", yaml.safe_dump(data))

    def test_doctor_workspace_returns_validation_failure_for_contract_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_workspace(root, manifest={**manifest_data("Future", ["backend"]), "schema_version": 99})
            args = Namespace(preset=None, workspace=str(root), from_launcher=True)
            with patch.object(cli, "evaluate_doctor_checks", return_value=[]), contextlib.redirect_stdout(io.StringIO()):
                result = cli.cmd_doctor(args)

        self.assertEqual(cli.EXIT_VALIDATION, result)

    def _run_doctor_for(self, root: Path) -> tuple[int, str]:
        args = Namespace(preset=None, workspace=str(root), from_launcher=True)
        output = io.StringIO()
        with patch.object(cli, "evaluate_doctor_checks", return_value=[]), contextlib.redirect_stdout(output):
            result = cli.cmd_doctor(args)
        return result, output.getvalue()

    def test_doctor_workspace_passes_the_cloud_check_for_a_local_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_workspace(root, manifest=manifest_data("Local", ["backend"]))
            _, text = self._run_doctor_for(root)

        self.assertIn("Workspace is outside cloud-synced folders", text)
        self.assertNotIn(CLOUD_SYNC_MESSAGE, text)

    def test_doctor_workspace_fails_the_cloud_check_with_guidance(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "synced" / "project"
            root.mkdir(parents=True)
            write_workspace(root, manifest=manifest_data("Cloud", ["backend"]))
            with fake_reparse(base / "synced", CLOUD_TAG):
                result, text = self._run_doctor_for(root)

        self.assertEqual(cli.EXIT_VALIDATION, result)
        self.assertIn("Workspace is outside cloud-synced folders", text)
        self.assertIn(CLOUD_SYNC_MESSAGE, text)

    def test_doctor_workspace_ignores_non_cloud_reparse_points_in_the_cloud_check(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "linked" / "project"
            root.mkdir(parents=True)
            write_workspace(root, manifest=manifest_data("Linked", ["backend"]))
            with fake_reparse(base / "linked", JUNCTION_TAG):
                _, text = self._run_doctor_for(root)

        self.assertNotIn(CLOUD_SYNC_MESSAGE, text)

    def test_remote_generation_uses_the_post_copy_copier_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            answers_path = root / ".copier-answers.yml"
            answers_path.write_text(
                yaml.safe_dump(
                    {
                        "_src_path": "https://github.com/mo0rti/prism.git",
                        "_commit": "new-template-ref",
                        "project_name": "Remote Project",
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )

            with patch.object(cli, "get_template_commit", return_value=None):
                self.assertTrue(
                    cli.refresh_workspace_manifest(
                        root,
                        "https://github.com/mo0rti/prism.git",
                        {"project_name": "Remote Project"},
                    )
                )
            data = yaml.safe_load((root / MANIFEST_FILE).read_text(encoding="utf-8"))

        self.assertEqual("new-template-ref", data["generated_by"]["template_commit"])
        self.assertEqual("https://github.com/mo0rti/prism.git", data["generated_by"]["template_source"])


class ReadSurfaceSplitTests(unittest.TestCase):
    def test_cli_keeps_v1_render_imports_while_implementation_lives_in_render_module(self) -> None:
        self.assertIs(cli.render_status_result, render.render_status_result)
        self.assertEqual("prism_cli.render", cli.render_status_result.__module__)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _make_git_skeleton(root: Path) -> None:
    """Make `root` a git work tree without running a git command that writes."""

    git_dir = root / ".git"
    (git_dir / "objects").mkdir(parents=True)
    (git_dir / "refs").mkdir()
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")


def _tree(root: Path) -> set[str]:
    return {str(path.relative_to(root)) for path in root.rglob("*")}


class DoctorBoardCheckTests(unittest.TestCase):
    """`prism doctor --workspace` shared-board checks are read-only and explain the fix."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        receipt = apply_install(self.root, plan_install(self.root, name="Doctor board", platforms=["backend"]))
        self.assertEqual("applied", receipt["status"])
        # Keep the default-port check independent of whatever runs on this machine.
        patcher = patch.object(board_server, "DEFAULT_BOARD_PORT", _free_port())
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_doctor(self) -> tuple[int, str]:
        args = Namespace(preset=None, workspace=str(self.root), from_launcher=True)
        output = io.StringIO()
        with patch.object(cli, "evaluate_doctor_checks", return_value=[]), contextlib.redirect_stdout(output):
            result = cli.cmd_doctor(args)
        return result, output.getvalue()

    def make_grant(self, *, writable: bool = False) -> None:
        with BoardService(self.root) as service:
            service.create_participant("Doctor test", "agent", writable=writable)

    def test_all_checks_are_listed_together_with_the_cloud_check(self) -> None:
        _, text = self.run_doctor()
        section = text.split("Shared board", 1)[1]
        for label in (
            "Workspace is outside cloud-synced folders",
            "Workflow pin is compatible with this Prism installation",
            "At least one active board grant exists",
            "is free",
            "`.prism/state` is ignored by git",
        ):
            self.assertIn(label, section)

    def test_workflow_pin_passes_for_a_compatible_workspace(self) -> None:
        result, text = self.run_doctor()

        self.assertEqual(0, result)
        self.assertIn("[ok] Workflow pin is compatible with this Prism installation", text)

    def test_workflow_pin_fails_with_the_reason_and_a_fix(self) -> None:
        manifest_path = self.root / MANIFEST_FILE
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        manifest["workflow"]["asset_digest"] = "0" * 64
        manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

        result, text = self.run_doctor()

        self.assertEqual(cli.EXIT_VALIDATION, result)
        self.assertIn("[fail] Workflow pin is compatible with this Prism installation", text)
        self.assertIn("do not match the installed canonical version", text)
        self.assertIn("Fix: Preview `prism workflow upgrade", text)
        self.assertIn("Shared board checks found 1 failure(s)", text)
        self.assertIn("[skip] At least one active board grant exists", text)

    def test_a_workspace_without_a_workflow_pin_gets_one_warning_not_a_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            legacy = Path(temp_dir)
            write_workspace(legacy, manifest=manifest_data("Legacy", ["backend"]))
            (legacy / "backend").mkdir()
            self.root = legacy
            _, text = self.run_doctor()

        self.assertIn("[warn] Workflow pin is compatible with this Prism installation", text)
        self.assertIn("Fix: Preview adoption with `prism workflow install", text)
        self.assertNotIn("[fail]", text)
        self.assertNotIn("active board grant", text)

    def test_next_step_without_a_target_matches_the_folder_doctor_runs_in(self) -> None:
        def run_in(folder: Path) -> str:
            previous = Path.cwd()
            os.chdir(folder)
            try:
                output = io.StringIO()
                args = Namespace(preset=None, workspace=None, from_launcher=True)
                with patch.object(cli, "evaluate_doctor_checks", return_value=[]), contextlib.redirect_stdout(output):
                    cli.cmd_doctor(args)
            finally:
                os.chdir(previous)
            return output.getvalue()

        in_workspace = run_in(self.root)
        self.assertIn("Run `prism doctor --workspace .` to check this workspace.", in_workspace)
        self.assertNotIn("You can generate a Prism project now.", in_workspace)

        with tempfile.TemporaryDirectory() as empty:
            elsewhere = run_in(Path(empty))
        self.assertIn("You can generate a Prism project now.", elsewhere)
        self.assertNotIn("--workspace .", elsewhere)

    def test_a_generated_workspace_without_a_workflow_pin_is_pointed_to_upgrade(self) -> None:
        manifest = {
            **manifest_data("Generated", ["backend"]),
            "generated_by": {"prism_cli_version": __version__, "template_source": "https://example.invalid/prism.git"},
        }
        cases = {
            "manifest provenance": {"manifest": manifest},
            "copier answers": {
                "manifest": manifest_data("Generated", ["backend"]),
                "answers": {"_src_path": "https://example.invalid/prism.git", "project_name": "Generated"},
            },
        }
        for label, options in cases.items():
            with self.subTest(label), tempfile.TemporaryDirectory() as temp_dir:
                generated = Path(temp_dir)
                write_workspace(generated, **options)
                self.root = generated
                _, text = self.run_doctor()

                self.assertIn("[warn] Workflow pin is compatible with this Prism installation", text)
                self.assertIn("Fix: Preview adoption with `prism workflow upgrade", text)
                self.assertNotIn("prism workflow install", text)
                self.assertNotIn("[fail]", text)

    def test_grant_check_warns_with_the_command_when_no_state_exists(self) -> None:
        result, text = self.run_doctor()

        self.assertEqual(0, result)
        self.assertIn("[warn] At least one active board grant exists", text)
        self.assertIn("No grants yet.", text)
        self.assertIn('prism board grant "NAME" --kind human|agent --write --path', text)
        self.assertFalse((self.root / ".prism").exists(), "doctor must not create board state")

    def test_grant_check_passes_with_an_active_grant(self) -> None:
        self.make_grant()

        result, text = self.run_doctor()

        self.assertEqual(0, result)
        self.assertIn("[ok] At least one active board grant exists", text)
        self.assertIn("1 active grant(s).", text)

    def test_grant_check_ignores_revoked_grants(self) -> None:
        with BoardService(self.root) as service:
            participant_id = service.create_participant("Doctor test", "agent")["participant"]["participant_id"]
            service.revoke_participant(participant_id)

        _, text = self.run_doctor()

        self.assertIn("[warn] At least one active board grant exists", text)
        self.assertIn("No active grants (1 revoked).", text)
        self.assertNotIn("No grants yet.", text)

    def test_grant_check_warns_when_every_grant_predates_the_workflow_pin(self) -> None:
        self.make_grant()
        database = sqlite3.connect(self.root / ".prism" / "state" / "board.sqlite3")
        try:
            database.execute("UPDATE grants SET asset_digest = ?", ("1" * 64,))
            database.commit()
        finally:
            database.close()

        result, text = self.run_doctor()

        self.assertEqual(0, result)
        self.assertIn("[warn] At least one active board grant exists", text)
        self.assertIn("1 grant(s) were issued for an earlier workflow pin", text)

    def test_grant_check_fails_when_the_board_state_is_unreadable(self) -> None:
        state = self.root / ".prism" / "state"
        state.mkdir(parents=True)
        (state / "board.sqlite3").write_bytes(b"this is not a sqlite database" * 20)

        result, text = self.run_doctor()

        self.assertEqual(cli.EXIT_VALIDATION, result)
        self.assertIn("[fail] At least one active board grant exists", text)
        self.assertIn("The board state cannot be read safely", text)
        self.assertNotIn("Traceback", text)

    def test_port_check_passes_when_the_default_port_is_free(self) -> None:
        _, text = self.run_doctor()

        self.assertIn(f"[ok] Default board port {board_server.DEFAULT_BOARD_PORT} is free", text)

    def test_port_check_names_the_busy_port(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as busy:
            busy.bind(("127.0.0.1", 0))
            busy.listen()
            port = busy.getsockname()[1]
            with patch.object(board_server, "DEFAULT_BOARD_PORT", port):
                result, text = self.run_doctor()

        self.assertEqual(0, result)
        self.assertIn(f"[warn] Default board port {port} is free", text)
        self.assertIn(f"Port {port} cannot be used", text)
        self.assertIn("prism board serve --port", text)

    @unittest.skipUnless(shutil.which("git"), "git is required")
    def test_state_ignore_check_passes_when_git_ignores_the_state_directory(self) -> None:
        _make_git_skeleton(self.root)
        self.assertIn(".prism/state/", (self.root / ".gitignore").read_text(encoding="utf-8"))

        _, text = self.run_doctor()

        self.assertIn("[ok] `.prism/state` is ignored by git", text)

    @unittest.skipUnless(shutil.which("git"), "git is required")
    def test_state_ignore_check_fails_when_the_state_directory_is_not_ignored(self) -> None:
        _make_git_skeleton(self.root)
        (self.root / ".gitignore").write_text("node_modules/\n", encoding="utf-8")

        result, text = self.run_doctor()

        self.assertEqual(cli.EXIT_VALIDATION, result)
        self.assertIn("[fail] `.prism/state` is ignored by git", text)
        self.assertIn("Fix: Add `.prism/state/` to .gitignore.", text)

    @unittest.skipUnless(shutil.which("git"), "git is required")
    def test_state_ignore_check_is_skipped_outside_a_git_repository(self) -> None:
        result, text = self.run_doctor()

        self.assertEqual(0, result)
        self.assertIn("[skip] `.prism/state` is ignored by git", text)
        self.assertIn("not a git repository", text)

    def test_state_ignore_check_is_skipped_when_git_is_unavailable(self) -> None:
        _make_git_skeleton(self.root)
        with patch("prism_cli.status.subprocess.run", side_effect=FileNotFoundError("git")):
            result, text = self.run_doctor()

        self.assertEqual(0, result)
        self.assertIn("[skip] `.prism/state` is ignored by git", text)
        self.assertIn("Git is not available", text)

    def test_doctor_never_creates_files_or_board_state(self) -> None:
        _make_git_skeleton(self.root)
        before = _tree(self.root)

        self.run_doctor()

        self.assertEqual(before, _tree(self.root))
        self.assertFalse((self.root / ".prism").exists())


if __name__ == "__main__":
    unittest.main()
