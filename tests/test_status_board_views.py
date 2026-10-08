"""The status board's derived columns and tables: the feature row cells, the Bugs table and the Operations table (CONTRACTS 8.2)."""

from __future__ import annotations

import unittest
from pathlib import Path

from prism_cli.board_service import _render_status_board
from prism_cli.wiki_incidents import IncidentPage
from prism_cli.wiki_lint import lint_wiki
from prism_cli.wiki_model import ReleaseRecord, parse_markdown_text
from prism_cli.wiki_operations import (
    EMPTY_CELL,
    cell_ids,
    ids_text,
    operation_row,
    operation_rows_match,
    parse_app_stages_cell,
    read_board_views,
)
from tests import real_temp  # noqa: F401
from tests.qa_pages import bug_page
from tests.qa_support import FEATURE, QaBoard, app_row
from tests.test_incidents import incident

BOARD = "knowledge/wiki/status-board.md"
BUG = "knowledge/wiki/bugs/BUG-001-summary-export-drops-comments.md"
HEADER = (
    "# Feature Status Board\n\n| ID | Feature | Status | Owner | Board Review | Design tracks | App stages | Open bugs |\n"
    "|----|---------|--------|-------|--------------|---------------|------------|-----------|\n"
)
FEATURE_ROW = "| F-001 | Review | in-dev | dev | not-needed | — | — | — |\n"


def bug_row(bug_id: str = "BUG-001", **overrides: str) -> dict[str, str]:
    row = {"id": bug_id, "title": "Export drops comments", "status": "open", "owner": "dev", "apps": "worker", "feature": "F-001", "blocking": "yes"}
    row.update(overrides)
    return row


def op_row(app: str = "worker", **overrides: str) -> dict[str, str]:
    row = {
        "app": app,
        "delivery_target": "production",
        "released_features": "—",
        "latest_release": "—",
        "latest_outcome": "—",
        "open_bugs": "BUG-001",
        "open_incidents": "—",
    }
    row.update(overrides)
    return row


class RenderTests(unittest.TestCase):
    def test_a_bug_row_and_an_operations_row_create_their_tables_at_the_end(self) -> None:
        text = _render_status_board(HEADER + FEATURE_ROW, {}, {"BUG-001": bug_row(), "app:worker": op_row()})
        views = read_board_views(text)
        self.assertEqual(["BUG-001"], list(views.bugs))
        self.assertEqual(["worker"], list(views.operations))
        self.assertTrue(views.has_bugs_table and views.has_operations_table)
        self.assertEqual([], views.errors)
        self.assertTrue(text.startswith(HEADER + FEATURE_ROW))

    def test_rows_keep_their_place_new_rows_sort_in_and_a_none_row_leaves(self) -> None:
        text = _render_status_board(HEADER + FEATURE_ROW, {}, {"BUG-002": bug_row("BUG-002"), "BUG-010": bug_row("BUG-010"), "app:worker": op_row()})
        text = _render_status_board(text, {}, {"BUG-004": bug_row("BUG-004"), "app:api": op_row("api")})
        views = read_board_views(text)
        self.assertEqual(["BUG-002", "BUG-004", "BUG-010"], list(views.bugs))
        self.assertEqual(["api", "worker"], list(views.operations))
        text = _render_status_board(text, {}, {"BUG-004": None, "app:api": None, "BUG-002": bug_row("BUG-002", status="fixed")})
        views = read_board_views(text)
        self.assertEqual(["BUG-002", "BUG-010"], list(views.bugs))
        self.assertEqual("fixed", views.bugs["BUG-002"]["status"])
        self.assertEqual(["worker"], list(views.operations))
        # Removing the last rows leaves an empty table, and removing from a board with no table writes nothing.
        text = _render_status_board(text, {}, {"BUG-002": None, "BUG-010": None})
        self.assertEqual({}, read_board_views(text).bugs)
        self.assertEqual(HEADER + FEATURE_ROW, _render_status_board(HEADER + FEATURE_ROW, {}, {"BUG-001": None, "app:worker": None}))

    def test_a_feature_row_follows_its_key_and_a_crlf_board_keeps_its_line_endings(self) -> None:
        board = (HEADER + FEATURE_ROW).replace("\n", "\r\n")
        after = {
            "id": "F-001",
            "title": "Review",
            "status": "in-qa",
            "owner": "qa",
            "advisory_review": "not-needed",
            "design_tracks": "ui: done; technical: done",
            "app_stages": "worker: in-qa",
            "open_bugs": "BUG-001",
        }
        text = _render_status_board(board, {}, {"F-001": after, "BUG-001": bug_row()})
        self.assertEqual(text.count("\r\n"), text.count("\n"))
        self.assertIn("| F-001 | Review | in-qa | qa | not-needed | ui: done; technical: done | worker: in-qa | BUG-001 |", text)
        self.assertEqual(["BUG-001"], list(read_board_views(text).bugs))


class DerivationTests(unittest.TestCase):
    def releases(self) -> list[ReleaseRecord]:
        def record(number: int, outcome: str, apps: dict[str, str]) -> ReleaseRecord:
            deliveries = tuple((app, "production", row) for app, row in apps.items())
            return ReleaseRecord(f"REL-{number:03d}", number, outcome, deliveries, Path(f"REL-{number:03d}.md"))

        return [record(3, "released", {"api": "released"}), record(4, "rolled-back", {"api": "rolled-back"}), record(5, "partial", {"api": "failed", "web": "released"})]

    def test_the_cells_list_identifiers_in_number_order(self) -> None:
        self.assertEqual("BUG-002, BUG-010", ids_text(["BUG-010", "BUG-002", "BUG-002"]))
        self.assertEqual(EMPTY_CELL, ids_text([]))
        self.assertEqual(["F-001", "F-002"], cell_ids("F-001, F-002"))
        self.assertEqual([], cell_ids("—"))
        self.assertEqual({"api": "released", "web": "in-dev"}, parse_app_stages_cell("api: released; web: in-dev"))
        self.assertEqual({}, parse_app_stages_cell("—"))

    def test_an_operations_row_reads_released_features_the_latest_record_bugs_and_incidents(self) -> None:
        incidents = [
            IncidentPage(parse_markdown_text(Path("INC-001-a.md"), incident())),
            IncidentPage(parse_markdown_text(Path("INC-002-b.md"), incident(id="INC-002", status="resolved", mitigation="x", resolution="y"))),
        ]
        row = operation_row(
            "backend",
            delivery_target="production",
            feature_stage_cells={"F-002": "backend: released", "F-001": "backend: released; web: in-dev", "F-003": "backend: in-qa"},
            bug_rows=[bug_row("BUG-004", apps="backend, web"), bug_row("BUG-005", apps="web")],
            incidents=incidents,
            releases=[],
        )
        self.assertEqual(
            {
                "app": "backend",
                "delivery_target": "production",
                "released_features": "F-001, F-002",
                "latest_release": "—",
                "latest_outcome": "—",
                "open_bugs": "BUG-004",
                "open_incidents": "INC-001",
            },
            row,
        )

    def test_the_latest_record_is_the_highest_number_that_names_the_app_and_its_outcome_is_the_apps(self) -> None:
        releases = self.releases()
        kwargs = dict(delivery_target=None, feature_stage_cells={}, bug_rows=[], incidents=[], releases=releases)
        self.assertEqual(("REL-005", "failed"), tuple(operation_row("api", **kwargs)[key] for key in ("latest_release", "latest_outcome")))
        self.assertEqual(("REL-005", "released"), tuple(operation_row("web", **kwargs)[key] for key in ("latest_release", "latest_outcome")))
        self.assertEqual("rolled-back", operation_row("api", **{**kwargs, "releases": releases[:2]})["latest_outcome"])
        self.assertIsNone(operation_row("worker", **kwargs))

    def test_the_delivery_target_is_not_compared(self) -> None:
        expected = op_row(delivery_target="—")
        self.assertTrue(operation_rows_match(expected, op_row(delivery_target="staging")))
        self.assertFalse(operation_rows_match(expected, op_row(open_bugs="—")))
        self.assertTrue(operation_rows_match(None, None))
        self.assertFalse(operation_rows_match(expected, None))


class FeatureRowTests(QaBoard):
    def board(self):
        return read_board_views(self.read(BOARD))

    def feature_row(self) -> str:
        return next(line for line in self.read(BOARD).splitlines() if line.startswith("| F-001 |"))

    def errors(self) -> list[str]:
        return [f"{item.code}: {item.message}" for item in lint_wiki(self.root).diagnostics if item.severity == "error"]

    def test_the_feature_row_carries_its_tracks_and_stages_and_an_idle_board_has_no_other_rows(self) -> None:
        cells = [cell.strip() for cell in self.feature_row().strip("|").split("|")]
        self.assertRegex(cells[5], r"^ui: \S+; technical: \S+$")
        self.assertIn("backend: ready-for-qa", cells[6])
        self.assertEqual("—", cells[7])
        self.assertEqual(({}, {}), (self.board().bugs, self.board().operations))
        self.assertEqual([], self.errors())

    def test_a_bug_found_by_qa_reaches_the_feature_row_the_bugs_table_and_the_apps_row(self) -> None:
        changes = [{"path": FEATURE, "content": self.qa_table([app_row("worker", result="fail")])}, {"path": BUG, "content": bug_page("BUG-001")}]
        self.apply("qa-verify", changes)
        self.assertTrue(self.feature_row().endswith("| BUG-001 |"), self.feature_row())
        views = self.board()
        self.assertEqual(("open", "dev", "worker", "F-001", "yes"), tuple(views.bugs["BUG-001"][key] for key in ("status", "owner", "apps", "feature", "blocking")))
        self.assertEqual("BUG-001", views.operations["worker"]["open_bugs"])
        self.assertNotIn("backend", views.operations)
        self.assertEqual([], self.errors())

    def test_closing_the_bug_removes_every_row_it_made(self) -> None:
        changes = [{"path": FEATURE, "content": self.qa_table([app_row("worker", result="fail")])}, {"path": BUG, "content": bug_page("BUG-001")}]
        self.apply("qa-verify", changes)
        closed = bug_page("BUG-001", status="closed", extra={"close-reason": "wont-fix: Accepted."})
        self.apply("bug-update", [{"path": BUG, "content": closed}], approver=self.pat)
        self.assertTrue(self.feature_row().endswith("| — |"), self.feature_row())
        self.assertEqual(({}, {}), (self.board().bugs, self.board().operations))
        self.assertEqual([], self.errors())

    def test_a_bug_planted_without_its_rows_is_drift_for_the_feature_and_for_the_tables(self) -> None:
        path = self.root / BUG
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(bug_page("BUG-001"), encoding="utf-8")
        found = [(item.code, item.feature_id) for item in lint_wiki(self.root).diagnostics if item.code == "status-board-frontmatter-drift"]
        self.assertIn(("status-board-frontmatter-drift", "F-001"), found)
        self.assertIn(("status-board-frontmatter-drift", None), found)


if __name__ == "__main__":
    unittest.main()
