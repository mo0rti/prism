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
    # Prevent closing tags and HTML tokenizer escape states inside script data.
    return json.dumps(payload).replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")


def render_html(envelope: dict[str, Any], mode: str = "snapshot", generated_at: str | None = None) -> str:
    template = _asset_text("graph_template.html")
    vendor = "/*\n" + _asset_text("force-graph.LICENSE.txt") + "\n*/\n" + _asset_text("force-graph.min.js")
    config = {
        "mode": mode,
        "generated_at": generated_at or datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    return (
        template.replace(VENDOR_PLACEHOLDER, vendor)
        .replace(CONFIG_PLACEHOLDER, _embed_json(config))
        # Replace data last so a literal placeholder in a wiki title/body
        # stays data and cannot be interpreted as a template directive.
        .replace(DATA_PLACEHOLDER, _embed_json(envelope))
    )


def write_dashboard(envelope: dict[str, Any], out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_html(envelope), encoding="utf-8")
    return out_path
