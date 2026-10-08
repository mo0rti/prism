"""Separation and evidence provenance: the journal, the excluded approvers and the checks (CONTRACTS 1.6).

The lifecycle evaluators that name an evidence row (`qa-pass`, `bug-verify`) land in later packages. These tests drive the
board's side of the contract: the journal binding, the exclusion functions and the checks that read them.
"""

from __future__ import annotations

import json
import sqlite3
import unittest
from unittest.mock import patch

from prism_cli.board_service import BoardError, _now
from tests.test_board_identity import FEATURE, SETTINGS, GatedBoardCase

POLICY_ON = "wiki-stale-after-days: 14\nqa-separate-from-dev: true"


def subject(item: str = "F-001", app: str = "backend", generation: int = 1, digest: str = "sha256:row-a", kind: str = "delivery") -> dict:
    return {"kind": kind, "item_id": item, "app": app, "generation": generation, "row_digest": digest}


class JournalCase(GatedBoardCase):
    def insert_operation(self, operation: str, approver, *, attempts=(), repair_of: str | None = None) -> None:
        intent = {"operation_id": operation, "actor": approver.to_dict(), "recovery_attempts": [{"actor": actor.to_dict()} for actor in attempts]}
        with self.service.store.transaction() as db:
            db.execute(
                "INSERT INTO operations(operation_id, participant_id, preview_id, payload_hash, intent_json, receipt_json, state, created_at, updated_at, repair_of) "
                "VALUES (?, ?, ?, 'sha256:x', ?, NULL, 'applied', ?, ?, ?)",
                (operation, approver.participant_id, f"preview-{operation}", json.dumps(intent), _now(), _now(), repair_of),
            )

    def produce(self, operation: str, *rows: dict) -> None:
        with self.service.store.transaction() as db:
            self.service._record_provenance(db, {"produces_evidence": list(rows)}, operation, _now())

    def policy(self, on: bool = True) -> None:
        text = self.read(SETTINGS)
        text = text.replace(POLICY_ON, "wiki-stale-after-days: 14")
        self.put(SETTINGS, text.replace("wiki-stale-after-days: 14", POLICY_ON) if on else text)

    def check(self, approver, *subjects) -> None:
        facts = self.service._trusted_facts(approver, {"separation_subjects": list(subjects)})
        self.service._assert_separation({"separation_subjects": list(subjects)}, facts)


class ProvenanceJournalTests(JournalCase):
    def test_an_evidence_row_is_found_by_its_whole_key_never_by_its_digest_alone(self) -> None:
        # Two features hold identical rows (same app, generation, digest): each resolves its own producing operation.
        self.insert_operation("dev-done-1", self.dev)
        self.insert_operation("dev-done-2", self.designer)
        self.produce("dev-done-1", subject("F-001"))
        self.produce("dev-done-2", subject("F-002"))
        lookup = self.service._producing_operation
        self.assertEqual({"status": "match", "operation_id": "dev-done-1"}, lookup("delivery", "F-001", "backend", 1, "sha256:row-a"))
        self.assertEqual({"status": "match", "operation_id": "dev-done-2"}, lookup("delivery", "F-002", "backend", 1, "sha256:row-a"))
        # A reopened row that reproduces an earlier digest is another generation, with its own producing operation.
        self.insert_operation("dev-done-3", self.po)
        self.produce("dev-done-3", subject("F-001", generation=2))
        self.assertEqual("dev-done-1", lookup("delivery", "F-001", "backend", 1, "sha256:row-a")["operation_id"])
        self.assertEqual("dev-done-3", lookup("delivery", "F-001", "backend", 2, "sha256:row-a")["operation_id"])
        # The same digest under another app, board item kind or generation is not a match.
        self.assertEqual("missing", lookup("delivery", "F-001", "other-app", 1, "sha256:row-a")["status"])
        self.assertEqual("missing", lookup("fix", "F-001", "backend", 1, "sha256:row-a")["status"])
        self.assertEqual("missing", lookup("delivery", "F-001", "backend", 3, "sha256:row-a")["status"])

    def test_a_digest_that_differs_from_the_journal_is_a_mismatch(self) -> None:
        self.insert_operation("dev-done-1", self.dev)
        self.produce("dev-done-1", subject())
        self.assertEqual("mismatch", self.service._producing_operation("delivery", "F-001", "backend", 1, "sha256:edited")["status"])

    def test_a_second_producing_operation_for_one_generation_is_refused(self) -> None:
        self.insert_operation("dev-done-1", self.dev)
        self.insert_operation("dev-done-2", self.dev)
        self.produce("dev-done-1", subject())
        with self.assertRaises(BoardError) as raised:
            self.produce("dev-done-2", subject(digest="sha256:row-b"))
        self.assertEqual(("evidence_generation_conflict", 409), (raised.exception.code, raised.exception.status))
        self.assertEqual("dev-done-1", self.service._producing_operation("delivery", "F-001", "backend", 1, "sha256:row-a")["operation_id"])

    def test_the_journal_is_scoped_to_the_board(self) -> None:
        self.insert_operation("dev-done-1", self.dev)
        self.produce("dev-done-1", subject())
        with patch.object(self.service, "_board_id", "00000000-0000-4000-8000-000000000000"):
            self.assertEqual("missing", self.service._producing_operation("delivery", "F-001", "backend", 1, "sha256:row-a")["status"])

    def test_the_excluded_approvers_are_the_approver_the_recoverers_and_the_repairers(self) -> None:
        recoverer = self.human("Rae", "dev")
        repairer = self.human("Remy", "dev")
        self.insert_operation("dev-done-1", self.dev, attempts=[recoverer])
        self.insert_operation("repair-1", repairer, repair_of="dev-done-1")
        self.insert_operation("elsewhere", self.po, repair_of="another-operation")
        self.assertEqual(
            {self.dev.participant_id, recoverer.participant_id, repairer.participant_id},
            self.service._excluded_approvers("dev-done-1"),
        )
        self.assertEqual(set(), self.service._excluded_approvers("no-such-operation"))

    def test_a_declared_producing_operation_is_recorded_with_the_intent_of_an_apply(self) -> None:
        original = self.service._validate_skill_semantics

        def producing(*args, **kwargs):
            result = original(*args, **kwargs)
            return {**result, "produces_evidence": [subject()]}

        with patch.object(self.service, "_validate_skill_semantics", side_effect=producing):
            preview = self.agent_proposal()
            receipt = self.approve(self.designer, preview, "dev-done-1")
        self.assertEqual("applied", receipt["state"])
        found = self.service._producing_operation("delivery", "F-001", "backend", 1, "sha256:row-a")
        self.assertEqual({"status": "match", "operation_id": "dev-done-1"}, found)
        # The same generation cannot be produced twice; the refused operation leaves no trace.
        self.put(FEATURE, self.read(FEATURE).replace("status: in-design", "status: ready-for-design"))
        self.put("knowledge/wiki/status-board.md", self.read("knowledge/wiki/status-board.md").replace("| in-design |", "| ready-for-design |"))
        with patch.object(self.service, "_validate_skill_semantics", side_effect=producing):
            again = self.agent_proposal()
            revision = self.review(self.designer, again)
            with self.assertRaises(BoardError) as raised:
                self.service.apply(self.designer, again["preview_id"], "dev-done-2", revision, True)
        self.assertEqual("evidence_generation_conflict", raised.exception.code)
        self.assertIsNone(self.service.store.connection.execute("SELECT 1 FROM operations WHERE operation_id = 'dev-done-2'").fetchone())
        self.assertIsNone(self.service.store.connection.execute("SELECT consumed_by FROM previews WHERE preview_id = ?", (again["preview_id"],)).fetchone()[0])


class SeparationCheckTests(JournalCase):
    def setUp(self) -> None:
        super().setUp()
        self.recoverer = self.human("Rae", "qa")
        self.quinn = self.human("Quinn", "qa")
        self.insert_operation("dev-done-1", self.dev, attempts=[self.recoverer])
        self.insert_operation("repair-1", self.po, repair_of="dev-done-1")
        self.produce("dev-done-1", subject(), subject(kind="fix", digest="sha256:fix-a"))
        self.policy(True)

    def refused(self, approver, *subjects) -> str:
        return self.code(lambda: self.check(approver, *subjects))

    def test_qa_pass_refuses_the_producing_approver_a_recoverer_and_a_repairer(self) -> None:
        for refused in (self.dev, self.recoverer, self.po):
            with self.subTest(approver=refused.name):
                self.assertEqual("separation_required", self.refused(refused, subject()))
        self.check(self.quinn, subject())

    def test_bug_verify_refuses_the_approver_of_the_fix(self) -> None:
        fix = subject(kind="fix", digest="sha256:fix-a")
        self.assertEqual("separation_required", self.refused(self.dev, fix))
        self.check(self.quinn, fix)

    def test_a_missing_entry_or_a_digest_mismatch_is_unverifiable(self) -> None:
        for unverifiable in (subject("F-009"), subject(digest="sha256:edited"), subject(generation=7)):
            with self.subTest(subject=unverifiable):
                self.assertEqual("separation_unverifiable", self.refused(self.quinn, unverifiable))
        self.assertEqual(("separation_unverifiable", 409), self.error_of(self.quinn, subject("F-009")))

    def error_of(self, approver, *subjects) -> tuple[str, int]:
        with self.assertRaises(BoardError) as raised:
            self.check(approver, *subjects)
        return raised.exception.code, raised.exception.status

    def test_a_refusal_is_a_403_and_names_the_item_and_app(self) -> None:
        with self.assertRaises(BoardError) as raised:
            self.check(self.dev, subject())
        self.assertEqual((403, {"item_id": "F-001", "app": "backend"}), (raised.exception.status, raised.exception.details))

    def test_nothing_is_enforced_while_the_setting_is_off(self) -> None:
        self.policy(False)
        self.check(self.dev, subject())
        self.check(self.quinn, subject("F-009"))

    def test_a_regrant_is_a_different_grant(self) -> None:
        self.service.revoke_participant(self.dev.participant_id)
        successor = self.human("Devi", "qa")
        self.check(successor, subject())

    def test_every_subject_of_an_action_is_checked(self) -> None:
        self.assertEqual("separation_required", self.refused(self.dev, subject(app="backend"), subject(kind="fix", digest="sha256:fix-a")))


class SeparationThroughApprovalTests(JournalCase):
    """A proposal that declares the evidence it verifies is held to the policy at preview, at apply and on recovery."""

    def setUp(self) -> None:
        super().setUp()
        self.quinn = self.human("Quinn", "designer")
        self.insert_operation("dev-done-1", self.designer)
        self.produce("dev-done-1", subject())
        self.policy(True)

    def with_subject(self):
        original = self.service._validate_skill_semantics

        def declaring(*args, **kwargs):
            return {**original(*args, **kwargs), "separation_subjects": [subject()]}

        return patch.object(self.service, "_validate_skill_semantics", side_effect=declaring)

    def test_the_agent_preview_warns_and_the_approver_is_checked_at_apply(self) -> None:
        with self.with_subject():
            preview = self.agent_proposal()
        self.assertIn(("separation-pending", "warning"), [(item["code"], item["status"]) for item in preview["checks"]])
        self.assertEqual("ready", preview["classification"])
        self.assertTrue(preview["applicable"])
        revision = self.review(self.designer, preview)
        self.assertEqual("separation_required", self.code(lambda: self.service.apply(self.designer, preview["preview_id"], "sep-1", revision, True)))
        self.assertIsNone(self.service.store.connection.execute("SELECT 1 FROM operations WHERE operation_id = 'sep-1'").fetchone())
        receipt = self.approve(self.quinn, preview, "sep-2")
        self.assertEqual("applied", receipt["state"], receipt)
        facts = json.loads(self.service.store.connection.execute("SELECT intent_json FROM operations WHERE operation_id = 'sep-2'").fetchone()[0])["approval"]["trusted_facts"]
        self.assertEqual("dev-done-1", facts["separation"]["delivery|F-001|backend|1"]["operation_id"])

    def test_a_human_direct_preview_refuses_an_excluded_approver_at_once(self) -> None:
        from prism_cli import wiki_transitions

        original = wiki_transitions.build_board_transition_preflight

        def declaring(*args, **kwargs):
            return {**original(*args, **kwargs), "separation_subjects": [subject()]}

        with patch.object(wiki_transitions, "build_board_transition_preflight", side_effect=declaring):
            with self.assertRaises(BoardError) as raised:
                self.service.preview_transition(self.designer, "F-001", "design-start", {"semantic_review_acknowledged": True})
            self.assertEqual("separation_required", raised.exception.code)
            preview = self.service.preview_transition(self.quinn, "F-001", "design-start", {"semantic_review_acknowledged": True})
        self.assertEqual("awaiting-approval", preview["approval"]["state"])

    def test_recovery_rechecks_separation_with_the_facts_of_the_recoverer(self) -> None:
        with self.with_subject():
            preview = self.agent_proposal()
        self.crash_after_first_write(self.quinn, preview, "sep-3")
        before = self.read("knowledge/wiki/status-board.md")
        # The producing approver of dev-done-1 holds the designer role and sees the operation, but cannot finish it.
        review = self.service.operation(self.designer, "sep-3")["recovery_review_revision"]
        refused = self.service.recover(self.designer, "sep-3", review, True)
        self.assertEqual("conflict", refused["state"], refused)
        self.assertIn("separation_required", refused["conflicts"][0]["reason"])
        self.assertEqual(before, self.read("knowledge/wiki/status-board.md"), "no write was made for the excluded recoverer")
        later = self.human("Lena", "designer")
        review = self.service.operation(later, "sep-3")["recovery_review_revision"]
        receipt = self.service.recover(later, "sep-3", review, True)
        self.assertEqual("applied", receipt["state"], receipt)
        excluded = self.service._excluded_approvers("sep-3")
        self.assertEqual({self.quinn.participant_id, self.designer.participant_id, later.participant_id}, excluded)


if __name__ == "__main__":
    unittest.main()
