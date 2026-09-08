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
from collections import OrderedDict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from threading import Lock
from typing import Any, Iterable
from urllib.parse import unquote, urlsplit

from prism_cli.status import IGNORED_INTAKE_FILES
from prism_cli.wiki_lint import WIKI_BLOCKER_CODES, WikiDiagnostic, WikiLintResult, _wiki_path_references, lint_wiki
from prism_cli.wiki_model import (
    VALID_ADVISORY_REVIEW_STATES,
    VALID_FEATURE_OWNERS,
    VALID_FEATURE_STATUSES,
    VALID_OPEN_QUESTION_OWNERS,
    VALID_PLATFORM_IDS,
    FeaturePage,
    extract_markdown_links,
    feature_id_from_path,
    parse_open_question_rows,
    parse_delivery_evidence,
    parse_advisory_required_actions,
    parse_revalidation,
    read_feature_pages,
    read_platform_requirement_pages,
    read_wiki_pages,
    resolve_relative_markdown_link,
    section_text,
)
from prism_cli.wiki_query import build_envelope
from prism_cli.workspace import (
    COPIER_ANSWERS_FILE,
    MANIFEST_FILE,
    PLATFORM_DIRS,
    WorkspaceInspection,
    detect_workspace_kind,
    inspect_workspace,
)


TRANSITION_SCHEMA_VERSION = 1
TRANSITION_CAPABILITY_VERSION = 2
SUPPORTED_ACTION = "po-handoff"
SUPPORTED_SOURCE_STATUS = "specified"  # compatibility aliases for old callers
SUPPORTED_SOURCE_OWNER = "po"
SUPPORTED_TARGET_STATUS = "ready-for-design"


@dataclass(frozen=True)
class ActionSpec:
    """One named, copy-only lifecycle mapping."""

    action: str
    source_status: str
    source_owner: str
    target_status: str
    target_owner: str
    command: str


ACTION_SPECS: tuple[ActionSpec, ...] = (
    ActionSpec("po-specify", "raw", "po", "specified", "po", "po-specify"),
    ActionSpec("po-handoff", "specified", "po", "ready-for-design", "designer", "po-handoff"),
    ActionSpec("design-start", "ready-for-design", "designer", "in-design", "designer", "design-start"),
    ActionSpec("design-handoff", "in-design", "designer", "ready-for-dev", "dev", "design-handoff"),
    ActionSpec("dev-start", "ready-for-dev", "dev", "in-dev", "dev", "dev-start"),
    ActionSpec("dev-done", "in-dev", "dev", "done", "none", "dev-done"),
    ActionSpec("reopen-spec", "done", "none", "specified", "po", "feature-reopen"),
    ActionSpec("reopen-design", "done", "none", "in-design", "designer", "feature-reopen"),
    ActionSpec("reopen-dev", "done", "none", "in-dev", "dev", "feature-reopen"),
)
ACTION_BY_ID = {spec.action: spec for spec in ACTION_SPECS}
SUPPORTED_ACTIONS = tuple(spec.action for spec in ACTION_SPECS)

# Keep this public compatibility mapping stable: earlier callers and fixtures
# create only the PO-handoff files.  New action surfaces are declared below.

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
}
_ACTION_SURFACE_PATHS[SUPPORTED_ACTION] = CAPABILITY_FILES

_ACTION_INVOCATIONS = {
    spec.action: {
        "codex": (
            f"$feature-reopen F-XXX {spec.target_status}"
            if spec.command == "feature-reopen"
            else f"${spec.command} F-XXX"
        ),
        "claude": (
            f"/feature-reopen F-XXX {spec.target_status}"
            if spec.command == "feature-reopen"
            else f"/{spec.command} F-XXX"
        ),
    }
    for spec in ACTION_SPECS
}
_ACTION_MARKERS = {
    spec.action: {
        "codex": ("$" + spec.command, "F-XXX", f"prism:{spec.command}-contract:v1"),
        "claude": ("/" + spec.command, "F-XXX", f"prism:{spec.command}-contract:v1"),
    }
    for spec in ACTION_SPECS
}
# The existing PO handoff contract was intentionally named before this
# registry.  Preserve the old private name for callers/tests that inspected it.
_CAPABILITY_MARKERS = _ACTION_MARKERS[SUPPORTED_ACTION]


def _capability_paths() -> tuple[Path, ...]:
    """Return every generated instruction path that can affect capabilities."""

    paths: set[Path] = set()
    for surface_paths in _ACTION_SURFACE_PATHS.values():
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
_WIKI_SOURCE_DIRECTORIES = {
    "advisory",
    "api-contracts",
    "business-rules",
    "decisions",
    "design",
    "features",
    "personas",
    "platform-requirements",
}
_PLACEHOLDER_PATTERNS = (
    re.compile(r"^one paragraph\b", re.IGNORECASE),
    re.compile(r"\[what this feature does, why it exists", re.IGNORECASE),
    re.compile(r"\[persona from personas/", re.IGNORECASE),
    re.compile(r"\[business outcome\]", re.IGNORECASE),
    re.compile(r"condition \d+\s*\(testable, unambiguous\)", re.IGNORECASE),
)
_PLATFORM_PLACEHOLDER = re.compile(
    r"^\[what\s+(?:backend|mobile-android|mobile-ios|web-user-app|web-admin-portal)\s+must\s+implement,\s+or\s+['\"]not in scope['\"]\]$",
    re.IGNORECASE,
)
_PLATFORM_SCOPE_LINE = re.compile(
    r"^\s*[-*]\s+\*{0,2}(backend|mobile-android|mobile-ios|web-user-app|web-admin-portal)\*{0,2}\s*:\s*(.*?)\s*$",
    re.IGNORECASE,
)
_HARD_IDENTITY_DIAGNOSTIC_CODES = {
    "answers-filesystem-drift",
    "invalid-copier-answers-shape",
    "invalid-copier-answers-yaml",
    "invalid-manifest-platform",
    "invalid-min-prism-cli-version",
    "invalid-workspace-manifest-project",
    "invalid-workspace-manifest-provenance",
    "invalid-workspace-manifest-schema",
    "invalid-workspace-manifest-shape",
    "invalid-workspace-manifest-surfaces",
    "invalid-workspace-manifest-platforms",
    "invalid-workspace-manifest-paths",
    "manifest-answers-drift",
    "manifest-filesystem-drift",
    "minimum-prism-cli-version-not-met",
    "missing-expected-surface",
    "missing-manifest-path",
    "readable-workspace-manifest",
    "unreadable-copier-answers",
    "unreadable-workspace-manifest",
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


def workspace_fingerprint(root: Path) -> tuple[tuple[str, str], ...]:
    """Fingerprint files and metadata consumed by graph and transition reads.

    The tuple shape is kept compatible with the existing graph server watcher.
    Content is hashed for files; queue entries and platform directories retain
    the existing name/type invalidation semantics.  Capability instructions are
    included so changing or removing a generated command invalidates a snapshot.
    """

    workspace_root = root.expanduser().resolve()
    entries: list[tuple[str, str]] = [("today", date.today().isoformat())]

    for relative in _WATCH_FILES:
        path = workspace_root / relative
        kind = _path_kind(path)
        entries.append((relative, _file_fingerprint(path) if kind == "file" else kind))

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
                entries.append((relative, _file_fingerprint(path)))
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

    for platform_id, relative in sorted(PLATFORM_DIRS.items()):
        entries.append((f"platform:{platform_id}", _path_kind(workspace_root / relative)))

    for relative in _capability_paths():
        path = workspace_root / relative
        kind = _path_kind(path)
        entries.append((relative.as_posix(), _file_fingerprint(path) if kind == "file" else kind))

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
    normalized_id = feature_id.strip().lower() if isinstance(feature_id, str) else ""
    matches = [feature for feature in features if feature.feature_id.strip().lower() == normalized_id]
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

    if requested and requested not in ACTION_BY_ID:
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
    requirement_pages = requirement_pages if requirement_pages is not None else read_platform_requirement_pages(workspace_root / _WATCH_WIKI_DIR)
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
            add_record(node.get("transition"))
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

    matching_specs = [
        spec
        for spec in ACTION_SPECS
        if feature.status == spec.source_status and feature.owner == spec.source_owner
    ]

    # Preserve the original PO evaluator's detailed check vocabulary and
    # compatibility semantics for the first supported action.
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
        if feature.status == "done" and feature.owner == "none":
            return _done_primary_transition(feature, records), records
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
        str(wiki_root / "index.md"),
        *[str(workspace_root / relative) for relative in CAPABILITY_FILES.values()],
    ]
    for raw_target in extract_markdown_links(feature.page.body):
        linked = resolve_relative_markdown_link(feature.page.path, raw_target, wiki_root)
        if linked is not None:
            sources.append(str(linked))

    path_feature_id = feature_id_from_path(path)
    normalized_feature_id = feature_id.strip().lower()
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
        checks.append(_platform_section_check(feature))
        checks.append(_open_questions_check(feature))
        checks.append(_advisory_check(feature))
        checks.append(_revalidation_check(feature, {"specification"}, {"specification"}))
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
        "target_owner": "designer" if target_status == SUPPORTED_TARGET_STATUS else None,
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
) -> dict[str, Any]:
    """Evaluate one action mapping without performing the lifecycle write."""

    path = feature.page.path
    feature_id = feature.feature_id
    source_pair_known = feature.status == spec.source_status and feature.owner == spec.source_owner
    checks = _base_action_checks(feature, spec, duplicate_ids)
    checks.extend(identity_checks)
    sources = _transition_sources(workspace_root, feature, spec, requirement_pages, wiki_pages)

    if source_pair_known:
        checks.append(_scope_check(feature, inspection, workspace_root))
        if spec.action == "design-start":
            checks.extend(
                [
                    _advisory_check(feature),
                    _revalidation_check(feature, {"specification"}, set()),
                    _open_questions_check_for_action(feature, {"po"}),
                ]
            )
        elif spec.action == "design-handoff":
            checks.extend(
                [
                    _design_completion_check(feature, wiki_pages),
                    _advisory_check(feature),
                    _advisory_actions_check(feature, wiki_pages),
                    _open_questions_check_for_action(feature, {"po", "designer"}),
                    _revalidation_check(feature, {"specification", "design"}, {"design"}),
                ]
            )
        elif spec.action == "dev-start":
            checks.extend(
                [
                    _requirements_check(feature, requirement_pages, require_done=False),
                    _api_contract_check(feature, wiki_pages, require_implemented=False),
                    _advisory_check(feature),
                    _advisory_actions_check(feature, wiki_pages),
                    _open_questions_check_for_action(feature, {"po", "designer", "dev"}),
                    _revalidation_check(feature, {"specification", "design"}, set()),
                ]
            )
        elif spec.action == "dev-done":
            checks.extend(
                [
                    _design_completion_check(feature, wiki_pages),
                    _requirements_check(feature, requirement_pages, require_done=False),
                    _api_contract_check(feature, wiki_pages, require_implemented=False),
                    _revalidation_check(
                        feature,
                        {"specification", "design", "implementation", "tests", "release"},
                        {"implementation", "tests", "release"},
                    ),
                    _delivery_evidence_check(feature),
                    _advisory_check(feature),
                    _advisory_actions_check(feature, wiki_pages),
                    _open_questions_check_for_action(feature, {"po", "designer", "dev"}),
                ]
            )
        elif spec.action.startswith("reopen-"):
            checks.append(
                _check(
                    "reopen-impact-review",
                    "pass",
                    "Copy-only preparation includes an explicit impact review step; no write is authorized until it is completed and confirmed.",
                    path,
                )
            )

        # Canonical workflow blockers are intentionally scoped to the selected
        # feature.  A blocker on another feature remains visible in the
        # envelope, but cannot become a false prerequisite for this action.
        if not spec.action.startswith("reopen-"):
            checks.extend(_feature_workflow_checks(feature, lint_result, spec.action))
        ignored_integrity = {
            "done-delivery-evidence",
            "done-platform-requirement",
            "done-api-contract",
            "done-advisory-actions",
            "invalid-revalidation",
            "pending-revalidation",
        } if spec.action in {"reopen-spec", "reopen-design", "reopen-dev", "dev-done"} else set()
        checks.extend(_relevant_integrity_checks(feature, lint_result, ignore_codes=ignored_integrity))
        checks.extend(capability_checks)

    classification = _classify_checks(checks, capability_available=capability_available)
    if not source_pair_known:
        return _unsupported_source_transition(feature, identity_checks, spec=spec)

    supported = capability_available and classification != "unknown"
    reason = _action_transition_reason(spec, classification, checks)
    transition: dict[str, Any] = {
        "version": TRANSITION_SCHEMA_VERSION,
        "feature_id": feature_id,
        "source_status": feature.status,
        "source_owner": feature.owner,
        "source_path": str(path),
        "target_status": spec.target_status,
        "target_owner": spec.target_owner,
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


def _base_action_checks(
    feature: FeaturePage,
    spec: ActionSpec,
    duplicate_ids: set[str],
) -> list[dict[str, Any]]:
    path = feature.page.path
    normalized_feature_id = feature.feature_id.strip().lower()
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
            _source_status_check(feature, spec),
            _source_owner_check(feature, spec),
        ]
    return [
        _check("feature-id", "pass", "Feature ID and path identify one canonical feature page.", path),
        _source_status_check(feature, spec),
        _source_owner_check(feature, spec),
    ]


def _source_status_check(feature: FeaturePage, spec: ActionSpec) -> dict[str, Any]:
    path = feature.page.path
    if feature.status not in VALID_FEATURE_STATUSES:
        return _check("source-status", "unknown", f"Source status `{feature.status}` is missing or unsupported.", path)
    if feature.status == spec.source_status:
        return _check("source-status", "pass", f"Source status is `{spec.source_status}`.", path)
    return _check(
        "unsupported-source-stage",
        "unknown",
        f"Action `{spec.action}` requires source status `{spec.source_status}`, observed `{feature.status}`.",
        path,
    )


def _source_owner_check(feature: FeaturePage, spec: ActionSpec) -> dict[str, Any]:
    path = feature.page.path
    if feature.owner not in VALID_FEATURE_OWNERS:
        return _check("source-owner", "unknown", f"Source owner `{feature.owner}` is missing or unsupported.", path)
    if feature.owner == spec.source_owner:
        return _check("source-owner", "pass", f"Source owner is `{spec.source_owner}`.", path)
    return _check(
        "source-owner",
        "unknown",
        f"Action `{spec.action}` requires source owner `{spec.source_owner}`, observed `{feature.owner}`.",
        path,
    )


def _unsupported_source_transition(
    feature: FeaturePage,
    identity_checks: list[dict[str, Any]],
    *,
    spec: ActionSpec | None = None,
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
            "pass" if feature_id_from_path(path) == feature_id and feature_id.strip().lower() not in set() else "unknown",
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
        checks[1] = _source_status_check(feature, spec)
        checks[2] = _source_owner_check(feature, spec)
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
        "action": None,
        "classification": "unknown",
        "supported": False,
        "checks": checks,
        "sources": [str(path)],
        "reason": reason,
    }


def _done_primary_transition(feature: FeaturePage, records: list[dict[str, Any]]) -> dict[str, Any]:
    path = feature.page.path
    return {
        "version": TRANSITION_SCHEMA_VERSION,
        "feature_id": feature.feature_id,
        "source_status": feature.status,
        "source_owner": feature.owner,
        "source_path": str(path),
        "target_status": None,
        "action": None,
        "classification": "unknown",
        "supported": False,
        "checks": [
            _check("done-source", "pass", "Feature is recorded as done; choose an explicit reopen route to continue work.", path),
            _check("reopen-route", "review", "Done has three explicit reopen routes; choose one after impact review.", path),
        ],
        "sources": _unique_strings(
            source
            for record in records
            for source in record.get("sources", [])
            if isinstance(source, str)
        ),
        "reason": "Done has no primary forward action; choose reopen-spec, reopen-design, or reopen-dev after impact review.",
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
        str(wiki_root / "index.md"),
        *[str(workspace_root / relative) for relative in _ACTION_SURFACE_PATHS[spec.action].values()],
    ]
    feature_id = feature.feature_id.strip().lower()
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
) -> list[dict[str, Any]]:
    relevant_codes = {
        "po-handoff": {"pending-board-review"},
        "design-start": {"pending-board-review"},
        "design-handoff": {"pending-board-review"},
        "dev-start": WIKI_BLOCKER_CODES,
        "dev-done": WIKI_BLOCKER_CODES,
    }.get(action, WIKI_BLOCKER_CODES)
    normalized_id = feature.feature_id.strip().lower()
    path = feature.page.path.resolve()
    checks: list[dict[str, Any]] = []
    for diagnostic in lint_result.diagnostics:
        if diagnostic.code not in relevant_codes:
            continue
        diagnostic_feature_id = diagnostic.feature_id.strip().lower() if isinstance(diagnostic.feature_id, str) else ""
        try:
            same_path = Path(diagnostic.path).resolve() == path
        except (OSError, RuntimeError, ValueError):
            same_path = False
        if diagnostic_feature_id != normalized_id and not same_path:
            continue
        status = "review" if diagnostic.code == "pending-board-review" else "blocked"
        checks.append(
            _check(
                f"workflow:{diagnostic.code}",
                status,
                diagnostic.message,
                Path(diagnostic.path),
            )
        )
    return checks


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
        numbers = ", ".join(row["number"] for row in open_rows)
        return _check("open-questions", "blocked", f"Open action-relevant questions remain ({numbers}).", path)
    return _check("open-questions", "pass", "No open questions remain for this action.", path)


def _design_completion_check(feature: FeaturePage, wiki_pages: list[Any]) -> dict[str, Any]:
    path = feature.page.path
    if not any(platform in {"mobile-android", "mobile-ios", "web-user-app", "web-admin-portal"} for platform in feature.platforms):
        return _check("design", "pass", "No UI platform is declared; visual design is not applicable.", path)
    design_value = feature.page.frontmatter.get("design")
    if design_value == "not-applicable":
        reason = feature.page.frontmatter.get("design-exemption-reason")
        if isinstance(reason, str) and reason.strip():
            return _check("design", "pass", "An explicit design exemption is recorded; the agent must verify confirmation.", path)
        return _check("design", "blocked", "`design: not-applicable` requires a non-empty design-exemption-reason.", path)
    if design_value is not None and not isinstance(design_value, str):
        return _check("design", "unknown", "Feature `design` must be a string when present.", path)
    feature_id = feature.feature_id.strip().lower()
    matching: list[Any] = []
    design_root = path.parent.parent / "design"
    for page in wiki_pages:
        try:
            page.path.resolve().relative_to(design_root.resolve())
        except (ValueError, OSError, RuntimeError):
            continue
        page_feature_id = page.frontmatter.get("feature-id")
        if not isinstance(page_feature_id, str) or not page_feature_id.strip():
            page_feature_id = feature_id_from_path(page.path)
        if isinstance(page_feature_id, str) and page_feature_id.strip().lower() == feature_id:
            matching.append(page)
    if not matching:
        return _check("design", "blocked", "UI platform scope requires a matching design page or an explicit confirmed exemption.", path)
    malformed = [page for page in matching if getattr(page, "parse_errors", [])]
    if malformed:
        return _check("design", "unknown", "A matching design page has malformed frontmatter.", malformed[0].path)
    return _check("design", "pass", "A matching design page is recorded; the agent must verify it covers every declared UI platform.", matching[0].path)


def _requirements_check(feature: FeaturePage, requirement_pages: list[Any], *, require_done: bool) -> dict[str, Any]:
    path = feature.page.path
    declared = feature.platforms
    if not declared:
        return _check("platform-requirements", "unknown", "Platform requirements cannot be evaluated without a valid feature platform scope.", path)
    by_platform: dict[str, list[Any]] = {}
    feature_id = feature.feature_id.strip().lower()
    for requirement in requirement_pages:
        requirement_id = getattr(requirement, "feature_id", None)
        platform = getattr(requirement, "platform", None)
        if not isinstance(requirement_id, str) or requirement_id.strip().lower() != feature_id or not isinstance(platform, str):
            continue
        by_platform.setdefault(platform.strip().lower(), []).append(requirement)
    problems: list[str] = []
    unknown = False
    for platform in declared:
        matches = by_platform.get(platform.strip().lower(), [])
        if not matches:
            problems.append(f"missing requirement for `{platform}`")
            continue
        if len(matches) > 1:
            problems.append(f"duplicate requirements for `{platform}`")
            unknown = True
            continue
        requirement = matches[0]
        if getattr(requirement, "parse_errors", []):
            problems.append(f"malformed requirement for `{platform}`")
            unknown = True
            continue
        status = getattr(requirement, "status", None)
        if status not in {"pending", "in-progress", "done"}:
            problems.append(f"unsupported requirement status for `{platform}`")
            unknown = True
        elif require_done and status != "done":
            problems.append(f"requirement for `{platform}` is `{status}`")
    if problems:
        status = "unknown" if unknown else "blocked"
        return _check("platform-requirements", status, "; ".join(problems) + ".", path)
    message = "Every declared platform has a completed requirement." if require_done else "Every declared platform has a handed-off platform requirement."
    return _check("platform-requirements", "pass", message, path)


def _api_contract_check(feature: FeaturePage, wiki_pages: list[Any], *, require_implemented: bool) -> dict[str, Any]:
    path = feature.page.path
    api_section = section_text(feature.page.body, "API surface")
    normalized_section = re.sub(r"\s+", " ", api_section).strip().lower()
    section_applicable = bool(normalized_section) and normalized_section not in {"none", "no api", "not applicable", "n/a"}
    feature_id = feature.feature_id.strip().lower()
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
        if isinstance(page_feature_id, str) and page_feature_id.strip().lower() == feature_id:
            matching.append(page)

    # Include contracts explicitly referenced from the feature or any scoped
    # platform requirement, including shared contracts whose own filename or
    # feature-id is intentionally independent of this feature.
    source_pages = [feature.page]
    for page in wiki_pages:
        page_feature_id = page.frontmatter.get("feature-id")
        if not isinstance(page_feature_id, str) or page_feature_id.strip().lower() != feature_id:
            continue
        if page.frontmatter.get("platform") not in feature.platforms:
            continue
        try:
            page.path.resolve().relative_to((wiki_root / "platform-requirements").resolve())
        except (ValueError, OSError, RuntimeError):
            continue
        source_pages.append(page)
    for source in source_pages:
        for raw_target in extract_markdown_links(source.body):
            target = _resolve_api_link(source.path, raw_target, wiki_root)
            if target is None:
                continue
            for page in wiki_pages:
                if page.path.resolve() == target and page not in matching:
                    matching.append(page)
        for raw_target in _wiki_path_references(source.body, "api-contracts"):
            target = _resolve_api_link(source.path, raw_target, wiki_root)
            if target is None:
                continue
            for page in wiki_pages:
                if page.path.resolve() == target and page not in matching:
                    matching.append(page)
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


def _resolve_api_link(source_path: Path, raw_target: str, wiki_root: Path) -> Path | None:
    normalized = unquote(raw_target).replace("\\", "/")
    try:
        parsed = urlsplit(normalized)
    except ValueError:
        return None
    if parsed.scheme or parsed.netloc:
        return None
    lowered = normalized.lower()
    marker = "knowledge/wiki/"
    if marker in lowered:
        suffix = normalized[lowered.index(marker) + len(marker) :]
        if not suffix.lower().startswith("api-contracts/"):
            return None
        target = (wiki_root / suffix).resolve()
    elif lowered.startswith("wiki/api-contracts/"):
        target = (wiki_root / normalized[len("wiki/") :]).resolve()
    elif lowered.startswith("api-contracts/"):
        target = (wiki_root / normalized).resolve()
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


def _delivery_evidence_check(feature: FeaturePage) -> dict[str, Any]:
    rows, errors = parse_delivery_evidence(feature.page.body, feature.platforms)
    path = feature.page.path
    if errors:
        return _check("delivery-evidence", "blocked", "; ".join(errors), path)
    if not rows:
        return _check("delivery-evidence", "blocked", "No per-platform delivery evidence was supplied.", path)
    return _check(
        "delivery-evidence",
        "pass",
        f"Delivery evidence has substantive implementation, test, and release cells for {len(rows)} declared platform(s); an agent must verify the references.",
        path,
    )


def _action_transition_reason(spec: ActionSpec, classification: str, checks: list[dict[str, Any]]) -> str:
    if classification == "ready":
        if spec.action.startswith("reopen-"):
            return "Action mapping and observable source checks pass; explicit impact review and user confirmation remain outstanding."
        if spec.action == "dev-done":
            return "Observable Done evidence checks pass; an agent must verify artifacts and obtain final confirmation."
        return f"Observable {spec.action} checks pass; semantic review and user confirmation remain outstanding."
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
    # Keep the legacy PO action last so callers that keyed old v1 surfaces by
    # role continue to observe the PO surface while v2 consumers use action.
    action_order = [action for action in SUPPORTED_ACTIONS if action != SUPPORTED_ACTION] + [SUPPORTED_ACTION]
    for action in action_order:
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
    elif inspection.project_name is None or not inspection.platforms:
        checks.append(_check("workspace-identity", "unknown", "Workspace project identity or platform scope is incomplete.", identity_path))
    elif hard:
        message = "; ".join(sorted({diagnostic.message for diagnostic in hard}))
        checks.append(_check("workspace-identity", "unknown", f"Workspace identity is drifted or unsupported: {message}", hard[0].path))
    else:
        checks.append(_check("workspace-identity", "pass", "Workspace identity and declared scope are available.", identity_path))
    return checks


def _scope_check(feature: FeaturePage, inspection: WorkspaceInspection, root: Path) -> dict[str, Any]:
    path = feature.page.path
    value = feature.page.frontmatter.get("platforms")
    if not isinstance(value, list):
        return _check("platform-scope", "unknown", "Feature `platforms` must be a list of valid platform IDs.", path)
    if not value:
        return _check("platform-scope", "blocked", "Feature must list at least one platform in scope.", path)
    invalid = [item for item in value if not isinstance(item, str) or item not in VALID_PLATFORM_IDS]
    if invalid:
        return _check("platform-scope", "unknown", f"Feature platform scope contains invalid values: {invalid!r}.", path)
    available = set(inspection.platforms)
    missing = sorted(set(value) - available)
    if missing:
        return _check(
            "platform-scope",
            "blocked",
            f"Feature platforms {', '.join(missing)} are outside the available workspace scope.",
            path,
        )
    return _check("platform-scope", "pass", "Feature platforms are valid and within the available workspace scope.", path)


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


def _platform_section_check(feature: FeaturePage) -> dict[str, Any]:
    """Reconcile declared feature platforms with the body scope section."""

    path = feature.page.path
    declared = feature.page.frontmatter.get("platforms")
    body = section_text(feature.page.body, "Platform scope")
    if not body.strip():
        return _check("platform-section", "blocked", "Required `Platform scope` section is empty or missing.", path)
    if not isinstance(declared, list) or any(not isinstance(item, str) for item in declared):
        return _check(
            "platform-section",
            "unknown",
            "Platform scope cannot be reconciled until frontmatter `platforms` is a list of strings.",
            path,
        )
    rows: dict[str, str] = {}
    for raw_line in body.splitlines():
        match = _PLATFORM_SCOPE_LINE.match(raw_line)
        if match:
            rows[match.group(1).lower()] = match.group(2).strip()
    if not rows:
        return _check(
            "platform-section",
            "blocked",
            "Platform scope must list at least one declared platform with a description.",
            path,
        )
    missing = [platform for platform in declared if not rows.get(platform.lower())]
    if missing:
        return _check(
            "platform-section",
            "blocked",
            f"Platform scope is missing a non-empty entry for: {', '.join(missing)}.",
            path,
        )
    invalid_entries: list[str] = []
    for platform, description in rows.items():
        normalized_description = re.sub(r"\s+", " ", description).strip()
        if _PLATFORM_PLACEHOLDER.fullmatch(normalized_description):
            invalid_entries.append(f"{platform} retains the template placeholder")
            continue
        if platform in {item.lower() for item in declared} and normalized_description.lower() in {
            "not in scope",
            "n/a",
            "none",
        }:
            invalid_entries.append(f"{platform} is declared but marked not in scope")
            continue
        if platform not in {item.lower() for item in declared} and normalized_description.lower() not in {
            "not in scope",
            "n/a",
            "none",
        }:
            invalid_entries.append(f"{platform} describes work but is not declared in frontmatter")
    if invalid_entries:
        return _check(
            "platform-section",
            "blocked",
            "Platform scope does not match frontmatter: " + "; ".join(invalid_entries) + ".",
            path,
        )
    return _check(
        "platform-section",
        "pass",
        "Platform scope lists each declared feature platform with a description.",
        path,
    )


def _open_questions_check(feature: FeaturePage) -> dict[str, Any]:
    section = section_text(feature.page.body, "Open questions")
    rows, errors = parse_open_question_rows(feature.page.body)
    path = feature.page.path
    if section.strip():
        table_lines = [line.strip() for line in section.splitlines() if line.strip().startswith("|")]
        header_seen = False
        for line in table_lines:
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if _is_question_separator(cells):
                continue
            if cells[:4] == ["#", "Question", "Owner", "Status"]:
                header_seen = True
                continue
            if len(cells) != 4:
                errors.append(f"Malformed open questions table row: {line}")
        if table_lines and not header_seen:
            errors.append("Open questions table is missing the expected header row.")
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
        numbers = ", ".join(row["number"] for row in open_po)
        return _check("open-questions", "blocked", f"Open PO-owned questions remain ({numbers}).", path)
    return _check("open-questions", "pass", "No open PO-owned questions remain.", path)


def _is_question_separator(cells: list[str]) -> bool:
    if not cells:
        return False
    return bool(cells) and all(re.fullmatch(r":?-+:?", cell) for cell in cells if cell)


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
    feature_id = feature.feature_id.strip().lower()
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
        if isinstance(page_feature_id, str) and page_feature_id.strip().lower() == feature_id:
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
    for filename in ("SCHEMA.md", "index.md"):
        required_path = wiki_root / filename
        try:
            if required_path.exists():
                required_path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError):
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
        if diagnostic.code in WIKI_BLOCKER_CODES:
            continue
        diagnostic_path = Path(diagnostic.path).resolve()
        is_global_contract = diagnostic.code in {"missing-required-wiki-file", "malformed-index"} and diagnostic_path.name in {
            "SCHEMA.md",
            "index.md",
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
        return [_check("source-integrity", "pass", "No feature-specific integrity diagnostics were reported.", feature.page.path)]
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
    return "ready"


def _transition_reason(classification: str, checks: list[dict[str, Any]]) -> str:
    if classification == "ready":
        return "Observable po-handoff checks pass; semantic completeness and user confirmation remain outstanding."
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
        "platforms": feature.platforms,
        "path": str(feature.page.path),
    }


def _duplicate_feature_ids(features: list[FeaturePage]) -> set[str]:
    counts: dict[str, int] = {}
    for feature in features:
        key = feature.feature_id.strip().lower()
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


# Short aliases make the evaluator discoverable to callers that use the noun
# form from the CLI surface while retaining the descriptive public API above.
transition_preflight = build_transition_preflight
evaluate_transitions = evaluate_transition_summaries
