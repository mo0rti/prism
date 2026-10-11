"""What the Lumen Library case asserts after a step: the pages, the status board and the three read surfaces.

`LumenChecks` is a mixin for a test class that has `root`, `read` and `exists`. `assert_step(number)` compares the workspace with
`EXPECTED[number]` (written from CONTRACTS 10.1 and 8.2) and checks that `prism wiki lint --json`, `prism status --json` and
`prism wiki transition-preflight` agree with the pages.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from prism_cli.wiki_model import read_feature_evidence
from tests.lumen_library import APPS, BUG_DIR, CATALOG, CONTRACT_PATH, FEATURE_ID, FEATURE_PATH, INCIDENT_DIR, READER, RELEASE_DIR, BOARD_PATH, split_page
from tests.lumen_steps import DASH, EXPECTED, Expected
from tests.test_apps_surfaces import run_cli

BUG_META = {
    "BUG-001": ("Reserve button does nothing", READER, "F-001", "yes"),
    "BUG-002": ("Reservation response lacks the pickup date", CATALOG, "F-001", "yes"),
    "BUG-003": ("Reservation cache ignores copy status", CATALOG, "none", "no"),
}
FEATURE_TITLE = "Reserve a book"
FEATURE_HEADER = ["ID", "Feature", "Status", "Owner", "Board Review", "Design tracks", "App stages", "Open bugs"]
BUG_HEADER = ["ID", "Bug", "Status", "Owner", "Apps", "Feature", "Blocking"]
OPERATIONS_HEADER = ["App", "Delivery target", "Released features", "Latest release", "Latest attempt outcome", "Open bugs", "Open incidents"]


def cells_of(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def board_tables(text: str) -> dict[str, list[list[str]]]:
    """The tables of a status board by heading ("" for the feature table): the rows under the header and its separator."""

    tables: dict[str, list[list[str]]] = {}
    heading = ""
    for line in text.splitlines():
        if line.startswith("## "):
            heading = line[3:].strip()
        elif line.strip().startswith("|"):
            tables.setdefault(heading, []).append(cells_of(line))
    return {name: rows for name, rows in tables.items()}


def strip_code(cell: str) -> str:
    return cell.strip().strip("`")


class LumenChecks:
    """Assertions over a Lumen workspace. The host class provides `root`, `read(path)` and `exists(path)`."""

    root: Path

    # -- reading the pages -----------------------------------------------------------------------------------------------------

    def page_state(self) -> dict[str, Any]:
        frontmatter, body = split_page(self.read(FEATURE_PATH))
        evidence = read_feature_evidence(body)
        history = re.findall(r"(?m)^### \d{4}-\d{2}-\d{2} - (\S+)", body.split("## Evidence history", 1)[1])
        state: dict[str, Any] = {
            "status": (frontmatter["status"], frontmatter["owner"]),
            "tracks": frontmatter.get("design-tracks"),
            "delivery": {row.cells[0]: strip_code(row.cells[1]) for row in evidence.delivery},
            "qa": sorted((row.cells[0], int(row.cells[5].removeprefix("qa-")), row.cells[6]) for row in evidence.qa),
            "release": {
                row.cells[0]: (row.cells[1], strip_code(row.cells[2]), int(row.cells[3].removeprefix("release-")), row.cells[4], (re.search(r"REL-\d+", row.cells[5]) or [DASH])[0])
                for row in evidence.release
                if row.cells[4] != "pending"
            },
            "pending": sorted(row.cells[0] for row in evidence.release if row.cells[4] == "pending"),
            "history": history,
            "revalidation": frontmatter.get("app-revalidation") or {},
            "contract": split_page(self.read(CONTRACT_PATH))[0]["status"] if self.exists(CONTRACT_PATH) else None,
        }
        return state

    def directory_front_matter(self, directory: str, key: str) -> dict[str, dict[str, Any]]:
        folder = self.root / directory
        pages = sorted(folder.glob("*.md")) if folder.is_dir() else []
        found: dict[str, dict[str, Any]] = {}
        for path in pages:
            if path.name.startswith("_"):
                continue
            frontmatter = split_page(path.read_text(encoding="utf-8"))[0]
            found[frontmatter[key]] = frontmatter
        return found

    # -- the assertions ----------------------------------------------------------------------------------------------------------

    def assert_step(self, number: int) -> None:
        """The workspace after step `number` is the state CONTRACTS 10.1 describes."""

        expected = EXPECTED[number]
        label = f"after step {number}"
        state = self.page_state()
        self.assertEqual(expected.status, state["status"], f"{label}: status and owner")  # type: ignore[attr-defined]
        self.assertEqual(expected.delivery, state["delivery"], f"{label}: Delivery evidence rows")  # type: ignore[attr-defined]
        self.assertEqual(sorted(expected.qa), state["qa"], f"{label}: QA verification rows (row, attempt, result)")  # type: ignore[attr-defined]
        pending = sorted(app for app, row in expected.release.items() if row[3] == "pending")
        self.assertEqual(pending, state["pending"], f"{label}: pending Release rows")  # type: ignore[attr-defined]
        self.assertEqual({app: row for app, row in expected.release.items() if row[3] != "pending"}, state["release"], f"{label}: Release rows")  # type: ignore[attr-defined]
        self.assertEqual(expected.history, state["history"], f"{label}: Evidence history entries")  # type: ignore[attr-defined]
        self.assertEqual(expected.revalidation, state["revalidation"], f"{label}: app-revalidation")  # type: ignore[attr-defined]
        self.assertEqual(expected.contract, state["contract"], f"{label}: API contract status")  # type: ignore[attr-defined]
        bugs = self.directory_front_matter(BUG_DIR, "id")
        self.assertEqual(expected.bugs, {key: (page["status"], page["owner"]) for key, page in bugs.items()}, f"{label}: bug pages")  # type: ignore[attr-defined]
        records = self.directory_front_matter(RELEASE_DIR, "id")
        self.assertEqual(expected.records, {key: page["outcome"] for key, page in records.items()}, f"{label}: release records")  # type: ignore[attr-defined]
        incidents = self.directory_front_matter(INCIDENT_DIR, "id")
        self.assertEqual(expected.incidents, {key: page["status"] for key, page in incidents.items()}, f"{label}: incident records")  # type: ignore[attr-defined]
        self.assert_board(number, expected)
        self.assert_surfaces(number, expected)

    def assert_board(self, number: int, expected: Expected) -> None:
        """The status board shows the feature row, the open bugs and the Operations rows of CONTRACTS 8.2."""

        tables = board_tables(self.read(BOARD_PATH))
        label = f"after step {number}: the status board"
        header, *rows = tables.get("", [FEATURE_HEADER])
        self.assertEqual(FEATURE_HEADER, header, label)  # type: ignore[attr-defined]
        stages = "; ".join(f"{app}: {expected.stages[app]}" for app in APPS if app in expected.stages) or DASH
        self.assertEqual(
            [[FEATURE_ID, FEATURE_TITLE, expected.status[0], expected.status[1], "not-needed", expected.tracks, stages, expected.feature_bugs]] if number >= 1 else [],
            [row for row in rows if not set(row) <= {"-" * len(cell) for cell in row} and not all(set(cell) <= {"-"} for cell in row)],
            f"{label}: the feature row",
        )
        open_bugs = {key: value for key, value in expected.bugs.items() if value[0] not in ("released", "closed")}
        bug_header, *bug_rows = tables.get("Bugs", [BUG_HEADER])
        self.assertEqual(BUG_HEADER, bug_header, label)  # type: ignore[attr-defined]
        bug_rows = [row for row in bug_rows if not all(set(cell) <= {"-"} for cell in row)]
        self.assertEqual(  # type: ignore[attr-defined]
            [[key, BUG_META[key][0], status, owner, BUG_META[key][1], BUG_META[key][2], BUG_META[key][3]] for key, (status, owner) in sorted(open_bugs.items())],
            sorted(bug_rows, key=lambda row: row[0]),
            f"{label}: the Bugs table",
        )
        operation_header, *operation_rows = tables.get("Operations", [OPERATIONS_HEADER])
        self.assertEqual(OPERATIONS_HEADER, operation_header, label)  # type: ignore[attr-defined]
        operation_rows = [row for row in operation_rows if not all(set(cell) <= {"-"} for cell in row)]
        self.assertEqual(  # type: ignore[attr-defined]
            [[app, *expected.operations[app]] for app in APPS if app in expected.operations],
            operation_rows,
            f"{label}: the Operations table",
        )

    def cli(self, *argv: str) -> dict[str, Any]:
        code, stdout, stderr = run_cli(*argv)
        self.assertIn(code, (0, 1, 2, 3), f"prism {' '.join(argv[:2])} exited {code}: {stderr}")  # type: ignore[attr-defined]
        return json.loads(stdout)

    def assert_surfaces(self, number: int, expected: Expected) -> None:
        """`prism wiki lint --json`, `prism status --json` and `prism wiki transition-preflight` agree with the pages and the board."""

        label = f"after step {number}"
        lint = self.cli("wiki", "lint", str(self.root), "--json")
        problems = [f"{item['code']}: {item['message']}" for item in lint["diagnostics"] if item["severity"] in ("error", "warning")]
        self.assertEqual([], problems, f"{label}: lint")  # type: ignore[attr-defined]
        self.assertEqual((0, 0, True), (lint["facts"]["error_count"], lint["facts"]["warning_count"], lint["facts"]["clean"]), f"{label}: lint facts")  # type: ignore[attr-defined]
        status = self.cli("status", str(self.root), "--json")
        wiki = status["facts"]["wiki"] if "wiki" in status["facts"] else status["facts"]
        self.assertEqual({FEATURE_ID: expected.stages} if expected.stages else {}, wiki["feature_app_stages"], f"{label}: status app stages")  # type: ignore[attr-defined]
        counts = wiki["feature_status_counts"]
        self.assertEqual(1, counts[expected.status[0]], f"{label}: status counts")  # type: ignore[attr-defined]
        self.assertEqual(1, sum(counts.values()), f"{label}: one feature")  # type: ignore[attr-defined]
        self.assertEqual(0, wiki["error_count"], f"{label}: status error count")  # type: ignore[attr-defined]
        preflight = self.cli("wiki", "transition-preflight", FEATURE_ID, str(self.root), "--action", expected.next_action, "--json")
        transition = preflight["facts"]["transition"]
        self.assertEqual(expected.status, (transition["source_status"], transition["source_owner"]), f"{label}: preflight source")  # type: ignore[attr-defined]
        self.assertEqual(expected.next_action, transition["action"], label)  # type: ignore[attr-defined]
        self.assertTrue(transition["classification"] in ("ready", "blocked", "unknown", "review"), f"{label}: preflight classification")  # type: ignore[attr-defined]


# The end state of the case as files: the pages the nineteen steps write, the index and the status board. The log is left out
# because it names previews and participants, which differ on every run.
FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "lumen_library"
SNAPSHOT_DIRECTORIES = ("features", "app-requirements", "design", "technical-design", "api-contracts", "bugs", "releases", "incidents")
SNAPSHOT_FILES = ("index.md", "status-board.md")
WRITE_FIXTURE_VARIABLE = "PRISM_WRITE_LUMEN_FIXTURE"


def end_state(root: Path) -> dict[str, str]:
    """The files of the end state below `knowledge/wiki`, by path relative to it, with LF line endings."""

    wiki = root / "knowledge" / "wiki"
    found: dict[str, str] = {}
    for name in SNAPSHOT_FILES:
        found[name] = (wiki / name).read_text(encoding="utf-8").replace("\r\n", "\n")
    for directory in SNAPSHOT_DIRECTORIES:
        for path in sorted((wiki / directory).glob("*.md")):
            if not path.name.startswith("_"):
                found[f"{directory}/{path.name}"] = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    return found


def committed_end_state() -> dict[str, str]:
    return {
        path.relative_to(FIXTURE_ROOT).as_posix(): path.read_text(encoding="utf-8").replace("\r\n", "\n")
        for path in sorted(FIXTURE_ROOT.rglob("*.md"))
    }
