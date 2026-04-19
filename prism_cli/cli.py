"""Prism CLI entry point."""

from __future__ import annotations

import argparse
import contextlib
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from collections import deque
from pathlib import Path
from typing import Any

import yaml

from prism_cli import __version__
from prism_cli.presets import (
    ALL_AUTH_CHOICES,
    ALL_PLATFORM_CHOICES,
    DEFAULT_ANSWERS,
    PRESETS,
    get_preset,
    merge_answers,
)
from prism_cli.ui import (
    ANSI_PATTERN,
    PALETTE_SIGNAL,
    STYLE,
    SelectOption,
    colorize,
    error,
    header,
    info,
    interactive_command_palette,
    interactive_multiselect,
    interactive_single_select,
    maturity_badge,
    panel,
    review_key_value,
    section,
    session_panel,
    success,
    supports_unicode,
    terminal_width,
    truncate_visible,
    visible_length,
    warn,
)


EXIT_USAGE = 2
EXIT_VALIDATION = 3
EXIT_ENVIRONMENT = 4
EXIT_COPIER = 5

REPO_ROOT = Path(__file__).resolve().parent.parent
COPIER_ANSWERS_FILE = ".copier-answers.yml"
DEFAULT_GENERATED_DIR = "generated"
COPIER_PROGRESS_PATTERN = re.compile(r"^\s*(create|identical|overwrite|conflict|skip|remove)\s+(.+?)\s*$")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        return args.func(args)
    except KeyboardInterrupt:
        print()
        print(warn("Prism cancelled."))
        return 130


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="prism",
        description="Prism CLI for guided multi-platform project generation.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.set_defaults(func=cmd_home, parser=parser)
    subparsers = parser.add_subparsers(dest="command")

    presets_parser = subparsers.add_parser("presets", help="Show recommended Prism presets.")
    presets_parser.set_defaults(func=cmd_presets)

    doctor_parser = subparsers.add_parser("doctor", help="Check local prerequisites.")
    doctor_parser.set_defaults(func=cmd_doctor)

    validate_parser = subparsers.add_parser("validate", help="Validate the template repo or a generated Prism project.")
    validate_parser.add_argument("path", nargs="?", default=".", help="Path to validate. Defaults to the current directory.")
    validate_parser.add_argument(
        "--kind",
        choices=["auto", "template", "generated-project"],
        default="auto",
        help="Validation target type. Defaults to auto-detect.",
    )
    validate_parser.add_argument(
        "--template-mode",
        choices=["full", "contract", "backend-smoke"],
        default="contract",
        help="Validation mode when validating the template repository.",
    )
    validate_parser.set_defaults(func=cmd_validate)

    update_parser = subparsers.add_parser("update", help="Update a generated Prism project from its original template.")
    update_parser.add_argument("path", nargs="?", default=".", help="Generated project path. Defaults to the current directory.")
    update_parser.add_argument(
        "--strategy",
        choices=["auto", "update", "recopy"],
        default="auto",
        help="Use Copier's smart update when possible, or force a recopy-based refresh.",
    )
    update_parser.add_argument("--yes", action="store_true", help="Skip the confirmation prompt.")
    update_parser.set_defaults(func=cmd_update)

    new_parser = subparsers.add_parser("new", help="Create a Prism project.")
    new_parser.add_argument("--preset", choices=[preset.slug for preset in PRESETS])
    new_parser.add_argument("--project-name")
    new_parser.add_argument("--description")
    new_parser.add_argument("--package-identifier")
    new_parser.add_argument("--github-org")
    new_parser.add_argument("--dest")
    new_parser.add_argument("--template", default=str(REPO_ROOT))
    new_parser.add_argument("--answers", help="Path to a Prism YAML answers file.")
    new_parser.add_argument("--debug", action="store_true", help="Show raw resolved answers.")
    new_parser.add_argument("--yes", action="store_true", help="Skip the confirmation prompt.")
    new_parser.set_defaults(func=cmd_new)

    return parser


def cmd_home(args: argparse.Namespace) -> int:
    current_dir = Path.cwd().resolve()
    context_kind, context_label = detect_launch_context(current_dir)

    print(header("Choose a Prism command"))
    print(session_panel(__version__, str(current_dir), context_label))
    print()

    actions = build_home_actions(context_kind)
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print(section("Available commands"))
        for action in actions:
            print(f"- {action.label}: {action.description}")
        print()
        args.parser.print_help()
        return 0

    while True:
        selected = interactive_single_select("Prism actions", actions, allow_palette=True)
        if selected is PALETTE_SIGNAL:
            selected = interactive_command_palette("Command palette", actions)
            if selected is None:
                continue
        return dispatch_home_action(selected, args.parser)


def detect_launch_context(path: Path) -> tuple[str, str]:
    kind = detect_validation_target(path)
    if kind == "template":
        return "template", "template repo"
    if kind == "generated-project":
        return "generated-project", "generated project"
    return "directory", "plain directory"


def build_home_actions(context_kind: str) -> list[SelectOption]:
    actions = [
        SelectOption(
            value="new",
            label="New Project",
            meta="[new]",
            description="Create a new Prism project with guided defaults.",
            accent="action",
        ),
        SelectOption(
            value="presets",
            label="Browse Presets",
            meta="[presets]",
            description="See recommended starting paths and maturity guidance.",
            accent="action",
        ),
        SelectOption(
            value="doctor",
            label="Doctor",
            meta="[doctor]",
            description="Check the local tools Prism expects for generation and workflows.",
            accent="action",
        ),
    ]

    if context_kind == "template":
        actions.append(
            SelectOption(
                value="validate",
                label="Validate Template Repo",
                meta="[validate]",
                description="Run validation for the current Prism template repository.",
                accent="action",
            )
        )
    elif context_kind == "generated-project":
        actions.extend(
            [
                SelectOption(
                    value="validate",
                    label="Validate Generated Project",
                    meta="[validate]",
                    description="Run structural validation for the current generated Prism project.",
                    accent="action",
                ),
                SelectOption(
                    value="update",
                    label="Update Generated Project",
                    meta="[update]",
                    description="Refresh the current generated project from its Prism template.",
                    accent="action",
                ),
            ]
        )
    else:
        actions.append(
            SelectOption(
                value="validate",
                label="Validate Current Directory",
                meta="[validate]",
                description="Try to validate the current directory as a template repo or generated project.",
                accent="action",
            )
        )

    actions.extend(
        [
            SelectOption(
                value="help",
                label="Help",
                meta="[help]",
                description="Show Prism CLI help and the direct command forms.",
                accent="action",
            ),
            SelectOption(
                value="exit",
                label="Exit",
                meta="[exit]",
                description="Leave the Prism launcher.",
                accent="action",
            ),
        ]
    )
    return actions


def dispatch_home_action(selected: str, parser: argparse.ArgumentParser) -> int:
    if selected == "exit":
        return 0
    if selected == "help":
        parser.print_help()
        return 0

    parsed = parser.parse_args([selected])
    parsed.from_launcher = True
    return parsed.func(parsed)


def show_command_intro(args: argparse.Namespace, subtitle: str) -> None:
    if getattr(args, "from_launcher", False):
        print()
        print(section(subtitle))
        print()
        return
    print(header(subtitle))


def cmd_presets(_args: argparse.Namespace) -> int:
    show_command_intro(_args, "Recommended generation paths")
    for preset in PRESETS:
        print(f"{preset.slug:<24} {maturity_badge(preset.maturity)}")
        print(f"  {preset.label}: {preset.summary}")
        for note in preset.notes:
            print(f"  {warn(note)}")
        print()
    return 0


def cmd_doctor(_args: argparse.Namespace) -> int:
    show_command_intro(_args, "Environment checks for generation and common workflows")
    system = platform.system()
    incubation_mode = is_incubating_checkout()
    body = [
        f"OS: {system}",
        f"Python: {platform.python_version()}",
        f"Mode: {'incubation' if incubation_mode else 'packaged/runtime'}",
        f"Repo: {REPO_ROOT if incubation_mode else 'n/a'}",
    ]
    print(panel("Environment", body))
    print()

    checks = [
        ("Python", "Required to generate", lambda: shutil.which("python")),
        ("Node.js", "Required for shared generated tooling", lambda: shutil.which("node")),
        ("go-task", "Required for generated task commands", lambda: shutil.which("task")),
        ("Docker", "Common backend/container workflow", lambda: shutil.which("docker")),
        ("JDK", "Backend and Android workflows", lambda: shutil.which("java")),
    ]
    if incubation_mode:
        checks.insert(1, ("Copier", "Required to generate in incubation mode", lambda: shutil.which("copier")))

    failed_required = False
    for label, note, resolver in checks:
        resolved = resolver()
        if resolved:
            print(f"[ok] {label:<10} {resolved}")
            print(f"     {note}")
        else:
            print(f"[missing] {label:<10} {note}")
            if label in {"Python", "Copier"}:
                failed_required = True

    if not incubation_mode:
        print("[managed] Copier     Expected to be bundled or privately managed in packaged mode")

    print()
    if system == "Darwin":
        print(section("macOS-only iOS checks"))
        for label, command in (("xcodegen", "xcodegen"), ("fastlane", "fastlane"), ("Xcode CLI", "xcodebuild")):
            resolved = shutil.which(command)
            if resolved:
                print(f"[ok] {label:<10} {resolved}")
            else:
                print(f"[missing] {label:<10} Optional for iOS validation on macOS.")
    else:
        print(section("iOS checks"))
        print("Skipped: iOS build tooling checks are only applicable on macOS.")

    print()
    if failed_required:
        print(error("Generation prerequisites are missing. Install the required tools before running `prism new`."))
        return EXIT_ENVIRONMENT

    print(success("Core generation prerequisites look good."))
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    target_path = Path(args.path).expanduser().resolve()
    kind = args.kind if args.kind != "auto" else detect_validation_target(target_path)

    show_command_intro(args, "Validate template integrity or generated project structure")
    print(panel("Target", [f"Path: {target_path}", f"Kind: {kind}"]))
    print()

    if kind == "template":
        return validate_template_repo(target_path, args.template_mode)
    if kind == "generated-project":
        return validate_generated_project(target_path)

    print(error("Could not determine whether the target is the template repo or a generated Prism project."), file=sys.stderr)
    print(info("Tip: pass `--kind template` or `--kind generated-project` explicitly."), file=sys.stderr)
    return EXIT_VALIDATION


def cmd_update(args: argparse.Namespace) -> int:
    project_path = Path(args.path).expanduser().resolve()
    if detect_validation_target(project_path) != "generated-project":
        print(error("`prism update` must be run against a generated Prism project."), file=sys.stderr)
        return EXIT_VALIDATION

    repo_state = inspect_git_worktree(project_path)
    if not repo_state["is_repo"]:
        print(error("`prism update` requires the generated project to be under git version control."), file=sys.stderr)
        print(info("Initialize a git repository and commit the current generated state before updating."), file=sys.stderr)
        return EXIT_VALIDATION
    if repo_state["is_dirty"]:
        print(error("`prism update` requires a clean git working tree."), file=sys.stderr)
        print(info("Commit or stash local changes in the generated project, then retry."), file=sys.stderr)
        return EXIT_VALIDATION

    answers_path = project_path / COPIER_ANSWERS_FILE
    answers_data = load_copier_answers(answers_path)
    if answers_data is None:
        print(error(f"Missing {COPIER_ANSWERS_FILE} in generated project: {project_path}"), file=sys.stderr)
        print(info("Generate the project with the Prism CLI first, or add a valid Copier answers file before updating."), file=sys.stderr)
        return EXIT_VALIDATION

    strategy = resolve_update_strategy(args.strategy, answers_data)
    src_path = answers_data.get("_src_path")
    review_lines = [
        f"Project: {project_path}",
        f"Answers file: {answers_path.name}",
        f"Template source: {src_path or 'unknown'}",
        f"Strategy: {strategy}",
    ]
    show_command_intro(args, "Update a generated project from its original template")
    print(panel("Review", review_lines))
    print()

    if not args.yes and not confirm("Update this Prism project now?", default=True):
        print(warn("Update cancelled."))
        return 0

    return run_copier_update(project_path, answers_data, strategy)


def cmd_new(args: argparse.Namespace) -> int:
    if args.answers and args.preset:
        print(error("`--answers` and `--preset` cannot be used together in v1."), file=sys.stderr)
        return EXIT_USAGE

    show_command_intro(args, "Scaffold a multi-platform project with guided defaults")
    answer_file_data = load_answers_file(args.answers) if args.answers else None
    if answer_file_data is None and args.answers:
        return EXIT_VALIDATION

    if args.answers:
        template_path = args.template if args.template != str(REPO_ROOT) else answer_file_data.get("template_ref", str(REPO_ROOT))
        destination = args.dest or answer_file_data.get("destination")
        answers = dict(answer_file_data.get("answers", {}))
    else:
        template_path = args.template
        destination = args.dest
        answers = {}

    if not args.answers:
        preset_answers = resolve_preset_answers(args)
        if preset_answers is None:
            return EXIT_USAGE
        answers = merge_answers(answers, preset_answers)

    cli_overrides = {
        "project_name": args.project_name,
        "description": args.description,
        "package_identifier": args.package_identifier,
        "github_org": args.github_org,
    }
    for key, value in cli_overrides.items():
        if value:
            answers[key] = value

    merged_answers = merge_answers(DEFAULT_ANSWERS, answers)
    if not merged_answers.get("project_name"):
        if sys.stdin.isatty():
            merged_answers["project_name"] = prompt_text("Project name")
        else:
            print(error("Project name is required."), file=sys.stderr)
            return EXIT_VALIDATION

    if destination is None:
        if sys.stdin.isatty():
            destination = prompt_text(
                "Where should Prism create the project?",
                DEFAULT_GENERATED_DIR,
            )
        else:
            print(error("Destination is required in non-interactive mode. Use `--dest` or an answers file."), file=sys.stderr)
            return EXIT_VALIDATION

    dest_path = Path(destination).expanduser()
    validation_errors, validation_warnings = validate_answers(merged_answers)
    if validation_errors:
        for message in validation_errors:
            print(error(message), file=sys.stderr)
        return EXIT_VALIDATION

    render_summary(merged_answers, dest_path, template_path, validation_warnings)
    if args.debug:
        print(section("Resolved answers"))
        for key in sorted(merged_answers):
            print(f"- {key}: {merged_answers[key]}")
        print()

    if not args.yes and not confirm("Generate this Prism project?", default=True):
        print(warn("Generation cancelled."))
        return 0

    destination_result = prepare_generation_destination(dest_path)
    if destination_result is not None:
        return destination_result

    return run_copier(template_path, dest_path, merged_answers)


def detect_validation_target(path: Path) -> str:
    if (path / "copier.yml").exists() and (path / "template").exists():
        return "template"
    if (path / "README.md").exists() and (path / "CONTEXT.md").exists() and (path / "knowledge" / "wiki" / "SCHEMA.md").exists():
        return "generated-project"
    return "unknown"


def validate_template_repo(path: Path, mode: str) -> int:
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if not shell:
        print(error("PowerShell is required to validate the template repository."), file=sys.stderr)
        return EXIT_ENVIRONMENT

    using_staged_template = should_stage_template_path(str(path))
    with staged_template_path(str(path)) as effective_template:
        effective_path = Path(effective_template)
        script_path = effective_path / "scripts" / "validate-template.ps1"
        if not script_path.exists():
            print(error(f"Template validation script not found: {script_path}"), file=sys.stderr)
            return EXIT_VALIDATION

        print(section("Template validation"))
        if using_staged_template:
            print(info("Using a temporary clean copy of the local template for validation."))
        print(info(f"Running {script_path.name} in `{mode}` mode..."))
        print()
        command = [shell, "-ExecutionPolicy", "Bypass", "-File", str(script_path), "-Mode", mode]
        result = subprocess.run(command, cwd=str(effective_path))
        if result.returncode != 0:
            print(error("Template validation failed."), file=sys.stderr)
            return EXIT_COPIER

    print()
    print(success("Template validation passed."))
    return 0


def validate_generated_project(path: Path) -> int:
    errors, warnings, detected_platforms = validate_generated_project_structure(path)

    if detected_platforms:
        labels = dict(ALL_PLATFORM_CHOICES)
        print(section("Detected platforms"))
        print(", ".join(labels[p] for p in detected_platforms))
        print()

    if warnings:
        print(section("Warnings"))
        for warning_message in warnings:
            print(f"- {warn(warning_message)}")
        print()

    if errors:
        print(section("Errors"))
        for error_message in errors:
            print(f"- {error(error_message)}")
        return EXIT_VALIDATION

    checks = [
        "README.md present",
        "CONTEXT.md present",
        "knowledge/wiki/SCHEMA.md present",
        "Taskfile.yml present",
        "platform directories and key workflows present",
    ]
    print(panel("Validation passed", checks))
    return 0


def validate_generated_project_structure(path: Path) -> tuple[list[str], list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    required_paths = [
        ("README.md", path / "README.md"),
        ("CONTEXT.md", path / "CONTEXT.md"),
        ("knowledge/wiki/SCHEMA.md", path / "knowledge" / "wiki" / "SCHEMA.md"),
        ("Taskfile.yml", path / "Taskfile.yml"),
    ]
    for label, required_path in required_paths:
        if not required_path.exists():
            errors.append(f"Missing required generated-project file: {label}")

    detected_platforms: list[str] = []
    workflows = {
        "backend": ".github/workflows/backend.yml",
        "web-user-app": ".github/workflows/web-user-app.yml",
        "web-admin-portal": ".github/workflows/web-admin-portal.yml",
        "mobile-android": ".github/workflows/mobile-android.yml",
        "mobile-ios": ".github/workflows/mobile-ios.yml",
    }

    for platform_id, _label in ALL_PLATFORM_CHOICES:
        platform_dir = path / platform_id
        if platform_dir.exists():
            detected_platforms.append(platform_id)
            workflow_path = path / workflows[platform_id]
            if not workflow_path.exists():
                errors.append(f"Missing workflow for detected platform `{platform_id}`: {workflows[platform_id]}")

    if not detected_platforms:
        warnings.append("No recognized platform directories were detected.")

    if any(platform_id in detected_platforms for platform_id in ("web-user-app", "web-admin-portal")):
        cloudflare_doc = path / "docs" / "deployment" / "cloudflare-setup.md"
        if not cloudflare_doc.exists():
            errors.append("Web slices were detected but docs/deployment/cloudflare-setup.md is missing.")

    return errors, warnings, detected_platforms


def load_answers_file(path_str: str) -> dict[str, Any] | None:
    path = Path(path_str).expanduser()
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    except OSError as exc:
        print(error(f"Unable to read answers file: {exc}"), file=sys.stderr)
        return None
    except yaml.YAMLError as exc:
        print(error(f"Invalid YAML in answers file: {exc}"), file=sys.stderr)
        return None

    if not isinstance(data, dict):
        print(error("Answers file must be a mapping."), file=sys.stderr)
        return None
    if data.get("schema_version") != 1:
        print(error("Answers file schema_version must be 1."), file=sys.stderr)
        return None
    answers = data.get("answers")
    if not isinstance(answers, dict):
        print(error("Answers file must include an `answers` mapping."), file=sys.stderr)
        return None
    return data


def load_copier_answers(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    except OSError:
        return None
    except yaml.YAMLError:
        return None

    if not isinstance(data, dict):
        return None
    if "_src_path" not in data:
        return None
    return data


def resolve_update_strategy(requested: str, answers_data: dict[str, Any]) -> str:
    if requested != "auto":
        return requested

    src_path = str(answers_data.get("_src_path", ""))
    if answers_data.get("_commit") and supports_versioned_update(src_path):
        return "update"
    return "recopy"


def resolve_preset_answers(args: argparse.Namespace) -> dict[str, Any] | None:
    if args.preset:
        preset = get_preset(args.preset)
        if preset is None:
            print(error(f"Unknown preset: {args.preset}"), file=sys.stderr)
            return None
        print(info(f"Using preset: {preset.label} ({preset.maturity})"))
        return dict(preset.answers)

    selected = prompt_preset()
    if selected == "advanced":
        return prompt_advanced_answers()

    preset = get_preset(selected)
    if preset is None:
        print(error(f"Unknown preset selection: {selected}"), file=sys.stderr)
        return None
    print(info(f"Using preset: {preset.label} ({preset.maturity})"))
    for note in preset.notes:
        print(warn(note))
    return dict(preset.answers)


def prompt_preset() -> str:
    if sys.stdin.isatty() and sys.stdout.isatty():
        options = [
            SelectOption(
                value=preset.slug,
                label=preset.label,
                meta=f"[{preset.slug}]",
                description=preset.summary,
                notes=preset.notes,
                accent=preset.maturity,
            )
            for preset in PRESETS
        ]
        options.append(
            SelectOption(
                value="advanced",
                label="Advanced",
                meta="[custom-selection]",
                description="Build a custom Prism configuration from scratch.",
                accent="advanced",
            )
        )
        return interactive_single_select("Recommended presets", options)

    print(section("Recommended presets"))
    for index, preset in enumerate(PRESETS, start=1):
        print(f"{index}. {preset.label} [{preset.slug}] - {maturity_badge(preset.maturity)}")
        print(f"   {preset.summary}")
        for note in preset.notes:
            print(f"   {warn(note)}")
    advanced_index = len(PRESETS) + 1
    print(f"{advanced_index}. Advanced - custom selection")
    print()

    while True:
        raw = input("Choose a path: ").strip()
        selected = parse_preset_selection(raw)
        if selected is not None:
            return selected
        print(warn("Enter the number for one of the options above."))


def parse_preset_selection(raw: str) -> str | None:
    if not raw.isdigit():
        return None
    selected = int(raw)
    if 1 <= selected <= len(PRESETS):
        return PRESETS[selected - 1].slug
    if selected == len(PRESETS) + 1:
        return "advanced"
    return None


def prompt_advanced_answers() -> dict[str, Any]:
    print()
    print(section("Advanced configuration"))
    project_name = prompt_text("Project name")
    description = prompt_text("Description", DEFAULT_ANSWERS["description"])
    package_identifier = prompt_text("Package identifier", f"com.example.{slugify(project_name).replace('-', '')}")
    github_org = prompt_text("GitHub organization or username", "")
    platforms = prompt_multiselect("Select platforms", ALL_PLATFORM_CHOICES, default_values=["backend", "mobile-android"])
    auth_default = DEFAULT_ANSWERS["auth_methods"] if any(p in platforms for p in ("web-user-app", "web-admin-portal")) else []
    auth_methods = prompt_multiselect("Select auth methods", ALL_AUTH_CHOICES, default_values=auth_default, allow_empty=True)
    use_docker = prompt_bool("Include Docker Compose?", True)

    return {
        "project_name": project_name,
        "description": description,
        "package_identifier": package_identifier,
        "github_org": github_org,
        "platforms": platforms,
        "auth_methods": auth_methods,
        "use_docker": use_docker,
    }


def prompt_text(label: str, default: str | None = None) -> str:
    while True:
        prompt = f"{label}"
        if default is not None:
            prompt += f" [{default}]"
        prompt += ": "
        value = input(prompt).strip()
        if value:
            return value
        if default is not None:
            return default
        print(warn(f"{label} is required."))


def prompt_bool(label: str, default: bool) -> bool:
    suffix = "Y/n" if default else "y/N"
    while True:
        raw = input(f"{label} [{suffix}]: ").strip().lower()
        if not raw:
            return default
        if raw in {"y", "yes"}:
            return True
        if raw in {"n", "no"}:
            return False
        print(warn("Enter y or n."))


def prompt_multiselect(
    label: str,
    choices: tuple[tuple[str, str], ...],
    default_values: list[str] | tuple[str, ...] | None = None,
    allow_empty: bool = False,
) -> list[str]:
    defaults = list(default_values or [])
    if sys.stdin.isatty() and sys.stdout.isatty():
        return interactive_multiselect(label, choices, defaults, allow_empty=allow_empty)

    while True:
        print(label)
        for index, (key, description) in enumerate(choices, start=1):
            default_marker = " (default)" if key in defaults else ""
            print(f"  {index}. {description} [{key}]{default_marker}")
        raw = input("Choose comma-separated numbers: ").strip()
        parsed = parse_multiselect_response(raw, choices, defaults, allow_empty)
        if parsed is not None:
            selected_keys, used_default = parsed
            if used_default or selected_keys or allow_empty:
                return selected_keys
        print(warn("Enter one or more valid numbers separated by commas."))


def parse_multiselect_response(
    raw: str,
    choices: tuple[tuple[str, str], ...],
    defaults: list[str],
    allow_empty: bool,
) -> tuple[list[str], bool] | None:
    if not raw and defaults:
        return defaults, True
    if not raw and allow_empty:
        return [], False

    selected_keys: list[str] = []
    for item in [part.strip() for part in raw.split(",") if part.strip()]:
        if not item.isdigit():
            return None
        idx = int(item)
        if idx < 1 or idx > len(choices):
            return None
        key = choices[idx - 1][0]
        if key not in selected_keys:
            selected_keys.append(key)
    if selected_keys or allow_empty:
        return selected_keys, False
    return None


def prepare_generation_destination(dest_path: Path) -> int | None:
    if not dest_path.exists():
        return None
    if dest_path.is_file():
        print(error(f"Destination already exists as a file: {dest_path}"), file=sys.stderr)
        return EXIT_VALIDATION
    if not any(dest_path.iterdir()):
        return None

    print(warn(f"Destination already exists and is not empty: {dest_path}"))
    if not sys.stdin.isatty():
        print(error("Refusing to delete an existing non-empty destination in non-interactive mode."), file=sys.stderr)
        print(info("Choose an empty destination or remove the existing contents first."), file=sys.stderr)
        return EXIT_VALIDATION

    if not confirm("Delete the existing contents and continue?", default=False):
        print(warn("Generation cancelled."))
        return 0

    clear_directory_contents(dest_path)
    print(info(f"Cleared existing contents in `{dest_path}`."))
    print()
    return None


def clear_directory_contents(path: Path) -> None:
    for child in path.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def validate_answers(answers: dict[str, Any]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    platforms = answers.get("platforms", [])
    auth_methods = answers.get("auth_methods", [])

    if not platforms:
        errors.append("At least one platform must be selected.")
    if "web-user-app" in platforms and not auth_methods:
        errors.append("User Web App currently requires at least one auth method.")
    if "web-admin-portal" in platforms and "password" not in auth_methods:
        errors.append("Admin Web Portal currently requires Username + Password auth.")
    if "apple" in auth_methods:
        warnings.append("Apple Sign-In remains experimental.")
    if "mobile-ios" in platforms:
        warnings.append("Validate iOS generation locally on macOS before treating it as build-proven.")
    if any(p in platforms for p in ("web-user-app", "web-admin-portal")):
        warnings.append("Generated web slices still need live Cloudflare deployment validation.")
    return errors, warnings


def render_summary(answers: dict[str, Any], dest_path: Path, template_path: str, warnings: list[str]) -> None:
    platform_labels = dict(ALL_PLATFORM_CHOICES)
    auth_labels = dict(ALL_AUTH_CHOICES)
    body: list[str] = []
    body.append(colorize("Project", STYLE.bold, STYLE.blue))
    body.extend(review_key_value("Name", answers["project_name"], STYLE.bold, STYLE.white))
    body.extend(
        review_key_value(
            "Description",
            answers.get("description", DEFAULT_ANSWERS["description"]),
            STYLE.white,
        )
    )

    body.append("")
    body.append(colorize("Output", STYLE.bold, STYLE.blue))
    body.extend(review_key_value("Destination", str(dest_path), STYLE.white))
    body.extend(review_key_value("Template", template_path, STYLE.dim))

    body.append("")
    body.append(colorize("Stack", STYLE.bold, STYLE.blue))
    body.extend(
        review_key_value(
            "Platforms",
            ", ".join(platform_labels[p] for p in answers.get("platforms", [])),
            STYLE.cyan,
            STYLE.bold,
        )
    )
    body.extend(
        review_key_value(
            "Auth",
            ", ".join(auth_labels[a] for a in answers.get("auth_methods", [])) or "None",
            STYLE.green if answers.get("auth_methods") else STYLE.yellow,
        )
    )
    docker_enabled = answers.get("use_docker", True)
    body.extend(
        review_key_value(
            "Docker Compose",
            "Yes" if docker_enabled else "No",
            STYLE.green if docker_enabled else STYLE.yellow,
            STYLE.bold,
        )
    )
    if answers.get("github_org"):
        body.extend(review_key_value("GitHub org", answers["github_org"], STYLE.magenta))
    print()
    print(panel("Generation Review", body))
    print()
    if warnings:
        warning_lines = [warn(message) for message in warnings]
        print(panel("Warnings", warning_lines))
        print()


def run_copier(template_path: str, dest_path: Path, answers: dict[str, Any]) -> int:
    if dest_path.exists() and dest_path.is_file():
        print(error(f"Destination already exists as a file: {dest_path}"), file=sys.stderr)
        return EXIT_VALIDATION
    if dest_path.exists() and any(dest_path.iterdir()):
        print(error(f"Destination already exists and is not empty: {dest_path}"), file=sys.stderr)
        return EXIT_VALIDATION

    print(section("Generating"))
    print(info("Running Copier with the resolved Prism configuration..."))
    print()

    using_staged_template = should_stage_template_path(template_path)
    with staged_template_path(template_path) as effective_template:
        if using_staged_template:
            print(info("Using a temporary clean copy of the local template for generation."))
        command = ["copier", "copy", "--trust", "--defaults", "--answers-file", COPIER_ANSWERS_FILE]
        for key, value in answers.items():
            command.extend(["--data", f"{key}={format_data_value(value)}"])
        command.extend([str(effective_template), str(dest_path)])
        result = run_copier_generation_process(command, REPO_ROOT)
        if result["returncode"] != 0:
            print(error("Copier generation failed."), file=sys.stderr)
            if result["tail"]:
                print(panel("Copier output", list(result["tail"])), file=sys.stderr)
            return EXIT_COPIER
        ensure_copier_answers_file(dest_path, template_path, answers)

    print()
    if result["event_count"]:
        print(success(f"Generated {result['event_count']} file updates in {dest_path.name}."))
        print()
    next_steps = [
        f"Open the generated repo: {dest_path}",
        "Read README.md and CONTEXT.md",
        "Run setup-project inside the generated repository",
        "Validate the selected platform slices before treating them as settled",
    ]
    print(panel("Success", next_steps))
    return 0


def parse_copier_progress_line(line: str) -> tuple[str, str] | None:
    sanitized = ANSI_PATTERN.sub("", line)
    match = COPIER_PROGRESS_PATTERN.match(sanitized)
    if not match:
        return None
    action, path = match.groups()
    return action.lower(), path


def format_copier_progress_line(action: str, path: str, tick: int = 0) -> str:
    indicator_frames = ("-", "\\", "|", "/")
    if supports_unicode():
        indicator_frames = ("⠋", "⠙", "⠸", "⠴", "⠦", "⠇")
    indicator = indicator_frames[tick % len(indicator_frames)]
    action_text = {
        "create": "Creating",
        "identical": "Keeping",
        "overwrite": "Updating",
        "conflict": "Conflict",
        "skip": "Skipping",
        "remove": "Removing",
    }.get(action, action.capitalize())
    action_style = {
        "create": (STYLE.green, STYLE.bold),
        "identical": (STYLE.dim,),
        "overwrite": (STYLE.yellow, STYLE.bold),
        "conflict": (STYLE.red, STYLE.bold),
        "skip": (STYLE.dim,),
        "remove": (STYLE.yellow,),
    }.get(action, (STYLE.white,))
    return f"{colorize(indicator, STYLE.cyan, STYLE.bold)} {colorize(action_text, *action_style)} {colorize(path, STYLE.white)}"


def render_live_progress_line(line: str) -> None:
    width = max(20, min(terminal_width(), 88))
    rendered = line
    if visible_length(line) > width - 1:
        rendered = truncate_visible(line, width - 2) + ("…" if supports_unicode() else ".")
    padding = max(0, width - 1 - visible_length(rendered))
    sys.stdout.write("\r" + rendered + (" " * padding))
    sys.stdout.flush()


def finish_live_progress_line() -> None:
    width = max(20, min(terminal_width(), 88))
    sys.stdout.write("\r" + (" " * (width - 1)) + "\r")
    sys.stdout.flush()


def run_copier_generation_process(command: list[str], cwd: Path) -> dict[str, Any]:
    if not sys.stdout.isatty():
        result = subprocess.run(command, cwd=str(cwd))
        return {"returncode": result.returncode, "event_count": 0, "tail": []}

    process = subprocess.Popen(
        command,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    event_count = 0
    tick = 0
    output_tail: deque[str] = deque(maxlen=8)
    showed_live_line = False

    assert process.stdout is not None
    for raw_line in process.stdout:
        line = raw_line.rstrip()
        if not line:
            continue
        parsed = parse_copier_progress_line(line)
        if parsed is not None:
            action, path = parsed
            event_count += 1
            render_live_progress_line(format_copier_progress_line(action, path, tick))
            tick += 1
            showed_live_line = True
            continue
        if line.startswith("Copying from template version"):
            continue
        output_tail.append(line)

    returncode = process.wait()
    if showed_live_line:
        finish_live_progress_line()
    return {"returncode": returncode, "event_count": event_count, "tail": list(output_tail)}


def run_copier_update(project_path: Path, answers_data: dict[str, Any], strategy: str) -> int:
    src_path = str(answers_data["_src_path"])
    print(section("Updating"))
    if strategy == "update":
        print(info("Running Copier update with Prism-managed guardrails..."))
    else:
        print(info("Running Copier recopy with Prism-managed guardrails..."))
        print(warn("Recopy reapplies the template with the saved answers and does not preserve manual drift like `copier update`."))
    print()

    if strategy == "update":
        temp_answers_name = None
        temp_answers_path = None
        command = ["copier", "update", "--trust", "--defaults"]
    else:
        temp_answers_name = ".copier-answers.prism-recopy.yml"
        temp_answers_path = project_path / temp_answers_name

    using_staged_template = should_stage_template_path(src_path)
    with staged_template_path(src_path) as effective_template:
        if strategy == "recopy":
            updated_answers = dict(answers_data)
            updated_answers["_src_path"] = str(effective_template)
            with temp_answers_path.open("w", encoding="utf-8") as handle:
                yaml.safe_dump(updated_answers, handle, sort_keys=False)
            command = ["copier", "recopy", "--trust", "--defaults", "--overwrite", "--answers-file", temp_answers_name]
        if using_staged_template:
            print(info(f"Using a temporary clean copy of the local template for {strategy}."))

        try:
            command.append(str(project_path))
            result = subprocess.run(command, cwd=str(project_path))
        finally:
            if temp_answers_path and temp_answers_path.exists():
                temp_answers_path.unlink()

        if result.returncode != 0:
            if strategy == "update":
                print(error("Project update failed."), file=sys.stderr)
                print(info("If this project was generated from the local incubation template, retry with `prism update --strategy recopy`."), file=sys.stderr)
            else:
                print(error("Project recopy failed."), file=sys.stderr)
            return EXIT_COPIER

    public_answers = {key: value for key, value in answers_data.items() if not key.startswith("_")}
    ensure_copier_answers_file(project_path, src_path, public_answers)

    print()
    if strategy == "update":
        print(success("Project update finished. Review the changes before committing."))
    else:
        print(success("Project recopy finished. Review the regenerated changes before committing."))
    return 0


def ensure_copier_answers_file(dest_path: Path, template_path: str, answers: dict[str, Any]) -> None:
    answers_path = dest_path / COPIER_ANSWERS_FILE
    remembered_answers: dict[str, Any] = {}
    if answers_path.exists():
        with contextlib.suppress(OSError, yaml.YAMLError):
            existing_data = yaml.safe_load(answers_path.read_text(encoding="utf-8")) or {}
            if isinstance(existing_data, dict):
                remembered_answers.update(existing_data)

    remembered_answers["_src_path"] = normalize_template_path(template_path)
    template_commit = get_template_commit(template_path)
    if template_commit:
        remembered_answers["_commit"] = template_commit
    remembered_answers.update(answers)
    with answers_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(remembered_answers, handle, sort_keys=False)


def should_stage_template_path(template_path: str) -> bool:
    if "://" in template_path:
        return False
    path = Path(template_path).expanduser().resolve()
    return path.is_dir() and (path / ".git").exists()


@contextlib.contextmanager
def staged_template_path(template_path: str):
    if "://" in template_path:
        yield template_path
        return
    path = Path(template_path).expanduser().resolve()
    if should_stage_template_path(template_path):
        with tempfile.TemporaryDirectory(prefix="prism-template-") as temp_dir:
            staged_root = Path(temp_dir) / path.name
            shutil.copytree(
                path,
                staged_root,
                ignore=shutil.ignore_patterns(
                    ".git",
                    ".venv",
                    "__pycache__",
                    ".pytest_cache",
                    "node_modules",
                    ".gradle",
                    ".idea",
                    "tmp",
                    "build",
                    "dist",
                    "*.egg-info",
                ),
            )
            yield staged_root
        return
    yield path


def format_data_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return "[" + ", ".join(str(item) for item in value) + "]"
    return str(value)


def slugify(name: str) -> str:
    slug = name.strip().lower().replace("_", "-").replace(" ", "-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug


def normalize_template_path(template_path: str) -> str:
    if "://" in template_path:
        return template_path
    return str(Path(template_path).expanduser().resolve())


def get_template_commit(template_path: str) -> str | None:
    if "://" in template_path:
        return None
    path = Path(template_path).expanduser().resolve()
    if not (path / ".git").exists():
        return None
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            capture_output=True,
            check=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def supports_versioned_update(template_path: str) -> bool:
    if "://" in template_path:
        return True
    path = Path(template_path).expanduser().resolve()
    if not (path / ".git").exists():
        return False
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "tag", "--list"],
            capture_output=True,
            check=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return False
    return bool(result.stdout.strip())


def is_incubating_checkout() -> bool:
    return (REPO_ROOT / ".git").exists() and (REPO_ROOT / "copier.yml").exists()


def inspect_git_worktree(path: Path) -> dict[str, bool]:
    try:
        inside = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            check=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return {"is_repo": False, "is_dirty": False}

    if inside.stdout.strip() != "true":
        return {"is_repo": False, "is_dirty": False}

    try:
        status = subprocess.run(
            ["git", "-C", str(path), "status", "--porcelain"],
            capture_output=True,
            check=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return {"is_repo": True, "is_dirty": False}
    return {"is_repo": True, "is_dirty": bool(status.stdout.strip())}


def confirm(prompt: str, default: bool) -> bool:
    if not sys.stdin.isatty():
        return default
    suffix = "Y/n" if default else "y/N"
    while True:
        try:
            raw = input(f"{prompt} [{suffix}]: ").strip().lower()
        except EOFError:
            return default
        if not raw:
            return default
        if raw in {"y", "yes"}:
            return True
        if raw in {"n", "no"}:
            return False
        print(warn("Enter y or n."))
