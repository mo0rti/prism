"""Deterministic linting for Prism generated-project wiki state."""

from __future__ import annotations

import re
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import date
from functools import cached_property
from pathlib import Path
from typing import Any, NamedTuple
from urllib.parse import unquote, urlsplit

from prism_cli.app_model import (
    CAPABILITIES,
    CAPABILITY_HAS_UI,
    UNKNOWN,
    WORKSPACE_REPOSITORY_ID,
    WorkspaceModel,
    api_surface_without_api_app_message,
    retired_in_scope_message,
)
from prism_cli.wiki_model import (
    VALID_ADVISORY_REVIEW_STATES,
    VALID_APP_REQUIREMENT_STATUSES,
    VALID_FEATURE_OWNERS,
    VALID_FEATURE_STATUSES,
    RELEASE_EVIDENCE_REQUIRED,
    VALID_OPEN_QUESTION_OWNERS,
    AppRequirementPage,
    FeaturePage,
    MarkdownPage,
    candidate_relative_markdown_link as _candidate_relative_link,
    extract_markdown_links,
    is_pending_intake_source,
    processed_source_path,
    source_link_parts,
    normalize_feature_id,
    feature_id_from_path,
    history_date_fields,
    parse_conflict_report,
    parse_status_board_rows,
    parse_iso_date,
    parse_open_question_rows,
    parse_delivery_evidence,
    api_surface_declared,
    parse_advisory_required_actions,
    parse_revalidation,
    read_feature_pages,
    read_app_requirement_pages,
    read_wiki_settings,
    read_wiki_pages,
    section_text,
    within_wiki_read_scope,
)
from prism_cli.fs_safety import reparse_kind
from prism_cli.wiki_index import (
    CURRENT_STATE_DIRECTORIES,
    GENERAL_PAGE_FOLDERS,
    GENERAL_PAGE_STATUSES,
    ROOT_PAGE_KINDS,
    is_current_state_page,
    is_page_path,
    is_project_doc_target,
    parse_index_entries,
)
from prism_cli.wiki_links import heading_anchors, iter_markdown_links, parse_external_link
from prism_cli.wiki_paths import REPARSE, UNSAFE, decoded_link_path, resolve_confined, resolve_to_path
from prism_cli.wiki_log import (
    LOG_FIELD_PATTERN,
    LOG_FIELDS,
    LOG_HEADING_PATTERN,
    last_verifications,
    split_log_entries,
)
from prism_cli.workspace import (
    MANIFEST_FILE,
    WorkspaceLoadResult,
    detect_workspace_kind,
    inspect_workspace,
    load_resolved_workspace,
)


DEFAULT_WIKI_STALE_AFTER_DAYS = 14
PENDING_BOARD_REVIEW_STATUSES = {"ready-for-design", "in-design", "ready-for-dev", "in-dev"}
DESIGN_REQUIRED_STATUSES = {"ready-for-dev", "in-dev", "done"}
APP_REQUIREMENTS_REQUIRED_STATUSES = {"ready-for-dev", "in-dev"}
API_CONTRACT_DOWNSTREAM_STATUSES = {"ready-for-dev", "in-dev"}

WIKI_BLOCKER_CODES = {
    "pending-board-review",
    "missing-design",
    "missing-app-requirements",
    "unresolved-open-questions",
    "api-contract-not-ready",
    "cross-app-dependency",
}
EXPECTED_OWNER_BY_STATUS = {
    "raw": "po",
    "specified": "po",
    "ready-for-design": "designer",
    "in-design": "designer",
    "ready-for-dev": "dev",
    "in-dev": "dev",
    "done": "none",
}

_FEATURE_ID_PATTERN = re.compile(r"\bF-\d+\b")
_FEATURE_FILE_PATTERN = re.compile(r"\bF-\d+(?:-[A-Za-z0-9][A-Za-z0-9_-]*)?\.md\b")
_MARKDOWN_LINK_PATTERN = re.compile(r"(?<!!)\[[^\]]*\]\([^)]*\)")
_WIKI_PATH_PATTERN = r"(?P<path>(?:(?:knowledge/)?wiki/)?(?:\.\.?/)*(?:{directory})/[A-Za-z0-9][A-Za-z0-9_-]*\.md\b)"
_EXTERNAL_URL_PATTERN = re.compile(r"(?i)(?:(?:https?|ftp):|//)[^\s<>()]+")
_NON_SOURCE_FILENAMES = {
    "BOARD.md",
    "PROJECT_FOUNDATION.md",
    "SCHEMA.md",
    "LIFECYCLE.md",
    "SETTINGS.md",
    "WIKI_REPORT.md",
    "log.md",
    "status-board.md",
}
_SCHEMA_VERSION_FILES = ("SCHEMA.md", "LIFECYCLE.md")
SUPPORTED_SCHEMA_VERSION = 1
# A dated record keeps its own date field; every other page kind carries none.
_RECORD_DATE_FIELDS = {"decisions": "date"}
# The five evidence labels a current-state page uses as a bold run-in label.
EVIDENCE_LABELS = ("Decided", "Observed", "Proposed", "Assumed", "Unknown")
# A claim that rests on evidence must link it.
_LINKED_EVIDENCE_LABELS = frozenset({"Decided", "Observed"})
# `**Label:** text` at the start of a list item or paragraph. A bold word whose colon sits
# outside the bold (`**backend**: ...`) is a name, not a label.
_EVIDENCE_LABEL_LINE = re.compile(r"^(?P<indent>[ \t]*)(?P<marker>(?:[-*+]|\d+[.)])[ \t]+)?(?:\[[ xX]\][ \t]+)?\*\*(?P<label>[^*\n:]+):\*\*")
_LIST_ITEM_LINE = re.compile(r"^[ \t]*(?:[-*+]|\d+[.)])[ \t]+")
_CLAIM_EVIDENCE_LINK = re.compile(r"\[[^\]]+\]\(\s*<?[^)\s>]+|https?://\S+")
# Pages that state what is true now. Decisions and advisory reviews are records.
_CURRENT_STATE_DIRECTORIES = CURRENT_STATE_DIRECTORIES
# Freshness asks for a review and never gates a lifecycle action or changes a status.
FRESHNESS_CODES = frozenset({"stale-page", "never-verified"})
_ADR_ID_PATTERN = re.compile(r"^ADR-\d+$", re.IGNORECASE)
_FRONTMATTER_PAGE_DIRECTORIES = {
    "api-contracts",
    "business-rules",
    "decisions",
    "design",
    "personas",
    *GENERAL_PAGE_FOLDERS,
}


@dataclass(frozen=True)
class WikiDiagnostic:
    code: str
    severity: str
    path: str
    message: str
    feature_id: str | None = None
    # False for a finding that asks for a review or reports a link outside the wiki: it never gates a lifecycle action.
    gates: bool = True

    @cached_property
    def resolved_path(self) -> Path:
        # Diagnostics belong to one lint snapshot. Resolve each path once, not
        # once per feature/action; a fresh read creates fresh diagnostics.
        return Path(self.path).resolve()

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "code": self.code,
            "severity": self.severity,
            "path": self.path,
            "message": self.message,
        }
        if self.feature_id:
            data["feature_id"] = self.feature_id
        return data


@dataclass(frozen=True)
class WikiLintResult:
    root: Path
    diagnostics: list[WikiDiagnostic] = field(default_factory=list)
    feature_count: int = 0
    # Findings that only `prism wiki lint` reports (`never-verified`). Status, queries, the graph and the lifecycle gates read `diagnostics`.
    information: list[WikiDiagnostic] = field(default_factory=list)

    @property
    def all_diagnostics(self) -> list[WikiDiagnostic]:
        """The diagnostics and the information findings in report order."""

        return sorted([*self.diagnostics, *self.information], key=_diagnostic_order)

    @property
    def error_count(self) -> int:
        return sum(1 for diagnostic in self.diagnostics if diagnostic.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for diagnostic in self.diagnostics if diagnostic.severity == "warning")

    @property
    def is_clean(self) -> bool:
        return self.error_count == 0

    @property
    def readiness_blockers(self) -> list[WikiDiagnostic]:
        """Return valid-but-not-ready workflow findings without changing lint semantics."""

        return [diagnostic for diagnostic in self.diagnostics if diagnostic.code in WIKI_BLOCKER_CODES]

    @property
    def integrity_errors(self) -> list[WikiDiagnostic]:
        """Return errors that mean the wiki cannot be trusted as structurally sound."""

        return [
            diagnostic
            for diagnostic in self.diagnostics
            if diagnostic.severity == "error" and diagnostic.code not in WIKI_BLOCKER_CODES
        ]

    @property
    def non_blocker_warnings(self) -> list[WikiDiagnostic]:
        return [
            diagnostic
            for diagnostic in self.diagnostics
            if diagnostic.severity == "warning" and diagnostic.code not in WIKI_BLOCKER_CODES
        ]

    def to_dict(self) -> dict[str, Any]:
        confidence = "error" if self.error_count else "degraded" if self.warning_count else "high"
        inspection = inspect_workspace(self.root)
        return {
            "schema_version": 1,
            "experimental": True,
            "command": "wiki lint",
            "confidence": confidence,
            "root": str(self.root),
            "workspace": {
                "kind": detect_workspace_kind(self.root),
                "project_name": inspection.project_name,
                **({"purpose": inspection.model.purpose} if inspection.model.purpose else {}),
                "apps": inspection.apps,
            },
            "facts": {
                "feature_count": self.feature_count,
                "error_count": self.error_count,
                "warning_count": self.warning_count,
                "clean": self.is_clean,
            },
            "blocker_facts": [
                diagnostic.to_dict()
                for diagnostic in self.diagnostics
                if diagnostic.code in WIKI_BLOCKER_CODES
            ],
            "required_obligations": [
                {"code": diagnostic.code, "path": diagnostic.path}
                for diagnostic in self.diagnostics
                if diagnostic.code in WIKI_BLOCKER_CODES
            ],
            "sources": [str(self.root / "knowledge" / "wiki")],
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.all_diagnostics],
        }


# One lint call resolves the same wiki paths many times (every check re-resolves
# every page and the wiki folders). Resolving is a pair of syscalls, so a call
# keeps its answers here. The memo is local to one ``lint_wiki`` call.
_RESOLVE_MEMO: ContextVar[dict[str, Path] | None] = ContextVar("prism_lint_resolve_memo", default=None)


def _resolve(path: Path) -> Path:
    """Return ``path.resolve()``, remembered for the rest of the current lint call."""

    memo = _RESOLVE_MEMO.get()
    if memo is None:
        return path.resolve()
    key = str(path)
    resolved = memo.get(key)
    if resolved is None:
        resolved = memo[key] = path.resolve()
    return resolved


@within_wiki_read_scope
def lint_wiki(workspace_root: Path, *, today: date | None = None) -> WikiLintResult:
    """Lint the wiki of one workspace. `today` is the clock for the freshness checks."""

    token = _RESOLVE_MEMO.set({})
    try:
        return _lint_wiki(workspace_root, today=today)
    finally:
        _RESOLVE_MEMO.reset(token)


def _lint_wiki(workspace_root: Path, *, today: date | None = None) -> WikiLintResult:
    root = workspace_root.expanduser().resolve()
    wiki_root = root / "knowledge" / "wiki"
    diagnostics: list[WikiDiagnostic] = []

    if not wiki_root.exists():
        diagnostics.append(_diag("missing-wiki-root", "error", wiki_root, "Missing knowledge/wiki directory."))
        return WikiLintResult(root=root, diagnostics=diagnostics)

    # SETTINGS.md is optional by contract. SCHEMA.md, LIFECYCLE.md, the index and the status
    # board remain the structural files that lint requires before it can reason about the wiki.
    for required in ("SCHEMA.md", "LIFECYCLE.md", "index.md", "status-board.md"):
        required_path = wiki_root / required
        if not required_path.exists():
            diagnostics.append(
                _diag(
                    "missing-required-wiki-file",
                    "error",
                    required_path,
                    f"Missing required wiki file: {required}.",
                )
            )

    settings = read_wiki_settings(wiki_root)
    diagnostics.extend(_diag(code, "warning", settings.path, message) for code, message in settings.diagnostics)

    load = load_resolved_workspace(root)
    model = load.manifest.model if load.manifest is not None else WorkspaceModel(schema_version=0)
    diagnostics.extend(_lint_unknown_app_capabilities(model, root / MANIFEST_FILE))

    feature_pages = read_feature_pages(wiki_root)
    requirement_pages = read_app_requirement_pages(wiki_root)
    all_pages = read_wiki_pages(wiki_root)
    requirements_by_feature_app = {
        (normalize_feature_id(page.feature_id), page.app): page
        for page in requirement_pages
        if page.feature_id and page.app
    }

    for requirement in requirement_pages:
        diagnostics.extend(_lint_app_requirement(requirement, model))

    features_by_id: dict[str, FeaturePage] = {}
    for feature in feature_pages:
        diagnostics.extend(_lint_feature(feature, model))
        feature_id = feature.feature_id
        if normalize_feature_id(feature_id) in features_by_id:
            diagnostics.append(
                _diag("duplicate-feature-id", "error", feature.page.path, f"Duplicate feature id `{feature_id}`.", feature_id)
            )
        features_by_id[normalize_feature_id(feature_id)] = feature

    requirement_keys: set[tuple[str, str]] = set()
    known_feature_ids = set(features_by_id)
    for requirement in requirement_pages:
        if not requirement.feature_id or not requirement.app:
            continue
        key = (normalize_feature_id(requirement.feature_id), requirement.app)
        if key in requirement_keys:
            diagnostics.append(_diag("duplicate-app-requirement", "error", requirement.page.path,
                f"Multiple requirement pages declare `{key[0]}` / `{key[1]}`.", requirement.feature_id))
        requirement_keys.add(key)
        if key[0] not in known_feature_ids:
            diagnostics.append(_diag("orphan-app-requirement", "error", requirement.page.path,
                f"Requirement refers to missing feature `{requirement.feature_id}`.", requirement.feature_id))

    for feature in feature_pages:
        if feature.status == "done":
            diagnostics.extend(_lint_done_completion(feature, requirement_pages, all_pages, wiki_root))

    # Auxiliary pages have their own frontmatter formats. Surface parse errors
    # so a malformed design, contract, or decision cannot silently disappear
    # from the read surface.
    feature_and_requirement_paths = {
        _resolve(page.page.path) for page in feature_pages
    } | {_resolve(page.page.path) for page in requirement_pages}
    for page in all_pages:
        if _resolve(page.path) in feature_and_requirement_paths:
            continue
        diagnostics.extend(_lint_auxiliary_page(page, wiki_root))

    diagnostics.extend(
        _lint_feature_blockers(
            feature_pages,
            requirements_by_feature_app,
            _design_pages_by_feature(all_pages, wiki_root),
            model,
        )
    )
    diagnostics.extend(_lint_api_contract_blockers(feature_pages, requirement_pages, all_pages, wiki_root))
    diagnostics.extend(_lint_cross_app_dependencies(requirement_pages, feature_pages, wiki_root))
    diagnostics.extend(_lint_history_dates(all_pages, wiki_root))
    diagnostics.extend(_lint_schema_versions(all_pages, wiki_root))
    log = _read_log(wiki_root / "log.md")
    diagnostics.extend(_lint_log_entries(log))
    diagnostics.extend(_lint_evidence_labels(all_pages, wiki_root))
    diagnostics.extend(_lint_decision_supersession(all_pages, wiki_root))
    diagnostics.extend(_lint_superseded_decision_citations(all_pages, wiki_root))
    diagnostics.extend(_lint_intake_items(root))
    diagnostics.extend(_lint_links(all_pages, wiki_root, root, feature_pages, requirement_pages, load))
    stale, information = _lint_freshness(all_pages, wiki_root, root, log, settings.stale_after_days, today or date.today())
    diagnostics.extend(stale)

    diagnostics.extend(_lint_index_entries(all_pages, wiki_root))

    board_path = wiki_root / "status-board.md"
    if board_path.exists():
        board_rows, board_errors = parse_status_board_rows(board_path)
        for message in board_errors:
            diagnostics.append(_diag("malformed-status-board", "error", board_path, message))
        if not board_errors:
            board_feature_ids = {normalize_feature_id(row.feature_id) for row in board_rows}
            for feature_id, feature in features_by_id.items():
                if feature_id not in board_feature_ids:
                    diagnostics.append(
                        _diag(
                            "feature-missing-from-status-board",
                            "error",
                            board_path,
                            f"Feature `{feature.feature_id}` has a feature page but no row in status-board.md.",
                            feature.feature_id,
                        )
                    )
        for row in board_rows:
            feature = features_by_id.get(normalize_feature_id(row.feature_id))
            if feature is None:
                diagnostics.append(
                    _diag(
                        "status-board-missing-feature",
                        "error",
                        board_path,
                        f"status-board.md references `{row.feature_id}` but no matching feature page exists.",
                        row.feature_id,
                    )
                )
                continue
            if feature.status and row.status != feature.status:
                diagnostics.append(
                    _diag(
                        "status-board-frontmatter-drift",
                        "error",
                        board_path,
                        f"status-board.md status for `{row.feature_id}` is `{row.status}` but feature frontmatter says `{feature.status}`.",
                        row.feature_id,
                    )
                )
            if feature.owner and row.owner != feature.owner:
                diagnostics.append(
                    _diag(
                        "status-board-frontmatter-drift",
                        "error",
                        board_path,
                        f"status-board.md owner for `{row.feature_id}` is `{row.owner}` but feature frontmatter says `{feature.owner}`.",
                        row.feature_id,
                    )
                )
            if feature.advisory_review and row.advisory_review != feature.advisory_review:
                diagnostics.append(
                    _diag(
                        "status-board-frontmatter-drift",
                        "error",
                        board_path,
                        f"status-board.md board review for `{row.feature_id}` is `{row.advisory_review}` but feature frontmatter says `{feature.advisory_review}`.",
                        row.feature_id,
                    )
                )

    diagnostics.sort(key=_diagnostic_order)
    return WikiLintResult(root=root, diagnostics=diagnostics, feature_count=len(feature_pages), information=sorted(information, key=_diagnostic_order))


def _lint_done_completion(
    feature: FeaturePage,
    requirement_pages: list[AppRequirementPage],
    pages: list[MarkdownPage],
    wiki_root: Path,
) -> list[WikiDiagnostic]:
    """Apply the post-write Done invariants to a completed feature."""

    diagnostics: list[WikiDiagnostic] = []
    feature_id = normalize_feature_id(feature.feature_id)
    if feature.advisory_review == "pending":
        diagnostics.append(
            _diag(
                "pending-board-review",
                "error",
                feature.page.path,
                f"Done feature `{feature.feature_id}` cannot retain `advisory-review: pending`.",
                feature.feature_id,
            )
        )
    open_questions, _question_errors = parse_open_question_rows(feature.page.body)
    for row in open_questions:
        if row["status"] == "open" and row["owner"] in VALID_OPEN_QUESTION_OWNERS:
            diagnostics.append(
                _diag(
                    "unresolved-open-questions",
                    "error",
                    feature.page.path,
                    f"Done feature `{feature.feature_id}` has an open question assigned to `{row['owner']}` (#{row['number']}).",
                    feature.feature_id,
                )
            )
    requirements = {
        (normalize_feature_id(requirement.feature_id), requirement.app.strip().lower()): requirement
        for requirement in requirement_pages
        if isinstance(requirement.feature_id, str) and isinstance(requirement.app, str)
    }
    for app_id in feature.apps:
        requirement = requirements.get((feature_id, app_id.strip().lower()))
        if requirement is None:
            diagnostics.append(
                _diag(
                    "done-app-requirement",
                    "error",
                    feature.page.path,
                    f"Done feature `{feature.feature_id}` requires a completed app requirement for `{app_id}`.",
                    feature.feature_id,
                )
            )
        elif requirement.status != "done":
            diagnostics.append(
                _diag(
                    "done-app-requirement",
                    "error",
                    requirement.page.path,
                    f"Done feature `{feature.feature_id}` has `{app_id}` requirement status `{requirement.status}`; expected `done`.",
                    feature.feature_id,
                )
            )

    api_pages = _api_contract_pages_for_feature(feature, requirement_pages, pages, wiki_root)
    api_applicable = api_surface_declared(section_text(feature.page.body, "API surface"))
    if api_applicable and not api_pages:
        diagnostics.append(
            _diag(
                "done-api-contract",
                "error",
                feature.page.path,
                f"Done feature `{feature.feature_id}` declares an API surface but has no applicable API contract.",
                feature.feature_id,
            )
        )
    for page in api_pages:
        if page.frontmatter.get("status") != "implemented":
            diagnostics.append(
                _diag(
                    "done-api-contract",
                    "error",
                    page.path,
                    f"Done feature `{feature.feature_id}` requires applicable API contract `{page.path.name}` to be `implemented`.",
                    feature.feature_id,
                )
            )
    if feature.advisory_review == "done":
        advisory_root = _resolve(wiki_root / "advisory")
        reviews: list[MarkdownPage] = []
        for page in pages:
            if not _is_under(page.path, advisory_root):
                continue
            page_feature_id = page.frontmatter.get("feature-id")
            if not isinstance(page_feature_id, str) or not page_feature_id.strip():
                page_feature_id = feature_id_from_path(page.path)
            if isinstance(page_feature_id, str) and normalize_feature_id(page_feature_id) == feature_id:
                reviews.append(page)
        if len(reviews) != 1:
            diagnostics.append(
                _diag(
                    "done-advisory-actions",
                    "error",
                    feature.page.path,
                    f"Done feature `{feature.feature_id}` requires one advisory review page with a checkable required-action section.",
                    feature.feature_id,
                )
            )
        else:
            pending, action_errors = parse_advisory_required_actions(reviews[0].body)
            for message in action_errors:
                diagnostics.append(_diag("done-advisory-actions", "error", reviews[0].path, message, feature.feature_id))
            if pending:
                diagnostics.append(
                    _diag(
                        "done-advisory-actions",
                        "error",
                        reviews[0].path,
                        f"Done feature `{feature.feature_id}` retains unchecked advisory actions: " + "; ".join(pending) + ".",
                        feature.feature_id,
                    )
                )
    return diagnostics


def _api_contract_pages_for_feature(
    feature: FeaturePage,
    requirement_pages: list[AppRequirementPage],
    pages: list[MarkdownPage],
    wiki_root: Path,
) -> list[MarkdownPage]:
    api_root = _resolve(wiki_root / "api-contracts")
    by_path = {_resolve(page.path): page for page in pages if _is_under(page.path, api_root)}
    feature_id = normalize_feature_id(feature.feature_id)
    result: list[MarkdownPage] = []
    for page in by_path.values():
        page_feature_id = page.frontmatter.get("feature-id")
        if not isinstance(page_feature_id, str) or not page_feature_id.strip():
            page_feature_id = feature_id_from_path(page.path)
        if isinstance(page_feature_id, str) and normalize_feature_id(page_feature_id) == feature_id:
            result.append(page)
    sources = [feature.page] + [
        requirement.page
        for requirement in requirement_pages
        if isinstance(requirement.feature_id, str)
        and normalize_feature_id(requirement.feature_id) == feature_id
        and requirement.app in feature.apps
    ]
    for source in sources:
        for raw_target in extract_markdown_links(source.body):
            target = _reference_path(source.path, raw_target, wiki_root, "api-contracts")
            if target is not None and target in by_path and by_path[target] not in result:
                result.append(by_path[target])
        for raw_target in _wiki_path_references(source.body, "api-contracts"):
            target = _reference_path(source.path, raw_target, wiki_root, "api-contracts")
            if target is not None and target in by_path and by_path[target] not in result:
                result.append(by_path[target])
    return sorted(result, key=lambda page: page.path.as_posix())


def _is_under(path: Path, root: Path) -> bool:
    try:
        _resolve(path).relative_to(_resolve(root))
    except (OSError, RuntimeError, ValueError):
        return False
    return True


def _lint_feature_blockers(
    feature_pages: list[FeaturePage],
    requirements_by_feature_app: dict[tuple[str | None, str | None], AppRequirementPage],
    designs_by_feature: dict[str, list[MarkdownPage]],
    model: WorkspaceModel,
) -> list[WikiDiagnostic]:
    diagnostics: list[WikiDiagnostic] = []
    for feature in feature_pages:
        feature_id = feature.feature_id
        path = feature.page.path
        if feature.status in PENDING_BOARD_REVIEW_STATUSES and feature.advisory_review == "pending":
            diagnostics.append(
                _diag(
                    "pending-board-review",
                    "error",
                    path,
                    f"Feature `{feature_id}` is {feature.status} but advisory-review is still pending.",
                    feature_id,
                )
            )

        if feature.status in DESIGN_REQUIRED_STATUSES:
            ui_apps = sorted(
                {app_id for app_id in feature.apps if (app := model.app(app_id)) is not None and app.gate_capability(CAPABILITY_HAS_UI)}
            )
            if (
                ui_apps
                and feature_id not in designs_by_feature
                and not _has_valid_design_exemption(feature)
            ):
                apps = ", ".join(ui_apps)
                if feature.page.frontmatter.get("design") == "not-applicable":
                    message = (
                        f"Feature `{feature_id}` declares `design: not-applicable` for app(s) with a UI "
                        f"{apps}, but `design-exemption-reason` is missing or blank."
                    )
                else:
                    message = (
                        f"Feature `{feature_id}` is {feature.status} for app(s) with a UI {apps} "
                        "but has no matching design page or valid confirmed design exemption."
                    )
                diagnostics.append(
                    _diag(
                        "missing-design",
                        "error",
                        path,
                        message,
                        feature_id,
                    )
                )

        if feature.status in APP_REQUIREMENTS_REQUIRED_STATUSES:
            for app_id in sorted(set(feature.apps)):
                if model.app(app_id) is not None and (
                    normalize_feature_id(feature_id),
                    app_id,
                ) not in requirements_by_feature_app:
                    diagnostics.append(
                        _diag(
                            "missing-app-requirements",
                            "error",
                            path,
                            f"Feature `{feature_id}` is {feature.status} but no app requirement exists for `{app_id}`.",
                            feature_id,
                        )
                    )

        if feature.status in APP_REQUIREMENTS_REQUIRED_STATUSES:
            open_questions, _ = parse_open_question_rows(feature.page.body)
            for row in open_questions:
                if row["status"] == "open" and row["owner"] in VALID_OPEN_QUESTION_OWNERS:
                    diagnostics.append(
                        _diag(
                            "unresolved-open-questions",
                            "error",
                            path,
                            f"Feature `{feature_id}` has an open question assigned to `{row['owner']}` (#{row['number']}).",
                            feature_id,
                        )
                    )
    return diagnostics


def _has_valid_design_exemption(feature: FeaturePage) -> bool:
    """Return whether the feature records the documented design exemption."""

    if feature.page.frontmatter.get("design") != "not-applicable":
        return False
    reason = feature.page.frontmatter.get("design-exemption-reason")
    return isinstance(reason, str) and bool(reason.strip())


def _design_pages_by_feature(pages: list[MarkdownPage], wiki_root: Path) -> dict[str, list[MarkdownPage]]:
    designs: dict[str, list[MarkdownPage]] = {}
    design_root = _resolve(wiki_root / "design")
    for page in pages:
        try:
            _resolve(page.path).relative_to(design_root)
        except ValueError:
            continue
        feature_id = page.frontmatter.get("feature-id")
        if not isinstance(feature_id, str) or not feature_id:
            feature_id = feature_id_from_path(page.path)
        if feature_id:
            designs.setdefault(feature_id, []).append(page)
    return designs


def _lint_api_contract_blockers(
    feature_pages: list[FeaturePage],
    requirement_pages: list[AppRequirementPage],
    pages: list[MarkdownPage],
    wiki_root: Path,
) -> list[WikiDiagnostic]:
    api_root = _resolve(wiki_root / "api-contracts")
    api_pages: list[MarkdownPage] = []
    for page in pages:
        try:
            _resolve(page.path).relative_to(api_root)
        except ValueError:
            continue
        api_pages.append(page)
    api_by_path = {_resolve(page.path): page for page in api_pages}
    api_by_feature: dict[str, list[MarkdownPage]] = {}
    for page in api_pages:
        feature_id = page.frontmatter.get("feature-id")
        if not isinstance(feature_id, str) or not feature_id:
            feature_id = feature_id_from_path(page.path)
        if feature_id:
            api_by_feature.setdefault(feature_id, []).append(page)
    diagnostics: list[WikiDiagnostic] = []
    for feature in feature_pages:
        if feature.status not in API_CONTRACT_DOWNSTREAM_STATUSES:
            continue
        references: list[MarkdownPage] = []
        feature_id = normalize_feature_id(feature.feature_id)
        declared_apps = {app_id.strip().lower() for app_id in feature.apps}
        source_pages = [feature.page] + [
            requirement.page
            for requirement in requirement_pages
            if isinstance(requirement.feature_id, str)
            and normalize_feature_id(requirement.feature_id) == feature_id
            and isinstance(requirement.app, str)
            and requirement.app.strip().lower() in declared_apps
        ]
        for source in source_pages:
            for raw_target in extract_markdown_links(source.body):
                target = _reference_path(source.path, raw_target, wiki_root, "api-contracts")
                if target is None:
                    continue
                contract = api_by_path.get(target)
                if contract is not None and contract not in references:
                    references.append(contract)
            for raw_target in _wiki_path_references(source.body, "api-contracts"):
                target = _reference_path(source.path, raw_target, wiki_root, "api-contracts")
                contract = api_by_path.get(target) if target is not None else None
                if contract is not None and contract not in references:
                    references.append(contract)
        for contract in api_by_feature.get(feature.feature_id, []):
            if contract not in references:
                references.append(contract)
        for contract in sorted(references, key=lambda page: page.path.as_posix()):
            if contract.frontmatter.get("status") == "draft":
                contract_name = contract.path.name
                diagnostics.append(
                    _diag(
                        "api-contract-not-ready",
                        "error",
                        contract.path,
                        f"Feature `{feature.feature_id}` is {feature.status} but API contract `{contract_name}` is still draft.",
                        feature.feature_id,
                    )
                )
    return diagnostics


def _lint_cross_app_dependencies(
    requirement_pages: list[AppRequirementPage],
    feature_pages: list[FeaturePage],
    wiki_root: Path,
) -> list[WikiDiagnostic]:
    features_by_path = {_resolve(feature.page.path): feature for feature in feature_pages}
    features_by_id = {normalize_feature_id(feature.feature_id): feature for feature in feature_pages}
    requirements_by_path = {_resolve(requirement.page.path): requirement for requirement in requirement_pages}
    diagnostics: list[WikiDiagnostic] = []

    for requirement in requirement_pages:
        dependency_body = section_text(requirement.page.body, "Dependencies")
        if not dependency_body:
            continue

        unfinished: set[tuple[str, str]] = set()
        for raw_target in extract_markdown_links(dependency_body):
            target = _reference_path(requirement.page.path, raw_target, wiki_root, "app-requirements")
            if target is None:
                continue
            target_feature = features_by_path.get(target)
            if target_feature is not None and _is_unfinished_feature(target_feature):
                unfinished.add(("feature", target_feature.feature_id))
            target_requirement = requirements_by_path.get(target)
            if target_requirement is not None and _is_unfinished_requirement(target_requirement, features_by_id):
                unfinished.add(("app requirement", _requirement_label(target_requirement)))

        for directory, kind in (("features", "feature"), ("app-requirements", "app requirement")):
            for raw_target in _wiki_path_references(dependency_body, directory):
                target = _reference_path(requirement.page.path, raw_target, wiki_root, directory)
                if target is None:
                    continue
                target_feature = features_by_path.get(target)
                if kind == "feature" and target_feature is not None and _is_unfinished_feature(target_feature):
                    unfinished.add(("feature", target_feature.feature_id))
                target_requirement = requirements_by_path.get(target)
                if kind == "app requirement" and target_requirement is not None and _is_unfinished_requirement(target_requirement, features_by_id):
                    unfinished.add(("app requirement", _requirement_label(target_requirement)))

        feature_by_name = {feature.page.path.name: feature for feature in feature_pages}
        requirement_by_name = {requirement.page.path.name: requirement for requirement in requirement_pages}
        for filename in _FEATURE_FILE_PATTERN.findall(dependency_body):
            target_feature = feature_by_name.get(filename)
            if target_feature is not None and _is_unfinished_feature(target_feature):
                unfinished.add(("feature", target_feature.feature_id))
            target_requirement = requirement_by_name.get(filename)
            if target_requirement is not None and _is_unfinished_requirement(target_requirement, features_by_id):
                unfinished.add(("app requirement", _requirement_label(target_requirement)))

        plain_body = _MARKDOWN_LINK_PATTERN.sub(" ", dependency_body)
        plain_body = _FEATURE_FILE_PATTERN.sub(" ", plain_body)
        for feature_id in _FEATURE_ID_PATTERN.findall(plain_body):
            target_feature = features_by_id.get(normalize_feature_id(feature_id))
            if target_feature is not None and _is_unfinished_feature(target_feature):
                unfinished.add(("feature", feature_id))

        # A requirement page links its own feature page; that link is context,
        # not a dependency, and the requirement is never its own dependency.
        own_feature = normalize_feature_id(requirement.feature_id) if isinstance(requirement.feature_id, str) else None
        own_label = _requirement_label(requirement)
        unfinished = {
            (kind, target)
            for kind, target in unfinished
            if not (kind == "feature" and own_feature is not None and normalize_feature_id(target) == own_feature)
            and not (kind == "app requirement" and target == own_label)
        }

        for kind, target in sorted(unfinished):
            diagnostics.append(
                _diag(
                    "cross-app-dependency",
                    "error",
                    requirement.page.path,
                    f"App requirement `{_requirement_label(requirement)}` depends on unfinished {kind} `{target}`.",
                    requirement.feature_id,
                )
            )
    return diagnostics


def _is_unfinished_feature(feature: FeaturePage) -> bool:
    return feature.status in VALID_FEATURE_STATUSES and feature.status != "done"


def _is_unfinished_requirement(
    requirement: AppRequirementPage,
    features_by_id: dict[str, FeaturePage] | None = None,
) -> bool:
    if requirement.status in VALID_APP_REQUIREMENT_STATUSES and requirement.status != "done":
        return True
    if requirement.status != "done" or features_by_id is None or not isinstance(requirement.feature_id, str):
        return False
    parent = features_by_id.get(normalize_feature_id(requirement.feature_id))
    if parent is None:
        return False
    domains, errors = parse_revalidation(parent.page.frontmatter.get("revalidation"))
    return bool(errors or domains)


def _requirement_label(requirement: AppRequirementPage) -> str:
    if requirement.feature_id and requirement.app:
        return f"{requirement.feature_id}-{requirement.app}"
    return requirement.page.path.stem


def _lint_history_dates(pages: list[MarkdownPage], wiki_root: Path) -> list[WikiDiagnostic]:
    """Report a history-date field in the front matter of a current-state page.

    A decision keeps its own `date` and an advisory review its own `reviewed`: those
    are dated records. Every other page says when something happened in log.md.
    """

    diagnostics: list[WikiDiagnostic] = []
    for page in pages:
        if _is_non_source_page(page.path, wiki_root):
            continue
        allowed = _record_date_field(page.path, wiki_root)
        for field_name in history_date_fields(page):
            if field_name.strip().casefold().replace("_", "-") == allowed:
                continue
            diagnostics.append(
                _diag(
                    "history-date-on-page",
                    "error",
                    page.path,
                    f"`{field_name}` is a history date and does not belong on a current-state page. Remove it and record when it happened in log.md.",
                    feature_id_from_path(page.path),
                )
            )
    return diagnostics


def _record_date_field(path: Path, wiki_root: Path) -> str | None:
    """The date field a dated record keeps, or ``None`` for a current-state page."""

    try:
        relative = _resolve(path).relative_to(_resolve(wiki_root))
    except ValueError:
        return None
    if len(relative.parts) >= 2 and relative.parts[0] in _RECORD_DATE_FIELDS:
        return _RECORD_DATE_FIELDS[relative.parts[0]]
    if len(relative.parts) == 2 and relative.parts[0] == "advisory" and relative.name.startswith("F-") and relative.name.endswith("-review.md"):
        return "reviewed"
    return None


def _lint_schema_versions(pages: list[MarkdownPage], wiki_root: Path) -> list[WikiDiagnostic]:
    """SCHEMA.md and LIFECYCLE.md each start with front matter `schema-version: 1`."""

    diagnostics: list[WikiDiagnostic] = []
    by_name = {page.path.name: page for page in pages if page.path.parent == wiki_root}
    for name in _SCHEMA_VERSION_FILES:
        page = by_name.get(name)
        if page is None:
            continue  # a missing file is reported as missing-required-wiki-file
        value = page.frontmatter.get("schema-version")
        if isinstance(value, bool) or value != SUPPORTED_SCHEMA_VERSION:
            diagnostics.append(
                _diag(
                    "missing-schema-version",
                    "error",
                    page.path,
                    f"{name} must start with front matter `schema-version: {SUPPORTED_SCHEMA_VERSION}`.",
                )
            )
    return diagnostics


def _read_log(log_path: Path) -> tuple[Path, str]:
    """The path of log.md and its text, empty when it cannot be read."""

    try:
        return log_path, log_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return log_path, ""


def _lint_log_entries(log: tuple[Path, str]) -> list[WikiDiagnostic]:
    """Check each log.md entry against the log format. Entries are reported, never rewritten."""

    log_path, text = log
    diagnostics: list[WikiDiagnostic] = []
    for number, heading, body in split_log_entries(text):
        problem = _log_entry_problem(heading, body)
        if problem is None:
            continue
        label = heading if len(heading) <= 80 else heading[:77] + "..."
        diagnostics.append(
            _diag(
                "malformed-log-entry",
                "warning",
                log_path,
                f"Log entry at line {number} (`{label}`) is not in the log format: {problem} See the log.md conventions in SCHEMA.md.",
            )
        )
    return diagnostics


def _log_entry_problem(heading: str, body: list[str]) -> str | None:
    match = LOG_HEADING_PATTERN.match(heading)
    if match is None or parse_iso_date(match.group(1)) is None:
        return "the heading must be `## YYYY-MM-DD <operation> | <subject>`."
    for index, field_name in enumerate(LOG_FIELDS):
        line = body[index] if index < len(body) else ""
        field_match = LOG_FIELD_PATTERN.match(line)
        if field_match is None or field_match.group(1) != field_name:
            return f"line {index + 1} after the heading must be `- {field_name}: <value>`."
    extra = body[len(LOG_FIELDS):]
    if len(extra) > 1:
        return "after the `by` line only one optional line of plain text may follow."
    if extra and extra[0].startswith(("-", "#", "|", ">")):
        return "the optional line after the `by` line must be plain text."
    return None


def _wiki_directory(path: Path, wiki_root: Path) -> str | None:
    """The wiki folder a page sits directly in (`direction.md` and `roadmap.md` stand for themselves), or ``None`` for a page elsewhere."""

    try:
        relative = _resolve(path).relative_to(_resolve(wiki_root))
    except ValueError:
        return None
    if len(relative.parts) == 2:
        return relative.parts[0]
    return relative.parts[0] if len(relative.parts) == 1 and relative.parts[0] in ROOT_PAGE_KINDS else None


def _lint_evidence_labels(pages: list[MarkdownPage], wiki_root: Path) -> list[WikiDiagnostic]:
    """Check the evidence labels of the current-state pages, mechanically.

    A bold run-in label at the start of a list item or paragraph must be one of the
    five labels, and a Decided or Observed claim must link its evidence. Whether the
    link supports the claim is not judged here.
    """

    diagnostics: list[WikiDiagnostic] = []
    for page in pages:
        if _wiki_directory(page.path, wiki_root) not in _CURRENT_STATE_DIRECTORIES or page.path.name.startswith("_"):
            continue
        feature_id = _page_feature_id(page, {}, {})
        lines = page.body.splitlines()
        in_fence = False
        for index, line in enumerate(lines):
            if line.lstrip().startswith(("```", "~~~")):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            match = _EVIDENCE_LABEL_LINE.match(line)
            if match is None:
                continue
            label = match.group("label").strip()
            if label not in EVIDENCE_LABELS:
                diagnostics.append(
                    _diag(
                        "unknown-evidence-label",
                        "warning",
                        page.path,
                        f"`**{label}:**` (body line {index + 1}) is not an evidence label. Use one of {', '.join(f'`{item}`' for item in EVIDENCE_LABELS)}. See Evidence labels in SCHEMA.md.",
                        feature_id,
                        gates=False,
                    )
                )
                continue
            if label not in _LINKED_EVIDENCE_LABELS:
                continue
            if not _CLAIM_EVIDENCE_LINK.search(_claim_block(lines, index, len(match.group("indent")))):
                diagnostics.append(
                    _diag(
                        "unlinked-claim",
                        "warning",
                        page.path,
                        f"The `{label}` claim at body line {index + 1} links no evidence. Link a processed intake item, a record or a URL. See Evidence labels in SCHEMA.md.",
                        feature_id,
                        gates=False,
                    )
                )
    return diagnostics


def _claim_block(lines: list[str], start: int, indent: int) -> str:
    """The text of the list item or paragraph that begins at ``lines[start]``."""

    block = [lines[start]]
    for line in lines[start + 1 :]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            break
        if _EVIDENCE_LABEL_LINE.match(line) or (_LIST_ITEM_LINE.match(line) and len(line) - len(line.lstrip()) <= indent):
            break
        block.append(line)
    return "\n".join(block)


def _decision_pages(pages: list[MarkdownPage], wiki_root: Path) -> list[MarkdownPage]:
    return [
        page
        for page in pages
        if _wiki_directory(page.path, wiki_root) == "decisions" and not page.path.name.startswith("_") and not page.parse_errors
    ]


def _adr_key(value: Any) -> str | None:
    return value.strip().upper() if isinstance(value, str) and _ADR_ID_PATTERN.match(value.strip()) else None


def _lint_decision_supersession(pages: list[MarkdownPage], wiki_root: Path) -> list[WikiDiagnostic]:
    """The two sides of a supersession agree: `supersedes` on the new ADR, `superseded-by` and `status: superseded` on the old one."""

    decisions = _decision_pages(pages, wiki_root)
    by_id: dict[str, MarkdownPage] = {}
    for page in decisions:
        key = _adr_key(page.frontmatter.get("id"))
        if key is not None:
            by_id.setdefault(key, page)

    diagnostics: list[WikiDiagnostic] = []

    def mismatch(page: MarkdownPage, message: str) -> None:
        diagnostics.append(_diag("supersession-mismatch", "error", page.path, message, None))

    for page in decisions:
        own = _adr_key(page.frontmatter.get("id"))
        if own is None:
            continue  # an invalid id is reported by the decision page checks
        status = page.frontmatter.get("status")
        if "supersedes" in page.frontmatter:
            target_key = _adr_key(page.frontmatter["supersedes"])
            if target_key is None:
                mismatch(page, f"{own} has `supersedes: {page.frontmatter['supersedes']}`, which is not one ADR ID such as `ADR-001`.")
            elif target_key == own:
                mismatch(page, f"{own} cannot supersede itself.")
            elif target_key not in by_id:
                mismatch(page, f"{own} supersedes {target_key}, but no decision page has that ID.")
            else:
                target = by_id[target_key]
                if target.frontmatter.get("status") != "superseded" or _adr_key(target.frontmatter.get("superseded-by")) != own:
                    mismatch(
                        page,
                        f"{own} supersedes {target_key}, but {target_key} does not carry `status: superseded` and `superseded-by: {own}`.",
                    )
        if "superseded-by" in page.frontmatter or status == "superseded":
            if status != "superseded":
                mismatch(page, f"{own} has `superseded-by` but its status is `{status}`, not `superseded`.")
            successor_key = _adr_key(page.frontmatter.get("superseded-by"))
            if "superseded-by" not in page.frontmatter:
                mismatch(page, f"{own} has `status: superseded` but no `superseded-by: ADR-NNN`.")
            elif successor_key is None:
                mismatch(page, f"{own} has `superseded-by: {page.frontmatter['superseded-by']}`, which is not one ADR ID such as `ADR-002`.")
            elif successor_key == own:
                mismatch(page, f"{own} cannot be superseded by itself.")
            elif successor_key not in by_id:
                mismatch(page, f"{own} is superseded by {successor_key}, but no decision page has that ID.")
            elif _adr_key(by_id[successor_key].frontmatter.get("supersedes")) != own:
                mismatch(page, f"{own} is superseded by {successor_key}, but {successor_key} does not declare `supersedes: {own}`.")
    return diagnostics


def _lint_superseded_decision_citations(pages: list[MarkdownPage], wiki_root: Path) -> list[WikiDiagnostic]:
    """Warn when a current-state page links a decision that a newer decision supersedes."""

    superseded: dict[Path, tuple[str, str | None]] = {}
    for page in _decision_pages(pages, wiki_root):
        if page.frontmatter.get("status") == "superseded":
            key = _adr_key(page.frontmatter.get("id")) or page.path.stem
            superseded[_resolve(page.path)] = (key, _adr_key(page.frontmatter.get("superseded-by")))
    if not superseded:
        return []

    diagnostics: list[WikiDiagnostic] = []
    for page in pages:
        if _wiki_directory(page.path, wiki_root) not in _CURRENT_STATE_DIRECTORIES or page.path.name.startswith("_"):
            continue
        cited: set[Path] = set()
        for raw_target in extract_markdown_links(page.body):
            candidate = _candidate_relative_link(page.path, raw_target, _resolve(wiki_root))
            if candidate is not None and candidate in superseded and candidate not in cited:
                cited.add(candidate)
                key, successor = superseded[candidate]
                current = f"link {successor}" if successor else "link the decision that replaces it"
                diagnostics.append(
                    _diag(
                        "superseded-decision-cited",
                        "warning",
                        page.path,
                        f"This page links {key}, which is superseded. Update the page to {current} and state the current decision.",
                        _page_feature_id(page, {}, {}),
                        gates=False,
                    )
                )
    return diagnostics


def _intake_item_directories(queue: Path) -> list[Path]:
    """The item folders directly inside an intake queue, in name order. Files and links are not items."""

    try:
        children = sorted(queue.iterdir(), key=lambda item: item.name)
    except OSError:
        return []
    items: list[Path] = []
    for child in children:
        try:
            if child.is_dir() and not child.is_symlink():
                items.append(child)
        except OSError:
            continue
    return items


def _lint_intake_items(root: Path) -> list[WikiDiagnostic]:
    """Check the processed and quarantined intake items. Processed sources are never judged, only their record files."""

    diagnostics: list[WikiDiagnostic] = []
    intake = root / "knowledge" / "intake"
    for item in _intake_item_directories(intake / "processed"):
        if not (item / "MANIFEST.md").is_file():
            diagnostics.append(
                _diag(
                    "processed-source-without-manifest",
                    "warning",
                    item,
                    f"Processed intake item `{item.name}` has no MANIFEST.md listing what was extracted from it. Processed items are immutable: add the manifest in a new, separate operation.",
                )
            )
    for item in _intake_item_directories(intake / "quarantined"):
        report = item / "CONFLICT.md"
        relative = report.relative_to(root).as_posix()
        if not report.is_file():
            diagnostics.append(
                _diag("malformed-conflict", "error", item, f"Quarantined intake item `{item.name}` has no CONFLICT.md. See Conflict quarantine in SCHEMA.md.")
            )
            continue
        try:
            text = report.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as exc:
            diagnostics.append(_diag("malformed-conflict", "error", report, f"`{relative}` cannot be read: {exc}"))
            continue
        status, problems = parse_conflict_report(text)
        for problem in problems:
            diagnostics.append(_diag("malformed-conflict", "error", report, f"`{relative}` is not a valid conflict record: {problem} See Conflict quarantine in SCHEMA.md."))
        if status == "open":
            diagnostics.append(
                _diag(
                    "unresolved-conflict",
                    "warning",
                    report,
                    f"[{relative}]({relative}) records an open conflict. A human resolves it, then sets `status: resolved` in that file.",
                )
            )
    return diagnostics


def _lint_index_entries(pages: list[MarkdownPage], wiki_root: Path) -> list[WikiDiagnostic]:
    """Every wiki page has exactly one line in `index.md`, and every line names a page that exists.

    A project doc line (`../../docs/architecture.md`) is held to the same rule from the other side: it
    names a doc that exists and appears once. Docs the user adds need no line.

    The findings are warnings on the index file and carry no feature ID: a missing line is
    housekeeping, so it never blocks a lifecycle action.
    """

    index_path = wiki_root / "index.md"
    if not index_path.exists():
        return []  # reported as missing-required-wiki-file
    try:
        text = index_path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        return [_diag("malformed-index", "error", index_path, f"Unable to read index.md: {exc}")]

    by_target: dict[str, list[int]] = {}
    for entry in parse_index_entries(text):
        by_target.setdefault(entry.target, []).append(entry.number)
    root = _resolve(wiki_root)
    diagnostics: list[WikiDiagnostic] = []
    page_paths: set[str] = set()
    for page in pages:
        try:
            relative = _resolve(page.path).relative_to(root).as_posix()
        except ValueError:
            continue
        if is_page_path(relative):
            page_paths.add(relative)
    for relative in sorted(page_paths):
        lines = by_target.get(relative, [])
        if not lines:
            diagnostics.append(
                _diag(
                    "missing-index-entry",
                    "warning",
                    index_path,
                    f"`{relative}` has no line in index.md. Add `- [Label]({relative}): one sentence on what the page says now` under its kind's heading.",
                )
            )
        elif len(lines) > 1:
            where = ", ".join(str(number) for number in lines)
            diagnostics.append(
                _diag(
                    "duplicate-index-entry",
                    "warning",
                    index_path,
                    f"`{relative}` has {len(lines)} lines in index.md (lines {where}). Keep one and remove the others.",
                )
            )
    for target in sorted(by_target):
        if target in page_paths:
            continue
        if is_project_doc_target(target):
            diagnostics.extend(_lint_project_doc_lines(index_path, wiki_root, target, by_target[target]))
            continue
        try:
            exists = (wiki_root / target).is_file()
        except (OSError, ValueError):
            exists = False
        if not exists:
            diagnostics.append(
                _diag(
                    "orphan-index-entry",
                    "warning",
                    index_path,
                    f"index.md line {by_target[target][0]} links `{target}`, which is not a page of this wiki. Remove the line or restore the page.",
                )
            )
    return diagnostics


def _lint_project_doc_lines(index_path: Path, wiki_root: Path, target: str, lines: list[int]) -> list[WikiDiagnostic]:
    """The findings for the index lines of one project doc: a doc that does not exist, or a doc listed twice."""

    diagnostics: list[WikiDiagnostic] = []
    try:
        exists = (wiki_root / target).is_file()
    except (OSError, ValueError):
        exists = False
    if not exists:
        diagnostics.append(
            _diag(
                "orphan-index-entry",
                "warning",
                index_path,
                f"index.md line {lines[0]} links the project doc `{target}`, which does not exist. Remove the line or restore the doc.",
            )
        )
    if len(lines) > 1:
        where = ", ".join(str(number) for number in lines)
        diagnostics.append(
            _diag(
                "duplicate-index-entry",
                "warning",
                index_path,
                f"`{target}` has {len(lines)} lines in index.md (lines {where}). Keep one and remove the others.",
            )
        )
    return diagnostics


def _lint_links(
    pages: list[MarkdownPage],
    wiki_root: Path,
    root: Path,
    feature_pages: list[FeaturePage],
    requirement_pages: list[AppRequirementPage],
    load: WorkspaceLoadResult,
) -> list[WikiDiagnostic]:
    """Check every relative Markdown link and every `sources` entry of the wiki pages.

    `root` is the resolved workspace root. A link or source that does not resolve is `broken-link` (error).
    An anchor with no heading is `broken-anchor` (warning). A `repo:<repository-id>/<path>` link is resolved
    through `prism.local.yml`: an unresolved repository is one `external-repository-unresolved` warning and its
    links are skipped. URLs are never fetched, and an external checkout is only asked whether a path exists.

    Only a broken link to a file of the wiki gates a lifecycle action, as it always has; the other findings
    describe the page's sources and never block.
    """

    checker = _LinkChecker(root, _resolve(wiki_root), load)
    feature_by_path = {_resolve(feature.page.path): feature for feature in feature_pages}
    requirement_by_path = {_resolve(requirement.page.path): requirement for requirement in requirement_pages}
    diagnostics: list[WikiDiagnostic] = []
    for page in pages:
        if _is_non_source_page(page.path, wiki_root):
            continue
        links = list(iter_markdown_links(page.body))
        source_fields = _source_fields(page, wiki_root)
        if not links and not source_fields:
            continue
        feature_id = _page_feature_id(page, feature_by_path, requirement_by_path)
        # One finding per distinct problem, with every line it occurs on.
        findings: dict[_LinkFinding, list[int]] = {}
        for line, raw_target in links:
            finding = checker.check_link(page.path, raw_target)
            if finding is not None:
                findings.setdefault(finding, []).append(page.body_offset + line)
        source_text: str | None = None
        for field_name, path_only, entries in source_fields:
            for entry in entries:
                finding = checker.check_source(entry, field_name, path_only)
                if finding is None:
                    continue
                if source_text is None:
                    source_text = _read_page_text(page)
                findings.setdefault(finding, []).append(_source_line(source_text, field_name, entry))
        for finding, lines in findings.items():
            where = f"line {lines[0]}" if len(lines) == 1 else "lines " + ", ".join(str(number) for number in lines)
            diagnostics.append(
                _diag(finding.code, finding.severity, page.path, f"{finding.subject} ({where}) {finding.problem}", feature_id, gates=finding.gates)
            )
    diagnostics.extend(checker.unresolved_repository_diagnostics())
    return diagnostics


class _LinkFinding(NamedTuple):
    code: str
    severity: str
    subject: str
    problem: str
    gates: bool = False


class _LinkChecker:
    """Resolves one lint call's links against the workspace and, for `repo:` links, its external checkouts."""

    def __init__(self, root: Path, wiki_root: Path, load: WorkspaceLoadResult) -> None:
        self.root = root
        self.wiki_root = wiki_root
        self.load = load
        manifest = load.manifest
        model = manifest.model if manifest is not None else WorkspaceModel(schema_version=0)
        self.declared = {repository.id for repository in model.repositories}
        self.unresolved: set[str] = set()
        self._anchors: dict[Path, set[str] | None] = {}

    def check_link(self, page_path: Path, raw_target: str) -> _LinkFinding | None:
        """The finding for one Markdown link target as written, or ``None`` when it is fine or not checked."""

        target = raw_target.strip()
        external = parse_external_link(unquote(target))
        if external is not None:
            return self._check_external(*external, subject=f"Link `{raw_target}`")
        try:
            parsed = urlsplit(target)
        except ValueError:
            return None
        if not target or parsed.scheme or parsed.netloc or parsed.path.startswith("/"):
            return None  # a URL, a mail link or a web path as written is not a relative link
        subject = f"Relative link `{raw_target}`"
        fragment = unquote(parsed.fragment)
        if not parsed.path:
            return self._anchor_finding(page_path, fragment, subject, "this page") if fragment else None
        # The path is decoded, checked and confined as text first (UNC, rooted, drive-qualified, backslash and `..`
        # forms are refused before any filesystem call); only then are its components looked at.
        try:
            base = _resolve(page_path.parent)
        except (OSError, RuntimeError, ValueError):
            return _LinkFinding("broken-link", "error", subject, "does not resolve to an existing file or folder.")
        resolution = resolve_confined(self.root, base, parsed.path)
        if resolution.kind == UNSAFE:
            return _LinkFinding("broken-link", "error", subject, f"is not a safe relative path: it {resolution.problem}")
        if resolution.kind == REPARSE:
            return _LinkFinding("broken-link", "error", subject, resolution.problem or "passes through a symlink or reparse point.")
        if not resolution.ok or resolution.path is None:
            return _LinkFinding(
                "broken-link",
                "error",
                subject,
                "leaves the workspace. Link a file of an external repository as `repo:<repository-id>/<path>`.",
            )
        candidate = resolution.path
        if not resolution.exists:
            return _LinkFinding("broken-link", "error", subject, "does not resolve to an existing file or folder.", gates=self._in_wiki(candidate))
        if fragment and candidate.suffix.lower() == ".md" and candidate.is_file():
            return self._anchor_finding(candidate, fragment, subject, f"`{candidate.name}`")
        return None

    def check_source(self, entry: Any, field_name: str, path_only: bool) -> _LinkFinding | None:
        """The finding for one `sources` entry, or ``None`` when it is fine, a URL or free text."""

        if not isinstance(entry, str):
            return None
        subject = f"`{field_name}` entry `{entry}`"
        external = parse_external_link(entry.strip())
        if external is not None:
            return self._check_external(*external, subject=subject)
        parts = source_link_parts(entry, path_only=path_only)
        if parts is None:
            return None
        resolution = resolve_confined(self.root, self.root, "/".join(parts), percent_encoded=False)
        if resolution.kind == UNSAFE:
            return _LinkFinding("broken-link", "error", subject, f"is not a safe workspace path: it {resolution.problem}")
        if resolution.kind == REPARSE:
            return _LinkFinding("broken-link", "error", subject, resolution.problem or "passes through a symlink or reparse point.")
        if resolution.ok and resolution.exists:
            return None
        hint = (
            f" It is in the pending intake queue, which moves when intake applies; list `{processed_source_path(parts)}` instead."
            if is_pending_intake_source(parts)
            else ""
        )
        return _LinkFinding("broken-link", "error", subject, f"does not exist in the workspace.{hint}")

    def unresolved_repository_diagnostics(self) -> list[WikiDiagnostic]:
        """One `external-repository-unresolved` warning per repository a link points into, reusing the model's finding."""

        diagnostics: list[WikiDiagnostic] = []
        for repository in sorted(self.unresolved):
            model_finding = next(
                (item for item in self.load.diagnostics if item.code == "external-repository-unresolved" and f"`{repository}`" in item.message),
                None,
            )
            if model_finding is not None:
                diagnostics.append(_diag(model_finding.code, "warning", Path(model_finding.path), model_finding.message))
                continue
            diagnostics.append(
                _diag(
                    "external-repository-unresolved",
                    "warning",
                    self.root / "prism.local.yml",
                    f"External repository `{repository}` has no checkout on this machine; add `repositories: {{{repository}: <absolute path>}}` to prism.local.yml. Links into it are skipped.",
                )
            )
        return diagnostics

    def _in_wiki(self, candidate: Path) -> bool:
        try:
            candidate.relative_to(self.wiki_root)
        except ValueError:
            return False
        return True

    def _check_external(self, repository: str, path: str, problem: str | None, *, subject: str) -> _LinkFinding | None:
        if problem is not None:
            return _LinkFinding("broken-link", "error", subject, f"is not a repository link: {problem}")
        if repository == WORKSPACE_REPOSITORY_ID:
            checkout: Path | None = self.root
        elif repository in self.declared:
            checkout = self.load.local_repositories.get(repository)
            if checkout is None:
                self.unresolved.add(repository)
                return None
        else:
            known = ", ".join(f"`{item}`" for item in sorted(self.declared - {WORKSPACE_REPOSITORY_ID})) or "none"
            return _LinkFinding(
                "broken-link",
                "error",
                subject,
                f"names repository `{repository}`, which prism.workspace.yml does not declare (external repositories: {known}).",
            )
        found = _exists_in_checkout(checkout, path)
        if found is None:
            return _LinkFinding(
                "broken-link",
                "error",
                subject,
                f"passes through a symlink or reparse point in the checkout of repository `{repository}`, which lint does not follow.",
            )
        if not found:
            return _LinkFinding("broken-link", "error", subject, f"does not exist in the checkout of repository `{repository}`.")
        return None

    def _anchor_finding(self, target: Path, fragment: str, subject: str, where: str) -> _LinkFinding | None:
        if target not in self._anchors:
            try:
                self._anchors[target] = {item.casefold() for item in heading_anchors(target.read_text(encoding="utf-8-sig"))}
            except (OSError, UnicodeError):
                self._anchors[target] = None
        anchors = self._anchors[target]
        if anchors is None or fragment.casefold() in anchors:
            return None
        return _LinkFinding("broken-anchor", "warning", subject, f"names the anchor `#{fragment}`, which no heading of {where} gives.")


def _path_exists(path: Path) -> bool:
    try:
        return path.exists()
    except (OSError, ValueError):
        return False


def _exists_in_checkout(checkout: Path, relative: str) -> bool | None:
    """Whether `relative` exists below `checkout`, or ``None`` when the walk meets a symlink or reparse point.

    The walk only looks at directory entries: it never reads a file and never leaves the checkout.
    """

    resolution = resolve_confined(checkout, checkout, relative, percent_encoded=False)
    if resolution.kind == REPARSE:
        return None
    return resolution.ok and resolution.exists


def _source_fields(page: MarkdownPage, wiki_root: Path) -> list[tuple[str, bool, list[Any]]]:
    """The source fields a page kind carries, as `(field, path_only, entries)`.

    A feature's `sources` are paths. A persona, a general page and a business rule may hold free text
    in their source fields, so only an entry that is a `knowledge/` path (or a `repo:` link) is checked.
    """

    directory = _wiki_directory(page.path, wiki_root)
    if directory == "features":
        field_name, path_only = "sources", True
    elif directory == "business-rules":
        field_name, path_only = "source", False
    elif directory in {"personas", *GENERAL_PAGE_FOLDERS, *ROOT_PAGE_KINDS}:
        field_name, path_only = "sources", False
    else:
        return []
    value = page.frontmatter.get(field_name)
    entries = [value] if isinstance(value, str) else list(value) if isinstance(value, list) else []
    return [(field_name, path_only, entries)] if entries else []


def _read_page_text(page: MarkdownPage) -> str:
    try:
        return page.path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        return ""


def _source_line(text: str, field_name: str, entry: Any) -> int:
    """The file line of a source entry: the line that holds it below the field name, else the field's own line."""

    field_line = 0
    for number, line in enumerate(text.splitlines(), start=1):
        if line.startswith(f"{field_name}:"):
            field_line = number
        if field_line and isinstance(entry, str) and entry in line:
            return number
    return field_line or 1


def _lint_freshness(
    pages: list[MarkdownPage], wiki_root: Path, root: Path, log: tuple[Path, str], stale_after_days: int, today: date
) -> tuple[list[WikiDiagnostic], list[WikiDiagnostic]]:
    """Ask for review of a current-state page that nobody has verified lately: `(stale-page warnings, never-verified information)`.

    A page's last verification is the latest `verify` entry of `log.md` whose `paths` include it.
    `stale-page` means the last verification is older than `wiki-stale-after-days`; `never-verified`
    means there is none. Records, the log, the index and generated artifacts are exempt. Freshness never
    changes a status and never gates a lifecycle action.
    """

    verified = last_verifications(log[1])
    resolved_wiki = _resolve(wiki_root)
    stale: list[WikiDiagnostic] = []
    never: list[WikiDiagnostic] = []
    for page in pages:
        resolved = _resolve(page.path)
        try:
            relative = resolved.relative_to(resolved_wiki).as_posix()
            workspace_path = resolved.relative_to(root).as_posix()
        except ValueError:
            continue
        if not is_current_state_page(relative):
            continue
        last = verified.get(workspace_path)
        if last is None:
            never.append(
                _diag(
                    "never-verified",
                    "info",
                    page.path,
                    f"`{workspace_path}` has no `verify` entry in log.md. Once someone has checked it against its sources, record that with `prism wiki verify {workspace_path}`.",
                    gates=False,
                )
            )
            continue
        age = (today - last).days
        if age > stale_after_days:
            stale.append(
                _diag(
                    "stale-page",
                    "warning",
                    page.path,
                    f"`{workspace_path}` was last verified {last.isoformat()}, {age} days ago; `wiki-stale-after-days` is {stale_after_days}. Check it against its sources and run `prism wiki verify {workspace_path}`.",
                    gates=False,
                )
            )
    return stale, never


def _wiki_path_references(body: str, directory: str) -> list[str]:
    # A local-looking path embedded in an external URL is not a wiki
    # reference. Remove URL spans before matching plain local paths so an
    # external ``.../api-contracts/SHARED.md`` cannot become a local contract.
    body = _EXTERNAL_URL_PATTERN.sub(" ", body)
    pattern = re.compile(_WIKI_PATH_PATTERN.format(directory=re.escape(directory)), re.IGNORECASE)
    return [match.group("path") for match in pattern.finditer(body)]


def _reference_path(source_path: Path, raw_target: str, wiki_root: Path, directory: str) -> Path | None:
    """The page a link or a plain path reference names, or ``None``. Every form goes through the shared resolver."""

    normalized, _problem = decoded_link_path(raw_target)
    if normalized is None:
        return None
    root = _resolve(wiki_root)
    marker = "knowledge/wiki/"
    if marker in normalized:
        target = normalized.split(marker, 1)[1]
        if not target.startswith(f"{directory}/"):
            return None
        return resolve_to_path(root, root, target)
    if normalized.startswith("wiki/"):
        target = normalized.split("wiki/", 1)[1]
        if not target.startswith(f"{directory}/"):
            return None
        return resolve_to_path(root, root, target)
    if normalized.startswith(f"{directory}/"):
        return resolve_to_path(root, root, normalized)
    return _candidate_relative_link(source_path, normalized, root)


def _is_non_source_page(path: Path, wiki_root: Path) -> bool:
    if path.name.startswith("_") or path.name in _NON_SOURCE_FILENAMES:
        return True
    try:
        relative = _resolve(path).relative_to(_resolve(wiki_root))
    except ValueError:
        return True
    return not relative.parts or relative.parts[0] not in {
        "advisory",
        "api-contracts",
        "business-rules",
        "decisions",
        "design",
        "features",
        "personas",
        "app-requirements",
        *GENERAL_PAGE_FOLDERS,
        *ROOT_PAGE_KINDS,
    }


def _page_feature_id(
    page: MarkdownPage,
    feature_by_path: dict[Path, FeaturePage],
    requirement_by_path: dict[Path, AppRequirementPage],
) -> str | None:
    feature = feature_by_path.get(_resolve(page.path))
    if feature is not None:
        return feature.feature_id
    requirement = requirement_by_path.get(_resolve(page.path))
    if requirement is not None:
        return requirement.feature_id
    value = page.frontmatter.get("feature-id")
    if isinstance(value, str):
        return value
    return feature_id_from_path(page.path)


def _lint_auxiliary_page(page: MarkdownPage, wiki_root: Path) -> list[WikiDiagnostic]:
    if not _requires_frontmatter(page.path, wiki_root):
        return []
    feature_id = _auxiliary_feature_id(page)
    if page.parse_errors:
        return [
            _diag("malformed-page", "error", page.path, message, feature_id)
            for message in page.parse_errors
        ]

    try:
        relative = _resolve(page.path).relative_to(_resolve(wiki_root))
    except ValueError:
        return []
    directory = relative.parts[0]
    if directory in GENERAL_PAGE_FOLDERS:
        return _lint_general_page(page, GENERAL_PAGE_FOLDERS[directory])
    if directory in ROOT_PAGE_KINDS:
        return _lint_general_page(page, ROOT_PAGE_KINDS[directory])
    if directory == "api-contracts":
        return _lint_api_contract_page(page, feature_id)
    if directory == "design":
        return _lint_design_page(page, feature_id)
    if directory == "advisory":
        return _lint_advisory_review_page(page, feature_id)
    if directory == "business-rules":
        return _lint_business_rule_page(page)
    if directory == "personas":
        return _lint_persona_page(page)
    if directory == "decisions":
        return _lint_decision_page(page)
    return []


def _auxiliary_feature_id(page: MarkdownPage) -> str | None:
    for field_name in ("feature-id", "id"):
        value = page.frontmatter.get(field_name)
        if isinstance(value, str) and value.strip():
            return value
    return feature_id_from_path(page.path)


def _lint_api_contract_page(page: MarkdownPage, feature_id: str | None) -> list[WikiDiagnostic]:
    diagnostics = _lint_aux_required_string(page, "feature-id", "api-contract", feature_id)
    diagnostics.extend(_lint_aux_required_int(page, "version", "api-contract", feature_id))
    diagnostics.extend(
        _lint_aux_enum(
            page,
            "status",
            "api-contract-status",
            {"draft", "agreed", "implemented"},
            feature_id,
        )
    )
    return diagnostics


def _lint_design_page(page: MarkdownPage, feature_id: str | None) -> list[WikiDiagnostic]:
    diagnostics = _lint_aux_required_string(page, "feature-id", "design", feature_id)
    diagnostics.extend(_lint_aux_required_string(page, "title", "design", feature_id))
    diagnostics.extend(_lint_aux_required_string(page, "figma", "design", feature_id))
    if "designer" in page.frontmatter and not isinstance(page.frontmatter["designer"], str):
        diagnostics.append(_diag("invalid-design-designer", "error", page.path, "`designer` must be a string when present.", feature_id))
    return diagnostics


def _lint_advisory_review_page(page: MarkdownPage, feature_id: str | None) -> list[WikiDiagnostic]:
    diagnostics = _lint_aux_required_string(page, "feature-id", "advisory-review", feature_id)
    diagnostics.extend(_lint_aux_required_date(page, "reviewed", "advisory-review", feature_id))
    diagnostics.extend(_lint_aux_required_string_list(page, "board-members-consulted", "advisory-review", feature_id))
    return diagnostics


def _lint_business_rule_page(page: MarkdownPage) -> list[WikiDiagnostic]:
    diagnostics = _lint_aux_required_string(page, "id", "business-rule", None)
    diagnostics.extend(_lint_aux_required_string(page, "title", "business-rule", None))
    diagnostics.extend(_lint_aux_required_string(page, "source", "business-rule", None))
    return diagnostics


def _lint_persona_page(page: MarkdownPage) -> list[WikiDiagnostic]:
    diagnostics = _lint_aux_required_string(page, "id", "persona", None)
    diagnostics.extend(_lint_aux_required_string(page, "name", "persona", None))
    diagnostics.extend(_lint_aux_required_string_list(page, "sources", "persona", None))
    return diagnostics


def _lint_general_page(page: MarkdownPage, kind: str) -> list[WikiDiagnostic]:
    """Topic, research, plan, direction and roadmap pages: `kind`, then `title` and `status` where the kind has them, and `sources`."""

    diagnostics = _lint_aux_enum(page, "kind", f"{kind}-kind", {kind}, None)
    if kind in GENERAL_PAGE_STATUSES:
        diagnostics.extend(_lint_aux_required_string(page, "title", kind, None))
        diagnostics.extend(_lint_aux_enum(page, "status", f"{kind}-status", set(GENERAL_PAGE_STATUSES[kind]), None))
    diagnostics.extend(_lint_aux_required_string_list(page, "sources", kind, None))
    return diagnostics


def _lint_decision_page(page: MarkdownPage) -> list[WikiDiagnostic]:
    diagnostics = _lint_aux_required_string(page, "id", "decision", None)
    diagnostics.extend(_lint_aux_required_string(page, "title", "decision", None))
    diagnostics.extend(_lint_aux_required_date(page, "date", "decision", None))
    diagnostics.extend(
        _lint_aux_enum(
            page,
            "status",
            "decision-status",
            {"proposed", "accepted", "deprecated", "superseded"},
            None,
        )
    )
    return diagnostics


def _lint_aux_required_string(page: MarkdownPage, field_name: str, kind: str, feature_id: str | None) -> list[WikiDiagnostic]:
    if field_name not in page.frontmatter:
        return [_diag(f"missing-{kind}-frontmatter", "error", page.path, f"Required frontmatter field `{field_name}` is missing.", feature_id)]
    if not isinstance(page.frontmatter[field_name], str) or not page.frontmatter[field_name].strip():
        return [_diag(f"invalid-{kind}-{field_name}", "error", page.path, f"`{field_name}` must be a non-empty string.", feature_id)]
    return []


def _lint_aux_required_int(page: MarkdownPage, field_name: str, kind: str, feature_id: str | None) -> list[WikiDiagnostic]:
    if field_name not in page.frontmatter:
        return [_diag(f"missing-{kind}-frontmatter", "error", page.path, f"Required frontmatter field `{field_name}` is missing.", feature_id)]
    value = page.frontmatter[field_name]
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        return [_diag(f"invalid-{kind}-{field_name}", "error", page.path, f"`{field_name}` must be an integer.", feature_id)]
    return []


def _lint_aux_required_date(page: MarkdownPage, field_name: str, kind: str, feature_id: str | None) -> list[WikiDiagnostic]:
    if field_name not in page.frontmatter:
        return [_diag(f"missing-{kind}-frontmatter", "error", page.path, f"Required frontmatter field `{field_name}` is missing.", feature_id)]
    if parse_iso_date(page.frontmatter[field_name]) is None:
        return [_diag(f"invalid-{kind}-{field_name}", "error", page.path, f"`{field_name}` must be an ISO date (YYYY-MM-DD).", feature_id)]
    return []


def _lint_aux_required_string_list(page: MarkdownPage, field_name: str, kind: str, feature_id: str | None) -> list[WikiDiagnostic]:
    if field_name not in page.frontmatter:
        return [_diag(f"missing-{kind}-frontmatter", "error", page.path, f"Required frontmatter field `{field_name}` is missing.", feature_id)]
    value = page.frontmatter[field_name]
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        return [_diag(f"invalid-{kind}-{field_name}", "error", page.path, f"`{field_name}` must be a list of strings.", feature_id)]
    return []


def _lint_aux_enum(
    page: MarkdownPage,
    field_name: str,
    code: str,
    allowed: set[str],
    feature_id: str | None,
) -> list[WikiDiagnostic]:
    if field_name not in page.frontmatter:
        return [_diag(f"missing-{code}", "error", page.path, f"Required frontmatter field `{field_name}` is missing.", feature_id)]
    value = page.frontmatter[field_name]
    valid = isinstance(value, str) and value in allowed
    if not valid:
        return [_diag(f"invalid-{code}", "error", page.path, f"`{field_name}` has an unsupported value.", feature_id)]
    return []


def _requires_frontmatter(path: Path, wiki_root: Path) -> bool:
    try:
        relative = _resolve(path).relative_to(_resolve(wiki_root))
    except ValueError:
        return False
    if len(relative.parts) == 1:
        return relative.parts[0] in ROOT_PAGE_KINDS
    directory = relative.parts[0]
    if directory in _FRONTMATTER_PAGE_DIRECTORIES:
        return True
    return directory == "advisory" and relative.name.startswith("F-") and relative.name.endswith("-review.md")


def _lint_feature(feature: FeaturePage, model: WorkspaceModel) -> list[WikiDiagnostic]:
    diagnostics: list[WikiDiagnostic] = []
    path = feature.page.path
    feature_id = feature.feature_id
    for message in feature.page.parse_errors:
        diagnostics.append(_diag("malformed-frontmatter", "error", path, message, feature_id))

    frontmatter = feature.page.frontmatter
    required_fields = ("id", "title", "status", "owner", "apps", "sources", "advisory-review")
    for field_name in required_fields:
        if field_name not in frontmatter:
            diagnostics.append(_diag("missing-feature-frontmatter", "error", path, f"Required frontmatter field `{field_name}` is missing.", feature_id))

    if "id" in frontmatter:
        value = frontmatter["id"]
        if not isinstance(value, str) or not re.fullmatch(r"F-\d+", value.strip()):
            diagnostics.append(_diag("invalid-feature-id", "error", path, "`id` must be a feature ID such as `F-001`.", feature_id))
    if "title" in frontmatter and (not isinstance(frontmatter["title"], str) or not frontmatter["title"].strip()):
        diagnostics.append(_diag("invalid-feature-title", "error", path, "`title` must be a non-empty string.", feature_id))

    status_value = frontmatter.get("status")
    if "status" in frontmatter and (not isinstance(status_value, str) or status_value not in VALID_FEATURE_STATUSES):
        diagnostics.append(_diag("invalid-feature-status", "error", path, f"`status` must be one of {sorted(VALID_FEATURE_STATUSES)}.", feature_id))
    owner_value = frontmatter.get("owner")
    if "owner" in frontmatter and (not isinstance(owner_value, str) or owner_value not in VALID_FEATURE_OWNERS):
        diagnostics.append(_diag("invalid-feature-owner", "error", path, f"`owner` must be one of {sorted(VALID_FEATURE_OWNERS)}.", feature_id))
    advisory_value = frontmatter.get("advisory-review")
    if "advisory-review" in frontmatter and (
        not isinstance(advisory_value, str) or advisory_value not in VALID_ADVISORY_REVIEW_STATES
    ):
        diagnostics.append(
            _diag("invalid-advisory-review", "error", path, f"`advisory-review` must be one of {sorted(VALID_ADVISORY_REVIEW_STATES)}.", feature_id)
        )
    if feature.status in EXPECTED_OWNER_BY_STATUS and feature.owner != EXPECTED_OWNER_BY_STATUS[feature.status]:
        diagnostics.append(
            _diag(
                "invalid-status-owner-pairing",
                "error",
                path,
                f"`status: {feature.status}` must pair with `owner: {EXPECTED_OWNER_BY_STATUS[feature.status]}`.",
                feature_id,
            )
        )
    if feature.advisory_review == "skipped" and not isinstance(frontmatter.get("advisory-skip-reason"), str):
        diagnostics.append(
            _diag(
                "missing-advisory-skip-reason",
                "error",
                path,
                "`advisory-review: skipped` requires `advisory-skip-reason` frontmatter.",
                feature_id,
            )
        )

    _revalidation, revalidation_errors = parse_revalidation(frontmatter.get("revalidation"))
    for message in revalidation_errors:
        diagnostics.append(_diag("invalid-revalidation", "error", path, message, feature_id))
    if feature.status == "done" and _revalidation:
        diagnostics.append(
            _diag(
                "pending-revalidation",
                "error",
                path,
                "A Done feature cannot retain pending revalidation domains: " + ", ".join(_revalidation) + ".",
                feature_id,
            )
        )

    if feature.status == "done":
        _delivery_evidence, delivery_problems = parse_delivery_evidence(feature.page.body, feature.apps)
        for problem in delivery_problems:
            code = RELEASE_EVIDENCE_REQUIRED if problem.code == RELEASE_EVIDENCE_REQUIRED else "done-delivery-evidence"
            diagnostics.append(_diag(code, "error", path, problem.message, feature_id))

    if "platforms" in frontmatter:
        diagnostics.append(
            _diag("unknown-feature-field", "error", path, "`platforms` is not a valid feature field; list the feature's apps in `apps:`.", feature_id)
        )
    apps_value = frontmatter.get("apps")
    if "apps" in frontmatter and not isinstance(apps_value, list):
        diagnostics.append(_diag("invalid-feature-apps", "error", path, "`apps` must be a list.", feature_id))
    elif isinstance(apps_value, list):
        for app_value in apps_value:
            if not isinstance(app_value, str):
                diagnostics.append(
                    _diag("invalid-feature-apps", "error", path, "Every `apps` entry must be a string.", feature_id)
                )
                continue
            if model.app(app_value) is None:
                diagnostics.append(_diag("unknown-app-id", "error", path, _unknown_app_message(app_value, model), feature_id))

    if feature.status in VALID_FEATURE_STATUSES and feature.status != "done":
        retired = model.retired_apps(feature.apps)
        if retired:
            diagnostics.append(_diag("app-retired-in-scope", "error", path, retired_in_scope_message(feature_id, retired), feature_id))
        if api_surface_declared(section_text(feature.page.body, "API surface")) and not model.scope_serves_api(feature.apps):
            diagnostics.append(
                _diag("api-surface-without-api-app", "error", path, api_surface_without_api_app_message(model, feature_id, feature.apps), feature_id)
            )

    sources_value = frontmatter.get("sources")
    if "sources" in frontmatter and (
        not isinstance(sources_value, list) or any(not isinstance(source, str) for source in sources_value)
    ):
        diagnostics.append(_diag("invalid-feature-sources", "error", path, "`sources` must be a list of strings.", feature_id))

    open_questions, open_question_errors = parse_open_question_rows(feature.page.body)
    for message in open_question_errors:
        diagnostics.append(_diag("malformed-open-questions", "error", path, message, feature_id))
    for row in open_questions:
        owner = row["owner"]
        status = row["status"]
        if owner not in VALID_OPEN_QUESTION_OWNERS:
            diagnostics.append(_diag("invalid-open-question-owner", "error", path, f"Open question owner `{owner}` is invalid.", feature_id))
        if status != "open" and not status.startswith("resolved:"):
            diagnostics.append(_diag("invalid-open-question-status", "error", path, f"Open question status `{status}` is invalid.", feature_id))

    return diagnostics


def _unknown_app_message(app_id: str, model: WorkspaceModel) -> str:
    declared = ", ".join(f"`{app.id}`" for app in model.apps) or "none"
    return f"`{app_id}` is not an app of this workspace; the workspace's apps are {declared}."


def _lint_unknown_app_capabilities(model: WorkspaceModel, manifest_path: Path) -> list[WikiDiagnostic]:
    """One information-level finding per app and capability that resolves to ``unknown``.

    Lifecycle gates treat ``unknown`` as true, the stricter side.
    """

    return [
        _diag(
            "app-capability-unknown",
            "info",
            manifest_path,
            f"App `{app.id}` has capability `{name}` unknown; lifecycle gates treat it as true until the manifest declares true or false.",
        )
        for app in model.apps
        for name in CAPABILITIES
        if app.capability(name) == UNKNOWN
    ]


def _lint_app_requirement(requirement: AppRequirementPage, model: WorkspaceModel) -> list[WikiDiagnostic]:
    diagnostics: list[WikiDiagnostic] = []
    path = requirement.page.path
    feature_id = requirement.feature_id
    for message in requirement.page.parse_errors:
        diagnostics.append(_diag("malformed-frontmatter", "error", path, message, feature_id))
    frontmatter = requirement.page.frontmatter
    for field_name in ("feature-id", "app", "status"):
        if field_name not in frontmatter:
            diagnostics.append(_diag("missing-app-requirement-frontmatter", "error", path, f"Required frontmatter field `{field_name}` is missing.", feature_id))
    if "feature-id" in frontmatter and (not isinstance(frontmatter["feature-id"], str) or not frontmatter["feature-id"].strip()):
        diagnostics.append(_diag("invalid-app-requirement-feature-id", "error", path, "`feature-id` must be a non-empty feature ID.", feature_id))
    if "platform" in frontmatter:
        diagnostics.append(
            _diag("unknown-requirement-field", "error", path, "`platform` is not a valid requirement field; name the app in `app:`.", feature_id)
        )
    if "app" in frontmatter and (not isinstance(frontmatter["app"], str) or model.app(frontmatter["app"]) is None):
        diagnostics.append(_diag("unknown-app-id", "error", path, _unknown_app_message(str(frontmatter["app"]), model), feature_id))
    if "status" in frontmatter and (
        not isinstance(frontmatter["status"], str) or frontmatter["status"] not in VALID_APP_REQUIREMENT_STATUSES
    ):
        diagnostics.append(
            _diag("invalid-app-requirement-status", "error", path, f"`status` must be one of {sorted(VALID_APP_REQUIREMENT_STATUSES)}.", feature_id)
        )
    return diagnostics


def _diag(code: str, severity: str, path: Path, message: str, feature_id: str | None = None, *, gates: bool = True) -> WikiDiagnostic:
    return WikiDiagnostic(code=code, severity=severity, path=str(path), message=message, feature_id=feature_id, gates=gates)


def _diagnostic_order(diagnostic: WikiDiagnostic) -> tuple[str, str, str, str]:
    return (diagnostic.path, diagnostic.code, diagnostic.feature_id or "", diagnostic.message)
