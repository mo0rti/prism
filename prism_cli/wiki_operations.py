"""The status board's derived views: the feature columns, the Bugs table and the Operations table (CONTRACTS 8.2).

`status-board.md` holds three tables. The feature table has one row per feature; its `Design tracks`, `App stages` and `Open
bugs` cells are derived from the feature page and the bug pages. The `## Bugs` table lists the bugs that are not `released` or
`closed`. The `## Operations` table has one row per app that has anything to show: its released features, the latest release
record that names it and that record's outcome for it, its open bugs and its open incidents. A row for an app with nothing to
show is left out, so a new workspace starts with empty tables.

This module reads and writes the text of the two tables and derives every cell from the pages. The board service writes the rows
with each operation that changes their inputs; wiki lint derives the same rows from the pages and compares them with the file.
Nothing here reads a file: the callers pass the pages in.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from prism_cli.wiki_bugs import ACTIVE_BUG_STATUSES, BugPage
from prism_cli.wiki_incidents import IncidentPage, incident_sort_key
from prism_cli.wiki_model import parse_design_tracks
from prism_cli.wiki_releases import ReleaseRecord, latest_record

EMPTY_CELL = "—"
BUGS_HEADING = "Bugs"
OPERATIONS_HEADING = "Operations"
BUG_TABLE_COLUMNS = ("ID", "Bug", "Status", "Owner", "Apps", "Feature", "Blocking")
OPERATIONS_TABLE_COLUMNS = (
    "App",
    "Delivery target",
    "Released features",
    "Latest release",
    "Latest attempt outcome",
    "Open bugs",
    "Open incidents",
)
# The row keys of a bug row and of an operations row, in column order.
BUG_ROW_KEYS = ("id", "title", "status", "owner", "apps", "feature", "blocking")
OPERATION_ROW_KEYS = ("app", "delivery_target", "released_features", "latest_release", "latest_outcome", "open_bugs", "open_incidents")
# The cells of an operations row that the pages decide. The delivery target comes from `SETTINGS.md`, which a person edits by
# hand, so lint does not compare it: the next write that changes the row refreshes it.
OPERATION_COMPARED_KEYS = tuple(key for key in OPERATION_ROW_KEYS if key != "delivery_target")
# The keys of a board row in the merge: `F-001` for a feature, `BUG-001` for a bug and `app:<id>` for an app.
APP_KEY_PREFIX = "app:"
_FEATURE_KEY = re.compile(r"^F-\d+$", re.IGNORECASE)
_BUG_KEY = re.compile(r"^BUG-\d+$")
_ID_NUMBER = re.compile(r"(\d+)$")


def row_kind(key: str) -> str:
    """The table a row key belongs to: `feature`, `bug` or `operation`."""

    if key.startswith(APP_KEY_PREFIX):
        return "operation"
    if _BUG_KEY.match(key):
        return "bug"
    return "feature"


def operation_key(app_id: str) -> str:
    return APP_KEY_PREFIX + app_id


def _id_number(identifier: str) -> int:
    match = _ID_NUMBER.search(identifier)
    return int(match.group(1)) if match else 10**9


def sorted_ids(identifiers: Iterable[str]) -> list[str]:
    """Identifiers such as `BUG-002` and `F-010` in number order, each once."""

    return sorted(dict.fromkeys(identifiers), key=lambda item: (_id_number(item), item))


def ids_text(identifiers: Iterable[str]) -> str:
    """A cell that lists identifiers: `BUG-001, BUG-004`, or `—`."""

    ordered = sorted_ids(identifiers)
    return ", ".join(ordered) if ordered else EMPTY_CELL


def cell_ids(cell: str) -> list[str]:
    """The identifiers a list cell names, in order."""

    return [] if cell.strip() in {"", EMPTY_CELL} else [item.strip() for item in cell.split(",") if item.strip()]


def cell_text(value: str) -> str:
    """A value as one table cell: one line, with `|` written as an entity."""

    return re.sub(r"\s+", " ", value).strip().replace("|", "&#124;")


# --- Feature columns -----------------------------------------------------------------------------------------------


def design_tracks_text(frontmatter: Mapping[str, Any]) -> str:
    """The `Design tracks` cell: `ui: <state>; technical: <state>`, or `—` before design starts or when the tracks are malformed."""

    tracks, _problems = parse_design_tracks(frontmatter)
    return EMPTY_CELL if tracks is None else f"ui: {tracks.ui}; technical: {tracks.technical}"


def parse_app_stages_cell(cell: str) -> dict[str, str]:
    """The `app: stage` pairs of an `App stages` cell, in order."""

    stages: dict[str, str] = {}
    for part in cell.split(";"):
        app, separator, stage = part.partition(":")
        if separator and app.strip() and stage.strip():
            stages[app.strip()] = stage.strip()
    return stages


# --- Bugs table ----------------------------------------------------------------------------------------------------


def bug_is_open(bug: BugPage) -> bool:
    return bug.status in ACTIVE_BUG_STATUSES


def bug_board_row(bug: BugPage) -> dict[str, str] | None:
    """The Bugs-table row of a bug, or ``None`` for a bug that is `released` or `closed` (it leaves the table)."""

    if not bug_is_open(bug):
        return None
    return {
        "id": bug.bug_id,
        "title": cell_text(bug.title),
        "status": bug.status or EMPTY_CELL,
        "owner": bug.owner or EMPTY_CELL,
        "apps": ", ".join(bug.apps) or EMPTY_CELL,
        "feature": bug.feature or "none",
        "blocking": "yes" if bug.blocking else "no",
    }


def open_bugs_of_feature(feature_id: str, bug_rows: Iterable[Mapping[str, str]]) -> list[str]:
    """The IDs of the open bugs linked to a feature, from Bugs-table rows."""

    wanted = feature_id.strip().casefold()
    return [row["id"] for row in bug_rows if row["feature"].strip().casefold() == wanted]


def open_bugs_of_app(app_id: str, bug_rows: Iterable[Mapping[str, str]]) -> list[str]:
    """The IDs of the open bugs that name an app, from Bugs-table rows."""

    return [row["id"] for row in bug_rows if app_id in cell_ids(row["apps"])]


# --- Operations table ----------------------------------------------------------------------------------------------


def released_features_of_app(app_id: str, feature_stage_cells: Mapping[str, str]) -> list[str]:
    """The features whose `App stages` cell shows the app as `released`. `feature_stage_cells` maps a feature ID to its cell."""

    return [feature for feature, cell in feature_stage_cells.items() if parse_app_stages_cell(cell).get(app_id) == "released"]


def open_incidents_of_app(app_id: str, incidents: Iterable[IncidentPage]) -> list[str]:
    """The IDs of the incidents that name the app and are not `resolved`."""

    return [incident.incident_id for incident in incidents if incident.open and app_id in incident.apps]


def operation_row(
    app_id: str,
    *,
    delivery_target: str | None,
    feature_stage_cells: Mapping[str, str],
    bug_rows: Iterable[Mapping[str, str]],
    incidents: Iterable[IncidentPage],
    releases: Iterable[ReleaseRecord],
) -> dict[str, str] | None:
    """The Operations-table row of an app, or ``None`` when the app has nothing to show."""

    released = released_features_of_app(app_id, feature_stage_cells)
    latest = latest_record(releases, app_id)
    bugs = open_bugs_of_app(app_id, bug_rows)
    open_incidents = open_incidents_of_app(app_id, incidents)
    if not (released or latest or bugs or open_incidents):
        return None
    return {
        "app": app_id,
        "delivery_target": delivery_target or EMPTY_CELL,
        "released_features": ids_text(released),
        "latest_release": latest.record_id if latest is not None else EMPTY_CELL,
        "latest_outcome": (latest.outcome_for(app_id) or EMPTY_CELL) if latest is not None else EMPTY_CELL,
        "open_bugs": ids_text(bugs),
        "open_incidents": ids_text(sorted(open_incidents, key=incident_sort_key)),
    }


def operation_rows_match(expected: Mapping[str, str] | None, actual: Mapping[str, str] | None) -> bool:
    """Whether two operations rows agree on every cell the pages decide (both absent also agree)."""

    if expected is None or actual is None:
        return expected is None and actual is None
    return all(expected[key] == actual[key] for key in OPERATION_COMPARED_KEYS)


# --- Reading and writing the two tables ----------------------------------------------------------------------------


@dataclass
class BoardViews:
    """The Bugs and Operations tables of a `status-board.md`, keyed by bug ID and by app ID."""

    bugs: dict[str, dict[str, str]] = field(default_factory=dict)
    operations: dict[str, dict[str, str]] = field(default_factory=dict)
    has_bugs_table: bool = False
    has_operations_table: bool = False
    errors: list[str] = field(default_factory=list)


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _is_separator(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-+:?", cell) for cell in cells if cell) and any(cells)


def read_board_views(text: str) -> BoardViews:
    """The Bugs and Operations tables of a status board; a table the file lacks is absent, and a malformed row is an error."""

    views = BoardViews()
    current: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith("|"):
            current = None
            continue
        cells = _cells(line)
        if tuple(cells) == BUG_TABLE_COLUMNS:
            current, views.has_bugs_table = "bugs", True
            continue
        if tuple(cells) == OPERATIONS_TABLE_COLUMNS:
            current, views.has_operations_table = "operations", True
            continue
        if current is None or _is_separator(cells):
            continue
        keys = BUG_ROW_KEYS if current == "bugs" else OPERATION_ROW_KEYS
        label = "Bugs" if current == "bugs" else "Operations"
        if len(cells) != len(keys):
            views.errors.append(f"status-board.md contains a {label} row with {len(cells)} cells; the table has {len(keys)} columns.")
            continue
        row = dict(zip(keys, cells))
        key = row["id"] if current == "bugs" else row["app"]
        if not key:
            views.errors.append(f"status-board.md contains a {label} row with an empty key.")
            continue
        (views.bugs if current == "bugs" else views.operations)[key] = row
    return views


def format_bug_row(row: Mapping[str, str]) -> str:
    return "| " + " | ".join(row[key] for key in BUG_ROW_KEYS) + " |"


def format_operation_row(row: Mapping[str, str]) -> str:
    return "| " + " | ".join(row[key] for key in OPERATION_ROW_KEYS) + " |"


def table_text(heading: str, columns: tuple[str, ...], rows: Iterable[str], newline: str = "\n") -> str:
    """A `## heading` section with its header, its separator and `rows`."""

    separator = "|" + "|".join("-" * (len(column) + 2) for column in columns) + "|"
    lines = [f"## {heading}", "", "| " + " | ".join(columns) + " |", separator, *rows]
    return newline.join(lines) + newline
