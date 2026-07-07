"""Render the interactive wiki-graph dashboard as a single self-contained HTML file."""

from __future__ import annotations

import json
from datetime import datetime
from importlib import resources
from pathlib import Path
from typing import Any


DATA_PLACEHOLDER = "/*__PRISM_GRAPH_DATA__*/"
CONFIG_PLACEHOLDER = "/*__PRISM_CONFIG__*/"
VENDOR_PLACEHOLDER = "/*__PRISM_VENDOR_JS__*/"


def _asset_text(name: str) -> str:
    return (resources.files("prism_cli") / "assets" / name).read_text(encoding="utf-8")


def _embed_json(payload: Any) -> str:
    # `</` would terminate the surrounding <script> tag; escape it inside JSON strings.
    return json.dumps(payload).replace("</", "<\\/")


def render_html(envelope: dict[str, Any], mode: str = "snapshot", generated_at: str | None = None) -> str:
    template = _asset_text("graph_template.html")
    vendor = _asset_text("force-graph.min.js")
    config = {
        "mode": mode,
        "generated_at": generated_at or datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    return (
        template.replace(VENDOR_PLACEHOLDER, vendor)
        .replace(DATA_PLACEHOLDER, _embed_json(envelope))
        .replace(CONFIG_PLACEHOLDER, _embed_json(config))
    )


def write_dashboard(envelope: dict[str, Any], out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_html(envelope), encoding="utf-8")
    return out_path
