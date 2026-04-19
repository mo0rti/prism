from __future__ import annotations

import re
import subprocess
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from prism_cli import cli as cli_module
from prism_cli import ui as ui_module
from prism_cli.cli import (
    DEFAULT_GENERATED_DIR,
    build_home_actions,
    build_parser,
    build_doctor_checks,
    choose_next_doctor_result,
    clear_directory_contents,
    detect_validation_target,
    detect_launch_context,
    dispatch_home_action,
    doctor_install_command,
    doctor_install_reference,
    evaluate_doctor_checks,
    ensure_copier_answers_file,
    format_data_value,
    inspect_git_worktree,
    is_incubating_checkout,
    load_answers_file,
    load_copier_answers,
    normalize_template_path,
    parse_copier_progress_line,
    parse_multiselect_response,
    parse_preset_selection,
    format_copier_progress_line,
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
from prism_cli.ui import SelectOption, colorize, filter_select_options, panel, review_key_value, truncate_visible, visible_length


class ValidateAnswersTests(unittest.TestCase):
    def test_requires_at_least_one_platform(self) -> None:
        errors, warnings = validate_answers({"platforms": [], "auth_methods": []})
        self.assertIn("At least one platform must be selected.", errors)
        self.assertEqual([], warnings)

    def test_requires_auth_for_user_web(self) -> None:
        errors, _warnings = validate_answers({"platforms": ["web-user-app"], "auth_methods": []})
        self.assertIn("User Web App currently requires at least one auth method.", errors)

    def test_requires_password_for_admin_portal(self) -> None:
        errors, _warnings = validate_answers({"platforms": ["web-admin-portal"], "auth_methods": ["google"]})
        self.assertIn("Admin Web Portal currently requires Username + Password auth.", errors)

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
        self.assertEqual("generated", DEFAULT_GENERATED_DIR)


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

    @patch("prism_cli.cli.subprocess.run")
    def test_inspect_git_worktree_handles_status_failure(self, mocked_run: object) -> None:
        mocked_run.side_effect = [
            unittest.mock.Mock(stdout="true\n"),
            subprocess.CalledProcessError(1, ["git", "status", "--porcelain"]),
        ]

        state = inspect_git_worktree(Path("C:/fake"))

        self.assertTrue(state["is_repo"])
        self.assertFalse(state["is_dirty"])


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
