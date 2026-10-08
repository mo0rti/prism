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
    "| ID | Feature | Status | Owner | Board Review | Design tracks | App stages | Open bugs |\n"
    "|----|---------|--------|-------|--------------|---------------|------------|-----------|\n"
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
    """Write `knowledge/wiki/status-board.md` under the workspace `root` with the given table rows.

    A row of five cells (ID to Board Review) is completed with the three columns the board derives: `Design tracks` and
    `App stages` follow the feature page on disk and `Open bugs` follows the bug pages. The Bugs and Operations tables are
    added, from the bug, incident and release pages on disk, when they have rows.
    """

    wiki_root = root / "knowledge" / "wiki"
    wiki_root.mkdir(parents=True, exist_ok=True)
    text = STATUS_BOARD_HEADER + _complete_rows(root, rows) + _view_tables(root)
    (wiki_root / "status-board.md").write_text(text, encoding="utf-8", newline="\n")


def _view_tables(root: Path) -> str:
    """The Bugs and Operations tables of the pages on disk, each only when it has rows."""

    from prism_cli.wiki_bugs import read_bug_pages
    from prism_cli.wiki_incidents import read_incident_pages
    from prism_cli.wiki_model import app_stages_text, read_feature_pages, read_release_records
    from prism_cli.wiki_operations import (
        BUG_TABLE_COLUMNS,
        BUGS_HEADING,
        OPERATIONS_HEADING,
        OPERATIONS_TABLE_COLUMNS,
        bug_board_row,
        format_bug_row,
        format_operation_row,
        operation_row,
        table_text,
    )
    from prism_cli.workspace import inspect_workspace

    wiki_root = root / "knowledge" / "wiki"
    bug_rows = [row for bug in read_bug_pages(wiki_root) if (row := bug_board_row(bug)) is not None]
    model = inspect_workspace(root).model
    cells = {page.feature_id: app_stages_text(page.status, page.apps, page.page.body, model) for page in read_feature_pages(wiki_root)}
    incidents, releases = read_incident_pages(wiki_root), read_release_records(wiki_root)
    operations = [
        row
        for app in model.apps
        if (row := operation_row(app.id, delivery_target=None, feature_stage_cells=cells, bug_rows=bug_rows, incidents=incidents, releases=releases))
        is not None
    ]
    text = ""
    if bug_rows:
        text += "\n" + table_text(BUGS_HEADING, BUG_TABLE_COLUMNS, [format_bug_row(row) for row in sorted(bug_rows, key=lambda item: item["id"])])
    if operations:
        text += "\n" + table_text(OPERATIONS_HEADING, OPERATIONS_TABLE_COLUMNS, [format_operation_row(row) for row in operations])
    return text


def _complete_rows(root: Path, rows: str) -> str:
    from prism_cli.wiki_bugs import read_bug_pages
    from prism_cli.wiki_model import app_stages_text, read_feature_pages
    from prism_cli.wiki_operations import bug_board_row, design_tracks_text, ids_text, open_bugs_of_feature
    from prism_cli.workspace import inspect_workspace

    wiki_root = root / "knowledge" / "wiki"
    pages = {page.feature_id.casefold(): page for page in read_feature_pages(wiki_root)}
    bug_rows = [row for bug in read_bug_pages(wiki_root) if (row := bug_board_row(bug)) is not None]
    model = None
    completed: list[str] = []
    for line in rows.splitlines(keepends=True):
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if line.strip().startswith("|") and len(cells) == 5 and cells[0].upper().startswith("F-"):
            page = pages.get(cells[0].casefold())
            stages, tracks, bugs = "—", "—", "—"
            if page is not None:
                if model is None:
                    model = inspect_workspace(root).model
                stages = app_stages_text(page.status, page.apps, page.page.body, model)
                tracks = design_tracks_text(page.page.frontmatter)
                bugs = ids_text(open_bugs_of_feature(page.feature_id, bug_rows))
            ending = "\n" if line.endswith("\n") else ""
            line = "| " + " | ".join([*cells, tracks, stages, bugs]) + " |" + ending
        completed.append(line)
    return "".join(completed)


def evidence_tables(
    apps: list[str],
    *,
    stage: str = "released",
    feature_id: str = "F-001",
    criterion: str = "The summary includes the payout period.",
    skip: tuple[str, ...] = (),
) -> str:
    """The three evidence tables of a feature whose `apps` are all at `stage`, each app citing criterion AC-1.

    The criterion is the one the fixtures write: `AC-1 [<apps>] <criterion>` with no evidence label. `stage` is
    `ready-for-qa` (delivery rows), `in-qa` (plus a passing QA row per app), `ready-for-release` (plus a pending
    Release row) or `released` (a released Release row). Apps named in `skip` get no rows.
    """

    from prism_cli.wiki_model import criterion_revision

    revision = criterion_revision(feature_id, 1, apps, False, "", criterion)
    delivery = ["## Delivery evidence", "| App | Artifact | Contract | Implementation | Tests | Basis |", "|---|---|---|---|---|---|"]
    qa = ["## QA verification", "| Row | Criteria | Method | Artifact | Environment | Attempt | Result | Evidence | Basis |", "|---|---|---|---|---|---|---|---|---|"]
    release = ["## Release", "| App | Target | Version | Attempt | Outcome | Record | Basis |", "|---|---|---|---|---|---|---|"]
    levels = ("ready-for-qa", "in-qa", "ready-for-release", "released")
    level = levels.index(stage)
    for app in apps:
        if app in skip:
            continue
        artifact = f"build:{app}#1"
        delivery.append(f"| {app} | `{artifact}` | none | [PR 1](https://git.example/acme/pull/1) | `./run-tests`: passed | checked |")
        if level >= 1:
            qa.append(f"| {app} | AC-1@{revision} | automated | `{artifact}` | ci | qa-1 | pass | [run](https://ci.example/1) | checked |")
        if level == 2:
            release.append(f"| {app} | — | `{artifact}` | release-1 | pending | — | — |")
        if level == 3:
            release.append(f"| {app} | production | `{artifact}` | release-1 | released | [REL-001](https://records.example/REL-001) | checked |")
    return "\n\n".join("\n".join(section) for section in (delivery, qa, release)) + "\n"


def refresh_status_board(root: Path) -> None:
    """Rewrite the whole status board of the workspace `root` from the pages on disk, as the board service leaves it.

    A test that plants a bug, incident or release page straight into the wiki (not through the service) calls this so the
    board shows what the pages say.
    """

    import re

    from prism_cli.wiki_model import read_feature_pages

    wiki_root = root / "knowledge" / "wiki"
    rows = ""
    for page in sorted(read_feature_pages(wiki_root), key=lambda item: int(re.search(r"\d+", item.feature_id).group(0))):
        frontmatter = page.page.frontmatter
        title = re.sub(r"\s+", " ", str(frontmatter.get("title", ""))).strip().replace("|", "&#124;")
        rows += f"| {page.feature_id} | {title} | {page.status} | {page.owner} | {frontmatter.get('advisory-review')} |\n"
    write_status_board(root, rows)
