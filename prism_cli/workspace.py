"""Workspace detection and manifest helpers for Prism generated projects."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


MANIFEST_FILE = "prism.workspace.yml"
MANIFEST_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class WorkspaceDiagnostic:
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
class WorkspaceManifest:
    path: Path
    data: dict[str, Any]

    @property
    def schema_version(self) -> int | None:
        value = self.data.get("schema_version")
        return value if isinstance(value, int) else None

    @property
    def project_name(self) -> str | None:
        project = self.data.get("project")
        if not isinstance(project, dict):
            return None
        value = project.get("name")
        return value if isinstance(value, str) else None

    @property
    def platforms(self) -> list[str]:
        project = self.data.get("project")
        if not isinstance(project, dict):
            return []
        value = project.get("platforms")
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, str)]

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
    def platform_maturity(self) -> dict[str, dict[str, str]]:
        value = self.data.get("platform_maturity")
        if not isinstance(value, dict):
            return {}
        maturity: dict[str, dict[str, str]] = {}
        for platform_id, data in value.items():
            if not isinstance(platform_id, str) or not isinstance(data, dict):
                continue
            maturity[platform_id] = {key: item for key, item in data.items() if isinstance(key, str) and isinstance(item, str)}
        return maturity


@dataclass(frozen=True)
class WorkspaceLoadResult:
    root: Path
    manifest: WorkspaceManifest | None
    diagnostics: list[WorkspaceDiagnostic]


def load_workspace(root: Path) -> WorkspaceLoadResult:
    """Load the generated workspace manifest when present.

    Missing manifests are allowed during the transition period. Callers should
    degrade confidence rather than fail hard when the older generated-project
    shape is otherwise recognizable.
    """

    workspace_root = root.expanduser().resolve()
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
                    f"Missing {MANIFEST_FILE}; falling back to older generated-project signals.",
                )
            ],
        )

    try:
        data = yaml.safe_load(manifest_path.read_text(encoding="utf-8-sig")) or {}
    except OSError as exc:
        return WorkspaceLoadResult(root=workspace_root, manifest=None, diagnostics=[_diag("unreadable-workspace-manifest", "error", manifest_path, f"Unable to read {MANIFEST_FILE}: {exc}")])
    except yaml.YAMLError as exc:
        return WorkspaceLoadResult(root=workspace_root, manifest=None, diagnostics=[_diag("invalid-workspace-manifest-yaml", "error", manifest_path, f"Invalid YAML in {MANIFEST_FILE}: {exc}")])

    if not isinstance(data, dict):
        return WorkspaceLoadResult(root=workspace_root, manifest=None, diagnostics=[_diag("invalid-workspace-manifest-shape", "error", manifest_path, f"{MANIFEST_FILE} must be a mapping.")])

    diagnostics: list[WorkspaceDiagnostic] = []
    schema_version = data.get("schema_version")
    if not isinstance(schema_version, int):
        diagnostics.append(_diag("invalid-workspace-manifest-schema", "error", manifest_path, f"{MANIFEST_FILE} schema_version must be an integer."))
    elif schema_version > MANIFEST_SCHEMA_VERSION:
        diagnostics.append(
            _diag(
                "unsupported-workspace-manifest-schema",
                "error",
                manifest_path,
                f"{MANIFEST_FILE} schema_version is {schema_version}; this CLI supports {MANIFEST_SCHEMA_VERSION}. Upgrade Prism CLI to read this workspace.",
            )
        )
    elif schema_version < MANIFEST_SCHEMA_VERSION:
        diagnostics.append(
            _diag(
                "older-workspace-manifest-schema",
                "warning",
                manifest_path,
                f"{MANIFEST_FILE} schema_version is {schema_version}; this CLI supports {MANIFEST_SCHEMA_VERSION} and will use compatibility behavior.",
            )
        )

    return WorkspaceLoadResult(
        root=workspace_root,
        manifest=WorkspaceManifest(path=manifest_path, data=data),
        diagnostics=diagnostics,
    )


def detect_workspace_kind(root: Path) -> str:
    workspace_root = root.expanduser().resolve()
    if (workspace_root / MANIFEST_FILE).exists():
        return "generated-project"
    if (
        (workspace_root / "README.md").exists()
        and (workspace_root / "CONTEXT.md").exists()
        and (workspace_root / "knowledge" / "wiki" / "SCHEMA.md").exists()
    ):
        return "generated-project"
    if (workspace_root / "copier.yml").exists() and (workspace_root / "template").exists():
        return "template"
    return "unknown"


def _diag(code: str, severity: str, path: Path, message: str) -> WorkspaceDiagnostic:
    return WorkspaceDiagnostic(code=code, severity=severity, path=str(path), message=message)
