"""Write the two wiki index files that test workspaces need: the general index and the status board.

`write_index` builds the general index of the pages on disk with the same line derivation the board
service uses, so a fixture workspace is lint-clean without hand-written index lines.
"""

from __future__ import annotations

from pathlib import Path

from prism_cli.wiki_index import build_index

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
