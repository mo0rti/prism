"""The status-board half of the board service: which rows an operation changes (CONTRACTS 8.2).

`StatusBoardMixin` is mixed into `BoardService`. An operation that writes a feature, bug, incident or release page changes
cells of `status-board.md`: the feature's own row, the open bugs of the features its bugs name, the bug row, and the
Operations row of every app whose released features, open bugs, open incidents or latest release moved. This module works out
the rows before and after the operation from the pages it writes and the board it reads; the service writes them as keyed
rows of the managed status-board merge, so two operations that touch different rows never conflict.

Like `board_bugs`, it reaches the helpers of `board_service` through `bs`, which resolves them when a method runs.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from prism_cli.board_bugs import bs, is_bug_path
from prism_cli.wiki_bugs import BugPage
from prism_cli.wiki_incidents import IncidentPage, is_incident_path, read_incident_pages
from prism_cli.wiki_model import load_markdown_page, parse_markdown_text, read_wiki_settings
from prism_cli.wiki_operations import (
    bug_board_row,
    cell_ids,
    ids_text,
    open_bugs_of_feature,
    operation_key,
    operation_row,
    operation_rows_match,
    parse_app_stages_cell,
    read_board_views,
    row_kind,
)
from prism_cli.wiki_releases import RELEASE_DIRECTORY, ReleaseRecord, read_release_records

_FEATURE_PREFIX = "knowledge/wiki/features/"
_RELEASE_PREFIX = f"knowledge/wiki/{RELEASE_DIRECTORY}/"


class StatusBoardMixin:
    """Which status-board rows an operation changes, and how to read one row back."""

    # -- reading ---------------------------------------------------------------------------------------------------------

    def _board_text(self) -> str:
        return self._read_text(self._safe_path(bs._STATUS_BOARD_PATH))  # type: ignore[attr-defined]

    def _board_row(self, key: str) -> dict[str, str] | None:
        """The row of a status-board key as the board holds it now: a feature (`F-001`), a bug (`BUG-001`) or an app (`app:<id>`)."""

        kind = row_kind(key)
        if kind == "feature":
            return self._status_existing_row(key)  # type: ignore[attr-defined]
        views = read_board_views(self._board_text())
        return views.bugs.get(key) if kind == "bug" else views.operations.get(key[len("app:"):])

    # -- the rows an operation changes -----------------------------------------------------------------------------------

    def _status_board_changes(self, overlay: Mapping[str, str]) -> tuple[dict[str, Any], dict[str, Any]]:
        """`(expected rows, after rows)` of the status board for an operation that writes the pages of `overlay`.

        `overlay` maps a workspace path to the text the operation writes. A key of the result is a feature ID, a bug ID or
        `app:<id>`; an expected value is the row on the board now (``None`` when it has none), and an after value is the row the
        operation leaves (``None`` for a row that leaves the board). Only rows that change appear.
        """

        wiki: Path = self.root / "knowledge" / "wiki"  # type: ignore[attr-defined]
        model = self._model  # type: ignore[attr-defined]
        board = self._board_text()
        views = read_board_views(board)
        features_now = {row["id"].casefold(): row for row in self._feature_board_rows(board)}
        expected: dict[str, Any] = {}
        after: dict[str, Any] = {}
        touched_features: set[str] = set()
        touched_apps: set[str] = set()

        # The bugs first: the open bugs of a feature, and of an app, are read from the bug rows the operation leaves.
        bug_rows = dict(views.bugs)
        for relative, text in sorted(overlay.items()):
            if not is_bug_path(relative):
                continue
            bug = BugPage(parse_markdown_text(wiki / "bugs" / PurePosixPath(relative).name, text))
            old, new = views.bugs.get(bug.bug_id), bug_board_row(bug)
            if old == new:
                continue
            expected[bug.bug_id], after[bug.bug_id] = old, new
            if new is None:
                bug_rows.pop(bug.bug_id, None)
            else:
                bug_rows[bug.bug_id] = new
            for row in (old, new):
                if row is not None:
                    touched_features.add(row["feature"].casefold())
            old_apps = set(cell_ids(old["apps"])) if old else set()
            new_apps = set(cell_ids(new["apps"])) if new else set()
            touched_apps |= (old_apps ^ new_apps) if old and new else (old_apps | new_apps)

        # The features the operation writes: their row follows the page, with the open bugs the bug rows leave.
        feature_rows = dict(features_now)
        for relative, text in sorted(overlay.items()):
            if not relative.startswith(_FEATURE_PREFIX):
                continue
            frontmatter, body = bs._parse_markdown(text, relative)
            feature_id = str(frontmatter.get("id", ""))
            row = bs._status_row(frontmatter, body, model, ids_text(open_bugs_of_feature(feature_id, bug_rows.values())))
            existing = features_now.get(feature_id.casefold())
            feature_rows[feature_id.casefold()] = row
            if existing != row:
                expected[feature_id], after[feature_id] = existing, row
            old_released = _released_apps(existing["app_stages"]) if existing else set()
            touched_apps |= old_released ^ _released_apps(row["app_stages"])
        # A feature whose page is not written but whose bugs moved changes only its `Open bugs` cell.
        for feature_key in sorted(touched_features):
            current = feature_rows.get(feature_key)
            if current is None:
                continue
            row = {**current, "open_bugs": ids_text(open_bugs_of_feature(current["id"], bug_rows.values()))}
            if row != current:
                expected[current["id"]], after[current["id"]] = features_now.get(feature_key), row
                feature_rows[feature_key] = row

        # The incidents and release records the operation writes name apps whose Operations row follows them.
        incidents = self._incident_pages_with(overlay)
        releases = self._release_records_with(overlay)
        for relative, text in sorted(overlay.items()):
            if is_incident_path(relative):
                new_incident = IncidentPage(parse_markdown_text(wiki / "incidents" / PurePosixPath(relative).name, text))
                old_page = wiki / "incidents" / PurePosixPath(relative).name
                old_incident = IncidentPage(load_markdown_page(old_page)) if old_page.is_file() else None
                if old_incident is None or old_incident.open != new_incident.open or old_incident.apps != new_incident.apps:
                    touched_apps |= set(new_incident.apps) | (set(old_incident.apps) if old_incident is not None else set())
            elif relative.startswith(_RELEASE_PREFIX):
                record = ReleaseRecord(parse_markdown_text(wiki / RELEASE_DIRECTORY / PurePosixPath(relative).name, text))
                touched_apps |= set(record.apps)

        touched_apps = {app for app in touched_apps if model is None or model.app(app) is not None}
        if touched_apps:
            targets = self._delivery_targets(wiki)
            stage_cells = {row["id"]: row["app_stages"] for row in feature_rows.values()}
            for app in sorted(touched_apps):
                old = views.operations.get(app)
                new = operation_row(
                    app,
                    delivery_target=targets.get(app),
                    feature_stage_cells=stage_cells,
                    bug_rows=bug_rows.values(),
                    incidents=incidents,
                    releases=releases,
                )
                if not operation_rows_match(new, old):
                    expected[operation_key(app)], after[operation_key(app)] = old, new
        return expected, after

    @staticmethod
    def _feature_board_rows(board: str) -> list[dict[str, str]]:
        rows = []
        for line in board.splitlines():
            match = bs._STATUS_ROW.match(line)
            if match:
                rows.append(bs._status_row_from_match(match))
        return rows

    def _delivery_targets(self, wiki: Path) -> dict[str, str]:
        """The delivery target name of each app, read leniently: a malformed SETTINGS.md leaves a cell empty and refuses nothing."""

        try:
            settings = read_wiki_settings(wiki, self._model)  # type: ignore[attr-defined]
        except (OSError, ValueError):
            return {}
        return {app: str(entry["target"]) for app, entry in settings.delivery_targets.items()}

    def _incident_pages_with(self, overlay: Mapping[str, str]) -> list[IncidentPage]:
        """The incident pages as they would be once the operation applies: the pages on disk, the operation's pages in their place."""

        wiki: Path = self.root / "knowledge" / "wiki"  # type: ignore[attr-defined]
        pages = {incident.page.path.name: incident for incident in read_incident_pages(wiki)}
        for relative, text in overlay.items():
            if is_incident_path(relative):
                name = PurePosixPath(relative).name
                pages[name] = IncidentPage(parse_markdown_text(wiki / "incidents" / name, text))
        return [pages[name] for name in sorted(pages)]

    def _release_records_with(self, overlay: Mapping[str, str]) -> list[ReleaseRecord]:
        """The release records as they would be once the operation applies."""

        wiki: Path = self.root / "knowledge" / "wiki"  # type: ignore[attr-defined]
        records = {record.page.path.name: record for record in read_release_records(wiki)}
        for relative, text in overlay.items():
            if relative.startswith(_RELEASE_PREFIX):
                name = PurePosixPath(relative).name
                records[name] = ReleaseRecord(parse_markdown_text(wiki / RELEASE_DIRECTORY / name, text))
        return sorted(records.values(), key=lambda record: (record.number is None, record.number or 0, record.page.path.name))


def _released_apps(app_stages_cell: str) -> set[str]:
    return {app for app, stage in parse_app_stages_cell(app_stages_cell).items() if stage == "released"}
