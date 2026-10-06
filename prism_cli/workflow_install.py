"""Preview-first adoption of the packaged, non-application Prism workflow."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import tempfile
from typing import Any
from uuid import UUID, uuid4

import yaml

from prism_cli.app_model import (
    GENERATED_PLATFORM_DIRS,
    LOCAL_OVERRIDE_FILE,
    MANIFEST_SCHEMA_VERSION,
    PURPOSE_KNOWLEDGE_ROOT,
    apps_from_platforms,
    normalize_manifest,
)
from prism_cli.workspace import MANIFEST_FILE
from prism_cli.workflow_assets import asset_digest, bootstrap_files, guidance_pointer, previous_digests
from prism_cli.board_store import BoardLockError, unresolved_board_operations, workspace_process_lock
from prism_cli.fs_safety import CLOUD_SYNC_MESSAGE, reparse_kind


WORKFLOW_VERSION = "1"
_IGNORE_MARKER = "# Prism local workflow state"
_IGNORE_RULE = ".prism/state/"
_LOCAL_IGNORE_MARKER = "# Prism per-machine repository checkouts"
_LOCAL_IGNORE_RULE = LOCAL_OVERRIDE_FILE
_ATTRIBUTES_MARKER = "# Prism workflow files keep LF line endings"
_ATTRIBUTES_RULE = "knowledge/** text eol=lf"


def plan_install(
    root: Path,
    name: str | None = None,
    apps: list[str] | None = None,
    upgrade: bool = False,
    knowledge_root: bool = False,
) -> dict[str, Any]:
    """Build an exact, non-mutating file plan for installing or upgrading.

    ``apps`` names the generated app IDs (the ``--app`` values) to register
    in a manifest that declares no apps. A new workspace without them has no apps.
    ``knowledge_root`` starts a workflow-only workspace that records
    ``workflow.purpose: knowledge-root``; it has no apps of its own, so it
    cannot be combined with ``apps``.
    """

    workspace = _validated_root(root)
    selected_apps = _validate_requested_apps(apps)
    if type(knowledge_root) is not bool:
        raise ValueError("knowledge_root must be true or false.")
    if knowledge_root and selected_apps is not None:
        raise ValueError(
            "`--knowledge-root` cannot be combined with `--app`: a knowledge root has no apps of its own; register the apps of other repositories with `prism app add`."
        )
    if name is not None:
        _validate_name(name)
    if type(upgrade) is not bool:
        raise ValueError("upgrade must be true or false.")

    digest = asset_digest(WORKFLOW_VERSION)
    conflicts: list[str] = []
    unchanged: list[str] = []
    preserved: list[str] = []
    updated: list[str] = []
    optional_steps: list[str] = []
    changes: list[dict[str, str | None]] = []
    manifest_bytes: bytes | None = None
    try:
        manifest_bytes = _read_path_bytes(workspace, MANIFEST_FILE, allow_missing=True)
        before_manifest = manifest_bytes.decode("utf-8") if manifest_bytes is not None else None
        manifest_data, bom = _parse_manifest(manifest_bytes)
        _validate_workspace_binding(manifest_data, conflicts)
        project_value = _mutable_mapping(manifest_data, "project", MANIFEST_FILE)
        project = project_value if project_value is not None else {}
        old_workflow = _mutable_mapping(manifest_data, "workflow", MANIFEST_FILE)
        was_workflow_pinned = old_workflow is not None
        runtime_state_dir = workspace / ".prism" / "state"
        _check_path_components(workspace, runtime_state_dir)
        runtime_state_present = runtime_state_dir.exists()
        if runtime_state_present and not runtime_state_dir.is_dir():
            raise ValueError("Prism runtime state path must be a directory before workflow adoption.")
        runtime_lock_path = runtime_state_dir / "board.lock"
        _check_path_components(workspace, runtime_lock_path)
        runtime_lock_present = runtime_lock_path.exists()
        if runtime_lock_present and not runtime_lock_path.is_file():
            raise ValueError("Prism runtime lock path must be a regular file before workflow adoption.")

        generated_by = manifest_data.get("generated_by")
        if generated_by is not None and not isinstance(generated_by, dict):
            raise ValueError(f"{MANIFEST_FILE} generated_by must be a mapping before workflow adoption.")
        is_generated = isinstance(generated_by, dict)
        if isinstance(old_workflow, dict) and old_workflow.get("mode") == "generated":
            is_generated = True
        workflow_current = _workflow_is_current(old_workflow, digest)
        if old_workflow is not None and not upgrade and not workflow_current:
            conflicts.append(
                "This workspace has an older or non-canonical Prism workflow; use `prism workflow upgrade` to review and update it."
            )
        elif is_generated and not upgrade and not workflow_current:
            conflicts.append(
                "This generated workspace needs an explicit `prism workflow upgrade` before connected writes are enabled."
            )
        if upgrade and old_workflow is None and not is_generated:
            conflicts.append("There is no existing Prism or generated workflow to upgrade; use `prism workflow install`.")

        if before_manifest is not None and (
            type(manifest_data.get("schema_version")) is not int
            or manifest_data.get("schema_version") != MANIFEST_SCHEMA_VERSION
        ):
            raise ValueError(
                f"{MANIFEST_FILE} must use schema_version {MANIFEST_SCHEMA_VERSION} before workflow adoption; recreate or reinstall this workspace with this CLI."
            )
        # The manifest declares its own apps; the workflow only pins itself.
        model, model_diagnostics = normalize_manifest(manifest_data, path=Path(MANIFEST_FILE)) if before_manifest is not None else (None, [])
        scope_declared = "apps" in manifest_data

        old_version, board_id = _workflow_identity(old_workflow, upgrade=upgrade, conflicts=conflicts)
        if old_version and old_version != WORKFLOW_VERSION and not upgrade:
            conflicts.append(f"This workspace pins workflow version {old_version}; use `prism workflow upgrade` to change it.")
        if old_version and _is_future_version(old_version):
            conflicts.append(f"This workspace uses newer workflow version {old_version}; this CLI will not downgrade it.")
        if old_workflow is not None and old_workflow.get("asset_digest") not in (None, digest) and not upgrade:
            conflicts.append("The pinned workflow guidance differs from this CLI; review `prism workflow upgrade` before connected writes.")
        if old_workflow is not None and old_workflow.get("asset_digest") is None and old_version == WORKFLOW_VERSION and not upgrade:
            conflicts.append("This workflow has no canonical asset digest; use `prism workflow upgrade` to pin its guidance.")

        chosen_name = _choose_name(workspace, project, name, conflicts)
        problem_codes = sorted({item.code for item in model_diagnostics if item.severity == "error"})
        if problem_codes:
            conflicts.append(
                f"{MANIFEST_FILE} has invalid repository, app or workflow declarations ({', '.join(problem_codes)}); fix them before adopting or upgrading the workflow."
            )
        if scope_declared and model is not None:
            chosen_apps = model.active_app_ids
            # Naming the apps the workspace already has is harmless; naming others would change them.
            if selected_apps is not None and set(selected_apps) != set(chosen_apps):
                conflicts.append(f"`--app` cannot change the apps of this workspace; register another app with `prism app add` or edit `apps` in {MANIFEST_FILE}.")
        else:
            chosen_apps = selected_apps or []
        mode = "generated" if is_generated else "workflow"
        purpose = _choose_purpose(old_workflow, knowledge_root, is_generated, before_manifest is not None, conflicts)

        if not conflicts:
            if before_manifest is None:
                manifest_data["schema_version"] = MANIFEST_SCHEMA_VERSION
                manifest_data.setdefault("min_prism_cli_version", "0.3.0")
            project["name"] = chosen_name
            manifest_data["project"] = project
            if not scope_declared:
                # The chosen generated apps are registered with their ID, stack and default directory.
                manifest_data["apps"] = apps_from_platforms(chosen_apps)
            if old_workflow is None:
                old_workflow = {}
            old_workflow.update(
                {
                    "version": WORKFLOW_VERSION,
                    "mode": mode,
                    **({"purpose": purpose} if purpose is not None else {}),
                    "board_id": board_id,
                    "asset_digest": digest,
                }
            )
            manifest_data["workflow"] = old_workflow
            if "paths" not in manifest_data:
                manifest_data["paths"] = {
                    "wiki_root": "knowledge/wiki",
                    "intake_root": "knowledge/intake",
                    "advisory_board": "knowledge/wiki/advisory/BOARD.md",
                }

            if before_manifest is None or manifest_data != _parse_manifest_data(manifest_bytes):
                after_manifest = yaml.safe_dump(
                    manifest_data,
                    sort_keys=False,
                    allow_unicode=True,
                )
                if bom:
                    after_manifest = "\ufeff" + after_manifest
                if before_manifest != after_manifest:
                    changes.append({"path": MANIFEST_FILE, "before": before_manifest, "after": after_manifest})
            else:
                unchanged.append(MANIFEST_FILE)
        else:
            chosen_name = chosen_name or (project.get("name") if isinstance(project.get("name"), str) else None)
            chosen_apps = chosen_apps or []

        for bootstrap in bootstrap_files(WORKFLOW_VERSION):
            relative = bootstrap["path"]
            source_content = bootstrap["content"]
            existing = _read_path_bytes(workspace, relative, allow_missing=True)
            if existing is None:
                _check_missing_parent_chain(workspace, relative)
                changes.append({"path": relative, "before": None, "after": source_content})
            elif _lf(existing) == _lf(source_content.encode("utf-8")):
                # A Git checkout with core.autocrlf rewrites line endings; the text is still Prism's own.
                unchanged.append(relative)
            elif _is_earlier_shipped_copy(relative, existing):
                # An untouched copy of an earlier canonical version is Prism's own
                # text, so it is replaced without asking. Writes stay LF.
                changes.append({"path": relative, "before": existing.decode("utf-8"), "after": source_content})
                updated.append(relative)
            elif relative == "knowledge/wiki/CONNECTED.md":
                conflicts.append(
                    "knowledge/wiki/CONNECTED.md is present with different contents; preserve or reconcile it explicitly before installing the Prism-owned binding."
                )
            else:
                preserved.append(relative)

        _plan_guidance_pointer(workspace, "AGENTS.md", purpose, changes, preserved, updated, optional_steps, conflicts)
        _plan_guidance_pointer(workspace, "CLAUDE.md", purpose, changes, preserved, updated, optional_steps, conflicts)
        _plan_gitignore(workspace, changes, unchanged, conflicts)
        _plan_gitattributes(workspace, changes, unchanged, conflicts)

        # Keep the workflow manifest last so a partially applied scaffold never
        # advertises a connected workspace before its canonical binding exists.
        changes.sort(key=lambda item: (item["path"] == MANIFEST_FILE, str(item["path"])))
        missing_directories = _missing_parent_directories(workspace, changes)
        plan: dict[str, Any] = {
            "plan_id": str(uuid4()),
            "root": str(workspace),
            "version": WORKFLOW_VERSION,
            "mode": mode,
            "purpose": purpose,
            "asset_digest": digest,
            "board_id": board_id,
            "name": chosen_name,
            "apps": chosen_apps,
            "upgrade": upgrade,
            "changes": changes,
            "conflicts": _unique(conflicts),
            "unchanged": _unique(unchanged),
            "preserved": _unique(preserved),
            "updated": _unique(updated),
            "optional_steps": optional_steps,
            "directories": missing_directories,
            "source_manifest_digest": _raw_digest(manifest_bytes),
            "runtime_lock": {
                "path": ".prism/state/board.lock",
                "required": runtime_state_present or (was_workflow_pinned and (upgrade or bool(changes))),
                "creates": not runtime_lock_present and (runtime_state_present or (was_workflow_pinned and (upgrade or bool(changes)))),
            },
        }
        plan["digest"] = _plan_digest(plan)
        return plan
    except (OSError, UnicodeError, ValueError, yaml.YAMLError) as exc:
        conflicts.append(f"Unable to safely inspect this workspace: {exc}")
        plan = {
            "plan_id": str(uuid4()),
            "root": str(workspace),
            "version": WORKFLOW_VERSION,
            "mode": "workflow",
            "purpose": PURPOSE_KNOWLEDGE_ROOT if knowledge_root else None,
            "asset_digest": digest,
            "board_id": None,
            "name": name,
            "apps": selected_apps or [],
            "upgrade": upgrade,
            "changes": [],
            "conflicts": _unique(conflicts),
            "unchanged": [],
            "preserved": [],
            "updated": [],
            "optional_steps": optional_steps,
            "directories": [],
            "source_manifest_digest": _raw_digest(manifest_bytes),
            "runtime_lock": {"path": ".prism/state/board.lock", "required": False, "creates": False},
        }
        plan["digest"] = _plan_digest(plan)
        return plan


def apply_install(root: Path, plan: dict[str, Any]) -> dict[str, Any]:
    """Apply one reviewed plan without replacing changed or unrelated files."""

    workspace = _validated_root(root)
    if not isinstance(plan, dict):
        raise ValueError("The workflow installation plan must be a mapping.")
    if plan.get("root") != str(workspace):
        raise ValueError("The workflow installation plan belongs to a different workspace root.")
    if plan.get("version") != WORKFLOW_VERSION or plan.get("asset_digest") != asset_digest(WORKFLOW_VERSION):
        raise ValueError("The workflow installation plan does not match this CLI's packaged workflow asset.")
    if plan.get("digest") != _plan_digest(plan):
        raise ValueError("The workflow installation plan was changed after preview; prepare a fresh plan.")
    if plan.get("conflicts"):
        return _receipt(plan, status="conflict", conflicts=list(plan["conflicts"]))
    if type(plan.get("upgrade")) is not bool:
        raise ValueError("The workflow installation plan has an invalid upgrade marker.")
    changes = plan.get("changes")
    if not isinstance(changes, list):
        raise ValueError("The workflow installation plan has no valid change list.")

    # Inspect the current identity only to decide whether a lock-only state
    # directory must be created. Its bytes are checked again after acquiring
    # that lock, so a stale plan cannot write based on this preliminary read.
    try:
        current_manifest = _read_path_bytes(workspace, MANIFEST_FILE, allow_missing=True)
        current_data, _ = _parse_manifest(current_manifest)
        current_workflow = current_data.get("workflow")
        if current_workflow is not None and not isinstance(current_workflow, dict):
            raise ValueError(f"{MANIFEST_FILE} workflow must be a mapping before applying an installation plan.")
        create_lock = current_workflow is not None and (plan["upgrade"] or bool(changes))
    except (OSError, UnicodeError, ValueError, yaml.YAMLError) as exc:
        return _receipt(plan, status="conflict", conflicts=[f"Unable to safely inspect the current workflow identity: {exc}"])

    try:
        with workspace_process_lock(workspace, create=create_lock):
            current_manifest = _read_path_bytes(workspace, MANIFEST_FILE, allow_missing=True)
            if _raw_digest(current_manifest) != plan.get("source_manifest_digest"):
                return _receipt(
                    plan,
                    status="conflict",
                    conflicts=[f"{MANIFEST_FILE} changed after preview; prepare a fresh workflow plan."],
                )
            if plan["upgrade"]:
                try:
                    unresolved = unresolved_board_operations(workspace)
                except (OSError, ValueError) as exc:
                    return _receipt(plan, status="conflict", conflicts=[str(exc)])
                if unresolved:
                    descriptions = ", ".join(f"{operation_id} ({state})" for operation_id, state in unresolved[:8])
                    remainder = len(unresolved) - 8
                    if remainder > 0:
                        descriptions += f", and {remainder} more"
                    return _receipt(
                        plan,
                        status="conflict",
                        conflicts=[
                            "Workflow upgrade is blocked while unfinished board operations remain: "
                            f"{descriptions}. Recover, complete or abandon these operations, then preview the upgrade again."
                        ],
                    )
            return _apply_change_set(workspace, plan, changes)
    except BoardLockError as exc:
        return _receipt(plan, status="conflict", conflicts=[str(exc)])
    except (OSError, UnicodeError, ValueError, yaml.YAMLError) as exc:
        return _receipt(plan, status="conflict", conflicts=[f"Unable to safely apply the workflow plan: {exc}"])


def _apply_change_set(workspace: Path, plan: dict[str, Any], changes: list[Any]) -> dict[str, Any]:
    validated_changes: list[tuple[str, Path, bytes | None, bytes]] = []
    conflicts: list[str] = []
    seen: set[str] = set()
    for change in changes:
        if not isinstance(change, dict):
            conflicts.append("The workflow plan contains an invalid file change.")
            continue
        relative = change.get("path")
        before = change.get("before")
        after = change.get("after")
        try:
            target = _safe_target(workspace, relative)
        except ValueError as exc:
            conflicts.append(str(exc))
            continue
        if relative in seen:
            conflicts.append(f"The workflow plan lists {relative} more than once.")
            continue
        seen.add(relative)
        if (before is not None and not isinstance(before, str)) or not isinstance(after, str):
            conflicts.append(f"The workflow plan has invalid text contents for {relative}.")
            continue
        try:
            current = _read_path_bytes(workspace, relative, allow_missing=True)
        except (OSError, ValueError) as exc:
            conflicts.append(f"Unable to recheck {relative}: {exc}")
            continue
        before_bytes = before.encode("utf-8") if before is not None else None
        after_bytes = after.encode("utf-8")
        if current not in (before_bytes, after_bytes):
            conflicts.append(f"{relative} changed after preview; its current contents were preserved.")
            continue
        validated_changes.append((relative, target, before_bytes, after_bytes))

    if conflicts:
        return _receipt(plan, status="conflict", conflicts=_unique(conflicts))

    applied: list[str] = []
    already_applied: list[str] = []
    created_directories: list[str] = []
    for relative, target, before_bytes, after_bytes in validated_changes:
        try:
            _check_missing_parent_chain(workspace, relative)
            current = _read_path_bytes(workspace, relative, allow_missing=True)
            if current == after_bytes:
                already_applied.append(relative)
                continue
            if current != before_bytes:
                return _receipt(
                    plan,
                    status="partial" if applied else "conflict",
                    applied=applied,
                    already_applied=already_applied,
                    remaining=[item[0] for item in validated_changes if item[0] not in applied and item[0] not in already_applied],
                    conflicts=[f"{relative} changed immediately before replacement; its contents were preserved."],
                    created_directories=created_directories,
                )
            created_directories.extend(_ensure_parent_directories(workspace, target.parent))
            _atomic_write(workspace, relative, target, after_bytes, before_bytes)
            applied.append(relative)
        except (OSError, ValueError) as exc:
            return _receipt(
                plan,
                status="partial" if applied else "conflict",
                applied=applied,
                already_applied=already_applied,
                remaining=[item[0] for item in validated_changes if item[0] not in applied and item[0] not in already_applied],
                conflicts=[f"Unable to apply {relative}: {exc}"],
                created_directories=created_directories,
            )

    status = "applied" if applied else "unchanged"
    return _receipt(
        plan,
        status=status,
        applied=applied,
        already_applied=already_applied,
        remaining=[],
        conflicts=[],
        created_directories=created_directories,
    )


def _raw_digest(raw: bytes | None) -> str | None:
    return hashlib.sha256(raw).hexdigest() if raw is not None else None


def _validated_root(root: Path) -> Path:
    supplied = Path(root).expanduser()
    if ".." in supplied.parts:
        raise ValueError("The workflow workspace path cannot contain parent-directory traversal.")
    candidate = supplied.absolute()
    # Inspect the supplied path component-by-component before resolve() can
    # erase evidence that it crossed a symlink, junction, or reparse point.
    for current in reversed((candidate, *candidate.parents)):
        try:
            mode = current.lstat().st_mode
        except OSError as exc:
            if current == candidate:
                raise ValueError(f"Workflow workspace directory is unavailable: {exc}") from exc
            raise ValueError(f"Workflow workspace path contains an unavailable component: {current}") from exc
        if _is_link_or_reparse(current, mode):
            _raise_if_cloud(current)
            raise ValueError("The workflow workspace path cannot cross a symlink, junction, or reparse point.")
    mode = candidate.lstat().st_mode
    if not stat.S_ISDIR(mode):
        raise ValueError("The workflow workspace path must be an existing directory.")
    workspace = candidate.resolve(strict=True)
    if (workspace / "copier.yml").exists() and (workspace / "template").exists():
        raise ValueError("Prism workflow adoption cannot target the Prism template repository.")
    return workspace


def _is_link_or_reparse(path: Path, mode: int | None = None) -> bool:
    if mode is None:
        try:
            mode = path.lstat().st_mode
        except OSError:
            return False
    if stat.S_ISLNK(mode):
        return True
    is_junction = getattr(path, "is_junction", None)
    if callable(is_junction) and is_junction():
        return True
    try:
        return reparse_kind(path.lstat()) != "none"
    except OSError:
        return False


def _raise_if_cloud(path: Path) -> None:
    """Explain cloud-synced paths; call only where a reparse point is already being rejected."""

    try:
        info = path.lstat()
    except OSError:
        return
    if reparse_kind(info) == "cloud":
        raise ValueError(CLOUD_SYNC_MESSAGE)


def _safe_target(root: Path, relative: Any) -> Path:
    if not isinstance(relative, str) or not relative or "\\" in relative or "\x00" in relative or ":" in relative:
        raise ValueError("Workflow plan paths must be non-empty relative POSIX paths.")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or pure.as_posix() != relative or any(part in ("", ".", "..") for part in pure.parts):
        raise ValueError(f"Unsafe workflow plan path: {relative!r}.")
    target = root.joinpath(*pure.parts)
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Workflow plan path escapes the workspace: {relative!r}.") from exc
    _check_path_components(root, target)
    return target


def _check_path_components(root: Path, target: Path) -> None:
    relative = target.relative_to(root)
    current = root
    for part in relative.parts:
        current = current / part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise ValueError(f"Unable to inspect workflow path {current.relative_to(root).as_posix()}: {exc}") from exc
        if _is_link_or_reparse(current, mode):
            _raise_if_cloud(current)
            raise ValueError(f"Workflow path {current.relative_to(root).as_posix()} crosses a symlink, junction, or reparse point.")


def _check_missing_parent_chain(root: Path, relative: str) -> None:
    target = _safe_target(root, relative)
    _check_path_components(root, target.parent)
    if target.exists() and target.is_dir():
        raise ValueError(f"A directory already exists where workflow file {relative} should be created.")


def _read_path_bytes(
    root: Path,
    relative: str,
    *,
    allow_missing: bool,
) -> bytes | None:
    target = _safe_target(root, relative)
    if not target.exists() and not target.is_symlink():
        if allow_missing:
            return None
        raise FileNotFoundError(target)
    if _is_link_or_reparse(target):
        _raise_if_cloud(target)
        raise ValueError(f"Workflow file {relative} is a symlink, junction, or reparse point.")
    if not target.is_file():
        raise ValueError(f"Workflow file {relative} is not a regular file.")
    return target.read_bytes()


def _parse_manifest(raw: bytes | None) -> tuple[dict[str, Any], bool]:
    if raw is None:
        return {}, False
    text = raw.decode("utf-8-sig")
    value = yaml.safe_load(text)
    if value is None:
        return {}, raw.startswith(b"\xef\xbb\xbf")
    if not isinstance(value, dict):
        raise ValueError(f"{MANIFEST_FILE} must contain a YAML mapping.")
    return value, raw.startswith(b"\xef\xbb\xbf")


def _parse_manifest_data(raw: bytes | None) -> dict[str, Any]:
    return _parse_manifest(raw)[0]


def _validate_workspace_binding(manifest: dict[str, Any], conflicts: list[str]) -> None:
    paths = manifest.get("paths")
    if paths is not None:
        if not isinstance(paths, dict) or any(
            not isinstance(key, str) or not isinstance(value, str) for key, value in paths.items()
        ):
            conflicts.append(f"{MANIFEST_FILE} paths must map string names to string paths; preserve and repair the declaration before adoption.")
        else:
            expected = {
                "wiki_root": "knowledge/wiki",
                "intake_root": "knowledge/intake",
                "advisory_board": "knowledge/wiki/advisory/BOARD.md",
            }
            for key, canonical in expected.items():
                if key in paths and paths[key] != canonical:
                    conflicts.append(
                        f"{MANIFEST_FILE} paths.{key} must be {canonical!r} for the connected workflow; preserve and reconcile the custom path explicitly."
                    )

    surfaces = manifest.get("expected_surfaces")
    if surfaces is not None and (
        not isinstance(surfaces, dict)
        or any(
            not isinstance(key, str)
            or not isinstance(value, list)
            or any(not isinstance(item, str) for item in value)
            for key, value in surfaces.items()
        )
    ):
        conflicts.append(
            f"{MANIFEST_FILE} expected_surfaces must map names to lists of string paths; preserve and repair the declaration before adoption."
        )


def _mutable_mapping(data: dict[str, Any], key: str, source: str) -> dict[str, Any] | None:
    if key not in data:
        return None
    value = data[key]
    if not isinstance(value, dict):
        raise ValueError(f"{source} {key} must be a mapping before workflow adoption.")
    return value


def _validate_requested_apps(apps: list[str] | None) -> list[str] | None:
    if apps is None:
        return None
    if not isinstance(apps, list) or not apps:
        raise ValueError("Select at least one app with --app, or leave it out to create a workspace with no apps.")
    if any(not isinstance(item, str) for item in apps):
        raise ValueError("The apps must be a list of generated app IDs.")
    if len(set(apps)) != len(apps):
        raise ValueError("The apps cannot contain duplicate IDs.")
    invalid = sorted(set(apps) - set(GENERATED_PLATFORM_DIRS))
    if invalid:
        raise ValueError(f"Unsupported app IDs: {', '.join(invalid)}. Choose from {', '.join(GENERATED_PLATFORM_DIRS)}.")
    return [app_id for app_id in GENERATED_PLATFORM_DIRS if app_id in apps]


def _validate_name(name: str) -> None:
    if not isinstance(name, str) or not name.strip() or "\n" in name or "\r" in name:
        raise ValueError("Workspace name must be a non-empty single-line string.")


def _choose_name(
    root: Path,
    project: dict[str, Any],
    requested: str | None,
    conflicts: list[str],
) -> str | None:
    old = project.get("name")
    if requested is not None:
        return requested.strip()
    if isinstance(old, str) and old.strip():
        return old
    substantive_entries = [item for item in root.iterdir() if item.name.lower() != ".git"]
    if not substantive_entries:
        conflicts.append("A new empty workspace needs a display name; provide --name NAME.")
        return None
    if old is not None:
        conflicts.append("The existing project name is not a non-empty string; provide --name NAME to repair it.")
        return None
    return root.name or None


def _choose_purpose(
    old_workflow: dict[str, Any] | None,
    knowledge_root: bool,
    is_generated: bool,
    manifest_exists: bool,
    conflicts: list[str],
) -> str | None:
    """The workspace purpose to record: a knowledge root when requested or already recorded, else none.

    A knowledge root starts a workspace. An existing manifest keeps its purpose
    and is never turned into a knowledge root, and a generated workspace never is one.
    """

    existing = old_workflow.get("purpose") if isinstance(old_workflow, dict) else None
    if existing is not None and existing != PURPOSE_KNOWLEDGE_ROOT:
        return None  # The normalizer reports the invalid value as an error, so the plan is already in conflict.
    if not knowledge_root:
        return existing
    if is_generated:
        conflicts.append("`--knowledge-root` cannot apply to a generated workspace, which holds application code.")
    elif manifest_exists and existing != PURPOSE_KNOWLEDGE_ROOT:
        conflicts.append(
            f"`--knowledge-root` starts a new workspace; {MANIFEST_FILE} already exists and is not a knowledge root. Use an empty folder or a repository without {MANIFEST_FILE}."
        )
    return PURPOSE_KNOWLEDGE_ROOT


def _workflow_identity(
    workflow: dict[str, Any] | None,
    *,
    upgrade: bool,
    conflicts: list[str],
) -> tuple[str | None, str | None]:
    if workflow is None:
        return None, str(uuid4())
    version = workflow.get("version")
    if version is not None and not isinstance(version, str):
        conflicts.append("Existing workflow version must be a string.")
        version = None
    board_id = workflow.get("board_id")
    if board_id is not None:
        if not isinstance(board_id, str):
            conflicts.append("Existing workflow board_id is not a valid UUID; preserve its identity and repair it explicitly.")
            return version, None
        try:
            UUID(board_id)
        except (ValueError, TypeError, AttributeError):
            conflicts.append("Existing workflow board_id is not a valid UUID; preserve its identity and repair it explicitly.")
            return version, None
    elif version is not None and version == WORKFLOW_VERSION and not upgrade:
        conflicts.append("Existing workflow is missing its board identity; use an explicit workflow repair/upgrade review.")
        board_id = None
    else:
        board_id = str(uuid4())
    return version, board_id


def _workflow_is_current(workflow: dict[str, Any] | None, digest: str) -> bool:
    if not isinstance(workflow, dict):
        return False
    if (
        type(workflow.get("version")) is not str
        or workflow.get("version") != WORKFLOW_VERSION
        or workflow.get("asset_digest") != digest
        or workflow.get("mode") not in ("workflow", "generated")
        or not isinstance(workflow.get("board_id"), str)
    ):
        return False
    try:
        UUID(workflow["board_id"])
    except (ValueError, TypeError, AttributeError):
        return False
    return True


def _is_future_version(version: str) -> bool:
    try:
        return int(version.split(".", 1)[0]) > int(WORKFLOW_VERSION)
    except (ValueError, IndexError):
        return False


def _plan_guidance_pointer(
    root: Path,
    relative: str,
    purpose: str | None,
    changes: list[dict[str, str | None]],
    preserved: list[str],
    updated: list[str],
    optional_steps: list[str],
    conflicts: list[str],
) -> None:
    try:
        current = _read_path_bytes(root, relative, allow_missing=True)
    except (OSError, ValueError) as exc:
        conflicts.append(f"Unable to inspect optional {relative} guidance: {exc}")
        return
    if current is not None:
        pointer = guidance_pointer(relative, WORKFLOW_VERSION, purpose)
        if _lf(current) != _lf(pointer.encode("utf-8")) and _is_earlier_shipped_copy(relative, current):
            changes.append({"path": relative, "before": current.decode("utf-8"), "after": pointer})
            updated.append(relative)
            return
        preserved.append(f"{relative} (existing guidance left unchanged; a CONNECTED.md pointer is optional)")
        try:
            has_pointer = "knowledge/wiki/CONNECTED.md" in current.decode("utf-8")
        except UnicodeError:
            has_pointer = False
        if not has_pointer:
            optional_steps.append(
                f"Optionally add a short pointer from {relative} to knowledge/wiki/CONNECTED.md; existing guidance was preserved."
            )
        return
    _check_missing_parent_chain(root, relative)
    changes.append({"path": relative, "before": None, "after": guidance_pointer(relative, WORKFLOW_VERSION, purpose)})


def _lf(content: bytes) -> bytes:
    """Normalise CRLF line endings to LF so a copy checked out with CRLF compares equal to the packaged text."""

    return content.replace(b"\r\n", b"\n")


def _is_earlier_shipped_copy(relative: str, content: bytes) -> bool:
    """Tell whether workspace bytes equal an earlier packaged version of a Prism-owned file.

    Line endings are normalised first: the packaged digests are of LF text.
    """

    return hashlib.sha256(_lf(content)).hexdigest() in previous_digests(relative, WORKFLOW_VERSION)


def _plan_gitignore(
    root: Path,
    changes: list[dict[str, str | None]],
    unchanged: list[str],
    conflicts: list[str],
) -> None:
    relative = ".gitignore"
    try:
        current = _read_path_bytes(root, relative, allow_missing=True)
    except (OSError, ValueError) as exc:
        conflicts.append(f"Unable to inspect {relative}: {exc}")
        return
    if current is None:
        _check_missing_parent_chain(root, relative)
        after = f"{_IGNORE_MARKER}\n{_IGNORE_RULE}\n{_LOCAL_IGNORE_MARKER}\n{_LOCAL_IGNORE_RULE}\n"
        changes.append({"path": relative, "before": None, "after": after})
        return
    try:
        text = current.decode("utf-8")
    except UnicodeError as exc:
        conflicts.append(f"{relative} is not UTF-8 text and cannot safely receive the Prism ignore rules: {exc}")
        return
    additions: list[str] = []
    if not _state_ignore_is_effective(text):
        additions.extend((_IGNORE_MARKER, _IGNORE_RULE))
    if not _local_ignore_is_effective(text):
        additions.extend((_LOCAL_IGNORE_MARKER, _LOCAL_IGNORE_RULE))
    if not additions:
        unchanged.append(relative)
        return
    newline = "\r\n" if "\r\n" in text else "\n"
    suffix = "" if not text or text.endswith(("\n", "\r")) else newline
    after = f"{text}{suffix}" + "".join(f"{line}{newline}" for line in additions)
    changes.append({"path": relative, "before": text, "after": after})


def _plan_gitattributes(
    root: Path,
    changes: list[dict[str, str | None]],
    unchanged: list[str],
    conflicts: list[str],
) -> None:
    """Keep the Prism-owned `knowledge/` text on LF in Git checkouts.

    A checkout with `core.autocrlf=true` otherwise rewrites the installed
    files with CRLF. The rule is created or appended; existing content stays.
    """

    relative = ".gitattributes"
    try:
        current = _read_path_bytes(root, relative, allow_missing=True)
    except (OSError, ValueError) as exc:
        conflicts.append(f"Unable to inspect {relative}: {exc}")
        return
    if current is None:
        _check_missing_parent_chain(root, relative)
        changes.append({"path": relative, "before": None, "after": f"{_ATTRIBUTES_MARKER}\n{_ATTRIBUTES_RULE}\n"})
        return
    try:
        text = current.decode("utf-8")
    except UnicodeError as exc:
        conflicts.append(f"{relative} is not UTF-8 text and cannot safely receive the Prism line-ending rule: {exc}")
        return
    if _attributes_rule_is_effective(text):
        unchanged.append(relative)
        return
    newline = "\r\n" if "\r\n" in text else "\n"
    suffix = "" if not text or text.endswith(("\n", "\r")) else newline
    changes.append({"path": relative, "before": text, "after": f"{text}{suffix}{_ATTRIBUTES_MARKER}{newline}{_ATTRIBUTES_RULE}{newline}"})


def _attributes_rule_is_effective(text: str) -> bool:
    """Tell whether the last rule for `knowledge/**` already sets `eol=lf`."""

    effective = False
    for line in text.splitlines():
        tokens = line.split()
        if not tokens or tokens[0].startswith("#") or tokens[0] not in {"knowledge/**", "/knowledge/**"}:
            continue
        effective = "eol=lf" in tokens[1:]
    return effective


def _local_ignore_is_effective(text: str) -> bool:
    """Tell whether the last rule that names `prism.local.yml` ignores it."""

    effective = False
    for line in text.splitlines():
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        negate = value.startswith("!")
        pattern = value[1:].strip() if negate else value
        if pattern in {LOCAL_OVERRIDE_FILE, f"/{LOCAL_OVERRIDE_FILE}"}:
            effective = not negate
    return effective


def _state_ignore_is_effective(text: str) -> bool:
    relevant: list[tuple[bool, bool]] = []
    covered = {".prism", ".prism/", "/.prism", "/.prism/", ".prism/state", ".prism/state/", "/.prism/state", "/.prism/state/"}
    for line in text.splitlines():
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        negate = value.startswith("!")
        pattern = value[1:].strip() if negate else value
        if pattern in covered:
            relevant.append((negate, pattern in {".prism/state", ".prism/state/", "/.prism/state", "/.prism/state/"}))
    if not relevant:
        return False
    last_negate, last_specific = relevant[-1]
    return not last_negate and (last_specific or not any(item[0] for item in relevant))


def _missing_parent_directories(root: Path, changes: list[dict[str, str | None]]) -> list[str]:
    missing: set[str] = set()
    for change in changes:
        parent = PurePosixPath(str(change["path"])).parent
        while parent != PurePosixPath("."):
            candidate = root.joinpath(*parent.parts)
            if not candidate.exists():
                missing.add(parent.as_posix())
            parent = parent.parent
    return sorted(missing, key=lambda item: (item.count("/"), item))


def _ensure_parent_directories(root: Path, parent: Path) -> list[str]:
    relative = parent.relative_to(root)
    created: list[str] = []
    current = root
    for part in relative.parts:
        current = current / part
        if current.exists() or current.is_symlink():
            if _is_link_or_reparse(current) or not current.is_dir():
                if _is_link_or_reparse(current):
                    _raise_if_cloud(current)
                raise ValueError(f"Workflow parent {current.relative_to(root).as_posix()} is not a safe directory.")
            continue
        current.mkdir()
        created.append(current.relative_to(root).as_posix())
    return created


def _atomic_write(root: Path, relative: str, path: Path, content: bytes, expected_before: bytes | None) -> None:
    # The first comparison catches changes made after plan preflight. Recheck
    # again after the temporary file is durable, immediately before replace.
    current = _read_path_bytes(root, relative, allow_missing=True)
    if current != expected_before:
        raise ValueError(f"{relative} changed immediately before replacement; its contents were preserved.")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".prism-tmp", dir=path.parent)
    temporary = Path(temporary_name)
    descriptor_open = True
    try:
        mode = stat.S_IMODE(path.lstat().st_mode) if current is not None else 0o644
        with os.fdopen(descriptor, "wb") as handle:
            descriptor_open = False
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        current = _read_path_bytes(root, relative, allow_missing=True)
        if current != expected_before:
            raise ValueError(f"{relative} changed immediately before replacement; its contents were preserved.")
        os.replace(temporary, path)
    finally:
        if descriptor_open:
            with contextlib.suppress(OSError):
                os.close(descriptor)
        with contextlib.suppress(OSError):
            temporary.unlink()


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _plan_digest(plan: dict[str, Any]) -> str:
    body = {key: value for key, value in plan.items() if key not in ("plan_id", "digest")}
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _receipt(plan: dict[str, Any], *, status: str, **details: Any) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": status,
        "plan_id": plan.get("plan_id"),
        "digest": plan.get("digest"),
        "root": plan.get("root"),
        "version": plan.get("version"),
        "mode": plan.get("mode"),
        "purpose": plan.get("purpose"),
        "board_id": plan.get("board_id"),
        "asset_digest": plan.get("asset_digest"),
        "name": plan.get("name"),
        "apps": plan.get("apps", []),
        **details,
    }
