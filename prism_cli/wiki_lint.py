"""Deterministic linting for Prism generated-project wiki state."""

from __future__ import annotations

import re
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import date
from functools import cached_property
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from prism_cli.app_model import (
    CAPABILITIES,
    CAPABILITY_HAS_UI,
    UNKNOWN,
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
    extract_markdown_links,
    candidate_relative_markdown_link as _candidate_relative_link,
    normalize_feature_id,
    feature_id_from_path,
    page_date_field,
    parse_index_feature_rows,
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
from prism_cli.workspace import MANIFEST_FILE, detect_workspace_kind, inspect_workspace, workspace_model


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
}
_FRONTMATTER_PAGE_DIRECTORIES = {
    "api-contracts",
    "business-rules",
    "decisions",
    "design",
    "personas",
}


@dataclass(frozen=True)
class WikiDiagnostic:
    code: str
    severity: str
    path: str
    message: str
    feature_id: str | None = None

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
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
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

    # SETTINGS.md is optional by contract. SCHEMA.md, LIFECYCLE.md and index.md
    # remain the structural files that lint requires before it can reason about the board.
    for required in ("SCHEMA.md", "LIFECYCLE.md", "index.md"):
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

    stale_after_days, settings_diagnostics = _read_stale_after_days(wiki_root)
    diagnostics.extend(settings_diagnostics)

    model = workspace_model(root, resolved=True)
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
    diagnostics.extend(_lint_stale_pages(all_pages, wiki_root, stale_after_days, today or date.today()))
    diagnostics.extend(
        _lint_relative_links(
            all_pages,
            wiki_root,
            feature_pages,
            requirement_pages,
        )
    )

    index_path = wiki_root / "index.md"
    if index_path.exists():
        index_rows, index_errors = parse_index_feature_rows(index_path)
        for message in index_errors:
            diagnostics.append(_diag("malformed-index", "error", index_path, message))
        if not index_errors:
            index_feature_ids = {normalize_feature_id(row.feature_id) for row in index_rows}
            for feature_id, feature in features_by_id.items():
                if feature_id not in index_feature_ids:
                    diagnostics.append(
                        _diag(
                            "feature-missing-from-index",
                            "error",
                            index_path,
                            f"Feature `{feature.feature_id}` has a feature page but no row in index.md.",
                            feature.feature_id,
                        )
                    )
        for row in index_rows:
            feature = features_by_id.get(normalize_feature_id(row.feature_id))
            if feature is None:
                diagnostics.append(
                    _diag(
                        "index-missing-feature",
                        "error",
                        index_path,
                        f"index.md references `{row.feature_id}` but no matching feature page exists.",
                        row.feature_id,
                    )
                )
                continue
            if feature.status and row.status != feature.status:
                diagnostics.append(
                    _diag(
                        "index-frontmatter-drift",
                        "error",
                        index_path,
                        f"index.md status for `{row.feature_id}` is `{row.status}` but feature frontmatter says `{feature.status}`.",
                        row.feature_id,
                    )
                )
            if feature.owner and row.owner != feature.owner:
                diagnostics.append(
                    _diag(
                        "index-frontmatter-drift",
                        "error",
                        index_path,
                        f"index.md owner for `{row.feature_id}` is `{row.owner}` but feature frontmatter says `{feature.owner}`.",
                        row.feature_id,
                    )
                )
            if feature.advisory_review and row.advisory_review != feature.advisory_review:
                diagnostics.append(
                    _diag(
                        "index-frontmatter-drift",
                        "error",
                        index_path,
                        f"index.md board review for `{row.feature_id}` is `{row.advisory_review}` but feature frontmatter says `{feature.advisory_review}`.",
                        row.feature_id,
                    )
                )

    diagnostics.sort(key=lambda diagnostic: (diagnostic.path, diagnostic.code, diagnostic.feature_id or "", diagnostic.message))
    return WikiLintResult(root=root, diagnostics=diagnostics, feature_count=len(feature_pages))


def _read_stale_after_days(wiki_root: Path) -> tuple[int, list[WikiDiagnostic]]:
    settings = read_wiki_settings(wiki_root)
    diagnostics = [
        _diag(code, "warning", settings.path, message)
        for code, message in settings.diagnostics
    ]
    return settings.stale_after_days, diagnostics


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


def _lint_stale_pages(
    pages: list[MarkdownPage],
    wiki_root: Path,
    stale_after_days: int,
    today: date,
) -> list[WikiDiagnostic]:
    diagnostics: list[WikiDiagnostic] = []
    for page in pages:
        if _is_non_source_page(page.path, wiki_root):
            continue
        field = page_date_field(page)
        if field is None:
            continue
        field_name, raw_value = field
        parsed = parse_iso_date(raw_value)
        if parsed is None:
            if page.path.parent.name == "features":
                # Feature date fields have a more specific diagnostic in
                # _lint_feature; do not emit a duplicate generic warning.
                continue
            diagnostics.append(
                _diag(
                    "invalid-wiki-date",
                    "error",
                    page.path,
                    f"`{field_name}` must be an ISO date (YYYY-MM-DD) for staleness checks.",
                    feature_id_from_path(page.path),
                )
            )
            continue
        age_days = (today - parsed).days
        if age_days > stale_after_days:
            diagnostics.append(
                _diag(
                    "stale-page",
                    "warning",
                    page.path,
                    f"Page is {age_days} days old (wiki-stale-after-days: {stale_after_days}).",
                    feature_id_from_path(page.path),
                )
            )
    return diagnostics


def _lint_relative_links(
    pages: list[MarkdownPage],
    wiki_root: Path,
    feature_pages: list[FeaturePage],
    requirement_pages: list[AppRequirementPage],
) -> list[WikiDiagnostic]:
    wiki_root = _resolve(wiki_root)
    feature_by_path = {_resolve(feature.page.path): feature for feature in feature_pages}
    requirement_by_path = {_resolve(requirement.page.path): requirement for requirement in requirement_pages}
    diagnostics: list[WikiDiagnostic] = []
    for page in pages:
        if _is_non_source_page(page.path, wiki_root):
            continue
        feature_id = _page_feature_id(page, feature_by_path, requirement_by_path)
        for raw_target in sorted(set(extract_markdown_links(page.body))):
            candidate = _candidate_relative_link(page.path, raw_target)
            if candidate is None:
                continue
            try:
                candidate.relative_to(wiki_root)
            except ValueError:
                # The wiki contract covers links between wiki pages. Source
                # references may intentionally point to intake, repository,
                # or other files outside knowledge/wiki.
                continue
            try:
                exists = candidate.is_file()
            except (OSError, ValueError):
                exists = False
            if not exists:
                diagnostics.append(
                    _diag(
                        "broken-wiki-link",
                        "error",
                        page.path,
                        f"Relative markdown link `{raw_target}` does not resolve to an existing wiki page.",
                        feature_id,
                    )
                )
    return diagnostics


def _wiki_path_references(body: str, directory: str) -> list[str]:
    # A local-looking path embedded in an external URL is not a wiki
    # reference. Remove URL spans before matching plain local paths so an
    # external ``.../api-contracts/SHARED.md`` cannot become a local contract.
    body = _EXTERNAL_URL_PATTERN.sub(" ", body)
    pattern = re.compile(_WIKI_PATH_PATTERN.format(directory=re.escape(directory)), re.IGNORECASE)
    return [match.group("path") for match in pattern.finditer(body)]


def _reference_path(source_path: Path, raw_target: str, wiki_root: Path, directory: str) -> Path | None:
    normalized = unquote(raw_target).replace("\\", "/")
    marker = "knowledge/wiki/"
    if marker in normalized:
        target = normalized.split(marker, 1)[1]
        if not target.startswith(f"{directory}/"):
            return None
        return _resolve(wiki_root / target)
    if normalized.startswith("wiki/"):
        target = normalized.split("wiki/", 1)[1]
        if not target.startswith(f"{directory}/"):
            return None
        return _resolve(wiki_root / target)
    if normalized.startswith(f"{directory}/"):
        return _resolve(wiki_root / normalized)
    return _candidate_relative_link(source_path, normalized)


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
        "index.md",
        "personas",
        "app-requirements",
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
    diagnostics.extend(_lint_aux_required_date(page, "date", "design", feature_id))
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
    diagnostics.extend(_lint_aux_required_date(page, "introduced", "business-rule", None))
    diagnostics.extend(_lint_aux_required_string(page, "source", "business-rule", None))
    return diagnostics


def _lint_persona_page(page: MarkdownPage) -> list[WikiDiagnostic]:
    diagnostics = _lint_aux_required_string(page, "id", "persona", None)
    diagnostics.extend(_lint_aux_required_string(page, "name", "persona", None))
    diagnostics.extend(_lint_aux_required_date(page, "introduced", "persona", None))
    diagnostics.extend(_lint_aux_required_string_list(page, "sources", "persona", None))
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
            {"proposed", "accepted", "deprecated"},
            None,
            allow_superseded=True,
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
    *,
    allow_superseded: bool = False,
) -> list[WikiDiagnostic]:
    if field_name not in page.frontmatter:
        return [_diag(f"missing-{code}", "error", page.path, f"Required frontmatter field `{field_name}` is missing.", feature_id)]
    value = page.frontmatter[field_name]
    valid = isinstance(value, str) and value in allowed
    if allow_superseded:
        valid = valid or (isinstance(value, str) and re.fullmatch(r"superseded-by\s+ADR-\d+", value) is not None)
    if not valid:
        return [_diag(f"invalid-{code}", "error", page.path, f"`{field_name}` has an unsupported value.", feature_id)]
    return []


def _requires_frontmatter(path: Path, wiki_root: Path) -> bool:
    try:
        relative = _resolve(path).relative_to(_resolve(wiki_root))
    except ValueError:
        return False
    if len(relative.parts) < 2:
        return False
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
    required_fields = ("id", "title", "status", "owner", "introduced", "last-updated", "apps", "sources", "advisory-review")
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

    for field_name in ("introduced", "last-updated"):
        if field_name in frontmatter and parse_iso_date(frontmatter[field_name]) is None:
            diagnostics.append(
                _diag(
                    "invalid-feature-date",
                    "error",
                    path,
                    f"`{field_name}` must be an ISO date (YYYY-MM-DD).",
                    feature_id,
                )
            )

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


def _diag(code: str, severity: str, path: Path, message: str, feature_id: str | None = None) -> WikiDiagnostic:
    return WikiDiagnostic(code=code, severity=severity, path=str(path), message=message, feature_id=feature_id)
