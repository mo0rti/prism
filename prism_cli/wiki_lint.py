"""Deterministic linting for Prism generated-project wiki state."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from prism_cli.wiki_model import (
    VALID_ADVISORY_REVIEW_STATES,
    VALID_FEATURE_OWNERS,
    VALID_FEATURE_STATUSES,
    VALID_OPEN_QUESTION_OWNERS,
    VALID_PLATFORM_IDS,
    VALID_PLATFORM_REQUIREMENT_STATUSES,
    FeaturePage,
    parse_index_feature_rows,
    parse_open_question_rows,
    read_feature_pages,
    read_platform_requirement_pages,
)


READY_FOR_IMPLEMENTATION_STATUSES = {"ready-for-dev", "in-dev", "done"}
WIKI_BLOCKER_CODES = {"pending-board-review", "missing-platform-requirements"}
EXPECTED_OWNER_BY_STATUS = {
    "raw": "po",
    "specified": "po",
    "ready-for-design": "designer",
    "in-design": "designer",
    "ready-for-dev": "dev",
    "in-dev": "dev",
    "done": "none",
}


@dataclass(frozen=True)
class WikiDiagnostic:
    code: str
    severity: str
    path: str
    message: str
    feature_id: str | None = None

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

    def to_dict(self) -> dict[str, Any]:
        confidence = "error" if self.error_count else "degraded" if self.warning_count else "high"
        return {
            "schema_version": 1,
            "experimental": True,
            "command": "wiki lint",
            "confidence": confidence,
            "root": str(self.root),
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


def lint_wiki(workspace_root: Path) -> WikiLintResult:
    root = workspace_root.expanduser().resolve()
    wiki_root = root / "knowledge" / "wiki"
    diagnostics: list[WikiDiagnostic] = []

    if not wiki_root.exists():
        diagnostics.append(_diag("missing-wiki-root", "error", wiki_root, "Missing knowledge/wiki directory."))
        return WikiLintResult(root=root, diagnostics=diagnostics)

    for required in ("SCHEMA.md", "index.md", "SETTINGS.md"):
        required_path = wiki_root / required
        if not required_path.exists():
            diagnostics.append(_diag("missing-required-wiki-file", "error", required_path, f"Missing required wiki file: {required}."))

    feature_pages = read_feature_pages(wiki_root)
    requirement_pages = read_platform_requirement_pages(wiki_root)
    requirements_by_feature_platform = {
        (page.feature_id, page.platform): page
        for page in requirement_pages
        if page.feature_id and page.platform
    }

    for requirement in requirement_pages:
        diagnostics.extend(_lint_platform_requirement(requirement))

    features_by_id: dict[str, FeaturePage] = {}
    for feature in feature_pages:
        diagnostics.extend(_lint_feature(feature))
        feature_id = feature.feature_id
        if feature_id in features_by_id:
            diagnostics.append(
                _diag("duplicate-feature-id", "error", feature.page.path, f"Duplicate feature id `{feature_id}`.", feature_id)
            )
        features_by_id[feature_id] = feature

        if feature.status in READY_FOR_IMPLEMENTATION_STATUSES:
            if feature.advisory_review == "pending":
                diagnostics.append(
                    _diag(
                        "pending-board-review",
                        "error",
                        feature.page.path,
                        f"Feature `{feature_id}` is {feature.status} but advisory-review is still pending.",
                        feature_id,
                    )
                )
            for platform_id in feature.platforms:
                if platform_id in VALID_PLATFORM_IDS and (feature_id, platform_id) not in requirements_by_feature_platform:
                    diagnostics.append(
                        _diag(
                            "missing-platform-requirements",
                            "error",
                            feature.page.path,
                            f"Feature `{feature_id}` is {feature.status} but no platform requirement exists for `{platform_id}`.",
                            feature_id,
                        )
                    )

    index_path = wiki_root / "index.md"
    if index_path.exists():
        index_rows, index_errors = parse_index_feature_rows(index_path)
        for message in index_errors:
            diagnostics.append(_diag("malformed-index", "error", index_path, message))
        if not index_errors:
            index_feature_ids = {row.feature_id for row in index_rows}
            for feature_id, feature in features_by_id.items():
                if feature_id not in index_feature_ids:
                    diagnostics.append(
                        _diag(
                            "feature-missing-from-index",
                            "error",
                            index_path,
                            f"Feature `{feature_id}` has a feature page but no row in index.md.",
                            feature_id,
                        )
                    )
        for row in index_rows:
            feature = features_by_id.get(row.feature_id)
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

    return WikiLintResult(root=root, diagnostics=diagnostics, feature_count=len(feature_pages))


def _lint_feature(feature: FeaturePage) -> list[WikiDiagnostic]:
    diagnostics: list[WikiDiagnostic] = []
    path = feature.page.path
    feature_id = feature.feature_id
    for message in feature.page.parse_errors:
        diagnostics.append(_diag("malformed-frontmatter", "error", path, message, feature_id))

    required_fields = ("id", "title", "status", "owner", "introduced", "last-updated", "platforms", "sources", "advisory-review")
    for field_name in required_fields:
        if field_name not in feature.page.frontmatter:
            diagnostics.append(_diag("missing-feature-frontmatter", "error", path, f"Required frontmatter field `{field_name}` is missing.", feature_id))

    if feature.status and feature.status not in VALID_FEATURE_STATUSES:
        diagnostics.append(_diag("invalid-feature-status", "error", path, f"`status` must be one of {sorted(VALID_FEATURE_STATUSES)}.", feature_id))
    if feature.owner and feature.owner not in VALID_FEATURE_OWNERS:
        diagnostics.append(_diag("invalid-feature-owner", "error", path, f"`owner` must be one of {sorted(VALID_FEATURE_OWNERS)}.", feature_id))
    if feature.advisory_review and feature.advisory_review not in VALID_ADVISORY_REVIEW_STATES:
        diagnostics.append(
            _diag("invalid-advisory-review", "error", path, f"`advisory-review` must be one of {sorted(VALID_ADVISORY_REVIEW_STATES)}.", feature_id)
        )
    if feature.status in EXPECTED_OWNER_BY_STATUS and feature.owner and feature.owner != EXPECTED_OWNER_BY_STATUS[feature.status]:
        diagnostics.append(
            _diag(
                "invalid-status-owner-pairing",
                "error",
                path,
                f"`status: {feature.status}` must pair with `owner: {EXPECTED_OWNER_BY_STATUS[feature.status]}`.",
                feature_id,
            )
        )
    if feature.advisory_review == "skipped" and not feature.page.frontmatter.get("advisory-skip-reason"):
        diagnostics.append(
            _diag(
                "missing-advisory-skip-reason",
                "error",
                path,
                "`advisory-review: skipped` requires `advisory-skip-reason` frontmatter.",
                feature_id,
            )
        )

    platforms_value = feature.page.frontmatter.get("platforms")
    if "platforms" in feature.page.frontmatter and not isinstance(platforms_value, list):
        diagnostics.append(_diag("invalid-feature-platforms", "error", path, "`platforms` must be a list.", feature_id))
    for platform_id in feature.platforms:
        if platform_id not in VALID_PLATFORM_IDS:
            diagnostics.append(_diag("invalid-platform-id", "error", path, f"`{platform_id}` is not a valid Prism platform id.", feature_id))

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


def _lint_platform_requirement(requirement: Any) -> list[WikiDiagnostic]:
    diagnostics: list[WikiDiagnostic] = []
    path = requirement.page.path
    feature_id = requirement.feature_id
    for message in requirement.page.parse_errors:
        diagnostics.append(_diag("malformed-frontmatter", "error", path, message, feature_id))
    for field_name in ("feature-id", "platform", "status"):
        if field_name not in requirement.page.frontmatter:
            diagnostics.append(_diag("missing-platform-requirement-frontmatter", "error", path, f"Required frontmatter field `{field_name}` is missing.", feature_id))
    if requirement.platform and requirement.platform not in VALID_PLATFORM_IDS:
        diagnostics.append(_diag("invalid-platform-id", "error", path, f"`{requirement.platform}` is not a valid Prism platform id.", feature_id))
    if requirement.status and requirement.status not in VALID_PLATFORM_REQUIREMENT_STATUSES:
        diagnostics.append(
            _diag("invalid-platform-requirement-status", "error", path, f"`status` must be one of {sorted(VALID_PLATFORM_REQUIREMENT_STATUSES)}.", feature_id)
        )
    return diagnostics


def _diag(code: str, severity: str, path: Path, message: str, feature_id: str | None = None) -> WikiDiagnostic:
    return WikiDiagnostic(code=code, severity=severity, path=str(path), message=message, feature_id=feature_id)
