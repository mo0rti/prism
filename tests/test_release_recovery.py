"""Recovery, repair and freshness of release operations at the service level (CONTRACTS 1.6, 6.2; cases 10.2 and 10.3)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from prism_cli.board_service import BoardError
from tests.board_approval import approve
from tests.release_support import FEATURE, ReleaseTests, delivery, record_page, record_path


class _Crash(Exception):
    pass


class ReleaseRecoveryTests(ReleaseTests):
    def crash_after(self, role: str, approver, preview: dict, operation: str) -> None:
        """Apply a gated preview and stop the process just before the write of `role`."""

        original = self.service._apply_write

        def interrupted(write, **kwargs):
            if write["role"] == role:
                raise _Crash()
            return original(write, **kwargs)

        review = self.service.get_preview(approver, preview["preview_id"])["approval"]["review_revision"]
        with patch.object(self.service, "_apply_write", side_effect=interrupted):
            with self.assertRaises(_Crash):
                self.service.apply(approver, preview["preview_id"], operation, review, True)

    def abandon(self, human, operation: str) -> None:
        review = self.service.operation(human, operation)["recovery_review_revision"]
        failure = BoardError("checks_changed", "Current workflow checks no longer permit this action.", 409)
        with patch.object(self.service, "_revalidate_recovery", side_effect=failure):
            receipt = self.service.recover(human, operation, review, True, abandon=True)
        self.assertEqual("abandoned", receipt["state"], receipt)

    def test_a_crashed_release_rolls_forward_and_the_record_keeps_its_number_and_operation(self) -> None:
        preview = self.ready("release-done", self.release_changes())
        self.crash_after("status-board", self.owner, preview, "pending-1")
        # The pages and the record are written; the retry by the same approver finishes the operation.
        self.assertEqual(["REL-001.md"], self.records())
        receipt = self.service.apply(self.owner, preview["preview_id"], "pending-1")
        self.assertEqual("applied", receipt["state"])
        self.assertEqual("pending-1", self.record(1)[0]["operation"])
        self.assertEqual(["REL-001.md"], self.records())
        self.assertEqual(("released", "none"), self.status())
        self.assertEqual(set(), self.errors())

    def test_another_release_human_recovers_the_operation_after_renewed_review(self) -> None:
        preview = self.ready("release-done", self.release_changes())
        self.crash_after("status-board", self.owner, preview, "pending-1")
        other = self.service.authenticate(self.service.create_participant("Rae", "human", True, roles="release")["token"], via_session=True)
        review = self.service.operation(other, "pending-1")["recovery_review_revision"]
        receipt = self.service.recover(other, "pending-1", review, True)
        self.assertEqual("applied", receipt["state"])
        self.assertEqual("pending-1", self.record(1)[0]["operation"])
        self.assertEqual(set(), self.errors())

    def test_a_repair_of_an_abandoned_release_keeps_the_number_it_was_previewed_with(self) -> None:
        preview = self.ready("release-done", self.release_changes())
        self.crash_after("status-board", self.owner, preview, "pending-1")
        self.abandon(self.owner, "pending-1")
        # The abandoned operation left REL-001 on disk; the next free number is 2, and the repair still finishes REL-001.
        self.assertEqual(["REL-001.md"], self.records())
        repair = self.service.preview_transition(self.owner, None, "operation-repair", {"semantic_review_acknowledged": True}, operation_id="pending-1")
        self.assertEqual("applied", approve(self.service, self.owner, repair, "repair-1")["state"])
        self.assertEqual(["REL-001.md"], self.records())
        self.assertEqual("pending-1", self.record(1)[0]["operation"], "repair leaves the operation unchanged")
        self.assertEqual(("released", "none"), self.status())
        self.assertEqual(set(), self.errors())

    def test_a_record_written_after_the_preview_makes_the_preview_stale(self) -> None:
        preview = self.ready("release-done", self.release_changes())
        self.put(record_path(1), record_page(1, [delivery("F-002", "backend")], features=["F-002"]))
        review = self.service.get_preview(self.owner, preview["preview_id"])["approval"]["review_revision"]
        with self.assertRaises(BoardError) as caught:
            self.service.apply(self.owner, preview["preview_id"], "operation-1", review, True)
        self.assertEqual(("stale_preview", 409), (caught.exception.code, caught.exception.status))
        self.assertEqual(("ready-for-release", "release"), self.status())

    def test_a_second_preview_for_the_same_number_loses_to_the_first_apply(self) -> None:
        first = self.ready("release-done", self.release_changes())
        second_changes = self.release_changes()
        second = self.ready("release-done", second_changes)
        self.assertEqual("applied", approve(self.service, self.owner, first, "operation-1")["state"])
        review = self.service.get_preview(self.owner, second["preview_id"])["approval"]["review_revision"]
        with self.assertRaises(BoardError) as caught:
            self.service.apply(self.owner, second["preview_id"], "operation-2", review, True)
        self.assertIn(caught.exception.code, {"stale_preview", "release_id_taken", "conflict"})
        self.assertEqual(["REL-001.md"], self.records())

    def test_the_feature_page_changed_after_the_preview_makes_it_stale(self) -> None:
        preview = self.ready("release-done", self.release_changes())
        self.put(FEATURE, self.read(FEATURE) + "\nA note added by someone else.\n")
        review = self.service.get_preview(self.owner, preview["preview_id"])["approval"]["review_revision"]
        with self.assertRaises(BoardError) as caught:
            self.service.apply(self.owner, preview["preview_id"], "operation-1", review, True)
        self.assertIn(caught.exception.code, {"stale_preview", "stale_write"})
        self.assertEqual([], self.records())


if __name__ == "__main__":
    unittest.main()
