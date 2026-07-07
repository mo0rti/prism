"""Prism CLI entry point."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import webbrowser
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from prism_cli import __version__
from prism_cli.presets import (
    ALL_AUTH_CHOICES,
    ALL_PLATFORM_CHOICES,
    DEFAULT_ANSWERS,
    PRESETS,
    Preset,
    get_preset,
    merge_answers,
)
from prism_cli.status import WorkspaceStatus, build_status
from prism_cli.workspace import MANIFEST_FILE, detect_workspace_kind
from prism_cli.wiki_model import VALID_FEATURE_OWNERS, VALID_PLATFORM_IDS
from prism_cli.wiki_graph import build_graph, render_mermaid
from prism_cli.wiki_query import wiki_blockers, wiki_owner, wiki_platform, wiki_search, wiki_show
from prism_cli.wiki_lint import WikiLintResult, lint_wiki
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
DEFAULT_GENERATED_DIR = "workspaces"
COPIER_PROGRESS_PATTERN = re.compile(r"^\s*(create|identical|overwrite|conflict|skip|remove)\s+(.+?)\s*$")


def derive_project_slug(project_name: str) -> str:
    normalized = project_name.strip().lower().replace("_", "-").replace(" ", "-")
    normalized = re.sub(r"-{2,}", "-", normalized)
    return normalized or "generated-project"


def build_default_destination(project_name: str) -> str:
    return str(Path(DEFAULT_GENERATED_DIR) / derive_project_slug(project_name))


@dataclass(frozen=True)
class DoctorCheck:
    label: str
    category: str
    purpose: str
    impact: str
    install_hint: str
    next_step_hint: str
    install_commands: dict[str, str] | None = None
    install_references: dict[str, str] | None = None
    resolver: str | None = None
    platforms: tuple[str, ...] = ()
    required_os: str | None = None
    blocking: bool = False
    packaged_status: str | None = None


@dataclass(frozen=True)
class DoctorResult:
    check: DoctorCheck
    status: str
    detail: str
    install_command: str | None = None
    install_reference: str | None = None


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
    doctor_parser.add_argument(
        "--preset",
        choices=[preset.slug for preset in PRESETS],
        help="Evaluate readiness for a recommended Prism preset path.",
    )
    doctor_parser.add_argument(
        "--workspace",
        nargs="?",
        const=".",
        help="Include generated-project workspace status for the given path. Defaults to the current directory.",
    )
    doctor_parser.set_defaults(func=cmd_doctor)

    status_parser = subparsers.add_parser("status", help="Show generated-project workspace status.")
    status_parser.add_argument("path", nargs="?", default=".", help="Generated project path. Defaults to the current directory.")
    status_parser.add_argument("--full", action="store_true", help="Show full diagnostics and detailed counts.")
    status_parser.add_argument("--json", action="store_true", help="Emit versioned machine-readable status output.")
    status_parser.set_defaults(func=cmd_status)

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

    wiki_parser = subparsers.add_parser("wiki", help="Inspect and validate generated-project wiki state.")
    wiki_subparsers = wiki_parser.add_subparsers(dest="wiki_command")
    wiki_lint_parser = wiki_subparsers.add_parser("lint", help="Validate generated-project wiki schema and consistency.")
    wiki_lint_parser.add_argument("path", nargs="?", default=".", help="Generated project path. Defaults to the current directory.")
    wiki_lint_parser.add_argument("--json", action="store_true", help="Emit versioned machine-readable lint output.")
    wiki_lint_parser.set_defaults(func=cmd_wiki_lint)
    wiki_show_parser = wiki_subparsers.add_parser("show", help="Show one feature and its platform requirements.")
    wiki_show_parser.add_argument("feature_id", help="Feature id to show, for example F-001.")
    wiki_show_parser.add_argument("path", nargs="?", default=".", help="Generated project path. Defaults to the current directory.")
    wiki_show_parser.add_argument("--json", action="store_true", help="Emit versioned machine-readable output.")
    wiki_show_parser.set_defaults(func=cmd_wiki_show)
    wiki_blockers_parser = wiki_subparsers.add_parser("blockers", help="Show implementation blockers detected in the wiki.")
    wiki_blockers_parser.add_argument("path", nargs="?", default=".", help="Generated project path. Defaults to the current directory.")
    wiki_blockers_parser.add_argument("--json", action="store_true", help="Emit versioned machine-readable output.")
    wiki_blockers_parser.set_defaults(func=cmd_wiki_blockers)
    wiki_owner_parser = wiki_subparsers.add_parser("owner", help="Show feature and open-question facts for one owner.")
    wiki_owner_parser.add_argument("owner", choices=sorted(VALID_FEATURE_OWNERS), help="Owner role to inspect.")
    wiki_owner_parser.add_argument("path", nargs="?", default=".", help="Generated project path. Defaults to the current directory.")
    wiki_owner_parser.add_argument("--json", action="store_true", help="Emit versioned machine-readable output.")
    wiki_owner_parser.set_defaults(func=cmd_wiki_owner)
    wiki_platform_parser = wiki_subparsers.add_parser("platform", help="Show feature and requirement facts for one platform.")
    wiki_platform_parser.add_argument("platform", choices=sorted(VALID_PLATFORM_IDS), help="Platform id to inspect.")
    wiki_platform_parser.add_argument("path", nargs="?", default=".", help="Generated project path. Defaults to the current directory.")
    wiki_platform_parser.add_argument("--json", action="store_true", help="Emit versioned machine-readable output.")
    wiki_platform_parser.set_defaults(func=cmd_wiki_platform)
    wiki_search_parser = wiki_subparsers.add_parser("search", help="Run conservative substring search across wiki feature facts.")
    wiki_search_parser.add_argument("query", help="Literal substring to search for.")
    wiki_search_parser.add_argument("path", nargs="?", default=".", help="Generated project path. Defaults to the current directory.")
    wiki_search_parser.add_argument("--json", action="store_true", help="Emit versioned machine-readable output.")
    wiki_search_parser.set_defaults(func=cmd_wiki_search)
    wiki_graph_parser = wiki_subparsers.add_parser("graph", help="Render wiki relationship facts as JSON, Mermaid, or an interactive HTML dashboard.")
    wiki_graph_parser.add_argument("path", nargs="?", default=".", help="Generated project path. Defaults to the current directory.")
    wiki_graph_parser.add_argument("--json", action="store_true", help="Emit versioned machine-readable graph facts.")
    wiki_graph_parser.add_argument("--mermaid", action="store_true", help="Emit a Mermaid diagram (see --view).")
    wiki_graph_parser.add_argument("--view", choices=["lifecycle", "ego", "platform"], default="lifecycle", help="Mermaid view. Defaults to lifecycle.")
    wiki_graph_parser.add_argument("--feature", help="Feature id for --view ego, for example F-001.")
    wiki_graph_parser.add_argument("--platform", choices=sorted(VALID_PLATFORM_IDS), help="Platform id for --view platform.")
    wiki_graph_parser.add_argument("--html", nargs="?", const="", metavar="OUT", help="Write the interactive dashboard. Defaults to prism-graph.html in the workspace root.")
    wiki_graph_parser.add_argument("--open", action="store_true", help="Write the dashboard to a temporary file and open it in the browser.")
    wiki_graph_parser.add_argument("--serve", action="store_true", help="Serve the dashboard locally with live updates as wiki files change.")
    wiki_graph_parser.add_argument("--port", type=int, default=8321, help="Port for --serve. Defaults to 8321.")
    wiki_graph_parser.set_defaults(func=cmd_wiki_graph)
    wiki_parser.set_defaults(func=cmd_wiki_help, parser=wiki_parser)

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

    if context_kind == "generated-project":
        render_status_result(build_status(current_dir), full=False)
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
    actions: list[SelectOption] = []

    if context_kind == "generated-project":
        actions.extend(
            [
                SelectOption(
                    value="status",
                    label="Workspace Status",
                    meta="[status]",
                    description="Show project identity, queues, blockers, and schema issues.",
                    accent="action",
                ),
                SelectOption(
                    value="dashboard",
                    label="Open Dashboard",
                    meta="[wiki graph]",
                    description="Interactive product-truth dashboard: pipeline, graph, blockers, platforms.",
                    accent="action",
                ),
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
        actions.extend(
            [
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
        )

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
    elif context_kind != "generated-project":
        actions.append(
            SelectOption(
                value="validate",
                label="Validate Current Directory",
                meta="[validate]",
                description="Try to validate the current directory as a template repo or generated project.",
                accent="action",
            )
        )

    if context_kind == "generated-project":
        actions.extend(
            [
                SelectOption(
                    value="doctor",
                    label="Doctor",
                    meta="[doctor]",
                    description="Check local tools and generated-project workspace status.",
                    accent="action",
                ),
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
            ]
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
    if selected == "dashboard":
        parsed = parser.parse_args(["wiki", "graph", "--open"])
        parsed.from_launcher = True
        return parsed.func(parsed)

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
    selected_preset = get_preset(_args.preset) if _args.preset else None
    workspace_status = build_status(Path(_args.workspace)) if getattr(_args, "workspace", None) else None
    if selected_preset:
        target_platforms = set(selected_preset.answers.get("platforms", []))
    elif workspace_status:
        target_platforms = set(workspace_status.platforms)
    else:
        target_platforms = set()
    target_label = selected_preset.label if selected_preset else "Workspace Prism readiness" if workspace_status else "General Prism readiness"

    body = [
        f"OS: {system}",
        f"Python: {platform.python_version()}",
        f"Mode: {'incubation' if incubation_mode else 'packaged/runtime'}",
        f"Target: {target_label}",
        f"Repo: {REPO_ROOT if incubation_mode else 'n/a'}",
    ]
    print(panel("Environment", body))
    print()

    results = evaluate_doctor_checks(build_doctor_checks(incubation_mode), system, target_platforms)
    summary = summarize_doctor_results(results, selected_preset)
    core_missing = any(result.status == "missing" and result.check.blocking for result in results)
    print(panel("Summary", summary))
    print()

    if getattr(_args, "workspace", None):
        assert workspace_status is not None
        render_status_result(workspace_status, full=False)
        print()

    for title, category_key in (
        ("Core", "core"),
        ("Workflow", "workflow"),
        ("Backend", "backend"),
        ("Web", "web"),
        ("Build Tools", "build"),
        ("iOS", "ios"),
    ):
        category_results = [result for result in results if result.check.category == category_key]
        if not category_results:
            continue
        print(section(title))
        for result in category_results:
            for line in render_doctor_result(result):
                print(line)
        print()

    if core_missing:
        print(error("Install the blocking core dependencies before running `prism new`."))
        return EXIT_ENVIRONMENT

    print(success("Prism core generation is ready."))
    return 0


def build_doctor_checks(incubation_mode: bool) -> list[DoctorCheck]:
    # Keep this in code for the incubation phase. The longer-term plan is to move
    # dependency metadata into a shared manifest so CLI policy and docs do not drift.
    checks = [
        DoctorCheck(
            label="Python",
            category="core",
            purpose="Needed for the Prism runtime in the current install model.",
            impact="Prism generation is blocked until Python is available.",
            install_hint="Install CPython 3.12+ from the official Python publisher, then reopen your terminal.",
            next_step_hint="Install Python before running prism new.",
            install_commands={
                "Windows": "winget install Python.Python.3.12 --source winget",
            },
            install_references={
                "Windows": "https://docs.python.org/3/using/windows.html",
                "default": "https://www.python.org/downloads/",
            },
            # Python is special here: Prism is already running inside this interpreter,
            # so checking the active executable is more reliable than PATH lookup.
            resolver=sys.executable if Path(sys.executable).exists() else "python",
            blocking=True,
        ),
        DoctorCheck(
            label="Copier",
            category="core",
            purpose="Needed to render Prism projects from the template during incubation.",
            impact="Prism generation is blocked until Copier is available in this Python environment.",
            install_hint="Install Copier as an isolated CLI tool. If `uv` is not installed yet, use `pip install copier` as a fallback.",
            next_step_hint="Install Copier before running prism new in incubation mode.",
            install_commands={
                "default": "uv tool install copier",
            },
            install_references={
                "default": "https://copier.readthedocs.io/en/stable/",
            },
            resolver="copier",
            blocking=True,
            packaged_status="bundled" if not incubation_mode else None,
        ),
        DoctorCheck(
            label="Git",
            category="workflow",
            purpose="Needed for generated project updates and common repository workflows.",
            impact="Generation still works, but update and repository workflows are limited until Git is installed.",
            install_hint="Install Git using the maintained Git for Windows build or your platform installer.",
            next_step_hint="Install Git to unlock generated project updates and repository workflows.",
            install_commands={
                "Windows": "winget install --id Git.Git -e --source winget",
            },
            install_references={
                "Windows": "https://git-scm.com/install/windows",
                "default": "https://git-scm.com/downloads",
            },
            resolver="git",
        ),
        DoctorCheck(
            label="Node.js",
            category="workflow",
            purpose="Needed for shared generated tooling and web workflows.",
            impact="Generation still works, but shared Node-based tooling will be unavailable until this is installed.",
            install_hint="Install the current Node.js LTS release from the official Node.js downloads page.",
            next_step_hint="Install Node.js to unlock shared generated tooling and web workflows.",
            install_references={
                "default": "https://nodejs.org/en/download",
            },
            resolver="node",
        ),
        DoctorCheck(
            label="go-task",
            category="workflow",
            purpose="Needed to run generated Taskfile commands.",
            impact="Generation still works, but generated task workflows will not run until this is installed.",
            install_hint="Install go-task globally, then reopen your terminal so the `task` command is on PATH. This npm-based install requires Node.js first.",
            next_step_hint="Install go-task to run generated Taskfile commands.",
            install_commands={
                "default": "npm install -g @go-task/cli",
            },
            install_references={
                "default": "https://taskfile.dev/docs/installation",
            },
            resolver="task",
        ),
        DoctorCheck(
            label="Docker",
            category="backend",
            purpose="Needed for container-backed backend workflows and local infrastructure.",
            impact="Backend generation still works, but container-based backend workflows are unavailable until Docker is installed.",
            install_hint="Install Docker Desktop from Docker's setup guide, then complete the first-run setup.",
            next_step_hint="Install Docker to unlock container-backed backend workflows.",
            install_references={
                "Windows": "https://docs.docker.com/desktop/setup/install/windows-install/",
                "Darwin": "https://docs.docker.com/desktop/setup/install/mac-install/",
                "Linux": "https://docs.docker.com/desktop/setup/install/linux/",
                "default": "https://docs.docker.com/desktop/",
            },
            resolver="docker",
            platforms=("backend",),
        ),
        DoctorCheck(
            label="JDK",
            category="build",
            purpose="Needed for Android builds and Spring Boot local build workflows.",
            impact="Generation still works, but Android and some Java-based local builds will be unavailable until a JDK is installed.",
            install_hint="Install Eclipse Temurin JDK 21 and ensure `java` is available on PATH.",
            next_step_hint="Install a JDK to unlock Spring Boot and Android local builds.",
            install_commands={
                "Windows": "winget install EclipseAdoptium.Temurin.21.JDK",
            },
            install_references={
                "default": "https://adoptium.net/installation/",
            },
            resolver="java",
            platforms=("backend", "mobile-android"),
        ),
        DoctorCheck(
            label="Xcode CLI",
            category="ios",
            purpose="Needed for local iOS builds and validation on macOS.",
            impact="iOS generation still works structurally, but local iOS validation requires macOS with Xcode command line tools.",
            install_hint="Install Xcode and the Xcode command line tools on macOS.",
            next_step_hint="Install Xcode command line tools on macOS to validate iOS locally.",
            install_commands={
                "Darwin": "xcode-select --install",
            },
            install_references={
                "Darwin": "https://developer.apple.com/xcode/",
            },
            resolver="xcodebuild",
            platforms=("mobile-ios",),
            required_os="Darwin",
        ),
    ]
    return checks


def evaluate_doctor_checks(checks: list[DoctorCheck], system: str, target_platforms: set[str]) -> list[DoctorResult]:
    results: list[DoctorResult] = []
    for check in checks:
        if check.platforms and target_platforms and not set(check.platforms).intersection(target_platforms):
            continue

        if check.packaged_status:
            detail = "Bundled with Prism or privately managed in packaged mode."
            results.append(DoctorResult(check=check, status=check.packaged_status, detail=detail))
            continue

        if check.required_os and system != check.required_os:
            detail = "Not applicable on this OS. Local validation for this tool is only supported on the required platform."
            results.append(DoctorResult(check=check, status="not-applicable", detail=detail))
            continue

        resolved = shutil.which(check.resolver) if check.resolver else None
        if resolved:
            results.append(DoctorResult(check=check, status="ready", detail=resolved))
        else:
            results.append(
                DoctorResult(
                    check=check,
                    status="missing",
                    detail=check.install_hint,
                    install_command=doctor_install_command(check, system),
                    install_reference=doctor_install_reference(check, system),
                )
            )
    return results


def summarize_doctor_results(results: list[DoctorResult], selected_preset: Preset | None) -> list[str]:
    core_missing = any(result.status == "missing" and result.check.blocking for result in results)
    workflow_missing = sum(1 for result in results if result.check.category == "workflow" and result.status == "missing")
    platform_missing = sum(
        1 for result in results if result.check.category in {"backend", "web", "build", "ios"} and result.status == "missing"
    )
    next_step = "You can generate a Prism project now."
    next_result = choose_next_doctor_result(results, set(selected_preset.answers.get("platforms", [])) if selected_preset else set())
    if next_result:
        next_step = next_doctor_step(next_result)

    platform_status = "Ready"
    if platform_missing:
        platform_status = f"{platform_missing} missing"
    elif any(result.status == "not-applicable" and result.check.category == "ios" for result in results):
        platform_status = "Platform checks vary by OS"

    lines: list[str] = []
    lines.extend(review_key_value("Prism generation", "Blocked" if core_missing else "Ready", *(STYLE.red, STYLE.bold) if core_missing else (STYLE.green, STYLE.bold)))
    lines.extend(
        review_key_value(
            "Workflow tools",
            "Ready" if workflow_missing == 0 else f"{workflow_missing} missing",
            *(STYLE.green, STYLE.bold) if workflow_missing == 0 else (STYLE.yellow, STYLE.bold),
        )
    )
    lines.extend(
        review_key_value(
            "Platform path",
            platform_status,
            *(STYLE.green, STYLE.bold) if platform_missing == 0 and platform_status == "Ready" else (STYLE.yellow, STYLE.bold),
        )
    )
    lines.extend(review_key_value("Target preset", selected_preset.label if selected_preset else "General Prism readiness", STYLE.white))
    lines.extend(review_key_value("Next step", next_step, STYLE.white))
    return lines


def choose_next_doctor_result(results: list[DoctorResult], target_platforms: set[str]) -> DoctorResult | None:
    missing_results = [result for result in results if result.status == "missing"]
    if not missing_results:
        return None

    def sort_key(result: DoctorResult) -> tuple[int, int, str]:
        platform_relevant = bool(target_platforms) and bool(set(result.check.platforms).intersection(target_platforms))
        category_priority = 0 if result.check.blocking else 1 if platform_relevant else 2 if result.check.category == "workflow" else 3
        platform_priority = 0 if platform_relevant else 1
        return (category_priority, platform_priority, result.check.label)

    return sorted(missing_results, key=sort_key)[0]


def next_doctor_step(result: DoctorResult) -> str:
    return result.check.next_step_hint


def doctor_install_command(check: DoctorCheck, system: str) -> str | None:
    if not check.install_commands:
        return None
    return check.install_commands.get(system) or check.install_commands.get("default")


def doctor_install_reference(check: DoctorCheck, system: str) -> str | None:
    if not check.install_references:
        return None
    return check.install_references.get(system) or check.install_references.get("default")


def doctor_status_badge(status: str) -> str:
    labels = {
        "ready": ("[ready]", (STYLE.green, STYLE.bold)),
        "missing": ("[missing]", (STYLE.yellow, STYLE.bold)),
        "bundled": ("[bundled]", (STYLE.cyan, STYLE.bold)),
        "not-applicable": ("[n/a]", (STYLE.dim,)),
    }
    label, styles = labels.get(status, ("[info]", (STYLE.white,)))
    return colorize(label, *styles)


def render_doctor_result(result: DoctorResult) -> list[str]:
    lines = [f"{doctor_status_badge(result.status)} {colorize(result.check.label, STYLE.bold, STYLE.white)}"]
    lines.append(f"  {result.check.purpose}")
    if result.status == "ready":
        lines.append(f"  {colorize('Found:', STYLE.dim)} {result.detail}")
    elif result.status == "bundled":
        lines.append(f"  {colorize('Handled by Prism:', STYLE.dim)} {result.detail}")
    elif result.status == "not-applicable":
        lines.append(f"  {colorize('Scope:', STYLE.dim)} {result.detail}")
    else:
        lines.append(f"  {colorize('Impact:', STYLE.dim)} {result.check.impact}")
        lines.append(f"  {colorize('Install:', STYLE.dim)} {result.check.install_hint}")
        if result.install_command:
            lines.append(f"  {colorize('Try:', STYLE.dim)} {colorize(result.install_command, STYLE.cyan)}")
        if result.install_reference:
            lines.append(f"  {colorize('Docs:', STYLE.dim)} {colorize(result.install_reference, STYLE.cyan)}")
    return lines


def cmd_status(args: argparse.Namespace) -> int:
    target_path = Path(args.path).expanduser().resolve()
    result = build_status(target_path)
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
        return 0

    show_command_intro(args, "Generated-project workspace status")
    render_status_result(result, full=args.full)
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


def cmd_wiki_help(args: argparse.Namespace) -> int:
    args.parser.print_help()
    return 0


def cmd_wiki_lint(args: argparse.Namespace) -> int:
    target_path = Path(args.path).expanduser().resolve()
    result = lint_wiki(target_path)
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
        return 0 if result.is_clean else EXIT_VALIDATION

    show_command_intro(args, "Validate generated-project wiki contract")
    render_wiki_lint_result(result)
    return 0 if result.is_clean else EXIT_VALIDATION


def cmd_wiki_show(args: argparse.Namespace) -> int:
    result = wiki_show(Path(args.path), args.feature_id)
    return render_or_print_wiki_query(args, "Show wiki feature facts", result)


def cmd_wiki_blockers(args: argparse.Namespace) -> int:
    result = wiki_blockers(Path(args.path))
    return render_or_print_wiki_query(args, "Show wiki blockers", result)


def cmd_wiki_owner(args: argparse.Namespace) -> int:
    result = wiki_owner(Path(args.path), args.owner)
    return render_or_print_wiki_query(args, "Show wiki owner facts", result)


def cmd_wiki_platform(args: argparse.Namespace) -> int:
    result = wiki_platform(Path(args.path), args.platform)
    return render_or_print_wiki_query(args, "Show wiki platform facts", result)


def cmd_wiki_search(args: argparse.Namespace) -> int:
    result = wiki_search(Path(args.path), args.query)
    return render_or_print_wiki_query(args, "Search wiki facts", result)


def cmd_wiki_graph(args: argparse.Namespace) -> int:
    target_path = Path(args.path).expanduser().resolve()

    if args.serve:
        from prism_cli.graph_server import serve_graph

        return serve_graph(target_path, args.port)

    result = build_graph(target_path)

    if args.json:
        print(json.dumps(result, indent=2))
        return 0

    if args.mermaid:
        if args.view == "ego" and not args.feature:
            print(error("--view ego requires --feature F-XXX."), file=sys.stderr)
            return EXIT_VALIDATION
        if args.view == "platform" and not args.platform:
            print(error("--view platform requires --platform <platform-id>."), file=sys.stderr)
            return EXIT_VALIDATION
        print(render_mermaid(result, args.view, feature_id=args.feature, platform_id=args.platform))
        return 0

    if args.open or args.html is not None:
        from prism_cli.wiki_graph_html import render_html, write_dashboard

        if args.open:
            out_path = Path(tempfile.mkdtemp(prefix="prism-graph-")) / "prism-graph.html"
        else:
            out_path = Path(args.html) if args.html else target_path / "prism-graph.html"
        out_path = out_path.expanduser().resolve()
        knowledge_root = (target_path / "knowledge").resolve()
        if str(out_path).startswith(str(knowledge_root)):
            print(error("Refusing to write the dashboard inside knowledge/ — that directory is product truth."), file=sys.stderr)
            return EXIT_VALIDATION
        write_dashboard(result, out_path)
        print(success(f"Dashboard written: {out_path}"))
        if args.open:
            webbrowser.open(out_path.as_uri())
        return 0

    show_command_intro(args, "Wiki graph facts")
    facts = result["facts"]
    type_counts: dict[str, int] = {}
    for node in facts["nodes"]:
        type_counts[node["type"]] = type_counts.get(node["type"], 0) + 1
    summary_lines = [
        f"Nodes: {facts['node_count']}",
        f"Edges: {facts['edge_count']}",
        f"Dangling references: {len(facts['dangling_references'])}",
        f"Confidence: {result['confidence']}",
    ]
    summary_lines.extend(f"{node_type}: {count}" for node_type, count in sorted(type_counts.items()))
    print(panel("Graph", summary_lines))
    print()
    print(info("Use --json, --mermaid, --html, --open, or --serve for full output."))
    return 0


def render_or_print_wiki_query(args: argparse.Namespace, title: str, result: dict[str, Any]) -> int:
    if args.json:
        print(json.dumps(result, indent=2))
        return 0

    show_command_intro(args, title)
    render_wiki_query_result(result)
    return 0


def render_wiki_lint_result(result: WikiLintResult) -> None:
    summary = [
        f"Workspace: {result.root}",
        f"Features: {result.feature_count}",
        f"Errors: {result.error_count}",
        f"Warnings: {result.warning_count}",
    ]
    print(panel("Wiki lint", summary))
    print()
    if result.is_clean:
        print(success("Wiki contract checks passed."))
        return

    print(section("Diagnostics"))
    for diagnostic in result.diagnostics:
        formatter = error if diagnostic.severity == "error" else warn
        location = diagnostic.path
        if diagnostic.feature_id:
            location += f" [{diagnostic.feature_id}]"
        print(f"- {formatter(diagnostic.code)}: {diagnostic.message}")
        print(f"  {colorize(location, STYLE.dim)}")


def render_wiki_query_result(result: dict[str, Any]) -> None:
    workspace = result.get("workspace", {})
    facts = result.get("facts", {})
    print(
        panel(
            "Wiki query",
            [
                f"Command: {result.get('command')}",
                f"Workspace: {workspace.get('kind', 'unknown')}",
                f"Confidence: {format_confidence(str(result.get('confidence', 'unknown')))}",
            ],
        )
    )
    print()

    command = result.get("command")
    if command == "wiki show":
        render_wiki_show_facts(facts)
    elif command == "wiki blockers":
        render_wiki_blocker_facts(facts)
    elif command == "wiki owner":
        render_wiki_owner_facts(facts)
    elif command == "wiki platform":
        render_wiki_platform_facts(facts)
    elif command == "wiki search":
        render_wiki_search_facts(facts)
    else:
        print(json.dumps(facts, indent=2))

    diagnostics = result.get("diagnostics", [])
    if diagnostics:
        print()
        print(section("Diagnostics"))
        for diagnostic in diagnostics[:8]:
            formatter = error if diagnostic.get("severity") == "error" else warn
            print(f"- {formatter(diagnostic.get('code', 'diagnostic'))}: {diagnostic.get('message', '')}")
            print(f"  {colorize(str(diagnostic.get('path', '')), STYLE.dim)}")
        hidden_count = len(diagnostics) - 8
        if hidden_count > 0:
            print(info(f"{hidden_count} more diagnostics hidden. Use `--json` for the complete list."))


def render_wiki_show_facts(facts: dict[str, Any]) -> None:
    feature = facts.get("feature")
    if not feature:
        print(warn("No feature facts available."))
        return
    print(
        panel(
            "Feature",
            [
                f"ID: {feature.get('id')}",
                f"Title: {feature.get('title')}",
                f"Status: {feature.get('status')}",
                f"Owner: {feature.get('owner')}",
                f"Board review: {feature.get('advisory_review')}",
                f"Platforms: {', '.join(feature.get('platforms', [])) or 'none'}",
                f"Path: {feature.get('path')}",
            ],
        )
    )
    questions = feature.get("open_questions", [])
    requirements = feature.get("platform_requirements", [])
    print()
    print(section("Open questions"))
    if questions:
        for question in questions:
            print(f"- {question.get('number')}: {question.get('question')} [{question.get('owner')}, {question.get('status')}]")
    else:
        print("- none")
    print()
    print(section("Platform requirements"))
    if requirements:
        for requirement in requirements:
            print(f"- {requirement.get('platform')}: {requirement.get('status')} ({requirement.get('path')})")
    else:
        print("- none")


def render_wiki_blocker_facts(facts: dict[str, Any]) -> None:
    blockers = facts.get("blockers", [])
    print(panel("Blockers", [f"Count: {facts.get('blocker_count', 0)}"]))
    if not blockers:
        print()
        print(success("No blocker facts detected."))
        return
    print()
    for blocker in blockers:
        print(f"- {error(blocker.get('code', 'blocker'))}: {blocker.get('message', '')}")
        print(f"  {colorize(str(blocker.get('path', '')), STYLE.dim)}")


def render_wiki_owner_facts(facts: dict[str, Any]) -> None:
    print(panel("Owner", [f"Owner: {facts.get('owner')}", f"Features: {facts.get('feature_count', 0)}", f"Open questions: {facts.get('open_question_count', 0)}"]))
    print()
    print(section("Features"))
    render_feature_summaries(facts.get("features", []))
    print()
    print(section("Open questions"))
    questions = facts.get("open_questions", [])
    if questions:
        for question in questions:
            print(f"- {question.get('feature_id')} #{question.get('number')}: {question.get('question')}")
    else:
        print("- none")


def render_wiki_platform_facts(facts: dict[str, Any]) -> None:
    print(panel("Platform", [f"Platform: {facts.get('platform')}", f"Features: {facts.get('feature_count', 0)}", f"Requirements: {facts.get('platform_requirement_count', 0)}"]))
    print()
    print(section("Features"))
    render_feature_summaries(facts.get("features", []))
    print()
    print(section("Platform requirements"))
    requirements = facts.get("platform_requirements", [])
    if requirements:
        for requirement in requirements:
            print(f"- {requirement.get('feature_id')}: {requirement.get('status')} ({requirement.get('path')})")
    else:
        print("- none")


def render_wiki_search_facts(facts: dict[str, Any]) -> None:
    print(panel("Search", [f"Query: {facts.get('query')}", f"Results: {facts.get('result_count', 0)}"]))
    print()
    results = facts.get("results", [])
    if not results:
        print("- none")
        return
    for item in results:
        label = item.get("id") or item.get("feature_id") or item.get("type")
        print(f"- {item.get('type')}: {label}")
        print(f"  {colorize(str(item.get('path', '')), STYLE.dim)}")
        print(f"  matched: {', '.join(item.get('matched_fields', []))}")


def render_feature_summaries(features: list[dict[str, Any]]) -> None:
    if not features:
        print("- none")
        return
    for feature in features:
        print(f"- {feature.get('id')}: {feature.get('title')} [{feature.get('status')}, {feature.get('owner')}]")
        print(f"  {colorize(str(feature.get('path', '')), STYLE.dim)}")


def render_status_result(result: WorkspaceStatus, full: bool) -> None:
    workspace_lines = [
        f"Project: {result.project_name or 'unknown'}",
        f"Kind: {result.workspace_kind}",
        f"Platforms: {', '.join(result.platforms) if result.platforms else 'none detected'}",
        f"Setup: {format_setup_state(result.setup_state)}",
        f"Confidence: {format_confidence(result.confidence)}",
    ]
    print(panel("Workspace", workspace_lines))
    print()

    queue_lines = [
        f"Pending intake: {result.intake.pending}",
        f"Quarantined intake: {result.intake.quarantined}",
        f"Features: {result.wiki_lint.feature_count}",
        f"Blockers: {result.blocker_count}",
        f"Wiki errors: {result.wiki_lint.error_count}",
        f"Wiki warnings: {result.wiki_lint.warning_count}",
    ]
    print(panel("Queues and wiki", queue_lines))

    if result.setup_state == "not-initialized":
        print()
        print(warn("setup-project has not initialized the wiki yet."))

    caveats = [
        (platform_id, data.get("caveat", ""))
        for platform_id, data in result.platform_maturity.items()
        if data.get("caveat")
    ]
    if caveats:
        print()
        print(section("Platform maturity"))
        for platform_id, caveat in caveats:
            print(f"- {platform_id}: {warn(caveat)}")

    print()
    print(section("Feature lifecycle"))
    lifecycle_counts = compact_count_lines(result.feature_status_counts)
    if lifecycle_counts:
        for key, value in lifecycle_counts:
            print(f"- {key}: {value}")
    else:
        print("- none")

    if full:
        print()
        print(section("Owner queues"))
        owner_counts = compact_count_lines(result.feature_owner_counts)
        if owner_counts:
            for key, value in owner_counts:
                print(f"- {key}: {value}")
        else:
            print("- none")
        if result.open_questions_by_owner:
            print()
            print(section("Open questions"))
            for key, value in compact_count_lines(result.open_questions_by_owner):
                print(f"- {key}: {value}")
        if result.platform_requirement_status_counts:
            print()
            print(section("Platform requirements"))
            for key, value in compact_count_lines(result.platform_requirement_status_counts):
                print(f"- {key}: {value}")

    diagnostics = result.to_dict()["diagnostics"]
    if not diagnostics:
        print()
        print(success("Workspace status is clean."))
        return

    print()
    print(section("Attention"))
    visible_diagnostics = diagnostics if full else diagnostics[:8]
    for diagnostic in visible_diagnostics:
        formatter = error if diagnostic["severity"] == "error" else warn
        print(f"- {formatter(diagnostic['code'])}: {diagnostic['message']}")
        print(f"  {colorize(diagnostic['path'], STYLE.dim)}")
    hidden_count = len(diagnostics) - len(visible_diagnostics)
    if hidden_count > 0:
        print()
        print(info(f"{hidden_count} more diagnostics hidden. Run `prism status --full` or `prism wiki lint` for details."))


def format_setup_state(setup_state: str) -> str:
    if setup_state == "initialized":
        return success("initialized")
    if setup_state == "not-initialized":
        return warn("not initialized")
    return warn(setup_state)


def format_confidence(confidence: str) -> str:
    if confidence == "high":
        return success("high")
    if confidence == "degraded":
        return warn("degraded")
    return error(confidence)


def compact_count_lines(counts: dict[str, int]) -> list[tuple[str, int]]:
    return [(key, value) for key, value in counts.items() if value]


def cmd_update(args: argparse.Namespace) -> int:
    project_path = Path(args.path).expanduser().resolve()
    if detect_validation_target(project_path) != "generated-project":
        print(error("`prism update` must be run against a generated Prism project."), file=sys.stderr)
        return EXIT_VALIDATION

    repo_state = inspect_git_worktree(project_path)
    if not is_direct_git_worktree(project_path, repo_state):
        print(error("`prism update` requires the generated project to have its own git repository."), file=sys.stderr)
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
                build_default_destination(merged_answers["project_name"]),
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
    kind = detect_workspace_kind(path)
    if kind == "template":
        return "template"
    if kind == "generated-project":
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

    wiki_result = lint_wiki(path)
    if not wiki_result.is_clean:
        print(section("Wiki lint"))
        render_wiki_lint_result(wiki_result)
        return EXIT_VALIDATION

    checks = [
        "README.md present",
        "CONTEXT.md present",
        "knowledge/wiki/SCHEMA.md present",
        "Taskfile.yml present",
        "wiki contract checks passed",
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
    auth_default = DEFAULT_ANSWERS["auth_methods"]
    auth_methods = prompt_multiselect(
        "Select auth methods (keep Username + Password selected)",
        ALL_AUTH_CHOICES,
        default_values=auth_default,
        allow_empty=False,
    )
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
    entries = list(dest_path.iterdir())
    if not entries or is_generation_safe_existing_destination(entries):
        return None

    target_kind = detect_validation_target(dest_path)
    if target_kind == "generated-project":
        print(error(f"Destination already contains a generated Prism project: {dest_path}"), file=sys.stderr)
        print(info("Use `prism update` to refresh that workspace from its template."), file=sys.stderr)
        print(info("Or choose a different destination such as `workspaces/<project-slug>`."), file=sys.stderr)
        return EXIT_VALIDATION

    repo_state = inspect_git_worktree(dest_path)
    if is_direct_git_worktree(dest_path, repo_state) or (dest_path / ".git").exists():
        print(error(f"Destination is already under git version control: {dest_path}"), file=sys.stderr)
        print(info("Choose a new destination for `prism new`, or remove/archive the existing repository first."), file=sys.stderr)
        print(info("If this is an existing Prism workspace, prefer `prism update` instead of overwriting it."), file=sys.stderr)
        return EXIT_VALIDATION

    print(warn(f"Destination already exists and is not empty: {dest_path}"))
    if not sys.stdin.isatty():
        print(error("Refusing to delete an existing non-empty destination in non-interactive mode."), file=sys.stderr)
        print(info("Choose an empty destination or remove the existing contents first."), file=sys.stderr)
        return EXIT_VALIDATION

    if not confirm("Delete the existing contents and continue?", default=False):
        print(warn("Generation cancelled."))
        return 0

    try:
        clear_directory_contents(dest_path)
    except PermissionError as exc:
        print(error(f"Could not clear the destination because a file is in use: {exc}"), file=sys.stderr)
        print(info("Close any editor, terminal, or process using that folder, then retry."), file=sys.stderr)
        print(info("If this directory is an existing Prism workspace, use `prism update` instead."), file=sys.stderr)
        return EXIT_VALIDATION
    except OSError as exc:
        print(error(f"Could not clear the destination: {exc}"), file=sys.stderr)
        print(info("Choose a different destination or remove the existing contents manually, then retry."), file=sys.stderr)
        return EXIT_VALIDATION
    print(info(f"Cleared existing contents in `{dest_path}`."))
    print()
    return None


def clear_directory_contents(path: Path) -> None:
    for child in path.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def is_generation_safe_existing_destination(entries: list[Path]) -> bool:
    allowed_root_files = {".gitignore", ".gitattributes", ".editorconfig"}
    has_git_dir = False
    for entry in entries:
        if entry.name == ".git" and entry.is_dir():
            has_git_dir = True
            continue
        if entry.is_file() and entry.name in allowed_root_files:
            continue
        return False
    return has_git_dir


def validate_answers(answers: dict[str, Any]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    platforms = answers.get("platforms", [])
    auth_methods = answers.get("auth_methods", [])

    if not platforms:
        errors.append("At least one platform must be selected.")
    if platforms and "password" not in auth_methods:
        errors.append("Prism currently requires Username + Password auth as the baseline sign-in method.")
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
    if dest_path.exists():
        entries = list(dest_path.iterdir())
        if entries and not is_generation_safe_existing_destination(entries):
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
        "Watch your product truth take shape: prism wiki graph --serve",
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
                    "workspaces",
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


def inspect_git_worktree(path: Path) -> dict[str, bool | str | None]:
    try:
        inside = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            check=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return {"is_repo": False, "is_dirty": False, "repo_root": None}

    if inside.stdout.strip() != "true":
        return {"is_repo": False, "is_dirty": False, "repo_root": None}

    try:
        repo_root = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
            capture_output=True,
            check=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        repo_root = None

    try:
        status = subprocess.run(
            ["git", "-C", str(path), "status", "--porcelain"],
            capture_output=True,
            check=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return {"is_repo": True, "is_dirty": False, "repo_root": repo_root}
    return {"is_repo": True, "is_dirty": bool(status.stdout.strip()), "repo_root": repo_root}


def is_direct_git_worktree(path: Path, repo_state: dict[str, bool | str | None] | None = None) -> bool:
    repo_state = repo_state or inspect_git_worktree(path)
    if not repo_state["is_repo"]:
        return False
    repo_root = repo_state.get("repo_root")
    if not repo_root:
        return False
    return Path(str(repo_root)).resolve() == path.resolve()


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
