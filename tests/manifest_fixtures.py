"""Version-2 manifest text and data for tests that need a workspace manifest."""

from __future__ import annotations

from typing import Any, Iterable

import yaml

from prism_cli.app_model import apps_from_platforms


def manifest_data(name: str = "Prism App", platforms: Iterable[str] = ("backend",), **project: Any) -> dict[str, Any]:
    """A version-2 manifest whose apps are the given generated platforms, with ``project`` fields added."""

    return {
        "schema_version": 2,
        "project": {"name": name, **project},
        "apps": apps_from_platforms(list(platforms)),
    }


def manifest_text(name: str = "Prism App", platforms: Iterable[str] = ("backend",), **project: Any) -> str:
    return yaml.safe_dump(manifest_data(name, platforms, **project), sort_keys=False)
