"""The Operations row of the status board follows the release records (CONTRACTS 5.3, 8.2).

`release-done` writes the record and the status board in one operation, so the Operations row of every app the record names
changes with it: a release, a failed attempt, a rollback, a redeploy and the release of a bug fix. After each, lint reports no drift.
"""

from __future__ import annotations

import unittest

from prism_cli.wiki_lint import lint_wiki
from prism_cli.wiki_operations import read_board_views
from tests.release_support import (
    BUGS,
    FEATURE,
    FIX_HEADER,
    RELEASE_HEADER,
    VERIFICATION_HEADER,
    ReleaseTests,
    bug_page,
    delivery,
    fix_row,
    record_page,
    record_path,
    release_row,
    table,
    verification_row,
)
from tests import test_release_variants
from tests.wiki_files import refresh_status_board

BOARD = "knowledge/wiki/status-board.md"
BUG = f"{BUGS}/BUG-001-summary-export-drops-comments.md"
FAILED_EVIDENCE = "deployment: https://ci.example/deploy/aborted-7"
CELLS = ("released_features", "latest_release", "latest_outcome", "open_bugs", "open_incidents")


class OperationsFollowReleaseTests(ReleaseTests):
    def operations(self) -> dict[str, tuple[str, ...]]:
        views = read_board_views(self.read(BOARD))
        return {app: tuple(row[key] for key in CELLS) for app, row in views.operations.items()}

    def drift(self) -> list[str]:
        return [item.message for item in lint_wiki(self.root).diagnostics if item.code == "status-board-frontmatter-drift"]

    def rollback_page(self, number: int, of: int) -> str:
        rows = [delivery("F-001", app, outcome="rolled-back", attempt=None) for app in ("backend", "worker")]
        return record_page(number, rows, rollback_of=f"REL-{of:03d}", title="Rollback", summary="The release is rolled back.", rollback="Rolled back after errors.")

    def test_a_release_gives_each_app_its_released_features_and_the_record(self) -> None:
        self.assertEqual({}, self.operations())
        self.release()
        self.assertEqual(("F-001", "REL-001", "released", "—", "—"), self.operations()["backend"])
        self.assertEqual(self.operations()["backend"], self.operations()["worker"])
        self.assertEqual([], self.drift())
        self.assertEqual(set(), self.errors())

    def test_a_failed_attempt_is_the_latest_outcome_of_its_app_only(self) -> None:
        feature = self.released_page([release_row("backend", 1), release_row("worker", 1, outcome="failed")], status="ready-for-release", owner="release")
        record = record_page(1, [delivery("F-001", "backend"), delivery("F-001", "worker", outcome="failed", evidence=FAILED_EVIDENCE)])
        self.apply("release-done", [{"path": FEATURE, "content": feature}, {"path": record_path(1), "content": record}], approver=self.owner)
        operations = self.operations()
        self.assertEqual(("F-001", "REL-001", "released", "—", "—"), operations["backend"])
        self.assertEqual(("—", "REL-001", "failed", "—", "—"), operations["worker"])
        self.assertEqual([], self.drift())
        self.assertEqual(set(), self.errors())

    def test_a_failed_release_that_returns_the_feature_to_development_is_the_latest_outcome(self) -> None:
        changes = test_release_variants.ReleaseReturnTests.return_changes(self, ["backend", "worker"])  # type: ignore[arg-type]
        self.apply("release-done", changes, approver=self.owner)
        self.assertEqual(("in-dev", "dev"), self.status())
        for app in ("backend", "worker"):
            self.assertEqual(("—", "REL-001", "failed", "—", "—"), self.operations()[app])
        self.assertEqual([], self.drift())

    def test_a_rollback_is_the_latest_outcome_and_the_feature_stays_released(self) -> None:
        self.release()
        self.apply("release-done", [{"path": record_path(2), "content": self.rollback_page(2, 1)}], approver=self.owner)
        self.assertEqual(("released", "none"), self.status())
        for app in ("backend", "worker"):
            self.assertEqual(("F-001", "REL-002", "rolled-back", "—", "—"), self.operations()[app])
        self.assertEqual([], self.drift())
        self.assertEqual(set(), self.errors())

    def test_a_redeploy_after_a_rollback_is_released_again(self) -> None:
        self.release()
        self.apply("release-done", [{"path": record_path(2), "content": self.rollback_page(2, 1)}], approver=self.owner)
        rows = [delivery("F-001", app, attempt=None) for app in ("backend", "worker")]
        redeploy = record_page(3, rows, retry_of="REL-002", title="Redeploy", summary="The delivery is redeployed.")
        self.apply("release-done", [{"path": record_path(3), "content": redeploy}], approver=self.owner)
        for app in ("backend", "worker"):
            self.assertEqual(("F-001", "REL-003", "released", "—", "—"), self.operations()[app])
        self.assertEqual([], self.drift())
        self.assertEqual(set(), self.errors())

    def test_a_failed_redeploy_is_the_latest_outcome_until_it_is_retried(self) -> None:
        self.release()
        self.apply("release-done", [{"path": record_path(2), "content": self.rollback_page(2, 1)}], approver=self.owner)
        failed = [delivery("F-001", app, outcome="failed", attempt=None, evidence=FAILED_EVIDENCE) for app in ("backend", "worker")]
        self.apply(
            "release-done",
            [{"path": record_path(3), "content": record_page(3, failed, retry_of="REL-002", title="Redeploy", summary="The delivery is redeployed.")}],
            approver=self.owner,
        )
        self.assertEqual(("F-001", "REL-003", "failed", "—", "—"), self.operations()["backend"])
        self.assertEqual([], self.drift())

    def test_the_release_of_a_bug_fix_closes_its_open_bug_on_the_row(self) -> None:
        self.release()
        fix = table(FIX_HEADER, [fix_row("backend", "build:backend#2")])
        verification = table(VERIFICATION_HEADER, [verification_row("backend", "build:backend#2")])
        self.put(BUG, bug_page("BUG-001", status="verified", apps=["backend"], feature="F-001", fix=fix, verification=verification))
        refresh_status_board(self.root)
        self.assertEqual(("F-001", "REL-001", "released", "BUG-001", "—"), self.operations()["backend"])
        self.assertEqual([], self.drift())
        row = release_row("backend", 2, version="build:backend#2")
        feature = self.read(FEATURE).replace(release_row("backend", 1), row)
        bug = (
            bug_page("BUG-001", status="verified", apps=["backend"], feature="F-001", fix=fix, verification=verification, release=table(RELEASE_HEADER, [row]))
            .replace("status: verified", "status: released")
            .replace("owner: release", "owner: none")
        )
        record = record_page(2, [delivery("BUG-001", "backend", version="build:backend#2")], features=[], bugs=["BUG-001"], title="Hotfix of BUG-001", summary="BUG-001 is delivered to production.")
        self.apply("release-done", [{"path": FEATURE, "content": feature}, {"path": BUG, "content": bug}, {"path": record_path(2), "content": record}], approver=self.owner)
        self.assertEqual(("F-001", "REL-002", "released", "—", "—"), self.operations()["backend"])
        self.assertNotIn("BUG-001", read_board_views(self.read(BOARD)).bugs)
        self.assertEqual([], self.drift())
        self.assertEqual(set(), self.errors())


if __name__ == "__main__":
    unittest.main()
