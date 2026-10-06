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
from tests import real_temp  # noqa: F401


class CliAnswerValidationTests(unittest.TestCase):
    BACKEND = [{"id": "backend", "stack": "spring-backend"}]

    def test_rejects_wrong_app_list_and_auth_types_and_values(self) -> None:
        cases = (
            ({"apps": "backend", "auth_methods": ["password"]}, "`apps` must be a list"),
            ({"apps": [{"id": "x", "stack": "desktop"}], "auth_methods": ["password"]}, "needs a `stack` from the registry"),
            ({"apps": ["backend"], "auth_methods": ["password"]}, "`apps[0]` must be a mapping"),
            ({"apps": self.BACKEND, "auth_methods": "password"}, "auth_methods must be a list"),
            ({"apps": self.BACKEND, "auth_methods": ["magic"]}, "Unsupported auth_methods value"),
            ({"auth_methods": ["password"]}, "The app list is missing"),
        )
        for answers, expected in cases:
            with self.subTest(answers=answers):
                errors, _warnings = cli.validate_answers(answers)
                self.assertTrue(any(expected in error for error in errors), errors)

    def test_rejects_answers_for_questions_that_no_longer_exist(self) -> None:
        for removed in ("database", "supporting_services", "use_docker", "cloud_provider", "web_hosting", "platforms"):
            with self.subTest(removed=removed):
                errors, _warnings = cli.validate_answers(
                    {"apps": self.BACKEND, "auth_methods": ["password"], removed: "anything"}
                )
                self.assertEqual(1, len(errors), errors)
                self.assertIn(f"Unknown answer(s): {removed}.", errors[0])

    def test_accepts_every_answer_the_questionnaire_asks_for(self) -> None:
        errors, _warnings = cli.validate_answers(
            {
                "project_name": "Demo",
                "project_slug": "demo",
                "package_identifier": "com.example.demo",
                "description": "Demo",
                "apps": self.BACKEND,
                "auth_methods": ["password"],
                "github_org": "",
                "_prism_private": "ignored",
            }
        )
        self.assertEqual([], errors)

    def test_new_rejects_an_answers_file_that_sets_a_removed_question(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            answers_file = Path(temp_dir) / "answers.yml"
            answers_file.write_text(
                "schema_version: 1\nanswers:\n  project_name: Demo\n  apps: [{id: backend, stack: spring-backend}]\n  database: mysql\n",
                encoding="utf-8",
            )
            args = cli.build_parser().parse_args(["new", "--answers", str(answers_file), "--dest", str(Path(temp_dir) / "out"), "--yes"])
            stderr = io.StringIO()
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(stderr):
                result = cli.cmd_new(args)
            self.assertEqual(cli.EXIT_VALIDATION, result)
            self.assertIn("Unknown answer(s): database.", stderr.getvalue())
            self.assertFalse((Path(temp_dir) / "out").exists())

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
                "schema_version: 1\nanswers:\n  project_name: Bad Data\n  apps: backend\n  auth_methods: [password]\ndestination: "
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
        self.assertIn("`apps` must be a list", stderr.getvalue())
        self.assertFalse((root / "project").exists())


class ManifestFieldMergeTests(unittest.TestCase):
    def test_applies_template_edits_and_keeps_workspace_only_fields(self) -> None:
        previous = {
            "schema_version": 2,
            "min_prism_cli_version": "0.3.0",
            "project": {"name": "Example", "description": "Template description"},
            "generated_by": {"template_commit": "old", "generated_at": "old time", "custom": "baseline"},
        }
        current = {
            "schema_version": 2,
            "min_prism_cli_version": "0.3.0",
            "project": {"name": "Example", "description": "Workspace description"},
            "team_notes": {"owner": "workspace"},
            "generated_by": {"template_commit": "rewritten old", "generated_at": "new time", "custom": "workspace"},
        }
        latest = {
            "schema_version": 2,
            "min_prism_cli_version": "0.4.0",
            "project": {"name": "Example", "description": "Template description"},
            "template_field": True,
            "generated_by": {"template_commit": "new", "generated_at": "latest time", "custom": "baseline"},
        }

        merged = merge_workspace_manifest(previous, current, latest)

        self.assertEqual("0.4.0", merged["min_prism_cli_version"])
        self.assertEqual("Workspace description", merged["project"]["description"])
        self.assertEqual({"owner": "workspace"}, merged["team_notes"])
        self.assertTrue(merged["template_field"])
        self.assertEqual("workspace", merged["generated_by"]["custom"])
        self.assertNotIn("template_commit", merged["generated_by"])

    def test_rejects_different_edits_to_the_same_field(self) -> None:
        previous = {"schema_version": 2, "apps": [{"id": "backend"}]}
        current = {"schema_version": 2, "apps": [{"id": "backend"}, {"id": "mobile-ios"}]}
        latest = {"schema_version": 2, "apps": [{"id": "backend"}, {"id": "web-user-app"}]}

        with self.assertRaises(ManifestMergeConflict) as raised:
            merge_workspace_manifest(previous, current, latest)

        self.assertEqual(["apps"], raised.exception.fields)

    def test_merges_independent_new_nested_fields(self) -> None:
        previous = {"schema_version": 2}
        current = {"schema_version": 2, "custom": {"team": "green"}}
        latest = {"schema_version": 2, "custom": {"support": "email"}}

        merged = merge_workspace_manifest(previous, current, latest)

        self.assertEqual({"team": "green", "support": "email"}, merged["custom"])

    def test_rejects_non_string_nested_mapping_keys_cleanly(self) -> None:
        previous = {"schema_version": 2, "custom": {1: "baseline"}}
        current = {"schema_version": 2, "custom": {1: "workspace"}}
        latest = {"schema_version": 2, "custom": {"name": "template"}}

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
        original = b"schema_version: 2\nproject:\n  name: Example\n"
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
                    manifest_data={"schema_version": 2, "project": {"name": "Example"}},
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
            external_edit = b"schema_version: 2\nproject:\n  name: External edit\n"
            manifest.write_bytes(external_edit)
            stderr = io.StringIO()

            with patch.object(cli, "is_remote_template", return_value=False), contextlib.redirect_stderr(stderr):
                result = cli.refresh_workspace_manifest(
                    destination,
                    "C:/templates/prism",
                    {},
                    manifest_data={"schema_version": 2, "project": {"name": "Merged"}},
                    expected_manifest_bytes=original,
                )

            self.assertFalse(result)
            self.assertEqual(external_edit, manifest.read_bytes())
            self.assertIn("changed after update preflight", stderr.getvalue())


class MissingTemplateTagTests(unittest.TestCase):
    """Default generation needs the release tag; a missing tag ends in one message."""

    TAG = f"v{cli.__version__}"
    TRACEBACK = (
        "Traceback (most recent call last):\n"
        '  File "copier/_vcs.py", line 334, in _clone_via_cache\n'
        "plumbum.commands.processes.ProcessExecutionError: Unexpected exit code: 128\n"
        f"Stderr:       | fatal: invalid reference: {TAG}\n"
    )

    def run_new(self, result: dict, *extra: str):
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "project"
            argv = ["new", "--preset", "backend-only", "--project-name", "Demo", "--dest", str(destination), "--yes", *extra]
            stdout, stderr = io.StringIO(), io.StringIO()
            with (
                patch.object(cli, "default_template_reference", return_value=cli.DEFAULT_TEMPLATE_URL),
                patch.object(cli, "run_copier_generation_process", return_value=result) as process,
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                code = cli.main(argv)
            return code, stdout.getvalue(), stderr.getvalue(), process, destination

    def test_missing_release_tag_gives_one_message_and_no_traceback(self) -> None:
        code, stdout, stderr, process, destination = self.run_new(
            {"returncode": 1, "event_count": 0, "tail": [], "stderr": self.TRACEBACK}
        )

        self.assertEqual(cli.EXIT_VALIDATION, code)
        self.assertTrue(process.call_args.kwargs["capture_stderr"])
        self.assertIn(f"Default generation requires the matching template release tag `{self.TAG}`.", stdout)
        self.assertNotIn("Traceback", stderr)
        self.assertNotIn("Copier generation failed", stderr)
        self.assertEqual(1, len(stderr.strip().splitlines()), stderr)
        self.assertIn(f"`{self.TAG}` is not published", stderr)
        self.assertIn("--template <path or URL>", stderr)
        self.assertIn("install a released version", stderr)
        self.assertFalse(destination.exists())

    def test_missing_release_tag_is_recognized_from_terminal_output_too(self) -> None:
        code, _stdout, stderr, _process, _destination = self.run_new(
            {"returncode": 1, "event_count": 0, "tail": [f"Stderr:       | fatal: invalid reference: {self.TAG}"]}
        )

        self.assertEqual(cli.EXIT_VALIDATION, code)
        self.assertIn("is not published", stderr)
        self.assertNotIn("Copier output", stderr)

    def test_other_copier_failures_keep_their_output_and_exit_code(self) -> None:
        detail = "fatal: unable to access 'https://github.com/mo0rti/prism.git/': Could not resolve host"
        code, _stdout, stderr, _process, _destination = self.run_new(
            {"returncode": 1, "event_count": 0, "tail": [], "stderr": detail + "\n"}
        )

        self.assertEqual(cli.EXIT_COPIER, code)
        self.assertIn(detail, stderr)
        self.assertIn("Copier generation failed.", stderr)
        self.assertNotIn("is not published", stderr)

    def test_custom_template_does_not_capture_or_reinterpret_copier_output(self) -> None:
        code, _stdout, stderr, process, _destination = self.run_new(
            {"returncode": 1, "event_count": 0, "tail": [], "stderr": ""},
            "--template",
            "custom-template",
            "--trust-template",
        )

        self.assertEqual(cli.EXIT_COPIER, code)
        self.assertFalse(process.call_args.kwargs["capture_stderr"])
        self.assertNotIn("is not published", stderr)

    def test_noninteractive_process_captures_stderr_only_when_asked(self) -> None:
        completed = type("Completed", (), {"returncode": 1, "stderr": "boom\n"})()
        with patch.object(cli.sys.stdout, "isatty", return_value=False, create=True), patch.object(
            cli.subprocess, "run", return_value=completed
        ) as run:
            captured = cli.run_copier_generation_process(["copier"], Path("."), capture_stderr=True)
            plain = cli.run_copier_generation_process(["copier"], Path("."))

        self.assertEqual("boom\n", captured["stderr"])
        self.assertIs(run.call_args_list[0].kwargs["stderr"], cli.subprocess.PIPE)
        self.assertNotIn("stderr", run.call_args_list[1].kwargs)
        self.assertNotIn("stderr", plain)


if __name__ == "__main__":
    unittest.main()
