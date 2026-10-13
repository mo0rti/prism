"""Graph facts over the Prism wiki: nodes, evidence-carrying edges, and renderers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from prism_cli.app_model import WorkspaceModel
from prism_cli.status import detect_setup_state, list_queue_items
from prism_cli.release_rules import ReleaseSequence, validate_release_sequence
from prism_cli.wiki_bugs import BUG_OWNER_BY_STATUS, BUG_SEVERITIES, BUG_STATUS_ORDER, CLOSE_DISPOSITIONS, BugPage, parse_fix_rows, parse_verification_rows, read_bug_pages
from prism_cli.wiki_incidents import (
    INCIDENT_SEVERITIES,
    INCIDENT_STATUSES,
    IncidentPage,
    cause_is_unknown,
    read_incident_pages,
    section_is_blank,
    timeline_entries,
)
from prism_cli.wiki_lint import FRESHNESS_CODES, WIKI_BLOCKER_CODES, lint_wiki
from prism_cli.wiki_index import general_page_kind, is_page_path
from prism_cli.wiki_links import NON_PAGE_FILENAMES, markdown_files, page_references_feature
from prism_cli.wiki_model import (
    DESIGN_OWNERS,
    DESIGN_TRACKS,
    FEATURE_STATUS_ORDER,
    OWNER_BY_STATUS,
    app_stages,
    app_stages_text,
    number_order,
    extract_markdown_links,
    load_markdown_page,
    resolve_relative_markdown_link,
    parse_design_tracks,
    parse_open_question_rows,
    ReleaseParticipation,
    _NO_VALUE,
    QA_RESULTS,
    parse_release_rows,
    read_feature_evidence,
    read_feature_pages,
    read_app_requirement_pages,
    read_wiki_pages,
    read_wiki_settings,
    release_participants,
    remove_html_comments,
    section_text,
    stage_scope,
    status_rank,
    within_wiki_read_scope,
)
from prism_cli.wiki_operations import bug_board_row, operation_row
from prism_cli.wiki_query import build_envelope
from prism_cli.wiki_releases import (
    KIND_REDEPLOY,
    KIND_RELEASE,
    KIND_ROLLBACK,
    RECORD_OUTCOMES,
    ROW_OUTCOMES,
    ReleaseRecord,
    read_all_release_records,
    record_id_of_cell,
    record_sections,
    release_participation,
)
from prism_cli.qa_rules import QA_FAIL_STAGES
from prism_cli.wiki_transitions import (
    ACTION_BY_ID,
    ACTION_SPECS,
    DESIGN_OWNER,
    MINIMUM,
    MODE_AGENT_PROPOSED,
    UNCHANGED,
    evaluate_transition_summaries,
    finalize_transition_envelope,
    workspace_fingerprint,
)
from prism_cli.workspace import inspect_workspace



# The folders of the records and design pages a feature links; they are not graph nodes, and a link to one is not dangling.
_RECORD_FOLDERS = frozenset({"releases", "bugs", "incidents", "technical-design"})

# The release actions of a feature that is not yet released: they settle apps that are ready for release.
_RELEASE_ACTIONS = frozenset({"release-done", "release-return-dev"})


def _offered_transitions(node: GraphNode, records: list[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    """The actions a card offers: a feature in development has the QA actions only once one of its apps reached QA, and the
    release actions only once one of its apps is ready for release."""

    stages = [stage for _app, stage in node.app_stages or ()]
    # An app at `ready-for-release` can still fail QA (F15), so it counts with the apps in QA.
    in_qa = any(stage in QA_FAIL_STAGES for stage in stages)
    offered = list(records)
    if "ready-for-release" not in stages:
        offered = [record for record in offered if record.get("action") not in _RELEASE_ACTIONS]
    if node.status == "in-dev" and not in_qa:
        offered = [record for record in offered if getattr(ACTION_BY_ID.get(str(record.get("action"))), "package", None) != "D3"]
    return tuple(offered)


def _statuses_in_order(statuses: Iterable[str]) -> list[str]:
    wanted = set(statuses)
    return [status for status in FEATURE_STATUS_ORDER if status in wanted]


def _unique(values: Iterable[Any]) -> list[Any]:
    return list(dict.fromkeys(values))


def _action_metadata(spec: Any) -> dict[str, Any]:
    """The page's view of one registry action: the values a transition record may carry, who runs it, and its drop column.

    Every list is a set of allowed values, one per field. A design owner symbol resolves to both design owners. An action that
    targets the minimum over the app stages can leave the feature at any stage from `in-dev` (the first stage with app stages)
    up to the one after the highest stage it starts from; its owner follows the stage. The drop column is the stage the card
    moves to when the action completes, and it is set only where it is certain: a concrete target after every source. A
    minimum-of-stages or unchanged target has no drop column, because the result depends on the other apps.
    """

    sources = _unique(pair for owner in DESIGN_OWNERS for pair in spec.resolved_sources(owner))
    source_ranks = [status_rank(status) for status, _owner in sources]
    source_status = _statuses_in_order(status for status, _owner in sources)
    source_owner = _unique(owner for _status, owner in sources)
    drop_stage: str | None = None
    if spec.target_status == MINIMUM:
        first = max(min(source_ranks), status_rank("in-dev"))
        last = min(max(source_ranks) + 1, len(FEATURE_STATUS_ORDER) - 1)
        target_status = list(FEATURE_STATUS_ORDER[first : last + 1])
        target_owner = _unique(OWNER_BY_STATUS[status] for status in target_status)
    elif spec.target_status == UNCHANGED:
        target_status, target_owner = source_status, source_owner
    else:
        target_status = [spec.target_status]
        target_owner = list(DESIGN_OWNERS) if spec.target_owner == DESIGN_OWNER else [spec.target_owner]
        if status_rank(spec.target_status) > max(source_ranks):
            drop_stage = spec.target_status
    return {
        "action": spec.action,
        "skill": spec.command,
        "arguments": spec.arguments,
        "human_direct": spec.human_direct,
        "agent_proposal": MODE_AGENT_PROPOSED in spec.modes,
        "source_status": source_status,
        "source_owner": source_owner,
        "target_status": target_status,
        "target_owner": target_owner,
        "drop_stage": drop_stage,
    }


def action_registry() -> list[dict[str, Any]]:
    """The feature actions of the transition registry, in registry order, for the board page.

    The page reads these instead of keeping its own action rules, so a registry change reaches the page without a second edit.
    """

    return [_action_metadata(spec) for spec in ACTION_SPECS if spec.subject == "feature" and spec.available]


def app_operations(
    wiki_root: Path,
    model: WorkspaceModel,
    feature_pages: list[Any],
    participation: ReleaseParticipation,
    *,
    bugs: list[BugPage],
    incidents: list[IncidentPage],
    releases: list[ReleaseRecord],
) -> list[dict[str, str]]:
    """The status board's Operations rows, derived from the pages by the same function that writes and lints them.

    `bugs`, `incidents` and the valid `releases` are the pages the caller already read, so the graph reads them once.
    An app with nothing released, recorded or open has no row, as on the status board.
    """

    bug_rows = [row for bug in bugs if (row := bug_board_row(bug)) is not None]
    stage_cells = {
        feature.feature_id: app_stages_text(feature.status, feature.apps, feature.page.body, model, feature.feature_id, participation)
        for feature in feature_pages
    }
    try:
        targets = {app: str(entry["target"]) for app, entry in read_wiki_settings(wiki_root, model).delivery_targets.items()}
    except (OSError, ValueError):
        targets = {}
    return [
        row
        for app in model.apps
        if (
            row := operation_row(
                app.id,
                delivery_target=targets.get(app.id),
                feature_stage_cells=stage_cells,
                bug_rows=bug_rows,
                incidents=incidents,
                releases=releases,
            )
        )
        is not None
    ]


# --- Bug, release and incident records -----------------------------------------------------------------------------------
#
# The graph lists every bug page, release record and incident for the board's record views. Each entry is read by the
# readers that lint and the status board use, and an entry that lint marks invalid is listed with `valid: false`.

# The longest summary or impact, the longest timeline line and the most timeline lines an entry carries.
SUMMARY_LIMIT = 240
TIMELINE_TEXT_LIMIT = 200
TIMELINE_LIMIT = 20
# The lint codes that mark a page as not valid.
BUG_INVALID_CODES = frozenset({"bug-page-invalid", "invalid-bug-status-owner"})
RELEASE_INVALID_CODES = frozenset({"release-record-invalid"})
INCIDENT_INVALID_CODES = frozenset({"incident-record-invalid"})
# The kind of a release that retries a failed release; the validator calls it a `release`.
KIND_RETRY = "retry"

_BUG_OWNERS = tuple(dict.fromkeys(BUG_OWNER_BY_STATUS.values()))
_RECORD_NUMBER = re.compile(r"(\d+)$")
_BLANK_LINE = re.compile(r"\r?\n[ \t]*\r?\n")


def bounded_text(text: str, limit: int) -> str:
    """The text on one line, cut to `limit` characters at a word boundary with an ellipsis when it is longer."""

    collapsed = re.sub(r"\s+", " ", text).strip()
    if len(collapsed) <= limit:
        return collapsed
    head = collapsed[: limit - 1]
    if not collapsed[limit - 1].isspace() and " " in head:
        head = head[: head.rindex(" ")]
    return head.rstrip() + "…"


def _first_paragraph(section: str, limit: int) -> str | None:
    """The first paragraph of a section, without its HTML comments and bounded to `limit`; ``None`` for a section with no text."""

    cleaned = remove_html_comments(section).strip()
    if not cleaned:
        return None
    return bounded_text(_BLANK_LINE.split(cleaned, maxsplit=1)[0], limit) or None


def _one_of(value: str | None, allowed: Iterable[str]) -> str | None:
    return value if value in allowed else None


def _cell_value(text: str) -> str | None:
    """A table cell, or ``None`` for an empty cell and for the dash that stands for no value."""

    value = text.strip()
    return None if value in _NO_VALUE else value


def _record_order(identifier: str) -> tuple[int, int, str, str]:
    match = _RECORD_NUMBER.search(identifier)
    return number_order(match.group(1) if match else None, identifier)


def _page_path(workspace_root: Path, path: Path) -> str:
    try:
        return path.relative_to(workspace_root).as_posix()
    except ValueError:
        return path.as_posix()


def _invalid_pages(diagnostics: Iterable[Any], codes: frozenset[str]) -> set[str]:
    """The paths of the pages that carry a diagnostic with one of `codes`."""

    return {diagnostic.path for diagnostic in diagnostics if diagnostic.code in codes}


def bug_facts(bugs: Iterable[BugPage], *, workspace_root: Path, invalid_paths: set[str]) -> list[dict[str, Any]]:
    """`facts.bugs`: one entry per bug page, by bug number. A value the page lacks or states outside its vocabulary is ``None``."""

    entries: list[dict[str, Any]] = []
    for bug in sorted(bugs, key=lambda item: _record_order(item.bug_id)):
        body = bug.page.body
        fix_rows, _fix_problems = parse_fix_rows(body)
        verification_rows, _verification_problems = parse_verification_rows(body)
        release_rows, _release_problems = parse_release_rows(body)
        entries.append(
            {
                "id": bug.bug_id,
                "title": bug.title,
                "path": _page_path(workspace_root, bug.page.path),
                "status": _one_of(bug.status, BUG_STATUS_ORDER),
                "owner": _one_of(bug.owner, _BUG_OWNERS),
                "severity": _one_of(bug.severity, BUG_SEVERITIES),
                "blocking": bug.blocking,
                "apps": bug.apps,
                "feature": bug.feature,
                "found_in": bug.found_in,
                "environment": bug.environment,
                "deferred": bug.deferred,
                "close_reason": _one_of(bug.disposition, CLOSE_DISPOSITIONS),
                "duplicate_of": bug.duplicate_of,
                "promoted_to": bug.promoted_to,
                "regression_of": bug.regression_of,
                "summary": _first_paragraph(section_text(body, "Summary"), SUMMARY_LIMIT),
                "fix": [{"app": row.app, "artifact": _cell_value(row.artifact)} for row in fix_rows],
                "verification": [
                    {
                        "app": row.app,
                        "attempt": f"qa-{row.attempt}" if row.attempt is not None else None,
                        "result": _one_of(row.result, QA_RESULTS),
                    }
                    for row in verification_rows
                ],
                "release": [
                    {
                        "app": row.app,
                        "target": _cell_value(row.target),
                        "outcome": _one_of(row.outcome, ("released", "failed", "pending")),
                        "record": record_id_of_cell(row.record),
                    }
                    for row in release_rows
                ],
                "valid": str(bug.page.path) not in invalid_paths,
            }
        )
    return entries


def _release_kind(record: ReleaseRecord, kinds: dict[str, str]) -> str:
    """The kind of a record: the validator's, or `retry` for a release that names the failed release it retries.

    A record the validator rejects has no derived kind, so it is read from the links it declares.
    """

    kind = kinds.get(record.record_id)
    if kind is None:
        source_kind = kinds.get(record.retry_of or "")
        kind = KIND_ROLLBACK if record.rollback_of else KIND_REDEPLOY if source_kind in {KIND_ROLLBACK, KIND_REDEPLOY} else KIND_RELEASE
    return KIND_RETRY if kind == KIND_RELEASE and record.retry_of else kind


def release_facts(records: Iterable[ReleaseRecord], sequence: ReleaseSequence, *, workspace_root: Path, invalid_paths: set[str]) -> list[dict[str, Any]]:
    """`facts.releases`: one entry per release record, in record order.

    `sequence` is the `ReleaseSequence` of `validate_release_sequence` over those records: it decides each record's kind and
    which records are live. A record is `current` when it is the latest record of an (app, target) and it released there, so a
    record rolled back without a redeploy is not current.
    """

    current = {
        record.record_id
        for pair, (record, _rows) in sequence.deliveries.items()
        if sequence.latest.get(pair) is not None and sequence.latest[pair].record_id == record.record_id
    }
    entries: list[dict[str, Any]] = []
    for record in records:
        entries.append(
            {
                "id": record.record_id,
                "title": record.title,
                "path": _page_path(workspace_root, record.page.path),
                "date": record.date,
                "kind": _release_kind(record, sequence.kinds),
                "outcome": _one_of(record.outcome, RECORD_OUTCOMES),
                "features": record.features,
                "bugs": record.bugs,
                "retry_of": record.retry_of,
                "rollback_of": record.rollback_of,
                "summary": _first_paragraph(record_sections(record.page.body).get("Summary", ""), SUMMARY_LIMIT),
                "deliveries": [
                    {
                        "item": row.item,
                        "app": row.app,
                        "target": row.target,
                        "version": row.version,
                        "attempt": f"release-{row.attempt}" if row.attempt is not None else None,
                        "outcome": _one_of(row.outcome, ROW_OUTCOMES),
                    }
                    for row in record.rows
                ],
                "current": record.record_id in current,
                "valid": str(record.page.path) not in invalid_paths,
            }
        )
    return entries


def incident_facts(incidents: Iterable[IncidentPage], *, workspace_root: Path, invalid_paths: set[str]) -> list[dict[str, Any]]:
    """`facts.incidents`: one entry per incident page, by incident number. The timeline keeps the last lines when it is long."""

    entries: list[dict[str, Any]] = []
    for incident in sorted(incidents, key=lambda item: _record_order(item.incident_id)):
        body = incident.page.body
        lines = timeline_entries(body)
        truncated = len(lines) > TIMELINE_LIMIT
        day = incident.date
        entries.append(
            {
                "id": incident.incident_id,
                "title": incident.title,
                "path": _page_path(workspace_root, incident.page.path),
                "date": day.isoformat() if day is not None else None,
                "status": _one_of(incident.status, INCIDENT_STATUSES),
                "severity": _one_of(incident.severity, INCIDENT_SEVERITIES),
                "apps": incident.apps,
                "releases": incident.releases,
                "follow_ups": incident.follow_ups,
                "impact": _first_paragraph(section_text(body, "Impact"), SUMMARY_LIMIT),
                "cause_known": not section_is_blank(body, "Cause") and not cause_is_unknown(body),
                "timeline": [{"when": when, "text": bounded_text(text, TIMELINE_TEXT_LIMIT)} for when, text in lines[-TIMELINE_LIMIT:]],
                "timeline_truncated": truncated,
                "valid": str(incident.page.path) not in invalid_paths,
            }
        )
    return entries


LIFECYCLE_STAGES = list(FEATURE_STATUS_ORDER)

NODE_TYPES = {
    "feature",
    "persona",
    "business-rule",
    "design",
    "app-requirement",
    "api-contract",
    "decision",
    "advisory-review",
    "app",
}

EDGE_KINDS = {
    "targets",
    "has-requirement",
    "has-design",
    "has-contract",
    "has-review",
    "constrained-by",
    "serves",
    "related",
    "links-to",
}

_ID_DIRECTORIES = {
    "persona": ("personas", "persona"),
    "business-rule": ("business-rules", "rule"),
    "decision": ("decisions", "decision"),
}
_PATH_ID_DIRECTORIES = {
    "design": ("design", "design"),
    "api-contract": ("api-contracts", "api"),
    "advisory-review": ("advisory", "review"),
}

FEATURE_ID_PATTERN = re.compile(r"\bF-\d+\b")


@dataclass(frozen=True)
class GraphNode:
    id: str
    type: str
    title: str
    path: str | None
    status: str | None = None
    owner: str | None = None
    advisory_review: str | None = None
    health: str = "ok"
    open_questions: tuple[tuple[str, str, str, str], ...] | None = None  # (number, question, owner, status)
    transitions: tuple[dict[str, Any], ...] | None = None
    # app ID -> app stage for a feature at `in-dev` or later (CONTRACTS 4.2); the feature's status is the minimum.
    app_stages: tuple[tuple[str, str], ...] | None = None
    # The state of each design track (`ui`, `technical`) of a feature that has `design-tracks` front matter (CONTRACTS 3.1).
    design_tracks: tuple[tuple[str, str], ...] | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"id": self.id, "type": self.type, "title": self.title, "path": self.path, "health": self.health}
        if self.status is not None:
            data["status"] = self.status
        if self.owner is not None:
            data["owner"] = self.owner
        if self.advisory_review is not None:
            data["advisory_review"] = self.advisory_review
        if self.open_questions is not None:
            data["open_questions"] = [
                {"number": number, "question": question, "owner": owner, "status": status}
                for number, question, owner, status in self.open_questions
            ]
        if self.transitions is not None:
            data["transitions"] = list(self.transitions)
        if self.app_stages is not None:
            data["app_stages"] = [{"app": app, "stage": stage} for app, stage in self.app_stages]
        if self.design_tracks is not None:
            data["design_tracks"] = dict(self.design_tracks)
        return data


@dataclass(frozen=True)
class GraphEdge:
    source: str
    target: str
    kind: str
    evidence: str

    def to_dict(self) -> dict[str, str]:
        return {"source": self.source, "target": self.target, "kind": self.kind, "evidence": self.evidence}


@within_wiki_read_scope
def build_graph(root: Path) -> dict[str, Any]:
    workspace_root = root.expanduser().resolve()
    initial_fingerprint = workspace_fingerprint(workspace_root)
    wiki_root = workspace_root / "knowledge" / "wiki"
    lint_result = lint_wiki(workspace_root)
    feature_pages = read_feature_pages(wiki_root)
    requirement_pages = read_app_requirement_pages(wiki_root)
    wiki_pages = read_wiki_pages(wiki_root)
    inspection = inspect_workspace(workspace_root)
    transition_evaluation = evaluate_transition_summaries(
        workspace_root,
        features=feature_pages,
        lint_result=lint_result,
        inspection=inspection,
        requirement_pages=requirement_pages,
        wiki_pages=wiki_pages,
        initial_fingerprint=initial_fingerprint,
    )

    # The release records the graph reads decide which retired apps a released feature keeps, on every surface.
    participation = release_participation(wiki_root)
    nodes, pages_by_id, path_to_id = _collect_nodes(wiki_root, inspection.model, participation, feature_pages=feature_pages)
    edges, dangling = _collect_edges(wiki_root, nodes, pages_by_id, path_to_id)

    # An app node stays when a feature targets it or when the app has an Operations row, so a standalone bug or incident
    # (`feature: none`) still shows the app in the Apps view.
    # The bug, incident and release pages are read once for the Operations rows and for the record lists.
    bug_pages, incident_pages = read_bug_pages(wiki_root), read_incident_pages(wiki_root)
    release_pages = read_all_release_records(wiki_root)
    release_sequence = validate_release_sequence(release_pages)
    operations = app_operations(
        wiki_root,
        inspection.model,
        feature_pages,
        participation,
        bugs=bug_pages,
        incidents=incident_pages,
        releases=release_sequence.records,
    )
    shown_apps = {edge.target for edge in edges if edge.target.startswith("app:")} | {f"app:{row['app']}" for row in operations}
    nodes = {
        node_id: node
        for node_id, node in nodes.items()
        if node.type != "app" or node_id in shown_apps
    }
    edges = [edge for edge in edges if edge.source in nodes and edge.target in nodes]

    # Blocker diagnostics describe workflow state and freshness diagnostics ask
    # for a review; neither is page integrity, so neither is node health.
    health_by_path: dict[str, str] = {}
    for diagnostic in lint_result.diagnostics:
        if diagnostic.code in WIKI_BLOCKER_CODES or diagnostic.code in FRESHNESS_CODES:
            continue
        current = health_by_path.get(diagnostic.path)
        if diagnostic.severity == "error" or current == "error":
            health_by_path[diagnostic.path] = "error"
        elif current != "error":
            health_by_path[diagnostic.path] = "warning"

    healthy_nodes = [
        GraphNode(
            id=node.id,
            type=node.type,
            title=node.title,
            path=node.path,
            status=node.status,
            owner=node.owner,
            advisory_review=node.advisory_review,
            health=health_by_path.get(node.path or "", "ok"),
            open_questions=node.open_questions,
            app_stages=node.app_stages,
            design_tracks=node.design_tracks,
            transitions=(
                _offered_transitions(node, transition_evaluation.transitions_list_by_path.get(node.path or "", []))
                if node.path in transition_evaluation.transitions_list_by_path
                else None
            ),
        )
        for node in nodes.values()
    ]

    sorted_nodes = sorted(healthy_nodes, key=lambda node: (node.type, node.id))
    sorted_edges = sorted(set(edges), key=lambda edge: (edge.source, edge.target, edge.kind))

    intake_root = workspace_root / "knowledge" / "intake"
    facts = {
        "node_count": len(sorted_nodes),
        "edge_count": len(sorted_edges),
        "nodes": [node.to_dict() for node in sorted_nodes],
        "edges": [edge.to_dict() for edge in sorted_edges],
        "dangling_references": dangling,
        "setup_state": detect_setup_state(workspace_root, lint_result),
        "intake": {
            "pending": list_queue_items(intake_root / "pending"),
            "quarantined": list_queue_items(intake_root / "quarantined"),
        },
        "transition_capability": transition_evaluation.capability,
        "action_registry": action_registry(),
        "app_operations": operations,
        "bugs": bug_facts(
            bug_pages, workspace_root=workspace_root, invalid_paths=_invalid_pages(lint_result.diagnostics, BUG_INVALID_CODES)
        ),
        "releases": release_facts(
            release_pages,
            release_sequence,
            workspace_root=workspace_root,
            invalid_paths=_invalid_pages(lint_result.diagnostics, RELEASE_INVALID_CODES),
        ),
        "incidents": incident_facts(
            incident_pages, workspace_root=workspace_root, invalid_paths=_invalid_pages(lint_result.diagnostics, INCIDENT_INVALID_CODES)
        ),
    }
    sources = [str(wiki_root), *transition_evaluation.sources] + sorted(node.path for node in sorted_nodes if node.path)
    diagnostics = [*lint_result.diagnostics, *transition_evaluation.diagnostics]
    envelope = build_envelope(workspace_root, "wiki graph", diagnostics, facts, sources)
    return finalize_transition_envelope(workspace_root, envelope)


def _node_app_stages(feature: Any, model: WorkspaceModel, participation: ReleaseParticipation) -> tuple[tuple[str, str], ...] | None:
    """The stage of each app a feature shows, from its evidence tables; ``None`` before `in-dev`."""

    if status_rank(feature.status) < status_rank("in-dev"):
        return None
    evidence = read_feature_evidence(feature.page.body)
    participants = release_participants(feature.status, feature.apps, model, feature.feature_id, feature.page.body, evidence, participation)
    return tuple(app_stages(stage_scope(feature.status, feature.apps, model, participants), evidence).items())


def _collect_nodes(
    wiki_root: Path,
    model: WorkspaceModel,
    participation: ReleaseParticipation,
    *,
    feature_pages: list[Any] | None = None,
) -> tuple[dict[str, GraphNode], dict[str, Any], dict[str, str]]:
    nodes: dict[str, GraphNode] = {}
    pages_by_id: dict[str, Any] = {}
    path_to_id: dict[str, str] = {}

    # Reserve the workspace's app ids before reading user pages.  A page
    # with a colliding id must remain visible as a distinct node while edges
    # still have a stable target for the real app node.
    for app in sorted(model.apps, key=lambda item: item.id):
        node_id = f"app:{app.id}"
        # The node's status is the app's: `active`, or `retired` for an app kept as history.
        nodes[node_id] = GraphNode(id=node_id, type="app", title=app.name, path=None, status=app.status)

    for feature in feature_pages if feature_pages is not None else read_feature_pages(wiki_root):
        question_rows, _question_errors = parse_open_question_rows(feature.page.body)
        design_tracks, _track_problems = parse_design_tracks(feature.page.frontmatter)
        node_id = _unique_node_id(nodes, feature.feature_id, feature.page.path)
        node = GraphNode(
            id=node_id,
            type="feature",
            title=feature.title,
            path=str(feature.page.path),
            status=feature.status,
            owner=feature.owner,
            advisory_review=feature.advisory_review,
            open_questions=tuple(
                (row["number"], row["question"], row["owner"], row["status"]) for row in question_rows
            ),
            app_stages=_node_app_stages(feature, model, participation),
            design_tracks=(
                tuple((track, design_tracks.state(track)) for track in DESIGN_TRACKS) if design_tracks is not None else None
            ),
        )
        nodes[node.id] = node
        pages_by_id[node.id] = feature
        path_to_id[str(feature.page.path)] = node.id

    for node_type, (directory, prefix) in _ID_DIRECTORIES.items():
        for path in markdown_files(wiki_root / directory):
            if path.name in NON_PAGE_FILENAMES:
                continue
            page = load_markdown_page(path)
            raw_id = page.frontmatter.get("id")
            preferred_id = raw_id if isinstance(raw_id, str) and raw_id.strip() else f"{prefix}:{path.stem}"
            node_id = _unique_node_id(nodes, preferred_id, path)
            title = page.frontmatter.get("title") or page.frontmatter.get("name")
            status = page.frontmatter.get("status")
            node = GraphNode(
                id=node_id,
                type=node_type,
                title=title if isinstance(title, str) else path.stem,
                path=str(path),
                status=status if isinstance(status, str) else None,
            )
            nodes[node.id] = node
            pages_by_id[node.id] = page
            path_to_id[str(path)] = node.id

    for node_type, (directory, prefix) in _PATH_ID_DIRECTORIES.items():
        for path in markdown_files(wiki_root / directory):
            if path.name in NON_PAGE_FILENAMES:
                continue
            page = load_markdown_page(path)
            node_id = _unique_node_id(nodes, f"{prefix}:{path.stem}", path)
            title = page.frontmatter.get("title")
            status = page.frontmatter.get("status")
            node = GraphNode(
                id=node_id,
                type=node_type,
                title=title if isinstance(title, str) else path.stem,
                path=str(path),
                status=status if isinstance(status, str) else None,
            )
            nodes[node.id] = node
            pages_by_id[node.id] = page
            path_to_id[str(path)] = node.id

    for requirement in read_app_requirement_pages(wiki_root):
        path = requirement.page.path
        node_id = _unique_node_id(nodes, f"areq:{path.stem}", path)
        node = GraphNode(
            id=node_id,
            type="app-requirement",
            title=path.stem,
            path=str(path),
            status=requirement.status,
        )
        nodes[node.id] = node
        pages_by_id[node.id] = requirement
        path_to_id[str(path)] = node.id

    return nodes, pages_by_id, path_to_id


def _unique_node_id(nodes: dict[str, GraphNode], preferred: str, path: Path) -> str:
    """Keep every page addressable when malformed ids collide."""

    if preferred not in nodes:
        return preferred
    stem = path.stem or "page"
    candidate = f"{preferred}:duplicate:{stem}"
    suffix = 2
    while candidate in nodes:
        candidate = f"{preferred}:duplicate:{stem}:{suffix}"
        suffix += 1
    return candidate


def _collect_edges(
    wiki_root: Path,
    nodes: dict[str, GraphNode],
    pages_by_id: dict[str, Any],
    path_to_id: dict[str, str],
) -> tuple[list[GraphEdge], list[dict[str, str]]]:
    edges: list[GraphEdge] = []
    dangling: list[dict[str, str]] = []
    feature_ids = [node_id for node_id, node in nodes.items() if node.type == "feature"]

    def add(source: str, target: str, kind: str, evidence: str) -> None:
        if source == target:
            return
        edges.append(GraphEdge(source=source, target=target, kind=kind, evidence=evidence))

    for feature_id in feature_ids:
        feature = pages_by_id[feature_id]
        for app_id in feature.apps:
            if f"app:{app_id}" in nodes:
                add(feature_id, f"app:{app_id}", "targets", "frontmatter-apps")
        related_section = section_text(feature.page.body, "Related features")
        for match in FEATURE_ID_PATTERN.findall(related_section):
            if match == feature_id:
                continue
            if match in nodes:
                add(feature_id, match, "related", "related-features-section")
            else:
                dangling.append({"from": feature_id, "reference": match, "path": str(feature.page.path)})

    attachment_rules = {
        "design": "has-design",
        "api-contract": "has-contract",
        "advisory-review": "has-review",
        "app-requirement": "has-requirement",
    }
    for node_id, node in nodes.items():
        kind = attachment_rules.get(node.type)
        if kind is None or node.path is None:
            continue
        page = pages_by_id.get(node_id)
        frontmatter = getattr(page, "frontmatter", None)
        if frontmatter is None and hasattr(page, "page"):
            frontmatter = page.page.frontmatter
        feature_ref = frontmatter.get("feature-id") if isinstance(frontmatter, dict) else None
        filename = Path(node.path).name
        if isinstance(feature_ref, str) and feature_ref in nodes:
            add(feature_ref, node_id, kind, "frontmatter-feature-id")
            continue
        if isinstance(feature_ref, str):
            dangling.append({"from": node_id, "reference": feature_ref, "path": node.path})
        prefix_match = FEATURE_ID_PATTERN.match(filename)
        if prefix_match and prefix_match.group(0) in nodes:
            add(prefix_match.group(0), node_id, kind, "filename-prefix")

    for node_id, node in nodes.items():
        if node.type not in ("business-rule", "persona") or node.path is None:
            continue
        page = pages_by_id[node_id]
        for feature_id in feature_ids:
            if page_references_feature(page.frontmatter, page.body, Path(node.path).name, feature_id):
                if node.type == "business-rule":
                    add(feature_id, node_id, "constrained-by", "body-reference")
                else:
                    add(node_id, feature_id, "serves", "body-reference")

    specific_pairs = {(edge.source, edge.target) for edge in edges}
    specific_pairs.update((edge.target, edge.source) for edge in edges)
    for node_id, node in nodes.items():
        if node.path is None:
            continue
        page = pages_by_id[node_id]
        body = page.body if hasattr(page, "body") else page.page.body
        for raw_target in extract_markdown_links(body):
            target = resolve_relative_markdown_link(Path(node.path), raw_target, wiki_root)
            if target is None:
                continue
            resolved = str(target)
            target_id = path_to_id.get(resolved)
            if target_id is None:
                # A topic, research, plan, direction or roadmap page is not a graph node, and a link to one is not dangling.
                if not _is_general_page(target, wiki_root):
                    dangling.append({"from": node_id, "reference": raw_target, "path": node.path})
                continue
            if target_id == node_id or (node_id, target_id) in specific_pairs:
                continue
            edges.append(GraphEdge(source=node_id, target=target_id, kind="links-to", evidence="markdown-link"))

    return edges, dangling


def _is_general_page(target: Path, wiki_root: Path) -> bool:
    """Whether a link target is a page the graph leaves out of its nodes: a general page, or a release record, bug, incident or technical design page."""

    try:
        relative = target.relative_to(wiki_root.resolve()).as_posix()
    except ValueError:
        return False
    if general_page_kind(relative) is not None:
        return target.is_file()
    parts = relative.split("/")
    return len(parts) == 2 and parts[0] in _RECORD_FOLDERS and is_page_path(relative) and target.is_file()


# ---------------------------------------------------------------------------
# Mermaid rendering


def render_mermaid(envelope: dict[str, Any], view: str, feature_id: str | None = None, app_id: str | None = None) -> str:
    nodes = envelope["facts"]["nodes"]
    edges = envelope["facts"]["edges"]
    blocked_ids = {fact.get("feature_id") for fact in envelope.get("blocker_facts", []) if fact.get("feature_id")}

    if view == "lifecycle":
        return _mermaid_lifecycle(nodes, blocked_ids)
    if view == "ego":
        return _mermaid_ego(nodes, edges, feature_id or "")
    if view == "app":
        return _mermaid_app(nodes, edges, app_id or "")
    raise ValueError(f"Unknown mermaid view: {view}")


def _mermaid_id(node_id: str) -> str:
    return "n_" + re.sub(r"[^A-Za-z0-9_]", "_", node_id)


def _mermaid_label(text: str) -> str:
    """Sanitize one label fragment. Join fragments with _mermaid_multiline, never embed <br/> here."""
    cleaned = text.replace('"', "#quot;").replace("`", "").replace("|", "/").replace("<", "").replace(">", "")
    return cleaned.strip()


def _mermaid_multiline(*fragments: str) -> str:
    return "<br/>".join(_mermaid_label(fragment) for fragment in fragments if fragment)


_STAGE_CLASS = {
    "raw": "po",
    "specified": "po",
    "ready-for-design": "design",
    "in-design": "design",
    "ready-for-dev": "dev",
    "in-dev": "dev",
    "ready-for-qa": "qa",
    "in-qa": "qa",
    "ready-for-release": "release",
    "released": "done",
}


def _mermaid_lifecycle(nodes: list[dict[str, Any]], blocked_ids: set[str]) -> str:
    lines = ["flowchart LR"]
    class_lines: list[str] = []
    stage_representatives: list[str] = []
    for stage in LIFECYCLE_STAGES:
        stage_features = [node for node in nodes if node["type"] == "feature" and node.get("status") == stage]
        if not stage_features:
            continue
        stage_id = "s_" + re.sub(r"[^A-Za-z0-9_]", "_", stage)
        lines.append(f'  subgraph {stage_id}["{_mermaid_label(stage)}"]')
        for node in stage_features:
            node_ref = _mermaid_id(node["id"])
            label = _mermaid_multiline(node["id"], str(node["title"]))
            lines.append(f'    {node_ref}["{label}"]')
            if node.get("health") == "error":
                class_lines.append(f"  class {node_ref} broken")
            elif node["id"] in blocked_ids:
                class_lines.append(f"  class {node_ref} blocked")
            else:
                class_lines.append(f"  class {node_ref} {_STAGE_CLASS[stage]}")
        lines.append("  end")
        stage_representatives.append(_mermaid_id(stage_features[0]["id"]))
    invalid_features = [
        node
        for node in nodes
        if node["type"] == "feature" and node.get("status") not in LIFECYCLE_STAGES
    ]
    if invalid_features:
        lines.append('  subgraph s_invalid["invalid"]')
        for node in invalid_features:
            node_ref = _mermaid_id(node["id"])
            label = _mermaid_multiline(node["id"], str(node["title"]))
            lines.append(f'    {node_ref}["{label}"]')
            # An invalid status is a malformed lifecycle fact. Keep it visible
            # as broken instead of assigning it to an invented valid stage.
            class_lines.append(f"  class {node_ref} broken")
        lines.append("  end")
        stage_representatives.append(_mermaid_id(invalid_features[0]["id"]))
    # Mermaid may lay disconnected subgraphs out in reverse or arbitrary
    # order. Invisible links constrain the pipeline order without rendering
    # dependency edges that do not exist in the wiki facts.
    lines.extend(
        f"  {previous} ~~~ {current}"
        for previous, current in zip(stage_representatives, stage_representatives[1:])
    )
    lines.extend(class_lines)
    lines.extend(
        [
            "  classDef po fill:#9ec5f4,stroke:#256abf,color:#0b0b0b",
            "  classDef design fill:#f5cf7e,stroke:#8a5c00,color:#0b0b0b",
            "  classDef dev fill:#7cd7b2,stroke:#0f7a55,color:#0b0b0b",
            "  classDef qa fill:#c9b6f0,stroke:#5b3cb3,color:#0b0b0b",
            "  classDef release fill:#f2a7c3,stroke:#a8325f,color:#0b0b0b",
            "  classDef done fill:#8fd08f,stroke:#008300,color:#0b0b0b",
            "  classDef blocked fill:#fcfcfb,stroke:#d03b3b,stroke-width:3px,color:#0b0b0b",
            "  classDef broken fill:#fcfcfb,stroke:#898781,stroke-dasharray:6 4,color:#52514e",
        ]
    )
    return "\n".join(lines)


def _mermaid_ego(nodes: list[dict[str, Any]], edges: list[dict[str, Any]], feature_id: str) -> str:
    node_map = {node["id"]: node for node in nodes}
    center = node_map.get(feature_id)
    if center is None:
        return f'flowchart TD\n  missing["No feature page found for {_mermaid_label(feature_id)}"]'
    lines = ["flowchart TD"]
    center_ref = _mermaid_id(feature_id)
    center_label = _mermaid_multiline(feature_id, str(center["title"]))
    lines.append(f'  {center_ref}["{center_label}"]:::center')
    seen = {feature_id}
    for edge in edges:
        if feature_id not in (edge["source"], edge["target"]):
            continue
        other_id = edge["target"] if edge["source"] == feature_id else edge["source"]
        other = node_map.get(other_id)
        if other is None:
            continue
        other_ref = _mermaid_id(other_id)
        if other_id not in seen:
            label = _mermaid_multiline(other["type"], str(other["title"]))
            lines.append(f'  {other_ref}["{label}"]')
            seen.add(other_id)
        source_ref = _mermaid_id(edge["source"])
        target_ref = _mermaid_id(edge["target"])
        lines.append(f"  {source_ref} -->|{_mermaid_label(edge['kind'])}| {target_ref}")
    lines.append("  classDef center fill:#3987e5,stroke:#104281,color:#ffffff")
    return "\n".join(lines)


def _mermaid_app(nodes: list[dict[str, Any]], edges: list[dict[str, Any]], app_id: str) -> str:
    app_node_id = f"app:{app_id}"
    node_map = {node["id"]: node for node in nodes}
    lines = ["flowchart LR"]
    app_ref = _mermaid_id(app_node_id)
    retired = node_map.get(app_node_id, {}).get("status") == "retired"
    lines.append(f'  {app_ref}(["{_mermaid_label(app_id + " (retired)" if retired else app_id)}"]):::app')
    for edge in edges:
        if edge["kind"] == "targets" and edge["target"] == app_node_id:
            feature = node_map.get(edge["source"])
            if feature is None:
                continue
            feature_ref = _mermaid_id(feature["id"])
            label = _mermaid_multiline(feature["id"], str(feature["title"]), feature.get("status") or "")
            lines.append(f'  {feature_ref}["{label}"]')
            lines.append(f"  {feature_ref} --> {app_ref}")
            for requirement_edge in edges:
                if requirement_edge["kind"] == "has-requirement" and requirement_edge["source"] == feature["id"]:
                    requirement = node_map.get(requirement_edge["target"])
                    # Requirement pages are named F-XXX-<app-id>.md, so the node ID says which app it is for.
                    if requirement is None or requirement["id"].lower() != f"areq:{feature['id']}-{app_id}".lower():
                        continue
                    requirement_ref = _mermaid_id(requirement["id"])
                    status = requirement.get("status") or "unknown"
                    requirement_label = _mermaid_multiline("requirement", status)
                    lines.append(f'  {requirement_ref}["{requirement_label}"]')
                    lines.append(f"  {feature_ref} -.-> {requirement_ref}")
    lines.append("  classDef app fill:#eb6834,stroke:#8f3a17,color:#ffffff")
    return "\n".join(lines)
