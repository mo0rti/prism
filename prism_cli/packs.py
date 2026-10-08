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
    BACKEND_CLIENT_STACKS,
    BACKEND_STACK,
    GENERATION_REGISTERED,
    GENERATION_SCAFFOLDED,
    STACKS,
    WORKSPACE_REPOSITORY_ID,
    is_slug,
    normalize_manifest,
)
from prism_cli.safe_values import DESCRIPTION_RULE, LABEL_RULE, description_problem, label_problem, path_segments_problem
from prism_cli.wiki_paths import RefusedPath, read_confined_bytes


PACKS_DIR = "packs"
PACK_VERSIONS_FILE = "packs/versions.yml"
WORKSPACE_LAYER = "workspace"
COPIER_ANSWERS_FILE = ".copier-answers.yml"

# Stacks with a pack under packs/<stack>/. Each pack work package adds its stack here.
PACK_STACKS = ("spring-backend", "nextjs-web", "android-compose", "ios-swiftui", "python-agent-service")


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

# The Swift module of an iOS app is its module name, and `@testable import <module>` must find the app, not a system
# framework. These are the names of Apple frameworks and Swift runtime modules an app of this name would shadow. They
# are compared without case, because the module's files sit on a file system that may ignore it.
IOS_SYSTEM_MODULES = frozenset(
    name.casefold()
    for name in (
        "Swift SwiftUI UIKit AppKit Foundation Combine Observation Dispatch Darwin Glibc XCTest Testing CoreData CoreGraphics CoreFoundation "
        "CoreLocation CoreImage CoreText CoreMotion CoreML CoreBluetooth CoreMedia CoreVideo CoreAudio CoreHaptics CoreSpotlight CoreTelephony "
        "CloudKit MapKit AVFoundation AVKit StoreKit WebKit Security Network OSLog os Accelerate Metal MetalKit SceneKit SpriteKit RealityKit ARKit "
        "UserNotifications Intents AppIntents SwiftData Charts WidgetKit ActivityKit PhotosUI Photos MessageUI LocalAuthentication Contacts "
        "ContactsUI EventKit HealthKit GameKit GameplayKit PDFKit QuickLook SafariServices AuthenticationServices BackgroundTasks CryptoKit "
        "Synchronization Spatial TipKit Vision VisionKit NaturalLanguage Speech SoundAnalysis Translation PassKit WatchKit CarPlay ClockKit "
        "Compression Collections RegexBuilder Cocoa UniformTypeIdentifiers SystemConfiguration ImageIO CFNetwork FileProvider Concurrency".split()
    )
)

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


def ci_workflow_name(app_name: str, app_id: str) -> str:
    """The display name of an app's CI workflow: its name, and its ID when that adds something, so no two apps share one."""

    return f"{app_name} CI" if app_name == app_id else f"{app_name} CI ({app_id})"


def app_answers_path(app_path: str) -> str:
    """The Copier answers file of a scaffolded app, relative to the repository root."""

    return f"{app_path.rstrip('/')}/{COPIER_ANSWERS_FILE}"


def workflow_path(app_id: str) -> str:
    return f".github/workflows/{app_id}.yml"


# The port a generated client calls when the workspace has no backend that Prism scaffolded: the first port of the backend range.
DEFAULT_BACKEND_PORT = 8080
BACKEND_BASE_URL_PATTERN = re.compile(r"http://(?:localhost|127\.0\.0\.1):[0-9]{2,5}/?")


def backend_of(app: Mapping[str, Any], apps: Iterable[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    """The backend an app calls: the one its `backend` names, else the first backend Prism scaffolds in the workspace.

    ``None`` when the app calls no backend (its stack is not a client stack), or when the workspace has none to call.
    """

    if app.get("stack") not in BACKEND_CLIENT_STACKS:
        return None
    entries = [dict(item) for item in apps]
    named = app.get("backend")
    if named:
        return next((item for item in entries if item["id"] == named and item.get("stack") == BACKEND_STACK), None)
    return next((item for item in entries if item.get("stack") == BACKEND_STACK and item.get("generation") == GENERATION_SCAFFOLDED), None)


def backend_port_of(app: Mapping[str, Any], apps: Iterable[Mapping[str, Any]], port_of: Mapping[str, int | None]) -> int:
    """The port of the backend an app calls: the backend's own port, else the first port of the backend range.

    A backend that Prism did not scaffold has no remembered port, so a client of it starts from the default and states its
    own address in the answer `backend_base_url`.
    """

    backend = backend_of(app, apps)
    port = port_of.get(str(backend["id"])) if backend is not None else None
    return port if isinstance(port, int) and not isinstance(port, bool) and port > 0 else DEFAULT_BACKEND_PORT


def backend_port_in_workspace(root: Path, app: Mapping[str, Any], apps: Iterable[Mapping[str, Any]]) -> int:
    """``backend_port_of`` for an existing workspace: the ports are those the apps' answers files remember."""

    entries = [dict(item) for item in apps]
    return backend_port_of(app, entries, {str(item["id"]): _remembered_port(root, item) for item in entries if item.get("stack") == BACKEND_STACK})


def _remembered_port(root: Path, app: Mapping[str, Any]) -> int | None:
    answers = read_app_answers(root, str(app["path"])) if app.get("generation") == GENERATION_SCAFFOLDED else None
    port = answers.get("port") if answers else None
    return port if isinstance(port, int) and not isinstance(port, bool) else None


def pack_answers(project: Mapping[str, Any], app: Mapping[str, Any], *, port: int | None, backend_port: int | None = None) -> dict[str, Any]:
    """Every answer an app layer receives: the workspace identity, the app's identity and what derives from its ID.

    ``copier.yml`` derives the same values as defaults, so a raw Copier run agrees with the CLI. An app of a client stack
    also gets ``backend_base_url``, the loopback address of the backend it calls (``backend_port``, else the default port).
    """

    app_id = str(app["id"])
    app_path = str(app["path"]).rstrip("/")
    package = f"{project['package_identifier']}.{app_package_segment(app_id)}"
    name = str(app.get("name") or app_id)
    backend = {"backend_base_url": f"http://localhost:{backend_port or DEFAULT_BACKEND_PORT}"} if app.get("stack") in BACKEND_CLIENT_STACKS else {}
    return {
        **backend,
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
        "ci_workflow_name": ci_workflow_name(name, app_id),
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
    """The remembered answers of a scaffolded app, or ``None`` when its answers file is missing, unreadable or behind a link.

    The path is confined to the workspace first: an answers file that is a symlink or a reparse point, or that sits
    below one, is not read, and the file is opened without following a link.
    """

    try:
        raw = read_confined_bytes(root, app_answers_path(app_path))
        data = (yaml.safe_load(raw) or {}) if raw is not None else None
    except (RefusedPath, OSError, yaml.YAMLError, ValueError, OverflowError):
        return None
    return data if isinstance(data, dict) else None


COMMIT_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/+-]{0,199}")


def layer_answers_problems(recorded: Mapping[str, Any], workspace: Mapping[str, Any], app: Mapping[str, Any], *, approved_source: str) -> list[str]:
    """Why an app layer's saved answers cannot be trusted for an update, as sentences; empty when they can.

    The update runs Copier with `--trust` against each layer's answers file, so a saved answer is as good as code:
    the layer must come from the same approved template source as the workspace, name a plain revision, and carry
    the identity and the derived values that the manifest and the workspace give it. ``app`` is the manifest entry
    (`id`, `name`, `stack`, `path`, `audience`); ``workspace`` holds the workspace layer's saved answers.
    """

    problems: list[str] = []
    label = f"App `{app['id']}`"
    source = recorded.get("_src_path")
    if source != approved_source:
        problems.append(
            f"{label} records the template source `{source}`, which is not the workspace's approved source `{approved_source}`. "
            "An update runs the template of each layer with trust, so every layer must come from the workspace's own source."
        )
    revision = recorded.get("_commit")
    if revision is not None and not (isinstance(revision, str) and COMMIT_PATTERN.fullmatch(revision)):
        problems.append(f"{label} records a template revision that is not a plain tag or commit name.")
    project = {key: workspace.get(key) for key in ("project_name", "project_slug", "package_identifier")}
    if not all(isinstance(value, str) and value for value in project.values()):
        problems.append("The workspace's saved answers do not record its project name, slug and package identifier.")
        return problems
    port = recorded.get("port")
    if not isinstance(port, int) or isinstance(port, bool) or port < 0:
        problems.append(f"{label} records a port that is not a number.")
        return problems
    expected = pack_answers(project, app, port=port)
    # The name and the audience may have changed in the manifest since; they only have to be safe to render.
    for key in ("app_name", "audience"):
        value = recorded.get(key)
        if not isinstance(value, str) or label_problem(value) is not None:
            problems.append(f"{label} records a `{key}` that is not safe to render.")
    if recorded.get("ci_workflow_name") != ci_workflow_name(str(recorded.get("app_name")), str(app["id"])):
        problems.append(f"{label} records a `ci_workflow_name` that is not its app name and ID as `{ci_workflow_name(str(recorded.get('app_name')), str(app['id']))}`.")
    for key in ("prism_layer", "app_id", "app_path"):
        if key not in recorded:
            problems.append(f"{label} records no `{key}`.")
    base_url = recorded.get("backend_base_url")
    if base_url is not None and not (isinstance(base_url, str) and BACKEND_BASE_URL_PATTERN.fullmatch(base_url)):
        problems.append(f"{label} records a `backend_base_url` that is not a loopback address with a port.")
    for key, wanted in expected.items():
        if key in {"app_name", "audience", "ci_workflow_name", "port", "backend_base_url"}:
            continue
        if key in recorded and recorded[key] != wanted:
            problems.append(f"{label} records `{key}: {recorded[key]}`, but its manifest entry and the workspace give `{wanted}`.")
    unknown = sorted(str(key) for key in recorded if key not in {*expected, "backend_base_url", "_src_path", "_commit"})
    if unknown:
        problems.append(f"{label} records answer(s) that no app layer asks: {', '.join(f'`{key}`' for key in unknown)}.")
    return problems


# --- The workspace layer's saved answers ---------------------------------------------

# Every answer the workspace layer asks and Copier saves (`when: false` answers are never saved), and Copier's two private keys.
WORKSPACE_ANSWER_KEYS = frozenset({"_src_path", "_commit", "prism_layer", "project_name", "project_slug", "package_identifier", "description", "stacks", "apps"})
WORKSPACE_APP_KEYS = frozenset({"id", "name", "stack", "path", "audience", "port"})
PROJECT_SLUG_PATTERN = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*")
MAX_PORT = 65535


def workspace_apps_problems(stacks: Any, apps: Any) -> list[str]:
    """Why a workspace layer's `stacks` and `apps` cannot be rendered into its files, as sentences; empty when they can.

    The workspace layer renders each app's ID, name, path, audience and port into Taskfile includes, the compose file,
    the skills and the guidance, so every value follows the safe-value rule. The identifiers an ID derives and the stacks
    are re-derived from the apps and compared, never taken from the file. ``apps`` is the list a saved answers file or
    the manifest gives (`id`, `name`, `stack`, `path`, `audience`, `port`).
    """

    if not isinstance(apps, list):
        return ["The workspace's `apps` must be a list of apps."]
    problems: list[str] = []
    entries: list[dict[str, Any]] = []
    for index, item in enumerate(apps):
        label = f"apps[{index}]"
        if not isinstance(item, dict):
            problems.append(f"`{label}` must be a mapping.")
            continue
        if is_slug(item.get("id")):
            label = f"App `{item['id']}`"
        keys = set(item)
        if keys != WORKSPACE_APP_KEYS:
            missing = sorted(WORKSPACE_APP_KEYS - keys)
            extra = sorted(str(key) for key in keys - WORKSPACE_APP_KEYS)
            detail = (f"; missing {', '.join(missing)}" if missing else "") + (f"; unknown {', '.join(extra)}" if extra else "")
            problems.append(f"{label} must record exactly {', '.join(f'`{key}`' for key in sorted(WORKSPACE_APP_KEYS))}{detail}.")
            continue
        before = len(problems)
        if not is_slug(item["id"]):
            problems.append(f"{label} needs an `id` that is a slug: lowercase letters, digits and single hyphens.")
        if item["stack"] not in PACK_STACKS:
            problems.append(f"{label} records the stack `{item['stack']}`, which has no pack to scaffold.")
        name = item["name"]
        if not isinstance(name, str) or not name or label_problem(name) is not None:
            problems.append(f"{label} records a `name` that is not safe to render.")
        audience = item["audience"]
        if not isinstance(audience, str) or label_problem(audience) is not None:
            problems.append(f"{label} records an `audience` that is not safe to render.")
        path = item["path"]
        if not isinstance(path, str) or not path.rstrip("/"):
            problems.append(f"{label} records a `path` that is not a path.")
        else:
            path_problem = path_segments_problem(path.rstrip("/").split("/"))
            if path_problem is not None:
                problems.append(f"{label} records a `path` that is not safe to render: {path_problem}")
        port = item["port"]
        if not isinstance(port, int) or isinstance(port, bool) or not 0 <= port <= MAX_PORT:
            problems.append(f"{label} records a `port` that is not a port number.")
        if len(problems) == before:
            entries.append({"id": item["id"], "stack": item["stack"], "path": path.rstrip("/"), "generation": GENERATION_SCAFFOLDED})
    if problems:
        return problems
    ids = [entry["id"] for entry in entries]
    if len(set(ids)) != len(ids):
        problems.append("The workspace's `apps` list an app ID twice.")
    problems.extend(validate_scaffold(entries))
    derived = sorted({entry["stack"] for entry in entries})
    if stacks != derived:
        problems.append(f"The workspace records `stacks: {stacks}`, but its apps give `{derived}`.")
    return problems


def workspace_answers_problems(recorded: Mapping[str, Any]) -> list[str]:
    """Why the workspace layer's saved answers cannot be trusted for an update, as sentences; empty when they can.

    The update runs Copier with `--trust` against this file as well, and what it records is rendered into the root files
    (the Taskfile, the compose file, the skills) and, through the layer it selects, into code. So the file must select
    the workspace layer, name a plain template source and revision, and hold only the workspace layer's own answers,
    each safe to render. An answer that only an app layer asks (`app_package` and the like) has no place here: it is
    refused, not ignored.
    """

    problems: list[str] = []
    where = f"The workspace's {COPIER_ANSWERS_FILE}"
    layer = recorded.get("prism_layer", WORKSPACE_LAYER)
    if layer != WORKSPACE_LAYER:
        problems.append(f"{where} selects the layer `{layer}`; the workspace layer must select `{WORKSPACE_LAYER}`.")
    source = recorded.get("_src_path")
    if not isinstance(source, str) or not source or source != source.strip() or source.startswith("-") or any(ord(character) < 32 or ord(character) == 127 for character in source):
        problems.append(f"{where} records a template source that is not a plain path or URL.")
    revision = recorded.get("_commit")
    if revision is not None and not (isinstance(revision, str) and COMMIT_PATTERN.fullmatch(revision)):
        problems.append(f"{where} records a template revision that is not a plain tag or commit name.")
    name = recorded.get("project_name")
    if not isinstance(name, str) or not name or label_problem(name) is not None:
        problems.append(f"{where} records a `project_name` that is not safe to render: use {LABEL_RULE}.")
    slug = recorded.get("project_slug")
    if not isinstance(slug, str) or not PROJECT_SLUG_PATTERN.fullmatch(slug):
        problems.append(f"{where} records a `project_slug` that is not lowercase letters, digits and single hyphens.")
    package = recorded.get("package_identifier")
    if not isinstance(package, str) or not PACKAGE_IDENTIFIER_PATTERN.fullmatch(package) or any(part in RESERVED_IDENTIFIERS for part in package.split(".")):
        problems.append(f"{where} records a `package_identifier` that is not a reverse-domain name without Kotlin or Java keywords.")
    if "description" in recorded and description_problem(recorded["description"]) is not None:
        problems.append(f"{where} records a `description` that is not safe to render: use {DESCRIPTION_RULE}.")
    unknown = sorted(str(key) for key in recorded if key not in WORKSPACE_ANSWER_KEYS)
    if unknown:
        problems.append(f"{where} records answer(s) that the workspace layer does not ask: {', '.join(f'`{key}`' for key in unknown)}.")
    problems.extend(f"{where}: {problem}" for problem in workspace_apps_problems(recorded.get("stacks", []), recorded.get("apps", [])))
    return problems


def taken_ports(root: Path, apps: Iterable[Mapping[str, Any]]) -> set[int]:
    """The ports the scaffolded apps of a workspace hold, read from their answers files."""

    ports: set[int] = set()
    for app in apps:
        if app.get("generation") != GENERATION_SCAFFOLDED:
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
        return {"level": "experimental", "caveat": "The macOS CI job builds and tests the generated iOS app; no local macOS build is part of the evidence, and a physical device cannot use the local development sign-in."}
    if stack == "nextjs-web":
        return {
            "level": "provisional",
            "caveat": "Generated web apps are verified by lint, typecheck, unit and component tests and the build, with a mocked backend; sign-in against a running backend is checked by hand, and hosting is the project owner's choice (see the deployment skill).",
        }
    if stack == "python-agent-service":
        return {
            "level": "provisional",
            "caveat": "The generated agent service is verified by lint, typecheck, tests and an evaluation set that run the fake provider, and by a local run against the backend's dev identity; the Claude adapter is tested against a stub only and needs a live check with your own API key.",
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
    allowed = {"id", "name", "stack", "path", "repository", "remote", "audience", "generation", "backend"}
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
        if item.get("backend") is not None:
            entry["backend"] = item["backend"]
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
        if stack == "ios-swiftui" and app_module_name(app_id).casefold() in IOS_SYSTEM_MODULES:
            errors.append(
                f"App `{app_id}` cannot be scaffolded as an iOS app: its Swift module `{app_module_name(app_id)}` has the name of a system module, "
                "so `import` and the test target would find the framework instead of the app. Choose another ID, such as `mobile-ios`."
            )
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
