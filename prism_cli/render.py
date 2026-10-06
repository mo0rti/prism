"""Human renderers for Prism's read-only surfaces.

The command module owns dispatch and mutation workflows.  Status, wiki lint,
and wiki query presentation lives here so every read surface can share the
same rendering code without importing the CLI entry point.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from prism_cli.status import WorkspaceStatus
from prism_cli.ui import (
    STYLE,
    colorize,
    error,
    info,
    panel,
    section,
    success,
    warn,
)
from prism_cli.wiki_lint import WikiLintResult


def render_or_print_wiki_query(args: argparse.Namespace, title: str, result: dict[str, Any]) -> int:
    facts = result.get("facts", {})
    exit_code = 0
    if result.get("command") == "wiki show" and not facts.get("feature"):
        exit_code = 3
    if result.get("command") == "wiki transition-preflight":
        transition = facts.get("transition", {})
        if transition.get("classification") != "ready" or not transition.get("supported"):
            exit_code = 3
    if args.json:
        print(json.dumps(result, indent=2))
        return exit_code

    show_command_intro(args, title)
    render_wiki_query_result(result)
    return exit_code


def render_wiki_lint_result(result: WikiLintResult, *, readiness: bool = False) -> None:
    if readiness:
        integrity_errors = result.integrity_errors
        blockers = result.readiness_blockers
        warnings = result.non_blocker_warnings
        print(panel("Wiki readiness", [
            f"Workspace: {result.root}",
            f"Features: {result.feature_count}",
            f"Integrity errors: {len(integrity_errors)}",
            f"Readiness blockers: {len(blockers)}",
            f"Warnings: {len(warnings)}",
        ]))
        for title, diagnostics, formatter in (
            ("Integrity errors", integrity_errors, error),
            ("Workflow readiness", blockers, warn),
            ("Warnings", warnings, warn),
        ):
            if not diagnostics:
                continue
            print()
            print(section(title))
            for diagnostic in diagnostics:
                location = diagnostic.path
                if diagnostic.feature_id:
                    location += f" [{diagnostic.feature_id}]"
                print(f"- {formatter(diagnostic.code)}: {diagnostic.message}")
                print(f"  {colorize(location, STYLE.dim)}")
        if not integrity_errors:
            print()
            print(success("Wiki integrity checks passed."))
        return

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
        formatter = error if diagnostic.severity == "error" else info if diagnostic.severity == "info" else warn
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
    elif command == "wiki app":
        render_wiki_app_facts(facts)
    elif command == "wiki search":
        render_wiki_search_facts(facts)
    elif command == "wiki transition-preflight":
        transition = facts.get("transition", {})
        print(panel("Transition preflight", [
            f"Feature: {(facts.get('feature') or {}).get('id', 'unknown')}",
            f"Action: {transition.get('action') or 'unavailable'}",
            f"Result: {transition.get('classification', 'unknown')}",
            f"Supported: {'yes' if transition.get('supported') else 'no'}",
        ]))
        for check in transition.get("checks", []):
            if check.get("status") != "pass":
                print(f"- {check.get('code')}: {check.get('message', '')}")
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
                f"Apps: {', '.join(feature.get('apps', [])) or 'none'}",
                f"Path: {feature.get('path')}",
            ],
        )
    )
    questions = feature.get("open_questions", [])
    requirements = feature.get("app_requirements", [])
    print()
    print(section("Open questions"))
    if questions:
        for question in questions:
            print(f"- {question.get('number')}: {question.get('question')} [{question.get('owner')}, {question.get('status')}]")
    else:
        print("- none")
    print()
    print(section("App requirements"))
    if requirements:
        for requirement in requirements:
            print(f"- {requirement.get('app')}: {requirement.get('status')} ({requirement.get('path')})")
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


def render_wiki_app_facts(facts: dict[str, Any]) -> None:
    print(panel("App", [f"App: {facts.get('app')}", f"Features: {facts.get('feature_count', 0)}", f"Requirements: {facts.get('app_requirement_count', 0)}"]))
    print()
    print(section("Features"))
    render_feature_summaries(facts.get("features", []))
    print()
    print(section("App requirements"))
    requirements = facts.get("app_requirements", [])
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
        *([f"Purpose: {info('knowledge root')}"] if result.knowledge_root else []),
        f"Apps: {', '.join(app['id'] for app in result.apps) if result.apps else 'none declared'}",
        f"Setup: {format_setup_state(result.setup_state)}",
        f"Confidence: {format_confidence(result.confidence)}",
    ]
    print(panel("Workspace", workspace_lines))
    if result.apps:
        print()
        print(section("Apps"))
        for line in format_apps_table(result.apps):
            print(line)
    for repository in result.repositories:
        if repository.get("checkout") is not None:
            print(format_repository_checkout(repository))
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
    if result.knowledge_root and result.wiki_lint.feature_count == 0:
        print()
        print(info("No features yet. A knowledge root holds shared knowledge for apps in other repositories; the feature lifecycle is optional."))

    caveats = [
        (app["id"], app["maturity"].get("caveat", ""))
        for app in result.apps
        if app.get("maturity") and app["maturity"].get("caveat")
    ]
    if caveats:
        print()
        print(section("App maturity"))
        for app_id, caveat in caveats:
            print(f"- {app_id}: {warn(caveat)}")

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
        print(section("Advisory review"))
        review = result.advisory_review_snapshot
        for key, value in compact_count_lines(review.counts):
            print(f"- {key}: {value}")
        if review.pending_feature_ids:
            print(f"- pending features: {', '.join(review.pending_feature_ids)}")

        print()
        print(section("Settings health"))
        settings = result.settings_health
        if settings:
            print(f"- health: {settings.health}")
            print(f"- stale after days: {settings.stale_after_days}")
            print(f"- source: {settings.source}")
            for diagnostic in settings.diagnostics:
                print(f"- {warn(diagnostic.code)}: {diagnostic.message}")
        else:
            print("- unavailable")

        print()
        print(section("Generation answers"))
        if result.generation_answers:
            for key, value in sorted(result.generation_answers.items()):
                print(f"- {key}: {format_detail_value(value)}")
        else:
            print("- unavailable")

        print()
        print(section("Template provenance"))
        metadata = result.template_metadata
        for key in (
            "template_source",
            "template_version",
            "template_commit",
            "generated_by_prism_cli_version",
            "generated_at",
        ):
            print(f"- {key}: {metadata.get(key) or 'unknown'}")

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
        if result.app_requirement_status_counts:
            print()
            print(section("App requirements"))
            for key, value in compact_count_lines(result.app_requirement_status_counts):
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


APP_TABLE_HEADERS = ("ID", "Name", "Stack", "Repository", "Path", "Status", "Maturity")


def format_apps_table(apps: list[dict[str, Any]]) -> list[str]:
    """Aligned plain-text rows for the declared apps: ID, name, stack, repository, path, status and maturity."""

    rows = [
        (
            str(app["id"]),
            str(app["name"]),
            str(app["stack"]),
            str(app["repository"]),
            str(app["path"]),
            str(app["status"]),
            str((app.get("maturity") or {}).get("level") or "-"),
        )
        for app in apps
    ]
    widths = [max(len(row[column]) for row in [APP_TABLE_HEADERS, *rows]) for column in range(len(APP_TABLE_HEADERS))]

    def line(row: tuple[str, ...]) -> str:
        return "  ".join(cell.ljust(width) for cell, width in zip(row, widths)).rstrip()

    return [line(APP_TABLE_HEADERS), *(line(row) for row in rows)]


def format_repository_checkout(repository: dict[str, Any]) -> str:
    """One line saying whether an external repository's checkout is resolved on this machine."""

    if repository.get("checkout") == "resolved":
        return f"Repository {repository['id']}: checkout resolved"
    return f"Repository {repository['id']}: checkout {warn('unresolved')} (add it to prism.local.yml)"


def show_command_intro(args: argparse.Namespace, subtitle: str) -> None:
    if getattr(args, "from_launcher", False):
        print()
        print(section(subtitle))
        print()
        return
    from prism_cli.ui import header

    print(header(subtitle))


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


def format_detail_value(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value) or "none"
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True)
    if value is None:
        return "none"
    return str(value)
