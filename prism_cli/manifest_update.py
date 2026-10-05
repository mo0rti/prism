"""Semantic, field-level merge support for the Prism workspace manifest."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
import shutil
import tempfile
from typing import Any

import yaml

from prism_cli.app_model import MANIFEST_SCHEMA_VERSION, normalize_manifest
from prism_cli.workspace import COPIER_ANSWERS_FILE, MANIFEST_FILE


_PROVENANCE_KEYS = {
    "tool",
    "prism_cli_version",
    "template_source",
    "template_version",
    "template_commit",
    "generated_at",
}
_MISSING = object()


class ManifestUpdateError(ValueError):
    """Raised when a safe manifest update cannot be prepared."""


class ManifestMergeConflict(ManifestUpdateError):
    """A workspace and template made different edits to the same field."""

    def __init__(self, fields: list[str]) -> None:
        self.fields = fields
        formatted = ", ".join(fields)
        super().__init__(f"Competing edits in {MANIFEST_FILE}: {formatted}")


@dataclass(frozen=True)
class ManifestUpdatePlan:
    """The fully checked merge and the exact revision Copier must use."""

    target_ref: str
    manifest: dict[str, Any]
    source_manifest_bytes: bytes


def prepare_manifest_update(project_path: Path, old_revision: str) -> ManifestUpdatePlan:
    """Render both template baselines without running Copier copy/update tasks."""

    try:
        # Worker is Copier's renderer and revision resolver. We only inspect its
        # contexts and Jinja environment; no copy/update operation is executed.
        from copier._main import Worker
    except ImportError as exc:  # pragma: no cover - Copier is a package dependency
        raise ManifestUpdateError("Copier is required to prepare a manifest update.") from exc

    current_manifest, source_manifest_bytes = read_workspace_manifest(
        project_path / MANIFEST_FILE, "workspace"
    )

    try:
        with tempfile.TemporaryDirectory(prefix="prism-manifest-render-") as temp_dir:
            isolated_project = Path(temp_dir)
            shutil.copyfile(project_path / COPIER_ANSWERS_FILE, isolated_project / COPIER_ANSWERS_FILE)
            with Worker(
                dst_path=isolated_project,
                defaults=True,
                skip_tasks=True,
                unsafe=True,
                quiet=True,
            ) as latest_worker:
                latest_worker._ask()
                target_ref = latest_worker.template.commit_hash
                if not target_ref:
                    raise ManifestUpdateError("Copier could not resolve a versioned template revision.")
                latest_manifest = render_template_manifest(latest_worker)

            with Worker(
                dst_path=isolated_project,
                vcs_ref=old_revision,
                defaults=True,
                skip_tasks=True,
                unsafe=True,
                quiet=True,
            ) as previous_worker:
                previous_worker._ask()
                previous_manifest = render_template_manifest(previous_worker)
    except ManifestUpdateError:
        raise
    except Exception as exc:
        raise ManifestUpdateError(f"Unable to render the saved and selected template manifests: {exc}") from exc

    for label, manifest in (
        ("saved template", previous_manifest),
        ("selected template", latest_manifest),
    ):
        validate_manifest_shape(manifest, label)

    manifest = merge_workspace_manifest(previous_manifest, current_manifest, latest_manifest)
    return ManifestUpdatePlan(
        target_ref=target_ref,
        manifest=manifest,
        source_manifest_bytes=source_manifest_bytes,
    )


def load_workspace_manifest(path: Path, label: str = "workspace") -> dict[str, Any]:
    """Read a manifest and fail before update if it is malformed or conflicted."""

    try:
        manifest, _source_bytes = read_workspace_manifest(path, label)
        return manifest
    except (OSError, UnicodeError) as exc:
        raise ManifestUpdateError(f"Unable to read {path.name}: {exc}") from exc


def read_workspace_manifest(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    try:
        source_bytes = path.read_bytes()
        source = source_bytes.decode("utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise ManifestUpdateError(f"Unable to read {path.name}: {exc}") from exc

    if any(marker in source for marker in ("<<<<<<<", "=======", ">>>>>>>")):
        raise ManifestUpdateError(f"{path.name} contains unresolved conflict markers; repair it before updating.")

    try:
        manifest = yaml.safe_load(source)
    except (yaml.YAMLError, ValueError, OverflowError) as exc:
        raise ManifestUpdateError(f"{path.name} contains invalid YAML: {exc}") from exc

    validate_manifest_shape(manifest, label)
    # The apps and repositories must be valid before they are merged.
    _model, diagnostics = normalize_manifest(manifest, path=path)
    problems = sorted({item.code for item in diagnostics if item.severity == "error"})
    if problems:
        raise ManifestUpdateError(
            f"The {label} {MANIFEST_FILE} has invalid repository or app declarations ({', '.join(problems)}); fix them before updating."
        )
    return manifest, source_bytes


def validate_manifest_shape(manifest: Any, label: str) -> None:
    if not isinstance(manifest, dict):
        raise ManifestUpdateError(f"The {label} {MANIFEST_FILE} must be a mapping.")
    schema_version = manifest.get("schema_version")
    if type(schema_version) is not int or schema_version != MANIFEST_SCHEMA_VERSION:
        raise ManifestUpdateError(
            f"The {label} {MANIFEST_FILE} uses unsupported schema_version {schema_version!r}; "
            f"this CLI supports schema_version {MANIFEST_SCHEMA_VERSION}."
        )
    validate_string_mapping_keys(manifest, label, ())


def validate_string_mapping_keys(value: Any, label: str, path: tuple[str, ...]) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if not isinstance(key, str):
                location = ".".join(path) or "<root>"
                raise ManifestUpdateError(
                    f"The {label} {MANIFEST_FILE} has a non-string mapping key at {location}: {key!r}."
                )
            validate_string_mapping_keys(nested, label, path + (key,))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            validate_string_mapping_keys(nested, label, path + (f"[{index}]",))


def render_template_manifest(worker: Any) -> dict[str, Any]:
    """Render only the manifest with Copier's context; never run template tasks."""

    subdirectory = worker.template.subdirectory.strip("/\\")
    template_name = f"{subdirectory}/{MANIFEST_FILE}{worker.template.templates_suffix}" if subdirectory else f"{MANIFEST_FILE}{worker.template.templates_suffix}"
    try:
        rendered = worker.jinja_env.get_template(template_name).render(**worker._render_context())
    except Exception as exc:
        raise ManifestUpdateError(f"Unable to render {MANIFEST_FILE} from the template: {exc}") from exc
    try:
        manifest = yaml.safe_load(rendered)
    except (yaml.YAMLError, ValueError, OverflowError) as exc:
        raise ManifestUpdateError(f"The template rendered invalid YAML in {MANIFEST_FILE}: {exc}") from exc
    validate_manifest_shape(manifest, "template")
    return manifest


def merge_workspace_manifest(
    previous: dict[str, Any], current: dict[str, Any], latest: dict[str, Any]
) -> dict[str, Any]:
    """Apply template-only edits, preserve workspace-only edits, and report conflicts."""

    for label, manifest in (
        ("saved template", previous),
        ("workspace", current),
        ("selected template", latest),
    ):
        validate_manifest_shape(manifest, label)

    previous_clean = remove_cli_provenance(previous)
    current_clean = remove_cli_provenance(current)
    latest_clean = remove_cli_provenance(latest)
    conflicts: list[str] = []
    merged = _merge_value(previous_clean, current_clean, latest_clean, (), conflicts)
    if conflicts:
        raise ManifestMergeConflict(conflicts)
    if not isinstance(merged, dict):  # root manifests are checked above
        raise ManifestUpdateError(f"The merged {MANIFEST_FILE} is not a mapping.")
    return merged


def remove_cli_provenance(manifest: dict[str, Any]) -> dict[str, Any]:
    """Remove volatile fields owned by Prism while retaining custom provenance."""

    clean = deepcopy(manifest)
    generated_by = clean.get("generated_by")
    if isinstance(generated_by, dict):
        for key in _PROVENANCE_KEYS:
            generated_by.pop(key, None)
        if not generated_by:
            clean.pop("generated_by", None)
    return clean


def _merge_value(
    previous: Any,
    current: Any,
    latest: Any,
    path: tuple[str, ...],
    conflicts: list[str],
) -> Any:
    if current == previous:
        return _copy_value(latest)
    if latest == previous or current == latest:
        return _copy_value(current)

    if (
        isinstance(current, Mapping)
        and isinstance(latest, Mapping)
        and (isinstance(previous, Mapping) or previous is _MISSING)
    ):
        previous_map = previous if isinstance(previous, Mapping) else {}
        keys = set(previous_map) | set(current) | set(latest)
        result: dict[str, Any] = {}
        for key in sorted(keys):
            base_value = previous_map.get(key, _MISSING)
            current_value = current.get(key, _MISSING)
            latest_value = latest.get(key, _MISSING)
            value = _merge_value(base_value, current_value, latest_value, path + (str(key),), conflicts)
            if value is not _MISSING:
                result[key] = value
        return result

    conflicts.append(".".join(path) or "<root>")
    return _copy_value(current)


def _copy_value(value: Any) -> Any:
    return _MISSING if value is _MISSING else deepcopy(value)
