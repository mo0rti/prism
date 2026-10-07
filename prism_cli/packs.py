"""Stack packs: the app layers of generation and their answers.

Generation has two layers that one ``copier.yml`` and one template tag cover. The workspace layer
(``template/``) holds the knowledge base, the guidance, ``shared/`` and ``docker-compose.yml``. An app
layer (``packs/<stack>/``) holds one app's code, and Copier applies it once per scaffolded app to the
repository root, with every path under the app's own path. The CLI chooses the layer with the hidden
question ``prism_layer`` and passes each layer its answers.

This module holds what the CLI decides for those answers: which stacks have a pack, the identifiers an
app derives from its ID, the validation that keeps two apps apart and the port each app listens on.
"""

from __future__ import annotations

from pathlib import Path
import re
from types import MappingProxyType
from typing import Any, Iterable, Mapping

import yaml

from prism_cli.app_model import (
    GENERATION_REGISTERED,
    GENERATION_SCAFFOLDED,
    STACKS,
    WORKSPACE_REPOSITORY_ID,
    is_slug,
    normalize_manifest,
)


PACKS_DIR = "packs"
PACK_VERSIONS_FILE = "packs/versions.yml"
WORKSPACE_LAYER = "workspace"
COPIER_ANSWERS_FILE = ".copier-answers.yml"

# Stacks with a pack under packs/<stack>/. Each pack work package adds its stack here.
PACK_STACKS = ("spring-backend", "nextjs-web", "android-compose", "ios-swiftui")


def has_pack(stack: str) -> bool:
    return stack in PACK_STACKS


def scaffoldable_stacks() -> tuple[str, ...]:
    """The stacks Prism can scaffold now: those with a pack."""

    return tuple(stack_id for stack_id in STACKS if has_pack(stack_id))


# --- Identifiers ----------------------------------------------------------------

# Kotlin and Java keywords. A package segment cannot be one of them. copier.yml lists the same words.
RESERVED_IDENTIFIERS = frozenset(
    "as break class continue do else false for fun if in interface is null object package return super this throw true try typealias typeof val var when while "
    "abstract assert boolean byte case catch char const default double enum extends final finally float goto implements import instanceof int long native new "
    "private protected public short static strictfp switch synchronized throws transient void volatile".split()
)

PACKAGE_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+")
_SEGMENT_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
_MODULE_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# App IDs the workspace layer's own files would collide with: its api-contracts workflow and its Cursor rules.
RESERVED_APP_IDS = frozenset({"api-contracts", "advisory-review", "api-conventions"})
# Folders at the repository root that belong to the workspace layer or to git.
RESERVED_PATH_ROOTS = frozenset({".git", ".github", ".claude", ".agents", ".cursor", "knowledge", "docs", "shared"})


def app_package_segment(app_id: str) -> str:
    """The package segment of an app: its ID without hyphens."""

    return app_id.replace("-", "")


def app_module_name(app_id: str) -> str:
    """The module, target and class-name prefix of an app: its ID in PascalCase."""

    return "".join(part[:1].upper() + part[1:] for part in app_id.split("-"))


def app_answers_path(app_path: str) -> str:
    """The Copier answers file of a scaffolded app, relative to the repository root."""

    return f"{app_path.rstrip('/')}/{COPIER_ANSWERS_FILE}"


def workflow_path(app_id: str) -> str:
    return f".github/workflows/{app_id}.yml"


def pack_answers(project: Mapping[str, Any], app: Mapping[str, Any], *, port: int | None) -> dict[str, Any]:
    """Every answer an app layer receives: the workspace identity, the app's identity and what derives from its ID.

    ``copier.yml`` derives the same values as defaults, so a raw Copier run agrees with the CLI.
    """

    app_id = str(app["id"])
    app_path = str(app["path"]).rstrip("/")
    package = f"{project['package_identifier']}.{app_package_segment(app_id)}"
    name = str(app.get("name") or app_id)
    return {
        "prism_layer": app["stack"],
        "project_name": project["project_name"],
        "project_slug": project["project_slug"],
        "package_identifier": project["package_identifier"],
        "app_id": app_id,
        "app_name": name,
        "app_path": app_path,
        "audience": app.get("audience") or "",
        "port": port or 0,
        "app_package_segment": app_package_segment(app_id),
        "app_package": package,
        "app_package_path": package.replace(".", "/"),
        "app_module_name": app_module_name(app_id),
        "ci_workflow_name": f"{name} CI",
        "ci_paths": [f"{app_path}/**", "shared/api-contracts/**", workflow_path(app_id)],
    }


def workspace_data(project: Mapping[str, Any], apps: Iterable[Mapping[str, Any]], ports: Mapping[str, int | None]) -> dict[str, Any]:
    """The answers of the workspace layer: the project, the stacks of the scaffolded apps and the app list."""

    entries = [
        {
            "id": app["id"],
            "name": app.get("name") or app["id"],
            "stack": app["stack"],
            "path": app["path"],
            "audience": app.get("audience") or "",
            "port": ports.get(app["id"]) or 0,
        }
        for app in apps
        if app.get("generation") == GENERATION_SCAFFOLDED
    ]
    return {
        **{key: project[key] for key in ("project_name", "project_slug", "package_identifier") if key in project},
        "prism_layer": WORKSPACE_LAYER,
        "stacks": sorted({entry["stack"] for entry in entries}),
        "apps": entries,
    }


# --- Ports ------------------------------------------------------------------------


def allocate_port(stack: str, taken: Iterable[int]) -> int | None:
    """The first port of the stack's range that no app holds, or ``None`` for a stack with no server.

    A port is chosen once, when the app is added, and the app keeps it in its answers: removing another
    app never shifts it.
    """

    stack_info = STACKS.get(stack)
    if stack_info is None or stack_info.port_range is None:
        return None
    first, last = stack_info.port_range
    held = set(taken)
    for port in range(first, last + 1):
        if port not in held:
            return port
    raise ValueError(f"Every port of the {stack} range {first}-{last} is taken.")


def assign_ports(apps: Iterable[Mapping[str, Any]], taken: Iterable[int] = ()) -> dict[str, int]:
    """The port of every scaffolded app that has a pack and a server, each the first free one of its stack's range."""

    held = set(taken)
    ports: dict[str, int] = {}
    for app in apps:
        if app.get("generation") != GENERATION_SCAFFOLDED or not has_pack(str(app.get("stack"))):
            continue
        port = allocate_port(str(app["stack"]), held)
        if port is not None:
            ports[str(app["id"])] = port
            held.add(port)
    return ports


def read_app_answers(root: Path, app_path: str) -> dict[str, Any] | None:
    """The remembered answers of a scaffolded app, or ``None`` when its answers file is missing or unreadable."""

    path = root / app_answers_path(app_path)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeError, yaml.YAMLError, ValueError, OverflowError):
        return None
    return data if isinstance(data, dict) else None


def taken_ports(root: Path, apps: Iterable[Mapping[str, Any]]) -> set[int]:
    """The ports the scaffolded apps of a workspace hold, read from their answers files."""

    ports: set[int] = set()
    for app in apps:
        if app.get("generation") != GENERATION_SCAFFOLDED or not has_pack(str(app.get("stack"))):
            continue
        answers = read_app_answers(root, str(app["path"]))
        port = answers.get("port") if answers else None
        if isinstance(port, int) and not isinstance(port, bool) and port > 0:
            ports.add(port)
    return ports


# --- Maturity -----------------------------------------------------------------------


def stack_maturity(stack: str) -> dict[str, str]:
    """The ``app_maturity`` entry of a scaffolded app of this stack."""

    if stack == "ios-swiftui":
        return {"level": "experimental", "caveat": "Generated iOS structure requires local macOS/Xcode validation before treating it as build-proven."}
    if stack == "nextjs-web":
        return {
            "level": "provisional",
            "caveat": "Generated web apps are verified by lint, typecheck, unit and component tests and the build, with a mocked backend; sign-in against a running backend is checked by hand, and hosting is the project owner's choice (see the deployment skill).",
        }
    return {"level": "baseline", "caveat": ""}


# --- Validation -----------------------------------------------------------------------


def parse_app_list(raw: Any) -> tuple[list[dict[str, Any]], list[dict[str, str]], list[str]]:
    """Turn an app list from an answers file or a preset into manifest app entries.

    Each item names an ``id`` and a ``stack``. ``name`` defaults to the ID, ``path`` to the stack's default
    path (else the ID), ``repository`` to this repository and ``generation`` to ``scaffolded`` for an app of
    a generated stack in this repository, ``registered`` otherwise. An item may carry ``audience`` and, for
    an external repository, ``remote``. Returns the entries, the repositories they declare and the errors.
    """

    errors: list[str] = []
    entries: list[dict[str, Any]] = []
    repositories: list[dict[str, str]] = []
    if raw is None:
        return entries, repositories, errors
    if not isinstance(raw, list):
        return entries, repositories, ["`apps` must be a list of apps."]
    allowed = {"id", "name", "stack", "path", "repository", "remote", "audience", "generation"}
    declared_repositories: dict[str, str] = {}
    for index, item in enumerate(raw):
        label = f"apps[{index}]"
        if not isinstance(item, dict):
            errors.append(f"`{label}` must be a mapping with an `id` and a `stack`.")
            continue
        unknown = sorted(set(item) - allowed)
        if unknown:
            errors.append(f"`{label}` has unknown field(s): {', '.join(unknown)}. An app has {', '.join(sorted(allowed))}.")
            continue
        app_id = item.get("id")
        stack = item.get("stack")
        if not is_slug(app_id):
            errors.append(f"`{label}` needs an `id` that is a slug: lowercase letters, digits and single hyphens.")
            continue
        stack_info = STACKS.get(stack) if isinstance(stack, str) else None
        if stack_info is None:
            errors.append(f"App `{app_id}` needs a `stack` from the registry: {', '.join(STACKS)}.")
            continue
        repository = item.get("repository", WORKSPACE_REPOSITORY_ID)
        if not isinstance(repository, str):
            errors.append(f"App `{app_id}` needs a repository ID as a string.")
            continue
        remote = item.get("remote")
        if remote is not None:
            if repository == WORKSPACE_REPOSITORY_ID:
                errors.append(f"App `{app_id}` names a `remote` but lives in this repository; a remote belongs to an external repository.")
                continue
            if not isinstance(remote, str):
                errors.append(f"App `{app_id}` `remote` must be a string.")
                continue
            if declared_repositories.setdefault(repository, remote) != remote:
                errors.append(f"Repository `{repository}` is given two different remotes.")
                continue
            if not any(entry["id"] == repository for entry in repositories):
                repositories.append({"id": repository, "remote": remote})
        elif repository != WORKSPACE_REPOSITORY_ID and repository not in declared_repositories:
            errors.append(f"App `{app_id}` lives in repository `{repository}`; give its `remote`.")
            continue
        in_workspace = repository == WORKSPACE_REPOSITORY_ID
        generation = item.get("generation", GENERATION_SCAFFOLDED if in_workspace and stack_info.generated else GENERATION_REGISTERED)
        entry: dict[str, Any] = {
            "id": app_id,
            "name": item.get("name", app_id),
            "stack": stack,
            "repository": repository,
            "path": item.get("path", stack_info.default_path or app_id),
            "generation": generation,
        }
        if item.get("audience") is not None:
            entry["audience"] = item["audience"]
        entries.append(entry)
    if errors:
        return entries, repositories, errors

    model, diagnostics = normalize_manifest(
        {"schema_version": 2, "repositories": repositories, "apps": entries}, path=Path("prism.workspace.yml")
    )
    errors.extend(f"{item.code}: {item.message}" for item in diagnostics if item.severity == "error")
    return entries, repositories, errors


def validate_scaffold(apps: Iterable[Mapping[str, Any]], *, only: Iterable[str] | None = None) -> list[str]:
    """What stops Prism scaffolding these apps and keeps their identities apart.

    ``apps`` is every app of the workspace, so the identifiers are compared across all of them. ``only``
    limits the scaffold checks (the stack, the path and the files the pack creates) to the apps being
    scaffolded now; the identifier checks always cover every app.
    """

    entries = [dict(app) for app in apps]
    scaffolding = set(only) if only is not None else {entry["id"] for entry in entries if entry.get("generation") == GENERATION_SCAFFOLDED}
    errors: list[str] = []
    segments: dict[str, str] = {}
    for entry in entries:
        app_id = entry["id"]
        segment = app_package_segment(app_id)
        if segment in segments:
            errors.append(
                f"Apps `{segments[segment]}` and `{app_id}` would share the package segment `{segment}`; "
                "choose IDs that differ by more than their hyphens."
            )
        else:
            segments[segment] = app_id
        if app_id not in scaffolding:
            continue
        if not _SEGMENT_PATTERN.fullmatch(segment) or segment in RESERVED_IDENTIFIERS:
            errors.append(f"App `{app_id}` cannot be scaffolded: its package segment `{segment}` is a Kotlin or Java keyword or not a valid identifier.")
        if not _MODULE_PATTERN.fullmatch(app_module_name(app_id)):
            errors.append(f"App `{app_id}` cannot be scaffolded: its module name `{app_module_name(app_id)}` is not a valid identifier.")
        if app_id in RESERVED_APP_IDS:
            errors.append(f"App `{app_id}` cannot be scaffolded: its workflow or Cursor rule would replace a file of the workspace.")
        stack = entry["stack"]
        path = str(entry["path"])
        if has_pack(stack):
            first = path.split("/", 1)[0]
            if first in RESERVED_PATH_ROOTS:
                errors.append(f"App `{app_id}` cannot be scaffolded at `{path}`: `{first}/` belongs to the workspace.")
        else:
            errors.append(f"Stack `{stack}` cannot be scaffolded: Prism has no pack for it. Register `{app_id}` instead.")
    return errors


def scaffold_collisions(root: Path, app: Mapping[str, Any]) -> list[str]:
    """The files in an existing workspace that scaffolding this app would collide with."""

    app_id = str(app["id"])
    problems: list[str] = []
    target = root / str(app["path"])
    if target.exists() and (target.is_file() or any(target.iterdir())):
        problems.append(f"The path `{app['path']}` of app `{app_id}` already holds files; a scaffolded app needs an empty or absent path.")
    if has_pack(str(app["stack"])):
        for relative in (workflow_path(app_id), f".cursor/rules/{app_id}.mdc"):
            if (root / relative).exists():
                problems.append(f"`{relative}` already exists; scaffolding app `{app_id}` would replace it.")
    return problems


def load_pack_versions(template_root: Path) -> Mapping[str, Any]:
    """The pinned versions of a template checkout, as ``packs/versions.yml`` states them."""

    data = yaml.safe_load((template_root / PACK_VERSIONS_FILE).read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{PACK_VERSIONS_FILE} must be a mapping of stack to pinned versions.")
    return MappingProxyType(data)
