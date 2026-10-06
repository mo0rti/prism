"""CLI entry points for workflow adoption and the local shared board.

Imports of transport dependencies stay lazy so the legacy read commands do not
start a service or create any persistent state.
"""

from __future__ import annotations

import argparse
import difflib
import json
from pathlib import Path
import sqlite3
import sys

from prism_cli.arguments import IntermixedParser
from prism_cli.workspace import PLATFORM_DIRS, inspect_workspace


def register_commands(subparsers) -> None:
    workflow = subparsers.add_parser("workflow", help="Install or upgrade the Prism workflow without generating applications.")
    actions = workflow.add_subparsers(dest="workflow_command", required=True, parser_class=IntermixedParser)
    for action in ("install", "upgrade"):
        parser = actions.add_parser(action, help=f"Preview a preserving workflow {action}; --apply confirms the displayed changes.")
        parser.add_argument("path", nargs="?", default=".")
        parser.add_argument("--name", help="Workspace display name; required for a new workspace.")
        parser.add_argument(
            "--app",
            action="append",
            choices=sorted(PLATFORM_DIRS),
            help="Generated app ID to register when the manifest declares no apps; repeat for several. Without it a new workspace has no apps.",
        )
        parser.add_argument("--apply", action="store_true", help="Apply the displayed plan after confirmation.")
        parser.add_argument("--yes", action="store_true", help="Confirm --apply without an interactive prompt.")
        parser.add_argument("--json", action="store_true", help="Emit the full installation plan or receipt as JSON.")
        parser.set_defaults(func=cmd_workflow)

    board = subparsers.add_parser("board", help="Run one local board and shared MCP connection for this workspace.")
    actions = board.add_subparsers(dest="board_command", required=True, parser_class=IntermixedParser)
    serve = actions.add_parser("serve", help="Serve the authenticated board and MCP endpoint on loopback.")
    serve.add_argument("path", nargs="?", default=".")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--no-open", action="store_true", help="Do not open a browser automatically.")
    serve.set_defaults(func=cmd_board_serve)
    grant = actions.add_parser("grant", help="Register a participant locally and print its access token once.")
    grant.add_argument("name")
    grant.add_argument("--path", default=".")
    grant.add_argument("--kind", choices=("human", "agent"), required=True)
    grant.add_argument("--write", action="store_true", help="Allow confirmed workflow operations; grants are read-only by default.")
    grant.set_defaults(func=cmd_board_participant)
    revoke = actions.add_parser("revoke", help="Revoke a participant's access immediately.")
    revoke.add_argument("participant_id")
    revoke.add_argument("--path", default=".")
    revoke.set_defaults(func=cmd_board_participant)
    status = actions.add_parser("status", help="Inspect workflow compatibility without creating service state.")
    status.add_argument("path", nargs="?", default=".")
    status.set_defaults(func=cmd_board_status)


def _json(value) -> None:
    # JSON escapes round-trip the full text even when Windows redirects stdout
    # through a legacy code page. Never mutate files and then fail on output.
    print(json.dumps(value, ensure_ascii=True, indent=2))


def _text(value: str, *, end: str = "\n", file=None) -> None:
    stream = file or sys.stdout
    encoding = getattr(stream, "encoding", None) or "utf-8"
    # Preserve otherwise unrepresentable code points as visible escapes in a
    # legacy terminal. The proposal and files keep their original UTF-8 bytes.
    print(value.encode(encoding, errors="backslashreplace").decode(encoding), end=end, file=stream)


def cmd_workflow(args: argparse.Namespace) -> int:
    from prism_cli.workflow_install import apply_install, plan_install

    try:
        root = Path(args.path).expanduser()
        plan = plan_install(root, name=args.name, apps=args.app, upgrade=args.workflow_command == "upgrade")
        if args.json:
            if not args.apply:
                _json(plan)
        else:
            _text(f"Prism workflow {args.workflow_command}: {root}")
            runtime_lock = plan.get("runtime_lock", {})
            if runtime_lock.get("required"):
                action = "Create and hold" if runtime_lock.get("creates") else "Hold"
                _text(f"{action} runtime lock: {runtime_lock.get('path', '.prism/state/board.lock')}")
            for change in plan.get("changes", []):
                before, after = change.get("before") or "", change.get("after") or ""
                _text("".join(difflib.unified_diff(
                    before.splitlines(keepends=True), after.splitlines(keepends=True),
                    fromfile=change["path"], tofile=change["path"],
                )), end="")
            for conflict in plan.get("conflicts", []):
                _text(f"Conflict: {conflict}", file=sys.stderr)
            for updated in plan.get("updated", []):
                _text(f"Updated: {updated}")
            for preserved in plan.get("preserved", []):
                _text(f"Preserved: {preserved}")
            for step in plan.get("optional_steps", []):
                _text(f"Optional: {step}")
        if plan.get("conflicts"):
            if args.json and args.apply:
                _json(plan)
            return 3
        if not args.apply:
            if not args.json:
                print("Preview only. Run again with --apply to confirm these changes.")
            return 0
        if not args.yes:
            if args.json or not sys.stdin.isatty():
                print("Applying non-interactively requires --apply --yes after reviewing the preview.", file=sys.stderr)
                return 2
            try:
                answer = input("Apply exactly this workflow installation? [y/N] ")
            except EOFError:
                answer = ""
            if answer.strip().lower() not in ("y", "yes"):
                print("Canceled; no files changed.")
                return 0
        receipt = apply_install(root, plan)
        if args.json:
            receipt = {**receipt, "plan": plan}
        _json(receipt)
        return 0 if receipt.get("status") in ("applied", "unchanged") else 3
    except (OSError, ValueError) as exc:
        _text(f"Workflow installation failed: {exc}", file=sys.stderr)
        return 3


def cmd_board_serve(args: argparse.Namespace) -> int:
    if not 1 <= args.port <= 65535:
        print("Port must be between 1 and 65535.", file=sys.stderr)
        return 2
    from prism_cli.board_server import serve_board

    return serve_board(Path(args.path), port=args.port, open_browser=not args.no_open)


def cmd_board_participant(args: argparse.Namespace) -> int:
    from prism_cli.board_service import BoardError, BoardService

    try:
        with BoardService(Path(args.path)) as service:
            if args.board_command == "grant":
                result = service.create_participant(args.name, args.kind, writable=args.write)
            else:
                result = service.revoke_participant(args.participant_id)
        _json(result)
        return 0
    except (BoardError, OSError, ValueError, sqlite3.Error) as exc:
        print(f"Participant management failed: {exc}", file=sys.stderr)
        return 3


def cmd_board_status(args: argparse.Namespace) -> int:
    from prism_cli.board_service import BoardError, BoardService

    try:
        with BoardService(Path(args.path)) as service:
            compatibility = service.compatibility()
    except (BoardError, OSError, ValueError) as exc:
        _json({"schema_version": 1, "compatible": False, "reason": str(exc),
               "next_step": "Preview an explicit prism workflow install or upgrade."})
        return 3
    result = inspect_workspace(Path(args.path))
    manifest = result.manifest
    workflow = manifest.workflow if manifest else {}
    errors = [item.to_dict() for item in result.contract_diagnostics if item.severity == "error"]
    compatible = not compatibility["read_only"] and not errors
    _json({
        "schema_version": 1,
        "project_name": result.project_name,
        "workflow": workflow,
        "compatible": compatible,
        "reason": compatibility.get("reason"),
        "diagnostics": [item.to_dict() for item in result.contract_diagnostics],
        "next_step": "prism board serve" if compatible else "Preview an explicit prism workflow install or upgrade.",
    })
    return 0 if compatible else 3
