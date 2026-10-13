"""Workspaces for the board-page tests: feature F-001 with two apps, `backend` and `worker`, in a chosen state.

`TwoAppWorkspace` extends the lifecycle test workspace. The seeded states are the ones the board page has to explain:
`backend` released while `worker` is still in QA, and a feature in development with `backend` delivered. The Bugs and
Operations tables of the status board are written from the pages on disk, as the board service leaves them.

`add_record_history` plants the bug, release and incident records the board's record views read: a bug through its lifecycle, a
release that partly fails, its retry, a rollback, a failed redeploy and a redeploy, an open and a resolved incident, and one
invalid record of each kind.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import yaml

from tests.qa_pages import bug_page, fix_row, verification_row
from tests.release_pages import delivery, record_page
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

    # The record fixture: backend delivers to `production` and worker to `store`.
    BACKEND_BUILD = "build:backend#412"
    BACKEND_FIX_BUILD = "build:backend#413"
    WORKER_BUILD = "build:worker#1"

    def write_wiki_page(self, relative: str, text: str) -> None:
        path = self.root / "knowledge" / "wiki" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))

    def incident_page(
        self,
        incident_id: str,
        *,
        title: str,
        status: str,
        apps: list[str],
        releases: list[str],
        follow_ups: list[str],
        impact: str,
        timeline: list[str],
        cause: str,
        mitigation: str = "",
        resolution: str = "",
    ) -> str:
        frontmatter = {
            "id": incident_id,
            "title": title,
            "date": "2026-10-09",
            "status": status,
            "severity": "high",
            "apps": apps,
            "releases": releases,
            "follow-ups": follow_ups,
        }
        return (
            f"---\n{yaml.safe_dump(frontmatter, sort_keys=False).rstrip()}\n---\n\n"
            f"## Impact\n{impact}\n\n"
            "## Timeline\n" + "\n".join(timeline) + "\n\n"
            f"## Cause\n{cause}\n\n"
            f"## Mitigation\n{mitigation}\n\n"
            f"## Resolution\n{resolution}\n\n"
            "## Follow-ups\n" + "\n".join(f"- {item}" for item in follow_ups) + "\n"
        )

    def add_record_history(self) -> None:
        """Bugs, release records and incidents of a two-app workspace whose F-001 is released.

        Releases: REL-001 delivers F-001 and BUG-001 (backend released, worker failed), REL-002 retries it, REL-003 delivers BUG-002
        to backend, REL-004 rolls REL-003 back, REL-005 is a failed redeploy, REL-006 the redeploy that succeeds, and REL-007 is
        invalid (it retries a record that does not exist). Bugs: BUG-001 and BUG-002 released, BUG-003 open, BUG-004 verified,
        BUG-005 closed as a duplicate of BUG-003, and BUG-006 invalid (status `open` with owner `qa`). Incidents: INC-001 resolved,
        INC-002 open with an unknown cause, and INC-003 invalid (a Timeline line that is not an entry).
        """

        fix_header = "| App | Artifact | Implementation | Tests | Basis |\n|---|---|---|---|---|"
        verification_header = "| App | Method | Artifact | Environment | Attempt | Result | Evidence | Basis |\n|---|---|---|---|---|---|---|---|"
        release_header = "| App | Target | Version | Attempt | Outcome | Record | Basis |\n|---|---|---|---|---|---|---|"

        def release_cell(app: str, number: int, *, attempt: int = 1, target: str = "production", version: str) -> str:
            return f"| {app} | {target} | `{version}` | release-{attempt} | released | [REL-{number:03d}](../releases/REL-{number:03d}.md) | checked |"

        bugs = {
            "BUG-001-reserve-button-does-nothing": bug_page(
                "BUG-001",
                title="Reserve button does nothing",
                status="released",
                apps=["worker"],
                fix=f"{fix_header}\n{fix_row('worker', self.WORKER_BUILD)}",
                verification=f"{verification_header}\n{verification_row('worker', self.WORKER_BUILD)}",
                release=f"{release_header}\n{release_cell('worker', 2, attempt=2, target='store', version=self.WORKER_BUILD)}",
            ),
            "BUG-002-reservation-response-lacks-the-pickup-date": bug_page(
                "BUG-002",
                title="Reservation response lacks the pickup date",
                status="released",
                apps=["backend"],
                feature="none",
                fix=f"{fix_header}\n{fix_row('backend', self.BACKEND_FIX_BUILD)}",
                verification=f"{verification_header}\n{verification_row('backend', self.BACKEND_FIX_BUILD)}",
                release=f"{release_header}\n{release_cell('backend', 3, version=self.BACKEND_FIX_BUILD)}",
            ),
            "BUG-003-reservation-cache-ignores-copy-status": bug_page(
                "BUG-003",
                title="Reservation cache ignores copy status",
                severity="medium",
                blocking=False,
                apps=["backend"],
                feature="none",
                extra={"regression-of": "BUG-002"},
            ),
            "BUG-004-export-drops-the-last-comment": bug_page(
                "BUG-004",
                title="Export drops the last comment",
                status="verified",
                severity="low",
                blocking=False,
                apps=["worker"],
                feature="none",
                fix=f"{fix_header}\n{fix_row('worker', 'build:worker#2')}",
                verification=f"{verification_header}\n{verification_row('worker', 'build:worker#2', attempt=2)}",
            ),
            "BUG-005-cache-ignores-copy-status-again": bug_page(
                "BUG-005",
                title="Cache ignores copy status again",
                status="closed",
                severity="medium",
                blocking=False,
                apps=["backend"],
                feature="none",
                extra={"close-reason": "duplicate", "duplicate-of": "BUG-003"},
            ),
            "BUG-006-owner-does-not-follow-the-status": bug_page(
                "BUG-006", title="Owner does not follow the status", apps=["backend"], feature="none", owner="qa"
            ),
        }
        for name, text in bugs.items():
            self.write_wiki_page(f"bugs/{name}.md", text)

        failed_evidence = "store: https://stores.example/worker/failed"
        records = {
            1: record_page(
                1,
                [
                    delivery("F-001", "backend", version=self.BACKEND_BUILD),
                    delivery("F-001", "worker", outcome="failed", target="store", version=self.WORKER_BUILD, evidence=failed_evidence),
                    delivery("BUG-001", "worker", outcome="failed", target="store", version=self.WORKER_BUILD, evidence=failed_evidence),
                ],
                bugs=["BUG-001"],
                title="Release of F-001 and BUG-001",
                day="2026-10-08",
                summary="F-001 is delivered to production; the store upload of the worker fails.",
            ),
            2: record_page(
                2,
                [
                    delivery("F-001", "worker", attempt=2, target="store", version=self.WORKER_BUILD, evidence="store: https://stores.example/worker/2"),
                    delivery("BUG-001", "worker", attempt=2, target="store", version=self.WORKER_BUILD, evidence="store: https://stores.example/worker/2"),
                ],
                bugs=["BUG-001"],
                title="Retry of REL-001",
                day="2026-10-08",
                retry_of="REL-001",
                summary="The worker is delivered to the store on the second attempt.",
            ),
            3: record_page(
                3,
                [delivery("BUG-002", "backend", version=self.BACKEND_FIX_BUILD)],
                features=[],
                bugs=["BUG-002"],
                title="Fix of BUG-002",
                day="2026-10-09",
                summary="BUG-002 is delivered to production.",
            ),
            4: record_page(
                4,
                [delivery("BUG-002", "backend", outcome="rolled-back", attempt=None, version=self.BACKEND_FIX_BUILD)],
                features=[],
                bugs=["BUG-002"],
                title="Rollback of REL-003",
                day="2026-10-09",
                rollback_of="REL-003",
                summary="REL-003 is rolled back after the reservation errors.",
            ),
            5: record_page(
                5,
                [delivery("BUG-002", "backend", outcome="failed", attempt=None, version=self.BACKEND_FIX_BUILD)],
                features=[],
                bugs=["BUG-002"],
                title="Redeploy of REL-004",
                day="2026-10-09",
                retry_of="REL-004",
                summary="The redeploy of build 413 fails.",
            ),
            6: record_page(
                6,
                [delivery("BUG-002", "backend", attempt=None, version=self.BACKEND_FIX_BUILD)],
                features=[],
                bugs=["BUG-002"],
                title="Redeploy of REL-005",
                day="2026-10-09",
                retry_of="REL-005",
                summary="Build 413 is redeployed to production.",
            ),
            7: record_page(
                7,
                [delivery("BUG-003", "backend", attempt=None, version=self.BACKEND_FIX_BUILD)],
                features=[],
                bugs=["BUG-003"],
                title="Retry of a record that does not exist",
                day="2026-10-10",
                retry_of="REL-099",
                summary="This record names a record that is not in the wiki.",
            ),
        }
        for number, text in records.items():
            self.write_wiki_page(f"releases/REL-{number:03d}.md", text)

        self.write_wiki_page(
            "incidents/INC-001-reservations-fail-after-the-catalog-fix.md",
            self.incident_page(
                "INC-001",
                title="Reservations fail after the catalog fix",
                status="resolved",
                apps=["backend"],
                releases=["REL-003", "REL-004", "REL-005", "REL-006"],
                follow_ups=["BUG-003", "F-001"],
                impact="Readers could not reserve books for 25 minutes.\nSupport received a few reports.\n\nA second paragraph that the summary leaves out.",
                timeline=[
                    "- 2026-10-09 08:15: Reservations started failing after REL-003.",
                    "- 2026-10-09 08:40: REL-003 was rolled back by REL-004.",
                    "- 2026-10-09 09:10: Build 413 was redeployed by REL-006.",
                ],
                cause="The reservation cache ignored the copy status after REL-003.",
                mitigation="REL-003 was rolled back by REL-004 at 08:40.",
                resolution="Build 413 was redeployed by REL-006 and reservations succeed again.",
            ),
        )
        self.write_wiki_page(
            "incidents/INC-002-exports-fail-for-the-worker.md",
            self.incident_page(
                "INC-002",
                title="Exports fail for the worker",
                status="open",
                apps=["worker"],
                releases=["REL-002"],
                follow_ups=[],
                impact="Exports of the worker fail for large reviews.",
                timeline=["- 2026-10-10 11:00: Exports started failing after REL-002."],
                cause="**Unknown:** The failing path is not known yet.",
            ),
        )
        self.write_wiki_page(
            "incidents/INC-003-timeline-with-a-free-text-line.md",
            self.incident_page(
                "INC-003",
                title="Timeline with a free text line",
                status="open",
                apps=["backend"],
                releases=[],
                follow_ups=[],
                impact="An incident whose Timeline has a line that is not an entry.",
                timeline=["- 2026-10-10 12:00: The page starts well.", "- this line has no date"],
                cause="**Unknown:** Not known.",
            ),
        )

    def write_status_board(self) -> None:
        refresh_status_board(self.root)


@contextmanager
def two_app_workspace(state: str) -> Iterator[Path]:
    """The root of a disposable two-app workspace in `state`.

    `released-and-in-qa`, `in-dev` and `in-qa` are seeded states with an open bug on `worker`. `released-worker-retired` is F-001
    released on both apps with `worker` retired afterwards. `standalone-operations` has no feature, an open bug on `backend` and
    an open incident on `worker`, both without a feature. `records` is F-001 released on both apps with the bugs, release records
    and incidents of `add_record_history`.
    """

    case = TwoAppWorkspace()
    case.setUp()
    try:
        if state == "released-worker-retired":
            case.seed_released()
            case.retire("worker")
        elif state == "records":
            case.seed_released()
            case.add_record_history()
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
