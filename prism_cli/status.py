"""Workspace status aggregation for generated Prism projects."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
import subprocess
from typing import Any

from prism_cli.app_model import PURPOSE_KNOWLEDGE_ROOT, WORKSPACE_REPOSITORY_ID
from prism_cli.wiki_lint import WIKI_BLOCKER_CODES, WikiDiagnostic, WikiLintResult, lint_wiki
from prism_cli.wiki_model import (
    FEATURE_STATUS_ORDER,
    active_scope,
    app_stages,
    parse_open_question_rows,
    read_feature_evidence,
    read_feature_pages,
    read_app_requirement_pages,
    read_wiki_settings,
    status_rank,
)
from prism_cli.workspace import (
    COPIER_ANSWERS_FILE,
    GENERATION_ANSWER_FIELDS,
    MANIFEST_FILE,
    WorkspaceDiagnostic,
    WorkspaceInspection,
    WorkspaceLoadResult,
    detect_workspace_kind,
    inspect_workspace,
)


IGNORED_INTAKE_FILES = {"PO_BRIEF_TEMPLATE.md", "DESIGN_HANDOFF_TEMPLATE.md", ".gitkeep", ".DS_Store", "desktop.ini", "Thumbs.db"}
DEFAULT_STALE_AFTER_DAYS = 14


@dataclass(frozen=True)
class SettingsHealth:
    """The effective wiki staleness setting and its source health."""

    path: Path
    stale_after_days: int = DEFAULT_STALE_AFTER_DAYS
    health: str = "degraded"
    source: str = "fallback"
    diagnostics: list[StatusDiagnostic] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "stale_after_days": self.stale_after_days,
            "health": self.health,
            "status": self.health,
            "source": self.source,
            "configured": self.source == "settings",
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
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
class AdvisoryReviewSnapshot:
    counts: dict[str, int] = field(default_factory=dict)
    pending_feature_ids: list[str] = field(default_factory=list)

    @property
    def pending(self) -> int:
        return self.counts.get("pending", 0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "counts": dict(self.counts),
            "pending": self.pending,
            "pending_feature_ids": list(self.pending_feature_ids),
        }


@dataclass(frozen=True)
class WorkspaceStatus:
    root: Path
    workspace_kind: str
    project_name: str | None
    apps: list[dict[str, Any]]
    repositories: list[dict[str, Any]]
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
    app_requirement_status_counts: dict[str, int] = field(default_factory=dict)
    # feature ID -> app ID -> app stage, for the features at `in-dev` or later (CONTRACTS 4.2).
    feature_app_stages: dict[str, dict[str, str]] = field(default_factory=dict)
    advisory_review_snapshot: AdvisoryReviewSnapshot = field(default_factory=AdvisoryReviewSnapshot)
    settings_health: SettingsHealth | None = None
    generation_answers: dict[str, Any] = field(default_factory=dict)
    template_metadata: dict[str, Any] = field(default_factory=dict)
    answers_present: bool = False
    purpose: str | None = None

    @property
    def knowledge_root(self) -> bool:
        return self.purpose == PURPOSE_KNOWLEDGE_ROOT

    @property
    def workspace_stacks(self) -> set[str]:
        """The stacks of the active apps that live in this repository; doctor checks the tools they need."""

        return {app["stack"] for app in self.apps if app["status"] == "active" and app["repository"] == WORKSPACE_REPOSITORY_ID}

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
                **({"purpose": self.purpose} if self.purpose else {}),
                "apps": [dict(app) for app in self.apps],
                "repositories": [dict(repository) for repository in self.repositories],
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
                    "app_requirement_status_counts": dict(self.app_requirement_status_counts),
                    "feature_app_stages": {feature_id: dict(stages) for feature_id, stages in self.feature_app_stages.items()},
                    "blocker_count": self.blocker_count,
                    "error_count": self.wiki_lint.error_count,
                    "warning_count": self.wiki_lint.warning_count,
                    "clean": self.wiki_lint.is_clean,
                },
                "advisory_review": self.advisory_review_snapshot.to_dict(),
                "settings": self.settings_health.to_dict() if self.settings_health else None,
                "generation": {
                    "answers_file": str(self.root / COPIER_ANSWERS_FILE),
                    "answers_present": self.answers_present,
                    "answers": dict(self.generation_answers),
                    "template": dict(self.template_metadata),
                },
                # These direct aliases keep the detail names easy to consume
                # without changing the stable envelope keys.
                "generation_answers": dict(self.generation_answers),
                "template": dict(self.template_metadata),
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
        paths = [
            str(self.root / MANIFEST_FILE),
            str(self.root / COPIER_ANSWERS_FILE),
            str(self.root / "knowledge" / "wiki"),
            str(self.root / "knowledge" / "intake"),
        ]
        if self.settings_health:
            paths.append(str(self.settings_health.path))
        return list(dict.fromkeys(paths))


@dataclass(frozen=True)
class BoardCheck:
    """One read-only shared-board readiness check for ``prism doctor --workspace``.

    ``state`` is ``pass``, ``warn``, ``fail`` or ``skip``. Only ``fail`` makes
    doctor exit with a validation error.
    """

    code: str
    label: str
    state: str
    detail: str = ""
    fix: str = ""


def _shell_path(path: Path) -> str:
    text = str(path)
    return f'"{text}"' if " " in text else text


def build_board_checks(root: Path, port: int | None = None) -> list[BoardCheck]:
    """Run the shared-board readiness checks without writing anything.

    A workspace with no workflow pin has not adopted the board, so it gets one
    warning instead of checks that cannot apply. Nothing here creates board
    state, grants or files.
    """

    from prism_cli.board_server import DEFAULT_BOARD_PORT

    workspace = Path(root).expanduser().resolve()
    board_port = DEFAULT_BOARD_PORT if port is None else port
    manifest = inspect_workspace(workspace).manifest
    workflow = manifest.workflow if manifest else {}
    if not workflow:
        # A generated project needs the explicit upgrade; install refuses it.
        answers = workspace / COPIER_ANSWERS_FILE
        generated = bool(manifest and isinstance(manifest.data.get("generated_by"), dict)) or answers.is_symlink() or answers.exists()
        command = "upgrade" if generated else "install"
        return [
            BoardCheck(
                "workflow-pin",
                "Workflow pin is compatible with this Prism installation",
                "warn",
                "This workspace has no workflow pin, so the shared board is unavailable.",
                f"Preview adoption with `prism workflow {command} {_shell_path(workspace)}`; nothing changes until you add --apply.",
            )
        ]

    pin = _workflow_pin_check(workspace, workflow)
    return [
        pin,
        _active_grant_check(workspace, workflow, pin.state == "pass"),
        _board_port_check(board_port),
        _state_ignored_check(workspace),
    ]


def _workflow_pin_check(workspace: Path, workflow: dict[str, Any]) -> BoardCheck:
    from prism_cli.board_service import BoardError, BoardService

    label = "Workflow pin is compatible with this Prism installation"
    try:
        # The service constructor is read-only; its compatibility verdict is the
        # same one `prism board status` and the server use.
        with BoardService(workspace) as service:
            compatibility = service.compatibility()
    except BoardError as exc:
        reason = exc.message
    except (OSError, ValueError) as exc:
        reason = str(exc)
    else:
        if not compatibility["read_only"]:
            return BoardCheck("workflow-pin", label, "pass", f"Workflow version {workflow.get('version')} matches this installation.")
        reason = compatibility.get("reason") or "The workflow pin is not compatible."
    return BoardCheck(
        "workflow-pin",
        label,
        "fail",
        str(reason),
        f"Preview `prism workflow upgrade {_shell_path(workspace)}` and apply it after review. "
        "If the message asks for a newer Prism, upgrade Prism first.",
    )


def _active_grant_check(workspace: Path, workflow: dict[str, Any], pin_ok: bool) -> BoardCheck:
    from prism_cli.board_store import count_active_grants

    label = "At least one active board grant exists"
    grant_fix = f'Issue one with `prism board grant "NAME" --kind human|agent --write --path {_shell_path(workspace)}`.'
    if not pin_ok:
        return BoardCheck("active-grant", label, "skip", "Needs a compatible workflow pin first.")
    identity = (
        str(workflow.get("board_id")),
        str(workflow.get("version")),
        str(workflow.get("asset_digest") or ""),
    )
    try:
        counts = count_active_grants(workspace, identity)
    except (OSError, ValueError) as exc:
        return BoardCheck(
            "active-grant",
            label,
            "fail",
            f"The board state cannot be read safely: {exc}",
            "Resolve the state path problem, then run doctor again.",
        )
    if counts is None or counts[0] == 0:
        revoked = _revoked_grant_count(workspace) if counts is not None else 0
        message = f"No active grants ({revoked} revoked)." if revoked else "No grants yet."
        return BoardCheck("active-grant", label, "warn", message, grant_fix)
    active, current = counts
    if current == 0:
        return BoardCheck(
            "active-grant",
            label,
            "warn",
            f"{active} grant(s) were issued for an earlier workflow pin and no longer work.",
            grant_fix,
        )
    return BoardCheck("active-grant", label, "pass", f"{current} active grant(s).")


def _revoked_grant_count(workspace: Path) -> int:
    """Count revoked grants in a journal `count_active_grants` already accepted.

    The journal is opened read-only; any problem reads as zero revoked grants,
    which leaves the plain "No grants yet." message.
    """

    import sqlite3
    from urllib.parse import quote

    try:
        database = (workspace / ".prism" / "state" / "board.sqlite3").resolve(strict=True)
        connection = sqlite3.connect(f"file:{quote(str(database).replace(chr(92), '/'), safe='/:')}?mode=ro", uri=True, timeout=1)
        try:
            return int(connection.execute("SELECT COUNT(*) FROM grants WHERE active = 0").fetchone()[0])
        finally:
            connection.close()
    except (OSError, ValueError, sqlite3.Error):
        return 0


def _board_port_check(port: int) -> BoardCheck:
    from prism_cli.board_server import loopback_port_problem

    label = f"Default board port {port} is free"
    problem = loopback_port_problem(port)
    if problem is None:
        return BoardCheck("board-port", label, "pass")
    return BoardCheck(
        "board-port",
        label,
        "warn",
        f"Port {port} cannot be used: {problem}.",
        "If the board is already running, this is expected. Otherwise run `prism board serve --port <other port>`.",
    )


def _state_ignored_check(workspace: Path) -> BoardCheck:
    label = "`.prism/state` is ignored by git"
    probe = ".prism/state/board.sqlite3"

    def run_git(*args: str) -> subprocess.CompletedProcess[str] | None:
        try:
            return subprocess.run(
                ["git", "-C", str(workspace), *args],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None

    inside = run_git("rev-parse", "--is-inside-work-tree")
    if inside is None:
        return BoardCheck("state-ignored", label, "skip", "Git is not available, so this check was skipped.")
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        return BoardCheck("state-ignored", label, "skip", "This folder is not a git repository, so this check was skipped.")
    ignored = run_git("check-ignore", "-q", "--", probe)
    if ignored is None:
        return BoardCheck("state-ignored", label, "skip", "Git could not be run, so this check was skipped.")
    if ignored.returncode == 0:
        return BoardCheck("state-ignored", label, "pass")
    if ignored.returncode == 1:
        return BoardCheck(
            "state-ignored",
            label,
            "fail",
            "Grants and the operation journal could be committed by mistake.",
            "Add `.prism/state/` to .gitignore.",
        )
    return BoardCheck("state-ignored", label, "skip", "Git could not evaluate the ignore rules, so this check was skipped.")


def build_status(root: Path) -> WorkspaceStatus:
    workspace_root = root.expanduser().resolve()
    inspection = inspect_workspace(workspace_root)
    workspace_result = inspection.load_result
    answers = inspection.answers
    wiki_lint = lint_wiki(workspace_root)
    status_diagnostics = _status_diagnostics(inspection.diagnostics)
    settings_health = _settings_health(workspace_root)
    status_diagnostics.extend(settings_health.diagnostics)

    project_name = inspection.project_name
    setup_state = _setup_state(workspace_root, wiki_lint)
    intake = _intake_counts(workspace_root)
    feature_counts, owner_counts, open_question_counts, requirement_counts = _wiki_counts(workspace_root)
    feature_app_stages = _feature_app_stages(workspace_root, inspection.model)
    advisory_review_snapshot = _advisory_review_snapshot(workspace_root)
    confidence = _confidence(workspace_result, status_diagnostics, wiki_lint)

    return WorkspaceStatus(
        root=workspace_root,
        workspace_kind=detect_workspace_kind(workspace_root),
        project_name=project_name,
        apps=inspection.apps,
        repositories=inspection.repositories,
        setup_state=setup_state,
        confidence=confidence,
        manifest_present=workspace_result.manifest_exists,
        manifest_diagnostics=workspace_result.diagnostics,
        status_diagnostics=status_diagnostics,
        wiki_lint=wiki_lint,
        intake=intake,
        feature_status_counts=feature_counts,
        feature_owner_counts=owner_counts,
        open_questions_by_owner=open_question_counts,
        app_requirement_status_counts=requirement_counts,
        feature_app_stages=feature_app_stages,
        advisory_review_snapshot=advisory_review_snapshot,
        settings_health=settings_health,
        generation_answers=_safe_generation_answers(answers),
        template_metadata=_template_metadata(inspection),
        answers_present=inspection.answers_present,
        purpose=inspection.model.purpose,
    )


def _status_diagnostics(diagnostics: list[WorkspaceDiagnostic]) -> list[StatusDiagnostic]:
    return [
        StatusDiagnostic(
            code=diagnostic.code,
            severity=diagnostic.severity,
            path=diagnostic.path,
            message=diagnostic.message,
        )
        for diagnostic in diagnostics
    ]


def _settings_health(root: Path) -> SettingsHealth:
    settings_path = root / "knowledge" / "wiki" / "SETTINGS.md"
    settings = read_wiki_settings(root / "knowledge" / "wiki")
    diagnostics = [
        StatusDiagnostic(
            code=code,
            severity="warning",
            path=str(settings.path),
            message=message,
        )
        for code, message in settings.diagnostics
    ]
    return SettingsHealth(
        path=settings_path,
        stale_after_days=settings.stale_after_days,
        health="degraded" if settings.used_fallback else "healthy",
        source="fallback" if settings.used_fallback else "settings",
        diagnostics=diagnostics,
    )


def _advisory_review_snapshot(root: Path) -> AdvisoryReviewSnapshot:
    counts: Counter[str] = Counter()
    pending_feature_ids: list[str] = []
    for feature in read_feature_pages(root / "knowledge" / "wiki"):
        state = feature.advisory_review or "unknown"
        counts[state] += 1
        if state == "pending":
            pending_feature_ids.append(feature.feature_id)

    known_states = ("not-needed", "pending", "done", "skipped", "unknown")
    for state in known_states:
        counts.setdefault(state, 0)
    return AdvisoryReviewSnapshot(
        counts=dict(sorted(counts.items())),
        pending_feature_ids=sorted(pending_feature_ids),
    )


def _safe_generation_answers(answers: dict[str, Any]) -> dict[str, Any]:
    """Return only documented, non-private Copier fields for status output."""

    safe_answers: dict[str, Any] = {}
    for key in GENERATION_ANSWER_FIELDS:
        if key not in answers:
            continue
        value = _safe_json_value(answers[key])
        if value is not _UNSAFE_VALUE:
            safe_answers[key] = value
    return safe_answers


_UNSAFE_VALUE = object()


def _safe_json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, list):
        safe_values = [_safe_json_value(item) for item in value]
        return safe_values if all(item is not _UNSAFE_VALUE for item in safe_values) else _UNSAFE_VALUE
    if isinstance(value, dict):
        safe_mapping: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                return _UNSAFE_VALUE
            safe_item = _safe_json_value(item)
            if safe_item is _UNSAFE_VALUE:
                return _UNSAFE_VALUE
            safe_mapping[key] = safe_item
        return safe_mapping
    return _UNSAFE_VALUE


def _template_metadata(inspection: WorkspaceInspection) -> dict[str, Any]:
    manifest = inspection.manifest
    answers = inspection.answers
    metadata: dict[str, Any] = {
        "answers_file": str(inspection.answers_path),
        "template_source": None,
        "template_version": None,
        "template_commit": None,
        "generated_by_prism_cli_version": None,
        "generated_at": None,
    }
    if manifest:
        metadata.update(
            {
                "template_source": manifest.template_source,
                "template_version": _known_metadata_value(manifest.template_version),
                "template_commit": _known_metadata_value(manifest.template_commit),
                "generated_by_prism_cli_version": _known_metadata_value(manifest.generated_by_prism_cli_version),
                "generated_at": _known_metadata_value(manifest.generated_at),
            }
        )

    # The manifest records provenance when the generator knew it.  The Copier
    # answers file is the documented fallback for source and commit metadata only.
    if metadata["template_source"] is None:
        source = answers.get("_src_path")
        if isinstance(source, str):
            metadata["template_source"] = source
    if metadata["template_commit"] is None:
        commit = answers.get("_commit")
        if isinstance(commit, str):
            metadata["template_commit"] = commit
    return metadata


def _known_metadata_value(value: str | None) -> str | None:
    if value is None or value.strip().lower() in {"", "unknown", "none", "null"}:
        return None
    return value


# Workspace contract inspection lives in prism_cli.workspace.inspect_workspace.


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
    except (OSError, UnicodeError):
        return "unknown"
    if ("<!-- prism:setup-required -->" in board_text or "will be generated by /setup-project" in board_text
            or "run /setup-project" in board_text or "run setup-project" in board_text):
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

    for status in FEATURE_STATUS_ORDER:
        feature_status_counts.setdefault(status, 0)

    for requirement in read_app_requirement_pages(wiki_root):
        requirement_status_counts[requirement.status or "unknown"] += 1

    return (
        dict(sorted(feature_status_counts.items())),
        dict(sorted(feature_owner_counts.items())),
        dict(sorted(open_question_counts.items())),
        dict(sorted(requirement_status_counts.items())),
    )


def _feature_app_stages(root: Path, model: Any) -> dict[str, dict[str, str]]:
    """The stage of each active app of every feature at `in-dev` or later, from its evidence tables."""

    stages: dict[str, dict[str, str]] = {}
    for feature in read_feature_pages(root / "knowledge" / "wiki"):
        if status_rank(feature.status) < status_rank("in-dev"):
            continue
        stages[feature.feature_id] = app_stages(active_scope(feature.apps, model), read_feature_evidence(feature.page.body))
    return dict(sorted(stages.items()))


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
