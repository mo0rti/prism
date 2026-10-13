"""Workspaces for the board-page tests: feature F-001 with two apps, `backend` and `worker`, in a chosen state.

`TwoAppWorkspace` extends the lifecycle test workspace. The seeded states are the ones the board page has to explain:
`backend` released while `worker` is still in QA, and a feature in development with `backend` delivered. The Bugs and
Operations tables of the status board are written from the pages on disk, as the board service leaves them.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from tests.qa_pages import bug_page
from tests.test_lifecycle_model import (
    TEXT_ONE,
    TEXT_TWO,
    _Workspace,
    delivery_row,
    qa_row,
    ref,
    release_row,
)
from tests.wiki_files import refresh_status_board

BOTH = ["backend", "worker"]
ARTIFACTS = {"backend": "build:backend#1", "worker": "build:worker#1"}


class TwoAppWorkspace(_Workspace):
    """A workspace of two apps that holds F-001 in the state a test seeds."""

    def runTest(self) -> None:  # noqa: N802 - lets the case be built outside a test run
        pass

    def criteria(self) -> list[str]:
        return [f"AC-1 [backend, worker] {TEXT_ONE}", f"AC-2 [backend] {TEXT_TWO}"]

    def covering_qa(self) -> list[str]:
        return [
            qa_row("backend", [ref(1, BOTH, TEXT_ONE), ref(2, ["backend"], TEXT_TWO)], f"`{ARTIFACTS['backend']}`"),
            qa_row("worker", [ref(1, BOTH, TEXT_ONE)], f"`{ARTIFACTS['worker']}`"),
        ]

    def seed_released_and_in_qa(self) -> None:
        """`backend` is released and `worker` is in QA, so the feature is `in-qa` (the minimum of its app stages)."""

        page = self.page(
            "in-qa",
            "qa",
            BOTH,
            self.criteria(),
            delivery=[delivery_row(app) for app in BOTH],
            qa=self.covering_qa(),
            release=[release_row("backend", "released")],
        )
        self.seed("in-qa", "qa", page)

    def seed_in_dev(self) -> None:
        """`backend` is delivered and `worker` is not, so the feature is `in-dev`."""

        page = self.page("in-dev", "dev", BOTH, self.criteria(), delivery=[delivery_row("backend")])
        self.seed("in-dev", "dev", page)

    def add_open_bug(self) -> None:
        path = self.root / "knowledge" / "wiki" / "bugs" / "BUG-001-summary-export.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(bug_page("BUG-001", apps=["worker"], feature="F-001").encode("utf-8"))

    def write_status_board(self) -> None:
        refresh_status_board(self.root)


@contextmanager
def two_app_workspace(state: str) -> Iterator[Path]:
    """The root of a disposable two-app workspace in `state` (`released-and-in-qa` or `in-dev`)."""

    case = TwoAppWorkspace()
    case.setUp()
    try:
        {"released-and-in-qa": case.seed_released_and_in_qa, "in-dev": case.seed_in_dev}[state]()
        case.add_open_bug()
        case.write_status_board()
        yield case.root
    finally:
        case.doCleanups()
