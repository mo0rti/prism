from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from prism_cli import cli
from prism_cli.manifest_update import (
    ManifestMergeConflict,
    ManifestUpdateError,
    merge_workspace_manifest,
)


class CliAnswerValidationTests(unittest.TestCase):
    def test_rejects_wrong_platform_and_auth_types_and_values(self) -> None:
        cases = (
            ({"platforms": "backend", "auth_methods": ["password"]}, "platforms must be a list"),
            ({"platforms": ["desktop"], "auth_methods": ["password"]}, "Unsupported platforms value"),
            ({"platforms": ["backend"], "auth_methods": "password"}, "auth_methods must be a list"),
            ({"platforms": ["backend"], "auth_methods": ["magic"]}, "Unsupported auth_methods value"),
        )
        for answers, expected in cases:
            with self.subTest(answers=answers):
                errors, _warnings = cli.validate_answers(answers)
                self.assertTrue(any(expected in error for error in errors), errors)

    def test_rejects_non_boolean_docker_preset_data(self) -> None:
        errors, _warnings = cli.validate_answers(
            {"platforms": ["backend"], "auth_methods": ["password"], "use_docker": "sometimes"}
        )
        self.assertIn("use_docker must be true or false.", errors)

    def test_non_interactive_new_requires_answers_or_preset_before_prompting(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "project"
            args = cli.build_parser().parse_args(["new", "--project-name", "No Preset", "--dest", str(destination)])
            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr), patch("sys.stdin", io.StringIO("")):
                result = cli.cmd_new(args)

        self.assertEqual(cli.EXIT_USAGE, result)
        self.assertIn("requires `--preset` or `--answers`", stderr.getvalue())
        self.assertFalse(destination.exists())

    def test_project_slug_override_is_passed_to_copier(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "generated"
            args = cli.build_parser().parse_args(
                [
                    "new",
                    "--preset",
                    "backend-only",
                    "--project-name",
                    "Café",
                    "--project-slug",
                    "cafe",
                    "--dest",
                    str(destination),
                    "--template",
                    "custom-template",
                    "--trust-template",
                    "--yes",
                ]
            )
            with (
                patch.object(cli, "ensure_template_trust", return_value=True),
                patch.object(cli, "render_summary"),
                patch.object(cli, "prepare_generation_destination", return_value=None),
                patch.object(cli, "run_copier", return_value=0) as run_copier,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                result = cli.cmd_new(args)

        self.assertEqual(0, result)
        self.assertEqual("cafe", run_copier.call_args.args[2]["project_slug"])

    def test_answers_file_bad_values_are_rejected_before_any_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            answers_path = root / "answers.yml"
            answers_path.write_text(
                "schema_version: 1\nanswers:\n  project_name: Bad Data\n  platforms: backend\n  auth_methods: [password]\ndestination: "
                + str(root / "project")
                + "\n",
                encoding="utf-8",
            )
            args = cli.build_parser().parse_args(["new", "--answers", str(answers_path)])
            stderr = io.StringIO()
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(stderr), patch(
                "sys.stdin", io.StringIO("")
            ):
                result = cli.cmd_new(args)

        self.assertEqual(cli.EXIT_VALIDATION, result)
        self.assertIn("platforms must be a list", stderr.getvalue())
        self.assertFalse((root / "project").exists())


class ManifestFieldMergeTests(unittest.TestCase):
    def test_applies_template_edits_and_keeps_workspace_only_fields(self) -> None:
        previous = {
            "schema_version": 1,
            "min_prism_cli_version": "0.2.0",
            "project": {"name": "Example", "description": "Template description", "platforms": ["backend"]},
            "generated_by": {"template_commit": "old", "generated_at": "old time", "custom": "baseline"},
        }
        current = {
            "schema_version": 1,
            "min_prism_cli_version": "0.2.0",
            "project": {"name": "Example", "description": "Workspace description", "platforms": ["backend"]},
            "team_notes": {"owner": "workspace"},
            "generated_by": {"template_commit": "rewritten old", "generated_at": "new time", "custom": "workspace"},
        }
        latest = {
            "schema_version": 1,
            "min_prism_cli_version": "0.3.0",
            "project": {"name": "Example", "description": "Template description", "platforms": ["backend"]},
            "template_field": True,
            "generated_by": {"template_commit": "new", "generated_at": "latest time", "custom": "baseline"},
        }

        merged = merge_workspace_manifest(previous, current, latest)

        self.assertEqual("0.3.0", merged["min_prism_cli_version"])
        self.assertEqual("Workspace description", merged["project"]["description"])
        self.assertEqual({"owner": "workspace"}, merged["team_notes"])
        self.assertTrue(merged["template_field"])
        self.assertEqual("workspace", merged["generated_by"]["custom"])
        self.assertNotIn("template_commit", merged["generated_by"])

    def test_rejects_different_edits_to_the_same_field(self) -> None:
        previous = {"schema_version": 1, "project": {"platforms": ["backend"]}}
        current = {"schema_version": 1, "project": {"platforms": ["backend", "mobile-ios"]}}
        latest = {"schema_version": 1, "project": {"platforms": ["backend", "web-user-app"]}}

        with self.assertRaises(ManifestMergeConflict) as raised:
            merge_workspace_manifest(previous, current, latest)

        self.assertEqual(["project.platforms"], raised.exception.fields)

    def test_merges_independent_new_nested_fields(self) -> None:
        previous = {"schema_version": 1}
        current = {"schema_version": 1, "custom": {"team": "green"}}
        latest = {"schema_version": 1, "custom": {"support": "email"}}

        merged = merge_workspace_manifest(previous, current, latest)

        self.assertEqual({"team": "green", "support": "email"}, merged["custom"])

    def test_rejects_non_string_nested_mapping_keys_cleanly(self) -> None:
        previous = {"schema_version": 1, "custom": {1: "baseline"}}
        current = {"schema_version": 1, "custom": {1: "workspace"}}
        latest = {"schema_version": 1, "custom": {"name": "template"}}

        with self.assertRaisesRegex(ManifestUpdateError, "non-string mapping key at custom"):
            merge_workspace_manifest(previous, current, latest)


class UpdateBaselineTests(unittest.TestCase):
    def test_local_and_missing_revision_sources_have_no_trustworthy_baseline(self) -> None:
        self.assertFalse(cli.has_trustworthy_template_baseline("C:/templates/prism", {"_commit": "abc123"}))
        self.assertFalse(cli.has_trustworthy_template_baseline("https://example.invalid/template.git", {}))
        self.assertTrue(cli.has_trustworthy_template_baseline("git+file:///tmp/template", {"_commit": "v1.0.0"}))

    def test_smart_update_with_missing_baseline_is_refused_before_copier(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            (project / cli.COPIER_ANSWERS_FILE).write_text(
                "_src_path: C:/templates/prism\nproject_name: Local Project\n", encoding="utf-8"
            )
            args = Namespace(
                path=str(project),
                strategy="auto",
                yes=True,
                trust_template=True,
                from_launcher=False,
            )
            with (
                patch.object(cli, "detect_validation_target", return_value="generated-project"),
                patch.object(cli, "inspect_git_worktree", return_value={"is_repo": True, "is_dirty": False, "repo_root": str(project)}),
                patch.object(cli, "is_direct_git_worktree", return_value=True),
                patch.object(cli, "ensure_template_trust", return_value=True),
                patch.object(cli, "run_copier_update") as run_update,
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()) as stderr,
            ):
                result = cli.cmd_update(args)

        self.assertEqual(cli.EXIT_VALIDATION, result)
        self.assertFalse(run_update.called)
        self.assertIn("trustworthy versioned template baseline", stderr.getvalue())


class ManifestSaveSafetyTests(unittest.TestCase):
    def _destination(self, root: Path) -> tuple[Path, Path, bytes]:
        destination = root / "project"
        destination.mkdir()
        manifest = destination / cli.MANIFEST_FILE
        original = b"schema_version: 1\nproject:\n  name: Example\n"
        manifest.write_bytes(original)
        (destination / cli.COPIER_ANSWERS_FILE).write_text("{}\n", encoding="utf-8")
        return destination, manifest, original

    def test_uses_random_sidecar_and_preserves_legacy_temp_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            destination, manifest, original = self._destination(Path(temp_dir))
            legacy_temp = destination / (cli.MANIFEST_FILE + ".prism-tmp")
            legacy_temp.write_bytes(b"user-owned sentinel")

            with patch.object(cli, "is_remote_template", return_value=False):
                result = cli.refresh_workspace_manifest(
                    destination,
                    "C:/templates/prism",
                    {},
                    manifest_data={"schema_version": 1, "project": {"name": "Example"}},
                    expected_manifest_bytes=original,
                )

            self.assertTrue(result)
            self.assertNotEqual(original, manifest.read_bytes())
            self.assertEqual(b"user-owned sentinel", legacy_temp.read_bytes())
            self.assertEqual(
                sorted([cli.COPIER_ANSWERS_FILE, cli.MANIFEST_FILE, legacy_temp.name]),
                sorted(path.name for path in destination.iterdir()),
            )

    def test_does_not_overwrite_manifest_changed_after_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            destination, manifest, original = self._destination(Path(temp_dir))
            external_edit = b"schema_version: 1\nproject:\n  name: External edit\n"
            manifest.write_bytes(external_edit)
            stderr = io.StringIO()

            with patch.object(cli, "is_remote_template", return_value=False), contextlib.redirect_stderr(stderr):
                result = cli.refresh_workspace_manifest(
                    destination,
                    "C:/templates/prism",
                    {},
                    manifest_data={"schema_version": 1, "project": {"name": "Merged"}},
                    expected_manifest_bytes=original,
                )

            self.assertFalse(result)
            self.assertEqual(external_edit, manifest.read_bytes())
            self.assertIn("changed after update preflight", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
