"""Workspaces for the board-page tests: feature F-001 with two apps, `backend` and `worker`, in a chosen state.

`TwoAppWorkspace` extends the lifecycle test workspace. The seeded states are the ones the board page has to explain:
`backend` released while `worker` is still in QA, and a feature in development with `backend` delivered. The Bugs and
Operations tables of the status board are written from the pages on disk, as the board service leaves them.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import yaml

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

    def seed_in_qa(self) -> None:
        """Both apps are delivered and `backend` is verified, so the feature is `in-qa` with both apps in QA."""

        page = self.page(
            "in-qa",
            "qa",
            BOTH,
            self.criteria(),
            delivery=[delivery_row(app) for app in BOTH],
            qa=self.covering_qa(),
        )
        self.seed("in-qa", "qa", page)

    def seed_released(self) -> None:
        """Both apps are released, so F-001 is `released` and keeps its whole scope as history."""

        page = self.page(
            "released",
            "none",
            BOTH,
            self.criteria(),
            delivery=[delivery_row(app) for app in BOTH],
            qa=self.covering_qa(),
            release=[release_row(app, "released") for app in BOTH],
        )
        self.seed("released", "none", page)

    def retire(self, app: str) -> None:
        """Set `status: retired` on one app of the manifest."""

        manifest_path = self.root / "prism.workspace.yml"
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        for entry in manifest["apps"]:
            if entry["id"] == app:
                entry["status"] = "retired"
        manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

    def add_standalone_bug(self, app: str, bug_id: str = "BUG-002") -> None:
        """An open bug that names `app` and no feature (`feature: none`)."""

        path = self.root / "knowledge" / "wiki" / "bugs" / f"{bug_id}-standalone.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(bug_page(bug_id, apps=[app], feature="none").encode("utf-8"))

    def add_open_incident(self, app: str, incident_id: str = "INC-001") -> None:
        """An open incident that names `app`."""

        frontmatter = {
            "id": incident_id,
            "title": "Exports fail",
            "date": "2026-10-01",
            "status": "open",
            "severity": "high",
            "apps": [app],
            "releases": [],
            "follow-ups": [],
        }
        text = (
            f"---\n{yaml.safe_dump(frontmatter, sort_keys=False).rstrip()}\n---\n\n"
            "## Impact\nExports failed for a day.\n\n"
            "## Timeline\n- 2026-10-01 08:15: Exports started failing.\n\n"
            "## Cause\n**Unknown:** The failing path is not known yet.\n\n"
            "## Mitigation\n\n## Resolution\n\n## Follow-ups\n"
        )
        path = self.root / "knowledge" / "wiki" / "incidents" / f"{incident_id}-exports-fail.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))

    def add_open_bug(self) -> None:
        path = self.root / "knowledge" / "wiki" / "bugs" / "BUG-001-summary-export.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(bug_page("BUG-001", apps=["worker"], feature="F-001").encode("utf-8"))

    def write_status_board(self) -> None:
        refresh_status_board(self.root)


@contextmanager
def two_app_workspace(state: str) -> Iterator[Path]:
    """The root of a disposable two-app workspace in `state`.

    `released-and-in-qa`, `in-dev` and `in-qa` are seeded states with an open bug on `worker`. `released-worker-retired` is F-001
    released on both apps with `worker` retired afterwards. `standalone-operations` has no feature, an open bug on `backend` and
    an open incident on `worker`, both without a feature.
    """

    case = TwoAppWorkspace()
    case.setUp()
    try:
        if state == "released-worker-retired":
            case.seed_released()
            case.retire("worker")
        elif state == "standalone-operations":
            case.add_standalone_bug("backend")
            case.add_open_incident("worker")
        else:
            {"released-and-in-qa": case.seed_released_and_in_qa, "in-dev": case.seed_in_dev, "in-qa": case.seed_in_qa}[state]()
            case.add_open_bug()
        case.write_status_board()
        yield case.root
    finally:
        case.doCleanups()
