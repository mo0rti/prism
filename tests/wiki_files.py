"""Write the two wiki index files that test workspaces need: the general index and the status board.

`write_index` builds the general index of the pages on disk with the same line derivation the board
service uses, so a fixture workspace is lint-clean without hand-written index lines.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from jinja2 import Environment, StrictUndefined

from prism_cli.wiki_index import build_index

TEMPLATE_KNOWLEDGE = Path(__file__).resolve().parents[1] / "template" / "knowledge"


def render_template_text(source: str, **context: Any) -> str:
    """Render one template file the way Copier does, with only the given answers (none: the workflow-only form)."""

    return Environment(undefined=StrictUndefined, autoescape=False, keep_trailing_newline=True).from_string(source).render(**context)


def copy_template_knowledge(destination: Path, **context: Any) -> None:
    """Copy `template/knowledge` to `destination`, rendering each `.jinja` file and dropping its suffix.

    With no context the copy is the workflow-only form that `prism workflow install` writes; with
    ``apps=[...]`` it is the form a generated workspace gets.
    """

    shutil.copytree(TEMPLATE_KNOWLEDGE, destination, ignore=shutil.ignore_patterns("*.jinja"))
    for source in sorted(TEMPLATE_KNOWLEDGE.rglob("*.jinja")):
        target = destination / source.relative_to(TEMPLATE_KNOWLEDGE).with_suffix("")
        target.write_text(render_template_text(source.read_text(encoding="utf-8"), **context), encoding="utf-8", newline="\n")

STATUS_BOARD_HEADER = (
    "# Feature Status Board\n\n"
    "| ID | Feature | Status | Owner | Board Review |\n"
    "|----|---------|--------|-------|--------------|\n"
)


def index_text(wiki_root: Path) -> str:
    """The general index of the pages under `wiki_root`: one line per page, grouped by kind."""

    return build_index(wiki_root)


def write_index(root: Path) -> None:
    """Write `knowledge/wiki/index.md` under the workspace `root`, listing every page that exists now."""

    wiki_root = root / "knowledge" / "wiki"
    wiki_root.mkdir(parents=True, exist_ok=True)
    (wiki_root / "index.md").write_text(index_text(wiki_root), encoding="utf-8", newline="\n")


def write_status_board(root: Path, rows: str = "") -> None:
    """Write `knowledge/wiki/status-board.md` under the workspace `root` with the given table rows."""

    wiki_root = root / "knowledge" / "wiki"
    wiki_root.mkdir(parents=True, exist_ok=True)
    (wiki_root / "status-board.md").write_text(STATUS_BOARD_HEADER + rows, encoding="utf-8", newline="\n")
