"""``prism app``: list the workspace's apps, register a new one, scaffold one and retire one.

Registering or retiring an app edits ``prism.workspace.yml`` only; it never
generates, moves or deletes code, pages or evidence. ``prism app add --scaffold``
also generates the new app's code from the workspace's template tag, on a branch
with one commit per layer. The new manifest is validated by the one normalizer
before anything is written, and the write goes through the same safe-path and
atomic-replace helpers that ``prism workflow install`` uses.
"""

from __future__ import annotations

import argparse
import difflib
import json
from pathlib import Path
import sys
from typing import Any

import yaml

from prism_cli.app_model import (
    BACKEND_CLIENT_STACKS,
    CAPABILITIES,
    CAPABILITY_HAS_UI,
    CAPABILITY_SERVES_API,
    GENERATION_SCAFFOLDED,
    STACKS,
    UNKNOWN,
    WORKSPACE_REPOSITORY_ID,
    WorkspaceDiagnostic,
    app_entries,
    normalize_manifest,
    resolve_local_repositories,
)
from prism_cli.packs import (
    allocate_port,
    backend_port_in_workspace,
    scaffold_collisions,
    stack_maturity,
    taken_ports,
    validate_scaffold,
    workflow_path,
    workspace_answers_problems,
)
from prism_cli.workflow_install import (
    _atomic_write,
    _parse_manifest,
    _raw_digest,
    _read_path_bytes,
    _safe_target,
    _validated_root,
)
from prism_cli.arguments import IntermixedParser
from prism_cli.wiki_model import read_feature_pages
from prism_cli.workspace import MANIFEST_FILE, inspect_workspace


CAPABILITY_CHOICES = ("true", "false", UNKNOWN)

IDENTITY_NOTICE = (
    "The board identity changed: the app scope is part of it. Stop a running board and start it again with `prism board serve`, "
    "and reissue grants with `prism board grant` for any participant the board rejects."
)


def register_commands(subparsers) -> None:
    app = subparsers.add_parser("app", help="List the workspace's apps, register or scaffold a new one, or retire one.")
    actions = app.add_subparsers(dest="app_command", required=True, parser_class=IntermixedParser)

    list_parser = actions.add_parser("list", help="Show the apps and repositories of a workspace.")
    list_parser.add_argument("path", nargs="?", default=".", help="Workspace path. Defaults to the current directory.")
    list_parser.add_argument("--json", action="store_true", help="Emit the apps and repositories as JSON.")
    list_parser.set_defaults(func=cmd_app_list)

    add_parser = actions.add_parser(
        "add",
        help="Preview registering an app in prism.workspace.yml; --apply writes it. No code is generated unless --scaffold is given.",
    )
    add_parser.add_argument("id", help="Stable app ID: lowercase letters, digits and single hyphens. It is never reused.")
    add_parser.add_argument("path", nargs="?", default=".", help="Workspace path. Defaults to the current directory.")
    add_parser.add_argument("--stack", required=True, choices=list(STACKS), help="The app's stack from the registry.")
    add_parser.add_argument("--name", help="Display name. Defaults to the app ID.")
    add_parser.add_argument("--repository", help=f"Repository ID. Defaults to `{WORKSPACE_REPOSITORY_ID}`, this repository.")
    add_parser.add_argument("--remote", help="Canonical remote URL; allowed only when --repository names a repository the manifest does not declare yet.")
    add_parser.add_argument("--path", dest="app_path", metavar="PATH", help="App directory relative to its repository. Defaults to the stack's default path, else the app ID.")
    add_parser.add_argument("--audience", help="Free-text audience, for example B2C.")
    add_parser.add_argument(
        "--backend",
        metavar="APP_ID",
        help="The backend app this app calls (a web, Android, iOS or agent-service app). Without it a generated app calls the first backend Prism scaffolded.",
    )
    add_parser.add_argument("--has-ui", choices=CAPABILITY_CHOICES, help="Override the stack's has-ui capability; required for an `other` app.")
    add_parser.add_argument("--serves-api", choices=CAPABILITY_CHOICES, help="Override the stack's serves-api capability; required for an `other` app.")
    add_parser.add_argument(
        "--scaffold",
        action="store_true",
        help=(
            "Also generate the app's code from the template tag the workspace records (a stack with a pack, in this repository). "
            "With --apply it works on a branch with one commit per layer, and needs a git repository with a clean working tree."
        ),
    )
    add_parser.add_argument("--trust-template", action="store_true", help="Allow the workspace's custom template to execute code while scaffolding.")
    add_parser.add_argument("--apply", action="store_true", help="Write the displayed change after confirmation.")
    add_parser.add_argument("--yes", action="store_true", help="Confirm --apply without an interactive prompt.")
    add_parser.add_argument("--json", action="store_true", help="Emit the plan or receipt as JSON.")
    add_parser.set_defaults(func=cmd_app_add)

    retire_parser = actions.add_parser(
        "retire",
        help="Preview retiring an app in prism.workspace.yml; --apply writes it. No code, page or evidence is deleted.",
    )
    retire_parser.add_argument("id", help="The ID of the app to retire.")
    retire_parser.add_argument("path", nargs="?", default=".", help="Workspace path. Defaults to the current directory.")
    retire_parser.add_argument("--apply", action="store_true", help="Write the displayed change after confirmation.")
    retire_parser.add_argument("--yes", action="store_true", help="Confirm --apply without an interactive prompt.")
    retire_parser.add_argument("--json", action="store_true", help="Emit the plan or receipt as JSON.")
    retire_parser.set_defaults(func=cmd_app_retire)


def _json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=True, indent=2))


def _text(value: str, *, end: str = "\n", file=None) -> None:
    stream = file or sys.stdout
    encoding = getattr(stream, "encoding", None) or "utf-8"
    print(value.encode(encoding, errors="backslashreplace").decode(encoding), end=end, file=stream)


# --- prism app list -----------------------------------------------------------


def cmd_app_list(args: argparse.Namespace) -> int:
    from prism_cli.render import format_apps_table, format_repository_checkout

    inspection = inspect_workspace(Path(args.path))
    manifest = inspection.manifest
    diagnostics = [item.to_dict() for item in inspection.load_result.diagnostics]
    if manifest is None:
        if args.json:
            _json({"schema_version": 1, "command": "app list", "root": str(inspection.root), "apps": [], "repositories": [], "diagnostics": diagnostics})
        else:
            _text(f"No usable {MANIFEST_FILE} in {inspection.root}.", file=sys.stderr)
            for item in diagnostics:
                _text(f"- {item['code']}: {item['message']}", file=sys.stderr)
        return 3
    apps = inspection.apps
    repositories = inspection.repositories
    if args.json:
        _json(
            {
                "schema_version": 1,
                "command": "app list",
                "root": str(inspection.root),
                "apps": apps,
                "repositories": repositories,
                "diagnostics": diagnostics,
            }
        )
        return 0
    _text(f"Apps in {inspection.root}")
    if apps:
        for line in format_apps_table(apps):
            _text(line)
    else:
        _text("No apps declared. Register one with `prism app add <id> --stack <stack>`.")
    for repository in repositories:
        if repository.get("checkout") is not None:
            _text(format_repository_checkout(repository))
    for item in diagnostics:
        _text(f"- {item['severity']} {item['code']}: {item['message']}")
    return 0


# --- prism app add ------------------------------------------------------------


def plan_app_add(
    root: Path,
    app_id: str,
    stack: str,
    *,
    name: str | None = None,
    repository: str | None = None,
    remote: str | None = None,
    path: str | None = None,
    audience: str | None = None,
    capabilities: dict[str, bool | str] | None = None,
    scaffold: bool = False,
    backend: str | None = None,
) -> dict[str, Any]:
    """The exact manifest change that registers one app. Nothing is written.

    The plan lists ``conflicts`` (error findings; the plan cannot be applied)
    and ``warnings``. Without conflicts, ``changes`` holds the manifest text
    before and after. With ``scaffold``, the app is recorded as scaffolded and
    the plan's ``scaffold`` names what generating its code needs and does.
    """

    workspace = _validated_root(root)
    capabilities = capabilities or {}
    conflicts: list[str] = []
    warnings: list[str] = []
    notes: list[str] = []
    changes: list[dict[str, str | None]] = []
    app_entry: dict[str, Any] | None = None
    repository_entry: dict[str, Any] | None = None
    scaffold_plan: dict[str, Any] | None = None
    manifest_bytes: bytes | None = None
    try:
        manifest_bytes = _read_path_bytes(workspace, MANIFEST_FILE, allow_missing=True)
        if manifest_bytes is None:
            raise ValueError(f"{MANIFEST_FILE} is missing; install the workflow or generate a workspace first.")
        data, bom = _parse_manifest(manifest_bytes)
        before = manifest_bytes.decode("utf-8-sig")
        stack_info = STACKS.get(stack)
        if stack_info is None:
            raise ValueError(f"Unknown stack `{stack}`; the registry has {', '.join(STACKS)}.")
        repository_id = repository if repository is not None else WORKSPACE_REPOSITORY_ID
        # Argument problems get a message about the flags; the normalizer's duplicates of them are left out below.
        explained: set[str] = set()
        if _check_repository_arguments(data, repository, remote, conflicts):
            explained.add("unknown-app-repository")
        if not stack_info.default_capabilities:
            missing = [f"--{'has-ui' if name_ == CAPABILITY_HAS_UI else 'serves-api'}" for name_ in CAPABILITIES if name_ not in capabilities]
            if missing:
                conflicts.append(f"An `{stack}` app has no stack defaults, so it needs {' and '.join(missing)} (true, false or unknown).")
                explained.add("undeclared-app-capability")
        app_path = path if path is not None else (stack_info.default_path or app_id)
        app_entry = {"id": app_id, "name": name if name is not None else app_id, "stack": stack, "repository": repository_id, "path": app_path}
        if audience is not None:
            app_entry["audience"] = audience
        if backend is not None:
            app_entry["backend"] = backend
        if capabilities:
            app_entry["capabilities"] = {key: capabilities[key] for key in CAPABILITIES if key in capabilities}
        if scaffold:
            if repository is not None or remote is not None:
                conflicts.append("--scaffold generates the app in this repository; do not pass --repository or --remote.")
            elif not stack_info.generated:
                conflicts.append(f"Stack `{stack}` cannot be scaffolded; register the app instead.")
            else:
                app_entry["generation"] = GENERATION_SCAFFOLDED

        new_data = dict(data)
        new_data["apps"] = [*(data.get("apps") if isinstance(data.get("apps"), list) else []), app_entry]
        if remote is not None and repository is not None:
            repository_entry = {"id": repository, "remote": remote}
            existing = data.get("repositories")
            new_data = _with_repositories(new_data, [*(existing if isinstance(existing, list) else []), repository_entry])
        elif "apps" in data and not isinstance(data["apps"], list):
            conflicts.append(f"{MANIFEST_FILE} `apps` must be a list before an app can be added.")

        model, diagnostics = normalize_manifest(new_data, path=Path(MANIFEST_FILE))
        errors = [item for item in diagnostics if item.severity == "error"]
        conflicts.extend(_diagnostic_text(item) for item in errors if item.code not in explained)
        if scaffold and app_entry.get("generation") == GENERATION_SCAFFOLDED and not errors:
            scaffold_plan = _plan_scaffold(workspace, model, app_entry, new_data, conflicts, notes)
            if scaffold_plan is not None:
                new_data = _with_scaffold_surfaces(new_data, app_entry)
        if not errors:
            if repository_id == WORKSPACE_REPOSITORY_ID and not scaffold and not (workspace / app_path).exists():
                warnings.append(f"Path `{app_path}` does not exist yet; create the app's code there. Nothing is generated.")
            if repository_entry is not None:
                warnings.extend(
                    item.message
                    for item in resolve_local_repositories(workspace, model).diagnostics
                    if item.code == "external-repository-unresolved" and f"`{repository}`" in item.message
                )
        if not conflicts:
            after = yaml.safe_dump(new_data, sort_keys=False, allow_unicode=True)
            if bom:
                after = "\ufeff" + after
            changes.append({"path": MANIFEST_FILE, "before": before, "after": after})
    except (OSError, UnicodeError, ValueError, yaml.YAMLError) as exc:
        conflicts.append(f"Unable to safely inspect this workspace: {exc}")
        changes = []
    plan = {
        "schema_version": 1,
        "command": "app add",
        "root": str(workspace),
        "app": app_entry,
        "repository": repository_entry,
        "changes": changes,
        "conflicts": list(dict.fromkeys(conflicts)),
        "warnings": list(dict.fromkeys(warnings)),
        "board_identity_changed": True,
        "notice": IDENTITY_NOTICE,
        "source_manifest_digest": _raw_digest(manifest_bytes),
    }
    if scaffold:
        plan["scaffold"] = scaffold_plan
        plan["notes"] = list(dict.fromkeys(notes))
    return plan


def _plan_scaffold(
    workspace: Path,
    model: Any,
    app_entry: dict[str, Any],
    new_data: dict[str, Any],
    conflicts: list[str],
    notes: list[str],
) -> dict[str, Any] | None:
    """What scaffolding the new app needs and does, or ``None`` with the reasons recorded in ``conflicts``.

    The app's code comes from the template revision the workspace records, so it matches the workspace layer
    and every other app. The workspace layer is brought in line with the new app list first, which needs a
    git repository with a clean working tree: Copier updates against the last commit.
    """

    from prism_cli import cli

    try:
        root = cli.read_answers_snapshot(workspace, cli.COPIER_ANSWERS_FILE)
    except cli.UpdateSafetyError as exc:
        conflicts.append(str(exc))
        return None
    answers = root.data if root is not None and "_src_path" in root.data else None
    if root is None or answers is None:
        conflicts.append(f"Scaffolding needs the workspace's {cli.COPIER_ANSWERS_FILE}, which records the template and the project identity; it is missing or unreadable.")
        return None
    src_path = answers.get("_src_path")
    if not cli.has_trustworthy_template_baseline(src_path, answers):
        conflicts.append(
            "This workspace records an unversioned or unknown template snapshot, so Prism cannot scaffold from \"the workspace's template tag\". "
            "Generate the workspace from a versioned template, or register the app and create its code yourself."
        )
        return None
    missing = [key for key in ("project_name", "project_slug", "package_identifier") if not isinstance(answers.get(key), str) or not answers[key]]
    if missing:
        conflicts.append(f"The workspace's {cli.COPIER_ANSWERS_FILE} does not record: {', '.join(missing)}.")
        return None
    # Scaffolding runs Copier with trust against this file, so it is held to the rule `prism update` applies.
    saved_problems = workspace_answers_problems(answers)
    if saved_problems:
        conflicts.extend(saved_problems)
        return None
    repo_state = cli.inspect_git_worktree(workspace)
    if not cli.is_direct_git_worktree(workspace, repo_state):
        conflicts.append("Scaffolding needs the workspace to be its own git repository, so the workspace layer can be updated against its last commit and the work stays on a branch.")
    elif repo_state["is_dirty"]:
        conflicts.append("Scaffolding needs a clean git working tree. Commit or stash your changes, then retry.")
    apps = [{"id": app.id, "stack": app.stack, "path": app.path, "generation": app.generation, "backend": app.backend} for app in model.apps]
    conflicts.extend(validate_scaffold(apps, only=[app_entry["id"]]))
    conflicts.extend(scaffold_collisions(workspace, app_entry))
    existing = [app for app in apps if app["id"] != app_entry["id"]]
    port = allocate_port(app_entry["stack"], taken_ports(workspace, existing))
    package = f"{answers['package_identifier']}.{app_entry['id'].replace('-', '')}"
    backend_port = backend_port_in_workspace(workspace, app_entry, apps) if app_entry["stack"] in BACKEND_CLIENT_STACKS else None
    plan = {
        "stack": app_entry["stack"],
        "path": app_entry["path"],
        "port": port,
        "backend_port": backend_port,
        "package": package,
        "template": src_path,
        "ref": answers.get("_commit"),
        # The apply compares this with the workspace's answers file as it reads it, so a file that changes in between is refused.
        "answers_digest": root.digest,
        "branch": f"prism-scaffold-{app_entry['id']}",
        "workflow": workflow_path(app_entry["id"]),
    }
    notes.append(
        f"Scaffolds `{app_entry['id']}` ({app_entry['stack']}) at `{app_entry['path']}`"
        + (f" on port {port}" if port else "")
        + f", package `{package}`, from {src_path} at {answers.get('_commit')}."
    )
    if backend_port is not None:
        notes.append(f"It calls the backend at `http://localhost:{backend_port}` (`backend_base_url` in its answers file).")
    notes.append(f"With --apply it works on the branch `{plan['branch']}`: one commit for the workspace layer, one for the app and the manifest.")
    return plan


def _with_scaffold_surfaces(data: dict[str, Any], app_entry: dict[str, Any]) -> dict[str, Any]:
    """The manifest with the maturity and the workflow of a scaffolded app, as `prism new` records them."""

    result = dict(data)
    maturity = dict(result["app_maturity"]) if isinstance(result.get("app_maturity"), dict) else {}
    maturity[app_entry["id"]] = stack_maturity(app_entry["stack"])
    result["app_maturity"] = maturity
    surfaces = dict(result["expected_surfaces"]) if isinstance(result.get("expected_surfaces"), dict) else {}
    workflows = list(surfaces["workflows"]) if isinstance(surfaces.get("workflows"), list) else []
    workflow = workflow_path(app_entry["id"])
    if workflow not in workflows:
        workflows.append(workflow)
    surfaces["workflows"] = workflows
    result["expected_surfaces"] = surfaces
    return result


def _with_repositories(data: dict[str, Any], repositories: list[Any]) -> dict[str, Any]:
    """The manifest with ``repositories`` set; a new key goes just before ``apps``, as the contract lists them."""

    if "repositories" in data:
        return {**data, "repositories": repositories}
    ordered: dict[str, Any] = {}
    for key, value in data.items():
        if key == "apps":
            ordered["repositories"] = repositories
        ordered[key] = value
    ordered.setdefault("repositories", repositories)
    return ordered


def _diagnostic_text(item: WorkspaceDiagnostic) -> str:
    return f"{item.code}: {item.message}"


def _check_repository_arguments(data: dict[str, Any], repository: str | None, remote: str | None, conflicts: list[str]) -> bool:
    """Record a problem with --repository and --remote; ``True`` when the repository is undeclared and has no remote."""

    declared_entries = data.get("repositories")
    declared = {entry.get("id") for entry in declared_entries or [] if isinstance(entry, dict)} if isinstance(declared_entries, list) else set()
    declared.add(WORKSPACE_REPOSITORY_ID)
    if remote is not None and repository is None:
        conflicts.append("--remote needs --repository: name the repository the remote belongs to.")
    elif remote is not None and repository in declared:
        conflicts.append(f"--remote is allowed only for a repository that is not declared yet; `{repository}` already is.")
    elif repository is not None and repository not in declared and remote is None:
        conflicts.append(f"Repository `{repository}` is not declared; add --remote URL to declare it with this app.")
        return True
    return False


def apply_app_add(root: Path, plan: dict[str, Any], *, trust_template: bool = False) -> dict[str, Any]:
    """Write a previewed plan after rechecking that the manifest is unchanged; a scaffolded app is generated first."""

    if plan.get("scaffold") and not plan.get("conflicts"):
        return _apply_scaffold(root, plan, trust_template=trust_template)
    return _apply_manifest_plan(root, plan, command="app add", subject="app")


def _apply_scaffold(root: Path, plan: dict[str, Any], *, trust_template: bool) -> dict[str, Any]:
    """Generate a scaffolded app on a branch, one commit per layer, and record it in the manifest."""

    from prism_cli import cli

    workspace = _validated_root(root)
    receipt: dict[str, Any] = {
        "schema_version": 1,
        "command": "app add",
        "root": str(workspace),
        "app": plan.get("app"),
        "repository": plan.get("repository"),
        "scaffold": plan.get("scaffold"),
        "board_identity_changed": plan.get("board_identity_changed", True),
        "notice": plan.get("notice", IDENTITY_NOTICE),
    }
    if plan.get("root") != str(workspace):
        raise ValueError("The app plan belongs to a different workspace root.")
    changes = plan.get("changes")
    if not isinstance(changes, list) or len(changes) != 1 or changes[0].get("path") != MANIFEST_FILE:
        raise ValueError("The app plan must change exactly the workspace manifest.")
    after = changes[0].get("after")
    if not isinstance(after, str):
        raise ValueError("The app plan has invalid manifest contents.")
    try:
        current = _read_path_bytes(workspace, MANIFEST_FILE, allow_missing=False)
        if _raw_digest(current) != plan.get("source_manifest_digest"):
            return {**receipt, "status": "conflict", "conflicts": [f"{MANIFEST_FILE} changed after preview; prepare a fresh plan."]}
    except (OSError, ValueError) as exc:
        return {**receipt, "status": "conflict", "conflicts": [f"Unable to read {MANIFEST_FILE}: {exc}"]}

    def write_manifest() -> None:
        target = _safe_target(workspace, MANIFEST_FILE)
        _atomic_write(workspace, MANIFEST_FILE, target, after.encode("utf-8"), current)

    outcome = cli.scaffold_app(workspace, plan["app"], plan["scaffold"], write_manifest=write_manifest, trust_template=trust_template)
    return {**receipt, **outcome}


def _apply_manifest_plan(root: Path, plan: dict[str, Any], *, command: str, subject: str) -> dict[str, Any]:
    """Write a previewed manifest plan after rechecking that the manifest is unchanged."""

    workspace = _validated_root(root)
    receipt: dict[str, Any] = {
        "schema_version": 1,
        "command": command,
        "root": str(workspace),
        "app": plan.get("app"),
        "repository": plan.get("repository"),
        "board_identity_changed": plan.get("board_identity_changed", True),
        "notice": plan.get("notice", IDENTITY_NOTICE),
    }
    if plan.get("root") != str(workspace):
        raise ValueError(f"The {subject} plan belongs to a different workspace root.")
    if plan.get("conflicts"):
        return {**receipt, "status": "conflict", "conflicts": list(plan["conflicts"])}
    changes = plan.get("changes")
    if not isinstance(changes, list) or len(changes) != 1 or changes[0].get("path") != MANIFEST_FILE:
        raise ValueError(f"The {subject} plan must change exactly the workspace manifest.")
    before = changes[0].get("before")
    after = changes[0].get("after")
    if not isinstance(before, str) or not isinstance(after, str):
        raise ValueError(f"The {subject} plan has invalid manifest contents.")
    try:
        current = _read_path_bytes(workspace, MANIFEST_FILE, allow_missing=False)
        if _raw_digest(current) != plan.get("source_manifest_digest"):
            return {**receipt, "status": "conflict", "conflicts": [f"{MANIFEST_FILE} changed after preview; prepare a fresh plan."]}
        target = _safe_target(workspace, MANIFEST_FILE)
        _atomic_write(workspace, MANIFEST_FILE, target, after.encode("utf-8"), current)
    except (OSError, ValueError) as exc:
        return {**receipt, "status": "conflict", "conflicts": [f"Unable to write {MANIFEST_FILE}: {exc}"]}
    return {**receipt, "status": "applied", "conflicts": []}


# --- prism app retire ---------------------------------------------------------


def plan_app_retire(root: Path, app_id: str) -> dict[str, Any]:
    """The exact manifest change that retires one app. Nothing is written.

    Retiring sets ``status: retired`` on the app's manifest entry and nothing
    else: no code, page, requirement or evidence is touched. The plan lists
    ``flagged_features``, the features in progress that still list the app and
    will be flagged ``app-retired-in-scope`` until their scope is edited, and
    ``conflicts`` (error findings; the plan cannot be applied).
    """

    workspace = _validated_root(root)
    conflicts: list[str] = []
    warnings: list[str] = []
    changes: list[dict[str, str | None]] = []
    flagged: list[dict[str, str]] = []
    app_entry: dict[str, Any] | None = None
    manifest_bytes: bytes | None = None
    try:
        manifest_bytes = _read_path_bytes(workspace, MANIFEST_FILE, allow_missing=True)
        if manifest_bytes is None:
            raise ValueError(f"{MANIFEST_FILE} is missing; install the workflow or generate a workspace first.")
        data, bom = _parse_manifest(manifest_bytes)
        before = manifest_bytes.decode("utf-8-sig")
        apps = data.get("apps")
        if not isinstance(apps, list):
            conflicts.append(f"{MANIFEST_FILE} `apps` must be a list before an app can be retired.")
        else:
            index = next((position for position, item in enumerate(apps) if isinstance(item, dict) and item.get("id") == app_id), None)
            if index is None:
                declared = ", ".join(f"`{item['id']}`" for item in apps if isinstance(item, dict) and isinstance(item.get("id"), str)) or "none"
                conflicts.append(f"`{app_id}` is not an app of this workspace; the workspace's apps are {declared}.")
            elif apps[index].get("status", "active") == "retired":
                conflicts.append(f"App `{app_id}` is already retired.")
            else:
                new_data = {**data, "apps": [*apps[:index], {**apps[index], "status": "retired"}, *apps[index + 1 :]]}
                model, diagnostics = normalize_manifest(new_data, path=Path(MANIFEST_FILE))
                errors = [item for item in diagnostics if item.severity == "error"]
                conflicts.extend(_diagnostic_text(item) for item in errors)
                if not errors:
                    app_entry = next((entry for entry in app_entries(model) if entry["id"] == app_id), None)
                    flagged = _features_in_progress_with_app(workspace, app_id)
                    after = yaml.safe_dump(new_data, sort_keys=False, allow_unicode=True)
                    if bom:
                        after = "\ufeff" + after
                    changes.append({"path": MANIFEST_FILE, "before": before, "after": after})
    except (OSError, UnicodeError, ValueError, yaml.YAMLError) as exc:
        conflicts.append(f"Unable to safely inspect this workspace: {exc}")
        changes = []
    return {
        "schema_version": 1,
        "command": "app retire",
        "root": str(workspace),
        "app": app_entry,
        "repository": None,
        "changes": changes,
        "flagged_features": flagged,
        "conflicts": list(dict.fromkeys(conflicts)),
        "warnings": list(dict.fromkeys(warnings)),
        "board_identity_changed": True,
        "notice": IDENTITY_NOTICE,
        "source_manifest_digest": _raw_digest(manifest_bytes),
    }


def _features_in_progress_with_app(workspace: Path, app_id: str) -> list[dict[str, str]]:
    """The features before done whose scope lists ``app_id``; a wiki that cannot be read lists none."""

    try:
        features = read_feature_pages(workspace / "knowledge" / "wiki")
    except (OSError, ValueError):
        return []
    return [
        {"id": feature.feature_id, "status": feature.status or "unknown"}
        for feature in features
        if app_id in feature.apps and feature.status != "done"
    ]


def apply_app_retire(root: Path, plan: dict[str, Any]) -> dict[str, Any]:
    """Write a previewed retirement after rechecking that the manifest is unchanged."""

    return _apply_manifest_plan(root, plan, command="app retire", subject="retirement")


def _capabilities_from_args(args: argparse.Namespace) -> dict[str, bool | str]:
    values: dict[str, bool | str] = {}
    for key, raw in ((CAPABILITY_HAS_UI, args.has_ui), (CAPABILITY_SERVES_API, args.serves_api)):
        if raw is not None:
            values[key] = UNKNOWN if raw == UNKNOWN else raw == "true"
    return values


def cmd_app_add(args: argparse.Namespace) -> int:
    root = Path(args.path).expanduser()
    try:
        plan = plan_app_add(
            root,
            args.id,
            args.stack,
            name=args.name,
            repository=args.repository,
            remote=args.remote,
            path=args.app_path,
            audience=args.audience,
            capabilities=_capabilities_from_args(args),
            scaffold=args.scaffold,
            backend=args.backend,
        )
    except (OSError, ValueError) as exc:
        _text(f"App registration failed: {exc}", file=sys.stderr)
        return 3
    trust = getattr(args, "trust_template", False)
    return _run_manifest_plan(
        args,
        root,
        plan,
        apply=lambda workspace, applied_plan: apply_app_add(workspace, applied_plan, trust_template=trust),
        label="Prism app add",
        failure="App registration failed",
        applied=(
            f"Scaffolded app `{args.id}` and registered it in {MANIFEST_FILE}."
            if args.scaffold
            else f"Registered app `{args.id}` in {MANIFEST_FILE}."
        ),
    )


def cmd_app_retire(args: argparse.Namespace) -> int:
    root = Path(args.path).expanduser()
    try:
        plan = plan_app_retire(root, args.id)
    except (OSError, ValueError) as exc:
        _text(f"App retirement failed: {exc}", file=sys.stderr)
        return 3
    return _run_manifest_plan(
        args,
        root,
        plan,
        apply=apply_app_retire,
        label="Prism app retire",
        failure="App retirement failed",
        applied=f"Retired app `{args.id}` in {MANIFEST_FILE}. No code, page, requirement or evidence was deleted.",
    )


def _run_manifest_plan(
    args: argparse.Namespace,
    root: Path,
    plan: dict[str, Any],
    *,
    apply,
    label: str,
    failure: str,
    applied: str,
) -> int:
    """Show a manifest plan, and with ``--apply`` write it after confirmation."""

    try:
        if args.json:
            if not args.apply:
                _json(plan)
        else:
            _text(f"{label}: {root}")
            for change in plan["changes"]:
                before, after = change.get("before") or "", change.get("after") or ""
                _text(
                    "".join(
                        difflib.unified_diff(
                            before.splitlines(keepends=True),
                            after.splitlines(keepends=True),
                            fromfile=change["path"],
                            tofile=change["path"],
                        )
                    ),
                    end="",
                )
            for conflict in plan["conflicts"]:
                _text(f"Error: {conflict}", file=sys.stderr)
            for warning in plan["warnings"]:
                _text(f"Warning: {warning}")
            for note in plan.get("notes", []):
                _text(f"Note: {note}")
            if not plan["conflicts"]:
                for feature in plan.get("flagged_features", []):
                    _text(
                        f"Warning: feature {feature['id']} ({feature['status']}) lists this app and is flagged app-retired-in-scope until its `apps` is edited. "
                        "Retirement never changes a feature's scope by itself."
                    )
                _text(IDENTITY_NOTICE)
        if plan["conflicts"]:
            if args.json and args.apply:
                _json(plan)
            return 3
        if not args.apply:
            if not args.json:
                print("Preview only. Run again with --apply to confirm this change.")
            return 0
        if not args.yes:
            if args.json or not sys.stdin.isatty():
                print("Applying non-interactively requires --apply --yes after reviewing the preview.", file=sys.stderr)
                return 2
            try:
                answer = input("Apply exactly this manifest change? [y/N] ")
            except EOFError:
                answer = ""
            if answer.strip().lower() not in ("y", "yes"):
                print("Canceled; no files changed.")
                return 0
        receipt = apply(root, plan)
        if args.json:
            _json({**receipt, "plan": plan})
        elif receipt["status"] == "applied":
            _text(applied)
            if receipt.get("branch"):
                _text(f"The work is on branch `{receipt['branch']}`, one commit per layer. Review it, then merge it.")
            _text(IDENTITY_NOTICE)
        else:
            for conflict in receipt["conflicts"]:
                _text(f"Error: {conflict}", file=sys.stderr)
        return 0 if receipt["status"] == "applied" else 3
    except (OSError, ValueError) as exc:
        _text(f"{failure}: {exc}", file=sys.stderr)
        return 3
