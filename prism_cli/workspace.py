"""Workspace detection, manifest, and generation-contract helpers.

The workspace manifest is deliberately a small runtime contract.  It is read
by the CLI, while ``.copier-answers.yml`` remains Copier's generation/update
source of truth.  The helpers in this module keep the comparison rules in one
place so status, doctor, and the read surfaces can agree about degraded state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from copy import deepcopy
from functools import cached_property
from pathlib import Path
from typing import Any, Mapping, Sequence
import re
from uuid import UUID

import yaml

from prism_cli import __version__
from prism_cli.app_model import (
    GENERATED_PLATFORM_DIRS,
    MANIFEST_SCHEMA_VERSION,
    GENERATION_SCAFFOLDED,
    App,
    WorkspaceDiagnostic,
    WorkspaceModel,
    app_entries,
    normalize_manifest,
    repository_entries,
    resolve_local_repositories,
)
from prism_cli.wiki_model import request_fact


MANIFEST_FILE = "prism.workspace.yml"
COPIER_ANSWERS_FILE = ".copier-answers.yml"

# These are the user-facing Copier questions.  Derived Copier values and
# private ``_`` metadata intentionally stay out of status output.
GENERATION_ANSWER_FIELDS = (
    "project_name",
    "project_slug",
    "package_identifier",
    "description",
    "stacks",
    "auth_methods",
    "github_org",
)

_VERSION_PATTERN = re.compile(r"^\d+(?:\.\d+){0,2}(?:[-+][0-9A-Za-z.-]+)?$")


@dataclass(frozen=True)
class WorkspaceManifest:
    path: Path
    data: dict[str, Any]

    @property
    def schema_version(self) -> int | None:
        value = self.data.get("schema_version")
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    @property
    def project_data(self) -> dict[str, Any]:
        value = self.data.get("project")
        return value if isinstance(value, dict) else {}

    @property
    def workflow(self) -> dict[str, Any]:
        value = self.data.get("workflow")
        return value if isinstance(value, dict) else {}

    @property
    def workflow_only(self) -> bool:
        return self.workflow.get("mode") == "workflow"

    @property
    def project_name(self) -> str | None:
        value = self.project_data.get("name")
        return value if isinstance(value, str) else None

    @cached_property
    def _normalized(self) -> tuple[WorkspaceModel, list[WorkspaceDiagnostic]]:
        """The application model, built once per manifest by the one normalizer."""

        return normalize_manifest(self.data, path=self.path)

    @property
    def model(self) -> WorkspaceModel:
        return self._normalized[0]

    @property
    def model_diagnostics(self) -> list[WorkspaceDiagnostic]:
        return list(self._normalized[1])

    @property
    def apps(self) -> tuple[App, ...]:
        return self.model.apps

    @property
    def app_ids(self) -> list[str]:
        """The IDs of the active apps."""

        return self.model.active_app_ids

    @property
    def generated_by(self) -> dict[str, Any]:
        value = self.data.get("generated_by")
        return value if isinstance(value, dict) else {}

    @property
    def generated_by_prism_cli_version(self) -> str | None:
        value = self.generated_by.get("prism_cli_version")
        return value if isinstance(value, str) else None

    @property
    def template_source(self) -> str | None:
        value = self.generated_by.get("template_source")
        return value if isinstance(value, str) else None

    @property
    def template_version(self) -> str | None:
        value = self.generated_by.get("template_version")
        return value if isinstance(value, str) else None

    @property
    def template_commit(self) -> str | None:
        value = self.generated_by.get("template_commit")
        return value if isinstance(value, str) else None

    @property
    def generated_at(self) -> str | None:
        value = self.generated_by.get("generated_at")
        return value if isinstance(value, str) else None

    @property
    def min_prism_cli_version(self) -> str | None:
        value = self.data.get("min_prism_cli_version")
        return value if isinstance(value, str) else None

    @property
    def expected_surfaces(self) -> dict[str, list[str]]:
        value = self.data.get("expected_surfaces")
        if not isinstance(value, dict):
            return {}
        surfaces: dict[str, list[str]] = {}
        for key, items in value.items():
            if isinstance(key, str) and isinstance(items, list):
                surfaces[key] = [item for item in items if isinstance(item, str)]
        return surfaces

    @property
    def paths(self) -> dict[str, str]:
        value = self.data.get("paths")
        if not isinstance(value, dict):
            return {}
        return {
            key: item
            for key, item in value.items()
            if isinstance(key, str) and isinstance(item, str)
        }

    @property
    def app_maturity(self) -> dict[str, dict[str, str]]:
        return {app_id: dict(entry) for app_id, entry in self.model.app_maturity.items()}



@dataclass(frozen=True)
class WorkspaceLoadResult:
    root: Path
    manifest: WorkspaceManifest | None
    diagnostics: list[WorkspaceDiagnostic]
    # A manifest can exist but be unreadable or use a schema newer than this
    # CLI.  Keep presence distinct from usability so output remains truthful.
    manifest_exists: bool = False
    manifest_schema_version: int | None = None
    # External repositories that resolve to a checkout through prism.local.yml.
    local_repositories: Mapping[str, Path] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkspaceInspection:
    """Canonical manifest/answers/filesystem facts shared by read surfaces."""

    root: Path
    load_result: WorkspaceLoadResult
    answers: dict[str, Any]
    answers_present: bool
    answers_path: Path
    filesystem_platforms: list[str]
    diagnostics: list[WorkspaceDiagnostic]

    @property
    def manifest(self) -> WorkspaceManifest | None:
        return self.load_result.manifest

    @property
    def project_name(self) -> str | None:
        return self.manifest.project_name if self.manifest else None

    @property
    def model(self) -> WorkspaceModel:
        """The application model of the manifest; a workspace without a usable manifest has no apps."""

        if self.manifest:
            return self.manifest.model
        return WorkspaceModel(schema_version=0)

    @property
    def app_ids(self) -> list[str]:
        """The IDs of the active apps of the model."""

        return self.model.active_app_ids

    @property
    def apps(self) -> list[dict[str, Any]]:
        """Every declared app in the shape workspace-level JSON reports."""

        return app_entries(self.model)

    @property
    def repositories(self) -> list[dict[str, Any]]:
        """The workspace's repositories with each external checkout's resolved or unresolved state."""

        if not self.manifest:
            return []
        return repository_entries(self.manifest.model, self.load_result.local_repositories)

    @property
    def contract_diagnostics(self) -> list[WorkspaceDiagnostic]:
        """Return schema and comparison diagnostics in one stable order."""

        return [*self.load_result.diagnostics, *self.diagnostics]


def load_workspace(root: Path) -> WorkspaceLoadResult:
    """Load the workspace manifest when present.

    A missing manifest is reported as a warning diagnostic and the workspace
    declares no apps. Inside one ``wiki_read_scope`` the manifest is read once, so the
    readers of a request agree on the same model.
    """

    return load_resolved_workspace(root.expanduser().resolve())


def load_resolved_workspace(workspace_root: Path) -> WorkspaceLoadResult:
    """``load_workspace`` for a root that is already resolved."""

    return request_fact(("workspace-load", str(workspace_root)), lambda: _load_workspace(workspace_root))


def _load_workspace(workspace_root: Path) -> WorkspaceLoadResult:
    manifest_path = workspace_root / MANIFEST_FILE
    if not manifest_path.exists():
        return WorkspaceLoadResult(
            root=workspace_root,
            manifest=None,
            diagnostics=[
                _diag(
                    "missing-workspace-manifest",
                    "warning",
                    manifest_path,
                    f"Missing {MANIFEST_FILE}; the workspace declares no apps.",
                )
            ],
            manifest_exists=False,
        )

    try:
        data = yaml.safe_load(manifest_path.read_text(encoding="utf-8-sig")) or {}
    except (OSError, UnicodeError) as exc:
        return WorkspaceLoadResult(
            root=workspace_root,
            manifest=None,
            diagnostics=[
                _diag(
                    "unreadable-workspace-manifest",
                    "error",
                    manifest_path,
                    f"Unable to read {MANIFEST_FILE}: {exc}",
                )
            ],
            manifest_exists=True,
        )
    except (yaml.YAMLError, ValueError, OverflowError) as exc:
        return WorkspaceLoadResult(
            root=workspace_root,
            manifest=None,
            diagnostics=[
                _diag(
                    "invalid-workspace-manifest-yaml",
                    "error",
                    manifest_path,
                    f"Invalid YAML in {MANIFEST_FILE}: {exc}",
                )
            ],
            manifest_exists=True,
        )

    if not isinstance(data, dict):
        return WorkspaceLoadResult(
            root=workspace_root,
            manifest=None,
            diagnostics=[
                _diag(
                    "invalid-workspace-manifest-shape",
                    "error",
                    manifest_path,
                    f"{MANIFEST_FILE} must be a mapping.",
                )
            ],
            manifest_exists=True,
        )

    diagnostics: list[WorkspaceDiagnostic] = []
    schema_version = data.get("schema_version")
    if not isinstance(schema_version, int) or isinstance(schema_version, bool):
        diagnostics.append(_diag("invalid-workspace-manifest-schema", "error", manifest_path, f"{MANIFEST_FILE} schema_version must be an integer."))
        return WorkspaceLoadResult(
            root=workspace_root,
            manifest=None,
            diagnostics=diagnostics,
            manifest_exists=True,
        )
    elif schema_version != MANIFEST_SCHEMA_VERSION:
        diagnostics.append(
            _diag(
                "unsupported-workspace-manifest-schema",
                "error",
                manifest_path,
                f"{MANIFEST_FILE} schema_version is {schema_version}; this CLI supports only {MANIFEST_SCHEMA_VERSION}. Recreate or reinstall this workspace with this CLI.",
            )
        )
        # Do not interpret fields from a schema this CLI does not understand.
        return WorkspaceLoadResult(
            root=workspace_root,
            manifest=None,
            diagnostics=diagnostics,
            manifest_exists=True,
            manifest_schema_version=schema_version,
        )

    diagnostics.extend(_validate_manifest_shape(data, manifest_path))

    manifest = WorkspaceManifest(path=manifest_path, data=data)
    diagnostics.extend(manifest.model_diagnostics)
    resolution = resolve_local_repositories(workspace_root, manifest.model)
    diagnostics.extend(resolution.diagnostics)
    local_repositories: Mapping[str, Path] = dict(resolution.paths)

    return WorkspaceLoadResult(
        root=workspace_root,
        manifest=manifest,
        diagnostics=diagnostics,
        manifest_exists=True,
        manifest_schema_version=schema_version,
        local_repositories=local_repositories,
    )


def inspect_workspace(root: Path) -> WorkspaceInspection:
    """Read manifest, Copier answers, and filesystem facts without writing.

    This is the shared boundary for status, doctor, and future wiki read
    surfaces.  The ``diagnostics`` list contains comparison and answers-file
    diagnostics; schema diagnostics remain on ``load_result`` so callers can
    preserve their source grouping while using one canonical inspection.
    """

    workspace_root = root.expanduser().resolve()
    load_result = load_workspace(workspace_root)
    answers_path = workspace_root / COPIER_ANSWERS_FILE
    answers, answers_present, answer_diagnostics = _read_answers(answers_path)
    filesystem_platforms = _detect_platform_dirs(workspace_root)
    diagnostics = list(answer_diagnostics)
    if not answers_present and detect_workspace_kind(workspace_root) == "generated-project":
        diagnostics.append(
            _diag(
                "missing-copier-answers",
                "warning",
                answers_path,
                f"Missing {COPIER_ANSWERS_FILE}; generation/update comparisons are unavailable.",
            )
        )
    diagnostics.extend(_compare_manifest_answers(load_result.manifest, answers, answers_path))
    diagnostics.extend(_compare_manifest_filesystem(load_result.manifest, filesystem_platforms, workspace_root))
    diagnostics.extend(_compare_manifest_runtime(load_result.manifest))
    return WorkspaceInspection(
        root=workspace_root,
        load_result=load_result,
        answers=answers,
        answers_present=answers_present,
        answers_path=answers_path,
        filesystem_platforms=filesystem_platforms,
        diagnostics=diagnostics,
    )


def workspace_model(root: Path, *, resolved: bool = False) -> WorkspaceModel:
    """The application model of a workspace: the manifest's, empty without a usable manifest.

    Pass ``resolved=True`` for a root that is already resolved.
    """

    manifest = (load_resolved_workspace(root) if resolved else load_workspace(root)).manifest
    return manifest.model if manifest is not None else WorkspaceModel(schema_version=0)


def detect_workspace_kind(root: Path) -> str:
    workspace_root = root.expanduser().resolve()
    if (workspace_root / "copier.yml").exists() and (workspace_root / "template").exists():
        return "template"
    if (workspace_root / MANIFEST_FILE).exists():
        manifest = load_workspace(workspace_root).manifest
        if manifest is not None and manifest.workflow_only:
            return "workflow-project"
        return "generated-project"
    if (
        (workspace_root / "README.md").exists()
        and (workspace_root / "AGENTS.md").exists()
        and (workspace_root / "knowledge" / "wiki" / "SCHEMA.md").exists()
        and (workspace_root / "knowledge" / "wiki" / "LIFECYCLE.md").exists()
    ):
        return "generated-project"
    return "unknown"


def _diag(code: str, severity: str, path: Path, message: str) -> WorkspaceDiagnostic:
    return WorkspaceDiagnostic(code=code, severity=severity, path=str(path), message=message)


def write_workspace_manifest(
    destination: Path,
    answers: Mapping[str, Any],
    *,
    prism_cli_version: str,
    template_source: str | None = None,
    template_version: str | None = None,
    template_commit: str | None = None,
    generated_at: str | None = None,
    apps: Sequence[Mapping[str, Any]] | None = None,
    repositories: Sequence[Mapping[str, Any]] | None = None,
) -> Path:
    """Write generation provenance into a generated workspace manifest.

    Copier renders the manifest template first.  This explicit generation or
    update step then records the CLI and template metadata known to the caller,
    and, once, the apps the questionnaire chose (``apps``, with the
    ``repositories`` that external apps declare).
    Read commands never call this function.
    """

    destination = destination.expanduser().resolve()
    manifest_path = destination / MANIFEST_FILE
    data: dict[str, Any] = {}
    if manifest_path.exists():
        try:
            loaded = yaml.safe_load(manifest_path.read_text(encoding="utf-8-sig")) or {}
        except (OSError, UnicodeError) as exc:
            raise ValueError(f"Unable to read existing {MANIFEST_FILE}: {exc}") from exc
        except (yaml.YAMLError, ValueError, OverflowError) as exc:
            raise ValueError(f"Existing {MANIFEST_FILE} contains invalid YAML: {exc}") from exc
        if not isinstance(loaded, dict):
            raise ValueError(f"Existing {MANIFEST_FILE} must be a mapping.")
        data = deepcopy(loaded)
        if data and (type(data.get("schema_version")) is not int or data["schema_version"] != MANIFEST_SCHEMA_VERSION):
            raise ValueError(
                f"Existing {MANIFEST_FILE} does not use schema_version {MANIFEST_SCHEMA_VERSION}; recreate or reinstall this workspace with this CLI."
            )

    data["schema_version"] = MANIFEST_SCHEMA_VERSION
    data.setdefault("min_prism_cli_version", __version__)
    generated_by = data.get("generated_by")
    if not isinstance(generated_by, dict):
        generated_by = {}
    generated_by.update(
        {
            "tool": "prism-cli",
            "prism_cli_version": prism_cli_version,
            "template_version": template_version or "unknown",
            "template_commit": template_commit or "unknown",
            "generated_at": generated_at or _current_timestamp(),
        }
    )
    if template_source:
        generated_by["template_source"] = template_source
    data["generated_by"] = generated_by

    project = data.get("project")
    if not isinstance(project, dict):
        project = {}
    answer_to_project = {
        "project_name": "name",
        "project_slug": "slug",
        "package_identifier": "package_identifier",
        "description": "description",
        "auth_methods": "auth_methods",
        "github_org": "github_org",
    }
    for answer_key, project_key in answer_to_project.items():
        if answer_key in answers:
            project[project_key] = deepcopy(answers[answer_key])
    data["project"] = project
    # The questionnaire's apps are generation input; they enter the manifest once.
    if apps is not None and "apps" not in data:
        data = _with_apps(data, apps, repositories or ())

    destination.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return manifest_path


def _with_apps(data: dict[str, Any], apps: Sequence[Mapping[str, Any]], repositories: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The manifest with its apps, their maturity and the workflows of the scaffolded ones, after ``project``."""

    from prism_cli.packs import stack_maturity, workflow_path

    entries = [dict(app) for app in apps]
    scaffolded = [app for app in entries if app.get("generation") == GENERATION_SCAFFOLDED]
    added: dict[str, Any] = {}
    if repositories:
        added["repositories"] = [dict(item) for item in repositories]
    added["apps"] = entries
    maturity = {app["id"]: stack_maturity(app["stack"]) for app in scaffolded}
    if maturity:
        added["app_maturity"] = maturity
    result: dict[str, Any] = {}
    for key, value in data.items():
        result[key] = value
        if key == "project":
            result.update(added)
    for key, value in added.items():
        result.setdefault(key, value)
    surfaces = result.get("expected_surfaces")
    if isinstance(surfaces, dict) and scaffolded:
        surfaces = dict(surfaces)
        surfaces["workflows"] = [workflow_path(app["id"]) for app in scaffolded]
        result["expected_surfaces"] = surfaces
    return result


def _current_timestamp() -> str:
    from datetime import datetime

    return datetime.now().astimezone().isoformat(timespec="seconds")


def _read_answers(path: Path) -> tuple[dict[str, Any], bool, list[WorkspaceDiagnostic]]:
    if not path.exists():
        return {}, False, []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}
    except (OSError, UnicodeError) as exc:
        return {}, True, [_diag("unreadable-copier-answers", "error", path, f"Unable to read {COPIER_ANSWERS_FILE}: {exc}")]
    except (yaml.YAMLError, ValueError, OverflowError) as exc:
        return {}, True, [_diag("invalid-copier-answers-yaml", "error", path, f"Invalid YAML in {COPIER_ANSWERS_FILE}: {exc}")]
    if not isinstance(data, dict):
        return {}, True, [_diag("invalid-copier-answers-shape", "error", path, f"{COPIER_ANSWERS_FILE} must be a mapping.")]
    if "_src_path" not in data:
        return data, True, [_diag("missing-copier-template-source", "warning", path, f"{COPIER_ANSWERS_FILE} does not record Copier's `_src_path`.")]
    return data, True, []


def _compare_manifest_answers(
    manifest: WorkspaceManifest | None,
    answers: Mapping[str, Any],
    answers_path: Path,
) -> list[WorkspaceDiagnostic]:
    if manifest is None or not answers:
        return []
    project = manifest.project_data
    answer_to_project = {
        "project_name": "name",
        "project_slug": "slug",
        "package_identifier": "package_identifier",
        "description": "description",
        "auth_methods": "auth_methods",
        "github_org": "github_org",
    }
    diagnostics: list[WorkspaceDiagnostic] = []
    for answer_key, project_key in answer_to_project.items():
        if answer_key not in answers or project_key not in project:
            continue
        answer_value = answers[answer_key]
        manifest_value = project[project_key]
        if _comparison_value(answer_value) != _comparison_value(manifest_value):
            diagnostics.append(
                _diag(
                    "manifest-answers-drift",
                    "error",
                    manifest.path,
                    f"Manifest project field `{project_key}` differs from Copier answers `{answer_key}`.",
                )
            )
    return diagnostics


def _compare_manifest_filesystem(
    manifest: WorkspaceManifest | None,
    filesystem_platforms: list[str],
    root: Path,
) -> list[WorkspaceDiagnostic]:
    if manifest is None:
        return []
    diagnostics: list[WorkspaceDiagnostic] = _compare_app_directories(manifest, filesystem_platforms, root)
    for path_key, relative_path in manifest.paths.items():
        if not _surface_exists(root, relative_path):
            diagnostics.append(
                _diag(
                    "missing-manifest-path",
                    "error",
                    root / relative_path,
                    f"Manifest path `{path_key}` points to missing `{relative_path}`.",
                )
            )
    for surface_group, surfaces in manifest.expected_surfaces.items():
        for surface in surfaces:
            if not _surface_exists(root, surface):
                diagnostics.append(
                    _diag(
                        "missing-expected-surface",
                        "warning",
                        root / surface,
                        f"Expected {surface_group} surface `{surface}` is missing.",
                    )
                )
    return diagnostics


def _compare_app_directories(
    manifest: WorkspaceManifest,
    filesystem_platforms: list[str],
    root: Path,
) -> list[WorkspaceDiagnostic]:
    """Compare the declared apps with the workspace. Only apps in this repository are looked up, at their paths.

    An app in an external repository is never looked up on disk here; its
    checkout is resolved through ``prism.local.yml`` and reported separately.
    """

    if manifest.workflow_only:
        return []
    diagnostics: list[WorkspaceDiagnostic] = []
    declared_paths = [app.path for app in manifest.model.workspace_apps()]
    for platform_id in sorted(filesystem_platforms):
        directory = GENERATED_PLATFORM_DIRS[platform_id]
        if not any(path == directory or path.startswith(f"{directory}/") or directory.startswith(f"{path}/") for path in declared_paths):
            diagnostics.append(
                _diag(
                    "manifest-filesystem-drift",
                    "warning",
                    root / directory,
                    f"Directory `{directory}` exists but no app in {MANIFEST_FILE} is declared at that path.",
                )
            )
    for app in manifest.model.workspace_apps(active_only=True):
        if not (root / app.path).exists():
            diagnostics.append(
                _diag(
                    "manifest-filesystem-drift",
                    "error",
                    root / app.path,
                    f"{MANIFEST_FILE} declares app `{app.id}` but its directory `{app.path}` is missing.",
                )
            )
    return diagnostics


def _compare_manifest_runtime(manifest: WorkspaceManifest | None) -> list[WorkspaceDiagnostic]:
    """Check runtime constraints that do not depend on wiki parsing."""

    if manifest is None:
        return []

    diagnostics: list[WorkspaceDiagnostic] = []
    minimum = manifest.min_prism_cli_version
    if minimum and _VERSION_PATTERN.fullmatch(minimum.strip()):
        if _version_tuple(__version__) < _version_tuple(minimum):
            diagnostics.append(
                _diag(
                    "minimum-prism-cli-version-not-met",
                    "error",
                    manifest.path,
                    f"Workspace requires Prism CLI >= {minimum}; running {__version__}.",
                )
            )
    return diagnostics


def _validate_manifest_shape(data: Mapping[str, Any], path: Path) -> list[WorkspaceDiagnostic]:
    diagnostics: list[WorkspaceDiagnostic] = []
    workflow = data.get("workflow")
    if workflow is not None:
        valid = isinstance(workflow, dict)
        if valid:
            valid = (
                isinstance(workflow.get("version"), str)
                and bool(workflow["version"].strip())
                and workflow.get("mode") in ("workflow", "generated")
                and isinstance(workflow.get("board_id"), str)
            )
        if valid:
            try:
                UUID(workflow["board_id"])
            except (ValueError, AttributeError):
                valid = False
        if not valid:
            diagnostics.append(_diag("invalid-workspace-workflow", "error", path, "Manifest `workflow` requires a version string, UUID board_id, and mode workflow or generated."))
        elif workflow["version"] != "1":
            diagnostics.append(_diag("unsupported-workflow-version", "warning", path, "This workflow version is not supported for connected writes; the workspace remains readable."))
    project = data.get("project")
    if workflow is not None and not isinstance(project, dict):
        diagnostics.append(_diag("missing-workflow-project", "error", path, "A workflow workspace requires project identity."))
    if project is not None and not isinstance(project, dict):
        diagnostics.append(_diag("invalid-workspace-manifest-project", "error", path, "Manifest `project` must be a mapping."))
    elif isinstance(project, dict):
        if "name" in project and not isinstance(project["name"], str):
            diagnostics.append(_diag("invalid-workspace-manifest-project", "error", path, "Manifest project `name` must be a string."))

    generated_by = data.get("generated_by")
    if generated_by is not None and not isinstance(generated_by, dict):
        diagnostics.append(_diag("invalid-workspace-manifest-provenance", "error", path, "Manifest `generated_by` must be a mapping."))

    min_version = data.get("min_prism_cli_version")
    if min_version is not None and (
        not isinstance(min_version, str) or not _VERSION_PATTERN.fullmatch(min_version.strip())
    ):
        diagnostics.append(
            _diag(
                "invalid-min-prism-cli-version",
                "error",
                path,
                "Manifest `min_prism_cli_version` must be a dotted numeric version.",
            )
        )

    paths = data.get("paths")
    if paths is not None and (
        not isinstance(paths, dict)
        or any(not isinstance(key, str) or not isinstance(value, str) for key, value in paths.items())
    ):
        diagnostics.append(_diag("invalid-workspace-manifest-paths", "error", path, "Manifest `paths` must map string names to string paths."))

    expected_surfaces = data.get("expected_surfaces")
    if expected_surfaces is not None and (
        not isinstance(expected_surfaces, dict)
        or any(not isinstance(key, str) or not isinstance(value, list) or any(not isinstance(item, str) for item in value) for key, value in expected_surfaces.items())
    ):
        diagnostics.append(_diag("invalid-workspace-manifest-surfaces", "error", path, "Manifest `expected_surfaces` must map names to lists of paths."))
    return diagnostics


def _detect_platform_dirs(root: Path) -> list[str]:
    return [platform_id for platform_id, directory in GENERATED_PLATFORM_DIRS.items() if (root / directory).exists()]


def _comparison_value(value: Any) -> Any:
    if isinstance(value, list):
        return [_comparison_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _comparison_value(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    return value


def _version_tuple(value: str) -> tuple[int, int, int]:
    numbers: list[int] = []
    for part in value.strip().split(".")[:3]:
        match = re.match(r"\d+", part)
        numbers.append(int(match.group(0)) if match else 0)
    while len(numbers) < 3:
        numbers.append(0)
    return tuple(numbers)  # type: ignore[return-value]


def _surface_exists(root: Path, surface: str) -> bool:
    normalized = surface.rstrip("/")
    if not normalized:
        return True
    return (root / normalized).exists()
