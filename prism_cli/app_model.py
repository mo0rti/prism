"""Application model: the stack registry, manifest version 2 and the one normalizer.

``prism.workspace.yml`` declares what a workspace contains: repositories and
apps, and every app has a stack from the registry below. ``normalize_manifest``
turns the manifest into one ``WorkspaceModel``, and every reader of the manifest
goes through it. Nothing in this module writes a file.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
import re
from types import MappingProxyType
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit

import yaml

from prism_cli.fs_safety import reparse_kind


# The one manifest version this CLI reads and writes.
MANIFEST_SCHEMA_VERSION = 2

WORKSPACE_REPOSITORY_ID = "workspace"
LOCAL_OVERRIDE_FILE = "prism.local.yml"

# The slug rule `prism new` applies to a project slug: a lowercase letter first,
# then lowercase letters and digits, with single hyphens between parts.
SLUG_PATTERN = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*")

CAPABILITY_HAS_UI = "has-ui"
CAPABILITY_SERVES_API = "serves-api"
CAPABILITIES = (CAPABILITY_HAS_UI, CAPABILITY_SERVES_API)
UNKNOWN = "unknown"

APP_STATUSES = ("active", "retired")

# What a workflow workspace is for, from the optional ``workflow.purpose`` field.
# No gate reads it; status, the board and the generated guidance describe it.
PURPOSE_KNOWLEDGE_ROOT = "knowledge-root"
WORKFLOW_PURPOSES = (PURPOSE_KNOWLEDGE_ROOT,)


@dataclass(frozen=True)
class WorkspaceDiagnostic:
    """One finding about a workspace, shared by the manifest, model and comparison checks."""

    code: str
    severity: str
    path: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "severity": self.severity,
            "path": self.path,
            "message": self.message,
        }


def _diag(code: str, severity: str, path: Path, message: str) -> WorkspaceDiagnostic:
    return WorkspaceDiagnostic(code=code, severity=severity, path=str(path), message=message)


# --- Stack registry ---------------------------------------------------------


@dataclass(frozen=True)
class Stack:
    """A kind of application. ``generated`` stacks have a template in this CLI."""

    id: str
    generated: bool
    default_capabilities: Mapping[str, bool]
    default_path: str | None = None


def _stack(stack_id: str, generated: bool, capabilities: Mapping[str, bool], default_path: str | None = None) -> Stack:
    return Stack(stack_id, generated, MappingProxyType(dict(capabilities)), default_path)


STACKS: Mapping[str, Stack] = MappingProxyType(
    {
        "spring-backend": _stack("spring-backend", True, {CAPABILITY_HAS_UI: False, CAPABILITY_SERVES_API: True}, "backend"),
        "nextjs-web": _stack("nextjs-web", True, {CAPABILITY_HAS_UI: True, CAPABILITY_SERVES_API: False}),
        "android-compose": _stack("android-compose", True, {CAPABILITY_HAS_UI: True, CAPABILITY_SERVES_API: False}, "mobile-android"),
        "ios-swiftui": _stack("ios-swiftui", True, {CAPABILITY_HAS_UI: True, CAPABILITY_SERVES_API: False}, "mobile-ios"),
        # An app of an unlisted kind declares both capabilities itself.
        "other": _stack("other", False, {}),
    }
)

# --- Generated platforms ----------------------------------------------------

# The platform IDs the questionnaire offers, each the ID of the app that
# generating it registers. Iteration order is the order of the platform
# directory table.
GENERATED_PLATFORM_IDS = ("backend", "mobile-android", "mobile-ios", "web-user-app", "web-admin-portal")

GENERATED_PLATFORM_STACKS: Mapping[str, str] = MappingProxyType(
    {
        "backend": "spring-backend",
        "web-user-app": "nextjs-web",
        "web-admin-portal": "nextjs-web",
        "mobile-android": "android-compose",
        "mobile-ios": "ios-swiftui",
    }
)

# Iteration order is the order of the questionnaire choices.
GENERATED_PLATFORM_LABELS: Mapping[str, str] = MappingProxyType(
    {
        "backend": "Spring Boot Backend",
        "web-user-app": "User-Facing Web App",
        "web-admin-portal": "Admin Web Portal",
        "mobile-android": "Android (Kotlin/Compose)",
        "mobile-ios": "iOS (Swift/SwiftUI)",
    }
)

ALL_PLATFORM_CHOICES: tuple[tuple[str, str], ...] = tuple(GENERATED_PLATFORM_LABELS.items())


def generated_platform_dir(platform_id: str) -> str:
    """The workspace directory of a generated platform: the stack's default path, else the ID."""

    return STACKS[GENERATED_PLATFORM_STACKS[platform_id]].default_path or platform_id


GENERATED_PLATFORM_DIRS: Mapping[str, str] = MappingProxyType({platform_id: generated_platform_dir(platform_id) for platform_id in GENERATED_PLATFORM_IDS})

def apps_from_platforms(platforms: list[str]) -> list[dict[str, str]]:
    """Manifest `apps` entries for generated platform IDs, in the order given.

    Each app's ID is the platform ID, its stack comes from the platform, and it
    lives in the workspace repository at the platform's directory.
    """

    unknown = [item for item in platforms if item not in GENERATED_PLATFORM_STACKS]
    if unknown:
        raise ValueError(f"Unsupported Prism platform IDs: {', '.join(str(item) for item in unknown)}.")
    return [
        {
            "id": platform_id,
            "name": GENERATED_PLATFORM_LABELS[platform_id],
            "stack": GENERATED_PLATFORM_STACKS[platform_id],
            "repository": WORKSPACE_REPOSITORY_ID,
            "path": GENERATED_PLATFORM_DIRS[platform_id],
        }
        for platform_id in platforms
    ]


# --- Model ------------------------------------------------------------------


@dataclass(frozen=True)
class Repository:
    """A repository the workspace's apps live in. ``workspace`` is this repository."""

    id: str
    remote: str | None = None

    @property
    def is_workspace(self) -> bool:
        return self.id == WORKSPACE_REPOSITORY_ID


@dataclass(frozen=True)
class App:
    id: str
    name: str
    stack: str
    repository: str = WORKSPACE_REPOSITORY_ID
    path: str = ""
    audience: str | None = None
    capability_overrides: Mapping[str, bool | str] = field(default_factory=dict)
    status: str = "active"

    @property
    def active(self) -> bool:
        return self.status == "active"

    @property
    def in_workspace(self) -> bool:
        return self.repository == WORKSPACE_REPOSITORY_ID

    def capability(self, name: str) -> bool | str:
        """The resolved capability: ``True``, ``False`` or ``"unknown"``.

        An override wins over the stack default. A capability the stack has no
        default for, and the app did not declare, is ``"unknown"``.
        """

        if name in self.capability_overrides:
            return self.capability_overrides[name]
        stack = STACKS.get(self.stack)
        if stack is not None and name in stack.default_capabilities:
            return stack.default_capabilities[name]
        return UNKNOWN

    @property
    def capabilities(self) -> dict[str, bool | str]:
        return {name: self.capability(name) for name in CAPABILITIES}

    def gate_capability(self, name: str) -> bool:
        """The value a lifecycle gate reads: ``"unknown"`` counts as ``True``, the stricter side."""

        return self.capability(name) is not False


@dataclass(frozen=True)
class WorkspaceModel:
    schema_version: int
    repositories: tuple[Repository, ...] = (Repository(WORKSPACE_REPOSITORY_ID),)
    apps: tuple[App, ...] = ()
    app_maturity: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    purpose: str | None = None

    @property
    def knowledge_root(self) -> bool:
        return self.purpose == PURPOSE_KNOWLEDGE_ROOT

    @property
    def active_app_ids(self) -> list[str]:
        return [app.id for app in self.apps if app.active]

    def app(self, app_id: str) -> App | None:
        return next((app for app in self.apps if app.id == app_id), None)

    def repository(self, repository_id: str) -> Repository | None:
        return next((item for item in self.repositories if item.id == repository_id), None)

    @property
    def external_repositories(self) -> tuple[Repository, ...]:
        return tuple(item for item in self.repositories if not item.is_workspace)

    def workspace_apps(self, *, active_only: bool = False) -> tuple[App, ...]:
        """Apps whose code lives in this repository, at their paths."""

        return tuple(app for app in self.apps if app.in_workspace and (app.active or not active_only))

    def maturity(self, app_id: str) -> dict[str, str] | None:
        """The ``app_maturity`` entry of an app, or ``None`` when the manifest records none."""

        entry = self.app_maturity.get(app_id)
        return dict(entry) if entry is not None else None

    def retired_apps(self, app_ids: Iterable[str]) -> list[str]:
        """The IDs among ``app_ids`` that name a retired app, in the order given."""

        return [app_id for app_id in app_ids if (app := self.app(app_id)) is not None and not app.active]

    def scope_serves_api(self, app_ids: Iterable[str]) -> bool:
        """Whether an active app among ``app_ids`` serves an API, as a lifecycle gate reads it (``unknown`` counts as true)."""

        return any((app := self.app(app_id)) is not None and app.active and app.gate_capability(CAPABILITY_SERVES_API) for app_id in app_ids)


def _quoted_ids(app_ids: Iterable[str]) -> str:
    return ", ".join(f"`{app_id}`" for app_id in app_ids)


def retired_in_scope_message(feature_id: str, retired: Iterable[str]) -> str:
    """The finding for an in-progress feature whose scope lists a retired app."""

    return (
        f"Feature `{feature_id}` is in progress and lists retired app(s) {_quoted_ids(retired)}. Retiring an app never changes a feature's scope by itself; "
        "edit the feature's `apps` explicitly (and its `## App scope`), and record the change in `log.md`."
    )


def app_retired_message(retired: Iterable[str]) -> str:
    """The rejection for a new feature, or an edit, that adds a retired app to a feature's scope."""

    return f"App(s) {_quoted_ids(retired)} are retired and cannot be added to a feature's scope; a retired app stays only on features that are done."


def api_surface_without_api_app_message(model: "WorkspaceModel", feature_id: str, app_ids: Iterable[str]) -> str:
    """The finding for a feature that declares API work while no active app in its scope serves an API."""

    described = ", ".join(
        f"`{app_id}` ({'unknown app' if (app := model.app(app_id)) is None else 'retired' if not app.active else f'serves-api: {str(app.capability(CAPABILITY_SERVES_API)).lower()}'})"
        for app_id in app_ids
    )
    return (
        f"Feature `{feature_id}` declares API work in `## API surface`, but no active app in its scope serves an API: its apps are {described or 'none'}. "
        "Add an app that serves an API to `apps`, or change the API surface."
    )


# --- Output shapes ----------------------------------------------------------

CHECKOUT_RESOLVED = "resolved"
CHECKOUT_UNRESOLVED = "unresolved"


def app_entries(model: WorkspaceModel) -> list[dict[str, Any]]:
    """Every app of the workspace in manifest order, in the shape workspace-level JSON reports.

    Each entry has ``id``, ``name``, ``stack``, ``repository``, ``path``,
    ``audience`` (or ``None``), ``status``, ``capabilities`` (``has-ui`` and
    ``serves-api``, each ``True``, ``False`` or ``"unknown"``) and ``maturity``
    (the ``app_maturity`` entry or ``None``).
    """

    return [
        {
            "id": app.id,
            "name": app.name,
            "stack": app.stack,
            "repository": app.repository,
            "path": app.path,
            "audience": app.audience,
            "status": app.status,
            "capabilities": app.capabilities,
            "maturity": model.maturity(app.id),
        }
        for app in model.apps
    ]


def repository_entries(model: WorkspaceModel, local_repositories: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The repositories of the workspace: ``id``, ``remote`` (or ``None``) and, for an external one, ``checkout``.

    ``checkout`` is ``resolved`` or ``unresolved`` from ``prism.local.yml``. The
    local path itself is never reported.
    """

    entries: list[dict[str, Any]] = []
    for repository in model.repositories:
        entry: dict[str, Any] = {"id": repository.id, "remote": repository.remote}
        if not repository.is_workspace:
            entry["checkout"] = CHECKOUT_RESOLVED if repository.id in local_repositories else CHECKOUT_UNRESOLVED
        entries.append(entry)
    return entries


# --- Normalizer -------------------------------------------------------------


def normalize_manifest(data: Mapping[str, Any], *, path: Path) -> tuple[WorkspaceModel, list[WorkspaceDiagnostic]]:
    """Turn a parsed manifest into the application model, plus its diagnostics.

    Every repository and app rule is validated, and each failure is an error.
    A schema version other than 2 yields an empty model and the
    unsupported-version error. Nothing is written.
    """

    version = data.get("schema_version")
    if not isinstance(version, int) or isinstance(version, bool):
        return WorkspaceModel(schema_version=0), [
            _diag("invalid-workspace-manifest-schema", "error", path, "prism.workspace.yml schema_version must be an integer.")
        ]
    if version != MANIFEST_SCHEMA_VERSION:
        return WorkspaceModel(schema_version=version), [
            _diag(
                "unsupported-workspace-manifest-schema",
                "error",
                path,
                f"prism.workspace.yml schema_version is {version}; this CLI supports only {MANIFEST_SCHEMA_VERSION}. Recreate or reinstall this workspace with this CLI.",
            )
        ]
    return _normalize_manifest(data, path)


def _normalize_manifest(data: Mapping[str, Any], path: Path) -> tuple[WorkspaceModel, list[WorkspaceDiagnostic]]:
    diagnostics: list[WorkspaceDiagnostic] = []
    project = data.get("project")
    if isinstance(project, dict) and "platforms" in project:
        diagnostics.append(
            _diag(
                "conflicting-app-declarations",
                "error",
                path,
                "`project.platforms` is not a valid field; declare the workspace's apps in `apps`.",
            )
        )
    repositories = _read_repositories(data.get("repositories"), path, diagnostics)
    apps, declared_ids = _read_apps(data.get("apps"), repositories, path, diagnostics)
    maturity = _read_app_maturity(data.get("app_maturity"), declared_ids, path, diagnostics)
    _check_path_conflicts(apps, path, diagnostics)
    purpose = _read_purpose(data.get("workflow"), path, diagnostics)
    return (
        WorkspaceModel(
            schema_version=MANIFEST_SCHEMA_VERSION,
            repositories=tuple(repositories),
            apps=tuple(apps),
            app_maturity=maturity,
            purpose=purpose,
        ),
        diagnostics,
    )


def _read_purpose(workflow: Any, path: Path, diagnostics: list[WorkspaceDiagnostic]) -> str | None:
    """The workspace purpose: ``knowledge-root`` or absent. Anything else is an error."""

    if not isinstance(workflow, dict) or "purpose" not in workflow:
        return None
    purpose = workflow["purpose"]
    if purpose not in WORKFLOW_PURPOSES or not isinstance(purpose, str):
        diagnostics.append(
            _diag(
                "invalid-workflow-purpose",
                "error",
                path,
                f"Manifest `workflow.purpose` must be `{PURPOSE_KNOWLEDGE_ROOT}` or absent.",
            )
        )
        return None
    if workflow.get("mode") != "workflow":
        diagnostics.append(
            _diag(
                "invalid-workflow-purpose",
                "error",
                path,
                f"`workflow.purpose: {purpose}` belongs to a workflow-only workspace; `workflow.mode` must be `workflow`.",
            )
        )
        return None
    return purpose


def is_slug(value: Any) -> bool:
    return isinstance(value, str) and SLUG_PATTERN.fullmatch(value) is not None


def _read_repositories(value: Any, path: Path, diagnostics: list[WorkspaceDiagnostic]) -> list[Repository]:
    repositories = [Repository(WORKSPACE_REPOSITORY_ID)]
    if value is None:
        return repositories
    if not isinstance(value, list):
        diagnostics.append(_diag("invalid-repository", "error", path, "Manifest `repositories` must be a list of repositories."))
        return repositories
    declared: set[str] = set()
    for index, item in enumerate(value):
        label = f"repositories[{index}]"
        if not isinstance(item, dict):
            diagnostics.append(_diag("invalid-repository", "error", path, f"Manifest `{label}` must be a mapping with an `id` and a `remote`."))
            continue
        repository_id = item.get("id")
        if not is_slug(repository_id):
            diagnostics.append(_diag("invalid-repository", "error", path, f"Manifest `{label}` needs an `id` that is a slug: lowercase letters, digits and single hyphens."))
            continue
        if repository_id in declared:
            diagnostics.append(_diag("duplicate-repository-id", "error", path, f"Repository `{repository_id}` is declared more than once."))
            continue
        declared.add(repository_id)
        remote = item.get("remote")
        if repository_id != WORKSPACE_REPOSITORY_ID and remote is None:
            diagnostics.append(
                _diag("repository-remote-required", "error", path, f"Repository `{repository_id}` needs a `remote`: its canonical URL, never a local path.")
            )
            continue
        if remote is not None:
            problem = _remote_problem(remote)
            if problem is not None:
                diagnostics.append(_diag("invalid-repository-remote", "error", path, f"Repository `{repository_id}` remote {problem}"))
                continue
        if repository_id == WORKSPACE_REPOSITORY_ID:
            repositories[0] = Repository(WORKSPACE_REPOSITORY_ID, remote)
        else:
            repositories.append(Repository(repository_id, remote))
    return repositories


_SCP_REMOTE = re.compile(r"git@[A-Za-z0-9][A-Za-z0-9.-]*:(?!/)[^\s:][^\s]*")


def _remote_problem(remote: Any) -> str | None:
    """Why a repository remote is not a canonical remote URL, or ``None``."""

    if not isinstance(remote, str) or not remote.strip():
        return "must be a non-empty string."
    if remote != remote.strip() or re.search(r"\s", remote):
        return "must not contain whitespace."
    if _SCP_REMOTE.fullmatch(remote):
        return None
    scheme = remote.split(":", 1)[0].lower() if ":" in remote else ""
    if scheme in {"https", "ssh"} and remote[len(scheme) :].startswith("://"):
        try:
            parsed = urlsplit(remote)
            host = parsed.hostname
            password = parsed.password
        except ValueError:
            return "is not a valid URL."
        if not host:
            return "needs a host."
        if password is not None:
            return "must not embed credentials."
        return None
    return "must be an https:// or ssh:// URL or a git@host:path address, never a local path or file: URL."


def _read_apps(
    value: Any,
    repositories: list[Repository],
    path: Path,
    diagnostics: list[WorkspaceDiagnostic],
) -> tuple[list[App], set[str]]:
    apps: list[App] = []
    declared_ids: set[str] = set()
    if value is None:
        return apps, declared_ids
    if not isinstance(value, list):
        diagnostics.append(_diag("invalid-app-declaration", "error", path, "Manifest `apps` must be a list of apps."))
        return apps, declared_ids
    repository_ids = {item.id for item in repositories}
    for index, item in enumerate(value):
        label = f"apps[{index}]"
        if not isinstance(item, dict):
            diagnostics.append(_diag("invalid-app-declaration", "error", path, f"Manifest `{label}` must be a mapping."))
            continue
        app_id = item.get("id")
        if not is_slug(app_id):
            diagnostics.append(_diag("invalid-app-id", "error", path, f"Manifest `{label}` needs an `id` that is a slug: lowercase letters, digits and single hyphens."))
            continue
        if app_id in declared_ids:
            diagnostics.append(_diag("duplicate-app-id", "error", path, f"App `{app_id}` is declared more than once."))
            continue
        declared_ids.add(app_id)
        app = _read_app(item, app_id, repository_ids, repositories, path, diagnostics)
        if app is not None:
            apps.append(app)
    return apps, declared_ids


def _read_app(
    item: Mapping[str, Any],
    app_id: str,
    repository_ids: set[str],
    repositories: list[Repository],
    path: Path,
    diagnostics: list[WorkspaceDiagnostic],
) -> App | None:
    """One app, or ``None`` when a field of its own is invalid (the error is recorded)."""

    valid = True

    stack_id = item.get("stack")
    stack = STACKS.get(stack_id) if isinstance(stack_id, str) else None
    if stack is None:
        diagnostics.append(_diag("unknown-app-stack", "error", path, f"App `{app_id}` needs a `stack` from the registry: {', '.join(STACKS)}."))
        valid = False

    repository_id = item.get("repository", WORKSPACE_REPOSITORY_ID)
    if not isinstance(repository_id, str) or repository_id not in repository_ids:
        diagnostics.append(_diag("unknown-app-repository", "error", path, f"App `{app_id}` names a repository that `repositories` does not declare."))
        valid = False

    app_path: str | None = None
    raw_path = item.get("path")
    if raw_path is None and stack is not None and stack.default_path is not None:
        raw_path = stack.default_path
    problem = _app_path_problem(raw_path, repository_id if isinstance(repository_id, str) else WORKSPACE_REPOSITORY_ID)
    if problem is not None:
        diagnostics.append(_diag("invalid-app-path", "error", path, f"App `{app_id}` path {problem}"))
        valid = False
    else:
        app_path = _normalized_app_path(raw_path)

    name = item.get("name", app_id)
    audience = item.get("audience")
    if not isinstance(name, str) or not name.strip() or (audience is not None and not isinstance(audience, str)):
        diagnostics.append(_diag("invalid-app-declaration", "error", path, f"App `{app_id}` needs a non-empty string `name`, and `audience` must be a string."))
        valid = False

    status = item.get("status", "active")
    if status not in APP_STATUSES:
        diagnostics.append(_diag("invalid-app-status", "error", path, f"App `{app_id}` status must be `active` or `retired`."))
        valid = False

    overrides, capabilities_valid = _read_capabilities(item.get("capabilities"), app_id, stack, path, diagnostics)
    valid = valid and capabilities_valid

    if not valid or stack is None or app_path is None:
        return None
    return App(
        id=app_id,
        name=name.strip(),
        stack=stack.id,
        repository=repository_id,
        path=app_path,
        audience=audience,
        capability_overrides=overrides,
        status=status,
    )


def _read_capabilities(
    value: Any,
    app_id: str,
    stack: Stack | None,
    path: Path,
    diagnostics: list[WorkspaceDiagnostic],
) -> tuple[dict[str, bool | str], bool]:
    overrides: dict[str, bool | str] = {}
    valid = True
    if value is not None and not isinstance(value, dict):
        diagnostics.append(_diag("invalid-app-capability", "error", path, f"App `{app_id}` `capabilities` must be a mapping of capability to true, false or unknown."))
        return overrides, False
    for name, setting in (value or {}).items():
        if name not in CAPABILITIES:
            diagnostics.append(_diag("invalid-app-capability", "error", path, f"App `{app_id}` declares unknown capability `{name}`; the capabilities are {', '.join(CAPABILITIES)}."))
            valid = False
        elif not (isinstance(setting, bool) or setting == UNKNOWN):
            diagnostics.append(_diag("invalid-app-capability", "error", path, f"App `{app_id}` capability `{name}` must be true, false or unknown."))
            valid = False
        else:
            overrides[name] = setting
    if stack is not None and not stack.default_capabilities:
        declared_names = set(value or {})
        for name in CAPABILITIES:
            if name not in declared_names:
                diagnostics.append(
                    _diag("undeclared-app-capability", "error", path, f"App `{app_id}` has stack `{stack.id}`, which has no defaults, so it must declare `{name}` as true, false or unknown.")
                )
                valid = False
    return overrides, valid


_DRIVE_PATH = re.compile(r"^[A-Za-z]:")


def _app_path_problem(value: Any, repository_id: str) -> str | None:
    """Why an app path is not a safe repository-relative path, or ``None``."""

    if not isinstance(value, str) or not value.strip():
        return "is required and must be a non-empty string."
    if value != value.strip() or "\x00" in value:
        return "must not have surrounding whitespace or NUL characters."
    if "\\" in value or _DRIVE_PATH.match(value) or value.startswith("/"):
        return "must be a relative POSIX path from the repository root, never absolute, with a drive or with a backslash."
    normalized = value[:-1] if value.endswith("/") and len(value) > 1 else value
    parts = normalized.split("/")
    if any(part in ("", "..") for part in parts):
        return "must not contain empty or `..` segments."
    if normalized == ".":
        if repository_id == WORKSPACE_REPOSITORY_ID:
            return "cannot be `.` in the workspace repository, which also holds the knowledge base and workflow files."
        return None
    if "." in parts:
        return "must not contain `.` segments."
    return None


def _normalized_app_path(value: str) -> str:
    return value[:-1] if value.endswith("/") and len(value) > 1 else value


def _check_path_conflicts(apps: list[App], path: Path, diagnostics: list[WorkspaceDiagnostic]) -> None:
    for index, app in enumerate(apps):
        left = _path_key(app.path)
        for other in apps[index + 1 :]:
            if other.repository != app.repository:
                continue
            right = _path_key(other.path)
            if left == right:
                diagnostics.append(_diag("app-path-conflict", "error", path, f"Apps `{app.id}` and `{other.id}` share the path `{app.path}` in repository `{app.repository}`."))
            elif _contains(left, right) or _contains(right, left):
                diagnostics.append(
                    _diag(
                        "app-path-conflict",
                        "error",
                        path,
                        f"App paths overlap in repository `{app.repository}`: `{app.id}` at `{app.path}` and `{other.id}` at `{other.path}`.",
                    )
                )


def _path_key(value: str) -> tuple[str, ...]:
    """Path segments, compared without case so a path cannot differ only by case on a case-insensitive disk."""

    return () if value == "." else tuple(part.casefold() for part in PurePosixPath(value).parts)


def _contains(outer: tuple[str, ...], inner: tuple[str, ...]) -> bool:
    return len(outer) < len(inner) and inner[: len(outer)] == outer


def _read_app_maturity(
    value: Any,
    declared_ids: set[str],
    path: Path,
    diagnostics: list[WorkspaceDiagnostic],
) -> dict[str, dict[str, str]]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        diagnostics.append(_diag("invalid-app-maturity", "error", path, "Manifest `app_maturity` must map app IDs to maturity entries."))
        return {}
    maturity: dict[str, dict[str, str]] = {}
    for key, data in value.items():
        if not isinstance(key, str) or key not in declared_ids:
            diagnostics.append(_diag("invalid-app-maturity", "error", path, f"`app_maturity` key `{key}` is not an app ID declared in `apps`."))
            continue
        if not isinstance(data, dict):
            diagnostics.append(_diag("invalid-app-maturity", "error", path, f"`app_maturity` entry `{key}` must be a mapping."))
            continue
        maturity[key] = {name: item for name, item in data.items() if isinstance(name, str) and isinstance(item, str)}
    return maturity


# --- Local checkouts of external repositories -------------------------------


@dataclass(frozen=True)
class LocalRepositories:
    """Where this machine keeps the external repositories, from ``prism.local.yml``."""

    paths: Mapping[str, Path] = field(default_factory=dict)
    diagnostics: tuple[WorkspaceDiagnostic, ...] = ()


def resolve_local_repositories(root: Path, model: WorkspaceModel) -> LocalRepositories:
    """Record which external repositories resolve to a checkout on this machine.

    ``prism.local.yml`` is untracked and per machine (``repositories: {<id>:
    <absolute path>}``). A missing or unreadable file is not an error. An
    external repository without a usable checkout is one warning. The checkout
    is only inspected, never read from or written to, and a symlink or reparse
    point is not followed.
    """

    external = [item.id for item in model.external_repositories]
    local_path = root / LOCAL_OVERRIDE_FILE
    diagnostics: list[WorkspaceDiagnostic] = []
    entries = _read_local_entries(local_path, diagnostics)

    for repository_id in entries:
        if repository_id not in external:
            diagnostics.append(
                _diag(
                    "unknown-local-repository",
                    "warning",
                    local_path,
                    f"{LOCAL_OVERRIDE_FILE} names repository `{repository_id}`, which the workspace manifest does not declare as an external repository.",
                )
            )

    resolved: dict[str, Path] = {}
    for repository_id in external:
        if repository_id not in entries:
            diagnostics.append(_unresolved(local_path, repository_id, f"{LOCAL_OVERRIDE_FILE} has no entry for it"))
            continue
        raw = entries[repository_id]
        candidate = Path(raw) if isinstance(raw, str) and raw.strip() else None
        if candidate is None or not candidate.is_absolute():
            diagnostics.append(
                _diag(
                    "invalid-local-repository-path",
                    "warning",
                    local_path,
                    f"{LOCAL_OVERRIDE_FILE} entry for `{repository_id}` must be an absolute path to the checkout.",
                )
            )
            continue
        reason = _checkout_problem(candidate)
        if reason is not None:
            diagnostics.append(_unresolved(local_path, repository_id, reason))
            continue
        resolved[repository_id] = candidate
    return LocalRepositories(paths=resolved, diagnostics=tuple(diagnostics))


def _unresolved(local_path: Path, repository_id: str, reason: str) -> WorkspaceDiagnostic:
    return _diag(
        "external-repository-unresolved",
        "warning",
        local_path,
        f"External repository `{repository_id}` has no checkout on this machine ({reason}); add `repositories: {{{repository_id}: <absolute path>}}` to {LOCAL_OVERRIDE_FILE}. Links into it are skipped.",
    )


def _read_local_entries(local_path: Path, diagnostics: list[WorkspaceDiagnostic]) -> dict[str, Any]:
    try:
        info = local_path.lstat()
    except FileNotFoundError:
        return {}
    except OSError as exc:
        diagnostics.append(_diag("unreadable-local-repositories", "warning", local_path, f"Unable to read {LOCAL_OVERRIDE_FILE}: {exc}"))
        return {}
    if reparse_kind(info) != "none":
        diagnostics.append(
            _diag("unreadable-local-repositories", "warning", local_path, f"{LOCAL_OVERRIDE_FILE} is a symlink or reparse point, so it is ignored.")
        )
        return {}
    try:
        loaded = yaml.safe_load(local_path.read_text(encoding="utf-8-sig")) or {}
    except (OSError, UnicodeError, yaml.YAMLError, ValueError, OverflowError) as exc:
        diagnostics.append(_diag("unreadable-local-repositories", "warning", local_path, f"Unable to read {LOCAL_OVERRIDE_FILE}: {exc}"))
        return {}
    entries = loaded.get("repositories") if isinstance(loaded, dict) else None
    if entries is None:
        return {}
    if not isinstance(entries, dict) or any(not isinstance(key, str) for key in entries):
        diagnostics.append(
            _diag("unreadable-local-repositories", "warning", local_path, f"{LOCAL_OVERRIDE_FILE} `repositories` must map repository IDs to absolute paths.")
        )
        return {}
    return dict(entries)


def _checkout_problem(candidate: Path) -> str | None:
    """Why a checkout path does not count as resolved, or ``None``."""

    try:
        info = candidate.lstat()
    except OSError:
        return "the recorded path does not exist"
    if reparse_kind(info) != "none":
        return "the recorded path is a symlink or reparse point"
    if not candidate.is_dir():
        return "the recorded path is not a directory"
    return None
