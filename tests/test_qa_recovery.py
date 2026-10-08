"""Recovery, repair and separation of QA operations at the service level (CONTRACTS 1.6, 9; cases 17, 45, 48)."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from prism_cli.board_service import BoardError
from prism_cli.wiki_lint import lint_wiki
from tests.board_approval import approve
from tests.qa_support import BUGS, FEATURE, QaBoard, app_row, bug_page, integration_row, release_row

BUG = f"{BUGS}/BUG-001-summary-export-drops-comments.md"


class _Crash(Exception):
    pass


class QaRecoveryTests(QaBoard):
    def pass_both(self) -> str:
        page = self.qa_table([app_row("backend"), app_row("worker"), integration_row()])
        return self.with_status("ready-for-release", "release", self.release_table([release_row("backend"), release_row("worker")], page))

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

    def errors(self) -> set[str]:
        return {item.code for item in lint_wiki(self.root).diagnostics if item.severity == "error"}

    def test_an_operation_that_creates_a_bug_rolls_forward_after_a_crash(self) -> None:
        changes = [{"path": FEATURE, "content": self.qa_table([app_row("worker", result="fail")])}, {"path": BUG, "content": bug_page("BUG-001")}]
        preview = self.ready("qa-verify", changes)
        self.crash_after("status-board", self.quinn, preview, "pending-1")
        # The feature page and the bug page are written; the retry by the same approver finishes the operation, with no stale preview.
        self.assertTrue((self.root / BUG).is_file())
        receipt = self.service.apply(self.quinn, preview["preview_id"], "pending-1")
        self.assertEqual("applied", receipt["state"])
        self.assertEqual(set(), self.errors())

    def test_another_qa_human_recovers_a_qa_fail_after_renewed_review(self) -> None:
        evidence = self.evidence()
        self.assertTrue(evidence.delivery)
        preview = self.ready("qa-verify", [{"path": FEATURE, "content": self.qa_table([app_row("backend")])}])
        self.crash_after("status-board", self.quinn, preview, "pending-1")
        other = self.service.authenticate(self.service.create_participant("Rae", "human", True, roles="qa")["token"], via_session=True)
        review = self.service.operation(other, "pending-1")["recovery_review_revision"]
        receipt = self.service.recover(other, "pending-1", review, True)
        self.assertEqual("applied", receipt["state"])
        self.assertEqual(set(), self.errors())

    def test_a_qa_pass_that_the_delivering_grant_approved_and_abandoned_cannot_be_repaired_by_it_once_separation_is_on(self) -> None:
        # Separation is off, so `owner`, who approved both deliveries, approves the pass; the operation is abandoned after its first write.
        preview = self.ready("qa-pass", [{"path": FEATURE, "content": self.pass_both()}])
        self.crash_after("status-board", self.owner, preview, "pending-1")
        self.abandon(self.owner, "pending-1")
        self.set_policy(True)
        with self.assertRaises(BoardError) as caught:
            self.service.preview_transition(self.owner, None, "operation-repair", {"semantic_review_acknowledged": True}, operation_id="pending-1")
        self.assertEqual(("separation_required", 403), (caught.exception.code, caught.exception.status))
        # A grant that did not produce the delivery repairs it.
        repair = self.service.preview_transition(self.quinn, None, "operation-repair", {"semantic_review_acknowledged": True}, operation_id="pending-1")
        self.assertEqual("applied", approve(self.service, self.quinn, repair, "repair-1")["state"])
        self.assertEqual(("ready-for-release", "release"), self.status())

    def operation_of_delivery(self, app: str) -> str:
        row = self.service.store.connection.execute(
            "SELECT operation_id FROM provenance WHERE item_id = 'F-001' AND app = ? AND kind = 'delivery'", (app,)
        ).fetchone()
        return row[0]

    def test_a_human_who_recovered_or_repaired_the_delivery_is_excluded_too(self) -> None:
        self.set_policy(True)
        recoverer = self.service.authenticate(self.service.create_participant("Rae", "human", True, roles="qa")["token"], via_session=True)
        repairer = self.service.authenticate(self.service.create_participant("Remy", "human", True, roles="qa")["token"], via_session=True)
        operation = self.operation_of_delivery("worker")
        with self.service.store.transaction() as db:
            row = db.execute("SELECT intent_json FROM operations WHERE operation_id = ?", (operation,)).fetchone()
            intent = json.loads(row[0])
            intent["recovery_attempts"] = [{"actor": recoverer.to_dict()}]
            db.execute("UPDATE operations SET intent_json = ? WHERE operation_id = ?", (json.dumps(intent), operation))
            db.execute(
                "INSERT INTO operations(operation_id, participant_id, preview_id, payload_hash, intent_json, receipt_json, state, created_at, updated_at, repair_of) "
                "VALUES ('repair-of-delivery', ?, 'preview-x', 'sha256:x', '{}', NULL, 'applied', '2026-10-08T00:00:00Z', '2026-10-08T00:00:00Z', ?)",
                (repairer.participant_id, operation),
            )
        preview = self.ready("qa-pass", [{"path": FEATURE, "content": self.pass_both()}])
        for index, excluded in enumerate((recoverer, repairer, self.owner)):
            review = self.service.get_preview(excluded, preview["preview_id"])["approval"]["review_revision"]
            with self.subTest(grant=excluded.name), self.assertRaises(BoardError) as caught:
                self.service.apply(excluded, preview["preview_id"], f"operation-{index}", review, True)
            self.assertEqual("separation_required", caught.exception.code)
        self.assertEqual("applied", approve(self.service, self.quinn, preview, "operation-quinn")["state"])


if __name__ == "__main__":
    unittest.main()
