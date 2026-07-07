"""Workspace status aggregation for generated Prism projects."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from prism_cli import __version__
from prism_cli.wiki_lint import WIKI_BLOCKER_CODES, WikiDiagnostic, WikiLintResult, lint_wiki
from prism_cli.wiki_model import (
    VALID_FEATURE_STATUSES,
    VALID_PLATFORM_IDS,
    parse_open_question_rows,
    read_feature_pages,
    read_platform_requirement_pages,
)
from prism_cli.workspace import MANIFEST_FILE, WorkspaceDiagnostic, WorkspaceLoadResult, detect_workspace_kind, load_workspace


COPIER_ANSWERS_FILE = ".copier-answers.yml"
IGNORED_INTAKE_FILES = {"PO_BRIEF_TEMPLATE.md", "DESIGN_HANDOFF_TEMPLATE.md", ".gitkeep", ".DS_Store", "desktop.ini", "Thumbs.db"}
PLATFORM_DIRS = {
    "backend": "backend",
    "mobile-android": "mobile-android",
    "mobile-ios": "mobile-ios",
    "web-user-app": "web-user-app",
    "web-admin-portal": "web-admin-portal",
}
@dataclass(frozen=True)
class StatusDiagnostic:
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


@dataclass(frozen=True)
class IntakeCounts:
    pending: int = 0
    quarantined: int = 0

    def to_dict(self) -> dict[str, int]:
        return {"pending": self.pending, "quarantined": self.quarantined}


@dataclass(frozen=True)
class WorkspaceStatus:
    root: Path
    workspace_kind: str
    project_name: str | None
    platforms: list[str]
    setup_state: str
    confidence: str
    manifest_present: bool
    manifest_diagnostics: list[WorkspaceDiagnostic]
    status_diagnostics: list[StatusDiagnostic]
    wiki_lint: WikiLintResult
    intake: IntakeCounts
    feature_status_counts: dict[str, int] = field(default_factory=dict)
    feature_owner_counts: dict[str, int] = field(default_factory=dict)
    open_questions_by_owner: dict[str, int] = field(default_factory=dict)
    platform_requirement_status_counts: dict[str, int] = field(default_factory=dict)
    platform_maturity: dict[str, dict[str, str]] = field(default_factory=dict)

    @property
    def blocker_count(self) -> int:
        return sum(1 for diagnostic in self.wiki_lint.diagnostics if diagnostic.code in WIKI_BLOCKER_CODES)

    @property
    def issue_count(self) -> int:
        return (
            len(self.manifest_diagnostics)
            + len(self.status_diagnostics)
            + self.wiki_lint.error_count
            + self.wiki_lint.warning_count
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "experimental": True,
            "command": "status",
            "root": str(self.root),
            "confidence": self.confidence,
            "workspace": {
                "kind": self.workspace_kind,
                "project_name": self.project_name,
                "platforms": self.platforms,
                "platform_maturity": dict(self.platform_maturity),
                "setup_state": self.setup_state,
            },
            "manifest": {
                "present": self.manifest_present,
                "file": str(self.root / MANIFEST_FILE),
                "diagnostics": [diagnostic.to_dict() for diagnostic in self.manifest_diagnostics],
            },
            "facts": {
                "intake": self.intake.to_dict(),
                "wiki": {
                    "feature_count": self.wiki_lint.feature_count,
                    "feature_status_counts": dict(self.feature_status_counts),
                    "feature_owner_counts": dict(self.feature_owner_counts),
                    "open_questions_by_owner": dict(self.open_questions_by_owner),
                    "platform_requirement_status_counts": dict(self.platform_requirement_status_counts),
                    "blocker_count": self.blocker_count,
                    "error_count": self.wiki_lint.error_count,
                    "warning_count": self.wiki_lint.warning_count,
                    "clean": self.wiki_lint.is_clean,
                },
            },
            "blocker_facts": self.blocker_facts(),
            "required_obligations": self.required_obligations(),
            "sources": self.sources(),
            "diagnostics": _diagnostics_to_dicts(
                self.manifest_diagnostics,
                self.status_diagnostics,
                self.wiki_lint.diagnostics,
                self.root,
            ),
        }

    def blocker_facts(self) -> list[dict[str, Any]]:
        return [
            diagnostic.to_dict()
            for diagnostic in self.wiki_lint.diagnostics
            if diagnostic.code in WIKI_BLOCKER_CODES
        ]

    def required_obligations(self) -> list[dict[str, Any]]:
        obligations: list[dict[str, Any]] = []
        if self.intake.quarantined:
            obligations.append({"code": "resolve-quarantined-intake", "count": self.intake.quarantined})
        if self.intake.pending:
            obligations.append({"code": "process-pending-intake", "count": self.intake.pending})
        obligations.extend({"code": diagnostic["code"], "path": diagnostic["path"]} for diagnostic in self.blocker_facts())
        return obligations

    def sources(self) -> list[str]:
        paths = [str(self.root / MANIFEST_FILE), str(self.root / "knowledge" / "wiki"), str(self.root / "knowledge" / "intake")]
        return paths


def build_status(root: Path) -> WorkspaceStatus:
    workspace_root = root.expanduser().resolve()
    workspace_result = load_workspace(workspace_root)
    answers = _load_copier_answers(workspace_root)
    wiki_lint = lint_wiki(workspace_root)
    status_diagnostics = _workspace_diagnostics(workspace_result, answers)

    project_name = _project_name(workspace_result, answers)
    platforms = _platforms(workspace_result, answers, workspace_root)
    setup_state = _setup_state(workspace_root, wiki_lint)
    intake = _intake_counts(workspace_root)
    feature_counts, owner_counts, open_question_counts, requirement_counts = _wiki_counts(workspace_root)
    confidence = _confidence(workspace_result, status_diagnostics, wiki_lint)

    return WorkspaceStatus(
        root=workspace_root,
        workspace_kind=detect_workspace_kind(workspace_root),
        project_name=project_name,
        platforms=platforms,
        setup_state=setup_state,
        confidence=confidence,
        manifest_present=workspace_result.manifest is not None,
        manifest_diagnostics=workspace_result.diagnostics,
        status_diagnostics=status_diagnostics,
        wiki_lint=wiki_lint,
        intake=intake,
        feature_status_counts=feature_counts,
        feature_owner_counts=owner_counts,
        open_questions_by_owner=open_question_counts,
        platform_requirement_status_counts=requirement_counts,
        platform_maturity=workspace_result.manifest.platform_maturity if workspace_result.manifest else {},
    )


def _load_copier_answers(root: Path) -> dict[str, Any]:
    path = root / COPIER_ANSWERS_FILE
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def _workspace_diagnostics(workspace_result: WorkspaceLoadResult, answers: dict[str, Any]) -> list[StatusDiagnostic]:
    root = workspace_result.root
    diagnostics: list[StatusDiagnostic] = []
    manifest = workspace_result.manifest

    if manifest is None:
        return diagnostics

    answers_name = answers.get("project_name")
    if isinstance(answers_name, str) and manifest.project_name and answers_name != manifest.project_name:
        diagnostics.append(
            StatusDiagnostic(
                code="manifest-answers-drift",
                severity="error",
                path=str(manifest.path),
                message=f"Manifest project name `{manifest.project_name}` differs from Copier answers `{answers_name}`.",
            )
        )

    answer_platforms = _list_value(answers.get("platforms"))
    if answer_platforms and sorted(answer_platforms) != sorted(manifest.platforms):
        diagnostics.append(
            StatusDiagnostic(
                code="manifest-answers-drift",
                severity="error",
                path=str(manifest.path),
                message="Manifest platforms differ from Copier answers.",
            )
        )

    filesystem_platforms = _detect_platform_dirs(root)
    manifest_platforms = set(manifest.platforms)
    extra_dirs = sorted(set(filesystem_platforms) - manifest_platforms)
    missing_dirs = sorted(manifest_platforms - set(filesystem_platforms))
    for platform_id in extra_dirs:
        diagnostics.append(
            StatusDiagnostic(
                code="manifest-filesystem-drift",
                severity="warning",
                path=str(root / PLATFORM_DIRS[platform_id]),
                message=f"Platform directory `{platform_id}` exists but is not declared in {MANIFEST_FILE}.",
            )
        )
    for platform_id in missing_dirs:
        diagnostics.append(
            StatusDiagnostic(
                code="manifest-filesystem-drift",
                severity="error",
                path=str(root / PLATFORM_DIRS.get(platform_id, platform_id)),
                message=f"{MANIFEST_FILE} declares `{platform_id}` but the platform directory is missing.",
            )
        )

    invalid_platforms = sorted(platform for platform in manifest.platforms if platform not in VALID_PLATFORM_IDS)
    for platform_id in invalid_platforms:
        diagnostics.append(
            StatusDiagnostic(
                code="invalid-manifest-platform",
                severity="error",
                path=str(manifest.path),
                message=f"`{platform_id}` is not a valid Prism platform id.",
            )
        )

    min_version = manifest.min_prism_cli_version
    if min_version and _version_tuple(__version__) < _version_tuple(min_version):
        diagnostics.append(
            StatusDiagnostic(
                code="minimum-prism-cli-version-not-met",
                severity="error",
                path=str(manifest.path),
                message=f"Workspace requires Prism CLI >= {min_version}; running {__version__}.",
            )
        )

    for surface_group, surfaces in manifest.expected_surfaces.items():
        for surface in surfaces:
            if not _surface_exists(root, surface):
                diagnostics.append(
                    StatusDiagnostic(
                        code="missing-expected-surface",
                        severity="error",
                        path=str(root / surface),
                        message=f"Expected {surface_group} surface `{surface}` is missing.",
                    )
                )

    return diagnostics


def _project_name(workspace_result: WorkspaceLoadResult, answers: dict[str, Any]) -> str | None:
    if workspace_result.manifest and workspace_result.manifest.project_name:
        return workspace_result.manifest.project_name
    value = answers.get("project_name")
    return value if isinstance(value, str) else None


def _platforms(workspace_result: WorkspaceLoadResult, answers: dict[str, Any], root: Path) -> list[str]:
    if workspace_result.manifest and workspace_result.manifest.platforms:
        return workspace_result.manifest.platforms
    answer_platforms = _list_value(answers.get("platforms"))
    if answer_platforms:
        return answer_platforms
    return _detect_platform_dirs(root)


def _setup_state(root: Path, wiki_lint: WikiLintResult) -> str:
    wiki_root = root / "knowledge" / "wiki"
    if not wiki_root.exists():
        return "unknown"
    board_path = root / "knowledge" / "wiki" / "advisory" / "BOARD.md"
    if not board_path.exists():
        if wiki_lint.feature_count == 0:
            return "not-initialized"
        return "unknown"
    try:
        board_text = board_path.read_text(encoding="utf-8").lower()
    except OSError:
        return "unknown"
    if "generated by /setup-project" in board_text or "run /setup-project" in board_text or "run setup-project" in board_text:
        return "not-initialized"
    return "initialized"


def _intake_counts(root: Path) -> IntakeCounts:
    intake_root = root / "knowledge" / "intake"
    return IntakeCounts(
        pending=_count_queue_items(intake_root / "pending"),
        quarantined=_count_queue_items(intake_root / "quarantined"),
    )


def _count_queue_items(path: Path) -> int:
    return len(list_queue_items(path))


def list_queue_items(path: Path) -> list[str]:
    """Names of real intake items in a queue directory (templates and litter excluded)."""
    if not path.exists():
        return []
    items = [
        child.name
        for child in path.iterdir()
        if child.name not in IGNORED_INTAKE_FILES and not child.name.startswith("_") and not child.name.startswith(".")
    ]
    return sorted(items)


def detect_setup_state(root: Path, wiki_lint: WikiLintResult) -> str:
    """Public alias used by graph/read surfaces; see _setup_state."""
    return _setup_state(root, wiki_lint)


def _wiki_counts(root: Path) -> tuple[dict[str, int], dict[str, int], dict[str, int], dict[str, int]]:
    wiki_root = root / "knowledge" / "wiki"
    feature_status_counts: Counter[str] = Counter()
    feature_owner_counts: Counter[str] = Counter()
    open_question_counts: Counter[str] = Counter()
    requirement_status_counts: Counter[str] = Counter()

    for feature in read_feature_pages(wiki_root):
        status = feature.status or "unknown"
        owner = feature.owner or "unknown"
        feature_status_counts[status] += 1
        feature_owner_counts[owner] += 1
        rows, _errors = parse_open_question_rows(feature.page.body)
        for row in rows:
            if row["status"] == "open":
                open_question_counts[row["owner"]] += 1

    for status in sorted(VALID_FEATURE_STATUSES):
        feature_status_counts.setdefault(status, 0)

    for requirement in read_platform_requirement_pages(wiki_root):
        requirement_status_counts[requirement.status or "unknown"] += 1

    return (
        dict(sorted(feature_status_counts.items())),
        dict(sorted(feature_owner_counts.items())),
        dict(sorted(open_question_counts.items())),
        dict(sorted(requirement_status_counts.items())),
    )


def _confidence(
    workspace_result: WorkspaceLoadResult,
    status_diagnostics: list[StatusDiagnostic],
    wiki_lint: WikiLintResult,
) -> str:
    if (
        any(diag.severity == "error" for diag in workspace_result.diagnostics)
        or wiki_lint.error_count
        or any(diag.severity == "error" for diag in status_diagnostics)
    ):
        return "error"
    if workspace_result.diagnostics or wiki_lint.warning_count or status_diagnostics or workspace_result.manifest is None:
        return "degraded"
    return "high"


def _detect_platform_dirs(root: Path) -> list[str]:
    return [platform_id for platform_id, directory in PLATFORM_DIRS.items() if (root / directory).exists()]


def _list_value(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _diagnostics_to_dicts(
    manifest_diagnostics: list[WorkspaceDiagnostic],
    status_diagnostics: list[StatusDiagnostic],
    wiki_diagnostics: list[WikiDiagnostic],
    root: Path,
) -> list[dict[str, Any]]:
    data: list[dict[str, Any]] = [diagnostic.to_dict() for diagnostic in manifest_diagnostics]
    data.extend(diagnostic.to_dict() for diagnostic in status_diagnostics)
    data.extend(diagnostic.to_dict() for diagnostic in wiki_diagnostics)
    return data


def _version_tuple(value: str) -> tuple[int, int, int]:
    parts = value.split(".")
    numbers: list[int] = []
    for part in parts[:3]:
        try:
            numbers.append(int(part))
        except ValueError:
            numbers.append(0)
    while len(numbers) < 3:
        numbers.append(0)
    return tuple(numbers)  # type: ignore[return-value]


def _surface_exists(root: Path, surface: str) -> bool:
    normalized = surface.rstrip("/")
    if not normalized:
        return True
    return (root / normalized).exists()
