"""Real journal, filesystem, and retry behavior in adopted neutral workspaces."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from prism_cli.board_service import BoardError, BoardService
from prism_cli.workflow_install import apply_install, plan_install
from tests.test_core_workflow_fixture import _feature_page, _write_index
from tests import real_temp  # noqa: F401


class SimulatedCrash(BaseException):
    pass


class BoardOperationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        apply_install(self.root, plan_install(self.root, name="Document review", apps=["backend"]))
        self.feature = "knowledge/wiki/features/F-001-document-review.md"
        self.board = "knowledge/wiki/status-board.md"
        self.log = "knowledge/wiki/log.md"
        source = self.root / "knowledge/intake/processed/2026-10-06-document-review-brief/brief.md"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"# Document review\nRecord a summary and outcome.\n")
        self.put(self.feature, _feature_page().replace("status: raw", "status: ready-for-design").replace("owner: po", "owner: designer").replace("| po | open |", "| po | resolved: Summarize key points. |"))
        _write_index(self.root, "ready-for-design", "designer")
        self.service = BoardService(self.root).start()
        self.addCleanup(lambda: self.service.close())
        self.grant = self.service.create_participant("Reviewer", "human", True)
        self.actor = self.service.authenticate(self.grant["token"])

    def put(self, relative, content):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode("utf-8"))

    def read(self, relative):
        return (self.root / relative).read_bytes().decode("utf-8")

    def preview(self, feature="F-001"):
        result = self.service.preview_transition(self.actor, feature, "design-start", {"semantic_review_acknowledged": True})
        self.assertTrue(result["applicable"], result)
        return result

    def apply(self, preview, operation="test-operation"):
        return self.service.apply(self.actor, preview["preview_id"], operation)

    def partial(self, preview, operation="test-operation", crash=False):
        original = self.service._apply_write
        def interrupted(write, **kwargs):
            if write["role"] == "status-board":
                if crash:
                    raise SimulatedCrash()
                raise OSError("synthetic write failure")
            return original(write, **kwargs)
        with patch.object(self.service, "_apply_write", side_effect=interrupted):
            if crash:
                with self.assertRaises(SimulatedCrash):
                    self.apply(preview, operation)
            else:
                receipt = self.apply(preview, operation)
                self.assertEqual("conflict", receipt["state"])

    def interrupted_agent_operation(self, operation="agent-operation"):
        from tests.test_board_service import _read_revisions

        grant = self.service.create_participant("Coding agent", "agent", True)
        agent = self.service.authenticate(grant["token"])
        content = self.read(self.feature).replace("status: ready-for-design", "status: in-design")
        changes = [{"path": self.feature, "content": content}]
        preview = self.service.preview_skill(agent, "design-start", changes, read_revisions=_read_revisions(self.service, agent, "design-start", changes))
        self.assertTrue(preview["applicable"], preview)
        human = self.actor
        try:
            self.actor = agent
            self.partial(preview, operation, crash=True)
        finally:
            self.actor = human
        return grant, agent, preview

    def test_human_recovers_revoked_agent_with_review_and_distinct_attribution(self):
        grant, agent, preview = self.interrupted_agent_operation()
        self.service.revoke_participant(agent.participant_id)
        self.assertIn("agent-operation", [item["operation_id"] for item in self.service.discover(self.actor)["pending_operations"]])
        inspected = self.service.operation(self.actor, "agent-operation")
        self.assertEqual(agent.participant_id, inspected["actor"]["participant_id"])
        self.assertEqual(["applied", "pending", "pending"], [item["state"] for item in inspected["remaining_changes"]])
        for revision, acknowledged in [(None, False), (inspected["recovery_review_revision"], False)]:
            with self.assertRaises(BoardError) as error:
                self.service.recover(self.actor, "agent-operation", revision, acknowledged)
            self.assertEqual("recovery_review_required", error.exception.code)
        # Preserve unrelated work that arrives while the human reviews the
        # target row and remaining writes.
        extra = "| F-002 | Keep unrelated work | raw | po | not-needed |\n"
        self.put(self.board, self.read(self.board) + extra)
        self.put(self.log, self.read(self.log) + "\nExternal note during recovery review.\n")
        receipt = self.service.recover(self.actor, "agent-operation", inspected["recovery_review_revision"], True)
        self.assertEqual("applied", receipt["state"], receipt)
        self.assertEqual(agent.participant_id, receipt["actor"]["participant_id"])
        self.assertEqual(self.actor.participant_id, receipt["recovered_by"]["participant_id"])
        self.assertEqual(1, len(receipt["recovery_attempts"]))
        self.assertIn(extra, self.read(self.board))
        self.assertIn("External note during recovery review.", self.read(self.log))
        self.assertEqual(1, self.read(self.log).count(f"<!-- prism:board-history:v1 preview={preview['preview_id']} -->"))
        self.assertEqual(receipt, self.service.recover(self.actor, "agent-operation", inspected["recovery_review_revision"], True))
        events = self.service.changes(self.actor)["changes"]
        self.assertEqual(["operation-recovery-started", "operation-applied"], [event["event"]["type"] for event in events])

    def test_cross_participant_recovery_is_limited_to_writable_humans_and_agent_operations(self):
        self.interrupted_agent_operation()
        for kind, writable in [("agent", True), ("human", False)]:
            grant = self.service.create_participant("Other participant", kind, writable)
            other = self.service.authenticate(grant["token"])
            self.assertNotIn("agent-operation", [item["operation_id"] for item in self.service.discover(other)["pending_operations"]])
            with self.assertRaises(BoardError):
                self.service.operation(other, "agent-operation")
            with self.assertRaises(BoardError):
                self.service.recover(other, "agent-operation", "arbitrary-review", True)
        # A writable human does not acquire another human's interrupted intent.
        self.put(self.feature, self.read(self.feature).replace("status: in-design", "status: ready-for-design"))
        # Use a distinct feature so unresolved agent work cannot overlap.
        self.put("knowledge/wiki/features/F-002-second-review.md", self.read(self.feature).replace("F-001", "F-002"))
        self.put(self.board, self.read(self.board) + "| F-002 | Second review | ready-for-design | designer | not-needed |\n")
        preview = self.preview("F-002")
        self.partial(preview, "human-operation", crash=True)
        other_grant = self.service.create_participant("Other human", "human", True)
        other = self.service.authenticate(other_grant["token"])
        with self.assertRaises(BoardError) as error:
            self.service.operation(other, "human-operation")
        self.assertEqual("operation_not_found", error.exception.code)

    def test_human_recovery_review_is_fresh_participant_bound_and_revocable(self):
        self.interrupted_agent_operation()
        inspected = self.service.operation(self.actor, "agent-operation")
        other_grant = self.service.create_participant("Second reviewer", "human", True)
        other = self.service.authenticate(other_grant["token"])
        with self.assertRaises(BoardError) as error:
            self.service.recover(other, "agent-operation", inspected["recovery_review_revision"], True)
        self.assertEqual("stale_recovery_review", error.exception.code)
        self.put(self.feature, self.read(self.feature) + "\nExternal relevant edit.\n")
        index, log = self.read(self.board), self.read(self.log)
        with self.assertRaises(BoardError) as error:
            self.service.recover(self.actor, "agent-operation", inspected["recovery_review_revision"], True)
        self.assertEqual("stale_recovery_review", error.exception.code)
        self.assertEqual((index, log), (self.read(self.board), self.read(self.log)))
        self.service.revoke_participant(self.actor.participant_id)
        with self.assertRaises(BoardError) as error:
            self.service.recover(self.actor, "agent-operation", inspected["recovery_review_revision"], True)
        self.assertEqual(401, error.exception.status)

    def test_human_recovery_intent_survives_another_crash_and_reviewer_revocation(self):
        _grant, agent, _preview = self.interrupted_agent_operation()
        self.service.revoke_participant(agent.participant_id)
        inspected = self.service.operation(self.actor, "agent-operation")
        original = self.service._apply_write
        def interrupted(write, **kwargs):
            if write["role"] == "log":
                raise SimulatedCrash()
            return original(write, **kwargs)
        with patch.object(self.service, "_apply_write", side_effect=interrupted):
            with self.assertRaises(SimulatedCrash):
                self.service.recover(self.actor, "agent-operation", inspected["recovery_review_revision"], True)
        self.service.close()
        self.service = BoardService(self.root).start()
        self.service.revoke_participant(self.actor.participant_id)
        other_grant = self.service.create_participant("Recovery reviewer", "human", True)
        other = self.service.authenticate(other_grant["token"])
        latest = self.service.operation(other, "agent-operation")
        self.assertEqual(["applied", "applied", "pending"], [item["state"] for item in latest["remaining_changes"]])
        receipt = self.service.recover(other, "agent-operation", latest["recovery_review_revision"], True)
        self.assertEqual("applied", receipt["state"], receipt)
        self.assertEqual(agent.participant_id, receipt["actor"]["participant_id"])
        self.assertEqual(other.participant_id, receipt["recovered_by"]["participant_id"])
        self.assertEqual(2, len(receipt["recovery_attempts"]))

    def test_preview_requires_semantic_confirmation_and_does_not_edit_wiki(self):
        before = {path: self.read(path) for path in (self.feature, self.board, self.log)}
        preview = self.service.preview_transition(self.actor, "F-001", "design-start")
        self.assertFalse(preview["applicable"])
        with self.assertRaises(BoardError) as error:
            self.apply(preview)
        self.assertEqual("preview_blocked", error.exception.code)
        self.assertEqual(before, {path: self.read(path) for path in before})

    def test_concurrent_duplicate_delivery_has_one_receipt_and_history_entry(self):
        preview = self.preview()
        with ThreadPoolExecutor(max_workers=2) as executor:
            receipts = list(executor.map(lambda _: self.apply(preview), range(2)))
        self.assertEqual(receipts[0], receipts[1])
        self.assertEqual("applied", receipts[0]["state"])
        self.assertEqual(1, self.service.store.connection.execute("SELECT COUNT(*) FROM events").fetchone()[0])
        self.assertEqual(1, self.read(self.log).count(f"<!-- prism:board-history:v1 preview={preview['preview_id']} -->"))
        self.assertEqual(receipts[0], self.service.operation(self.actor, "test-operation")["receipt"])

    def test_unrelated_status_board_bytes_and_log_append_are_preserved(self):
        preview = self.preview()
        extra = "| F-002 | Keep  exact spacing | raw | po | not-needed |\r\n"
        self.put(self.board, self.read(self.board).replace("\r\n", "\n").replace("\n", "\r\n") + extra)
        old_log = self.read(self.log) + "\r\nExternal human note: preserve these bytes.\r\n"
        self.put(self.log, old_log)
        self.assertEqual("applied", self.apply(preview)["state"])
        self.assertIn(extra, self.read(self.board))
        self.assertTrue(self.read(self.log).startswith(old_log))

    def test_relevant_change_and_target_row_change_reject_before_journaling(self):
        preview = self.preview()
        self.put(self.feature, self.read(self.feature) + "\nA new relevant observation.\n")
        with self.assertRaises(BoardError) as error:
            self.apply(preview)
        self.assertEqual("stale_preview", error.exception.code)
        self.assertEqual(0, self.service.store.connection.execute("SELECT COUNT(*) FROM operations").fetchone()[0])
        fresh = self.preview()
        self.put(self.board, self.read(self.board).replace("| designer |", "| po |"))
        with self.assertRaises(BoardError) as error:
            self.apply(fresh)
        self.assertEqual("stale_status_row", error.exception.code)

    def test_a_fresh_apply_does_not_evaluate_the_operation_a_second_time(self):
        # The apply that records an operation has just revalidated it against the live files, so its roll-forward skips the
        # second full evaluation; every path that picks an operation up later still runs it.
        preview = self.preview()
        with patch.object(self.service, "_revalidate_recovery", wraps=self.service._revalidate_recovery) as revalidation:
            receipt = self.apply(preview)
        self.assertEqual("applied", receipt["state"], receipt)
        self.assertEqual(0, revalidation.call_count)
        self.assertIn("status: in-design", self.read(self.feature))

    def test_recovery_and_a_retried_apply_of_a_pending_operation_revalidate_in_full(self):
        preview = self.preview()
        self.partial(preview, crash=True)
        with patch.object(self.service, "_revalidate_recovery", wraps=self.service._revalidate_recovery) as revalidation:
            retried = self.apply(preview)
        self.assertEqual("applied", retried["state"], retried)
        self.assertEqual(1, revalidation.call_count, "an apply that finds its operation pending revalidates it")
        self.assertIn("| in-design | designer |", self.read(self.board))

    def test_a_source_edited_after_the_validation_still_stops_the_roll_forward_before_any_write(self):
        preview = self.preview()
        original = self.service._recovery_preflight
        settings = "knowledge/wiki/SETTINGS.md"

        def edit_then_check(*arguments, **keywords):
            self.put(settings, self.read(settings) + "\nChanged relevant policy after the validation.\n")
            return original(*arguments, **keywords)

        board, log = self.read(self.board), self.read(self.log)
        with patch.object(self.service, "_recovery_preflight", side_effect=edit_then_check):
            receipt = self.apply(preview)
        self.assertEqual("conflict", receipt["state"], receipt)
        self.assertIn("recovery_source_changed", receipt["conflicts"][0]["reason"])
        self.assertEqual((board, log), (self.read(self.board), self.read(self.log)), "no write was made")
        self.assertIn("status: ready-for-design", self.read(self.feature))

    def test_process_crash_recovers_recorded_remaining_files_after_restart(self):
        preview = self.preview()
        self.partial(preview, crash=True)
        self.assertIn("status: in-design", self.read(self.feature))
        self.service.close()
        self.service = BoardService(self.root).start()
        self.actor = self.service.authenticate(self.grant["token"])
        pending = self.service.operation(self.actor, "test-operation")
        self.assertEqual("pending", pending["state"])
        self.assertEqual(["applied", "pending", "pending"], [item["state"] for item in pending["remaining_changes"]])
        receipt = self.service.recover(self.actor, "test-operation")
        self.assertEqual("applied", receipt["state"], receipt)
        self.assertIn("| in-design | designer |", self.read(self.board))
        self.assertEqual(receipt, self.apply(preview))

    def test_partial_recovery_rejects_changed_relevant_source_without_more_writes(self):
        preview = self.preview()
        self.partial(preview)
        index, log = self.read(self.board), self.read(self.log)
        settings = "knowledge/wiki/SETTINGS.md"
        self.put(settings, self.read(settings) + "\nChanged relevant policy.\n")
        receipt = self.service.recover(self.actor, "test-operation")
        self.assertEqual("conflict", receipt["state"])
        self.assertIn("recovery_source_changed", receipt["conflicts"][0]["reason"])
        self.assertEqual(index, self.read(self.board))
        self.assertEqual(log, self.read(self.log))

    def test_partial_recovery_preserves_manual_edit_to_already_written_file(self):
        preview = self.preview()
        self.partial(preview)
        edited = self.read(self.feature) + "\nHuman correction after interruption.\n"
        self.put(self.feature, edited)
        receipt = self.service.recover(self.actor, "test-operation")
        self.assertEqual("conflict", receipt["state"])
        self.assertEqual(edited, self.read(self.feature))

    def test_conflict_is_reported_once_in_changes_and_survives_repeated_recovery(self):
        preview = self.preview()
        self.partial(preview, crash=True)
        edited = self.read(self.feature) + "\nHuman correction after interruption.\n"
        self.put(self.feature, edited)
        for _ in range(3):
            receipt = self.service.recover(self.actor, "test-operation")
            self.assertEqual("conflict", receipt["state"])
        conflicts = [item for item in self.service.changes(self.actor)["changes"] if item["event"]["type"] == "operation-conflict"]
        self.assertEqual(1, len(conflicts))
        self.assertEqual("test-operation", conflicts[0]["operation_id"])
        self.assertEqual({"type": "operation-conflict", "operation_id": "test-operation", "paths": [self.feature]}, conflicts[0]["event"])
        self.assertNotIn("Human correction", str(conflicts[0]))

    def test_unrelated_operation_can_finish_while_first_is_pending(self):
        feature2 = "knowledge/wiki/features/F-002-another-review.md"
        self.put(feature2, self.read(self.feature).replace("F-001", "F-002"))
        self.put(self.board, self.read(self.board) + "| F-002 | Document review | ready-for-design | designer | not-needed |\n")
        first, second = self.preview(), self.preview("F-002")
        self.partial(first, "first")
        receipt = self.apply(second, "second")
        self.assertEqual("applied", receipt["state"], receipt)
        self.assertEqual("applied", self.service.recover(self.actor, "first")["state"])
        self.assertIn("status: in-design", self.read(feature2))
        self.assertEqual(3, self.service.store.connection.execute("SELECT COUNT(*) FROM events").fetchone()[0])

    def test_completed_files_can_finalize_receipt_after_later_source_change(self):
        preview = self.preview()
        original = self.service._apply_write
        def after_last(write, **kwargs):
            result = original(write, **kwargs)
            if write["role"] == "log":
                raise SimulatedCrash()
            return result
        with patch.object(self.service, "_apply_write", side_effect=after_last), self.assertRaises(SimulatedCrash):
            self.apply(preview)
        settings = "knowledge/wiki/SETTINGS.md"
        self.put(settings, self.read(settings) + "\nLater policy after completed writes.\n")
        receipt = self.service.recover(self.actor, "test-operation")
        self.assertEqual("applied", receipt["state"], receipt)
        self.assertEqual(1, self.service.store.connection.execute("SELECT COUNT(*) FROM events").fetchone()[0])

    def test_external_edit_between_temp_write_and_replace_is_not_overwritten(self):
        preview = self.preview()
        original = __import__("os").fsync
        edited = self.read(self.feature) + "\nConcurrent editor change.\n"
        changed = False
        def before_replace(fd):
            nonlocal changed
            original(fd)
            if not changed:
                changed = True
                self.put(self.feature, edited)
        with patch("prism_cli.board_service.os.fsync", side_effect=before_replace):
            receipt = self.apply(preview)
        self.assertEqual("conflict", receipt["state"])
        self.assertEqual(edited, self.read(self.feature))
        self.assertFalse(list(self.root.rglob(".prism-write-*")))

    def test_revoked_actor_cannot_apply_or_recover_and_other_actor_cannot_use_preview(self):
        preview = self.preview()
        other = self.service.create_participant("Other reviewer", "human", True)
        with self.assertRaises(BoardError) as error:
            self.service.apply(self.service.authenticate(other["token"]), preview["preview_id"], "other")
        self.assertEqual("preview_not_found", error.exception.code)
        self.partial(preview)
        self.service.revoke_participant(self.actor.participant_id)
        for call in (lambda: self.apply(preview), lambda: self.service.recover(self.actor, "test-operation")):
            with self.assertRaises(BoardError) as error:
                call()
            self.assertEqual("unauthorized", error.exception.code)

    def test_moved_tree_requires_exact_recorded_files_and_directories(self):
        source = self.root / "knowledge/intake/pending/new-brief"
        source.mkdir()
        (source / "empty").mkdir()
        (source / "brief.md").write_bytes(b"# Brief\n")
        destination = self.root / "knowledge/intake/processed/new-brief"
        move = {"source": source.relative_to(self.root).as_posix(), "destination": destination.relative_to(self.root).as_posix(), "source_digest": self.service._tree_digest(source), "source_files": self.service._tree_snapshot(source), "source_directories": self.service._tree_directories(source)}
        intent = {"moves": [move], "writes": []}
        self.assertEqual("pending", self.service._move_state(move, intent))
        source.rename(destination)
        self.assertEqual("applied", self.service._move_state(move, intent))
        (destination / "unexpected").mkdir()
        with self.assertRaises(BoardError):
            self.service._move_state(move, intent)
        (destination / "unexpected").rmdir()
        (destination / "empty").rmdir()
        with self.assertRaises(BoardError):
            self.service._move_state(move, intent)

    def test_marker_alone_is_not_proof_of_complete_history_entry(self):
        preview = self.preview()
        self.partial(preview)
        marker = f"<!-- prism:board-history:v1 preview={preview['preview_id']} -->"
        self.put(self.log, self.read(self.log) + marker + "\nTruncated entry\n")
        receipt = self.service.recover(self.actor, "test-operation")
        self.assertEqual("conflict", receipt["state"])
        self.assertIn("ready-for-design", self.read(self.board))

    def test_calendar_change_rechecks_rules_without_inventing_source_edit(self):
        clock = Mock(wraps=date)
        clock.today.return_value = date(2026, 9, 22)
        with patch("prism_cli.wiki_transitions.date", clock), patch("prism_cli.wiki_lint.date", clock):
            preview = self.preview()
            clock.today.return_value = date(2026, 9, 23)
            receipt = self.apply(preview)
        self.assertEqual("applied", receipt["state"], receipt)

    def test_preview_is_bound_to_one_operation_and_operation_to_one_payload(self):
        first, second = self.preview(), self.preview()
        self.apply(first)
        with self.assertRaises(BoardError) as error:
            self.apply(first, "different-operation")
        self.assertEqual("preview_already_submitted", error.exception.code)
        with self.assertRaises(BoardError) as error:
            self.apply(second)
        self.assertEqual("operation_id_reused", error.exception.code)

    def test_new_linked_context_requires_a_new_preview(self):
        preview = self.preview()
        self.put("knowledge/wiki/advisory/F-001-review.md", "---\nfeature-id: F-001\n---\nA new advisory record.\n")
        with self.assertRaises(BoardError) as error:
            self.apply(preview)
        self.assertEqual("stale_preview", error.exception.code)


if __name__ == "__main__":
    unittest.main()
