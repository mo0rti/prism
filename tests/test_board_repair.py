"""operation-repair adopts the writes an abandoned operation already made and finishes the rest (CONTRACTS F27)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from prism_cli.board_service import Actor, BoardError
from prism_cli.wiki_lint import WikiDiagnostic
from tests.test_board_identity import BOARD, FEATURE, GatedBoardCase, _Crash


class RepairTests(GatedBoardCase):
    def abandon(self, operation: str, human: Actor) -> None:
        review = self.service.operation(human, operation)["recovery_review_revision"]
        failure = BoardError("checks_changed", "Current workflow checks no longer permit this action.", 409)
        with patch.object(self.service, "_revalidate_recovery", side_effect=failure):
            receipt = self.service.recover(human, operation, review, True, abandon=True)
        self.assertEqual("abandoned", receipt["state"], receipt)

    def abandoned_operation(self, operation: str = "pending-1") -> dict:
        preview = self.agent_proposal()
        self.crash_after_first_write(self.designer, preview, operation)
        self.abandon(operation, self.designer)
        return preview

    def repair_preview(self, actor: Actor, operation: str = "pending-1") -> dict:
        return self.service.preview_transition(actor, None, "operation-repair", {"semantic_review_acknowledged": True}, operation_id=operation)

    def test_a_repair_adopts_the_written_effects_and_journals_both_links(self) -> None:
        self.abandoned_operation()
        written = self.read(FEATURE)
        self.assertIn("| ready-for-design |", self.read(BOARD))
        preview = self.repair_preview(self.designer)
        self.assertEqual(("operation-repair", True), (preview["action"], preview["applicable"]))
        self.assertEqual({"all_of": ["designer"], "any_of": []}, preview["approval"]["required_roles"])
        self.assertEqual(["knowledge/wiki/status-board.md", "knowledge/wiki/log.md"], [write["path"] for write in preview["writes"]], "only the remaining writes")
        self.assertNotIn("repair_basis", preview)
        receipt = self.approve(self.designer, preview, "repair-1")
        self.assertEqual("applied", receipt["state"], receipt)
        self.assertEqual("pending-1", receipt["repair_of"])
        self.assertEqual(written, self.read(FEATURE), "the page that was already written is adopted unchanged")
        self.assertIn("| in-design | designer |", self.read(BOARD))
        connection = self.service.store.connection
        self.assertEqual("pending-1", connection.execute("SELECT repair_of FROM operations WHERE operation_id = 'repair-1'").fetchone()[0])
        self.assertEqual("repair-1", connection.execute("SELECT repaired_by FROM operations WHERE operation_id = 'pending-1'").fetchone()[0])
        self.assertEqual("pending-1", self.service.operation(self.designer, "repair-1")["repair_of"])
        self.assertEqual("repair_invalid", self.code(lambda: self.repair_preview(self.designer)), "a second repair of the same operation")

    def test_a_repair_needs_the_original_predicate_a_session_and_an_abandoned_operation(self) -> None:
        self.abandoned_operation()
        self.assertEqual("role_required", self.code(lambda: self.repair_preview(self.po)))
        self.assertEqual("operation_not_found", self.code(lambda: self.repair_preview(self.designer, "no-such-operation")))
        preview = self.repair_preview(self.designer)
        self.assertEqual(
            "approval_requires_board_session",
            self.code(lambda: self.service.apply(self.bearer("Dana"), preview["preview_id"], "repair-1", "x", True)),
        )
        self.assertEqual("preview_not_found", self.code(lambda: self.service.apply(self.agent, preview["preview_id"], "repair-1")), "the repair preview is not the agent's")
        self.assertEqual("approval_review_required", self.code(lambda: self.service.apply(self.designer, preview["preview_id"], "repair-1")))

    def test_an_operation_that_is_not_abandoned_cannot_be_repaired(self) -> None:
        preview = self.agent_proposal()
        self.crash_after_first_write(self.designer, preview, "pending-1")
        self.assertEqual("repair_invalid", self.code(lambda: self.repair_preview(self.designer)))
        self.service.apply(self.designer, preview["preview_id"], "pending-1")
        self.assertEqual("repair_invalid", self.code(lambda: self.repair_preview(self.designer)))

    def test_a_repair_of_an_ungated_operation_by_a_writable_human_still_needs_a_session(self) -> None:
        with patch("prism_cli.roles.required_roles", return_value=None):
            preview = self.agent_proposal()
            original = self.service._apply_write

            def interrupted(write, **kwargs):
                if write["role"] == "status-board":
                    raise _Crash()
                return original(write, **kwargs)

            with patch.object(self.service, "_apply_write", side_effect=interrupted):
                with self.assertRaises(_Crash):
                    self.service.apply(self.agent, preview["preview_id"], "ungated-1")
            self.abandon("ungated-1", self.dev)
            repair = self.service.preview_transition(self.dev, None, "operation-repair", None, operation_id="ungated-1")
            self.assertEqual({"all_of": [], "any_of": []}, repair["approval"]["required_roles"])
            self.assertEqual(
                "approval_requires_board_session",
                self.code(lambda: self.service.apply(self.bearer("Devi"), repair["preview_id"], "repair-1", "x", True)),
            )
            receipt = self.approve(self.dev, repair, "repair-1")
        self.assertEqual("applied", receipt["state"], receipt)

    def test_a_remaining_prerequisite_that_fails_refuses_the_repair_with_its_code(self) -> None:
        self.abandoned_operation()
        failure = BoardError("criterion_not_covered", "A criterion has no passing row.", 409)
        with patch.object(self.service, "_revalidate_recovery", side_effect=failure):
            self.assertEqual("criterion_not_covered", self.code(lambda: self.repair_preview(self.designer)))

    def test_a_write_that_matches_neither_state_cannot_be_adopted(self) -> None:
        self.abandoned_operation()
        self.put(BOARD, self.read(BOARD).replace("| ready-for-design | designer |", "| ready-for-design | po |"))
        self.assertEqual("repair_invalid", self.code(lambda: self.repair_preview(self.designer)))

    def test_a_repair_checks_that_the_written_pages_lint_clean(self) -> None:
        self.abandoned_operation()

        def diagnose(candidate):
            result = unittest.mock.Mock()
            result.diagnostics = [WikiDiagnostic("feature-status-not-minimum", "error", str(candidate / FEATURE), "The status is not the minimum.")]
            return result

        with patch("prism_cli.wiki_lint.lint_wiki", side_effect=diagnose):
            self.assertEqual("repair_invalid", self.code(lambda: self.repair_preview(self.designer)))

    def test_the_repairer_is_among_the_excluded_approvers_of_the_original(self) -> None:
        self.abandoned_operation()
        repairer = self.human("Dora", "designer")
        preview = self.repair_preview(repairer)
        self.approve(repairer, preview, "repair-1")
        self.assertEqual({self.designer.participant_id, repairer.participant_id}, self.service._excluded_approvers("pending-1"))


if __name__ == "__main__":
    unittest.main()
