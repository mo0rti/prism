"""Release edge, denied and stale cases of CONTRACTS 10.2 and 10.3 that cross the modules: interruption at every write, stale previews, repair and numbering."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from prism_cli.board_service import BoardError
from tests.board_approval import approve
from tests.release_support import (
    BUGS,
    FEATURE,
    FIX_HEADER,
    RELEASE_HEADER,
    VERIFICATION_HEADER,
    ReleaseTests,
    FEATURE_TWO,
    ReleaseTwoFeatures,
    bug_page,
    delivery,
    fix_row,
    record_page,
    record_path,
    release_row,
    table,
    verification_row,
)
from tests import test_release_reopen
from tests.test_release_recovery import _Crash

BUG = f"{BUGS}/BUG-001-summary-export-drops-comments.md"
WRITES = 5  # the feature page, the record, the status board, the index and the log


class InterruptionTests(ReleaseTests):
    def crash_before_write(self, index: int, approver, preview: dict, operation: str) -> None:
        """Apply a gated preview and stop the process just before its `index`-th write."""

        original = self.service._apply_write
        seen = {"count": 0}

        def interrupted(write, **kwargs):
            if seen["count"] == index:
                raise _Crash()
            seen["count"] += 1
            return original(write, **kwargs)

        review = self.service.get_preview(approver, preview["preview_id"])["approval"]["review_revision"]
        with patch.object(self.service, "_apply_write", side_effect=interrupted):
            with self.assertRaises(_Crash):
                self.service.apply(approver, preview["preview_id"], operation, review, True)


def _roll_forward_test(index: int):
    def test(self: InterruptionTests) -> None:
        preview = self.ready("release-done", self.release_changes())
        self.crash_before_write(index, self.owner, preview, "pending-1")
        receipt = self.service.apply(self.owner, preview["preview_id"], "pending-1")
        self.assertEqual("applied", receipt["state"])
        self.assertEqual(["REL-001.md"], self.records())
        self.assertEqual("pending-1", self.record(1)[0]["operation"])
        self.assertEqual(("released", "none"), self.status())
        self.assertEqual(set(), self.errors())
        self.assertIn("backend: released", self.read("knowledge/wiki/status-board.md"))

    test.__doc__ = f"A crash before write {index + 1} of {WRITES} rolls forward to the same record, operation and state."
    return test


for _index in range(WRITES):
    setattr(InterruptionTests, f"test_a_crash_before_write_{_index + 1}_rolls_forward", _roll_forward_test(_index))


class StaleAndDeniedTests(ReleaseTests):
    def test_a_bug_ingested_between_the_preview_and_the_apply_makes_the_preview_stale(self) -> None:
        preview = self.ready("release-done", self.release_changes())
        self.put(f"{BUGS}/BUG-001-open.md", bug_page("BUG-001", status="open", apps=["backend"]))
        review = self.service.get_preview(self.owner, preview["preview_id"])["approval"]["review_revision"]
        with self.assertRaises(BoardError) as caught:
            self.service.apply(self.owner, preview["preview_id"], "operation-1", review, True)
        self.assertEqual(("stale_preview", 409), (caught.exception.code, caught.exception.status))
        self.assertEqual([], self.records())

    def test_a_blocking_bug_ingested_before_the_preview_blocks_the_release(self) -> None:
        self.put(f"{BUGS}/BUG-001-open.md", bug_page("BUG-001", status="open", apps=["backend"]))
        self.assertEqual(("open_bug_blocks_release", 409), self.refuse(*self.all_released()))

    def test_bug_update_cannot_release_a_bug(self) -> None:
        fix = table(FIX_HEADER, [fix_row("backend", "build:backend#1")])
        verification = table(VERIFICATION_HEADER, [verification_row("backend", "build:backend#1")])
        self.put(BUG, bug_page("BUG-001", status="verified", apps=["backend"], fix=fix, verification=verification))
        released = bug_page("BUG-001", status="released", apps=["backend"], fix=fix, verification=verification, release=table(RELEASE_HEADER, [release_row("backend", 1)]))
        error = self.refused("bug-update", [{"path": BUG, "content": released}], approver=self.owner)
        self.assertEqual(("bug_release_via_release_done", 409), (error.code, error.status))

    def test_a_record_numbered_below_the_highest_on_disk_is_refused(self) -> None:
        self.put(record_path(10), record_page(10, [delivery("F-002", "backend")], features=["F-002"]))
        feature, record = self.all_released(number=9)
        self.assertEqual(("release_sequence_invalid", 409), self.refuse(feature, record, number=9))
        feature, record = self.all_released(number=11)
        self.settle(feature, record, number=11)
        self.assertIn("REL-011.md", self.records())

    def test_two_previews_that_take_one_number_are_not_both_applied(self) -> None:
        first = self.ready("release-done", self.release_changes())
        second = self.ready("release-done", self.release_changes())
        self.assertEqual("applied", approve(self.service, self.owner, first, "operation-1")["state"])
        review = self.service.get_preview(self.owner, second["preview_id"])["approval"]["review_revision"]
        with self.assertRaises(BoardError) as caught:
            self.service.apply(self.owner, second["preview_id"], "operation-2", review, True)
        self.assertIn(caught.exception.code, {"stale_preview", "release_id_taken", "stale_write"})
        self.assertEqual(["REL-001.md"], self.records())

    def test_a_repair_adopts_the_record_unchanged_without_recounting_the_attempt(self) -> None:
        preview = self.ready("release-done", self.release_changes())
        original = self.service._apply_write

        def interrupted(write, **kwargs):
            if write["role"] == "status-board":
                raise _Crash()
            return original(write, **kwargs)

        review = self.service.get_preview(self.owner, preview["preview_id"])["approval"]["review_revision"]
        with patch.object(self.service, "_apply_write", side_effect=interrupted):
            with self.assertRaises(_Crash):
                self.service.apply(self.owner, preview["preview_id"], "pending-1", review, True)
        written = self.read(record_path(1))
        recovery_review = self.service.operation(self.owner, "pending-1")["recovery_review_revision"]
        failure = BoardError("checks_changed", "Current workflow checks no longer permit this action.", 409)
        with patch.object(self.service, "_revalidate_recovery", side_effect=failure):
            self.assertEqual("abandoned", self.service.recover(self.owner, "pending-1", recovery_review, True, abandon=True)["state"])
        repair = self.service.preview_transition(self.owner, None, "operation-repair", {"semantic_review_acknowledged": True}, operation_id="pending-1")
        self.assertEqual("applied", approve(self.service, self.owner, repair, "repair-1")["state"])
        self.assertEqual(written, self.read(record_path(1)))
        self.assertEqual({"backend": 1, "worker": 1}, {row.app: row.attempt for row in self.evidence().release})
        link = self.service.store.connection.execute("SELECT repair_of FROM operations WHERE operation_id = 'repair-1'").fetchone()
        self.assertEqual("pending-1", link[0])
        self.assertEqual(set(), self.errors())


class CoReleaseAttemptTests(ReleaseTwoFeatures):
    def test_a_retry_of_one_feature_and_a_first_attempt_of_another_share_one_record(self) -> None:
        # F-001 failed on the backend once; its retry is attempt 2 and F-002's first delivery is attempt 1, on one artifact.
        self.put(FEATURE_TWO, self.second_page("ready-for-release", "release", ["| backend | — | `build:backend#1` | release-1 | pending | — | — |"], "build:backend#1"))
        failed = self.released_page([release_row("backend", 1, outcome="failed"), release_row("worker", 1)], status="ready-for-release", owner="release")
        first = record_page(1, [delivery("F-001", "backend", outcome="failed", evidence="deployment: https://ci.example/deploy/aborted-5"), delivery("F-001", "worker")])
        self.settle(failed, first)
        feature = self.released_page([release_row("backend", 2, attempt=2), release_row("worker", 1)])
        second, _ = self.second_released(2, "build:backend#1")
        rows = [delivery("F-001", "backend", attempt=2), delivery("F-002", "backend")]
        record = record_page(2, rows, features=["F-001", "F-002"], retry_of="REL-001", title="Retry of F-001 with F-002", summary="F-001 is retried with F-002.")
        self.apply(
            "release-done",
            [{"path": FEATURE, "content": feature}, {"path": FEATURE_TWO, "content": second}, {"path": record_path(2), "content": record}],
            approver=self.owner,
        )
        self.assertEqual(("released", "none"), self.status())
        self.assertEqual(set(), self.errors())


class ReopenAfterBugFixTests(test_release_reopen.ReopenBoard):
    def test_reopen_dev_archives_the_row_a_bug_fix_updated_verbatim(self) -> None:
        fix = table(FIX_HEADER, [fix_row("backend", "build:backend#2")])
        verification = table(VERIFICATION_HEADER, [verification_row("backend", "build:backend#2")])
        self.put(BUG, bug_page("BUG-001", status="verified", apps=["backend"], fix=fix, verification=verification))
        released = bug_page("BUG-001", status="released", apps=["backend"], fix=fix, verification=verification, release=table(RELEASE_HEADER, [release_row("backend", 2, version="build:backend#2")]))
        feature = self.read(FEATURE).replace(release_row("backend", 1), release_row("backend", 2, version="build:backend#2"))
        record = record_page(2, [delivery("BUG-001", "backend", version="build:backend#2")], features=[], bugs=["BUG-001"], title="Fix of BUG-001", summary="BUG-001 is delivered.")
        self.apply("release-done", [{"path": FEATURE, "content": feature}, {"path": BUG, "content": released}, {"path": record_path(2), "content": record}], approver=self.owner)
        row = "| " + " | ".join(self.evidence().authoritative_release("backend").cells) + " |"
        self.assertIn("build:backend#2", row)
        self.apply("feature-reopen", self.dev_changes(("backend", "worker")), approver=self.owner)
        history = self.read(FEATURE).split("## Evidence history", 1)[1]
        self.assertIn(row.strip("| ").replace(" | ", " | "), history)
        self.assertEqual(["REL-001.md", "REL-002.md"], self.records())


if __name__ == "__main__":
    unittest.main()
