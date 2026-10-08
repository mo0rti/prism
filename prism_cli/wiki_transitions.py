"""Read-only lifecycle transition preflight facts.

The evaluator describes the lifecycle actions that a generated project can ask
an agent to perform.  It only reads source files and generated instructions;
it never edits a wiki, invokes an agent, or claims that a copied request ran.
"""

from __future__ import annotations

import hashlib
import json
import re
import stat
import time
from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path
from threading import Lock, RLock
from typing import Any, Callable, Iterable, Iterator, Mapping
from urllib.parse import unquote, urlsplit

from prism_cli.app_model import (
    CAPABILITY_HAS_UI,
    GENERATED_PLATFORM_DIRS,
    MANIFEST_SCHEMA_VERSION,
    WorkspaceModel,
    api_surface_without_api_app_message,
    retired_in_scope_message,
)
from prism_cli.fs_safety import reparse_kind
from prism_cli.qa_checks import qa_fail_checks, qa_pass_checks, qa_verify_checks
from prism_cli.roles import RolePredicate
from prism_cli.status import IGNORED_INTAKE_FILES
from prism_cli.wiki_lint import WIKI_BLOCKER_CODES, WikiDiagnostic, WikiLintResult, _wiki_path_references, lint_wiki
from prism_cli.wiki_model import (
    DESIGN_OWNERS,
    FEATURE_STATUS_ORDER,
    OWNER_BY_STATUS,
    VALID_ADVISORY_REVIEW_STATES,
    VALID_FEATURE_OWNERS,
    VALID_FEATURE_STATUSES,
    VALID_OPEN_QUESTION_OWNERS,
    DesignTracks,
    FeaturePage,
    active_scope,
    api_surface_declared,
    app_stages,
    clean_cell,
    contract_page_citation,
    design_owner,
    extract_markdown_links,
    feature_id_from_path,
    initial_design_tracks,
    minimum_stage,
    normalize_feature_id,
    parse_advisory_required_actions,
    parse_app_revalidation,
    parse_criteria,
    parse_delivery_rows,
    parse_design_tracks,
    parse_open_question_rows,
    parse_revalidation,
    read_app_requirement_pages,
    read_feature_evidence,
    read_feature_pages,
    read_wiki_pages,
    resolve_relative_markdown_link,
    section_text,
    status_rank,
    technical_design_problems,
    ui_apps,
    within_wiki_read_scope,
)
from prism_cli.wiki_paths import decoded_link_path, resolve_to_path
from prism_cli.wiki_query import build_envelope
from prism_cli.workspace import (
    COPIER_ANSWERS_FILE,
    MANIFEST_FILE,
    WorkspaceInspection,
    detect_workspace_kind,
    inspect_workspace,
)


TRANSITION_SCHEMA_VERSION = 2
TRANSITION_CAPABILITY_VERSION = 3
SUPPORTED_ACTION = "po-handoff"
SUPPORTED_SOURCE_STATUS = "specified"  # the po-handoff action's source and target
SUPPORTED_SOURCE_OWNER = "po"
SUPPORTED_TARGET_STATUS = "ready-for-design"

# The packages whose actions are enabled. A row of another package is registered but answers `action_unavailable` in the
# service and in discovery until its package lands and adds its ID here.
ENABLED_PACKAGES = frozenset({"D1", "D2", "D3"})

DESIGN_OWNER = "D"  # the owner symbol that resolves to `designer` or `tech-lead` from the feature's scope
MINIMUM = "minimum"  # the status or owner is the minimum over the app stages after the action
UNCHANGED = "unchanged"

MODE_HUMAN_DIRECT = "HD"
MODE_AGENT_PROPOSED = "AP"


@dataclass(frozen=True)
class ActionSpec:
    """One lifecycle action of the registry (CONTRACTS 2.3 and 2.8).

    `sources` are the (status, owner) pairs the action starts from; the owner `D` resolves from the feature's scope.
    `target_status` and `target_owner` are concrete values, or `minimum` (the minimum over the app stages after the
    action) or `unchanged`. `rows` are the contract rows the action covers; an action with two rows (`dev-done` is F8
    and F9) picks its row from the target it computes. `roles_all` and `roles_any` are the role predicate, in which `D` is
    the design owner. `package` is the work package that enables the action.
    """

    action: str
    command: str
    sources: tuple[tuple[str, str], ...]
    target_status: str | None
    target_owner: str | None
    roles_all: tuple[str, ...]
    modes: tuple[str, ...]
    package: str
    rows: tuple[str, ...]
    per_app: bool = False
    subject: str = "feature"  # feature | bug | operation
    roles_any: tuple[str, ...] = ()
    # Extra arguments the command takes for this action, as discovery shows them.
    arguments: str = ""
    # Whether the copy-only transition preflight lists the action (it needs generated command files).
    copy: bool = False

    @property
    def enabled(self) -> bool:
        return self.package in ENABLED_PACKAGES

    @property
    def available(self) -> bool:
        """Whether the work package that owns the action has landed; an unavailable action answers `action_unavailable`."""

        return self.enabled

    @property
    def unavailable_reason(self) -> str | None:
        if self.available:
            return None
        return f"The action `{self.action}` belongs to work package {self.package}, which has not landed in this Prism version."

    @property
    def source_pairs(self) -> tuple[tuple[str, str], ...]:
        return self.sources

    @property
    def human_direct(self) -> bool:
        return MODE_HUMAN_DIRECT in self.modes

    def resolved_sources(self, design_owner: str) -> tuple[tuple[str, str], ...]:
        return tuple((status, design_owner if owner == DESIGN_OWNER else owner) for status, owner in self.sources)

    def resolved_target(self, design_owner: str) -> tuple[str | None, str | None]:
        owner = design_owner if self.target_owner == DESIGN_OWNER else self.target_owner
        return self.target_status, owner

    def role_predicate(self, context: Mapping[str, Any] | None = None) -> RolePredicate | None:
        """The roles that approve this action in `context`, or ``None`` when the action is not gated there.

        See `prism_cli.roles.required_roles` for the context keys.
        """

        ctx = dict(context or {})
        if self.action == "scope-edit":
            # Ungated before `ready-for-dev`; gated for `po` from there on.
            status = ctx.get("status")
            if isinstance(status, str) and status in FEATURE_STATUS_ORDER and status_rank(status) < status_rank("ready-for-dev"):
                return None
        if self.action == "operation-repair":
            original = ctx.get("original_action")
            if not isinstance(original, str) or original == self.action:
                return None
            spec = ACTION_BY_ID.get(original)
            return spec.role_predicate({**ctx, "action": original}) if spec is not None else None
        if self.action == "bug-close" and ctx.get("disposition") == "duplicate":
            return RolePredicate(all_of=("qa",))
        owner = _design_owner_from_context(ctx)
        if owner is None:
            # The scope is not known (no model, root or resolved owner): either design role may approve, and the write itself
            # still has to hand the feature to the design owner of its scope (`design_owner_mismatch`).
            roles_all = [role for role in self.roles_all if role != DESIGN_OWNER]
            roles_any = list(DESIGN_OWNERS) if DESIGN_OWNER in self.roles_all else [role for role in self.roles_any]
            return RolePredicate(all_of=tuple(roles_all), any_of=tuple(roles_any))
        roles_all = [owner if role == DESIGN_OWNER else role for role in self.roles_all]
        completes = ctx.get("completes")
        if self.action == "design-handoff" and completes:
            # A track the handoff completes needs the role of that track on top of the design owner (D2 supplies `completes`).
            for track, role in (("ui", "designer"), ("technical", "tech-lead")):
                if track in completes and role not in roles_all:
                    roles_all.append(role)
        roles_any = [owner if role == DESIGN_OWNER else role for role in self.roles_any]
        return RolePredicate(all_of=tuple(roles_all), any_of=tuple(roles_any))


def _design_owner_from_context(context: Mapping[str, Any]) -> str | None:
    """The design owner the context resolves, or ``None`` when it names no model, root or resolved owner."""

    explicit = context.get("design_owner")
    if explicit in DESIGN_OWNERS:
        return str(explicit)
    model = context.get("model")
    if model is None and context.get("root") is not None:
        try:
            model = inspect_workspace(Path(context["root"])).model
        except (OSError, ValueError, TypeError):
            model = None
    if model is None:
        return None
    apps = context.get("apps")
    return design_owner(apps if isinstance(apps, (list, tuple, set, frozenset)) else (), model)


def _spec(
    action: str,
    command: str,
    sources: tuple[tuple[str, str], ...],
    target: tuple[str | None, str | None],
    roles: tuple[str, ...],
    modes: tuple[str, ...],
    package: str,
    rows: tuple[str, ...],
    **extra: Any,
) -> ActionSpec:
    return ActionSpec(action, command, sources, target[0], target[1], roles, modes, package, rows, **extra)


_D = DESIGN_OWNER
_AP = (MODE_AGENT_PROPOSED,)
_HD_AP = (MODE_HUMAN_DIRECT, MODE_AGENT_PROPOSED)
_DESIGN_SOURCES = (("ready-for-design", _D), ("in-design", _D))
_DEV_SOURCES = (("ready-for-dev", "dev"), ("in-dev", "dev"))
_QA_SOURCES = (("in-dev", "dev"), ("ready-for-qa", "qa"), ("in-qa", "qa"))
_RELEASE_SOURCES = (("in-dev", "dev"), ("ready-for-qa", "qa"), ("in-qa", "qa"), ("ready-for-release", "release"))
_BUG_ACTIVE = (("open", "dev"), ("in-fix", "dev"), ("fixed", "qa"), ("verified", "release"))

ACTION_SPECS: tuple[ActionSpec, ...] = (
    # Feature transitions (CONTRACTS 2.3).
    _spec("po-specify", "po-specify", (("raw", "po"),), ("specified", "po"), ("po",), _AP, "D1", ("F1",), copy=True),
    _spec("po-handoff", "po-handoff", (("specified", "po"),), ("ready-for-design", _D), ("po",), _HD_AP, "D1", ("F2",), copy=True),
    _spec("design-start", "design-start", (("ready-for-design", _D),), ("in-design", _D), (_D,), _HD_AP, "D2", ("F3",), copy=True),
    _spec("design-ui-done", "design-ui-done", _DESIGN_SOURCES, ("in-design", _D), ("designer",), _AP, "D2", ("F4",), copy=True),
    _spec("tech-design-done", "tech-design-done", _DESIGN_SOURCES, ("in-design", _D), ("tech-lead",), _AP, "D2", ("F5",), copy=True),
    _spec("design-handoff", "design-handoff", _DESIGN_SOURCES, ("ready-for-dev", "dev"), (_D,), _AP, "D2", ("F6",), copy=True),
    _spec("dev-start", "dev-start", (("ready-for-dev", "dev"),), ("in-dev", "dev"), ("dev",), _HD_AP, "D1", ("F7",), copy=True),
    _spec("dev-done", "dev-done", _DEV_SOURCES, (MINIMUM, MINIMUM), ("dev",), _AP, "D1", ("F8", "F9"), per_app=True, copy=True),
    _spec("dev-return-spec", "feature-reopen", _DEV_SOURCES, ("specified", "po"), ("dev",), _AP, "D2", ("F10",), arguments="specified", copy=True),
    _spec("dev-return-design", "feature-reopen", _DEV_SOURCES, ("in-design", _D), ("dev",), _AP, "D2", ("F11",), arguments="in-design", copy=True),
    _spec("qa-verify", "qa-verify", _QA_SOURCES, (MINIMUM, MINIMUM), ("qa",), _AP, "D3", ("F12",), per_app=True, copy=True),
    _spec("qa-pass", "qa-pass", _QA_SOURCES, (MINIMUM, MINIMUM), ("qa",), _AP, "D3", ("F13", "F14"), per_app=True, copy=True),
    _spec("qa-fail", "qa-fail", (*_QA_SOURCES, ("ready-for-release", "release")), ("in-dev", "dev"), ("qa",), _AP, "D3", ("F15",), per_app=True, copy=True),
    _spec("qa-return-spec", "feature-reopen", _RELEASE_SOURCES, ("specified", "po"), ("qa",), _AP, "D3", ("F16",), arguments="specified"),
    _spec("qa-return-design", "feature-reopen", _RELEASE_SOURCES, ("in-design", _D), ("qa",), _AP, "D3", ("F17",), arguments="in-design"),
    _spec("release-done", "release-done", _RELEASE_SOURCES, (MINIMUM, MINIMUM), ("release",), _AP, "D4", ("F18", "F19"), per_app=True),
    _spec("release-return-dev", "release-done", _RELEASE_SOURCES, ("in-dev", "dev"), ("release",), _AP, "D4", ("F20",), per_app=True, arguments="--return in-dev"),
    _spec("release-rollback", "release-done", (*_RELEASE_SOURCES, ("released", "none")), (UNCHANGED, UNCHANGED), ("release",), _AP, "D4", ("F21",), per_app=True, arguments="--rollback REL-XXX"),
    _spec("release-redeploy", "release-done", (*_RELEASE_SOURCES, ("released", "none")), (UNCHANGED, UNCHANGED), ("release",), _AP, "D4", ("F22",), per_app=True, arguments="--redeploy REL-XXX"),
    _spec("reopen-spec", "feature-reopen", (("released", "none"),), ("specified", "po"), ("po",), _AP, "D4", ("F23",), arguments="specified"),
    _spec("reopen-design", "feature-reopen", (("released", "none"),), ("in-design", _D), (_D,), _AP, "D4", ("F24",), arguments="in-design"),
    _spec("reopen-dev", "feature-reopen", (("released", "none"),), ("in-dev", "dev"), ("dev",), _AP, "D4", ("F25",), arguments="in-dev"),
    _spec(
        "scope-edit",
        "feature-scope",
        (("ready-for-dev", "dev"), ("in-dev", "dev"), ("ready-for-qa", "qa"), ("in-qa", "qa"), ("ready-for-release", "release"), ("released", "none")),
        (MINIMUM, MINIMUM),
        ("po",),
        _AP,
        "D1",
        ("F26",),
    ),
    _spec("operation-repair", "operation-repair", (), (UNCHANGED, UNCHANGED), (), (MODE_HUMAN_DIRECT,), "D1", ("F27",), subject="operation"),
    # Bug transitions (CONTRACTS 2.8). A bug has no feature-style source pair for creation.
    _spec("bug-open", "bug-update", (), ("open", "dev"), ("qa",), _AP, "D3", ("B1",), subject="bug"),
    _spec("bug-triage", "bug-update", (("open", "dev"),), (UNCHANGED, UNCHANGED), (), _AP, "D3", ("B2",), subject="bug", roles_any=("dev", "qa"), arguments="triage"),
    _spec("bug-scope", "bug-update", (("open", "dev"), ("in-fix", "dev"), ("fixed", "qa"), ("verified", "release")), (UNCHANGED, UNCHANGED), ("qa",), _AP, "D3", ("B3",), subject="bug", arguments="scope"),
    _spec("bug-start", "bug-update", (("open", "dev"),), ("in-fix", "dev"), ("dev",), _AP, "D3", ("B4",), subject="bug", arguments="in-fix"),
    _spec("bug-fixed", "bug-update", (("in-fix", "dev"),), ("fixed", "qa"), ("dev",), _AP, "D3", ("B5",), subject="bug", arguments="fixed"),
    _spec("bug-verify", "bug-update", (("fixed", "qa"),), ("verified", "release"), ("qa",), _AP, "D3", ("B6",), subject="bug", arguments="verified"),
    _spec("bug-reverify", "bug-update", (("verified", "release"),), (UNCHANGED, UNCHANGED), ("qa",), _AP, "D3", ("B7",), subject="bug", arguments="reverify"),
    _spec("bug-reject", "bug-update", (("fixed", "qa"), ("verified", "release")), ("in-fix", "dev"), ("qa",), _AP, "D3", ("B8",), subject="bug", arguments="reject"),
    _spec("bug-close", "bug-update", _BUG_ACTIVE, ("closed", "none"), ("po",), _AP, "D3", ("B9", "B10", "B11"), subject="bug", arguments="closed"),
    _spec("bug-defer", "bug-update", _BUG_ACTIVE[:3], (UNCHANGED, UNCHANGED), ("po",), _AP, "D3", ("B12",), subject="bug", arguments="defer"),
    _spec("bug-reopen", "bug-update", (("closed", "none"),), ("open", "dev"), ("po",), _AP, "D3", ("B13",), subject="bug", arguments="open"),
    _spec("bug-release", "bug-update", (("verified", "release"),), ("released", "none"), ("release",), _AP, "D4", ("B14",), subject="bug"),
)
ACTION_BY_ID = {spec.action: spec for spec in ACTION_SPECS}
FEATURE_ACTIONS = tuple(spec.action for spec in ACTION_SPECS if spec.subject == "feature")
# The actions the copy-only transition preflight lists: enabled actions that have generated command files.
SUPPORTED_ACTIONS = tuple(spec.action for spec in ACTION_SPECS if spec.enabled and spec.copy)


_FEATURE_REVALIDATION_ORDER = ("specification", "design", "technical-design")
_TRACK_KEYS_ALLOWED = frozenset({"design-tracks", "design-reaffirm"})


@dataclass(frozen=True)
class WriteScope:
    """What a lifecycle action may change on the feature page and elsewhere (CONTRACTS 2.5).

    This is the one table the board's front matter, body and revalidation allowlists read. A key or section outside it is
    refused with `lifecycle_frontmatter_scope` or `lifecycle_body_scope`, a page folder outside it with `lifecycle_write_scope`.
    """

    # Feature front matter keys the action may change.
    frontmatter: frozenset[str]
    # Feature body sections (`## heading`) the action may change.
    sections: frozenset[str]
    # Wiki folders of other pages the action may write (linked requirement and API contract pages).
    pages: tuple[str, ...] = ()
    # Feature revalidation domains the action may clear when its checks pass.
    clears: frozenset[str] = frozenset()
    # Per-app revalidation domains the action clears for the apps it names.
    clears_app: frozenset[str] = frozenset()
    # Feature revalidation domains a return route sets, and per-app domains it sets for every app of the scope.
    sets: frozenset[str] = frozenset()
    sets_app: frozenset[str] = frozenset()


_BASE_KEYS = frozenset({"status", "owner"})
_PAGE_SECTIONS = frozenset({"Summary", "User story", "Acceptance criteria", "Open questions", "App scope", "Design", "Related features", "API surface", "Board review summary"})
_EVIDENCE_PAGE_SECTIONS = frozenset({"Delivery evidence", "QA verification", "Release", "Evidence history"})
_LINKED_PAGES = ("knowledge/wiki/app-requirements/", "knowledge/wiki/api-contracts/")
_BUG_PAGES = "knowledge/wiki/bugs/"

WRITE_SCOPES: dict[str, WriteScope] = {
    # `po-specify` writes the page body but no evidence: the evidence sections exist and stay empty (checked separately).
    "po-specify": WriteScope(_BASE_KEYS | {"criteria-high-water"}, _PAGE_SECTIONS | _EVIDENCE_PAGE_SECTIONS),
    "po-handoff": WriteScope(_BASE_KEYS | {"advisory-review", "advisory-skip-reason", "revalidation"}, frozenset(), clears=frozenset({"specification"})),
    "design-start": WriteScope(_BASE_KEYS | _TRACK_KEYS_ALLOWED, frozenset()),
    "design-ui-done": WriteScope(_BASE_KEYS | _TRACK_KEYS_ALLOWED, frozenset({"Design"}), ("knowledge/wiki/design/",)),
    "tech-design-done": WriteScope(
        _BASE_KEYS | _TRACK_KEYS_ALLOWED, frozenset({"Design"}), ("knowledge/wiki/technical-design/", "knowledge/wiki/api-contracts/")
    ),
    "design-handoff": WriteScope(
        _BASE_KEYS | {"revalidation"} | _TRACK_KEYS_ALLOWED,
        frozenset({"Design"}),
        ("knowledge/wiki/design/", "knowledge/wiki/technical-design/", "knowledge/wiki/app-requirements/", "knowledge/wiki/api-contracts/"),
        clears=frozenset({"design", "technical-design"}),
    ),
    "dev-start": WriteScope(_BASE_KEYS, frozenset()),
    "dev-done": WriteScope(
        _BASE_KEYS | {"app-revalidation"},
        frozenset({"Delivery evidence"}),
        _LINKED_PAGES,
        clears_app=frozenset({"implementation", "tests"}),
    ),
    # The returns from implementation archive the evidence of every app and send the feature back (CONTRACTS 2.5, 2.6, 2.7).
    "dev-return-spec": WriteScope(
        _BASE_KEYS | {"revalidation", "app-revalidation"} | _TRACK_KEYS_ALLOWED,
        frozenset({"Delivery evidence", "QA verification", "Release", "Evidence history"}),
        _LINKED_PAGES,
        sets=frozenset({"specification", "design", "technical-design"}),
        sets_app=frozenset({"implementation", "tests", "qa", "release"}),
    ),
    "dev-return-design": WriteScope(
        _BASE_KEYS | {"revalidation", "app-revalidation"} | _TRACK_KEYS_ALLOWED,
        frozenset({"Delivery evidence", "QA verification", "Release", "Evidence history"}),
        _LINKED_PAGES,
        sets=frozenset({"design", "technical-design"}),
        sets_app=frozenset({"implementation", "tests", "qa", "release"}),
    ),
    "scope-edit": WriteScope(
        _BASE_KEYS | {"apps", "app-revalidation", "criteria-high-water"},
        frozenset({"App scope", "Acceptance criteria", "Delivery evidence", "QA verification", "Release", "Evidence history"}),
    ),
    # QA (CONTRACTS 2.5). A new bug page may accompany the three QA actions (B1); the bug folder is the one other page they write.
    "qa-verify": WriteScope(_BASE_KEYS, frozenset({"QA verification", "Open questions"}), (_BUG_PAGES,)),
    "qa-pass": WriteScope(
        _BASE_KEYS | {"app-revalidation"},
        frozenset({"QA verification", "Release", "Open questions"}),
        (_BUG_PAGES,),
        clears_app=frozenset({"qa"}),
    ),
    "qa-fail": WriteScope(
        _BASE_KEYS | {"app-revalidation"},
        frozenset({"Delivery evidence", "QA verification", "Release", "Evidence history"}),
        (*_LINKED_PAGES, _BUG_PAGES),
    ),
    # The routes back from QA reset the design tracks and both revalidation lists (CONTRACTS 2.6, 3.1).
    "qa-return-spec": WriteScope(
        _BASE_KEYS | {"revalidation", "app-revalidation"} | _TRACK_KEYS_ALLOWED,
        frozenset({"Delivery evidence", "QA verification", "Release", "Evidence history"}),
        _LINKED_PAGES,
        sets=frozenset({"specification", "design", "technical-design"}),
        sets_app=frozenset({"implementation", "tests", "qa", "release"}),
    ),
    "qa-return-design": WriteScope(
        _BASE_KEYS | {"revalidation", "app-revalidation"} | _TRACK_KEYS_ALLOWED,
        frozenset({"Delivery evidence", "QA verification", "Release", "Evidence history"}),
        _LINKED_PAGES,
        sets=frozenset({"design", "technical-design"}),
        sets_app=frozenset({"implementation", "tests", "qa", "release"}),
    ),
}
# The actions that return a feature to an earlier status: they set revalidation domains rather than clear them, and a retired
# app in the scope does not block them (CONTRACTS 2.2).
RETURN_ROUTE_ACTIONS = frozenset(
    {"dev-return-spec", "dev-return-design", "qa-return-spec", "qa-return-design", "reopen-spec", "reopen-design", "reopen-dev"}
)
# The actions that stay valid for a feature whose scope lists a retired app: the scope edit that removes it and the routes that
# send the feature back (CONTRACTS 2.2).
RETIRED_ALLOWED_ACTIONS = RETURN_ROUTE_ACTIONS | {"scope-edit"}


def lookup_action(action: str) -> ActionSpec | None:
    """The registry row for a lifecycle action name, or ``None`` when the name is not registered.

    This is the one lookup the board and discovery use: it returns the same `ActionSpec` whether or not the action is enabled
    (`spec.enabled`); a disabled action is refused with `action_unavailable`.
    """

    return ACTION_BY_ID.get(action)


def actions_of_command(command: str) -> tuple[ActionSpec, ...]:
    """Every registry row of a command (`feature-reopen` maps to several actions)."""

    return tuple(spec for spec in ACTION_SPECS if spec.command == command)


def capability_marker(spec: ActionSpec) -> str:
    """The generated-instruction marker of the command of `spec`: `v2` for a command that existed before the full lifecycle, `v1` for a new one."""

    return f"prism:{spec.command}-contract:v{_COMMAND_CONTRACT_VERSION.get(spec.command, 1)}"


# The commands of the 0.6 workflow carry contract version 2; commands the full lifecycle adds start at version 1.
_COMMAND_CONTRACT_VERSION = {
    "po-specify": 2,
    "po-handoff": 2,
    "design-start": 2,
    "design-handoff": 2,
    "dev-start": 2,
    "dev-done": 2,
    "feature-reopen": 2,
    "feature-scope": 2,
}

# The PO-handoff surface files; every other action's surfaces are declared below.

CAPABILITY_FILES = {
    "codex": Path(".agents/skills/po-handoff/SKILL.md"),
    "claude": Path(".claude/commands/po-handoff.md"),
}

_ACTION_SURFACE_PATHS: dict[str, dict[str, Path]] = {
    spec.action: {
        "codex": Path(f".agents/skills/{spec.command}/SKILL.md"),
        "claude": Path(f".claude/commands/{spec.command}.md"),
    }
    for spec in ACTION_SPECS
    if spec.subject == "feature"
}
_ACTION_SURFACE_PATHS[SUPPORTED_ACTION] = CAPABILITY_FILES

_ACTION_INVOCATIONS = {
    spec.action: {
        "codex": (
            f"$feature-reopen F-XXX {spec.arguments}"
            if spec.command == "feature-reopen"
            else f"${spec.command} F-XXX"
        ),
        "claude": (
            f"/feature-reopen F-XXX {spec.arguments}"
            if spec.command == "feature-reopen"
            else f"/{spec.command} F-XXX"
        ),
    }
    for spec in ACTION_SPECS
    if spec.subject == "feature"
}
_ACTION_MARKERS = {
    spec.action: {
        "codex": ("$" + spec.command, "F-XXX", capability_marker(spec)),
        "claude": ("/" + spec.command, "F-XXX", capability_marker(spec)),
    }
    for spec in ACTION_SPECS
    if spec.subject == "feature"
}

def _capability_paths() -> tuple[Path, ...]:
    """Return every generated instruction path that can affect capabilities."""

    paths: set[Path] = set()
    for action, surface_paths in _ACTION_SURFACE_PATHS.items():
        # A registered action whose work package has not landed is unavailable whatever its command files say.
        spec = ACTION_BY_ID.get(action)
        if spec is not None and not spec.enabled:
            continue
        paths.update(surface_paths.values())
    return tuple(sorted(paths, key=lambda path: path.as_posix()))

_WATCH_FILES = (MANIFEST_FILE, COPIER_ANSWERS_FILE)
_WATCH_WIKI_DIR = Path("knowledge/wiki")
_WATCH_QUEUE_DIRS = (
    Path("knowledge/intake/pending"),
    Path("knowledge/intake/quarantined"),
)
_OBSERVED_AT_CACHE_LIMIT = 256
_OBSERVED_AT_BY_FINGERPRINT: OrderedDict[str, str] = OrderedDict()
_OBSERVED_AT_LOCK = Lock()
# ``evaluate_transition_summaries`` checks the required wiki files once per call, not once per feature.
_REQUIRED_WIKI_FILE_READS: ContextVar[dict[Path, bool] | None] = ContextVar("prism_required_wiki_file_reads", default=None)
_PLACEHOLDER_PATTERNS = (
    re.compile(r"^one paragraph\b", re.IGNORECASE),
    re.compile(r"\[what this feature does, why it exists", re.IGNORECASE),
    re.compile(r"\[persona from personas/", re.IGNORECASE),
    re.compile(r"\[business outcome\]", re.IGNORECASE),
    re.compile(r"condition \d+\s*\(testable, unambiguous\)", re.IGNORECASE),
)
_APP_PLACEHOLDER = re.compile(
    r"^\[what\s+[a-z][a-z0-9-]*\s+must\s+implement,\s+or\s+['\"]not in scope['\"]\]$",
    re.IGNORECASE,
)
_HARD_IDENTITY_DIAGNOSTIC_CODES = {
    "invalid-copier-answers-shape",
    "invalid-copier-answers-yaml",
    "invalid-min-prism-cli-version",
    "invalid-workspace-manifest-project",
    "invalid-workspace-manifest-provenance",
    "invalid-workspace-manifest-schema",
    "invalid-workspace-manifest-shape",
    "invalid-workspace-manifest-surfaces",
    "invalid-workspace-manifest-paths",
    "manifest-answers-drift",
    "manifest-filesystem-drift",
    "minimum-prism-cli-version-not-met",
    "missing-manifest-path",
    "readable-workspace-manifest",
    "unreadable-copier-answers",
    "unreadable-workspace-manifest",
    "unsafe-copier-answers",
    "invalid-workspace-manifest-yaml",
    "unsupported-workspace-manifest-schema",
}


@dataclass(frozen=True)
class TransitionEvaluation:
    """Shared transition facts for a single read snapshot."""

    capability: dict[str, Any]
    transitions_by_path: dict[str, dict[str, Any]]
    transitions_list_by_path: dict[str, list[dict[str, Any]]]
    diagnostics: list[WikiDiagnostic]
    sources: list[str]


class FingerprintCache:
    """Reuse per-file content hashes between scans of an unchanged workspace.

    Only the shared graph refresh uses it, from the change poller and from the refresh
    that follows an apply or recover request; it feeds the graph snapshot and its
    version, never a stale-preview or apply decision, and no other request path uses
    it. A hash is reused when the file's ``(st_mtime_ns, st_size)`` is unchanged and the file
    was already older than the racy window when it was hashed, so an edit that
    lands in the same timestamp tick as the hash cannot hide behind it. An edit
    that keeps both size and modification time (a restored timestamp, ``rsync
    -t``) is only noticed by the full rehash that runs at least every
    ``FULL_REHASH_SECONDS``. The poller is a trigger: preview and apply compare
    content digests again before they write.
    """

    RACY_WINDOW_NS = 2_000_000_000
    FULL_REHASH_SECONDS = 60.0

    def __init__(
        self,
        *,
        wall_clock_ns: Callable[[], int] = time.time_ns,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._wall_clock_ns = wall_clock_ns
        self._monotonic = monotonic
        self._lock = RLock()
        self._entries: dict[str, tuple[int, int, str]] = {}
        self._seen: dict[str, tuple[int, int, str]] = {}
        self._last_full_rehash: float | None = None
        self._rehash_everything = True

    @contextmanager
    def scan(self) -> Iterator["FingerprintCache"]:
        """Bracket one fingerprint pass; files the pass did not visit are forgotten."""

        with self._lock:
            now = self._monotonic()
            last = self._last_full_rehash
            self._rehash_everything = last is None or now < last or now - last >= self.FULL_REHASH_SECONDS
            if self._rehash_everything:
                self._last_full_rehash = now
            self._seen = {}
            try:
                yield self
            finally:
                self._entries = self._seen
                self._seen = {}

    def file_fingerprint(self, path: Path, info: Any = None) -> str:
        """Return ``_file_fingerprint(path)``, reusing the last hash when the file is unchanged."""

        if info is None:
            try:
                info = path.stat()
            except (OSError, RuntimeError):
                return _file_fingerprint(path)
        key = str(path)
        modified_ns = info.st_mtime_ns
        size = info.st_size
        cached = self._entries.get(key)
        if not self._rehash_everything and cached is not None and cached[0] == modified_ns and cached[1] == size:
            self._seen[key] = cached
            return cached[2]
        hashed_at_ns = self._wall_clock_ns()
        digest = _file_fingerprint(path)
        if digest != "unreadable" and hashed_at_ns - modified_ns > self.RACY_WINDOW_NS:
            self._seen[key] = (modified_ns, size, digest)
        return digest


def workspace_fingerprint(root: Path, *, cache: FingerprintCache | None = None) -> tuple[tuple[str, str], ...]:
    """Fingerprint files and metadata consumed by graph and transition reads.

    The tuple shape is kept compatible with the existing graph server watcher.
    Content is hashed for files; queue entries and app directories retain
    the existing name/type invalidation semantics.  Capability instructions are
    included so changing or removing a generated command invalidates a snapshot.

    Every file is hashed unless a ``FingerprintCache`` is passed. The result is
    identical either way; only the shared graph refresh (the change poller and the
    refresh after an apply or recover request) passes one.
    """

    if cache is None:
        return _workspace_fingerprint(root, None)
    with cache.scan():
        return _workspace_fingerprint(root, cache)


def _workspace_fingerprint(root: Path, cache: FingerprintCache | None) -> tuple[tuple[str, str], ...]:
    def content(path: Path, info: Any = None) -> str:
        return _file_fingerprint(path) if cache is None else cache.file_fingerprint(path, info)

    workspace_root = root.expanduser().resolve()
    entries: list[tuple[str, str]] = [("today", date.today().isoformat())]

    for relative in _WATCH_FILES:
        path = workspace_root / relative
        # A link at the place of a watched file is recorded as a link and never followed or hashed.
        kind = "link" if _is_link(path) else _path_kind(path)
        entries.append((relative, content(path) if kind == "file" else kind))

    wiki_root = workspace_root / _WATCH_WIKI_DIR
    wiki_kind = _path_kind(wiki_root)
    entries.append((_WATCH_WIKI_DIR.as_posix(), wiki_kind))
    if wiki_kind == "directory":
        try:
            paths = sorted(wiki_root.rglob("*.md"), key=lambda item: item.as_posix())
        except (OSError, RuntimeError):
            paths = []
            entries.append((_WATCH_WIKI_DIR.as_posix(), "unreadable"))
        for path in paths:
            try:
                path_stat = path.stat()
                relative = path.relative_to(workspace_root).as_posix()
            except (OSError, RuntimeError, ValueError):
                continue
            if stat.S_ISREG(path_stat.st_mode):
                entries.append((relative, content(path, path_stat)))
            else:
                entries.append((relative, f"mode:{path_stat.st_mode}"))

    for queue_relative in _WATCH_QUEUE_DIRS:
        queue_root = workspace_root / queue_relative
        queue_kind = _path_kind(queue_root)
        entries.append((queue_relative.as_posix(), queue_kind))
        if queue_kind != "directory":
            continue
        try:
            children = sorted(queue_root.iterdir(), key=lambda item: item.name)
        except (OSError, RuntimeError):
            entries.append((queue_relative.as_posix(), "unreadable"))
            continue
        for child in children:
            if child.name in IGNORED_INTAKE_FILES or child.name.startswith("_") or child.name.startswith("."):
                continue
            try:
                relative = child.relative_to(workspace_root).as_posix()
            except (RuntimeError, ValueError):
                continue
            entries.append((relative, _path_kind(child)))

    # The directories the generated apps use; the manifest, hashed above, declares every other app path.
    for app_id, relative in sorted(GENERATED_PLATFORM_DIRS.items()):
        entries.append((f"app:{app_id}", _path_kind(workspace_root / relative)))

    for relative in _capability_paths():
        path = workspace_root / relative
        kind = _path_kind(path)
        entries.append((relative.as_posix(), content(path) if kind == "file" else kind))

    return tuple(entries)


def fingerprint_digest(entries: Iterable[tuple[str, str]]) -> str:
    """Return an opaque, deterministic digest for a workspace fingerprint."""

    payload = json.dumps(list(entries), ensure_ascii=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def _observed_at(entries: Iterable[tuple[str, str]]) -> str:
    """Reuse the first observation time for an unchanged cached source snapshot.

    ``observed_at`` records when this content fingerprint first entered the
    bounded cache; it is not refreshed for every read of the same snapshot.
    """

    key = fingerprint_digest(entries)
    with _OBSERVED_AT_LOCK:
        observed_at = _OBSERVED_AT_BY_FINGERPRINT.get(key)
        if observed_at is not None:
            _OBSERVED_AT_BY_FINGERPRINT.move_to_end(key)
            return observed_at
        observed_at = datetime.now().astimezone().isoformat(timespec="seconds")
        _OBSERVED_AT_BY_FINGERPRINT[key] = observed_at
        while len(_OBSERVED_AT_BY_FINGERPRINT) > _OBSERVED_AT_CACHE_LIMIT:
            _OBSERVED_AT_BY_FINGERPRINT.popitem(last=False)
        return observed_at


@within_wiki_read_scope
def build_transition_preflight(
    root: Path,
    feature_id: str,
    action: str = SUPPORTED_ACTION,
) -> dict[str, Any]:
    """Build a versioned, read-only preflight envelope for one feature."""

    workspace_root = root.expanduser().resolve()
    initial_fingerprint = workspace_fingerprint(workspace_root)
    lint_result = lint_wiki(workspace_root)
    inspection = inspect_workspace(workspace_root)
    features = read_feature_pages(workspace_root / _WATCH_WIKI_DIR)
    evaluation = evaluate_transition_summaries(
        workspace_root,
        features=features,
        lint_result=lint_result,
        inspection=inspection,
        initial_fingerprint=initial_fingerprint,
    )

    requested = action.strip() if isinstance(action, str) else ""
    normalized_id = normalize_feature_id(feature_id) if isinstance(feature_id, str) else ""
    matches = [feature for feature in features if normalize_feature_id(feature.feature_id) == normalized_id]
    diagnostics = [*lint_result.diagnostics, *evaluation.diagnostics]
    sources = [*evaluation.sources]

    available_transitions: list[dict[str, Any]] = []
    if not matches:
        diagnostics.append(
            _diag(
                "transition-feature-not-found",
                "error",
                workspace_root / _WATCH_WIKI_DIR / "features",
                f"No feature page found for `{feature_id}`.",
                feature_id if isinstance(feature_id, str) and feature_id else None,
            )
        )
        transition = _unknown_transition(
            str(feature_id),
            "Feature ID does not resolve to exactly one canonical feature page.",
            sources=[str(workspace_root / _WATCH_WIKI_DIR / "features")],
            action=None,
            checks=[_check("feature-id", "unknown", "Feature ID does not resolve to a feature page.", workspace_root / _WATCH_WIKI_DIR / "features")],
        )
        feature_summary = None
    elif len(matches) > 1:
        duplicate_sources = [str(feature.page.path) for feature in matches]
        transition = _unknown_transition(
            matches[0].feature_id,
            f"Feature ID `{matches[0].feature_id}` is duplicated across canonical pages.",
            sources=duplicate_sources,
            action=None,
            checks=[
                _check(
                    "duplicate-feature-id",
                    "unknown",
                    f"Feature ID `{matches[0].feature_id}` is present in more than one feature page.",
                    matches[0].page.path,
                )
            ],
        )
        feature_summary = _feature_summary(matches[0])
        sources.extend(duplicate_sources)
    else:
        feature = matches[0]
        available_transitions = evaluation.transitions_list_by_path.get(str(feature.page.path), [])
        transition = next(
            (record for record in available_transitions if record.get("action") == requested),
            None,
        )
        if transition is None:
            transition = _unsupported_or_unmapped_transition(
                feature,
                requested,
                available_transitions,
                workspace_root,
            )
        if not transition:
            transition = _unknown_transition(
                feature.feature_id,
                "No transition summary was produced for this source page.",
                sources=[str(feature.page.path)],
                action=None,
                checks=[_check("transition-summary", "unknown", "No transition summary was produced for this source page.", feature.page.path)],
            )
        feature_summary = _feature_summary(feature)
        sources.append(str(feature.page.path))

    if requested and requested not in SUPPORTED_ACTIONS:
        diagnostics.append(
            _diag(
                "unsupported-transition-action",
                "error",
                workspace_root / _WATCH_WIKI_DIR,
                f"Transition action `{requested}` is not supported by this read-only evaluator.",
            )
        )
        transition = _unknown_transition(
            transition.get("feature_id", str(feature_id)),
            f"Transition action `{requested}` is not supported by this evaluator.",
            sources=transition.get("sources", []),
            action=None,
            checks=[_check("unsupported-action", "unknown", f"Transition action `{requested}` is not supported.", workspace_root / _WATCH_WIKI_DIR)],
        )

    facts = {
        "requested_action": requested or None,
        "transition_capability": evaluation.capability,
        "feature": feature_summary,
        "transition": transition,
        "transitions": available_transitions,
    }
    envelope = build_envelope(
        workspace_root,
        "wiki transition-preflight",
        _unique_diagnostics(diagnostics),
        facts,
        _unique_strings(sources),
    )
    return finalize_transition_envelope(workspace_root, envelope)


@within_wiki_read_scope
def build_board_transition_preflight(
    root: Path,
    feature_id: str,
    action: str,
    *,
    advisory_override: tuple[str, str | None] | None = None,
    frontmatter_overrides: dict[str, Any] | None = None,
    named_apps: Iterable[str] | None = None,
    proposal: bool = False,
) -> dict[str, Any]:
    """Evaluate one named action for an explicitly adopted connected board.

    This service-only evaluator reuses the existing action checks but does not
    require copied Codex/Claude command files or a generated application
    directory.  The legacy ``build_transition_preflight`` contract remains
    copy-only and unchanged.

    `named_apps` are the apps a per-app proposal names and `proposal` says that the pages are a proposal's result (see
    ``_evaluate_action``).
    """

    workspace_root = root.expanduser().resolve()
    requested = action.strip() if isinstance(action, str) else ""
    normalized_id = normalize_feature_id(feature_id) if isinstance(feature_id, str) else ""
    wiki_root = workspace_root / _WATCH_WIKI_DIR
    features = read_feature_pages(wiki_root)
    matches = [feature for feature in features if normalize_feature_id(feature.feature_id) == normalized_id]
    lint_result = lint_wiki(workspace_root)
    inspection = inspect_workspace(workspace_root)
    identity_checks = _board_workspace_identity_checks(workspace_root, inspection)
    requirement_pages = read_app_requirement_pages(wiki_root)
    wiki_pages = read_wiki_pages(wiki_root)

    if requested not in ACTION_BY_ID or ACTION_BY_ID[requested].subject != "feature":
        return _unknown_transition(
            str(feature_id),
            f"Action `{requested}` is not registered for the Prism workflow.",
            sources=[str(wiki_root)],
            action=None,
            checks=[_check("unsupported-action", "unknown", f"Action `{requested}` is not registered for the Prism workflow.", wiki_root)],
        )
    if not ACTION_BY_ID[requested].enabled:
        return _unknown_transition(
            str(feature_id),
            f"Action `{requested}` is registered but not available yet.",
            sources=[str(wiki_root)],
            action=requested,
            checks=[_check("action-unavailable", "unknown", f"Action `{requested}` is registered but its work package has not landed.", wiki_root)],
        )
    if len(matches) != 1:
        status = "unknown" if matches else "error"
        message = (
            f"Feature ID `{feature_id}` resolves to more than one canonical page."
            if matches
            else f"No canonical feature page exists for `{feature_id}`."
        )
        return _unknown_transition(
            str(feature_id),
            message,
            sources=[str(wiki_root / "features")],
            action=requested,
            checks=[_check("feature-id", "unknown" if status == "unknown" else "blocked", message, wiki_root / "features")],
        )

    feature = matches[0]
    overrides = dict(frontmatter_overrides or {})
    if requested == "po-handoff" and advisory_override is not None:
        state, reason = advisory_override
        overrides["advisory-review"] = state
        if state == "skipped" and isinstance(reason, str):
            overrides["advisory-skip-reason"] = reason
    if overrides:
        frontmatter = dict(feature.page.frontmatter)
        frontmatter.update(overrides)
        page = replace(feature.page, frontmatter=frontmatter)
        feature = replace(feature, page=page)

    spec = ACTION_BY_ID[requested]
    capability_checks: list[dict[str, Any]] = []
    if requested == "po-handoff":
        transition = _evaluate_po_handoff(
            workspace_root,
            feature,
            lint_result,
            inspection,
            capability_checks,
            {},
            True,
            identity_checks,
            _duplicate_feature_ids(features),
        )
    else:
        transition = _evaluate_action(
            workspace_root,
            feature,
            spec,
            lint_result,
            inspection,
            capability_checks,
            {},
            True,
            identity_checks,
            _duplicate_feature_ids(features),
            requirement_pages,
            wiki_pages,
            named_apps,
            proposal=proposal,
        )
    # A service capability is an explicitly adopted workflow record, not an
    # installed vendor command. Keep the action's status/source checks intact.
    transition["supported"] = transition.get("action") == requested and transition.get("classification") != "unknown"
    return transition


def _board_workspace_identity_checks(root: Path, inspection: WorkspaceInspection) -> list[dict[str, Any]]:
    manifest = inspection.manifest
    if manifest is None:
        return [_check("workspace-identity", "unknown", "A readable workflow workspace manifest is required.", root / MANIFEST_FILE)]
    workflow = manifest.workflow
    if (
        manifest.schema_version != MANIFEST_SCHEMA_VERSION
        or workflow.get("version") != "1"
        or workflow.get("mode") not in {"workflow", "generated"}
        or not isinstance(workflow.get("board_id"), str)
    ):
        return [_check("workspace-identity", "unknown", "The workspace has no supported connected workflow identity.", manifest.path)]
    try:
        from uuid import UUID

        UUID(workflow["board_id"])
    except (ValueError, TypeError, AttributeError):
        return [_check("workspace-identity", "unknown", "The workflow board_id is not a valid UUID.", manifest.path)]
    if not manifest.project_name:
        return [_check("workspace-identity", "unknown", "Project identity is required.", manifest.path)]
    return [_check("workspace-identity", "pass", "The adopted workflow identity and scope are available.", manifest.path)]


@within_wiki_read_scope
def evaluate_transition_summaries(
    root: Path,
    *,
    features: list[FeaturePage] | None = None,
    lint_result: WikiLintResult | None = None,
    inspection: WorkspaceInspection | None = None,
    requirement_pages: list[Any] | None = None,
    wiki_pages: list[Any] | None = None,
    initial_fingerprint: tuple[tuple[str, str], ...] | None = None,
) -> TransitionEvaluation:
    """Evaluate all feature action summaries against one observed snapshot.

    ``features``, ``lint_result``, ``inspection``, and the page collections are
    injectable so graph construction can reuse its already-read data instead of
    performing another full lint/workspace scan.
    """

    workspace_root = root.expanduser().resolve()
    before = initial_fingerprint if initial_fingerprint is not None else workspace_fingerprint(workspace_root)
    observed_at = _observed_at(before)
    feature_pages = features if features is not None else read_feature_pages(workspace_root / _WATCH_WIKI_DIR)
    wiki_lint = lint_result if lint_result is not None else lint_wiki(workspace_root)
    workspace_inspection = inspection if inspection is not None else inspect_workspace(workspace_root)
    requirement_pages = requirement_pages if requirement_pages is not None else read_app_requirement_pages(workspace_root / _WATCH_WIKI_DIR)
    wiki_pages = wiki_pages if wiki_pages is not None else read_wiki_pages(workspace_root / _WATCH_WIKI_DIR)

    capability_checks_by_action: dict[str, list[dict[str, Any]]] = {}
    invocations_by_action: dict[str, dict[str, str]] = {}
    for action_id in SUPPORTED_ACTIONS:
        checks, invocations = _capability_checks(workspace_root, action_id)
        capability_checks_by_action[action_id] = checks
        invocations_by_action[action_id] = invocations
    capability_available_by_action = {
        action_id: bool(invocations)
        for action_id, invocations in invocations_by_action.items()
    }
    identity_checks = _workspace_identity_checks(workspace_root, workspace_inspection)
    duplicate_ids = _duplicate_feature_ids(feature_pages)
    transitions: dict[str, dict[str, Any]] = {}
    transitions_list: dict[str, list[dict[str, Any]]] = {}

    required_reads_token = _REQUIRED_WIKI_FILE_READS.set({})
    try:
        for feature in feature_pages:
            primary, records = _evaluate_feature(
                workspace_root,
                feature,
                wiki_lint,
                workspace_inspection,
                capability_checks_by_action,
                invocations_by_action,
                capability_available_by_action,
                identity_checks,
                duplicate_ids,
                requirement_pages,
                wiki_pages,
            )
            transitions[str(feature.page.path)] = primary
            transitions_list[str(feature.page.path)] = records
    finally:
        _REQUIRED_WIKI_FILE_READS.reset(required_reads_token)

    after = workspace_fingerprint(workspace_root)
    consistent = before == after
    snapshot = {
        "fingerprint": fingerprint_digest(after),
        "observed_at": observed_at,
        "consistent": consistent,
    }
    capability_sources = [
        str(workspace_root / relative)
        for relative in (
            *_WATCH_FILES,
            _WATCH_WIKI_DIR,
            *_WATCH_QUEUE_DIRS,
            *_capability_paths(),
        )
    ]
    capability = {
        "version": TRANSITION_CAPABILITY_VERSION,
        "mode": "copy-only",
        "supported_actions": [
            action_id
            for action_id in SUPPORTED_ACTIONS
            if capability_available_by_action[action_id] and consistent
        ],
        "surfaces": _capability_surfaces(
            workspace_root,
            capability_checks_by_action,
            invocations_by_action,
        ),
        "snapshot": snapshot,
        "sources": _unique_strings(capability_sources),
    }

    diagnostics: list[WikiDiagnostic] = []
    if not consistent:
        changed = _diag(
            "transition-source-changed",
            "error",
            workspace_root,
            "Workspace sources changed while transition facts were being read; refresh before using this snapshot.",
        )
        diagnostics.append(changed)
        for records in transitions_list.values():
            _invalidate_transition_records(
                records,
                workspace_root,
                "Workspace sources changed while this transition was being read.",
            )
        _invalidate_transition_records(
            list(transitions.values()),
            workspace_root,
            "Workspace sources changed while this transition was being read.",
        )

    return TransitionEvaluation(
        capability=capability,
        transitions_by_path=transitions,
        transitions_list_by_path=transitions_list,
        diagnostics=diagnostics,
        sources=_unique_strings(capability_sources),
    )


def finalize_transition_envelope(root: Path, envelope: dict[str, Any]) -> dict[str, Any]:
    """Invalidate transition facts if sources changed during envelope assembly.

    The evaluator checks the read window around its own inputs.  Graph edge
    collection and the shared envelope builder perform additional reads, so
    their callers use this final guard before exposing a snapshot.
    """

    facts = envelope.get("facts")
    capability = facts.get("transition_capability") if isinstance(facts, dict) else None
    snapshot = capability.get("snapshot") if isinstance(capability, dict) else None
    if not isinstance(capability, dict) or not isinstance(snapshot, dict):
        return envelope
    current_digest = fingerprint_digest(workspace_fingerprint(root))
    expected_digest = snapshot.get("fingerprint")
    if snapshot.get("consistent") is False and expected_digest == current_digest:
        return envelope
    if expected_digest == current_digest and snapshot.get("consistent") is not False:
        return envelope

    snapshot["consistent"] = False
    capability["supported_actions"] = []
    diagnostic = {
        "code": "transition-source-changed",
        "severity": "error",
        "path": str(root),
        "message": "Workspace sources changed while the complete transition snapshot was being assembled; refresh before using this snapshot.",
    }
    diagnostics = envelope.setdefault("diagnostics", [])
    if not any(
        isinstance(item, dict)
        and item.get("code") == diagnostic["code"]
        and item.get("message") == diagnostic["message"]
        for item in diagnostics
    ):
        diagnostics.append(diagnostic)
    envelope["confidence"] = "error"

    records: list[dict[str, Any]] = []
    seen_ids: set[int] = set()

    def add_record(value: Any) -> None:
        if not isinstance(value, dict) or id(value) in seen_ids:
            return
        seen_ids.add(id(value))
        records.append(value)

    if isinstance(facts.get("transition"), dict):
        add_record(facts["transition"])
    transition_list = facts.get("transitions") if isinstance(facts, dict) else None
    if isinstance(transition_list, list):
        for transition in transition_list:
            add_record(transition)
    nodes = facts.get("nodes") if isinstance(facts, dict) else None
    if isinstance(nodes, list):
        for node in nodes:
            if not isinstance(node, dict):
                continue
            node_transitions = node.get("transitions")
            if isinstance(node_transitions, list):
                for transition in node_transitions:
                    add_record(transition)
    for transition in records:
        checks = transition.setdefault("checks", [])
        if not any(check.get("code") == "snapshot-consistency" for check in checks if isinstance(check, dict)):
            checks.append(
                _check(
                    "snapshot-consistency",
                    "unknown",
                    "Workspace sources changed while this transition was being assembled.",
                    root,
                )
            )
        transition["classification"] = "unknown"
        transition["supported"] = False
        transition["reason"] = "Workspace sources changed while this transition was being assembled."
        transition.pop("invocations", None)
    return envelope


def _invalidate_transition_records(
    records: Iterable[dict[str, Any]],
    root: Path,
    reason: str,
) -> None:
    """Mark every exposed transition record unknown for an inconsistent read."""

    seen: set[int] = set()
    for transition in records:
        if not isinstance(transition, dict) or id(transition) in seen:
            continue
        seen.add(id(transition))
        checks = transition.setdefault("checks", [])
        if not any(
            isinstance(check, dict) and check.get("code") == "snapshot-consistency"
            for check in checks
        ):
            checks.append(_check("snapshot-consistency", "unknown", reason, root))
        transition["classification"] = "unknown"
        transition["supported"] = False
        transition["reason"] = reason
        transition.pop("invocations", None)


def _evaluate_feature(
    workspace_root: Path,
    feature: FeaturePage,
    lint_result: WikiLintResult,
    inspection: WorkspaceInspection,
    capability_checks_by_action: dict[str, list[dict[str, Any]]],
    invocations_by_action: dict[str, dict[str, str]],
    capability_available_by_action: dict[str, bool],
    identity_checks: list[dict[str, Any]],
    duplicate_ids: set[str],
    requirement_pages: list[Any],
    wiki_pages: list[Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return the primary and all currently mapped actions for one feature."""

    owner_of_design = design_owner(feature.apps, inspection.model)
    matching_specs = [
        spec
        for spec in ACTION_SPECS
        if spec.enabled and spec.copy and (feature.status, feature.owner) in spec.resolved_sources(owner_of_design)
    ]
    if feature.status == "in-design":
        # The handoff is what a feature in design moves to; the two track actions each settle one track of it.
        matching_specs.sort(key=lambda spec: spec.action != "design-handoff")

    # po-handoff has its own evaluator with the detailed completeness checks
    # (summary, user story, acceptance criteria, app scope) that the generic
    # action evaluator does not produce.
    if feature.status == SUPPORTED_SOURCE_STATUS and feature.owner == SUPPORTED_SOURCE_OWNER:
        primary = _evaluate_po_handoff(
            workspace_root,
            feature,
            lint_result,
            inspection,
            capability_checks_by_action[SUPPORTED_ACTION],
            invocations_by_action[SUPPORTED_ACTION],
            capability_available_by_action[SUPPORTED_ACTION],
            identity_checks,
            duplicate_ids,
        )
        return primary, [primary]

    if matching_specs:
        records = [
            _evaluate_action(
                workspace_root,
                feature,
                spec,
                lint_result,
                inspection,
                capability_checks_by_action[spec.action],
                invocations_by_action[spec.action],
                capability_available_by_action[spec.action],
                identity_checks,
                duplicate_ids,
                requirement_pages,
                wiki_pages,
            )
            for spec in matching_specs
        ]
        if feature.status == "released" and feature.owner == "none":
            return _released_primary_transition(feature, records), records
        return records[0], records

    return _unsupported_source_transition(feature, identity_checks), []


def _evaluate_po_handoff(
    workspace_root: Path,
    feature: FeaturePage,
    lint_result: WikiLintResult,
    inspection: WorkspaceInspection,
    capability_checks: list[dict[str, Any]],
    invocations: dict[str, str],
    capability_available: bool,
    identity_checks: list[dict[str, Any]],
    duplicate_ids: set[str],
) -> dict[str, Any]:
    path = feature.page.path
    feature_id = feature.feature_id
    frontmatter = feature.page.frontmatter
    status = feature.status
    owner = feature.owner
    source_pair_known = status == SUPPORTED_SOURCE_STATUS and owner == SUPPORTED_SOURCE_OWNER
    checks: list[dict[str, Any]] = []
    wiki_root = workspace_root / _WATCH_WIKI_DIR
    sources = [
        str(path),
        str(workspace_root / MANIFEST_FILE),
        str(workspace_root / COPIER_ANSWERS_FILE),
        str(wiki_root / "SCHEMA.md"),
        str(wiki_root / "LIFECYCLE.md"),
        str(wiki_root / "ACTIONS.md"),
        str(wiki_root / "index.md"),
        str(wiki_root / "status-board.md"),
        *[str(workspace_root / relative) for relative in CAPABILITY_FILES.values()],
    ]
    for raw_target in extract_markdown_links(feature.page.body):
        linked = resolve_relative_markdown_link(feature.page.path, raw_target, wiki_root)
        if linked is not None:
            sources.append(str(linked))

    path_feature_id = feature_id_from_path(path)
    normalized_feature_id = normalize_feature_id(feature_id)
    if (
        not isinstance(frontmatter.get("id"), str)
        or not re.fullmatch(r"F-\d+", str(frontmatter.get("id", "")).strip())
        or path_feature_id != feature_id
        or normalized_feature_id in duplicate_ids
    ):
        message = (
            f"Feature ID `{feature_id}` is not a unique canonical ID/path pair."
            if normalized_feature_id in duplicate_ids
            else f"Feature ID `{feature_id}` or its feature path is malformed."
        )
        checks.append(_check("feature-id", "unknown", message, path))
    else:
        checks.append(_check("feature-id", "pass", "Feature ID and path identify one canonical feature page.", path))

    if status not in VALID_FEATURE_STATUSES:
        checks.append(_check("source-status", "unknown", f"Source status `{status}` is missing or unsupported.", path))
    elif status == SUPPORTED_SOURCE_STATUS:
        checks.append(_check("source-status", "pass", "Source status is `specified`.", path))
    else:
        checks.append(
            _check(
                "unsupported-source-stage",
                "unknown",
                f"No first-slice transition is defined from source status `{status}`.",
                path,
            )
        )

    if owner not in VALID_FEATURE_OWNERS:
        checks.append(_check("source-owner", "unknown", f"Source owner `{owner}` is missing or unsupported.", path))
    elif status == SUPPORTED_SOURCE_STATUS and owner == SUPPORTED_SOURCE_OWNER:
        checks.append(_check("source-owner", "pass", "Source owner is `po`.", path))
    elif status == SUPPORTED_SOURCE_STATUS:
        checks.append(_check("source-owner", "unknown", f"Specified feature owner is `{owner}`, not `po`.", path))
    else:
        checks.append(_check("source-owner", "unknown", f"Source owner `{owner}` has no first-slice action mapping.", path))

    checks.extend(identity_checks)

    if source_pair_known:
        checks.append(_scope_check(feature, inspection, workspace_root))
        checks.extend(
            [
                _section_check(feature, "Summary", "summary"),
                _section_check(feature, "User story", "user-story"),
                _acceptance_criteria_check(feature),
            ]
        )
        checks.append(_app_section_check(feature, inspection.model))
        checks.append(_open_questions_check(feature))
        checks.append(_advisory_check(feature))
        checks.append(_revalidation_check(feature, {"specification"}, {"specification"}))
        checks.append(_design_owner_check(feature, inspection.model))
        checks.extend(capability_checks)
        checks.extend(_relevant_integrity_checks(feature, lint_result))

    classification = _classify_checks(checks, capability_available=capability_available)
    if not source_pair_known:
        action = None
        target_status = None
        supported = False
        reason = f"No supported po-handoff action is defined from source status `{status}` and owner `{owner}`."
    else:
        action = SUPPORTED_ACTION
        target_status = SUPPORTED_TARGET_STATUS
        supported = source_pair_known and capability_available and classification != "unknown"
        reason = _transition_reason(classification, checks)

    transition: dict[str, Any] = {
        "version": TRANSITION_SCHEMA_VERSION,
        "feature_id": feature_id,
        "source_status": status,
        "source_owner": owner,
        "source_path": str(path),
        "target_status": target_status,
        "target_owner": design_owner(feature.apps, inspection.model) if target_status == SUPPORTED_TARGET_STATUS else None,
        "action": action,
        "classification": classification,
        "supported": supported,
        "checks": checks,
        "sources": _unique_strings(sources),
        "reason": reason,
    }
    if invocations and source_pair_known:
        transition["invocations"] = {
            role: invocation.replace("F-XXX", feature_id)
            for role, invocation in invocations.items()
        }
    return transition


def _evaluate_action(
    workspace_root: Path,
    feature: FeaturePage,
    spec: ActionSpec,
    lint_result: WikiLintResult,
    inspection: WorkspaceInspection,
    capability_checks: list[dict[str, Any]],
    invocations: dict[str, str],
    capability_available: bool,
    identity_checks: list[dict[str, Any]],
    duplicate_ids: set[str],
    requirement_pages: list[Any],
    wiki_pages: list[Any],
    named_apps: Iterable[str] | None = None,
    *,
    proposal: bool = False,
) -> dict[str, Any]:
    """Evaluate one action mapping without performing the lifecycle write.

    `named_apps` are the apps a per-app action's proposal names (for `dev-done` the apps whose delivery evidence it adds);
    the copy-only preflight has no proposal and passes ``None``. `proposal` is set when the feature page and the pages
    around it are a proposal's result: a design track the proposal leaves pending is then a blocker, where the copy-only
    preflight judges whether the content of the track is ready.
    """

    path = feature.page.path
    feature_id = feature.feature_id
    model = inspection.model
    design = design_owner(feature.apps, model)
    source_pair_known = (feature.status, feature.owner) in spec.resolved_sources(design)
    checks = _base_action_checks(feature, spec, duplicate_ids, design)
    checks.extend(identity_checks)
    sources = _transition_sources(workspace_root, feature, spec, requirement_pages, wiki_pages)
    named = None if named_apps is None else tuple(named_apps)

    if source_pair_known:
        checks.append(_scope_check(feature, inspection, workspace_root, allow_retired=spec.action in RETIRED_ALLOWED_ACTIONS))
        checks.extend(_action_specific_checks(spec, feature, wiki_pages, requirement_pages, model, named, proposal=proposal))

        # Canonical workflow blockers are intentionally scoped to the selected
        # feature.  A blocker on another feature remains visible in the
        # envelope, but cannot become a false prerequisite for this action.
        if spec.action not in _ROUTE_ACTIONS:
            checks.extend(_feature_workflow_checks(feature, lint_result, spec.action, requirement_pages, model))
        checks.extend(_relevant_integrity_checks(feature, lint_result, ignore_codes=set(_IGNORED_INTEGRITY.get(spec.action, ()))))
        checks.extend(capability_checks)

    classification = _classify_checks(checks, capability_available=capability_available)
    if not source_pair_known:
        return _unsupported_source_transition(feature, identity_checks, spec=spec, design=design)

    supported = capability_available and classification != "unknown"
    reason = _action_transition_reason(spec, classification, checks)
    target_status, target_owner = _planned_target(spec, feature, model, named)
    transition: dict[str, Any] = {
        "version": TRANSITION_SCHEMA_VERSION,
        "feature_id": feature_id,
        "source_status": feature.status,
        "source_owner": feature.owner,
        "source_path": str(path),
        "target_status": target_status,
        "target_owner": target_owner,
        "action": spec.action,
        "classification": classification,
        "supported": supported,
        "checks": checks,
        "sources": _unique_strings(sources),
        "reason": reason,
    }
    if invocations:
        transition["invocations"] = {
            role: invocation.replace("F-XXX", feature_id)
            for role, invocation in invocations.items()
        }
    return transition


# The lint codes a gate ignores because the evaluated page is a candidate: the proposal's pages at the source status.
# The findings about the tracks and their pages that the track checks of an action report as blocked, with their own code.
_TRACK_FINDINGS = (
    "design-coverage-incomplete",
    "missing-technical-design",
    "technical-design-incomplete",
    "technical-design-feature-mismatch",
    "test-strategy-incomplete",
    "api-contract-required",
    "ui-exemption-reason-required",
    "technical-track-required",
)
# What a return from implementation sets right: evidence, requirement and contract states, the tracks and the pending domains.
_RETURN_FINDINGS = (
    *_TRACK_FINDINGS,
    "app-row-ahead-of-status",
    "app-row-missing",
    "app-row-out-of-order",
    "feature-status-not-minimum",
    "stale-qa-evidence",
    "stale-delivery-evidence",
    "done-app-requirement",
    "delivered-api-contract",
    "design-track-pending",
    "design-tracks-missing",
    "invalid-revalidation",
    "pending-revalidation",
    "status-board-frontmatter-drift",
)
_ROUTE_ACTIONS = frozenset({"dev-return-spec", "dev-return-design"})
_IGNORED_INTEGRITY: dict[str, tuple[str, ...]] = {
    "dev-done": ("app-row-ahead-of-status", "feature-status-not-minimum", "app-row-missing", "status-board-frontmatter-drift"),
    "scope-edit": ("app-row-ahead-of-status", "feature-status-not-minimum", "app-row-missing", "status-board-frontmatter-drift"),
    "design-ui-done": _TRACK_FINDINGS,
    "tech-design-done": _TRACK_FINDINGS,
    "design-handoff": _TRACK_FINDINGS,
    "dev-return-spec": _RETURN_FINDINGS,
    "dev-return-design": _RETURN_FINDINGS,
    **{
        action: ("app-row-ahead-of-status", "feature-status-not-minimum", "app-row-missing", "status-board-frontmatter-drift")
        for action in ("qa-verify", "qa-pass", "qa-fail")
    },
    # The routes back from QA reset what the routes back from implementation reset.
    "qa-return-spec": _RETURN_FINDINGS,
    "qa-return-design": _RETURN_FINDINGS,
}
# The workflow blockers of the 0.6 gates; the evidence-staleness blockers do not gate these actions.
LEGACY_BLOCKER_CODES = frozenset(
    {
        "pending-board-review",
        "design-track-pending",
        "missing-app-requirements",
        "unresolved-open-questions",
        "api-contract-not-ready",
        "cross-app-dependency",
    }
)
QA_BLOCKER_CODES = LEGACY_BLOCKER_CODES - {"cross-app-dependency"}


def _action_specific_checks(
    spec: ActionSpec,
    feature: FeaturePage,
    wiki_pages: list[Any],
    requirement_pages: list[Any],
    model: WorkspaceModel,
    named_apps: tuple[str, ...] | None,
    *,
    proposal: bool = False,
) -> list[dict[str, Any]]:
    action = spec.action
    if action == "po-specify":
        return _specification_checks(feature, model)
    if action == "design-start":
        return [
            _advisory_check(feature),
            _revalidation_check(feature, {"specification"}, set()),
            _open_questions_check_for_action(feature, {"po"}),
        ]
    if action == "design-ui-done":
        tracks = _effective_tracks(feature, model)
        return [
            _ui_track_check(feature, tracks, wiki_pages, model, proposal=proposal),
            _open_questions_check_for_action(feature, {"designer"}),
            _revalidation_check(feature, {"specification"}, set()),
        ]
    if action == "tech-design-done":
        tracks = _effective_tracks(feature, model)
        return [
            *_technical_track_checks(feature, tracks, wiki_pages, model, proposal=proposal),
            _api_surface_app_check(feature, model),
            _open_questions_check_for_action(feature, {"tech-lead"}),
            _revalidation_check(feature, {"specification"}, set()),
        ]
    if action == "design-handoff":
        tracks = _effective_tracks(feature, model)
        return [
            _ui_track_check(feature, tracks, wiki_pages, model, proposal=proposal),
            *_technical_track_checks(feature, tracks, wiki_pages, model, proposal=proposal),
            _reaffirm_check(feature, tracks),
            _api_surface_app_check(feature, model),
            _advisory_check(feature),
            _advisory_actions_check(feature, wiki_pages),
            _open_questions_check_for_action(feature, {"po", "designer", "tech-lead"}),
            _revalidation_check(feature, {"specification", "design", "technical-design"}, {"design", "technical-design"}),
        ]
    if action in _ROUTE_ACTIONS:
        return _return_route_checks(feature, model)
    if action == "dev-start":
        return [
            _requirements_check(feature, requirement_pages, require_done=False),
            _api_surface_app_check(feature, model),
            _api_contract_check(feature, wiki_pages, require_implemented=False),
            _advisory_check(feature),
            _advisory_actions_check(feature, wiki_pages),
            _open_questions_check_for_action(feature, {"po", "designer", "tech-lead", "dev"}),
            _revalidation_check(feature, {"specification", "design", "technical-design"}, set()),
        ]
    if action == "dev-done":
        return [
            _requirements_check(feature, requirement_pages, require_done=False),
            _api_surface_app_check(feature, model),
            _api_contract_check(feature, wiki_pages, require_implemented=False),
            _revalidation_check(feature, {"specification", "design", "technical-design"}, set()),
            _app_revalidation_check(feature, named_apps or (), {"implementation", "tests"}),
            *_delivery_evidence_checks(feature, named_apps),
            *_contract_binding_checks(feature, wiki_pages, named_apps),
            _advisory_check(feature),
            _advisory_actions_check(feature, wiki_pages),
            _open_questions_check_for_action(feature, {"po", "designer", "tech-lead", "dev"}),
        ]
    if action == "scope-edit":
        return [
            _scope_not_empty_check(feature, model),
            _open_questions_check_for_action(feature, {"po"}),
        ]
    if action == "qa-verify":
        return qa_verify_checks(feature, model, named_apps)
    if action == "qa-pass":
        return [
            *qa_pass_checks(feature, model, named_apps),
            _revalidation_check(feature, {"specification", "design", "technical-design"}, set()),
            _app_revalidation_check(feature, named_apps or (), {"qa"}),
            _open_questions_check_for_action(feature, {"po", "designer", "tech-lead", "dev", "qa"}),
        ]
    if action == "qa-fail":
        return qa_fail_checks(feature, model, named_apps)
    return []


def _planned_target(
    spec: ActionSpec,
    feature: FeaturePage,
    model: WorkspaceModel,
    named_apps: tuple[str, ...] | None,
) -> tuple[str | None, str | None]:
    """The status and owner the action leaves the feature in, resolved from the feature (CONTRACTS 2.3).

    A `minimum` target is the lowest app stage after the action: with the proposal's `named_apps` the page already carries the
    new rows; without a proposal (the copy-only preflight) every active app without delivery evidence is taken as delivered.
    """

    status, owner = spec.resolved_target(design_owner(feature.apps, model))
    if status == UNCHANGED:
        return feature.status, feature.owner
    if status != MINIMUM:
        return status, owner
    evidence = read_feature_evidence(feature.page.body)
    stages = app_stages(active_scope(feature.apps, model), evidence)
    if spec.action == "dev-done" and named_apps is None:
        stages = {app: ("ready-for-qa" if stage == "in-dev" else stage) for app, stage in stages.items()}
    if spec.action == "qa-pass" and named_apps is None:
        stages = {app: ("ready-for-release" if stage in {"ready-for-qa", "in-qa"} else stage) for app, stage in stages.items()}
    minimum = minimum_stage(stages.values())
    if minimum is None:
        return feature.status, feature.owner
    return minimum, OWNER_BY_STATUS[minimum]


def _specification_checks(feature: FeaturePage, model: WorkspaceModel) -> list[dict[str, Any]]:
    """The checks `po-specify` adds to the generic ones: criterion IDs and scope, and empty evidence sections (CONTRACTS 2.4)."""

    path = feature.page.path
    criteria = parse_criteria(feature.page.body, feature.feature_id)
    checks: list[dict[str, Any]] = []
    for code, label in (
        ("criterion-id-required", "Every acceptance criterion needs an ID"),
        ("invalid-applies-to", "Every acceptance criterion needs a valid `applies-to`"),
    ):
        problems = [f"{item.id or item.raw[:40]}: {message}" for item in criteria for problem_code, message in item.problems if problem_code == code]
        if not criteria:
            checks.append(_check(code, "blocked", "Acceptance criteria must contain at least one criterion.", path))
        elif problems:
            checks.append(_check(code, "blocked", f"{label}: " + "; ".join(problems[:4]), path))
        else:
            checks.append(_check(code, "pass", f"{label}.", path))
    duplicates = sorted({item.id for item in criteria if item.id and sum(1 for other in criteria if other.id == item.id) > 1})
    if duplicates:
        checks.append(_check("duplicate-criterion-id", "blocked", "Criterion IDs must be unique: " + ", ".join(duplicates) + ".", path))
    else:
        checks.append(_check("duplicate-criterion-id", "pass", "Criterion IDs are unique.", path))
    checks.append(_app_without_criteria_check(feature, criteria, model))
    evidence = read_feature_evidence(feature.page.body)
    populated = [name for name, rows in (("Delivery evidence", evidence.delivery), ("QA verification", evidence.qa), ("Release", evidence.release)) if rows]
    if populated:
        checks.append(_check("evidence-sections-empty", "blocked", "A specified feature has no evidence yet: " + ", ".join(populated) + " already hold rows.", path))
    else:
        checks.append(_check("evidence-sections-empty", "pass", "The evidence sections are empty.", path))
    return checks


def _app_without_criteria_check(feature: FeaturePage, criteria: list[Any], model: WorkspaceModel) -> dict[str, Any]:
    path = feature.page.path
    named = {app for item in criteria for app in item.applies_to}
    missing = [app for app in active_scope(feature.apps, model) if app not in named]
    if missing:
        return _check("app-without-criteria", "blocked", "Every scoped app must be named by at least one criterion; none names " + ", ".join(f"`{app}`" for app in missing) + ".", path)
    return _check("app-without-criteria", "pass", "Every scoped app is named by at least one criterion.", path)


def _scope_not_empty_check(feature: FeaturePage, model: WorkspaceModel) -> dict[str, Any]:
    path = feature.page.path
    if not feature.apps:
        return _check("scope-empty", "blocked", "A feature keeps at least one app in scope.", path)
    return _check("scope-empty", "pass", "The feature keeps at least one app in scope.", path)


def _design_owner_check(feature: FeaturePage, model: WorkspaceModel) -> dict[str, Any]:
    owner = design_owner(feature.apps, model)
    return _check(
        "design-owner",
        "pass",
        f"The design owner of this scope is `{owner}`: "
        + ("an active app has a UI (or its UI is unknown)." if owner == "designer" else "no active app in scope has a UI."),
        feature.page.path,
    )


def _base_action_checks(
    feature: FeaturePage,
    spec: ActionSpec,
    duplicate_ids: set[str],
    design: str,
) -> list[dict[str, Any]]:
    path = feature.page.path
    normalized_feature_id = normalize_feature_id(feature.feature_id)
    path_feature_id = feature_id_from_path(path)
    if (
        not isinstance(feature.page.frontmatter.get("id"), str)
        or not re.fullmatch(r"F-\d+", str(feature.page.frontmatter.get("id", "")).strip())
        or path_feature_id != feature.feature_id
        or normalized_feature_id in duplicate_ids
    ):
        return [
            _check(
                "feature-id",
                "unknown",
                f"Feature ID `{feature.feature_id}` is not a unique canonical ID/path pair.",
                path,
            ),
            _source_status_check(feature, spec, design),
            _source_owner_check(feature, spec, design),
        ]
    return [
        _check("feature-id", "pass", "Feature ID and path identify one canonical feature page.", path),
        _source_status_check(feature, spec, design),
        _source_owner_check(feature, spec, design),
    ]


def _source_statuses(spec: ActionSpec) -> list[str]:
    return list(dict.fromkeys(status for status, _owner in spec.sources))


def _source_status_check(feature: FeaturePage, spec: ActionSpec, design: str = "designer") -> dict[str, Any]:
    path = feature.page.path
    statuses = _source_statuses(spec)
    wanted = " or ".join(f"`{status}`" for status in statuses)
    if feature.status not in VALID_FEATURE_STATUSES:
        return _check("source-status", "unknown", f"Source status `{feature.status}` is missing or unsupported.", path)
    if feature.status in statuses:
        return _check("source-status", "pass", f"Source status is `{feature.status}`.", path)
    return _check(
        "unsupported-source-stage",
        "unknown",
        f"Action `{spec.action}` requires source status {wanted}, observed `{feature.status}`.",
        path,
    )


def _source_owner_check(feature: FeaturePage, spec: ActionSpec, design: str = "designer") -> dict[str, Any]:
    path = feature.page.path
    if feature.owner not in VALID_FEATURE_OWNERS:
        return _check("source-owner", "unknown", f"Source owner `{feature.owner}` is missing or unsupported.", path)
    owners = [owner for status, owner in spec.resolved_sources(design) if status == feature.status] or [owner for _status, owner in spec.resolved_sources(design)]
    if feature.owner in owners:
        return _check("source-owner", "pass", f"Source owner is `{feature.owner}`.", path)
    wanted = " or ".join(f"`{owner}`" for owner in dict.fromkeys(owners))
    return _check(
        "source-owner",
        "unknown",
        f"Action `{spec.action}` requires source owner {wanted}, observed `{feature.owner}`.",
        path,
    )


def _unsupported_source_transition(
    feature: FeaturePage,
    identity_checks: list[dict[str, Any]],
    *,
    spec: ActionSpec | None = None,
    design: str = "designer",
) -> tuple[dict[str, Any], list[dict[str, Any]]] | dict[str, Any]:
    """Describe a feature whose current status/owner has no requested mapping."""

    path = feature.page.path
    feature_id = feature.feature_id
    action = spec.action if spec is not None else None
    status = feature.status
    owner = feature.owner
    checks = [
        _check(
            "feature-id",
            "pass" if feature_id_from_path(path) == feature_id else "unknown",
            "Feature ID and path identify one canonical feature page."
            if feature_id_from_path(path) == feature_id
            else f"Feature ID `{feature_id}` or its feature path is malformed.",
            path,
        ),
        _check(
            "source-status",
            "unknown",
            f"Source status `{status}` has no mapping for the requested action."
            if status in VALID_FEATURE_STATUSES
            else f"Source status `{status}` is missing or unsupported.",
            path,
        ),
        _check(
            "source-owner",
            "unknown",
            f"Source owner `{owner}` has no mapping for the requested action.",
            path,
        ),
        *identity_checks,
    ]
    if spec is not None:
        checks[1] = _source_status_check(feature, spec, design)
        checks[2] = _source_owner_check(feature, spec, design)
        reason = f"Action `{spec.action}` is not mapped from source status `{status}` and owner `{owner}`."
    else:
        reason = f"No supported lifecycle action is mapped from source status `{status}` and owner `{owner}`."
    return {
        "version": TRANSITION_SCHEMA_VERSION,
        "feature_id": feature_id,
        "source_status": status,
        "source_owner": owner,
        "source_path": str(path),
        "target_status": None,
        "target_owner": None,
        "action": None,
        "classification": "unknown",
        "supported": False,
        "checks": checks,
        "sources": [str(path)],
        "reason": reason,
    }


def _released_primary_transition(feature: FeaturePage, records: list[dict[str, Any]]) -> dict[str, Any]:
    path = feature.page.path
    return {
        "version": TRANSITION_SCHEMA_VERSION,
        "feature_id": feature.feature_id,
        "source_status": feature.status,
        "source_owner": feature.owner,
        "source_path": str(path),
        "target_status": None,
        "target_owner": None,
        "action": None,
        "classification": "unknown",
        "supported": False,
        "checks": [
            _check("released-source", "pass", "Feature is recorded as released; choose an explicit reopen route to continue work.", path),
            _check("reopen-route", "review", "Released has three explicit reopen routes; choose one after impact review.", path),
        ],
        "sources": _unique_strings(
            source
            for record in records
            for source in record.get("sources", [])
            if isinstance(source, str)
        ),
        "reason": "Released has no primary forward action; choose reopen-spec, reopen-design, or reopen-dev after impact review.",
    }


def _unsupported_or_unmapped_transition(
    feature: FeaturePage,
    requested: str,
    available: list[dict[str, Any]],
    workspace_root: Path,
) -> dict[str, Any]:
    identity = next(
        (
            check
            for check in (available[0].get("checks", []) if available else [])
            if isinstance(check, dict) and check.get("code") == "workspace-identity"
        ),
        _check("workspace-identity", "unknown", "Workspace identity could not be established.", workspace_root),
    )
    return _unknown_transition(
        feature.feature_id,
        f"Action `{requested}` is not mapped from the current source status `{feature.status}` and owner `{feature.owner}`.",
        sources=[str(feature.page.path)],
        action=None,
        source_status=feature.status,
        source_owner=feature.owner,
        source_path=str(feature.page.path),
        checks=[
            _check(
                "feature-id",
                "pass" if feature_id_from_path(feature.page.path) == feature.feature_id else "unknown",
                "Feature ID and path identify one canonical feature page."
                if feature_id_from_path(feature.page.path) == feature.feature_id
                else f"Feature ID `{feature.feature_id}` or its feature path is malformed.",
                feature.page.path,
            ),
            _check(
                "unsupported-source-stage",
                "unknown",
                f"No `{requested}` action is available from source status `{feature.status}` and owner `{feature.owner}`.",
                feature.page.path,
            ),
            _check(
                "source-owner",
                "unknown",
                f"Source owner `{feature.owner}` is not valid for the requested `{requested}` action.",
                feature.page.path,
            ),
            identity,
        ],
    )


def _transition_sources(
    workspace_root: Path,
    feature: FeaturePage,
    spec: ActionSpec,
    requirement_pages: list[Any],
    wiki_pages: list[Any],
) -> list[str]:
    wiki_root = workspace_root / _WATCH_WIKI_DIR
    sources: list[str] = [
        str(feature.page.path),
        str(workspace_root / MANIFEST_FILE),
        str(workspace_root / COPIER_ANSWERS_FILE),
        str(wiki_root / "SCHEMA.md"),
        str(wiki_root / "LIFECYCLE.md"),
        str(wiki_root / "ACTIONS.md"),
        str(wiki_root / "index.md"),
        str(wiki_root / "status-board.md"),
        *[str(workspace_root / relative) for relative in _ACTION_SURFACE_PATHS[spec.action].values()],
    ]
    feature_id = normalize_feature_id(feature.feature_id)
    for raw_target in extract_markdown_links(feature.page.body):
        linked = resolve_relative_markdown_link(feature.page.path, raw_target, wiki_root)
        if linked is not None:
            sources.append(str(linked))
    for page in requirement_pages:
        page_feature = getattr(page, "feature_id", None)
        if isinstance(page_feature, str) and page_feature.strip().lower() == feature_id:
            sources.append(str(page.page.path))
    for page in wiki_pages:
        page_feature = page.frontmatter.get("feature-id") if hasattr(page, "frontmatter") else None
        if not isinstance(page_feature, str) or page_feature.strip().lower() != feature_id:
            continue
        try:
            page.path.resolve().relative_to((wiki_root / "api-contracts").resolve())
        except ValueError:
            continue
        sources.append(str(page.path))
    return _unique_strings(sources)


def _feature_workflow_checks(
    feature: FeaturePage,
    lint_result: WikiLintResult,
    action: str,
    requirement_pages: list[Any],
    model: WorkspaceModel,
) -> list[dict[str, Any]]:
    relevant_codes = {
        "po-handoff": {"pending-board-review"},
        "design-start": {"pending-board-review"},
        "design-ui-done": set(),
        "tech-design-done": set(),
        "design-handoff": {"pending-board-review"},
        "dev-start": LEGACY_BLOCKER_CODES,
        "dev-done": LEGACY_BLOCKER_CODES,
        "scope-edit": LEGACY_BLOCKER_CODES,
        # QA checks the delivered work as it is: the earlier gates still hold and an unreleased dependency does not matter yet.
        # The evidence of the QA rows is judged by the QA rules, not by the staleness blockers of the page the proposal replaces.
        "qa-verify": QA_BLOCKER_CODES,
        "qa-pass": QA_BLOCKER_CODES,
        "qa-fail": frozenset(),
        "qa-return-spec": frozenset(),
        "qa-return-design": frozenset(),
    }.get(action, WIKI_BLOCKER_CODES)
    # An unreleased dependency warns while work starts and is delivered; `release-done` blocks on it (CONTRACTS 8.1).
    warns = {"cross-app-dependency"} if action in {"dev-start", "dev-done"} else set()
    normalized_id = normalize_feature_id(feature.feature_id)
    path = feature.page.path.resolve()
    requirements_by_path: dict[Path, Any] = {}
    for requirement in requirement_pages:
        requirement_path = getattr(getattr(requirement, "page", None), "path", None)
        if not isinstance(requirement_path, Path):
            continue
        try:
            requirements_by_path[requirement_path.resolve()] = requirement
        except (OSError, RuntimeError, ValueError):
            continue
    checks: list[dict[str, Any]] = []
    for diagnostic in lint_result.diagnostics:
        if diagnostic.code not in relevant_codes:
            continue
        if _is_out_of_scope_requirement_dependency(diagnostic, feature, requirements_by_path, model):
            continue
        diagnostic_feature_id = normalize_feature_id(diagnostic.feature_id) if isinstance(diagnostic.feature_id, str) else ""
        try:
            same_path = diagnostic.resolved_path == path
        except (OSError, RuntimeError, ValueError):
            same_path = False
        if diagnostic_feature_id != normalized_id and not same_path:
            continue
        status = "review" if diagnostic.code == "pending-board-review" else "warning" if diagnostic.code in warns else "blocked"
        checks.append(
            _check(
                f"workflow:{diagnostic.code}",
                status,
                diagnostic.message,
                Path(diagnostic.path),
            )
        )
    return checks


def _is_out_of_scope_requirement_dependency(
    diagnostic: WikiDiagnostic,
    feature: FeaturePage,
    requirements_by_path: dict[Path, Any],
    model: WorkspaceModel,
) -> bool:
    """Skip only a proven out-of-scope dependency for this action's gate.

    Lint diagnostics remain global facts.  This evaluator-only exception keeps
    an unrelated declared-app requirement visible in the envelope while
    preventing it from blocking an action for a feature that does not declare
    that app.  Missing or malformed ownership/scope evidence fails
    closed by returning ``False``.
    """

    if diagnostic.code != "cross-app-dependency":
        return False
    try:
        requirement = requirements_by_path.get(diagnostic.resolved_path)
    except (OSError, RuntimeError, ValueError):
        return False
    if requirement is None:
        return False

    requirement_feature_id = getattr(requirement, "feature_id", None)
    if (
        not isinstance(requirement_feature_id, str)
        or normalize_feature_id(requirement_feature_id) != normalize_feature_id(feature.feature_id)
    ):
        return False
    requirement_app = getattr(requirement, "app", None)
    if (
        not isinstance(requirement_app, str)
        or not requirement_app.strip()
        or model.app(requirement_app.strip()) is None
    ):
        return False
    declared_apps = {
        app_id.strip().lower()
        for app_id in feature.apps
        if isinstance(app_id, str) and app_id.strip()
    }
    if not declared_apps:
        return False
    return requirement_app.strip().lower() not in declared_apps


def _open_questions_message(kind: str, numbers: list[str]) -> str:
    """Count the open questions and name each by its number, so a number is never read as a count."""

    listed = ", ".join(numbers)
    if len(numbers) == 1:
        return f"1 open {kind} question remains: question {listed}."
    return f"{len(numbers)} open {kind} questions remain: questions {listed}."


def _open_questions_check_for_action(feature: FeaturePage, owners: set[str]) -> dict[str, Any]:
    section = section_text(feature.page.body, "Open questions")
    rows, errors = parse_open_question_rows(feature.page.body)
    path = feature.page.path
    if section.strip() and not rows and not errors:
        # An empty, correctly headed table is valid.
        return _check("open-questions", "pass", "No open questions remain for this action.", path)
    if errors:
        return _check("open-questions", "unknown", "; ".join(errors), path)
    open_rows = [row for row in rows if row["status"] == "open" and row["owner"] in owners]
    if open_rows:
        return _check("open-questions", "blocked", _open_questions_message("action-relevant", [row["number"] for row in open_rows]), path)
    return _check("open-questions", "pass", "No open questions remain for this action.", path)


def _effective_tracks(feature: FeaturePage, model: WorkspaceModel) -> DesignTracks:
    """The tracks of a feature as the checks read them: those on the page, or the initial ones before design has started.

    Tracks that cannot be read are treated as the initial ones too; the lint reports them as `design-tracks-invalid`.
    """

    tracks, _problems = parse_design_tracks(feature.page.frontmatter)
    return tracks if tracks is not None else initial_design_tracks(feature.apps, model)


def _feature_pages_in(feature: FeaturePage, wiki_pages: list[Any], directory: str) -> list[Any]:
    """The pages of one wiki folder that belong to the feature (by `feature-id`, or by the file name when it has none)."""

    path = feature.page.path
    feature_id = normalize_feature_id(feature.feature_id)
    root = (path.parent.parent / directory).resolve()
    found: list[Any] = []
    for page in wiki_pages:
        try:
            page.path.resolve().relative_to(root)
        except (ValueError, OSError, RuntimeError):
            continue
        page_feature_id = page.frontmatter.get("feature-id")
        if not isinstance(page_feature_id, str) or not page_feature_id.strip():
            page_feature_id = feature_id_from_path(page.path)
        if isinstance(page_feature_id, str) and normalize_feature_id(page_feature_id) == feature_id:
            found.append(page)
    return found


def _ui_track_check(
    feature: FeaturePage,
    tracks: DesignTracks,
    wiki_pages: list[Any],
    model: WorkspaceModel,
    *,
    proposal: bool,
) -> dict[str, Any]:
    """The UI track (CONTRACTS 2.4): `done` needs design pages that cover every scoped app with a UI, `not-applicable` a reason.

    A `pending` track is a blocker in a proposal; in the copy-only preflight it asks whether the track could be completed.
    """

    path = feature.page.path
    state = tracks.ui
    if state == "not-applicable":
        if not (tracks.ui_reason or "").strip():
            return _check("ui-exemption-reason-required", "blocked", "A UI track that is `not-applicable` needs a non-blank `ui-reason`.", path)
        return _check("ui-track", "pass", f"The UI track is `not-applicable`: {tracks.ui_reason.strip()}", path)
    if state == "pending" and proposal:
        return _check("design-tracks-incomplete", "blocked", "The proposal leaves the UI track `pending`; set it to `done` or to `not-applicable` with a reason.", path)
    wanted = ui_apps(active_scope(feature.apps, model), model)
    if not wanted:
        return _check("ui-track", "pass", "No app with a UI is in scope; the UI track needs no design page.", path)
    pages = _feature_pages_in(feature, wiki_pages, "design")
    if not pages:
        return _check(
            "design-coverage-incomplete",
            "blocked",
            f"An app with a UI in scope ({', '.join(f'`{app}`' for app in wanted)}) needs a design page that lists it under `apps`, or a UI exemption with a reason.",
            path,
        )
    malformed = [page for page in pages if getattr(page, "parse_errors", [])]
    if malformed:
        return _check("ui-track", "unknown", "A matching design page has malformed frontmatter.", malformed[0].path)
    covered = {
        app
        for page in pages
        for app in (page.frontmatter.get("apps") if isinstance(page.frontmatter.get("apps"), list) else [])
        if isinstance(app, str)
    }
    missing = [app for app in wanted if app not in covered]
    if missing:
        return _check(
            "design-coverage-incomplete",
            "blocked",
            f"No design page covers {', '.join(f'`{app}`' for app in missing)}; list every app with a UI under `apps` in a design page.",
            pages[0].path,
        )
    return _check("ui-track", "pass", "Design pages cover every scoped app with a UI; the designer must verify the design itself.", pages[0].path)


def _technical_track_checks(
    feature: FeaturePage,
    tracks: DesignTracks,
    wiki_pages: list[Any],
    model: WorkspaceModel,
    *,
    proposal: bool,
) -> list[dict[str, Any]]:
    """The technical track (CONTRACTS 2.4): `done` needs a complete technical design page and, for API work, the API contract."""

    path = feature.page.path
    state = tracks.technical
    api_work = api_surface_declared(section_text(feature.page.body, "API surface"))
    if state == "not-applicable":
        if not (tracks.technical_reason or "").strip():
            return [_check("technical-track-required", "blocked", "A technical track that is `not-applicable` needs a non-blank `technical-reason`.", path)]
        if api_work:
            return [_check("technical-track-required", "blocked", "The technical track cannot be `not-applicable` while the API surface declares API work.", path)]
        return [_check("technical-track", "pass", f"The technical track is `not-applicable`: {tracks.technical_reason.strip()}", path)]
    if state == "pending" and proposal:
        return [_check("design-tracks-incomplete", "blocked", "The proposal leaves the technical track `pending`; set it to `done`, or to `not-applicable` with a reason.", path)]
    pages = _feature_pages_in(feature, wiki_pages, "technical-design")
    if not pages:
        return [_check("technical-design-incomplete", "blocked", "The technical track needs a technical design page for this feature in `technical-design/`.", path)]
    if len(pages) > 1:
        return [_check("technical-design-incomplete", "blocked", f"The feature has {len(pages)} technical design pages; it has one.", pages[0].path)]
    page = pages[0]
    if getattr(page, "parse_errors", []):
        return [_check("technical-track", "unknown", "The technical design page has malformed frontmatter.", page.path)]
    criteria = [item.id for item in parse_criteria(feature.page.body, feature.feature_id) if item.id]
    problems = technical_design_problems(
        page.frontmatter,
        page.body,
        feature_id=feature.feature_id,
        scope=active_scope(feature.apps, model),
        criteria_ids=criteria,
    )
    checks: list[dict[str, Any]] = []
    for code in dict.fromkeys(code for code, _message in problems):
        messages = [message for item, message in problems if item == code]
        extra = f" (and {len(messages) - 4} more)" if len(messages) > 4 else ""
        checks.append(_check(code, "blocked", " ".join(messages[:4]) + extra, page.path))
    if not problems:
        checks.append(_check("technical-track", "pass", "The technical design page is complete and its Test strategy names every criterion; the tech lead must verify the design itself.", page.path))
    if api_work:
        checks.append(_api_contract_check(feature, wiki_pages, require_implemented=False))
    return checks


def _reaffirm_check(feature: FeaturePage, tracks: DesignTracks) -> dict[str, Any]:
    path = feature.page.path
    if tracks.reaffirm:
        return _check(
            "design-reaffirm-pending",
            "blocked",
            f"The other track changed since {', '.join(f'`{track}`' for track in tracks.reaffirm)} was settled; its owner reaffirms it with no page change before the handoff.",
            path,
        )
    return _check("design-reaffirm-pending", "pass", "No design track awaits reaffirmation.", path)


def _return_route_checks(feature: FeaturePage, model: WorkspaceModel) -> list[dict[str, Any]]:
    """The app stages a return from implementation accepts (CONTRACTS 2.3, 2.4).

    The return applies while no app is in QA or beyond; a release of some apps and not all sends the changes to a new feature,
    and an app in QA goes back through the QA return.
    """

    path = feature.page.path
    if status_rank(feature.status) < status_rank("in-dev"):
        return [_check("return-stage", "pass", "No app has started, so there is no evidence to archive.", path)]
    evidence = read_feature_evidence(feature.page.body)
    stages = app_stages(active_scope(feature.apps, model), evidence)
    released = [app for app, stage in stages.items() if stage == "released"]
    if released and len(released) < len(stages):
        return [
            _check(
                "partial-release-requires-new-feature",
                "blocked",
                f"{', '.join(f'`{app}`' for app in released)} is released and the other apps are not: put the changed requirements or contracts in a new feature, and an implementation defect in a bug.",
                path,
            )
        ]
    in_qa = [app for app, stage in stages.items() if stage in {"in-qa", "ready-for-release", "released"}]
    if in_qa:
        return [
            _check(
                "app-stage-mismatch",
                "blocked",
                f"{', '.join(f'`{app}`' for app in in_qa)} is in QA or later, so this return does not apply: return it with the QA return (`qa-return-spec` or `qa-return-design`) or reopen it once released.",
                path,
            )
        ]
    return [_check("return-stage", "pass", "No app is in QA or later; the return archives the delivery evidence of the apps that were delivered.", path)]


def _contract_binding_checks(feature: FeaturePage, wiki_pages: list[Any], named_apps: Iterable[str] | None) -> list[dict[str, Any]]:
    """The Contract cell of the delivery rows an action adds cites the contract as it is now (CONTRACTS 3.4)."""

    if named_apps is None:
        return []
    rows, _problems = parse_delivery_rows(feature.page.body)
    named = set(named_apps)
    current = {
        citation
        for page in matching_contract_pages(feature, wiki_pages)
        if (citation := contract_page_citation(page.frontmatter, page.body)) is not None
    }
    path = feature.page.path
    stale: list[str] = []
    for row in rows:
        if row.app not in named:
            continue
        cited = clean_cell(row.contract)
        if cited.lower() == "none":
            if current:
                stale.append(f"`{row.app}` cites no contract but the feature has one ({', '.join(f'`{item}`' for item in sorted(current))})")
        elif cited not in current:
            stale.append(f"`{row.app}` cites `{cited}`" + (f", the current contract is {', '.join(f'`{item}`' for item in sorted(current))}" if current else ", but the feature has no contract"))
    if stale:
        return [_check("contract-binding-stale", "blocked", "The Contract cell is not the current contract: " + "; ".join(stale) + ".", path)]
    return [_check("contract-binding-stale", "pass", "The Contract cell of every delivered app is the current contract of the feature, or `none` when it has none.", path)]


def _requirements_check(feature: FeaturePage, requirement_pages: list[Any], *, require_done: bool) -> dict[str, Any]:
    path = feature.page.path
    declared = feature.apps
    if not declared:
        return _check("app-requirements", "unknown", "App requirements cannot be evaluated without a valid feature app scope.", path)
    by_app: dict[str, list[Any]] = {}
    feature_id = normalize_feature_id(feature.feature_id)
    for requirement in requirement_pages:
        requirement_id = getattr(requirement, "feature_id", None)
        app_id = getattr(requirement, "app", None)
        if not isinstance(requirement_id, str) or requirement_id.strip().lower() != feature_id or not isinstance(app_id, str):
            continue
        by_app.setdefault(app_id.strip().lower(), []).append(requirement)
    problems: list[str] = []
    unknown = False
    for app_id in declared:
        matches = by_app.get(app_id.strip().lower(), [])
        if not matches:
            problems.append(f"missing requirement for `{app_id}`")
            continue
        if len(matches) > 1:
            problems.append(f"duplicate requirements for `{app_id}`")
            unknown = True
            continue
        requirement = matches[0]
        if getattr(requirement, "parse_errors", []):
            problems.append(f"malformed requirement for `{app_id}`")
            unknown = True
            continue
        status = getattr(requirement, "status", None)
        if status not in {"pending", "in-progress", "done"}:
            problems.append(f"unsupported requirement status for `{app_id}`")
            unknown = True
        elif require_done and status != "done":
            problems.append(f"requirement for `{app_id}` is `{status}`")
    if problems:
        status = "unknown" if unknown else "blocked"
        return _check("app-requirements", status, "; ".join(problems) + ".", path)
    message = "Every declared app has a completed requirement." if require_done else "Every declared app has a handed-off app requirement."
    return _check("app-requirements", "pass", message, path)


def matching_contract_pages(feature: FeaturePage, wiki_pages: list[Any]) -> list[Any]:
    """The API contract pages that cover a feature: its own, those with its `feature-id`, and those its pages link."""

    path = feature.page.path
    feature_id = normalize_feature_id(feature.feature_id)
    wiki_root = path.parent.parent
    api_root = wiki_root / "api-contracts"
    matching: list[Any] = []
    for page in wiki_pages:
        try:
            page.path.resolve().relative_to(api_root.resolve())
        except (ValueError, OSError, RuntimeError):
            continue
        page_feature_id = page.frontmatter.get("feature-id")
        if not isinstance(page_feature_id, str) or not page_feature_id.strip():
            page_feature_id = feature_id_from_path(page.path)
        if isinstance(page_feature_id, str) and normalize_feature_id(page_feature_id) == feature_id:
            matching.append(page)

    # Include contracts explicitly referenced from the feature or any scoped
    # app requirement, including shared contracts whose own filename or
    # feature-id is intentionally independent of this feature.
    source_pages = [feature.page]
    for page in wiki_pages:
        page_feature_id = page.frontmatter.get("feature-id")
        if not isinstance(page_feature_id, str) or normalize_feature_id(page_feature_id) != feature_id:
            continue
        if page.frontmatter.get("app") not in feature.apps:
            continue
        try:
            page.path.resolve().relative_to((wiki_root / "app-requirements").resolve())
        except (ValueError, OSError, RuntimeError):
            continue
        source_pages.append(page)
    for source in source_pages:
        for target in api_contract_link_targets(source.body, source.path, wiki_root):
            for page in wiki_pages:
                if page.path.resolve() == target and page not in matching:
                    matching.append(page)
    return matching


def _api_contract_check(feature: FeaturePage, wiki_pages: list[Any], *, require_implemented: bool) -> dict[str, Any]:
    path = feature.page.path
    section_applicable = api_surface_declared(section_text(feature.page.body, "API surface"))
    matching = matching_contract_pages(feature, wiki_pages)
    if not matching and not section_applicable:
        return _check("api-contract", "pass", "No API surface is declared for this feature.", path)
    if not matching:
        return _check("api-contract", "blocked", "A substantive API surface requires a matching API contract page.", path)
    unknown = [page for page in matching if getattr(page, "parse_errors", [])]
    if unknown:
        return _check("api-contract", "unknown", "A matching API contract page has malformed frontmatter.", unknown[0].path)
    statuses = [page.frontmatter.get("status") for page in matching]
    if any(status not in {"draft", "agreed", "implemented"} for status in statuses):
        return _check("api-contract", "unknown", "A matching API contract has an unsupported status.", matching[0].path)
    if require_implemented and any(status != "implemented" for status in statuses):
        return _check("api-contract", "blocked", "Every applicable API contract must be `implemented` before Done.", matching[0].path)
    if any(status == "draft" for status in statuses):
        return _check("api-contract", "blocked", "An applicable API contract is still `draft`.", matching[0].path)
    return _check("api-contract", "pass", "Applicable API contracts are ready for this action.", matching[0].path)


def api_contract_link_targets(body: str, source_path: Path, wiki_root: Path) -> list[Path]:
    """Return the API contract paths that a page body links or names, in the order they appear."""

    targets: list[Path] = []
    for raw_target in [*extract_markdown_links(body), *_wiki_path_references(body, "api-contracts")]:
        target = _resolve_api_link(source_path, raw_target, wiki_root)
        if target is not None:
            targets.append(target)
    return targets


def _resolve_api_link(source_path: Path, raw_target: str, wiki_root: Path) -> Path | None:
    """The API contract page a link or a plain path reference names, or ``None``. The shared resolver refuses an unsafe path."""

    decoded, _problem = decoded_link_path(raw_target)
    if decoded is None:
        return None
    try:
        parsed = urlsplit(decoded)
    except ValueError:
        return None
    if parsed.scheme or parsed.netloc:
        return None
    normalized = parsed.path
    lowered = normalized.lower()
    marker = "knowledge/wiki/"
    root = wiki_root.resolve()
    if marker in lowered:
        suffix = normalized[lowered.index(marker) + len(marker) :]
        if not suffix.lower().startswith("api-contracts/"):
            return None
        target = resolve_to_path(root, root, suffix)
    elif lowered.startswith("wiki/api-contracts/"):
        target = resolve_to_path(root, root, normalized[len("wiki/") :])
    elif lowered.startswith("api-contracts/"):
        target = resolve_to_path(root, root, normalized)
    else:
        target = resolve_relative_markdown_link(source_path, normalized, wiki_root)
    if target is None:
        return None
    try:
        target.relative_to((wiki_root / "api-contracts").resolve())
    except ValueError:
        return None
    return target


def _revalidation_check(
    feature: FeaturePage,
    gated_domains: set[str],
    owned_domains: set[str],
) -> dict[str, Any]:
    domains, errors = parse_revalidation(feature.page.frontmatter.get("revalidation"))
    path = feature.page.path
    if errors:
        return _check("revalidation", "unknown", "; ".join(errors), path)
    pending = [domain for domain in domains if domain in gated_domains]
    blocked = [domain for domain in pending if domain not in owned_domains]
    owned = [domain for domain in pending if domain in owned_domains]
    if blocked:
        message = "Pending revalidation domains remain before this action: " + ", ".join(blocked) + "."
        if owned:
            message += " The current workflow must also verify and clear: " + ", ".join(owned) + "."
        return _check("revalidation", "blocked", message, path)
    if owned:
        return _check(
            "revalidation",
            "pass",
            "The current workflow must verify and clear pending revalidation domains: " + ", ".join(owned) + ".",
            path,
        )
    if domains:
        return _check("revalidation", "pass", "Pending revalidation domains do not affect this action: " + ", ".join(domains) + ".", path)
    return _check("revalidation", "pass", "No pending revalidation domains remain.", path)


def _app_revalidation_check(feature: FeaturePage, apps: Iterable[str], owned_domains: set[str]) -> dict[str, Any]:
    """The per-app revalidation of the named apps: the domains this action clears must be verified; the others do not gate it."""

    path = feature.page.path
    domains, errors = parse_app_revalidation(feature.page.frontmatter.get("app-revalidation"))
    if errors:
        return _check("app-revalidation", "unknown", "; ".join(errors), path)
    owned = {app: [domain for domain in domains.get(app, []) if domain in owned_domains] for app in apps}
    owned = {app: items for app, items in owned.items() if items}
    if owned:
        listed = "; ".join(f"`{app}`: {', '.join(items)}" for app, items in owned.items())
        return _check("app-revalidation", "pass", f"The current workflow must verify and clear pending app revalidation domains: {listed}.", path)
    return _check("app-revalidation", "pass", "No pending app revalidation domains remain for the apps this action delivers.", path)


def _delivery_evidence_checks(feature: FeaturePage, named_apps: Iterable[str] | None = None) -> list[dict[str, Any]]:
    """The delivery evidence rows of the apps an action delivers (CONTRACTS 2.4, 5.1).

    `named_apps` are the apps the proposal delivers. ``None`` is the copy-only preflight, which has no proposal: the rows
    arrive with the proposal, so the evidence is reported as not yet supplied.
    """

    rows, problems = parse_delivery_rows(feature.page.body)
    path = feature.page.path
    if named_apps is None:
        return [_check("delivery-evidence", "blocked", "No delivery evidence was supplied: the proposal adds one valid row for each app it delivers.", path)]
    named = list(dict.fromkeys(named_apps))
    if not named:
        return [_check("delivery-evidence", "blocked", "The proposal names no app: add one delivery evidence row for each app it delivers.", path)]
    present = {row.app for row in rows}
    missing = [app for app in named if app not in present]
    invalid = [problem.message for problem in problems if problem.subject is None or problem.subject in named]
    if missing:
        return [_check("delivery-evidence", "blocked", "Delivery evidence is missing for: " + ", ".join(f"`{app}`" for app in missing) + ".", path)]
    if invalid:
        return [_check("delivery-evidence", "blocked", "; ".join(invalid), path)]
    return [
        _check(
            "delivery-evidence",
            "pass",
            f"Delivery evidence has a valid artifact, contract, implementation, tests and basis for {len(named)} app(s); an agent must verify the references.",
            path,
        )
    ]


def _api_surface_app_check(feature: FeaturePage, model: WorkspaceModel) -> dict[str, Any]:
    """API work needs an active app in scope that serves an API (`unknown` counts as serving one)."""

    path = feature.page.path
    if not api_surface_declared(section_text(feature.page.body, "API surface")):
        return _check("api-surface-without-api-app", "pass", "No API surface is declared for this feature.", path)
    if model.scope_serves_api(feature.apps):
        return _check("api-surface-without-api-app", "pass", "An active app in scope serves an API.", path)
    return _check("api-surface-without-api-app", "blocked", api_surface_without_api_app_message(model, feature.feature_id, feature.apps), path)


def _action_transition_reason(spec: ActionSpec, classification: str, checks: list[dict[str, Any]]) -> str:
    if classification == "ready":
        if spec.action.startswith("reopen-"):
            return "Action mapping and observable source checks pass; explicit impact review and user confirmation remain outstanding." + _warning_note(checks)
        if spec.action == "dev-done":
            return "Observable delivery evidence checks pass; an agent must verify artifacts and obtain final confirmation." + _warning_note(checks)
        return f"Observable {spec.action} checks pass; semantic review and user confirmation remain outstanding." + _warning_note(checks)
    if classification == "blocked":
        messages = [check["message"] for check in checks if check["status"] in {"blocked", "review"}]
        return "; ".join(messages) or f"A known {spec.action} prerequisite is unmet."
    messages = [check["message"] for check in checks if check["status"] == "unknown"]
    return "; ".join(messages) or "Required transition facts are unknown."


def _capability_checks(root: Path, action: str = SUPPORTED_ACTION) -> tuple[list[dict[str, Any]], dict[str, str]]:
    spec = ACTION_BY_ID.get(action)
    if spec is None:
        return [
            _check(
                "capability-action",
                "unknown",
                f"Capability action `{action}` is not registered.",
                root,
            )
        ], {}
    checks: list[dict[str, Any]] = []
    invocations: dict[str, str] = {}
    for role, relative in _ACTION_SURFACE_PATHS[action].items():
        path = root / relative
        code = f"capability-{role}" if action == SUPPORTED_ACTION else f"capability-{action}-{role}"
        try:
            text = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as exc:
            checks.append(_check(code, "unknown", f"Unable to read generated {role} `{action}` capability: {exc}.", path))
            continue
        markers = _ACTION_MARKERS[action][role]
        if not text.strip():
            checks.append(_check(code, "unknown", f"Generated {role} `{action}` capability is empty.", path))
            continue
        if not all(marker in text for marker in markers):
            checks.append(
                _check(
                    code,
                    "unknown",
                    f"Generated {role} capability does not expose the supported `{action}` invocation and contract marker.",
                    path,
                )
            )
            continue
        checks.append(_check(code, "pass", f"Generated {role} `{action}` capability is available.", path))
        invocations[role] = _ACTION_INVOCATIONS[action][role]
    return checks, invocations


def _capability_surfaces(
    root: Path,
    checks_by_action: dict[str, list[dict[str, Any]]],
    invocations_by_action: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    """Expose each generated invocation surface independently.

    Codex and Claude files are optional views over the same copy-only action.
    A missing one must remain visible to callers without making an available
    sibling surface unusable.
    """

    surfaces: list[dict[str, Any]] = []
    for action in SUPPORTED_ACTIONS:
        by_code = {check["code"]: check for check in checks_by_action.get(action, [])}
        for role, relative in _ACTION_SURFACE_PATHS[action].items():
            code = f"capability-{role}" if action == SUPPORTED_ACTION else f"capability-{action}-{role}"
            check = by_code.get(code)
            invocation = invocations_by_action.get(action, {}).get(role)
            surface: dict[str, Any] = {
                "action": action,
                "role": role,
                "path": str(root / relative),
                "available": invocation is not None,
                "check": check["status"] if check else "unknown",
            }
            if invocation is not None:
                surface["invocation_template"] = invocation
            surfaces.append(surface)
    return surfaces


def _workspace_identity_checks(root: Path, inspection: WorkspaceInspection) -> list[dict[str, Any]]:
    diagnostics = inspection.contract_diagnostics
    hard = [diagnostic for diagnostic in diagnostics if _is_hard_identity_diagnostic(diagnostic)]
    checks: list[dict[str, Any]] = []
    identity_path = inspection.manifest.path if inspection.manifest else inspection.answers_path
    if detect_workspace_kind(root) == "unknown":
        checks.append(_check("workspace-identity", "unknown", "Workspace kind is unknown; transition scope cannot be established.", identity_path))
    elif inspection.project_name is None:
        checks.append(_check("workspace-identity", "unknown", "Workspace project identity or app scope is incomplete.", identity_path))
    elif hard:
        message = "; ".join(sorted({diagnostic.message for diagnostic in hard}))
        checks.append(_check("workspace-identity", "unknown", f"Workspace identity is drifted or unsupported: {message}", hard[0].path))
    else:
        checks.append(_check("workspace-identity", "pass", "Workspace identity and declared scope are available.", identity_path))
    return checks


def _scope_check(feature: FeaturePage, inspection: WorkspaceInspection, root: Path, *, allow_retired: bool = False) -> dict[str, Any]:
    path = feature.page.path
    value = feature.page.frontmatter.get("apps")
    if not isinstance(value, list):
        return _check("app-scope", "unknown", "Feature `apps` must be a list of app IDs of this workspace.", path)
    if not value:
        return _check("app-scope", "blocked", "Feature must list at least one app in scope.", path)
    invalid = [item for item in value if not isinstance(item, str)]
    if invalid:
        return _check("app-scope", "unknown", f"Feature app scope contains values that are not app IDs: {invalid!r}.", path)
    available = set(inspection.app_ids)
    retired = inspection.model.retired_apps(value)
    if retired and feature.status != "released" and not allow_retired:
        # A retired app stays valid on a feature that is released, as history; in progress it is flagged until the scope is edited
        # (the scope edit itself is how it is removed, so it is not blocked).
        return _check("app-retired-in-scope", "blocked", retired_in_scope_message(feature.feature_id, retired), path)
    available |= set(retired)
    missing = sorted(set(value) - available)
    if missing:
        hint = "" if available else " This workspace declares no apps; register them with `prism app add`."
        return _check(
            "app-scope",
            "blocked",
            f"Feature apps {', '.join(missing)} are outside the available workspace scope.{hint}",
            path,
        )
    return _check("app-scope", "pass", "Feature apps are valid and within the available workspace scope.", path)


def _section_check(feature: FeaturePage, heading: str, code: str) -> dict[str, Any]:
    path = feature.page.path
    body = section_text(feature.page.body, heading)
    normalized = re.sub(r"\s+", " ", body).strip()
    if not normalized:
        return _check(code, "blocked", f"Required `{heading}` section is empty or missing.", path)
    if any(pattern.search(normalized) for pattern in _PLACEHOLDER_PATTERNS):
        return _check(code, "blocked", f"Required `{heading}` section still contains a template placeholder.", path)
    return _check(code, "pass", f"Required `{heading}` section contains observable content.", path)


def _acceptance_criteria_check(feature: FeaturePage) -> dict[str, Any]:
    """Require at least one non-empty, list-shaped acceptance criterion."""

    path = feature.page.path
    body = section_text(feature.page.body, "Acceptance criteria")
    entries: list[str] = []
    for raw_line in body.splitlines():
        line = raw_line.strip()
        match = re.match(r"^(?:[-*+]\s+|\d+[.)]\s+)(.*)$", line)
        if not match:
            continue
        content = re.sub(r"^\[[ xX]\]\s*", "", match.group(1)).strip()
        if content and not content.startswith("<!--"):
            entries.append(content)
    if not entries:
        return _check(
            "acceptance-criteria",
            "blocked",
            "Acceptance criteria must contain at least one non-empty list entry.",
            path,
        )
    if any(any(pattern.search(entry) for pattern in _PLACEHOLDER_PATTERNS) for entry in entries):
        return _check(
            "acceptance-criteria",
            "blocked",
            "Acceptance criteria still contain a template placeholder.",
            path,
        )
    return _check(
        "acceptance-criteria",
        "pass",
        f"Acceptance criteria contain {len(entries)} observable list entr{'y' if len(entries) == 1 else 'ies'}.",
        path,
    )


def _app_section_check(feature: FeaturePage, model: WorkspaceModel) -> dict[str, Any]:
    """Reconcile declared feature apps with the body scope section."""

    path = feature.page.path
    declared = feature.page.frontmatter.get("apps")
    body = section_text(feature.page.body, "App scope")
    if not body.strip():
        return _check("app-section", "blocked", "Required `App scope` section is empty or missing.", path)
    if not isinstance(declared, list) or any(not isinstance(item, str) for item in declared):
        return _check(
            "app-section",
            "unknown",
            "App scope cannot be reconciled until frontmatter `apps` is a list of strings.",
            path,
        )
    # A scope line names an app of the workspace: its ID, as the model knows it.
    scope_ids = sorted({app.id for app in model.apps} | set(declared), key=len, reverse=True)
    scope_line = re.compile(
        r"^\s*[-*]\s+\*{0,2}(" + "|".join(re.escape(item) for item in scope_ids) + r")\*{0,2}\s*:\s*(.*?)\s*$",
        re.IGNORECASE,
    )
    rows: dict[str, str] = {}
    for raw_line in body.splitlines():
        match = scope_line.match(raw_line) if scope_ids else None
        if match:
            rows[match.group(1).lower()] = match.group(2).strip()
    if not rows:
        return _check(
            "app-section",
            "blocked",
            "App scope must list at least one declared app with a description.",
            path,
        )
    missing = [app_id for app_id in declared if not rows.get(app_id.lower())]
    if missing:
        return _check(
            "app-section",
            "blocked",
            f"App scope is missing a non-empty entry for: {', '.join(missing)}.",
            path,
        )
    invalid_entries: list[str] = []
    for app_id, description in rows.items():
        normalized_description = re.sub(r"\s+", " ", description).strip()
        if _APP_PLACEHOLDER.fullmatch(normalized_description):
            invalid_entries.append(f"{app_id} retains the template placeholder")
            continue
        if app_id in {item.lower() for item in declared} and normalized_description.lower() in {
            "not in scope",
            "n/a",
            "none",
        }:
            invalid_entries.append(f"{app_id} is declared but marked not in scope")
            continue
        if app_id not in {item.lower() for item in declared} and normalized_description.lower() not in {
            "not in scope",
            "n/a",
            "none",
        }:
            invalid_entries.append(f"{app_id} describes work but is not declared in frontmatter")
    if invalid_entries:
        return _check(
            "app-section",
            "blocked",
            "App scope does not match frontmatter: " + "; ".join(invalid_entries) + ".",
            path,
        )
    return _check(
        "app-section",
        "pass",
        "App scope lists each declared feature app with a description.",
        path,
    )


def _open_questions_check(feature: FeaturePage) -> dict[str, Any]:
    rows, errors = parse_open_question_rows(feature.page.body)
    path = feature.page.path
    if errors:
        return _check("open-questions", "unknown", "; ".join(errors), path)
    malformed_rows: list[str] = []
    for row in rows:
        if not row["number"] or not row["question"]:
            malformed_rows.append("question number and text are required")
        if row["owner"] not in VALID_OPEN_QUESTION_OWNERS:
            malformed_rows.append(f"unsupported question owner `{row['owner']}`")
        status = row["status"]
        if status != "open" and not (status.startswith("resolved:") and status[len("resolved:") :].strip()):
            malformed_rows.append(f"unsupported question status `{status}`")
    if malformed_rows:
        return _check("open-questions", "unknown", "; ".join(_unique_strings(malformed_rows)), path)
    open_po = [row for row in rows if row["owner"] == "po" and row["status"] == "open"]
    if open_po:
        return _check("open-questions", "blocked", _open_questions_message("PO-owned", [row["number"] for row in open_po]), path)
    return _check("open-questions", "pass", "No open PO-owned questions remain.", path)


def _advisory_check(feature: FeaturePage) -> dict[str, Any]:
    value = feature.advisory_review
    path = feature.page.path
    if value not in VALID_ADVISORY_REVIEW_STATES:
        return _check("advisory-review", "unknown", "Advisory review state is missing or unsupported.", path)
    if value == "pending":
        return _check("advisory-review", "review", "Advisory review is pending; review with the board before handoff.", path)
    if value == "skipped":
        reason = feature.page.frontmatter.get("advisory-skip-reason")
        if not isinstance(reason, str) or not reason.strip():
            return _check("advisory-review", "unknown", "Skipped advisory review requires a non-empty reason.", path)
    return _check("advisory-review", "pass", f"Advisory review state is `{value}`.", path)


def _advisory_actions_check(feature: FeaturePage, wiki_pages: list[Any]) -> dict[str, Any]:
    """Check required board actions without treating deferred work as a blocker."""

    path = feature.page.path
    if feature.advisory_review in {"not-needed", "skipped"}:
        return _check("advisory-actions", "pass", "No advisory action checklist is required for this feature.", path)
    if feature.advisory_review != "done":
        return _check("advisory-actions", "review", "Advisory review is not complete; required actions cannot be evaluated yet.", path)
    feature_id = normalize_feature_id(feature.feature_id)
    advisory_root = path.parent.parent / "advisory"
    reviews: list[Any] = []
    for page in wiki_pages:
        try:
            page.path.resolve().relative_to(advisory_root.resolve())
        except (ValueError, OSError, RuntimeError):
            continue
        page_feature_id = page.frontmatter.get("feature-id")
        if not isinstance(page_feature_id, str) or not page_feature_id.strip():
            page_feature_id = feature_id_from_path(page.path)
        if isinstance(page_feature_id, str) and normalize_feature_id(page_feature_id) == feature_id:
            reviews.append(page)
    if len(reviews) != 1:
        return _check(
            "advisory-actions",
            "unknown",
            "A unique advisory review page is required to evaluate actions required before development.",
            path,
        )
    review = reviews[0]
    pending, errors = parse_advisory_required_actions(review.body)
    if errors:
        return _check("advisory-actions", "unknown", "; ".join(errors), review.path)
    if pending:
        return _check(
            "advisory-actions",
            "blocked",
            "Advisory actions required before development remain open: " + "; ".join(pending) + ".",
            review.path,
        )
    return _check("advisory-actions", "pass", "All advisory actions required before development are checked; deferred actions remain informational.", review.path)


def _relevant_integrity_checks(
    feature: FeaturePage,
    lint_result: WikiLintResult,
    *,
    ignore_codes: set[str] | None = None,
) -> list[dict[str, Any]]:
    path = feature.page.path.resolve()
    wiki_root = path.parent.parent
    linked_paths: set[Path] = set()
    for raw_target in extract_markdown_links(feature.page.body):
        target = resolve_relative_markdown_link(feature.page.path, raw_target, wiki_root)
        if target is not None:
            linked_paths.add(target.resolve())
    relevant: list[WikiDiagnostic] = []
    for filename in ("SCHEMA.md", "LIFECYCLE.md", "ACTIONS.md", "index.md", "status-board.md"):
        required_path = wiki_root / filename
        if _required_wiki_file_unreadable(required_path):
            relevant.append(
                _diag(
                    "unreadable-required-wiki-file",
                    "error",
                    required_path,
                    f"Unable to read required wiki file `{filename}`.",
                    feature.feature_id,
                )
            )
    for diagnostic in lint_result.diagnostics:
        if ignore_codes and diagnostic.code in ignore_codes:
            continue
        if diagnostic.code in WIKI_BLOCKER_CODES or not diagnostic.gates:
            # A finding that asks for a review (freshness) or describes a page's sources never gates a lifecycle action.
            continue
        diagnostic_path = diagnostic.resolved_path
        if diagnostic.code == "unknown-app-id" and diagnostic_path == path:
            # The feature's own scope: the app-scope check reports an app outside the workspace as blocked.
            continue
        if diagnostic.code in {"app-retired-in-scope", "api-surface-without-api-app"} and diagnostic_path == path:
            # The feature's own scope: the app-scope and api-surface checks report these as blocked.
            continue
        is_global_contract = diagnostic.code in {"missing-required-wiki-file", "malformed-index", "malformed-status-board"} and diagnostic_path.name in {
            "SCHEMA.md",
            "LIFECYCLE.md",
            "ACTIONS.md",
            "index.md",
            "status-board.md",
        }
        diagnostic_feature_id = feature_id_from_path(diagnostic_path)
        if (
            is_global_contract
            or diagnostic.feature_id == feature.feature_id
            or diagnostic_feature_id == feature.feature_id
            or diagnostic_path == path
            or diagnostic_path in linked_paths
        ):
            relevant.append(diagnostic)
    if not relevant:
        return [_check("source-integrity", "pass", "No additional feature integrity issues block this request.", feature.page.path)]
    checks: list[dict[str, Any]] = []
    for diagnostic in sorted(relevant, key=lambda item: (item.path, item.code, item.message)):
        checks.append(
            _check(
                f"source-integrity:{diagnostic.code}",
                "unknown",
                diagnostic.message,
                Path(diagnostic.path),
            )
        )
    return checks


def _required_wiki_file_unreadable(path: Path) -> bool:
    """Report whether an existing required wiki file cannot be read as UTF-8.

    Inside ``evaluate_transition_summaries`` each file is read once for all features.
    """

    reads = _REQUIRED_WIKI_FILE_READS.get()
    if reads is not None and path in reads:
        return reads[path]
    try:
        if path.exists():
            path.read_text(encoding="utf-8-sig")
        unreadable = False
    except (OSError, UnicodeError):
        unreadable = True
    if reads is not None:
        reads[path] = unreadable
    return unreadable


def _classify_checks(checks: list[dict[str, Any]], *, capability_available: bool = False) -> str:
    unknown_checks = [
        check
        for check in checks
        if check["status"] == "unknown"
        and (not capability_available or not check["code"].startswith("capability-"))
    ]
    if unknown_checks:
        return "unknown"
    if any(check["status"] in {"blocked", "review"} for check in checks):
        return "blocked"
    # A `warning` check is non-blocking: it names something the approver should know and never gates the action.
    return "ready"


def _warning_note(checks: list[dict[str, Any]]) -> str:
    warnings = [check["message"] for check in checks if check["status"] == "warning"]
    return (" Warnings: " + "; ".join(warnings)) if warnings else ""


def _transition_reason(classification: str, checks: list[dict[str, Any]]) -> str:
    if classification == "ready":
        return "Observable po-handoff checks pass; semantic completeness and user confirmation remain outstanding." + _warning_note(checks)
    if classification == "blocked":
        messages = [check["message"] for check in checks if check["status"] in {"blocked", "review"}]
        return "; ".join(messages) or "A known po-handoff prerequisite is unmet."
    messages = [check["message"] for check in checks if check["status"] == "unknown"]
    return "; ".join(messages) or "Required transition facts are unknown."


def _unknown_transition(
    feature_id: str,
    reason: str,
    *,
    sources: list[str],
    action: str | None,
    checks: list[dict[str, Any]],
    source_status: str | None = None,
    source_owner: str | None = None,
    source_path: str | None = None,
) -> dict[str, Any]:
    return {
        "version": TRANSITION_SCHEMA_VERSION,
        "feature_id": feature_id or "unknown",
        "source_status": source_status,
        "source_owner": source_owner,
        "source_path": source_path,
        "target_status": None,
        "target_owner": None,
        "action": action,
        "classification": "unknown",
        "supported": False,
        "checks": checks,
        "sources": _unique_strings(sources),
        "reason": reason,
    }


def _feature_summary(feature: FeaturePage) -> dict[str, Any]:
    return {
        "id": feature.feature_id,
        "title": feature.title,
        "status": feature.status,
        "owner": feature.owner,
        "advisory_review": feature.advisory_review,
        "apps": feature.apps,
        "path": str(feature.page.path),
    }


def _duplicate_feature_ids(features: list[FeaturePage]) -> set[str]:
    counts: dict[str, int] = {}
    for feature in features:
        key = normalize_feature_id(feature.feature_id)
        counts[key] = counts.get(key, 0) + 1
    return {feature_id for feature_id, count in counts.items() if count > 1}


def _check(code: str, status: str, message: str, path: Path | None = None) -> dict[str, Any]:
    check: dict[str, Any] = {"code": code, "status": status, "message": message}
    if path is not None:
        check["path"] = str(path)
    return check


def _diag(code: str, severity: str, path: Path, message: str, feature_id: str | None = None) -> WikiDiagnostic:
    return WikiDiagnostic(code=code, severity=severity, path=str(path), message=message, feature_id=feature_id)


def _is_hard_identity_diagnostic(diagnostic: Any) -> bool:
    code = getattr(diagnostic, "code", "")
    if code in {"missing-copier-answers", "missing-copier-template-source", "missing-workspace-manifest"}:
        return False
    return code in _HARD_IDENTITY_DIAGNOSTIC_CODES or "drift" in code or getattr(diagnostic, "severity", "") == "error"


def _is_link(path: Path) -> bool:
    """Whether `path` itself is a symlink or a reparse point, from an `lstat` that never follows it."""

    try:
        return reparse_kind(path.lstat()) != "none"
    except (OSError, RuntimeError, ValueError):
        return False


def _path_kind(path: Path) -> str:
    try:
        path_stat = path.stat()
    except FileNotFoundError:
        return "missing"
    except (OSError, RuntimeError):
        return "unreadable"
    if stat.S_ISDIR(path_stat.st_mode):
        return "directory"
    if stat.S_ISREG(path_stat.st_mode):
        return "file"
    return f"mode:{path_stat.st_mode}"


def _file_fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except (OSError, RuntimeError):
        return "unreadable"
    return digest.hexdigest()


def _unique_strings(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _unique_diagnostics(values: Iterable[WikiDiagnostic]) -> list[WikiDiagnostic]:
    seen: set[tuple[str, str, str, str, str | None]] = set()
    result: list[WikiDiagnostic] = []
    for diagnostic in values:
        key = (diagnostic.code, diagnostic.severity, diagnostic.path, diagnostic.message, diagnostic.feature_id)
        if key in seen:
            continue
        seen.add(key)
        result.append(diagnostic)
    result.sort(key=lambda item: (item.path, item.code, item.feature_id or "", item.message))
    return result
