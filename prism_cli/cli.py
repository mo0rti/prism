"""Prism CLI entry point."""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
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
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from prism_cli import __version__
from prism_cli.arguments import IntermixedParser
from prism_cli.app_model import (
    ALL_PLATFORM_CHOICES,
    BACKEND_CLIENT_STACKS,
    BACKEND_STACK,
    GENERATION_REGISTERED,
    GENERATION_SCAFFOLDED,
    SLUG_PATTERN,
    STACKS,
    WORKSPACE_REPOSITORY_ID,
    apps_from_platforms,
    normalize_manifest,
)
from prism_cli.fs_safety import CLOUD_SYNC_MESSAGE, find_cloud_placeholder
from prism_cli.layers import (
    GitError,
    Layer,
    LayerResult,
    branch_exists,
    changed_paths,
    commit_layer,
    create_branch,
    current_branch,
    has_commit_identity,
    scan_conflicts,
)
from prism_cli.manifest_update import ManifestUpdateError, load_workspace_manifest, prepare_manifest_update
from prism_cli.packs import (
    COMMIT_PATTERN,
    PACKAGE_IDENTIFIER_PATTERN,
    RESERVED_IDENTIFIERS,
    WORKSPACE_LAYER,
    app_answers_path,
    assign_ports,
    backend_port_of,
    layer_answers_problems,
    has_pack,
    pack_answers,
    parse_app_list,
    read_app_answers,
    scaffoldable_stacks,
    validate_scaffold,
    workflow_path,
    workspace_answers_problems,
    workspace_apps_problems,
    workspace_data,
)
from prism_cli.presets import (
    DEFAULT_ANSWERS,
    PRESETS,
    WORKFLOW_PRESETS,
    Preset,
    get_preset,
    merge_answers,
)
from prism_cli.render import render_or_print_wiki_query, render_status_result, render_wiki_lint_result
from prism_cli.safe_values import description_problem, label_problem
from prism_cli.status import BoardCheck, build_board_checks, build_status
from prism_cli.wiki_paths import resolve_confined
from prism_cli.workspace import (
    MANIFEST_FILE,
    confined_answers_file,
    detect_workspace_kind,
    inspect_workspace,
    write_workspace_manifest,
)
from prism_cli.wiki_model import VALID_FEATURE_OWNERS
from prism_cli.wiki_graph import build_graph, render_mermaid
from prism_cli.wiki_query import wiki_app, wiki_blockers, wiki_owner, wiki_search, wiki_show
from prism_cli.wiki_lint import WIKI_BLOCKER_CODES, lint_wiki
from prism_cli.wiki_transitions import SUPPORTED_ACTION, SUPPORTED_ACTIONS, build_transition_preflight
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
EXIT_UPDATE_CONFLICT = 6

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TEMPLATE_URL = "https://github.com/mo0rti/prism.git"
COPIER_ANSWERS_FILE = ".copier-answers.yml"
DEFAULT_GENERATED_DIR = "workspaces"
COPIER_PROGRESS_PATTERN = re.compile(r"^\s*(create|identical|overwrite|conflict|skip|remove)\s+(.+?)\s*$")


def default_template_reference() -> str:
    """Use the checkout while developing and the canonical template when installed."""

    if (REPO_ROOT / ".git").exists() and (REPO_ROOT / "copier.yml").exists():
        return str(REPO_ROOT)
    return DEFAULT_TEMPLATE_URL


def derive_project_slug(project_name: str) -> str:
    normalized = project_name.strip().lower().replace("_", "-").replace(" ", "-")
    normalized = re.sub(r"-{2,}", "-", normalized)
    return normalized or "generated-project"


def build_default_destination(project_name: str, project_slug: str | None = None) -> str:
    return str(Path(DEFAULT_GENERATED_DIR) / (project_slug or derive_project_slug(project_name)))


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
    stacks: tuple[str, ...] = ()
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
        description="Prism workflows and shared boards for humans and agents, with optional application generation.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.set_defaults(func=cmd_home, parser=parser)
    subparsers = parser.add_subparsers(dest="command", parser_class=IntermixedParser)
    from prism_cli.app_cli import register_commands as register_app_commands
    from prism_cli.board_cli import register_commands

    register_commands(subparsers)
    register_app_commands(subparsers)

    presets_parser = subparsers.add_parser("presets", help="Show recommended Prism presets.")
    presets_parser.add_argument("--json", action="store_true", help="Emit the presets as machine-readable JSON.")
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

    status_parser = subparsers.add_parser("status", help="Show Prism workspace status.")
    status_parser.add_argument("path", nargs="?", default=".", help="Generated project path. Defaults to the current directory.")
    status_parser.add_argument("--full", action="store_true", help="Show full diagnostics and detailed counts.")
    status_parser.add_argument("--json", action="store_true", help="Emit versioned machine-readable status output.")
    status_parser.set_defaults(func=cmd_status)

    validate_parser = subparsers.add_parser("validate", help="Validate the template repo or a generated Prism project.")
    validate_parser.add_argument("path", nargs="?", default=".", help="Path to validate. Defaults to the current directory.")
    validate_parser.add_argument("--trust-template", action="store_true", help="Allow custom template validation scripts to execute code.")
    validate_parser.add_argument(
        "--kind",
        choices=["auto", "template", "generated-project", "workflow-project"],
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
    wiki_subparsers = wiki_parser.add_subparsers(dest="wiki_command", parser_class=IntermixedParser)
    wiki_lint_parser = wiki_subparsers.add_parser("lint", help="Validate generated-project wiki schema and consistency.")
    wiki_lint_parser.add_argument("path", nargs="?", default=".", help="Generated project path. Defaults to the current directory.")
    wiki_lint_parser.add_argument("--json", action="store_true", help="Emit versioned machine-readable lint output.")
    wiki_lint_parser.set_defaults(func=cmd_wiki_lint)
    wiki_verify_parser = wiki_subparsers.add_parser(
        "verify",
        help="Record that wiki pages were checked against their sources: one `verify` entry in knowledge/wiki/log.md, no page changed.",
    )
    wiki_verify_parser.add_argument("pages", nargs="+", metavar="page", help="A current-state wiki page, as `knowledge/wiki/topics/pricing.md` or `topics/pricing.md`.")
    wiki_verify_parser.add_argument("--path", default=".", help="Generated project path. Defaults to the current directory.")
    wiki_verify_parser.add_argument("--evidence", help="A link to what was checked. Recorded as `none` when omitted.")
    wiki_verify_parser.add_argument("--by", help="Who verified the pages. Defaults to the operating-system user.")
    wiki_verify_parser.set_defaults(func=cmd_wiki_verify)
    wiki_show_parser = wiki_subparsers.add_parser("show", help="Show one feature and its app requirements.")
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
    wiki_app_parser = wiki_subparsers.add_parser("app", help="Show feature and requirement facts for one app.")
    wiki_app_parser.add_argument("app", help="ID of an app of the workspace to inspect.")
    wiki_app_parser.add_argument("path", nargs="?", default=".", help="Generated project path. Defaults to the current directory.")
    wiki_app_parser.add_argument("--json", action="store_true", help="Emit versioned machine-readable output.")
    wiki_app_parser.set_defaults(func=cmd_wiki_app)
    wiki_search_parser = wiki_subparsers.add_parser("search", help="Run conservative substring search across wiki feature facts.")
    wiki_search_parser.add_argument("query", help="Literal substring to search for.")
    wiki_search_parser.add_argument("path", nargs="?", default=".", help="Generated project path. Defaults to the current directory.")
    wiki_search_parser.add_argument("--json", action="store_true", help="Emit versioned machine-readable output.")
    wiki_search_parser.set_defaults(func=cmd_wiki_search)
    wiki_transition_parser = wiki_subparsers.add_parser(
        "transition-preflight",
        help="Evaluate a read-only lifecycle transition request against current wiki evidence.",
    )
    wiki_transition_parser.add_argument("feature_id", help="Feature id to evaluate, for example F-001.")
    wiki_transition_parser.add_argument("path", nargs="?", default=".", help="Generated project path. Defaults to the current directory.")
    wiki_transition_parser.add_argument(
        "--action",
        choices=list(SUPPORTED_ACTIONS),
        default=SUPPORTED_ACTION,
        help="Transition action to evaluate. Defaults to po-handoff.",
    )
    wiki_transition_parser.add_argument("--json", action="store_true", help="Emit versioned machine-readable output.")
    wiki_transition_parser.set_defaults(func=cmd_wiki_transition_preflight)
    wiki_graph_parser = wiki_subparsers.add_parser("graph", help="Render wiki relationship facts as JSON, Mermaid, or an interactive HTML dashboard.")
    wiki_graph_parser.add_argument("path", nargs="?", default=".", help="Generated project path. Defaults to the current directory.")
    wiki_graph_parser.add_argument("--json", action="store_true", help="Emit versioned machine-readable graph facts.")
    wiki_graph_parser.add_argument("--mermaid", action="store_true", help="Emit a Mermaid diagram (see --view).")
    wiki_graph_parser.add_argument("--view", choices=["lifecycle", "ego", "app"], default="lifecycle", help="Mermaid view. Defaults to lifecycle.")
    wiki_graph_parser.add_argument("--feature", help="Feature id for --view ego, for example F-001.")
    wiki_graph_parser.add_argument("--app", help="App ID for --view app.")
    wiki_graph_parser.add_argument("--html", nargs="?", const="", metavar="OUT", help="Write the interactive dashboard. Defaults to prism-graph.html in the workspace root.")
    wiki_graph_parser.add_argument("--open", action="store_true", help="Open the live local dashboard without saving a snapshot; Ctrl+C stops the server.")
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
    update_parser.add_argument("--trust-template", action="store_true", help="Allow the saved custom template to execute code.")
    update_parser.set_defaults(func=cmd_update)

    new_parser = subparsers.add_parser("new", help="Create a Prism project.")
    new_parser.add_argument("--preset", choices=[preset.slug for preset in PRESETS])
    new_parser.add_argument("--project-name")
    new_parser.add_argument("--project-slug", help="Explicit lowercase project slug used by Copier and the default destination.")
    new_parser.add_argument("--description")
    new_parser.add_argument("--package-identifier")
    new_parser.add_argument("--dest")
    new_parser.add_argument("--template", help="Custom template path or URL. Installed defaults use the matching Prism release tag.")
    new_parser.add_argument("--trust-template", action="store_true", help="Allow a custom template to execute code.")
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

    if context_kind in ("generated-project", "workflow-project"):
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
    if kind == "workflow-project":
        return "workflow-project", "workflow workspace"
    return "directory", "plain directory"


def build_home_actions(context_kind: str) -> list[SelectOption]:
    actions: list[SelectOption] = []

    if context_kind in ("workflow-project", "generated-project"):
        actions.append(SelectOption(value="board", label="Shared Board", meta="[board serve]",
            description="Open the local board and shared MCP connection for registered participants.", accent="action"))
        if context_kind == "workflow-project":
            actions.extend([
                SelectOption(value="status", label="Workspace Status", meta="[status]", description="Show workflow facts and blockers.", accent="action"),
                SelectOption(value="validate", label="Validate Workflow", meta="[validate]", description="Check the wiki contract without application build requirements.", accent="action"),
                SelectOption(value="dashboard", label="Read-only Dashboard", meta="[wiki graph]", description="Inspect current wiki facts without a participant token.", accent="action"),
            ])
    if context_kind == "directory":
        actions.append(SelectOption(value="workflow", label="Install Workflow", meta="[workflow install]",
            description="Preview a Prism workflow in this directory without generating applications.", accent="action"))

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
                    description="Interactive product-truth dashboard: pipeline, graph, blockers, apps.",
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
    elif context_kind != "workflow-project":
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
    elif context_kind not in ("generated-project", "workflow-project"):
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
    if selected == "board":
        parsed = parser.parse_args(["board", "serve"])
        return parsed.func(parsed)
    if selected == "workflow":
        name = prompt_text("Workspace name", Path.cwd().name)
        selected_apps = prompt_multiselect("Select generated apps to register (none is fine)", ALL_PLATFORM_CHOICES, allow_empty=True)
        command = ["workflow", "install", "--name", name, "--apply"]
        for selected_app in selected_apps:
            command.extend(["--app", selected_app])
        parsed = parser.parse_args(command)
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
    if getattr(_args, "json", False):
        print(json.dumps(presets_to_dict(), indent=2))
        return 0
    show_command_intro(_args, "Recommended generation paths")
    for preset in PRESETS:
        print(f"{preset.slug:<24} {maturity_badge(preset.maturity)}")
        print(f"  {preset.label}: {preset.summary}")
        print(f"  Apps: {preset_apps_text(preset)}")
        for note in preset.notes:
            print(f"  {warn(note)}")
        print()
    print(section("Workflow presets (no application is generated)"))
    for workflow_preset in WORKFLOW_PRESETS:
        print(workflow_preset.slug)
        print(f"  {workflow_preset.label}: {workflow_preset.summary}")
        print(f"  Command: {workflow_preset.command}")
        for note in workflow_preset.notes:
            print(f"  {note}")
        print()
    return 0


def preset_apps_text(preset: Preset) -> str:
    """A preset's app list on one line: each app's ID and stack."""

    return ", ".join(f"{app['id']} ({app['stack']})" for app in preset.apps)


def presets_to_dict() -> dict[str, Any]:
    """The presets for ``prism presets --json``: generation presets and workflow presets are separate lists."""

    return {
        "schema_version": 1,
        "command": "presets",
        "generation_presets": [
            {
                "slug": preset.slug,
                "label": preset.label,
                "maturity": preset.maturity,
                "summary": preset.summary,
                "apps": [{"id": app["id"], "stack": app["stack"], "path": app["path"]} for app in preset.apps],
                "notes": list(preset.notes),
            }
            for preset in PRESETS
        ],
        "workflow_presets": [
            {
                "slug": preset.slug,
                "label": preset.label,
                "summary": preset.summary,
                "command": preset.command,
                "notes": list(preset.notes),
            }
            for preset in WORKFLOW_PRESETS
        ],
    }


def cmd_doctor(_args: argparse.Namespace) -> int:
    show_command_intro(_args, "Environment checks for generation and common workflows")
    system = platform.system()
    incubation_mode = is_incubating_checkout()
    selected_preset = get_preset(_args.preset) if _args.preset else None
    workspace_status = build_status(Path(_args.workspace)) if getattr(_args, "workspace", None) else None
    if selected_preset:
        target_stacks = preset_stacks(selected_preset)
    elif workspace_status:
        target_stacks = workspace_status.workspace_stacks
    else:
        target_stacks = set()
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

    checks = build_doctor_checks(incubation_mode)
    workflow_only = bool(workspace_status and workspace_status.workspace_kind == "workflow-project" and not selected_preset)
    if workflow_only:
        checks = [check for check in checks if check.label == "Python"]
    results = evaluate_doctor_checks(checks, system, target_stacks)
    summary = summarize_doctor_results(results, selected_preset, folder_is_workspace=folder_is_prism_workspace(_args))
    core_missing = any(result.status == "missing" and result.check.blocking for result in results)
    print(panel("Summary", summary))
    print()

    cloud_synced = False
    board_failures: list[BoardCheck] = []
    if getattr(_args, "workspace", None):
        assert workspace_status is not None
        render_status_result(workspace_status, full=False)
        print()
        cloud_placeholder = find_cloud_placeholder(Path(_args.workspace))
        cloud_synced = cloud_placeholder is not None
        print(section("Shared board"))
        if cloud_placeholder is None:
            print(f"{board_check_badge('pass')} Workspace is outside cloud-synced folders")
        else:
            print(f"{board_check_badge('fail')} Workspace is outside cloud-synced folders")
            print(f"  {CLOUD_SYNC_MESSAGE}")
            print(f"  Detected at: {cloud_placeholder}")
        board_checks = build_board_checks(Path(_args.workspace))
        for board_check in board_checks:
            for line in render_board_check(board_check):
                print(line)
        board_failures = [board_check for board_check in board_checks if board_check.state == "fail"]
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

    workspace_errors = cloud_synced or bool(board_failures) or bool(
        workspace_status
        and (
            workspace_status.confidence == "error"
            or any(diagnostic["severity"] == "error" for diagnostic in workspace_status.to_dict()["diagnostics"])
        )
    )
    if workspace_errors:
        if board_failures:
            print(error(f"Shared board checks found {len(board_failures)} failure(s); apply the fixes above."))
        diagnostics = workspace_status.to_dict()["diagnostics"]
        blockers = [item for item in diagnostics if item["code"] in WIKI_BLOCKER_CODES]
        integrity = [item for item in diagnostics if item["severity"] == "error" and item["code"] not in WIKI_BLOCKER_CODES]
        if integrity:
            print(error(f"Workspace integrity checks found {len(integrity)} error(s)."))
        if blockers:
            print(warn(f"Workflow has {len(blockers)} unresolved blocker(s); these describe work that still needs attention."))
        return EXIT_VALIDATION

    if core_missing:
        print(error("Install the blocking core dependencies before running `prism new`."))
        return EXIT_ENVIRONMENT

    print(success("Prism workflow checks passed." if workflow_only else "Prism core generation is ready."))
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
            purpose="Needed to render Prism projects from the template.",
            impact="Prism generation is blocked until Copier is available in this Python environment.",
            install_hint="Install Copier and jinja2-time, or install this checkout in editable mode before running generation.",
            next_step_hint="Install Copier and jinja2-time before running prism new.",
            install_commands={
                "default": "python -m pip install copier jinja2-time",
            },
            install_references={
                "default": "https://copier.readthedocs.io/en/stable/",
            },
            resolver="copier",
            blocking=True,
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
            stacks=("spring-backend",),
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
            stacks=("spring-backend", "android-compose"),
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
            stacks=("ios-swiftui",),
            required_os="Darwin",
        ),
    ]
    return checks


def preset_stacks(preset: Preset) -> set[str]:
    """The stacks of a preset's apps."""

    return {app["stack"] for app in preset.apps}


def evaluate_doctor_checks(checks: list[DoctorCheck], system: str, target_stacks: set[str]) -> list[DoctorResult]:
    """Run the checks that apply to the target stacks; with no target stacks, every check applies."""

    results: list[DoctorResult] = []
    for check in checks:
        if check.stacks and target_stacks and not set(check.stacks).intersection(target_stacks):
            continue

        if check.packaged_status:
            detail = "Bundled with Prism or privately managed in packaged mode."
            results.append(DoctorResult(check=check, status=check.packaged_status, detail=detail))
            continue

        if check.required_os and system != check.required_os:
            detail = "Not applicable on this OS. Local validation for this tool is only supported on the required platform."
            results.append(DoctorResult(check=check, status="not-applicable", detail=detail))
            continue

        if check.resolver == "copier":
            resolved = f"{sys.executable} -m copier" if importlib.util.find_spec("copier") else None
        else:
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


def folder_is_prism_workspace(args: argparse.Namespace) -> bool:
    """True when doctor runs without a target inside a Prism workspace folder."""

    if getattr(args, "workspace", None) or getattr(args, "preset", None):
        return False
    try:
        return detect_workspace_kind(Path.cwd()) in {"workflow-project", "generated-project"}
    except (OSError, ValueError):
        return False


def summarize_doctor_results(results: list[DoctorResult], selected_preset: Preset | None, *, folder_is_workspace: bool = False) -> list[str]:
    core_missing = any(result.status == "missing" and result.check.blocking for result in results)
    workflow_missing = sum(1 for result in results if result.check.category == "workflow" and result.status == "missing")
    platform_missing = sum(
        1 for result in results if result.check.category in {"backend", "web", "build", "ios"} and result.status == "missing"
    )
    next_step = (
        "Run `prism doctor --workspace .` to check this workspace."
        if folder_is_workspace
        else "You can generate a Prism project now."
    )
    next_result = choose_next_doctor_result(results, preset_stacks(selected_preset) if selected_preset else set())
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


def choose_next_doctor_result(results: list[DoctorResult], target_stacks: set[str]) -> DoctorResult | None:
    missing_results = [result for result in results if result.status == "missing"]
    if not missing_results:
        return None

    def sort_key(result: DoctorResult) -> tuple[int, int, str]:
        platform_relevant = bool(target_stacks) and bool(set(result.check.stacks).intersection(target_stacks))
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


def board_check_badge(state: str) -> str:
    labels = {
        "pass": ("[ok]", (STYLE.green, STYLE.bold)),
        "warn": ("[warn]", (STYLE.yellow, STYLE.bold)),
        "fail": ("[fail]", (STYLE.red, STYLE.bold)),
        "skip": ("[skip]", (STYLE.dim,)),
    }
    label, styles = labels.get(state, ("[info]", (STYLE.white,)))
    return colorize(label, *styles)


def render_board_check(check: BoardCheck) -> list[str]:
    lines = [f"{board_check_badge(check.state)} {check.label}"]
    if check.detail:
        lines.append(f"  {check.detail}")
    if check.fix and check.state != "pass":
        lines.append(f"  {colorize('Fix:', STYLE.dim)} {check.fix}")
    return lines


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

    title = "Generated-project workspace status" if result.workspace_kind == "generated-project" else "Workspace status"
    show_command_intro(args, title)
    render_status_result(result, full=args.full)
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    target_path = Path(args.path).expanduser().resolve()
    kind = args.kind if args.kind != "auto" else detect_validation_target(target_path)

    show_command_intro(args, "Validate template integrity or generated project structure")
    print(panel("Target", [f"Path: {target_path}", f"Kind: {kind}"]))
    print()

    if kind == "template":
        return validate_template_repo(target_path, args.template_mode, getattr(args, "trust_template", False))
    if kind == "generated-project":
        return validate_generated_project(target_path)
    if kind == "workflow-project":
        return validate_workflow_project(target_path)

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


def cmd_wiki_verify(args: argparse.Namespace) -> int:
    from prism_cli.board_service import BoardError, BoardService

    try:
        with BoardService(Path(args.path)) as service:
            result = service.record_verification(args.pages, evidence=args.evidence, by=args.by)
    except (BoardError, OSError, ValueError) as exc:
        print(error(f"Verification failed: {exc}"), file=sys.stderr)
        return EXIT_VALIDATION
    count = len(result["paths"])
    print(success(f"Recorded one verification of {count} page{'s' if count != 1 else ''} in {result['log']}."))
    for page in result["paths"]:
        print(f"- {page}")
    return 0


def cmd_wiki_show(args: argparse.Namespace) -> int:
    result = wiki_show(Path(args.path), args.feature_id)
    return render_or_print_wiki_query(args, "Show wiki feature facts", result)


def cmd_wiki_blockers(args: argparse.Namespace) -> int:
    result = wiki_blockers(Path(args.path))
    return render_or_print_wiki_query(args, "Show wiki blockers", result)


def cmd_wiki_owner(args: argparse.Namespace) -> int:
    result = wiki_owner(Path(args.path), args.owner)
    return render_or_print_wiki_query(args, "Show wiki owner facts", result)


def _unknown_app_error(path: Path, app_id: str) -> str | None:
    """The message for an app ID the workspace does not declare, or ``None`` when it does."""

    model = inspect_workspace(path).model
    if model.app(app_id) is not None:
        return None
    declared = ", ".join(f"`{app.id}`" for app in model.apps) or "none"
    return f"`{app_id}` is not an app of this workspace; the workspace's apps are {declared}."


def cmd_wiki_app(args: argparse.Namespace) -> int:
    problem = _unknown_app_error(Path(args.path), args.app)
    if problem is not None:
        print(error(problem), file=sys.stderr)
        return EXIT_VALIDATION
    result = wiki_app(Path(args.path), args.app)
    return render_or_print_wiki_query(args, "Show wiki app facts", result)


def cmd_wiki_search(args: argparse.Namespace) -> int:
    result = wiki_search(Path(args.path), args.query)
    return render_or_print_wiki_query(args, "Search wiki facts", result)


def cmd_wiki_transition_preflight(args: argparse.Namespace) -> int:
    result = build_transition_preflight(Path(args.path), args.feature_id, args.action)
    return render_or_print_wiki_query(args, "Preflight wiki transition", result)


def cmd_wiki_graph(args: argparse.Namespace) -> int:
    target_path = Path(args.path).expanduser().resolve()

    if args.serve or args.open:
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
        if args.view == "app" and not args.app:
            print(error("--view app requires --app <app-id>."), file=sys.stderr)
            return EXIT_VALIDATION
        if args.view == "app":
            problem = _unknown_app_error(target_path, args.app)
            if problem is not None:
                print(error(problem), file=sys.stderr)
                return EXIT_VALIDATION
        print(render_mermaid(result, args.view, feature_id=args.feature, app_id=args.app))
        return 0

    if args.html is not None:
        from prism_cli.wiki_graph_html import write_dashboard

        out_path = Path(args.html) if args.html else target_path / "prism-graph.html"
        out_path = out_path.expanduser().resolve()
        knowledge_root = (target_path / "knowledge").resolve()
        if str(out_path).startswith(str(knowledge_root)):
            print(error("Refusing to write the dashboard inside knowledge/ — that directory is product truth."), file=sys.stderr)
            return EXIT_VALIDATION
        write_dashboard(result, out_path)
        print(success(f"Dashboard written: {out_path}"))
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
    try:
        answers_data = load_copier_answers(answers_path)
    except UpdateSafetyError as exc:
        print(error(str(exc)), file=sys.stderr)
        return EXIT_VALIDATION
    if answers_data is None:
        print(error(f"Missing {COPIER_ANSWERS_FILE} in generated project: {project_path}"), file=sys.stderr)
        print(info("Generate the project with the Prism CLI first, or add a valid Copier answers file before updating."), file=sys.stderr)
        return EXIT_VALIDATION

    src_path = answers_data.get("_src_path")
    if args.strategy != "recopy" and not has_trustworthy_template_baseline(src_path, answers_data):
        print(error("Copier smart update requires a trustworthy versioned template baseline."), file=sys.stderr)
        print(info("This project records an unversioned or unknown template snapshot. Use `prism update --strategy recopy` to explicitly reapply the template."), file=sys.stderr)
        return EXIT_VALIDATION

    strategy = resolve_update_strategy(args.strategy, answers_data)
    if strategy == "recopy" and not args.yes and not sys.stdin.isatty():
        print(error("Recopy can overwrite customized files. Non-interactive recopy requires `--yes`."), file=sys.stderr)
        return EXIT_VALIDATION
    src_path = answers_data.get("_src_path")
    if not ensure_template_trust(str(src_path), getattr(args, "trust_template", False)):
        return EXIT_VALIDATION
    layers, layer_problems = plan_update_layers(project_path, answers_data)
    if layer_problems:
        for message in layer_problems:
            print(error(message), file=sys.stderr)
        return EXIT_VALIDATION
    review_lines = [
        f"Project: {project_path}",
        f"Answers file: {answers_path.name}",
        f"Template source: {src_path or 'unknown'}",
        f"Strategy: {strategy}",
        f"Layers, committed one by one on an update branch: {', '.join(layer.name for layer in layers)}",
    ]
    show_command_intro(args, "Update a generated project from its original template")
    print(panel("Review", review_lines))
    print()

    prompt = "Reapply the template and overwrite customized files?" if strategy == "recopy" else "Update this Prism project now?"
    if not args.yes and not confirm(prompt, default=strategy != "recopy"):
        print(warn("Update cancelled."))
        return 0

    return run_copier_update(project_path, answers_data, strategy)


def cmd_new(args: argparse.Namespace) -> int:
    if args.answers and args.preset:
        print(error("`--answers` and `--preset` cannot be used together in v1."), file=sys.stderr)
        return EXIT_USAGE

    if not args.answers and not args.preset and not sys.stdin.isatty():
        print(error("Non-interactive `prism new` requires `--preset` or `--answers`."), file=sys.stderr)
        return EXIT_USAGE

    show_command_intro(args, "Scaffold a multi-platform project with guided defaults")
    answer_file_data = load_answers_file(args.answers) if args.answers else None
    if answer_file_data is None and args.answers:
        return EXIT_VALIDATION

    if args.answers:
        default_template = default_template_reference()
        template_path = args.template
        if args.template is None:
            template_path = answer_file_data.get("template_ref", default_template)
        destination = args.dest or answer_file_data.get("destination")
        answers = dict(answer_file_data.get("answers", {}))
    else:
        template_path = args.template or default_template_reference()
        destination = args.dest
        answers = {}

    if not args.answers:
        preset_answers = resolve_preset_answers(args)
        if preset_answers is None:
            return EXIT_USAGE
        answers = merge_answers(answers, preset_answers)

    cli_overrides = {
        "project_name": args.project_name,
        "project_slug": args.project_slug,
        "description": args.description,
        "package_identifier": args.package_identifier,
    }
    for key, value in cli_overrides.items():
        if value is not None and (key == "project_slug" or value):
            answers[key] = value

    merged_answers = merge_answers(DEFAULT_ANSWERS, answers)
    if "project_slug" not in merged_answers:
        project_name = merged_answers.get("project_name")
        if isinstance(project_name, str) and project_name.strip():
            merged_answers["project_slug"] = derive_project_slug(project_name)

    validation_errors, _validation_warnings = validate_answers(merged_answers)
    if validation_errors:
        for message in validation_errors:
            print(error(message), file=sys.stderr)
        return EXIT_VALIDATION

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
                build_default_destination(merged_answers["project_name"], merged_answers.get("project_slug")),
            )
        else:
            print(error("Destination is required in non-interactive mode. Use `--dest` or an answers file."), file=sys.stderr)
            return EXIT_VALIDATION

    dest_path = Path(destination).expanduser().resolve()
    if "project_slug" not in merged_answers:
        merged_answers["project_slug"] = derive_project_slug(merged_answers["project_name"])
    merged_answers.setdefault("package_identifier", default_package_identifier(merged_answers["project_slug"]))
    validation_errors, validation_warnings = validate_answers(merged_answers)
    if validation_errors:
        for message in validation_errors:
            print(error(message), file=sys.stderr)
        return EXIT_VALIDATION
    # From here on the app list is the normalized one: manifest entries, and the repositories they declare.
    apps, repositories, _app_errors = parse_app_list(merged_answers.get("apps"))
    merged_answers["apps"] = apps
    merged_answers["repositories"] = repositories

    if not ensure_template_trust(template_path, getattr(args, "trust_template", False)):
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

    vcs_ref = f"v{__version__}" if args.template is None and template_path == DEFAULT_TEMPLATE_URL else None
    return run_copier(template_path, dest_path, merged_answers, vcs_ref=vcs_ref)


def default_package_identifier(project_slug: str) -> str:
    """The package identifier `copier.yml` derives from a slug when none is given."""

    return f"com.example.{project_slug.replace('-', '')}"


def detect_validation_target(path: Path) -> str:
    kind = detect_workspace_kind(path)
    if kind == "template":
        return "template"
    if kind == "generated-project":
        return "generated-project"
    if kind == "workflow-project":
        return "workflow-project"
    return "unknown"


def validate_template_repo(path: Path, mode: str, trust_template: bool = False) -> int:
    if not ensure_template_trust(str(path), trust_template):
        return EXIT_VALIDATION
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


def validate_workflow_project(path: Path) -> int:
    inspection = inspect_workspace(path)
    errors = [item for item in inspection.contract_diagnostics if item.severity == "error"]
    for diagnostic in errors:
        print(error(diagnostic.message))
    wiki_result = lint_wiki(path)
    if wiki_result.diagnostics:
        render_wiki_lint_result(wiki_result, readiness=True)
    if errors or wiki_result.integrity_errors:
        return EXIT_VALIDATION
    if wiki_result.readiness_blockers:
        print(success("Workflow identity and wiki integrity checks passed; readiness blockers are reported above."))
    else:
        print(success("Workflow identity and wiki contract checks passed."))
    return 0


def validate_generated_project(path: Path) -> int:
    errors, warnings, detected_apps = validate_generated_project_structure(path)

    if detected_apps:
        print(section("Scaffolded apps"))
        print(", ".join(detected_apps))
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
    if wiki_result.diagnostics:
        render_wiki_lint_result(wiki_result, readiness=True)
    if wiki_result.integrity_errors:
        return EXIT_VALIDATION

    checks = [
        "README.md present",
        "AGENTS.md present",
        "knowledge/wiki/SCHEMA.md present",
        "knowledge/wiki/LIFECYCLE.md present",
        "Taskfile.yml present",
        "wiki contract checks passed",
        "scaffolded apps, their answers files and workflows present",
    ]
    print(panel("Validation passed", checks))
    if wiki_result.readiness_blockers:
        print(warn(f"Validation passed with {len(wiki_result.readiness_blockers)} workflow readiness blocker(s) reported above."))
    return 0


def validate_generated_project_structure(path: Path) -> tuple[list[str], list[str], list[str]]:
    """The structure of a generated workspace, read from its manifest.

    Every active app that Prism scaffolded needs its directory, its own ``.copier-answers.yml`` and its workflow
    ``.github/workflows/<app id>.yml``; the apps come from ``prism.workspace.yml``, never from directory names. Returns the
    errors, the warnings and the scaffolded apps found, each as ``<id> (<stack>)``.
    """

    errors: list[str] = []
    warnings: list[str] = []

    required_paths = [
        ("README.md", path / "README.md"),
        ("AGENTS.md", path / "AGENTS.md"),
        (MANIFEST_FILE, path / MANIFEST_FILE),
        ("knowledge/wiki/SCHEMA.md", path / "knowledge" / "wiki" / "SCHEMA.md"),
        ("knowledge/wiki/LIFECYCLE.md", path / "knowledge" / "wiki" / "LIFECYCLE.md"),
        ("Taskfile.yml", path / "Taskfile.yml"),
    ]
    for label, required_path in required_paths:
        if not required_path.exists():
            errors.append(f"Missing required generated-project file: {label}")

    inspection = inspect_workspace(path)
    errors.extend(diagnostic.message for diagnostic in inspection.contract_diagnostics if diagnostic.severity == "error")

    detected_apps: list[str] = []
    for app in inspection.model.workspace_apps(active_only=True):
        if app.generation != GENERATION_SCAFFOLDED:
            continue
        detected_apps.append(f"{app.id} ({app.stack})")
        if not (path / app.path).is_dir():
            continue  # the missing directory is already an error of the workspace comparison
        if not (path / app_answers_path(app.path)).is_file():
            errors.append(f"Missing answers file for scaffolded app `{app.id}`: {app_answers_path(app.path)}")
        workflow = workflow_path(app.id)
        if has_pack(app.stack) and not (path / workflow).is_file():
            errors.append(f"Missing workflow for scaffolded app `{app.id}`: {workflow}")

    if not detected_apps:
        warnings.append(f"No scaffolded apps are declared in {MANIFEST_FILE}.")

    return errors, warnings, detected_apps


def load_answers_file(path_str: str) -> dict[str, Any] | None:
    path = Path(path_str).expanduser()
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    except (OSError, UnicodeError) as exc:
        print(error(f"Unable to read answers file: {exc}"), file=sys.stderr)
        return None
    except (yaml.YAMLError, ValueError, OverflowError) as exc:
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
    """The saved answers of a layer, or ``None`` when the file is missing or unreadable.

    The path is confined before anything else touches it, so a link planted at its place is never opened, not even to
    ask whether it exists: a symlink or a reparse point raises `UpdateSafetyError` with the way out.
    """

    checked = confined_answers_path(path)
    try:
        with checked.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    except (OSError, UnicodeError):
        return None
    except (yaml.YAMLError, ValueError, OverflowError):
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


def has_trustworthy_template_baseline(src_path: Any, answers_data: dict[str, Any]) -> bool:
    """Smart update is supported only for a saved revision of a VCS source."""

    revision = answers_data.get("_commit")
    return (
        isinstance(src_path, str)
        and is_remote_template(src_path)
        and isinstance(revision, str)
        and COMMIT_PATTERN.fullmatch(revision) is not None
    )


def resolve_preset_answers(args: argparse.Namespace) -> dict[str, Any] | None:
    if args.preset:
        preset = get_preset(args.preset)
        if preset is None:
            print(error(f"Unknown preset: {args.preset}"), file=sys.stderr)
            return None
        print(info(f"Using preset: {preset.label} ({preset.maturity})"))
        return preset_answers(preset)

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
    return preset_answers(preset)


def preset_answers(preset: Preset) -> dict[str, Any]:
    """A preset's answers: its app list, which `prism new` scaffolds, and its other answers."""

    return {**{key: value for key, value in preset.answers.items()}, "apps": [dict(app) for app in preset.apps]}


def prompt_preset() -> str:
    if sys.stdin.isatty() and sys.stdout.isatty():
        options = [
            SelectOption(
                value=preset.slug,
                label=preset.label,
                meta=f"[{preset.slug}]",
                description=f"{preset.summary} Apps: {preset_apps_text(preset)}.",
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
        print(f"   Apps: {preset_apps_text(preset)}")
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
    selected = prompt_multiselect("Select the apps to scaffold (none is fine)", ALL_PLATFORM_CHOICES, default_values=["backend"], allow_empty=True)
    apps = apps_from_platforms(selected, generation=GENERATION_SCAFFOLDED)
    for app in apps:
        if app["stack"] == "nextjs-web":
            audience = prompt_text(f"Audience of `{app['id']}` (free text, empty for none)", "")
            if audience:
                app["audience"] = audience
    apps.extend(prompt_more_apps({app["id"] for app in apps}))
    prompt_backends(apps)

    return {
        "project_name": project_name,
        "description": description,
        "package_identifier": package_identifier,
        "apps": apps,
    }


def prompt_backends(apps: list[dict[str, Any]]) -> None:
    """With several backends, ask which one each generated client calls; a client that calls the first one records nothing."""

    backends = [app for app in apps if app["stack"] == BACKEND_STACK and app.get("generation") == GENERATION_SCAFFOLDED]
    if len(backends) < 2:
        return
    choices = tuple((backend["id"], f"{backend['id']} ({backend.get('name') or backend['id']})") for backend in backends)
    for app in apps:
        if app["stack"] not in BACKEND_CLIENT_STACKS or app.get("generation") != GENERATION_SCAFFOLDED:
            continue
        selected = prompt_multiselect(f"Backend that `{app['id']}` calls (choose one)", choices, default_values=[backends[0]["id"]], allow_empty=False)[0]
        if selected != backends[0]["id"]:
            app["backend"] = selected


def prompt_more_apps(taken_ids: set[str]) -> list[dict[str, Any]]:
    """Ask for further apps, each with an ID, a stack, a path and whether Prism scaffolds it or only registers it."""

    apps: list[dict[str, Any]] = []
    stack_choices = tuple((stack_id, stack_id) for stack_id in STACKS)
    while True:
        app_id = prompt_text("ID of another app (empty to finish)", "")
        if not app_id:
            return apps
        if app_id in taken_ids:
            print(warn(f"App `{app_id}` is already listed."))
            continue
        stack = prompt_multiselect(f"Stack of `{app_id}` (choose one)", stack_choices, allow_empty=False)[0]
        stack_info = STACKS[stack]
        entry: dict[str, Any] = {"id": app_id, "stack": stack, "name": prompt_text("Display name", app_id)}
        repository = prompt_text("Repository ID (`workspace` is this repository)", WORKSPACE_REPOSITORY_ID)
        if repository != WORKSPACE_REPOSITORY_ID:
            entry["repository"] = repository
            remote = prompt_text("Remote URL of that repository (empty if declared by an earlier app)", "")
            if remote:
                entry["remote"] = remote
        entry["path"] = prompt_text("Path in its repository", stack_info.default_path or app_id)
        audience = prompt_text("Audience (free text, empty for none)", "")
        if audience:
            entry["audience"] = audience
        if repository == WORKSPACE_REPOSITORY_ID and stack in scaffoldable_stacks():
            entry["generation"] = GENERATION_SCAFFOLDED if confirm(f"Scaffold `{app_id}` now? Otherwise it is only registered.", default=True) else GENERATION_REGISTERED
        taken_ids.add(app_id)
        apps.append(entry)


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


# What an answers file may set: the project identity and the app list.
ANSWER_KEYS = frozenset({"project_name", "project_slug", "package_identifier", "description", "apps"})


def validate_answers(answers: dict[str, Any]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    for field_name in (
        "project_name",
        "project_slug",
        "description",
        "package_identifier",
    ):
        if field_name in answers and not isinstance(answers[field_name], str):
            errors.append(f"{field_name} must be a string.")
    # The project's name and description reach generated code, configuration and CI: the shared safe-value rule applies.
    for field_name, check in (("project_name", label_problem), ("description", description_problem)):
        if isinstance(answers.get(field_name), str):
            problem = check(answers[field_name])
            if problem is not None:
                errors.append(f"{field_name} {problem}")

    unknown_answers = sorted(key for key in answers if not key.startswith("_") and key not in ANSWER_KEYS)
    if unknown_answers:
        errors.append(
            f"Unknown answer(s): {', '.join(unknown_answers)}. "
            f"Prism asks only for: {', '.join(sorted(ANSWER_KEYS))}."
        )

    package = ""
    project_name = answers.get("project_name")
    slug = ""
    if project_name or "project_slug" in answers:
        slug = answers.get("project_slug")
        if slug is None and isinstance(project_name, str):
            slug = derive_project_slug(project_name)
        if not isinstance(slug, str) or not SLUG_PATTERN.fullmatch(slug):
            errors.append("Project slug must start with a lowercase letter and contain lowercase letters, digits, and single hyphens.")
            slug = ""
        package = answers.get("package_identifier", default_package_identifier(slug))
        if not isinstance(package, str) or not PACKAGE_IDENTIFIER_PATTERN.fullmatch(package) or any(part in RESERVED_IDENTIFIERS for part in package.split(".")):
            errors.append("Package identifier must contain valid dot-separated Kotlin/Java identifiers, starting with letters and without reserved keywords.")

    apps: list[dict[str, Any]] = []
    if "apps" not in answers:
        errors.append("The app list is missing: name the workspace's apps under `apps` (an empty list is allowed).")
    else:
        apps, _repositories, app_errors = parse_app_list(answers["apps"])
        errors.extend(app_errors)
        if not app_errors:
            errors.extend(validate_scaffold(apps))

    if any(app["stack"] == "ios-swiftui" and app["generation"] == GENERATION_SCAFFOLDED for app in apps):
        warnings.append("Validate iOS generation locally on macOS before treating it as build-proven.")
    return errors, warnings


def render_summary(answers: dict[str, Any], dest_path: Path, template_path: str, warnings: list[str]) -> None:
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
    body.append(colorize("Apps", STYLE.bold, STYLE.blue))
    app_lines = [
        f"{app['id']} ({app['stack']}, {'scaffolded' if app.get('generation') == GENERATION_SCAFFOLDED else 'registered'}) at {app['path']}"
        for app in answers.get("apps", [])
    ]
    body.extend(review_key_value("Apps", "; ".join(app_lines) or "None", STYLE.cyan, STYLE.bold))
    print()
    print(panel("Generation Review", body))
    print()
    if warnings:
        warning_lines = [warn(message) for message in warnings]
        print(panel("Warnings", warning_lines))
        print()


def run_copier(template_path: str, dest_path: Path, answers: dict[str, Any], *, vcs_ref: str | None = None) -> int:
    """Generate a workspace: the workspace layer, then one app layer for each scaffolded app that has a pack.

    ``answers`` holds the project answers and ``apps``: the manifest entries of every app, and the
    ``repositories`` that external apps declare. Both layers come from one template, so one release tag covers them.
    """

    dest_path = dest_path.expanduser().resolve()
    if dest_path.exists() and dest_path.is_file():
        print(error(f"Destination already exists as a file: {dest_path}"), file=sys.stderr)
        return EXIT_VALIDATION
    if dest_path.exists():
        entries = list(dest_path.iterdir())
        if entries and not is_generation_safe_existing_destination(entries):
            print(error(f"Destination already exists and is not empty: {dest_path}"), file=sys.stderr)
            return EXIT_VALIDATION

    apps = [dict(app) for app in answers.get("apps", [])]
    repositories = [dict(item) for item in answers.get("repositories", [])]
    project = {
        "project_name": answers["project_name"],
        "project_slug": answers["project_slug"],
        "package_identifier": answers.get("package_identifier") or default_package_identifier(answers["project_slug"]),
    }
    ports = assign_ports(apps)
    workspace_answers = {key: value for key, value in answers.items() if key not in ("apps", "repositories") and not key.startswith("_")}
    workspace_answers.update(workspace_data(project, apps, ports))
    layers: list[tuple[Layer, dict[str, Any]]] = [(Layer(name=WORKSPACE_LAYER, answers_file=COPIER_ANSWERS_FILE), workspace_answers)]
    for app in apps:
        if app.get("generation") == GENERATION_SCAFFOLDED and has_pack(app["stack"]):
            layer = Layer(name=app["id"], answers_file=app_answers_path(app["path"]), app_id=app["id"], app_path=app["path"])
            layers.append((layer, pack_answers(project, app, port=ports.get(app["id"]), backend_port=backend_port_of(app, apps, ports))))

    print(section("Generating"))
    print(info("Running Copier with the resolved Prism configuration..."))
    if vcs_ref:
        print(info(f"Default generation requires the matching template release tag `{vcs_ref}`."))
    print()

    event_count = 0
    using_staged_template = should_stage_template_path(template_path)
    with staged_template_path(template_path) as effective_template:
        if using_staged_template:
            print(info("Using a temporary clean copy of the local template for generation."))
        for layer, data in layers:
            if not layer.is_workspace:
                print(info(f"Generating app `{layer.name}` at `{layer.app_path}`..."))
            command = copier_copy_command(effective_template, dest_path, data, answers_file=layer.answers_file, vcs_ref=vcs_ref, cli_version=layer.is_workspace)
            result = run_copier_generation_process(command, REPO_ROOT, capture_stderr=bool(vcs_ref))
            if result["returncode"] != 0 and vcs_ref and is_missing_template_tag_failure(vcs_ref, result):
                print(error(missing_template_tag_message(vcs_ref)), file=sys.stderr)
                return EXIT_VALIDATION
            if result.get("stderr"):
                print(result["stderr"], end="", file=sys.stderr)
            if result["returncode"] != 0:
                what = "Copier generation failed." if layer.is_workspace else f"Copier generation failed for app `{layer.name}`."
                print(error(what), file=sys.stderr)
                if result["tail"]:
                    print(panel("Copier output", list(result["tail"])), file=sys.stderr)
                return EXIT_COPIER
            event_count += result["event_count"]
            try:
                ensure_copier_answers_file(dest_path, template_path, data, answers_relpath=layer.answers_file)
            except UpdateSafetyError as exc:
                print(error(str(exc)), file=sys.stderr)
                return EXIT_VALIDATION
    manifest_answers = {key: answers[key] for key in ("project_name", "project_slug", "package_identifier", "description") if key in answers}
    if not refresh_workspace_manifest(dest_path, template_path, manifest_answers, apps=apps, repositories=repositories):
        return EXIT_VALIDATION
    if not pin_generated_workflow(dest_path):
        return EXIT_VALIDATION

    print()
    if event_count:
        print(success(f"Generated {event_count} file updates in {dest_path.name}."))
        print()
    next_steps = [
        f"Open the generated repo: {dest_path}",
        "Read README.md and AGENTS.md",
        "Run setup-project inside the generated repository",
        "Watch your product truth take shape: prism wiki graph --serve",
        "Build and test each scaffolded app before treating its slice as settled",
    ]
    print(panel("Success", next_steps))
    return 0


def pin_generated_workflow(dest_path: Path) -> bool:
    """Record the packaged workflow in a freshly generated workspace, so its board is writable once a grant is issued.

    This is the same reviewed install plan that ``prism workflow upgrade`` applies, run on files this CLI has just
    written: it pins the workflow version, the board identity and the digest of the packaged assets in the manifest.
    A workspace whose pin is missing or stale (an older CLI's, an edited manifest) stays read-only until an explicit
    ``prism workflow upgrade``.
    """

    from prism_cli.workflow_install import apply_install, plan_install

    try:
        plan = plan_install(dest_path, upgrade=True)
        if plan["conflicts"]:
            raise ValueError("; ".join(plan["conflicts"]))
        receipt = apply_install(dest_path, plan)
        if receipt.get("status") == "conflict":
            raise ValueError("; ".join(receipt.get("conflicts") or ["the workspace changed while it was pinned"]))
    except (OSError, ValueError) as exc:
        print(error(f"Could not pin the packaged workflow in the generated workspace: {exc}"), file=sys.stderr)
        print(info(f"Run `prism workflow upgrade {dest_path} --apply` after fixing the cause."), file=sys.stderr)
        return False
    return True


def copier_copy_command(
    template: Any,
    dest_path: Path,
    data: dict[str, Any],
    *,
    answers_file: str,
    vcs_ref: str | None,
    cli_version: bool = False,
) -> list[str]:
    """The `copier copy` command of one layer: its answers file, its answers as data and the template."""

    command = [sys.executable, "-m", "copier", "copy", "--trust", "--defaults", "--answers-file", answers_file]
    if vcs_ref:
        command.extend(["--vcs-ref", vcs_ref])
    for key, value in data.items():
        if key.startswith("_"):
            continue
        command.extend(["--data", f"{key}={format_data_value(value)}"])
    if cli_version:
        # This private context value lets the template carry truthful CLI
        # provenance even when the manifest post-processing step is skipped.
        command.extend(["--data", f"_prism_cli_version={__version__}"])
    command.extend([str(template), str(dest_path)])
    return command


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


def is_missing_template_tag_failure(vcs_ref: str, result: dict[str, Any]) -> bool:
    """Tell a missing release tag apart from other Copier failures (network, trust, answers)."""

    text = "\n".join([str(result.get("stderr") or ""), *map(str, result.get("tail") or [])])
    return "invalid reference" in text and vcs_ref in text


def missing_template_tag_message(vcs_ref: str) -> str:
    return (
        f"The template release tag `{vcs_ref}` is not published, so the default template cannot be used. "
        "Pass `--template <path or URL>` or install a released version of Prism."
    )


def run_copier_generation_process(command: list[str], cwd: Path, *, capture_stderr: bool = False) -> dict[str, Any]:
    if not sys.stdout.isatty():
        if capture_stderr:
            # Captured so a missing release tag becomes one message, not a Copier traceback.
            result = subprocess.run(command, cwd=str(cwd), stderr=subprocess.PIPE, text=True, errors="replace")
            return {"returncode": result.returncode, "event_count": 0, "tail": [], "stderr": result.stderr or ""}
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


def plan_update_layers(project_path: Path, workspace_answers: dict[str, Any] | None = None) -> tuple[list[Layer], list[str]]:
    """The layers `prism update` brings along: the workspace layer, then each active scaffolded app that has a pack.

    Every layer's saved answers are validated here, before any Copier call: the workspace layer's file must select
    the workspace layer and hold only safe values, and each app layer's file must come from the same approved source
    with the identity the manifest and the workspace give it. A scaffolded app whose own answers file is missing
    cannot be updated; that is a problem too, reported before anything changes. ``workspace_answers`` is the object the
    update goes on to use (read once by the caller); without it, the file is read here.
    """

    layers = [Layer(name=WORKSPACE_LAYER, answers_file=COPIER_ANSWERS_FILE)]
    problems: list[str] = []
    try:
        manifest = load_workspace_manifest(project_path / MANIFEST_FILE)
    except ManifestUpdateError as exc:
        return layers, [f"Unable to read {MANIFEST_FILE}: {exc}"]
    model, _diagnostics = normalize_manifest(manifest, path=project_path / MANIFEST_FILE)
    if workspace_answers is None:
        try:
            workspace_answers = load_copier_answers(project_path / COPIER_ANSWERS_FILE)
        except UpdateSafetyError as exc:
            return layers, [str(exc)]
    if not workspace_answers:
        return layers, [f"The workspace's {COPIER_ANSWERS_FILE} is missing or unreadable."]
    workspace_problems = workspace_answers_problems(workspace_answers)
    try:
        # The update goes on to give Copier the apps of the manifest, so those are rendered into files too.
        manifest_layer = workspace_layer_data_from_manifest(project_path)
        workspace_problems.extend(f"The manifest's apps: {problem}" for problem in workspace_apps_problems(manifest_layer["stacks"], manifest_layer["apps"]))
    except ManifestUpdateError as exc:
        workspace_problems.append(f"Unable to read {MANIFEST_FILE}: {exc}")
    if workspace_problems:
        return layers, workspace_problems
    approved_source = workspace_answers.get("_src_path")
    for app in model.workspace_apps(active_only=True):
        if not app.scaffolded or not has_pack(app.stack):
            continue
        recorded = read_app_answers(project_path, app.path)
        if recorded is None or "_src_path" not in recorded:
            problems.append(
                f"App `{app.id}` is scaffolded, but `{app_answers_path(app.path)}` is missing, sits behind a link or does not record its template. "
                f"Restore the file from git, or leave the app out of the update: retire it (`prism app retire {app.id}`), or drop its entry from {MANIFEST_FILE} "
                f"(or set its `generation` to `registered`) when Prism no longer keeps its code current."
            )
            continue
        entry = {"id": app.id, "name": app.name, "stack": app.stack, "path": app.path, "audience": app.audience or ""}
        layer_problems = layer_answers_problems(recorded, workspace_answers, entry, approved_source=str(approved_source))
        if layer_problems:
            problems.extend(layer_problems)
            continue
        layers.append(Layer(name=app.id, answers_file=app_answers_path(app.path), app_id=app.id, app_path=app.path))
    return layers, problems


def workspace_layer_data_from_manifest(project_path: Path) -> dict[str, Any]:
    """The answers the manifest decides for the workspace layer: the stacks and the app list of its scaffolded apps.

    A retired app stays on the list: retiring changes only its manifest entry, so the workspace layer keeps
    rendering its files (its compose service and task include) until its code is removed.
    """

    manifest = load_workspace_manifest(project_path / MANIFEST_FILE)
    model, _diagnostics = normalize_manifest(manifest, path=project_path / MANIFEST_FILE)
    apps = [
        {"id": app.id, "name": app.name, "stack": app.stack, "path": app.path, "audience": app.audience, "generation": app.generation}
        for app in model.workspace_apps()
        if app.scaffolded
    ]
    ports: dict[str, int | None] = {}
    for app in apps:
        recorded = read_app_answers(project_path, app["path"]) if has_pack(app["stack"]) else None
        port = recorded.get("port") if recorded else None
        ports[app["id"]] = port if isinstance(port, int) and not isinstance(port, bool) else None
    data = workspace_data({}, apps, ports)
    return {"stacks": data["stacks"], "apps": data["apps"]}


def run_copier_update(project_path: Path, answers_data: dict[str, Any], strategy: str) -> int:
    """Bring every layer of a generated workspace to one template revision, on an update branch with one commit per layer.

    The workspace layer goes first, then each scaffolded app from its own answers file. Copier needs a clean
    git tree for each update, so each layer is committed before the next. Copier exits 0 on a conflict, so
    after each layer the CLI scans for `.rej` files and conflict markers and reports per layer. The branch is
    left checked out for the user to review and merge; when any layer conflicted, the update stops there and
    names the layers to resolve first.
    """

    src_path = str(answers_data["_src_path"])
    manifest_plan = None
    print(section("Updating"))
    layers, problems = plan_update_layers(project_path, answers_data)
    if problems:
        for message in problems:
            print(error(message), file=sys.stderr)
        return EXIT_VALIDATION
    if not has_commit_identity(project_path):
        print(error("`prism update` commits each layer on an update branch, and git does not know who you are."), file=sys.stderr)
        print(info("Set `git config user.name` and `git config user.email` in this project, then retry."), file=sys.stderr)
        return EXIT_VALIDATION

    if strategy == "update":
        revision = answers_data.get("_commit")
        if not isinstance(revision, str) or not revision.strip():
            print(error("Copier smart update requires a trustworthy versioned template baseline."), file=sys.stderr)
            print(info("Use `prism update --strategy recopy` to explicitly reapply an unversioned template snapshot."), file=sys.stderr)
            return EXIT_VALIDATION
        for layer in layers[1:]:
            recorded = read_app_answers(project_path, layer.app_path) or {}
            if not has_trustworthy_template_baseline(recorded.get("_src_path"), recorded):
                print(error(f"App `{layer.name}` records an unversioned or unknown template snapshot, so Copier cannot update it."), file=sys.stderr)
                print(info("Use `prism update --strategy recopy` to explicitly reapply the template."), file=sys.stderr)
                return EXIT_VALIDATION
        try:
            manifest_plan = prepare_manifest_update(project_path, revision)
        except ManifestUpdateError as exc:
            print(error(f"Unable to safely update {MANIFEST_FILE}: {exc}"), file=sys.stderr)
            print(info("Resolve the manifest issue or conflict, commit the project, then retry."), file=sys.stderr)
            return EXIT_VALIDATION
        branch = f"prism-update-{branch_safe(manifest_plan.target_label or manifest_plan.target_ref[:8])}"
        print(info("Running Copier update, one layer at a time, with Prism-managed guardrails..."))
    else:
        branch = f"prism-recopy-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        print(info("Running Copier recopy, one layer at a time, with Prism-managed guardrails..."))
        print(warn("Recopy reapplies the template with the saved answers and does not preserve manual drift like `copier update`."))
    print()

    try:
        if branch_exists(project_path, branch):
            print(error(f"The update branch `{branch}` already exists."), file=sys.stderr)
            print(info("Merge or delete it, then retry."), file=sys.stderr)
            return EXIT_VALIDATION
        original = current_branch(project_path)
        data_for_workspace = workspace_layer_data_from_manifest(project_path)
        create_branch(project_path, branch)
    except (GitError, ManifestUpdateError) as exc:
        print(error(str(exc)), file=sys.stderr)
        return EXIT_VALIDATION
    print(info(f"Updating on branch `{branch}`; the layers are committed one by one."))
    print()

    results: list[LayerResult] = []
    using_staged_template = should_stage_template_path(src_path)
    with staged_template_path(src_path) as effective_template:
        if strategy == "recopy" and using_staged_template:
            print(info("Using a temporary clean copy of the local template for recopy."))
        for layer in layers:
            result = update_layer(
                project_path,
                layer,
                strategy,
                answers_data=answers_data,
                effective_template=effective_template,
                src_path=src_path,
                manifest_plan=manifest_plan,
                workspace_answers=data_for_workspace,
            )
            results.append(result)
            if result.outcome == "failed":
                break

    return report_update(project_path, branch, original, results, layers_total=len(layers), strategy=strategy)


def manifest_apps_snapshot(project_path: Path) -> tuple[list[dict[str, Any]] | None, list[dict[str, Any]] | None]:
    """The apps and repositories a workspace's manifest declares, as written, or ``None`` when it cannot be read."""

    try:
        data = yaml.safe_load((project_path / MANIFEST_FILE).read_text(encoding="utf-8-sig")) or {}
    except (OSError, UnicodeError, yaml.YAMLError, ValueError, OverflowError):
        return None, None
    if not isinstance(data, dict):
        return None, None
    apps = data.get("apps")
    repositories = data.get("repositories")
    return (
        [dict(item) for item in apps if isinstance(item, dict)] if isinstance(apps, list) else None,
        [dict(item) for item in repositories if isinstance(item, dict)] if isinstance(repositories, list) else None,
    )


def branch_safe(label: str) -> str:
    """A git branch name part from a template revision label."""

    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", label).strip("-.")
    return cleaned or "update"


class UpdateSafetyError(ValueError):
    """A path or a recorded answer that an update must not follow or trust."""


def confined_answers_path(path: Path) -> Path:
    """The checked path of an answers file, or an `UpdateSafetyError` that names the way out when it is a link or leaves its folder."""

    checked, refusal = confined_answers_file(path)
    if checked is None:
        raise UpdateSafetyError(refusal or f"{path.name} cannot be used.")
    return checked


def confined_project_path(project_path: Path, relative: str) -> Path:
    """The path of `relative` below the project, or an `UpdateSafetyError` when a component is a symlink or a reparse point.

    Every answers file the update reads or writes goes through this check, so a planted link cannot point a write
    outside the workspace. The final component is checked too: a link at the place of an answers file is refused.
    """

    resolution = resolve_confined(project_path, project_path, relative, percent_encoded=False)
    if not resolution.ok:
        raise UpdateSafetyError(f"`{relative}` cannot be used by the update: it {resolution.problem}")
    return resolution.path


def create_recopy_answers(project_path: Path, answers_file: str, answers: dict[str, Any]) -> Path:
    """Write a layer's answers for a recopy to a new file beside its answers file and return its path.

    The file is created exclusively (`tempfile.mkstemp` opens it with `O_CREAT | O_EXCL`) in a directory that is
    checked first, so a file or a link that someone planted under a predictable name is never opened.
    """

    directory_relative = answers_file[: -len(COPIER_ANSWERS_FILE)].rstrip("/")
    directory = confined_project_path(project_path, directory_relative) if directory_relative else project_path
    if directory.exists() and not directory.is_dir():
        raise UpdateSafetyError(f"`{directory_relative}` is not a directory.")
    confined_project_path(project_path, answers_file)
    descriptor, name = tempfile.mkstemp(prefix=".copier-answers.prism-recopy.", suffix=".yml", dir=directory)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        yaml.safe_dump(answers, handle, sort_keys=False)
    return Path(name)


def update_layer(
    project_path: Path,
    layer: Layer,
    strategy: str,
    *,
    answers_data: dict[str, Any],
    effective_template: Any,
    src_path: str,
    manifest_plan: Any,
    workspace_answers: dict[str, Any],
) -> LayerResult:
    """Update one layer with Copier, then scan it for conflicts and commit it."""

    label = "workspace layer" if layer.is_workspace else f"app `{layer.name}`"
    print(info(f"Updating the {label}..."))
    if layer.is_workspace:
        layer_answers = answers_data
    else:
        layer_answers = read_app_answers(project_path, layer.app_path) or {}

    # A recopy renders the template's manifest again, which names no apps: the workspace keeps its own.
    recorded_apps, recorded_repositories = manifest_apps_snapshot(project_path) if layer.is_workspace and strategy == "recopy" else (None, None)
    temp_answers_path: Path | None = None
    try:
        if strategy == "update":
            # Copier reads this file itself, so the path is confirmed to be a plain file right before it runs.
            confined_project_path(project_path, layer.answers_file)
            command = [sys.executable, "-m", "copier", "update", "--trust", "--defaults", "--conflict", "inline"]
            command.extend(["--vcs-ref", manifest_plan.target_ref, "--answers-file", layer.answers_file])
            if layer.is_workspace:
                command.extend(["--skip", MANIFEST_FILE, "--data", f"_prism_cli_version={__version__}"])
                for key, value in workspace_answers.items():
                    command.extend(["--data", f"{key}={format_data_value(value)}"])
        else:
            recorded = dict(layer_answers)
            recorded["_src_path"] = str(effective_template)
            temp_answers_path = create_recopy_answers(project_path, layer.answers_file, recorded)
            temp_relative = temp_answers_path.relative_to(project_path).as_posix()
            command = [sys.executable, "-m", "copier", "recopy", "--trust", "--defaults", "--overwrite", "--answers-file", temp_relative]
            if layer.is_workspace:
                command.extend(["--data", f"_prism_cli_version={__version__}"])
        command.append(str(project_path))
        completed = subprocess.run(command, cwd=str(project_path))
        if completed.returncode == 0 and temp_answers_path is not None and temp_answers_path.exists():
            # Replace, never write through: the target is confined and a link at its place is replaced, not followed.
            os.replace(temp_answers_path, confined_project_path(project_path, layer.answers_file))
    except UpdateSafetyError as exc:
        print(error(str(exc)), file=sys.stderr)
        return LayerResult(layer, "failed", detail=str(exc))
    finally:
        if temp_answers_path is not None and temp_answers_path.exists():
            temp_answers_path.unlink()

    if completed.returncode != 0:
        print(error(f"Updating the {label} failed."), file=sys.stderr)
        if strategy == "update" and layer.is_workspace:
            print(info("If this project was generated from the local incubation template, retry with `prism update --strategy recopy`."), file=sys.stderr)
        return LayerResult(layer, "failed", detail=f"Copier exited with {completed.returncode}")

    try:
        if layer.is_workspace:
            ensure_copier_answers_file(project_path, src_path, {})
        elif strategy == "recopy":
            ensure_copier_answers_file(project_path, src_path, {}, answers_relpath=layer.answers_file)
    except UpdateSafetyError as exc:
        print(error(str(exc)), file=sys.stderr)
        return LayerResult(layer, "failed", detail=str(exc))
    if layer.is_workspace:
        if not refresh_workspace_manifest(
            project_path,
            src_path,
            answers_data,
            manifest_data=manifest_plan.manifest if manifest_plan else None,
            expected_manifest_bytes=manifest_plan.source_manifest_bytes if manifest_plan else None,
            apps=recorded_apps,
            repositories=recorded_repositories,
        ):
            return LayerResult(layer, "failed", detail="the manifest could not be written")

    try:
        conflicts = scan_conflicts(project_path)
        changed = bool(changed_paths(project_path))
        commit = commit_layer(project_path, update_commit_message(layer, strategy, manifest_plan, conflicts))
    except GitError as exc:
        print(error(str(exc)), file=sys.stderr)
        return LayerResult(layer, "failed", detail=str(exc))
    if conflicts:
        return LayerResult(layer, "conflicted", conflicts=conflicts, commit=commit)
    return LayerResult(layer, "updated" if changed and commit else "unchanged", commit=commit)


def update_commit_message(layer: Layer, strategy: str, manifest_plan: Any, conflicts: list[str]) -> str:
    verb = "Recopy" if strategy == "recopy" else "Update"
    label = "workspace layer" if layer.is_workspace else f"app {layer.name}"
    target = f" to {manifest_plan.target_label or manifest_plan.target_ref[:8]}" if manifest_plan else ""
    message = f"{verb} {label}{target}"
    if conflicts:
        message += f"\n\nUnresolved conflicts in {len(conflicts)} file(s):\n" + "\n".join(f"- {path}" for path in conflicts)
    return message


def report_update(
    project_path: Path,
    branch: str,
    original: str | None,
    results: list[LayerResult],
    *,
    layers_total: int,
    strategy: str,
) -> int:
    """Report each layer, and say what to do next. Returns the exit code."""

    print()
    lines: list[str] = []
    for result in results:
        name = "workspace layer" if result.layer.is_workspace else f"app {result.layer.name}"
        if result.outcome == "conflicted":
            lines.append(f"{name}: CONFLICT in {len(result.conflicts)} file(s), committed as {result.commit}")
            lines.extend(f"    {path}" for path in result.conflicts)
        elif result.outcome == "updated":
            lines.append(f"{name}: updated, committed as {result.commit}")
        elif result.outcome == "unchanged":
            lines.append(f"{name}: already up to date")
        else:
            lines.append(f"{name}: FAILED ({result.detail})")
    skipped = layers_total - len(results)
    if skipped:
        lines.append(f"{skipped} later layer(s) were not updated.")
    print(panel("Update report", lines))
    print()

    return_to = f"git switch {original}" if original else "git switch -"
    if any(result.outcome == "failed" for result in results):
        print(error("The update stopped at a failed layer."), file=sys.stderr)
        print(info(f"Run `git status` on branch `{branch}` to see what was applied. To abandon the update: `{return_to}` then `git branch -D {branch}`."), file=sys.stderr)
        return EXIT_COPIER
    conflicted = [result.layer for result in results if result.outcome == "conflicted"]
    if conflicted:
        names = ", ".join("the workspace layer" if layer.is_workspace else f"app `{layer.name}`" for layer in conflicted)
        print(error(f"Update stopped before merging: {names} conflicted."), file=sys.stderr)
        print(info(f"The branch `{branch}` holds one commit per layer, with the conflicts as `<<<<<<<` markers. Resolve them there, commit, then merge it: `{return_to}` and `git merge {branch}`."), file=sys.stderr)
        return EXIT_UPDATE_CONFLICT
    verb = "recopy" if strategy == "recopy" else "update"
    print(success(f"Project {verb} finished on branch `{branch}`, one commit per layer. Review it, then merge it: `{return_to}` and `git merge --ff-only {branch}`."))
    return 0


def scaffold_app(
    workspace: Path,
    app: dict[str, Any],
    scaffold: dict[str, Any],
    *,
    write_manifest: Any,
    trust_template: bool = False,
) -> dict[str, Any]:
    """Generate one new app into a generated workspace, on a branch with one commit per layer.

    The workspace layer is brought in line with the new app list first: Copier updates it at the revision the
    workspace already records, with the new app in its data, so its compose file, task includes and guidance
    list the app. The app layer then comes from that same revision, with its own answers file, and
    ``write_manifest`` records the app. Returns the receipt fields: ``status`` (``applied`` or ``conflict``),
    ``conflicts``, ``branch`` and ``commits``. Nothing is printed, so a JSON receipt stays clean.
    """

    problems: list[str] = []
    try:
        answers = load_copier_answers(workspace / COPIER_ANSWERS_FILE)
    except UpdateSafetyError as exc:
        return {"status": "conflict", "conflicts": [str(exc)]}
    if answers is None:
        return {"status": "conflict", "conflicts": [f"The workspace's {COPIER_ANSWERS_FILE} is missing or unreadable."]}
    saved_problems = workspace_answers_problems(answers)
    if saved_problems:
        return {"status": "conflict", "conflicts": saved_problems}
    src_path = str(answers["_src_path"])
    ref = answers.get("_commit")
    if not has_trustworthy_template_baseline(src_path, answers):
        problems.append("The workspace records an unversioned or unknown template snapshot, so its template tag is unknown.")
    repo_state = inspect_git_worktree(workspace)
    if not is_direct_git_worktree(workspace, repo_state):
        problems.append("The workspace must be its own git repository to scaffold an app.")
    elif repo_state["is_dirty"]:
        problems.append("The working tree is not clean; commit or stash your changes, then retry.")
    elif not has_commit_identity(workspace):
        problems.append("Git does not know who commits; set `git config user.name` and `user.email` in this project.")
    if not template_is_trusted(src_path, trust_template):
        problems.append(f"The workspace's template `{src_path}` can execute code; review it and pass `--trust-template`.")
    branch = str(scaffold["branch"])
    try:
        if not problems and branch_exists(workspace, branch):
            problems.append(f"The branch `{branch}` already exists; merge or delete it, then retry.")
    except GitError as exc:
        problems.append(str(exc))
    if problems:
        return {"status": "conflict", "conflicts": problems}

    project = {key: answers[key] for key in ("project_name", "project_slug", "package_identifier")}
    port = scaffold.get("port")
    try:
        layer_data = workspace_layer_data_from_manifest(workspace)
    except ManifestUpdateError as exc:
        return {"status": "conflict", "conflicts": [f"Unable to read {MANIFEST_FILE}: {exc}"]}
    new_entry = {"id": app["id"], "name": app.get("name") or app["id"], "stack": app["stack"], "path": app["path"], "audience": app.get("audience") or "", "port": port or 0}
    apps_data = [*layer_data["apps"], new_entry]
    stacks_data = sorted({entry["stack"] for entry in apps_data})

    def run_quietly(command: list[str]) -> tuple[bool, str]:
        completed = subprocess.run(command, cwd=str(workspace), capture_output=True, text=True, errors="replace")
        return completed.returncode == 0, "\n".join(((completed.stdout or "") + (completed.stderr or "")).strip().splitlines()[-8:])

    abandon = f"To abandon it: `git switch {current_branch(workspace) or '-'}` then `git branch -D {branch}`."
    commits: list[str] = []
    conflicts: list[str] = []
    try:
        create_branch(workspace, branch)
        workspace_command = [sys.executable, "-m", "copier", "update", "--trust", "--defaults", "--conflict", "inline"]
        workspace_command.extend(["--vcs-ref", str(ref), "--answers-file", COPIER_ANSWERS_FILE, "--skip", MANIFEST_FILE])
        workspace_command.extend(["--data", f"_prism_cli_version={__version__}"])
        workspace_command.extend(["--data", f"stacks={format_data_value(stacks_data)}", "--data", f"apps={format_data_value(apps_data)}"])
        workspace_command.append(str(workspace))
        ok, output = run_quietly(workspace_command)
        if not ok:
            return {"status": "conflict", "branch": branch, "conflicts": [f"Updating the workspace layer failed: {output}", abandon]}
        workspace_conflicts = scan_conflicts(workspace)
        conflicts.extend(f"{path} (workspace layer)" for path in workspace_conflicts)
        note = f"\n\nUnresolved conflicts in {len(workspace_conflicts)} file(s)" if workspace_conflicts else ""
        commit = commit_layer(workspace, f"Scaffold {app['id']}: workspace layer{note}")
        if commit:
            commits.append(commit)

        data = pack_answers(project, app, port=port, backend_port=scaffold.get("backend_port"))
        app_command = copier_copy_command(src_path, workspace, data, answers_file=app_answers_path(app["path"]), vcs_ref=str(ref))
        ok, output = run_quietly(app_command)
        if not ok:
            return {"status": "conflict", "branch": branch, "commits": commits, "conflicts": [f"Generating app `{app['id']}` failed: {output}", abandon]}
        ensure_copier_answers_file(workspace, src_path, data, answers_relpath=app_answers_path(app["path"]))
        write_manifest()
        app_conflicts = scan_conflicts(workspace)
        conflicts.extend(f"{path} (app layer)" for path in app_conflicts)
        commit = commit_layer(workspace, f"Scaffold {app['id']}: app layer and manifest")
        if commit:
            commits.append(commit)
    except (GitError, OSError, ValueError) as exc:
        return {"status": "conflict", "branch": branch, "commits": commits, "conflicts": [str(exc), abandon]}
    if conflicts:
        details = [f"Unresolved conflict in {item}" for item in conflicts]
        details.append(f"The branch `{branch}` holds the work; resolve the markers there, commit, then merge it.")
        return {"status": "conflict", "branch": branch, "commits": commits, "conflicts": details}
    return {"status": "applied", "conflicts": [], "branch": branch, "commits": commits}


def ensure_copier_answers_file(dest_path: Path, template_path: str, answers: dict[str, Any], *, answers_relpath: str = COPIER_ANSWERS_FILE) -> None:
    # Confined first: a link at the place of an answers file is neither read nor written through.
    answers_path = confined_project_path(dest_path, answers_relpath)
    if is_remote_template(template_path) and answers_path.exists():
        # Copier recorded the template and its revision itself. Its rendering of this file is what a later
        # `copier update` compares against, so the file stays exactly as Copier wrote it.
        return
    remembered_answers: dict[str, Any] = {}
    if answers_path.exists():
        with contextlib.suppress(OSError, UnicodeError, yaml.YAMLError, ValueError, OverflowError):
            existing_data = yaml.safe_load(answers_path.read_text(encoding="utf-8")) or {}
            if isinstance(existing_data, dict):
                remembered_answers.update(existing_data)

    remembered_answers["_src_path"] = normalize_template_path(template_path)
    if not is_remote_template(template_path):
        # Local generation stages the working tree, so HEAD is not proof of the
        # content Copier rendered. Keep that snapshot explicitly unversioned.
        remembered_answers.pop("_commit", None)
    remembered_answers.update({key: value for key, value in answers.items() if not key.startswith("_")})
    with answers_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(remembered_answers, handle, sort_keys=False)


def refresh_workspace_manifest(
    destination: Path,
    template_path: str,
    answers: dict[str, Any],
    *,
    manifest_data: dict[str, Any] | None = None,
    expected_manifest_bytes: bytes | None = None,
    apps: list[dict[str, Any]] | None = None,
    repositories: list[dict[str, Any]] | None = None,
) -> bool:
    """Record known generation metadata after an explicit copy/update, and the chosen apps after a generation."""

    effective_answers = dict(answers)
    try:
        recorded_answers = load_copier_answers(destination / COPIER_ANSWERS_FILE)
    except UpdateSafetyError as exc:
        print(error(str(exc)), file=sys.stderr)
        return False
    if recorded_answers:
        effective_answers.update(recorded_answers)
    if is_remote_template(template_path):
        candidate = effective_answers.get("_commit")
        template_commit = candidate if isinstance(candidate, str) and candidate else None
        template_version = get_template_version(template_path) or template_commit
    else:
        # Local template generation renders a working snapshot, which may differ
        # from every commit and tag in its checkout.
        template_commit = "unversioned"
        template_version = "unversioned"
    try:
        if manifest_data is None:
            write_workspace_manifest(
                destination,
                effective_answers,
                prism_cli_version=__version__,
                template_source=normalize_template_path(template_path),
                template_version=template_version,
                template_commit=template_commit,
                apps=apps,
                repositories=repositories,
            )
        else:
            with tempfile.TemporaryDirectory(prefix="prism-manifest-") as temp_dir:
                manifest_path = Path(temp_dir) / MANIFEST_FILE
                manifest_path.write_text(yaml.safe_dump(manifest_data, sort_keys=False), encoding="utf-8")
                write_workspace_manifest(
                    Path(temp_dir),
                    {},
                    prism_cli_version=__version__,
                    template_source=normalize_template_path(template_path),
                    template_version=template_version,
                    template_commit=template_commit,
                )
                rendered = manifest_path.read_bytes()

            destination_manifest = destination / MANIFEST_FILE
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{destination_manifest.name}.",
                suffix=".prism-tmp",
                dir=destination_manifest.parent,
            )
            temporary_manifest = Path(temporary_name)
            try:
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(rendered)

                if expected_manifest_bytes is not None:
                    try:
                        current_manifest_bytes = destination_manifest.read_bytes()
                    except OSError as exc:
                        print(
                            error(f"Unable to verify {MANIFEST_FILE} before saving the merge: {exc}"),
                            file=sys.stderr,
                        )
                        print(info("The merged manifest was not written. Restore the file and rerun the update."), file=sys.stderr)
                        return False
                    if current_manifest_bytes != expected_manifest_bytes:
                        print(
                            error(f"{MANIFEST_FILE} changed after update preflight; the merged manifest was not written."),
                            file=sys.stderr,
                        )
                        print(info("Review the current manifest and rerun `prism update` to merge from its latest contents."), file=sys.stderr)
                        return False
                os.replace(temporary_manifest, destination_manifest)
            finally:
                with contextlib.suppress(OSError):
                    temporary_manifest.unlink()
    except (OSError, ValueError) as exc:
        print(error(f"Unable to write {MANIFEST_FILE}: {exc}"), file=sys.stderr)
        return False
    return True


def should_stage_template_path(template_path: str) -> bool:
    if is_remote_template(template_path):
        return False
    path = Path(template_path).expanduser().resolve()
    return path.is_dir() and (path / ".git").exists()


@contextlib.contextmanager
def staged_template_path(template_path: str):
    if is_remote_template(template_path):
        yield template_path
        return
    path = Path(template_path).expanduser().resolve()
    if should_stage_template_path(template_path):
        with tempfile.TemporaryDirectory(prefix="prism-template-") as temp_dir:
            staged_root = Path(temp_dir) / path.name
            ignored_names = shutil.ignore_patterns(
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
            )

            def ignore(directory: str, names: list[str]) -> set[str]:
                skipped = set(ignored_names(directory, names))
                if Path(directory) == path:
                    # The repository's golden workspace is generated output, never part of the template.
                    skipped.update(name for name in names if name == "golden")
                return skipped

            shutil.copytree(path, staged_root, ignore=ignore)
            yield staged_root
        return
    yield path


def format_data_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, dict)) and not (isinstance(value, list) and all(isinstance(item, str) for item in value)):
        # Nested values go through as JSON, which is also YAML.
        return json.dumps(value)
    if isinstance(value, list):
        return "[" + ", ".join(str(item) for item in value) + "]"
    return str(value)


def slugify(name: str) -> str:
    slug = name.strip().lower().replace("_", "-").replace(" ", "-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug


def is_remote_template(template_path: str) -> bool:
    return "://" in template_path or template_path.startswith(("gh:", "gl:", "git@", "git+")) or bool(
        re.match(r"^[^/\\:@]+@[^/\\:]+:", template_path)
    )


def template_is_trusted(template_path: str, explicitly_trusted: bool = False) -> bool:
    """Whether a template may execute code without asking: the canonical one, this checkout, or one the user trusted."""

    canonical = {DEFAULT_TEMPLATE_URL, DEFAULT_TEMPLATE_URL.removesuffix(".git"), "gh:mo0rti/prism"}
    local_maintainer = (REPO_ROOT / "copier.yml").is_file() and not is_remote_template(template_path) and Path(template_path).expanduser().resolve() == REPO_ROOT
    return bool(explicitly_trusted or template_path in canonical or local_maintainer)


def ensure_template_trust(template_path: str, explicitly_trusted: bool = False) -> bool:
    if template_is_trusted(template_path, explicitly_trusted):
        return True
    print(warn(f"Custom template `{template_path}` can execute Python extensions, hooks, and validation scripts."))
    if sys.stdin.isatty() and confirm("Trust this template to execute code?", default=False):
        return True
    print(error("Custom template execution requires explicit trust. Review the source, then use `--trust-template`."), file=sys.stderr)
    return False


def normalize_template_path(template_path: str) -> str:
    if is_remote_template(template_path):
        return template_path
    return str(Path(template_path).expanduser().resolve())


def get_template_commit(template_path: str) -> str | None:
    if is_remote_template(template_path):
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


def get_template_version(template_path: str) -> str | None:
    """Return a tag/ref description when the local template exposes one."""

    if is_remote_template(template_path):
        return None
    path = Path(template_path).expanduser().resolve()
    if not (path / ".git").exists():
        return None
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "describe", "--tags", "--always", "--dirty"],
            capture_output=True,
            check=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def supports_versioned_update(template_path: str) -> bool:
    if is_remote_template(template_path):
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
