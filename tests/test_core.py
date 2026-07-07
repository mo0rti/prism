from __future__ import annotations

import contextlib
import io
import re
import subprocess
import tempfile
import unittest
import json
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from prism_cli import cli as cli_module
from prism_cli import ui as ui_module
from prism_cli.cli import (
    DEFAULT_GENERATED_DIR,
    build_home_actions,
    build_default_destination,
    build_parser,
    build_doctor_checks,
    choose_next_doctor_result,
    clear_directory_contents,
    detect_validation_target,
    detect_launch_context,
    dispatch_home_action,
    derive_project_slug,
    doctor_install_command,
    doctor_install_reference,
    evaluate_doctor_checks,
    ensure_copier_answers_file,
    format_data_value,
    inspect_git_worktree,
    is_direct_git_worktree,
    is_incubating_checkout,
    load_answers_file,
    load_copier_answers,
    normalize_template_path,
    parse_copier_progress_line,
    parse_multiselect_response,
    parse_preset_selection,
    format_copier_progress_line,
    is_generation_safe_existing_destination,
    prepare_generation_destination,
    render_doctor_result,
    resolve_update_strategy,
    summarize_doctor_results,
    supports_versioned_update,
    validate_answers,
    validate_generated_project_structure,
)
from prism_cli.presets import merge_answers
from prism_cli.presets import PRESETS, get_preset
from prism_cli.status import build_status
from prism_cli.ui import SelectOption, colorize, filter_select_options, panel, review_key_value, truncate_visible, visible_length
from prism_cli.wiki_graph import build_graph, render_mermaid
from prism_cli.wiki_query import wiki_blockers, wiki_owner, wiki_platform, wiki_search, wiki_show
from prism_cli.wiki_lint import lint_wiki
from prism_cli.workspace import MANIFEST_FILE, load_workspace


class ValidateAnswersTests(unittest.TestCase):
    def test_requires_at_least_one_platform(self) -> None:
        errors, warnings = validate_answers({"platforms": [], "auth_methods": []})
        self.assertIn("At least one platform must be selected.", errors)
        self.assertEqual([], warnings)

    def test_requires_password_auth_globally(self) -> None:
        errors, _warnings = validate_answers({"platforms": ["web-user-app"], "auth_methods": []})
        self.assertIn("Prism currently requires Username + Password auth as the baseline sign-in method.", errors)

    def test_requires_password_for_admin_portal(self) -> None:
        errors, _warnings = validate_answers({"platforms": ["web-admin-portal"], "auth_methods": ["google"]})
        self.assertIn("Prism currently requires Username + Password auth as the baseline sign-in method.", errors)

    def test_requires_password_for_backend_only_projects(self) -> None:
        errors, _warnings = validate_answers({"platforms": ["backend"], "auth_methods": ["google"]})
        self.assertIn("Prism currently requires Username + Password auth as the baseline sign-in method.", errors)

    def test_emits_expected_warnings(self) -> None:
        errors, warnings = validate_answers(
            {
                "platforms": ["mobile-ios", "web-user-app"],
                "auth_methods": ["apple", "password"],
            }
        )
        self.assertEqual([], errors)
        self.assertIn("Apple Sign-In remains experimental.", warnings)
        self.assertIn("Validate iOS generation locally on macOS before treating it as build-proven.", warnings)
        self.assertIn("Generated web slices still need live Cloudflare deployment validation.", warnings)


class MergeAnswersTests(unittest.TestCase):
    def test_override_wins(self) -> None:
        merged = merge_answers({"project_name": "Base", "use_docker": True}, {"use_docker": False})
        self.assertEqual("Base", merged["project_name"])
        self.assertFalse(merged["use_docker"])


class LoadAnswersFileTests(unittest.TestCase):
    def test_rejects_invalid_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "bad.yml"
            path.write_text("schema_version: [", encoding="utf-8")
            with patch("sys.stderr"):
                loaded = load_answers_file(str(path))
        self.assertIsNone(loaded)

    def test_rejects_wrong_schema_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "wrong-version.yml"
            path.write_text("schema_version: 2\nanswers: {}\n", encoding="utf-8")
            with patch("sys.stderr"):
                loaded = load_answers_file(str(path))
        self.assertIsNone(loaded)

    def test_rejects_missing_answers_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "missing-answers.yml"
            path.write_text("schema_version: 1\n", encoding="utf-8")
            with patch("sys.stderr"):
                loaded = load_answers_file(str(path))
        self.assertIsNone(loaded)

    def test_loads_valid_answers_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "answers.yml"
            path.write_text("schema_version: 1\nanswers:\n  project_name: Prism App\n", encoding="utf-8")
            with patch("sys.stderr"):
                loaded = load_answers_file(str(path))
        assert loaded is not None
        self.assertEqual("Prism App", loaded["answers"]["project_name"])


class LoadCopierAnswersTests(unittest.TestCase):
    def test_rejects_missing_src_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / ".copier-answers.yml"
            path.write_text("project_name: Prism App\n", encoding="utf-8")
            loaded = load_copier_answers(path)
        self.assertIsNone(loaded)

    def test_loads_valid_copier_answers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / ".copier-answers.yml"
            path.write_text("_src_path: C:/Workspace/Projects/Prism\nproject_name: Prism App\n", encoding="utf-8")
            loaded = load_copier_answers(path)
        assert loaded is not None
        self.assertEqual("Prism App", loaded["project_name"])


class CopierAnswersPersistenceTests(unittest.TestCase):
    @patch("prism_cli.cli.get_template_commit", return_value="abc123")
    def test_writes_answers_file_with_normalized_src_path(self, _mocked_commit: object) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ensure_copier_answers_file(root, ".", {"project_name": "Prism App", "platforms": ["backend"]})
            loaded = load_copier_answers(root / ".copier-answers.yml")

        assert loaded is not None
        self.assertEqual(str(Path(".").resolve()), loaded["_src_path"])
        self.assertEqual("Prism App", loaded["project_name"])
        self.assertEqual(["backend"], loaded["platforms"])
        self.assertIn("_commit", loaded)

    @patch("prism_cli.cli.get_template_commit", return_value="abc123")
    def test_preserves_existing_copier_metadata(self, _mocked_commit: object) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            answers_path = root / ".copier-answers.yml"
            answers_path.write_text("_src_path: old\n_custom_meta: keep-me\n", encoding="utf-8")
            ensure_copier_answers_file(root, ".", {"project_name": "Prism App"})
            loaded = load_copier_answers(answers_path)

        assert loaded is not None
        self.assertEqual("keep-me", loaded["_custom_meta"])
        self.assertIn("_commit", loaded)
        self.assertEqual("Prism App", loaded["project_name"])


class FormatDataValueTests(unittest.TestCase):
    def test_formats_bool(self) -> None:
        self.assertEqual("true", format_data_value(True))
        self.assertEqual("false", format_data_value(False))

    def test_formats_list(self) -> None:
        self.assertEqual("[backend, mobile-android]", format_data_value(["backend", "mobile-android"]))

    def test_formats_string(self) -> None:
        self.assertEqual("Prism App", format_data_value("Prism App"))


class CopierProgressTests(unittest.TestCase):
    def test_parses_create_progress_line(self) -> None:
        self.assertEqual(("create", ".agents\\skills\\ask\\SKILL.md"), parse_copier_progress_line("    create  .agents\\skills\\ask\\SKILL.md"))

    def test_parses_colored_create_progress_line(self) -> None:
        colored = "\033[32m\033[1m    create\033[39m\033[0m  .agents\\skills\\ask\\SKILL.md"
        self.assertEqual(("create", ".agents\\skills\\ask\\SKILL.md"), parse_copier_progress_line(colored))

    def test_ignores_non_event_progress_line(self) -> None:
        self.assertIsNone(parse_copier_progress_line("Copying from template version None"))

    def test_formats_progress_line_with_action_text(self) -> None:
        rendered = format_copier_progress_line("overwrite", "README.md", 0)
        self.assertIn("Updating", rendered)
        self.assertIn("README.md", rendered)


class UiRenderingTests(unittest.TestCase):
    def test_visible_length_ignores_ansi_sequences(self) -> None:
        rendered = colorize("Prism CLI", "\033[1m", "\033[36m")
        self.assertEqual(len("Prism CLI"), visible_length(rendered))

    def test_panel_right_edge_stays_aligned_with_colored_content(self) -> None:
        rendered = panel("Session", [colorize("Prism CLI", "\033[1m", "\033[36m"), "directory: C:\\Workspace\\Projects\\Prism"])
        visible_lines = [visible_length(line) for line in rendered.splitlines()]
        self.assertTrue(all(length == visible_lines[0] for length in visible_lines))

    def test_truncate_visible_preserves_visible_width(self) -> None:
        rendered = colorize("Prism CLI", "\033[1m", "\033[36m")
        truncated = truncate_visible(rendered, 5)
        self.assertEqual(5, visible_length(truncated))

    def test_filter_select_options_matches_command_text(self) -> None:
        options = [
            SelectOption(value="new", label="New Project", description="Create a new Prism project."),
            SelectOption(value="doctor", label="Doctor", description="Check prerequisites."),
        ]
        filtered = filter_select_options(options, "doc")
        self.assertEqual(["doctor"], [option.value for option in filtered])

    def test_command_palette_lines_stay_visibly_aligned(self) -> None:
        options = [
            SelectOption(value="new", label="New Project", description="Create a new Prism project."),
            SelectOption(value="doctor", label="Doctor", description="Check prerequisites."),
        ]
        lines = ui_module._render_command_palette_lines("Command palette", "do", options, 1)
        visible_lines = [visible_length(line) for line in lines]
        self.assertTrue(all(length == visible_lines[0] for length in visible_lines))

    def test_review_key_value_wraps_long_values(self) -> None:
        lines = review_key_value("Template", "C:/Workspace/Projects/Prism/" + ("very-long-segment/" * 8))
        self.assertGreater(len(lines), 1)

    def test_review_key_value_prefixes_only_first_line(self) -> None:
        lines = review_key_value("Platforms", "Backend, Android, iOS, Web User App, Web Admin Portal")
        self.assertTrue(lines[0].startswith("\033") or lines[0].startswith("Platforms: "))
        if len(lines) > 1:
            self.assertFalse("Platforms:" in lines[1])

    def test_single_select_lines_hide_palette_hint_when_disabled(self) -> None:
        lines = ui_module._render_single_select_lines(
            "Recommended presets",
            [SelectOption(value="new", label="New Project", description="Create a new Prism project.")],
            0,
            show_palette_hint=False,
        )
        self.assertNotIn("command palette", "\n".join(lines))

    def test_single_select_lines_show_palette_hint_when_enabled(self) -> None:
        lines = ui_module._render_single_select_lines(
            "Prism actions",
            [SelectOption(value="new", label="New Project", description="Create a new Prism project.")],
            0,
            show_palette_hint=True,
        )
        self.assertIn("command palette", "\n".join(lines))


class ParseMultiselectResponseTests(unittest.TestCase):
    def test_uses_defaults_when_input_is_empty(self) -> None:
        choices = (("backend", "Backend"), ("mobile-android", "Android"))
        parsed = parse_multiselect_response("", choices, ["backend"], allow_empty=False)
        self.assertEqual((["backend"], True), parsed)

    def test_parses_comma_separated_indexes(self) -> None:
        choices = (("backend", "Backend"), ("mobile-android", "Android"), ("mobile-ios", "iOS"))
        parsed = parse_multiselect_response("1, 3", choices, [], allow_empty=False)
        self.assertEqual((["backend", "mobile-ios"], False), parsed)

    def test_rejects_invalid_indexes(self) -> None:
        choices = (("backend", "Backend"),)
        self.assertIsNone(parse_multiselect_response("2", choices, [], allow_empty=False))


class ParsePresetSelectionTests(unittest.TestCase):
    def test_parses_regular_preset_choice(self) -> None:
        self.assertEqual("backend-only", parse_preset_selection("1"))

    def test_parses_advanced_choice(self) -> None:
        self.assertEqual("advanced", parse_preset_selection(str(len(PRESETS) + 1)))

    def test_rejects_invalid_choice(self) -> None:
        self.assertIsNone(parse_preset_selection("99"))


class NormalizeTemplatePathTests(unittest.TestCase):
    def test_normalizes_local_paths(self) -> None:
        self.assertEqual(str(Path(".").resolve()), normalize_template_path("."))

    def test_keeps_remote_template_refs(self) -> None:
        remote = "https://github.com/mo0rti/prism.git"
        self.assertEqual(remote, normalize_template_path(remote))


class DefaultsTests(unittest.TestCase):
    def test_default_generated_directory_name(self) -> None:
        self.assertEqual("workspaces", DEFAULT_GENERATED_DIR)

    def test_derives_project_slug_for_workspace_destinations(self) -> None:
        self.assertEqual("treasury-flow", derive_project_slug("Treasury Flow"))

    def test_builds_default_destination_under_workspaces(self) -> None:
        self.assertEqual(str(Path("workspaces") / "treasury-flow"), build_default_destination("Treasury Flow"))


class MainTests(unittest.TestCase):
    def test_main_returns_130_on_keyboard_interrupt(self) -> None:
        parser = unittest.mock.Mock()
        parser.parse_args.return_value = Namespace(func=lambda _args: (_ for _ in ()).throw(KeyboardInterrupt()))
        with patch("prism_cli.cli.build_parser", return_value=parser):
            exit_code = cli_module.main([])
        self.assertEqual(130, exit_code)


class HomeLauncherTests(unittest.TestCase):
    def test_build_parser_defaults_to_home_for_bare_prism(self) -> None:
        parser = build_parser()
        args = parser.parse_args([])
        self.assertEqual(cli_module.cmd_home, args.func)

    def test_detect_launch_context_for_template_repo(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "copier.yml").write_text("", encoding="utf-8")
            (root / "template").mkdir()
            self.assertEqual(("template", "template repo"), detect_launch_context(root))

    def test_detect_launch_context_for_generated_project(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "README.md").write_text("", encoding="utf-8")
            (root / "CONTEXT.md").write_text("", encoding="utf-8")
            (root / "knowledge" / "wiki").mkdir(parents=True)
            (root / "knowledge" / "wiki" / "SCHEMA.md").write_text("", encoding="utf-8")
            self.assertEqual(("generated-project", "generated project"), detect_launch_context(root))

    def test_build_home_actions_includes_update_only_for_generated_projects(self) -> None:
        generated_values = [action.value for action in build_home_actions("generated-project")]
        directory_values = [action.value for action in build_home_actions("directory")]
        self.assertIn("status", generated_values)
        self.assertIn("update", generated_values)
        self.assertNotIn("update", directory_values)

    def test_dispatch_home_action_help_prints_help(self) -> None:
        parser = build_parser()
        with patch.object(parser, "print_help") as print_help:
            result = dispatch_home_action("help", parser)
        self.assertEqual(0, result)
        print_help.assert_called_once()

    def test_dispatch_home_action_marks_command_as_from_launcher(self) -> None:
        parser = unittest.mock.Mock()
        seen: dict[str, bool] = {}

        def fake_func(args: Namespace) -> int:
            seen["from_launcher"] = getattr(args, "from_launcher", False)
            return 0

        parser.parse_args.return_value = Namespace(func=fake_func)
        result = dispatch_home_action("presets", parser)

        self.assertEqual(0, result)
        self.assertTrue(seen["from_launcher"])

    @patch("sys.stdout.isatty", return_value=False)
    @patch("sys.stdin.isatty", return_value=False)
    def test_cmd_home_noninteractive_renders_launcher_summary(self, _stdin_isatty: object, _stdout_isatty: object) -> None:
        parser = build_parser()
        args = parser.parse_args([])
        with patch("sys.stdout"):
            result = cli_module.cmd_home(args)
        self.assertEqual(0, result)


class DestinationPreparationTests(unittest.TestCase):
    def test_clear_directory_contents_removes_files_and_subdirectories(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "file.txt").write_text("hello", encoding="utf-8")
            (root / "nested").mkdir()
            (root / "nested" / "child.txt").write_text("world", encoding="utf-8")

            clear_directory_contents(root)

            self.assertEqual([], list(root.iterdir()))

    @patch("prism_cli.cli.confirm", return_value=True)
    @patch("sys.stdin.isatty", return_value=True)
    def test_prepare_generation_destination_clears_existing_directory_when_confirmed(self, _isatty: object, _confirm: object) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "old.txt").write_text("old", encoding="utf-8")

            result = prepare_generation_destination(root)

            self.assertIsNone(result)
            self.assertEqual([], list(root.iterdir()))

    @patch("sys.stdin.isatty", return_value=False)
    def test_prepare_generation_destination_refuses_noninteractive_delete(self, _isatty: object) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "old.txt").write_text("old", encoding="utf-8")

            with patch("sys.stderr"):
                result = prepare_generation_destination(root)

            self.assertEqual(cli_module.EXIT_VALIDATION, result)
            self.assertTrue((root / "old.txt").exists())

    def test_prepare_generation_destination_refuses_existing_generated_project(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "README.md").write_text("", encoding="utf-8")
            (root / "CONTEXT.md").write_text("", encoding="utf-8")
            (root / "knowledge" / "wiki").mkdir(parents=True)
            (root / "knowledge" / "wiki" / "SCHEMA.md").write_text("", encoding="utf-8")

            with patch("sys.stderr"):
                result = prepare_generation_destination(root)

            self.assertEqual(cli_module.EXIT_VALIDATION, result)

    def test_prepare_generation_destination_refuses_existing_git_repo(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".git").mkdir()
            (root / "README.txt").write_text("existing repo", encoding="utf-8")

            with patch("sys.stderr"):
                result = prepare_generation_destination(root)

            self.assertEqual(cli_module.EXIT_VALIDATION, result)

    def test_prepare_generation_destination_allows_empty_git_repo(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".git").mkdir()

            result = prepare_generation_destination(root)

            self.assertIsNone(result)

    def test_generation_safe_existing_destination_only_allows_single_git_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            git_dir = root / ".git"
            git_dir.mkdir()

            self.assertTrue(is_generation_safe_existing_destination([git_dir]))

            readme = root / "README.md"
            readme.write_text("", encoding="utf-8")
            self.assertFalse(is_generation_safe_existing_destination([git_dir, readme]))

    def test_generation_safe_existing_destination_allows_standard_repo_boilerplate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            git_dir = root / ".git"
            git_dir.mkdir()
            gitignore = root / ".gitignore"
            gitignore.write_text("node_modules/\n", encoding="utf-8")

            self.assertTrue(is_generation_safe_existing_destination([git_dir, gitignore]))


class UpdateStrategyTests(unittest.TestCase):
    def test_auto_uses_recopy_without_commit(self) -> None:
        strategy = resolve_update_strategy("auto", {"_src_path": str(Path(".").resolve())})
        self.assertEqual("recopy", strategy)

    @patch("prism_cli.cli.supports_versioned_update", return_value=True)
    def test_auto_uses_update_with_commit_and_supported_template(self, _mocked_support: object) -> None:
        strategy = resolve_update_strategy("auto", {"_src_path": str(Path(".").resolve()), "_commit": "abc123"})
        self.assertEqual("update", strategy)


class GitHelpersTests(unittest.TestCase):
    def test_supports_versioned_update_for_remote_refs(self) -> None:
        self.assertTrue(supports_versioned_update("https://github.com/mo0rti/prism.git"))

    def test_inspect_git_worktree_reports_non_repo(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state = inspect_git_worktree(Path(temp_dir))
        self.assertFalse(state["is_repo"])
        self.assertFalse(state["is_dirty"])
        self.assertIsNone(state["repo_root"])

    @patch("prism_cli.cli.subprocess.run")
    def test_inspect_git_worktree_handles_status_failure(self, mocked_run: object) -> None:
        mocked_run.side_effect = [
            unittest.mock.Mock(stdout="true\n"),
            unittest.mock.Mock(stdout="C:/fake\n"),
            subprocess.CalledProcessError(1, ["git", "status", "--porcelain"]),
        ]

        state = inspect_git_worktree(Path("C:/fake"))

        self.assertTrue(state["is_repo"])
        self.assertFalse(state["is_dirty"])
        self.assertEqual("C:/fake", state["repo_root"])

    def test_is_direct_git_worktree_rejects_parent_repo_false_positive(self) -> None:
        repo_state = {"is_repo": True, "is_dirty": False, "repo_root": str(Path("C:/parent").resolve())}
        self.assertFalse(is_direct_git_worktree(Path("C:/parent/child"), repo_state))


class DoctorCommandTests(unittest.TestCase):
    def test_build_doctor_checks_marks_packaged_copier_as_bundled(self) -> None:
        checks = build_doctor_checks(incubation_mode=False)
        copier_check = next(check for check in checks if check.label == "Copier")
        self.assertEqual("bundled", copier_check.packaged_status)

    @patch("prism_cli.cli.shutil.which")
    def test_evaluate_doctor_checks_marks_ios_not_applicable_on_windows(self, mocked_which: object) -> None:
        mocked_which.return_value = None
        results = evaluate_doctor_checks(build_doctor_checks(incubation_mode=True), "Windows", {"mobile-ios"})
        ios_result = next(result for result in results if result.check.label == "Xcode CLI")
        self.assertEqual("not-applicable", ios_result.status)

    @patch("prism_cli.cli.shutil.which")
    def test_summarize_doctor_results_points_to_missing_workflow_tool(self, mocked_which: object) -> None:
        def fake_which(command: str | None) -> str | None:
            if command in {None, "", "task"}:
                return None
            return f"C:/tools/{command}.exe"

        mocked_which.side_effect = fake_which
        results = evaluate_doctor_checks(build_doctor_checks(incubation_mode=True), "Windows", set())
        summary = summarize_doctor_results(results, None)
        rendered = "\n".join(summary)
        self.assertIn("Prism generation", rendered)
        self.assertIn("Next step", rendered)
        self.assertIn("Install go-task", rendered)

    def test_doctor_install_command_returns_windows_hint_for_go_task(self) -> None:
        check = next(check for check in build_doctor_checks(incubation_mode=True) if check.label == "go-task")
        self.assertEqual("npm install -g @go-task/cli", doctor_install_command(check, "Windows"))

    def test_doctor_install_reference_falls_back_to_default(self) -> None:
        check = next(check for check in build_doctor_checks(incubation_mode=True) if check.label == "go-task")
        self.assertEqual("https://taskfile.dev/docs/installation", doctor_install_reference(check, "Windows"))

    @patch("prism_cli.cli.shutil.which")
    def test_summary_reports_generate_now_when_everything_is_ready(self, mocked_which: object) -> None:
        mocked_which.return_value = "C:/tools/found.exe"
        results = evaluate_doctor_checks(build_doctor_checks(incubation_mode=True), "Windows", {"backend", "mobile-android"})
        summary = "\n".join(summarize_doctor_results(results, get_preset("backend-mobile")))
        self.assertIn("You can generate a Prism project now.", summary)

    @patch("prism_cli.cli.shutil.which")
    def test_preset_filtering_excludes_ios_check_for_backend_only(self, mocked_which: object) -> None:
        mocked_which.return_value = "C:/tools/found.exe"
        results = evaluate_doctor_checks(build_doctor_checks(incubation_mode=True), "Windows", {"backend"})
        labels = [result.check.label for result in results]
        self.assertNotIn("Xcode CLI", labels)

    def test_next_doctor_step_for_blocking_check_uses_explicit_hint(self) -> None:
        checks = build_doctor_checks(incubation_mode=True)
        python_check = next(check for check in checks if check.label == "Python")
        result = cli_module.DoctorResult(check=python_check, status="missing", detail=python_check.install_hint)
        self.assertEqual("Install Python before running prism new.", cli_module.next_doctor_step(result))

    @patch("prism_cli.cli.shutil.which")
    def test_choose_next_doctor_result_prefers_platform_relevant_missing_check(self, mocked_which: object) -> None:
        def fake_which(command: str | None) -> str | None:
            if command in {"task", "java"}:
                return None
            return "C:/tools/found.exe"

        mocked_which.side_effect = fake_which
        results = evaluate_doctor_checks(build_doctor_checks(incubation_mode=True), "Windows", {"backend", "mobile-android"})
        next_result = choose_next_doctor_result(results, {"backend", "mobile-android"})
        assert next_result is not None
        self.assertEqual("JDK", next_result.check.label)

    def test_render_doctor_result_includes_docs_for_missing_check(self) -> None:
        go_task = next(check for check in build_doctor_checks(incubation_mode=True) if check.label == "go-task")
        result = cli_module.DoctorResult(
            check=go_task,
            status="missing",
            detail=go_task.install_hint,
            install_command=doctor_install_command(go_task, "Windows"),
            install_reference=doctor_install_reference(go_task, "Windows"),
        )
        rendered = "\n".join(render_doctor_result(result))
        self.assertIn("Docs:", rendered)
        self.assertIn("@go-task/cli", rendered)

    def test_render_doctor_result_for_bundled_status_mentions_prism_management(self) -> None:
        copier = next(check for check in build_doctor_checks(incubation_mode=False) if check.label == "Copier")
        result = cli_module.DoctorResult(check=copier, status="bundled", detail="Bundled with Prism or privately managed in packaged mode.")
        rendered = "\n".join(render_doctor_result(result))
        self.assertIn("Handled by Prism:", rendered)


class IncubationModeTests(unittest.TestCase):
    def test_is_incubating_checkout_requires_git_and_copier_config(self) -> None:
        with patch.object(cli_module, "REPO_ROOT", Path("C:/fake")):
            with patch.object(Path, "exists", side_effect=[True, True]):
                self.assertTrue(is_incubating_checkout())
            with patch.object(Path, "exists", side_effect=[True, False]):
                self.assertFalse(is_incubating_checkout())


class ValidationTargetDetectionTests(unittest.TestCase):
    def test_detects_template_repo(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "copier.yml").write_text("", encoding="utf-8")
            (root / "template").mkdir()
            self.assertEqual("template", detect_validation_target(root))

    def test_detects_generated_project(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "README.md").write_text("", encoding="utf-8")
            (root / "CONTEXT.md").write_text("", encoding="utf-8")
            (root / "knowledge" / "wiki").mkdir(parents=True)
            (root / "knowledge" / "wiki" / "SCHEMA.md").write_text("", encoding="utf-8")
            self.assertEqual("generated-project", detect_validation_target(root))

    def test_returns_unknown_for_unrecognized_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            self.assertEqual("unknown", detect_validation_target(Path(temp_dir)))


class GeneratedProjectStructureTests(unittest.TestCase):
    def test_reports_missing_required_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            errors, warnings, platforms = validate_generated_project_structure(Path(temp_dir))
        self.assertTrue(errors)
        self.assertIn("Missing required generated-project file: README.md", errors)
        self.assertIn("No recognized platform directories were detected.", warnings)
        self.assertEqual([], platforms)

    def test_detects_backend_project_structure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "README.md").write_text("", encoding="utf-8")
            (root / "CONTEXT.md").write_text("", encoding="utf-8")
            (root / "Taskfile.yml").write_text("", encoding="utf-8")
            (root / "knowledge" / "wiki").mkdir(parents=True)
            (root / "knowledge" / "wiki" / "SCHEMA.md").write_text("", encoding="utf-8")
            (root / "backend").mkdir()
            (root / ".github" / "workflows").mkdir(parents=True)
            (root / ".github" / "workflows" / "backend.yml").write_text("", encoding="utf-8")

            errors, warnings, platforms = validate_generated_project_structure(root)

        self.assertEqual([], errors)
        self.assertEqual([], warnings)
        self.assertEqual(["backend"], platforms)

    def test_requires_cloudflare_docs_for_web_projects(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "README.md").write_text("", encoding="utf-8")
            (root / "CONTEXT.md").write_text("", encoding="utf-8")
            (root / "Taskfile.yml").write_text("", encoding="utf-8")
            (root / "knowledge" / "wiki").mkdir(parents=True)
            (root / "knowledge" / "wiki" / "SCHEMA.md").write_text("", encoding="utf-8")
            (root / "web-user-app").mkdir()
            (root / ".github" / "workflows").mkdir(parents=True)
            (root / ".github" / "workflows" / "web-user-app.yml").write_text("", encoding="utf-8")

            errors, _warnings, platforms = validate_generated_project_structure(root)

        self.assertIn("web-user-app", platforms)
        self.assertIn("Web slices were detected but docs/deployment/cloudflare-setup.md is missing.", errors)


class WorkspaceManifestTests(unittest.TestCase):
    def test_load_workspace_reports_missing_manifest_without_failing_detection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = load_workspace(Path(temp_dir))

        self.assertIsNone(result.manifest)
        self.assertEqual("missing-workspace-manifest", result.diagnostics[0].code)
        self.assertEqual("warning", result.diagnostics[0].severity)

    def test_load_workspace_reads_valid_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / MANIFEST_FILE).write_text(
                "schema_version: 1\nproject:\n  name: Prism App\n  platforms:\n    - backend\n",
                encoding="utf-8",
            )

            result = load_workspace(root)

        assert result.manifest is not None
        self.assertEqual(1, result.manifest.schema_version)
        self.assertEqual("Prism App", result.manifest.project_name)
        self.assertEqual(["backend"], result.manifest.platforms)


class WorkspaceStatusTests(unittest.TestCase):
    def test_build_parser_exposes_status_command(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["status", "--json"])

        self.assertEqual(cli_module.cmd_status, args.func)
        self.assertTrue(args.json)

    def test_fresh_workspace_reports_setup_not_initialized(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            create_wiki_skeleton(root)
            write_manifest(root, platforms=["backend"])
            (root / "backend").mkdir()
            write_board_placeholder(root)

            result = build_status(root)
            data = result.to_dict()

        self.assertEqual("not-initialized", result.setup_state)
        self.assertEqual("high", result.confidence)
        self.assertEqual(0, data["facts"]["intake"]["pending"])
        self.assertEqual(0, data["facts"]["intake"]["quarantined"])

    def test_status_counts_pending_and_quarantined_intake(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            create_wiki_skeleton(root)
            write_manifest(root, platforms=["backend"])
            (root / "backend").mkdir()
            (root / "knowledge" / "intake" / "pending" / "PO_BRIEF_TEMPLATE.md").write_text("", encoding="utf-8")
            (root / "knowledge" / "intake" / "pending" / "meeting-notes").mkdir()
            (root / "knowledge" / "intake" / "quarantined" / "conflicting-brief").mkdir()

            result = build_status(root)

        self.assertEqual(1, result.intake.pending)
        self.assertEqual(1, result.intake.quarantined)

    def test_legacy_generated_workspace_without_manifest_is_degraded_not_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "README.md").write_text("", encoding="utf-8")
            (root / "CONTEXT.md").write_text("", encoding="utf-8")
            create_wiki_skeleton(root)

            result = build_status(root)
            data = result.to_dict()

        self.assertEqual("generated-project", result.workspace_kind)
        self.assertEqual("degraded", result.confidence)
        self.assertEqual("degraded", data["confidence"])
        self.assertEqual(["missing-workspace-manifest"], [diagnostic["code"] for diagnostic in data["diagnostics"]])
        self.assertEqual("warning", data["diagnostics"][0]["severity"])

    def test_status_reports_malformed_wiki_schema_issues(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            create_wiki_skeleton(root)
            write_manifest(root, platforms=["backend"])
            (root / "backend").mkdir()
            write_feature(root, status="unknown", owner="qa", advisory_review="pending", platforms=["ios"])

            result = build_status(root)
            codes = {diagnostic["code"] for diagnostic in result.to_dict()["diagnostics"]}

        self.assertEqual("error", result.confidence)
        self.assertIn("invalid-feature-status", codes)
        self.assertIn("invalid-feature-owner", codes)
        self.assertIn("invalid-platform-id", codes)

    def test_status_reports_manifest_filesystem_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            create_wiki_skeleton(root)
            write_manifest(root, platforms=["backend", "mobile-ios"])
            (root / "backend").mkdir()

            result = build_status(root)
            diagnostics = result.to_dict()["diagnostics"]

        self.assertEqual("error", result.confidence)
        self.assertTrue(any(diagnostic["code"] == "manifest-filesystem-drift" for diagnostic in diagnostics))
        self.assertTrue(any("mobile-ios" in diagnostic["message"] for diagnostic in diagnostics))

    def test_status_keeps_plain_directory_unknown_without_generated_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "README.md").write_text("# Plain repo\n", encoding="utf-8")

            result = build_status(root)

        self.assertEqual("unknown", result.workspace_kind)
        self.assertEqual("unknown", result.setup_state)

    def test_status_tracks_lifecycle_and_open_question_counts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            create_wiki_skeleton(root)
            write_manifest(root, platforms=["backend"])
            (root / "backend").mkdir()
            write_feature(
                root,
                status="specified",
                owner="po",
                extra_body=(
                    "## Open questions\n"
                    "| # | Question | Owner | Status |\n"
                    "|---|----------|-------|--------|\n"
                    "| 1 | What happens offline? | designer | open |\n"
                    "| 2 | Should admins approve it? | po | resolved: not needed |\n"
                ),
            )

            result = build_status(root)

        self.assertEqual(1, result.feature_status_counts["specified"])
        self.assertEqual(1, result.feature_owner_counts["po"])
        self.assertEqual({"designer": 1}, result.open_questions_by_owner)

    def test_status_json_exposes_phase_three_envelope_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            create_wiki_skeleton(root)
            write_manifest(root, platforms=["backend"])
            (root / "backend").mkdir()

            data = build_status(root).to_dict()

        self.assertIn("confidence", data)
        self.assertIn("facts", data)
        self.assertIn("blocker_facts", data)
        self.assertIn("required_obligations", data)
        self.assertIn("sources", data)
        self.assertTrue(data["experimental"])
        self.assertNotIn("intake", data)
        self.assertNotIn("wiki", data)
        self.assertNotIn("confidence", data["workspace"])


class WikiQueryTests(unittest.TestCase):
    def test_build_parser_exposes_phase_three_wiki_commands(self) -> None:
        parser = build_parser()

        self.assertEqual(cli_module.cmd_wiki_show, parser.parse_args(["wiki", "show", "F-001"]).func)
        self.assertEqual(cli_module.cmd_wiki_blockers, parser.parse_args(["wiki", "blockers"]).func)
        self.assertEqual(cli_module.cmd_wiki_owner, parser.parse_args(["wiki", "owner", "po"]).func)
        self.assertEqual(cli_module.cmd_wiki_platform, parser.parse_args(["wiki", "platform", "backend"]).func)
        self.assertEqual(cli_module.cmd_wiki_search, parser.parse_args(["wiki", "search", "checkout"]).func)

    def test_wiki_show_returns_feature_and_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            create_wiki_skeleton(root)
            write_feature(root)
            write_index(root, "| F-001 | Checkout | specified | po | not-needed | 2026-01-01 |\n")
            write_platform_requirement(root, feature_id="F-001", platform="backend")
            write_wiki_page(root, "design", "F-001-checkout.md", "feature-id: F-001\n", "## Summary\nCheckout design.\n")

            data = wiki_show(root, "F-001")

        self.assertEqual("wiki show", data["command"])
        self.assertEqual("Checkout", data["facts"]["feature"]["title"])
        self.assertEqual(1, len(data["facts"]["feature"]["platform_requirements"]))
        self.assertEqual(1, len(data["facts"]["feature"]["linked_context"]["design"]))
        self.assertIn("facts", data)
        self.assertNotIn("wiki", data)
        json.dumps(data)

    def test_wiki_show_degrades_when_manifest_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            create_wiki_skeleton(root)
            write_feature(root)
            write_index(root, "| F-001 | Checkout | specified | po | not-needed | 2026-01-01 |\n")

            data = wiki_show(root, "F-001")

        self.assertEqual("degraded", data["confidence"])
        self.assertIn("missing-workspace-manifest", {diagnostic["code"] for diagnostic in data["diagnostics"]})

    def test_wiki_blockers_returns_blocker_facts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            create_wiki_skeleton(root)
            write_feature(root, status="in-dev", owner="dev", advisory_review="pending", platforms=["backend"])
            write_index(root, "| F-001 | Checkout | in-dev | dev | pending | 2026-01-01 |\n")
            write_platform_requirement(root, feature_id="F-001", platform="backend")

            data = wiki_blockers(root)
            blocker_codes = {blocker["code"] for blocker in data["blocker_facts"]}

        self.assertIn("pending-board-review", blocker_codes)
        self.assertEqual(data["blocker_facts"], data["facts"]["blockers"])

    def test_wiki_owner_returns_features_and_open_questions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            create_wiki_skeleton(root)
            write_feature(
                root,
                owner="po",
                extra_body=(
                    "## Open questions\n"
                    "| # | Question | Owner | Status |\n"
                    "|---|----------|-------|--------|\n"
                    "| 1 | Who approves refunds? | po | open |\n"
                ),
            )
            write_index(root, "| F-001 | Checkout | specified | po | not-needed | 2026-01-01 |\n")

            data = wiki_owner(root, "po")

        self.assertEqual(1, data["facts"]["feature_count"])
        self.assertEqual(1, data["facts"]["open_question_count"])

    def test_wiki_platform_returns_features_and_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            create_wiki_skeleton(root)
            write_feature(root, status="ready-for-dev", owner="dev", advisory_review="done", platforms=["backend"])
            write_index(root, "| F-001 | Checkout | ready-for-dev | dev | done | 2026-01-01 |\n")
            write_platform_requirement(root, feature_id="F-001", platform="backend")

            data = wiki_platform(root, "backend")

        self.assertEqual(1, data["facts"]["feature_count"])
        self.assertEqual(1, data["facts"]["platform_requirement_count"])

    def test_wiki_platform_excludes_raw_features_from_active_queue(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            create_wiki_skeleton(root)
            write_feature(root, status="raw", owner="po", platforms=["backend"])
            write_index(root, "| F-001 | Checkout | raw | po | not-needed | 2026-01-01 |\n")

            data = wiki_platform(root, "backend")

        self.assertEqual(0, data["facts"]["feature_count"])

    def test_wiki_search_uses_conservative_substring_matching(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            create_wiki_skeleton(root)
            write_feature(root, extra_body="## Summary\nCheckout supports refunds.\n")
            write_index(root, "| F-001 | Checkout | specified | po | not-needed | 2026-01-01 |\n")

            data = wiki_search(root, "refund")

        self.assertEqual(1, data["facts"]["result_count"])
        self.assertEqual(["body"], data["facts"]["results"][0]["matched_fields"])

    def test_wiki_search_covers_non_feature_wiki_pages(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            create_wiki_skeleton(root)
            write_wiki_page(root, "business-rules", "BR-001-refunds.md", "id: BR-001\ntitle: Refunds\n", "## Rule\nRefunds require approval.\n")
            write_wiki_page(root, "decisions", "ADR-001-refunds.md", "id: ADR-001\ntitle: Refund policy\n", "## Decision\nRefunds stay auditable.\n")

            data = wiki_search(root, "refund")
            result_types = {result["type"] for result in data["facts"]["results"]}

        self.assertIn("business-rule", result_types)
        self.assertIn("decision", result_types)


class GeneratedPromptContractTests(unittest.TestCase):
    def test_docker_compose_template_avoids_yaml_breaking_whitespace_trim(self) -> None:
        text = (cli_module.REPO_ROOT / "template" / "docker-compose.yml.jinja").read_text(encoding="utf-8")

        self.assertNotIn("{% if \"backend\" in platforms -%}", text)
        self.assertNotIn("{% endif -%}", text)
        self.assertIn("  backend:", text)
        self.assertIn("    depends_on:", text)

    def test_generated_read_prompts_prefer_cli_with_fallback(self) -> None:
        command_files = [
            "wiki-show.md.jinja",
            "wiki-blockers.md.jinja",
            "wiki-owner.md.jinja",
            "wiki-platform.md.jinja",
            "wiki-query.md.jinja",
            "lint-wiki.md.jinja",
        ]
        for filename in command_files:
            text = (cli_module.REPO_ROOT / "template" / ".claude" / "commands" / filename).read_text(encoding="utf-8")
            self.assertIn("Primary path: Prism CLI", text)
            self.assertIn("--json", text)
            self.assertIn("Fallback path", text)
            self.assertIn("read-only", text)

    def test_generated_codex_skills_prefer_cli_with_fallback(self) -> None:
        skill_names = ["wiki-show", "wiki-blockers", "wiki-owner", "wiki-platform", "wiki-query", "lint-wiki"]
        for skill_name in skill_names:
            text = (cli_module.REPO_ROOT / "template" / ".agents" / "skills" / skill_name / "SKILL.md.jinja").read_text(encoding="utf-8")
            self.assertIn("Primary path", text)
            self.assertIn("--json", text)
            self.assertIn("Fallback path", text)
            self.assertIn("read-only", text)

    def test_generated_read_prompts_preserve_direct_read_fallback_detail(self) -> None:
        checks = {
            ("commands", "wiki-show.md.jinja"): [
                "knowledge/wiki/design/[F-XXX]-[slug].md",
                "knowledge/wiki/api-contracts/[F-XXX].md",
                "business-rule",
            ],
            ("commands", "wiki-blockers.md.jinja"): [
                "Canonical blocker categories",
                "missing-design",
                "api-contract-not-ready",
            ],
            ("commands", "wiki-query.md.jinja"): [
                "knowledge/wiki/business-rules/",
                "Match classes",
                "exact feature ID",
            ],
            ("commands", "lint-wiki.md.jinja"): [
                "knowledge/wiki/SETTINGS.md",
                "wiki-stale-after-days",
                "do not create lint report files unless the user explicitly asks",
            ],
            ("skills/wiki-show", "SKILL.md.jinja"): [
                "knowledge/wiki/design/[F-XXX]-[slug].md",
                "knowledge/wiki/api-contracts/[F-XXX].md",
                "business-rule",
            ],
            ("skills/wiki-blockers", "SKILL.md.jinja"): [
                "Canonical blocker categories",
                "missing-design",
                "api-contract-not-ready",
            ],
            ("skills/wiki-query", "SKILL.md.jinja"): [
                "knowledge/wiki/business-rules/",
                "Match classes",
                "exact feature ID",
            ],
            ("skills/lint-wiki", "SKILL.md.jinja"): [
                "knowledge/wiki/SETTINGS.md",
                "wiki-stale-after-days",
                "do not create lint report files unless the user explicitly asks",
            ],
        }
        base_paths = {
            "commands": cli_module.REPO_ROOT / "template" / ".claude" / "commands",
            "skills": cli_module.REPO_ROOT / "template" / ".agents",
        }
        for (kind, filename), expected_fragments in checks.items():
            if kind.startswith("skills/"):
                relative_skill = kind.split("/", 1)[1]
                path = base_paths["skills"] / "skills" / relative_skill / filename
            else:
                path = base_paths[kind] / filename
            text = path.read_text(encoding="utf-8")
            for fragment in expected_fragments:
                self.assertIn(fragment, text)

    def test_generated_read_prompts_keep_agent_advice_layer(self) -> None:
        prompt_paths = [
            cli_module.REPO_ROOT / "template" / ".claude" / "commands" / "wiki-show.md.jinja",
            cli_module.REPO_ROOT / "template" / ".claude" / "commands" / "wiki-blockers.md.jinja",
            cli_module.REPO_ROOT / "template" / ".claude" / "commands" / "wiki-owner.md.jinja",
            cli_module.REPO_ROOT / "template" / ".claude" / "commands" / "wiki-platform.md.jinja",
            cli_module.REPO_ROOT / "template" / ".claude" / "commands" / "lint-wiki.md.jinja",
            cli_module.REPO_ROOT / "template" / ".agents" / "skills" / "wiki-show" / "SKILL.md.jinja",
            cli_module.REPO_ROOT / "template" / ".agents" / "skills" / "wiki-blockers" / "SKILL.md.jinja",
            cli_module.REPO_ROOT / "template" / ".agents" / "skills" / "wiki-owner" / "SKILL.md.jinja",
            cli_module.REPO_ROOT / "template" / ".agents" / "skills" / "wiki-platform" / "SKILL.md.jinja",
            cli_module.REPO_ROOT / "template" / ".agents" / "skills" / "lint-wiki" / "SKILL.md.jinja",
        ]
        for path in prompt_paths:
            text = path.read_text(encoding="utf-8")
            self.assertIn("separate facts from advice", text)
            self.assertNotIn("do not recommend next workflow steps unless", text)
            self.assertNotIn("do not recommend workflow steps unless", text)

    def test_schema_defines_canonical_blocker_semantics(self) -> None:
        text = (cli_module.REPO_ROOT / "template" / "knowledge" / "wiki" / "SCHEMA.md").read_text(encoding="utf-8")

        self.assertIn("`missing-design`: any UI-platform feature", text)
        self.assertIn("`api-contract-not-ready`: any feature", text)
        self.assertIn("`cross-platform-dependency`: any platform-requirement page", text)

    def test_wiki_workflow_documents_read_only_lint_default(self) -> None:
        text = (cli_module.REPO_ROOT / "docs" / "wiki-workflow.md").read_text(encoding="utf-8")

        self.assertIn("reports deterministic wiki diagnostics in the response by default", text)
        self.assertIn("only when explicitly requested", text)

    def test_generated_cursor_rules_describe_optional_cli_read_surface(self) -> None:
        text = (cli_module.REPO_ROOT / "template" / ".cursor" / "rules" / "wiki.mdc.jinja").read_text(encoding="utf-8")
        self.assertIn("CLI read surfaces", text)
        self.assertIn("prism wiki show F-XXX --json", text)
        self.assertIn("must not hard-depend on an installed Prism CLI", text)


class WikiLintTests(unittest.TestCase):
    def test_lint_accepts_empty_fresh_wiki(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            create_wiki_skeleton(root)

            result = lint_wiki(root)

        self.assertTrue(result.is_clean)
        self.assertEqual(0, result.feature_count)

    def test_lint_reports_malformed_feature_frontmatter(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            create_wiki_skeleton(root)
            feature_path = root / "knowledge" / "wiki" / "features" / "F-001-broken.md"
            feature_path.write_text(
                "---\nid: F-001\nstatus: unknown\nowner: qa\nadvisory-review: pending\nplatforms: [ios]\n---\n\n## Summary\nBroken.\n",
                encoding="utf-8",
            )

            result = lint_wiki(root)
            codes = {diagnostic.code for diagnostic in result.diagnostics}

        self.assertFalse(result.is_clean)
        self.assertIn("missing-feature-frontmatter", codes)
        self.assertIn("invalid-feature-status", codes)
        self.assertIn("invalid-feature-owner", codes)
        self.assertIn("invalid-platform-id", codes)

    def test_lint_uses_full_feature_id_from_filename_when_frontmatter_id_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            create_wiki_skeleton(root)
            features = root / "knowledge" / "wiki" / "features"
            (features / "F-001-login.md").write_text(
                "---\n"
                "title: Login\n"
                "status: specified\n"
                "owner: po\n"
                "introduced: 2026-01-01\n"
                "last-updated: 2026-01-01\n"
                "platforms: [backend]\n"
                "sources: []\n"
                "advisory-review: not-needed\n"
                "---\n",
                encoding="utf-8",
            )
            (features / "F-002-search.md").write_text(
                "---\n"
                "title: Search\n"
                "status: specified\n"
                "owner: po\n"
                "introduced: 2026-01-01\n"
                "last-updated: 2026-01-01\n"
                "platforms: [backend]\n"
                "sources: []\n"
                "advisory-review: not-needed\n"
                "---\n",
                encoding="utf-8",
            )

            result = lint_wiki(root)
            duplicate_codes = [diagnostic for diagnostic in result.diagnostics if diagnostic.code == "duplicate-feature-id"]

        self.assertEqual([], duplicate_codes)

    def test_lint_reports_feature_missing_from_index(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            create_wiki_skeleton(root)
            write_feature(root)

            result = lint_wiki(root)
            codes = {diagnostic.code for diagnostic in result.diagnostics}

        self.assertIn("feature-missing-from-index", codes)

    def test_lint_reports_index_frontmatter_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            create_wiki_skeleton(root)
            write_feature(root, status="ready-for-design", owner="designer", advisory_review="done")
            write_index(
                root,
                "| F-001 | Checkout | specified | po | pending | 2026-01-01 |\n",
            )

            result = lint_wiki(root)
            drift_messages = [diagnostic.message for diagnostic in result.diagnostics if diagnostic.code == "index-frontmatter-drift"]

        self.assertEqual(3, len(drift_messages))
        self.assertTrue(any("status" in message for message in drift_messages))
        self.assertTrue(any("owner" in message for message in drift_messages))
        self.assertTrue(any("board review" in message for message in drift_messages))

    def test_lint_accepts_gfm_alignment_separator_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            create_wiki_skeleton(root)
            write_feature(root)
            write_index(
                root,
                "| F-001 | Checkout | specified | po | not-needed | 2026-01-01 |\n",
                separator="|:---|:---:|---:|:---|:---|:---|\n",
            )

            result = lint_wiki(root)
            codes = {diagnostic.code for diagnostic in result.diagnostics}

        self.assertNotIn("index-missing-feature", codes)
        self.assertNotIn("malformed-index", codes)

    def test_lint_accepts_utf8_bom_frontmatter(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            create_wiki_skeleton(root)
            write_index(root, "| F-001 | Checkout | specified | po | not-needed | 2026-01-01 |\n")
            feature_path = root / "knowledge" / "wiki" / "features" / "F-001-checkout.md"
            feature_path.write_text(
                "\ufeff---\n"
                "id: F-001\n"
                "title: Checkout\n"
                "status: specified\n"
                "owner: po\n"
                "introduced: 2026-01-01\n"
                "last-updated: 2026-01-01\n"
                "platforms: [backend]\n"
                "sources: []\n"
                "advisory-review: not-needed\n"
                "---\n",
                encoding="utf-8",
            )

            result = lint_wiki(root)
            codes = {diagnostic.code for diagnostic in result.diagnostics}

        self.assertNotIn("malformed-frontmatter", codes)
        self.assertNotIn("missing-feature-frontmatter", codes)

    def test_lint_reports_missing_platform_requirements_for_ready_feature(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            create_wiki_skeleton(root)
            write_feature(root, status="ready-for-dev", owner="dev", advisory_review="done", platforms=["backend", "mobile-ios"])
            write_platform_requirement(root, feature_id="F-001", platform="backend")

            result = lint_wiki(root)
            diagnostics = [diagnostic for diagnostic in result.diagnostics if diagnostic.code == "missing-platform-requirements"]

        self.assertEqual(1, len(diagnostics))
        self.assertIn("mobile-ios", diagnostics[0].message)

    def test_lint_reports_pending_board_review_in_dev(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            create_wiki_skeleton(root)
            write_feature(root, status="in-dev", owner="dev", advisory_review="pending", platforms=["backend"])
            write_platform_requirement(root, feature_id="F-001", platform="backend")

            result = lint_wiki(root)
            codes = {diagnostic.code for diagnostic in result.diagnostics}

        self.assertIn("pending-board-review", codes)

    def test_lint_reports_malformed_open_question_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            create_wiki_skeleton(root)
            write_feature(
                root,
                extra_body=(
                    "## Open questions\n"
                    "| # | Question | Owner | Status |\n"
                    "|---|----------|-------|--------|\n"
                    "| 1 | What happens offline? | qa | maybe |\n"
                ),
            )

            result = lint_wiki(root)
            codes = {diagnostic.code for diagnostic in result.diagnostics}

        self.assertIn("invalid-open-question-owner", codes)
        self.assertIn("invalid-open-question-status", codes)

    def test_lint_reports_missing_advisory_skip_reason(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            create_wiki_skeleton(root)
            write_feature(root, advisory_review="skipped")

            result = lint_wiki(root)
            codes = {diagnostic.code for diagnostic in result.diagnostics}

        self.assertIn("missing-advisory-skip-reason", codes)

    def test_lint_reports_invalid_status_owner_pairing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            create_wiki_skeleton(root)
            write_feature(root, status="done", owner="dev", advisory_review="done")

            result = lint_wiki(root)
            codes = {diagnostic.code for diagnostic in result.diagnostics}

        self.assertIn("invalid-status-owner-pairing", codes)


class WikiGraphTests(unittest.TestCase):
    def _rich_workspace(self, root: Path) -> None:
        create_wiki_skeleton(root)
        write_feature(root, status="ready-for-dev", owner="dev", platforms=["backend"])
        (root / "knowledge" / "wiki" / "features" / "F-002-refunds.md").write_text(
            "---\nid: F-002\ntitle: Refunds\nstatus: raw\nowner: po\nintroduced: 2026-01-01\n"
            "last-updated: 2026-01-01\nplatforms: [backend]\nsources: []\nadvisory-review: not-needed\n---\n\n"
            "## Summary\nRefund handling.\n\n## Related features\n- [F-001](F-001-checkout.md) - refunds follow checkout\n- F-999 does not exist\n",
            encoding="utf-8",
        )
        write_index(
            root,
            "| F-001 | Checkout | ready-for-dev | dev | not-needed | 2026-01-01 |\n"
            "| F-002 | Refunds | raw | po | not-needed | 2026-01-01 |\n",
        )
        write_platform_requirement(root, feature_id="F-001", platform="backend")
        write_wiki_page(root, "design", "F-001-checkout.md", "feature-id: F-001\ntitle: Checkout design\n", "## Summary\nDesign.\n")
        write_wiki_page(root, "api-contracts", "F-001.md", "feature-id: F-001\nversion: 1\nstatus: draft\n", "## Endpoints\nPOST /checkout\n")
        write_wiki_page(root, "advisory", "F-001-review.md", "feature-id: F-001\nreviewed: 2026-01-02\n", "## 1. Conflicts\nNone.\n")
        write_wiki_page(root, "business-rules", "BR-001-refund-window.md", "id: BR-001\ntitle: Refund window\n", "## Affected features\nF-001 must respect the window.\n")
        write_wiki_page(root, "personas", "shopper.md", "id: P-001\nname: Shopper\n", "## Who they are\nUses F-001 daily.\n")
        write_wiki_page(root, "decisions", "ADR-001-payments.md", "id: ADR-001\ntitle: Payments\nstatus: accepted\n", "## Context\nSee [shopper](../personas/shopper.md).\n")

    def test_build_parser_exposes_graph_command(self) -> None:
        parser = build_parser()
        self.assertEqual(cli_module.cmd_wiki_graph, parser.parse_args(["wiki", "graph"]).func)

    def test_edge_rules_carry_expected_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._rich_workspace(root)
            data = build_graph(root)

        edges = {(edge["source"], edge["target"], edge["kind"]): edge["evidence"] for edge in data["facts"]["edges"]}
        self.assertEqual("frontmatter-platforms", edges[("F-001", "platform:backend", "targets")])
        self.assertEqual("frontmatter-feature-id", edges[("F-001", "preq:F-001-backend", "has-requirement")])
        self.assertEqual("frontmatter-feature-id", edges[("F-001", "design:F-001-checkout", "has-design")])
        self.assertEqual("frontmatter-feature-id", edges[("F-001", "api:F-001", "has-contract")])
        self.assertEqual("frontmatter-feature-id", edges[("F-001", "review:F-001-review", "has-review")])
        self.assertEqual("body-reference", edges[("F-001", "BR-001", "constrained-by")])
        self.assertEqual("body-reference", edges[("P-001", "F-001", "serves")])
        self.assertEqual("related-features-section", edges[("F-002", "F-001", "related")])
        self.assertEqual("markdown-link", edges[("ADR-001", "P-001", "links-to")])

    def test_node_ids_and_platform_nodes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._rich_workspace(root)
            data = build_graph(root)

        node_ids = {node["id"] for node in data["facts"]["nodes"]}
        self.assertIn("design:F-001-checkout", node_ids)
        self.assertIn("preq:F-001-backend", node_ids)
        self.assertIn("platform:backend", node_ids)
        self.assertNotIn("platform:mobile-ios", node_ids)

    def test_malformed_page_appears_with_error_health(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            create_wiki_skeleton(root)
            (root / "knowledge" / "wiki" / "features" / "F-003-broken.md").write_text(
                "---\ntitle: Broken\nstatus: raw\nowner: po\n---\n\n## Summary\nBroken.\n",
                encoding="utf-8",
            )
            data = build_graph(root)

        broken = [node for node in data["facts"]["nodes"] if node["id"] == "F-003"]
        self.assertEqual(1, len(broken))
        self.assertEqual("error", broken[0]["health"])
        self.assertEqual("error", data["confidence"])

    def test_dangling_reference_reported_not_fabricated(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._rich_workspace(root)
            data = build_graph(root)

        references = {item["reference"] for item in data["facts"]["dangling_references"]}
        node_ids = {node["id"] for node in data["facts"]["nodes"]}
        self.assertIn("F-999", references)
        self.assertNotIn("F-999", node_ids)

    def test_links_to_suppressed_when_specific_edge_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._rich_workspace(root)
            data = build_graph(root)

        pair_kinds = [edge["kind"] for edge in data["facts"]["edges"] if {edge["source"], edge["target"]} == {"F-001", "F-002"}]
        self.assertEqual(["related"], pair_kinds)

    def test_graph_is_deterministic_and_envelope_matches_query_family(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._rich_workspace(root)
            first = build_graph(root)
            second = build_graph(root)
            show = wiki_show(root, "F-001")

        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))
        self.assertEqual(sorted(show.keys()), sorted(first.keys()))

    def test_mermaid_lifecycle_sanitizes_and_marks_blockers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            create_wiki_skeleton(root)
            write_feature(root, status="in-dev", owner="dev", advisory_review="pending", platforms=["backend"])
            write_index(root, "| F-001 | Checkout | in-dev | dev | pending | 2026-01-01 |\n")
            write_platform_requirement(root, feature_id="F-001", platform="backend")
            data = build_graph(root)
            mermaid = render_mermaid(data, "lifecycle")

        self.assertIn("flowchart LR", mermaid)
        self.assertIn('subgraph s_in_dev["in-dev"]', mermaid)
        self.assertIn("class n_F_001 blocked", mermaid)
        self.assertNotIn('"F-001"|', mermaid)

    def test_mermaid_ego_reports_missing_feature(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            create_wiki_skeleton(root)
            data = build_graph(root)
            mermaid = render_mermaid(data, "ego", feature_id="F-404")

        self.assertIn("No feature page found for F-404", mermaid)

    def test_graph_facts_include_setup_state_and_intake_items(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            create_wiki_skeleton(root)
            (root / "knowledge" / "intake" / "pending" / "payment-alerts-brief.md").write_text("idea", encoding="utf-8")
            (root / "knowledge" / "intake" / "pending" / "PO_BRIEF_TEMPLATE.md").write_text("template", encoding="utf-8")
            (root / "knowledge" / "intake" / "quarantined" / "conflicting-brief").mkdir()
            data = build_graph(root)

        self.assertEqual("not-initialized", data["facts"]["setup_state"])
        self.assertEqual(["payment-alerts-brief.md"], data["facts"]["intake"]["pending"])
        self.assertEqual(["conflicting-brief"], data["facts"]["intake"]["quarantined"])

    def test_feature_nodes_carry_open_questions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            create_wiki_skeleton(root)
            write_feature(
                root,
                extra_body="## Summary\nCheckout.\n\n## Open questions\n"
                "| # | Question | Owner | Status |\n|---|----------|-------|--------|\n"
                "| 1 | What is the offline story? | po | open |\n"
                "| 2 | Empty state? | designer | resolved: minimal |\n",
            )
            write_index(root, "| F-001 | Checkout | specified | po | not-needed | 2026-01-01 |\n")
            data = build_graph(root)

        feature = next(node for node in data["facts"]["nodes"] if node["id"] == "F-001")
        self.assertEqual(2, len(feature["open_questions"]))
        self.assertEqual("po", feature["open_questions"][0]["owner"])
        self.assertEqual("open", feature["open_questions"][0]["status"])

    def test_launcher_offers_dashboard_for_generated_projects(self) -> None:
        generated_values = [action.value for action in build_home_actions("generated-project")]
        directory_values = [action.value for action in build_home_actions("directory")]
        self.assertIn("dashboard", generated_values)
        self.assertNotIn("dashboard", directory_values)


class WikiGraphHtmlTests(unittest.TestCase):
    def _graph_envelope(self, root: Path) -> dict:
        create_wiki_skeleton(root)
        write_feature(root, status="in-dev", owner="dev", platforms=["backend"])
        write_index(root, "| F-001 | Checkout | in-dev | dev | not-needed | 2026-01-01 |\n")
        write_platform_requirement(root, feature_id="F-001", platform="backend")
        return build_graph(root)

    def test_render_html_resolves_all_placeholders(self) -> None:
        from prism_cli.wiki_graph_html import render_html

        with tempfile.TemporaryDirectory() as temp_dir:
            envelope = self._graph_envelope(Path(temp_dir))
            html = render_html(envelope, mode="snapshot", generated_at="2026-06-12T10:00:00")

        self.assertNotIn("__PRISM_GRAPH_DATA__", html)
        self.assertNotIn("__PRISM_CONFIG__", html)
        self.assertNotIn("__PRISM_VENDOR_JS__", html)
        self.assertIn('"command": "wiki graph"'.replace(" ", ""), html.replace(" ", ""))
        self.assertIn("force-graph", html)
        self.assertIn('"mode":"snapshot"'.replace(" ", ""), html.replace(" ", ""))

    def test_render_html_escapes_script_terminators(self) -> None:
        from prism_cli.wiki_graph_html import _embed_json

        embedded = _embed_json({"text": "</script><b>bad</b>"})
        self.assertNotIn("</script>", embedded)

    def test_cmd_wiki_graph_refuses_output_inside_knowledge(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            create_wiki_skeleton(root)
            args = Namespace(
                path=str(root), json=False, mermaid=False, view="lifecycle", feature=None,
                platform=None, html=str(root / "knowledge" / "evil.html"), open=False, serve=False, port=8321,
            )
            with contextlib.redirect_stderr(io.StringIO()):
                exit_code = cli_module.cmd_wiki_graph(args)

        self.assertEqual(cli_module.EXIT_VALIDATION, exit_code)
        self.assertFalse((root / "knowledge" / "evil.html").exists())

    def test_cmd_wiki_graph_open_writes_temp_and_opens_browser(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            create_wiki_skeleton(root)
            args = Namespace(
                path=str(root), json=False, mermaid=False, view="lifecycle", feature=None,
                platform=None, html=None, open=True, serve=False, port=8321,
            )
            with patch.object(cli_module.webbrowser, "open") as mocked_open:
                with contextlib.redirect_stdout(io.StringIO()):
                    exit_code = cli_module.cmd_wiki_graph(args)

        self.assertEqual(0, exit_code)
        mocked_open.assert_called_once()
        self.assertTrue(mocked_open.call_args[0][0].startswith("file://"))

    def test_assets_are_packaged(self) -> None:
        from importlib import resources

        assets = resources.files("prism_cli") / "assets"
        self.assertTrue((assets / "graph_template.html").is_file())
        self.assertTrue((assets / "force-graph.min.js").is_file())

    def test_dashboard_script_declares_graph_before_theme_boot(self) -> None:
        # Regression guard for the boot TDZ crash: setTheme() touches `graph`
        # and runs from the theme initializer, so the declaration must precede it.
        # Full runtime coverage: node scripts/dashboard-boot-check.js <export.html>
        from importlib import resources

        template = (resources.files("prism_cli") / "assets" / "graph_template.html").read_text(encoding="utf-8")
        declaration = template.index("let graph = null;")
        theme_boot = template.index("(function initTheme()")
        self.assertLess(declaration, theme_boot)


def create_wiki_skeleton(root: Path) -> None:
    wiki = root / "knowledge" / "wiki"
    (wiki / "features").mkdir(parents=True)
    (wiki / "platform-requirements").mkdir()
    (wiki / "advisory").mkdir()
    for directory in ("personas", "business-rules", "design", "api-contracts", "decisions"):
        (wiki / directory).mkdir()
    (root / "knowledge" / "intake" / "pending").mkdir(parents=True)
    (root / "knowledge" / "intake" / "quarantined").mkdir(parents=True)
    (wiki / "SCHEMA.md").write_text("# Schema\n", encoding="utf-8")
    (wiki / "SETTINGS.md").write_text("---\nwiki-stale-after-days: 14\n---\n", encoding="utf-8")
    write_index(root)


def write_manifest(root: Path, project_name: str = "Prism App", platforms: list[str] | None = None) -> None:
    platforms = platforms or ["backend"]
    platform_lines = "\n".join(f"    - {platform}" for platform in platforms)
    (root / MANIFEST_FILE).write_text(
        "schema_version: 1\n"
        "project:\n"
        f"  name: {project_name}\n"
        "  slug: prism-app\n"
        "  platforms:\n"
        f"{platform_lines}\n",
        encoding="utf-8",
    )


def write_board_placeholder(root: Path) -> None:
    (root / "knowledge" / "wiki" / "advisory" / "BOARD.md").write_text(
        "# Advisory Board\n\n"
        "This file will be generated by /setup-project. Run that command first.\n",
        encoding="utf-8",
    )


def write_index(root: Path, rows: str = "", separator: str = "|----|---------|--------|-------|--------------|------------|\n") -> None:
    (root / "knowledge" / "wiki" / "index.md").write_text(
        "# Feature Status Board\n\n"
        "| ID | Feature | Status | Owner | Board Review | Introduced |\n"
        f"{separator}"
        f"{rows}"
        "\n## Other wiki pages\n",
        encoding="utf-8",
    )


def write_feature(
    root: Path,
    status: str = "specified",
    owner: str = "po",
    advisory_review: str = "not-needed",
    platforms: list[str] | None = None,
    extra_body: str = "## Summary\nCheckout.\n",
) -> None:
    platforms = platforms or ["backend"]
    platform_yaml = "[" + ", ".join(platforms) + "]"
    (root / "knowledge" / "wiki" / "features" / "F-001-checkout.md").write_text(
        "---\n"
        "id: F-001\n"
        "title: Checkout\n"
        f"status: {status}\n"
        f"owner: {owner}\n"
        "introduced: 2026-01-01\n"
        "last-updated: 2026-01-01\n"
        f"platforms: {platform_yaml}\n"
        "sources: []\n"
        f"advisory-review: {advisory_review}\n"
        "---\n\n"
        f"{extra_body}\n",
        encoding="utf-8",
    )


def write_platform_requirement(root: Path, feature_id: str, platform: str, status: str = "pending") -> None:
    (root / "knowledge" / "wiki" / "platform-requirements" / f"{feature_id}-{platform}.md").write_text(
        "---\n"
        f"feature-id: {feature_id}\n"
        f"platform: {platform}\n"
        f"status: {status}\n"
        "---\n\n"
        "## What to build\nImplement it.\n",
        encoding="utf-8",
    )


def write_wiki_page(root: Path, directory: str, filename: str, frontmatter: str, body: str) -> None:
    target_dir = root / "knowledge" / "wiki" / directory
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / filename).write_text(
        "---\n"
        f"{frontmatter}"
        "---\n\n"
        f"{body}",
        encoding="utf-8",
    )
