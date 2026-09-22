from __future__ import annotations

import contextlib
import io
import subprocess
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import yaml

from prism_cli import cli
from prism_cli import render
from prism_cli import __version__
from prism_cli.status import build_status
from prism_cli.workspace import (
    MANIFEST_FILE,
    MANIFEST_SCHEMA_VERSION,
    inspect_workspace,
    load_workspace,
    write_workspace_manifest,
)


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

    def test_older_schema_is_read_without_an_invented_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data = {"schema_version": MANIFEST_SCHEMA_VERSION - 1, "project": {"name": "Older", "platforms": ["backend"]}, "legacy": {"kept": True}}
            path = root / MANIFEST_FILE
            path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
            before = path.read_text(encoding="utf-8")

            result = load_workspace(root)

            self.assertIsNotNone(result.manifest)
            self.assertEqual(data, result.manifest.data)
            self.assertIn("older-workspace-manifest-schema", {item.code for item in result.diagnostics})
            self.assertEqual(before, path.read_text(encoding="utf-8"))

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
            write_workspace(root, manifest={"schema_version": 1, "min_prism_cli_version": "0.2.0", "project": {"name": "Test", "platforms": ["backend"]}})
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
            write_workspace(root, manifest={"schema_version": 1, "project": {"name": "Generated", "platforms": ["backend"]}})
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
                manifest={
                    "schema_version": 1,
                    "min_prism_cli_version": "99.0.0",
                    "project": {"name": "Manifest Name", "platforms": ["backend"]},
                },
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
            write_workspace(root, manifest={"schema_version": 2, "project": {"name": "Future", "platforms": ["mobile-ios"]}}, answers={"_src_path": "template", "project_name": "Current", "platforms": ["backend"]})
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
                template_version="v0.2.0",
                template_commit="abc123",
                generated_at="2026-09-08T12:00:00+00:00",
            )
            data = yaml.safe_load(path.read_text(encoding="utf-8"))

        self.assertEqual(1, data["schema_version"])
        self.assertEqual("0.2.0", data["min_prism_cli_version"])
        self.assertEqual("0.2.0", data["generated_by"]["prism_cli_version"])
        self.assertEqual("v0.2.0", data["generated_by"]["template_version"])
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
                    "schema_version": 1,
                    "min_prism_cli_version": "0.2.0",
                    "generated_by": {
                        "prism_cli_version": "0.2.0",
                        "template_source": "https://github.com/mo0rti/prism.git",
                        "template_version": "v0.2.0",
                        "template_commit": "abc123",
                        "generated_at": "2026-09-08T12:00:00Z",
                    },
                    "project": {"name": "Safe Project", "platforms": ["backend"]},
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
        self.assertEqual("v0.2.0", data["facts"]["generation"]["template"]["template_version"])
        self.assertNotIn("secret_token", yaml.safe_dump(data))

    def test_doctor_workspace_returns_validation_failure_for_contract_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_workspace(root, manifest={"schema_version": 99, "project": {"name": "Future", "platforms": ["backend"]}})
            args = Namespace(preset=None, workspace=str(root), from_launcher=True)
            with patch.object(cli, "evaluate_doctor_checks", return_value=[]), contextlib.redirect_stdout(io.StringIO()):
                result = cli.cmd_doctor(args)

        self.assertEqual(cli.EXIT_VALIDATION, result)

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


if __name__ == "__main__":
    unittest.main()
