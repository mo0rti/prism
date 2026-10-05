"""Regression tests for the independent release-review findings: stuck operations, unportable names,
line endings, sub-folder pages, change cursors and stale previews."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import yaml

from prism_cli.board_service import BoardError, BoardService
from prism_cli.board_store import unresolved_board_operations
from prism_cli.workflow_assets import asset_digest
from tests.core_workflow_fixture import FEATURE_PATH, INTAKE_ITEM, create_core_workflow_fixture
from tests.test_board_service import _design_page, _read_revisions
from tests.test_core_workflow_fixture import _feature_page
from tests import real_temp  # noqa: F401


class _Crash(BaseException):
    """A process crash that no handler in the service may swallow."""


FEATURE = FEATURE_PATH.as_posix()
SETTINGS = "knowledge/wiki/SETTINGS.md"
NEW_QUESTION = "| 2 | How should the review be organized? | designer | open |"


class BoardReviewFixTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = create_core_workflow_fixture(Path(temporary.name) / "board")
        manifest_path = self.root / "prism.workspace.yml"
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        manifest["workflow"] = {
            "version": "1",
            "board_id": "3a8db764-f386-461e-bb0b-165de1dcf3a9",
            "mode": "workflow",
            "asset_digest": asset_digest("1"),
        }
        manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
        feature = self.root / FEATURE
        feature.parent.mkdir(parents=True, exist_ok=True)
        feature.write_bytes(_feature_page().encode("utf-8"))
        self.service = BoardService(self.root).start()
        self.addCleanup(self.service.close)
        self.agent = self.service.authenticate(self.service.create_participant("Agent", "agent", writable=True)["token"])
        self.human = self.service.authenticate(self.service.create_participant("Owner", "human", writable=True)["token"])

    # -- helpers -----------------------------------------------------------------

    def read(self, relative: str) -> str:
        return (self.root / relative).read_bytes().decode("utf-8")

    def read_optional(self, relative: str) -> str | None:
        path = self.root / relative
        return path.read_bytes().decode("utf-8") if path.exists() else None

    def put(self, relative: str, content: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode("utf-8"))

    def ask_preview(self) -> dict:
        original = self.read(FEATURE)
        marker = "| 1 | Which points should a review summary highlight? | po | open |"
        changes = [{"path": FEATURE, "content": original.replace(marker, marker + "\n" + NEW_QUESTION)}]
        preview = self.service.preview_skill(
            self.agent, "ask", changes, read_revisions=_read_revisions(self.service, self.agent, "ask", changes)
        )
        self.assertTrue(preview["applicable"], preview)
        return preview

    def crash_before_log(self, preview: dict, operation_id: str) -> None:
        original = self.service._apply_write

        def interrupted(write, **kwargs):
            if write["role"] == "log":
                raise _Crash()
            return original(write, **kwargs)

        with patch.object(self.service, "_apply_write", side_effect=interrupted), self.assertRaises(_Crash):
            self.service.apply(self.agent, preview["preview_id"], operation_id)

    def insert_stuck_operation(self, operation_id: str = "op-stuck", writes: list | None = None) -> None:
        """Journal a conflicted agent operation whose intake move can no longer complete."""

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        intent = {
            "preview_id": str(uuid4()),
            "operation_id": operation_id,
            "kind": "skill",
            "skill": "po-intake",
            "participant_id": self.agent.participant_id,
            "actor": self.agent.to_dict(),
            "source_map": {FEATURE: "sha256:0"},
            "writes": writes or [],
            "moves": [
                {
                    "source": "knowledge/intake/pending/gone",
                    "destination": "knowledge/intake/processed/gone",
                    "source_digest": "sha256:0",
                    "source_files": {"brief.md": "sha256:0"},
                    "source_directories": [],
                }
            ],
        }
        with self.service.store.transaction() as db:
            db.execute(
                "INSERT INTO operations(operation_id, participant_id, preview_id, payload_hash, intent_json, receipt_json, state, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, NULL, 'conflict', ?, ?)",
                (operation_id, self.agent.participant_id, intent["preview_id"], "x", json.dumps(intent), now, now),
            )

    def review_revision(self, operation_id: str, actor=None) -> str:
        return self.service.operation(actor or self.human, operation_id)["recovery_review_revision"]

    # -- H1: stuck operations --------------------------------------------------------

    def test_acknowledged_human_recovers_against_the_current_files_after_a_source_changed(self) -> None:
        preview = self.ask_preview()
        self.crash_before_log(preview, "op-ask")
        self.put(SETTINGS, self.read(SETTINGS) + "\nA policy note added while the operation was interrupted.\n")

        receipt = self.service.recover(self.agent, "op-ask")
        self.assertEqual("conflict", receipt["state"])
        self.assertIn("recovery_source_changed", receipt["conflicts"][0]["reason"])
        for revision, acknowledged in ((None, False), (self.review_revision("op-ask"), False)):
            with self.assertRaises(BoardError) as error:
                self.service.recover(self.human, "op-ask", revision, acknowledged)
            self.assertEqual("recovery_review_required", error.exception.code)
        # An agent that supplies its own review is not a human review: the recorded sources still apply.
        agent_review = self.service.recover(self.agent, "op-ask", self.review_revision("op-ask", self.agent), True)
        self.assertEqual("conflict", agent_review["state"])
        self.assertIn("recovery_source_changed", agent_review["conflicts"][0]["reason"])
        log_before = self.read_optional("knowledge/wiki/log.md")

        reviewed = self.service.recover(self.human, "op-ask", self.review_revision("op-ask"), True)

        self.assertEqual("applied", reviewed["state"], reviewed)
        self.assertEqual(self.agent.participant_id, reviewed["actor"]["participant_id"])
        self.assertEqual(self.human.participant_id, reviewed["recovered_by"]["participant_id"])
        self.assertNotEqual(log_before, self.read_optional("knowledge/wiki/log.md"))
        self.assertIn(NEW_QUESTION, self.read(FEATURE))

    def test_acknowledged_recovery_still_refuses_a_stale_review_and_a_write_that_changed(self) -> None:
        preview = self.ask_preview()
        self.crash_before_log(preview, "op-ask")
        revision = self.review_revision("op-ask")
        self.put(SETTINGS, self.read(SETTINGS) + "\nChanged after the review.\n")
        with self.assertRaises(BoardError) as error:
            self.service.recover(self.human, "op-ask", revision, True)
        self.assertEqual("stale_recovery_review", error.exception.code)

        edited = self.read(FEATURE) + "\nA human correction after the write.\n"
        self.put(FEATURE, edited)
        receipt = self.service.recover(self.human, "op-ask", self.review_revision("op-ask"), True)
        self.assertEqual("conflict", receipt["state"])
        self.assertIn("recovery_conflict", receipt["conflicts"][0]["reason"])
        self.assertEqual(edited, self.read(FEATURE))

    def test_stuck_operation_is_abandoned_by_an_acknowledged_human_and_stops_blocking_writes(self) -> None:
        self.insert_stuck_operation()
        preview = self.ask_preview()
        with self.assertRaises(BoardError) as blocked:
            self.service.apply(self.agent, preview["preview_id"], "op-ask")
        self.assertEqual("unresolved_operation_overlap", blocked.exception.code)

        # Roll-forward cannot finish: both the recorded source and destination are gone.
        for actor in (self.agent, self.human):
            receipt = self.service.recover(actor, "op-stuck") if actor is self.agent else self.service.recover(actor, "op-stuck", self.review_revision("op-stuck"), True)
            self.assertEqual("conflict", receipt["state"])
            self.assertIn("recovery_move_conflict", receipt["conflicts"][0]["reason"])

        # Agents cannot abandon, with or without a review.
        for review in ((None, False), (self.review_revision("op-stuck", self.agent), True)):
            with self.assertRaises(BoardError) as refused:
                self.service.recover(self.agent, "op-stuck", review[0], review[1], abandon=True)
            self.assertEqual(("abandon_requires_human", 403), (refused.exception.code, refused.exception.status))
        # A human needs the same explicit, fresh review that recovery needs.
        revision = self.review_revision("op-stuck")
        for args in ((None, False), (revision, False), ("stale-revision", True)):
            with self.assertRaises(BoardError) as refused:
                self.service.recover(self.human, "op-stuck", *args, abandon=True)
            self.assertIn(refused.exception.code, {"recovery_review_required", "stale_recovery_review"})
        self.assertEqual("conflict", self.service.operation(self.human, "op-stuck")["state"])
        with self.assertRaises(BoardError) as still_blocked:
            self.service.apply(self.agent, preview["preview_id"], "op-ask")
        self.assertEqual("unresolved_operation_overlap", still_blocked.exception.code)

        receipt = self.service.recover(self.human, "op-stuck", revision, True, abandon=True)

        self.assertEqual("abandoned", receipt["state"])
        self.assertFalse(receipt["recovery_available"])
        self.assertEqual(self.agent.participant_id, receipt["actor"]["participant_id"])
        self.assertEqual(self.human.participant_id, receipt["abandoned_by"]["participant_id"])
        self.assertEqual([], receipt["applied_paths"])
        self.assertEqual([], receipt["moved_folders"])
        self.assertEqual(
            [{"source": "knowledge/intake/pending/gone", "destination": "knowledge/intake/processed/gone", "state": "missing"}],
            receipt["unmoved_folders"],
        )
        self.assertIn("recovery_move_conflict", receipt["reason"])
        events = [item["event"] for item in self.service.changes(self.human)["changes"] if item["event"]["type"] == "operation-abandoned"]
        self.assertEqual(1, len(events))
        self.assertEqual(self.agent.participant_id, events[0]["actor"]["participant_id"])
        self.assertEqual(self.human.participant_id, events[0]["abandoned_by"]["participant_id"])
        self.assertEqual("op-stuck", events[0]["operation_id"])

        # It is terminal: it no longer counts as pending anywhere, and asking again returns the same receipt.
        operation = self.service.operation(self.human, "op-stuck")
        self.assertEqual("abandoned", operation["state"])
        self.assertNotIn("remaining_changes", operation)
        for actor in (self.agent, self.human):
            self.assertNotIn("op-stuck", [item["operation_id"] for item in self.service.discover(actor)["pending_operations"]])
        self.assertEqual([], unresolved_board_operations(self.root))
        self.assertEqual(receipt, self.service.recover(self.human, "op-stuck", "any-revision", True, abandon=True))
        self.assertEqual(receipt, self.service.recover(self.human, "op-stuck"))
        self.assertEqual(receipt, self.service.recover(self.agent, "op-stuck"))

        # The overlapping write that was blocked now applies.
        self.assertEqual("applied", self.service.apply(self.agent, preview["preview_id"], "op-ask")["state"])
        self.assertIn(NEW_QUESTION, self.read(FEATURE))

    def test_abandoning_records_which_writes_were_applied_and_leaves_them_in_place(self) -> None:
        current = self.read(FEATURE)
        applied = self.service._write_record(FEATURE, "an earlier text\n", current, role="canonical")
        never = self.service._write_record("knowledge/wiki/features/F-009-never-written.md", None, "# Never written\n", role="canonical")
        self.insert_stuck_operation(writes=[applied, never])

        receipt = self.service.recover(self.human, "op-stuck", self.review_revision("op-stuck"), True, abandon=True)

        self.assertEqual("abandoned", receipt["state"])
        self.assertEqual([FEATURE], receipt["applied_paths"])
        self.assertEqual(["knowledge/wiki/features/F-009-never-written.md"], receipt["unapplied_paths"])
        self.assertEqual(current, self.read(FEATURE), "nothing already written is undone")
        self.assertFalse((self.root / "knowledge/wiki/features/F-009-never-written.md").exists())

    def test_an_operation_that_can_still_be_recovered_is_not_abandoned(self) -> None:
        preview = self.ask_preview()
        self.crash_before_log(preview, "op-ask")
        with self.assertRaises(BoardError) as error:
            self.service.recover(self.human, "op-ask", self.review_revision("op-ask"), True, abandon=True)
        self.assertEqual("abandon_not_needed", error.exception.code)
        self.assertEqual("pending", self.service.operation(self.human, "op-ask")["state"])
        self.assertEqual("applied", self.service.recover(self.human, "op-ask", self.review_revision("op-ask"), True)["state"])
        with self.assertRaises(BoardError) as applied:
            self.service.recover(self.human, "op-ask", "any-revision", True, abandon=True)
        self.assertEqual("operation_already_applied", applied.exception.code)

    def test_a_write_that_changed_after_it_was_made_can_be_abandoned_not_overwritten(self) -> None:
        preview = self.ask_preview()
        self.crash_before_log(preview, "op-ask")
        edited = self.read(FEATURE) + "\nA human correction after the write.\n"
        self.put(FEATURE, edited)
        receipt = self.service.recover(self.human, "op-ask", self.review_revision("op-ask"), True, abandon=True)
        self.assertEqual("abandoned", receipt["state"])
        self.assertIn("recovery_conflict", receipt["reason"])
        self.assertIn(FEATURE, receipt["unapplied_paths"])
        self.assertEqual(edited, self.read(FEATURE))
        self.assertEqual("abandoned", self.service.apply(self.agent, preview["preview_id"], "op-ask")["state"])

    # -- M1: names that Windows cannot hold, read from disk ------------------------------

    def test_a_filesystem_name_windows_cannot_hold_is_skipped_by_changes_and_reported(self) -> None:
        baseline = self.service.changes(self.agent)
        self.assertNotIn("skipped_paths", baseline)
        bad = "knowledge/intake/pending/review-summary/Brief: review.txt"
        original = BoardService._all_board_revision_paths
        with patch.object(BoardService, "_all_board_revision_paths", lambda service: original(service) | {bad}):
            result = self.service.changes(self.agent)
        self.assertEqual(baseline["board_revision"], result["board_revision"])
        self.assertEqual(baseline["head_cursor"], result["head_cursor"])
        self.assertEqual(1, result["skipped_paths"]["count"])
        self.assertEqual(["Brief: review.txt"], [name.rsplit("/", 1)[-1] for name in result["skipped_paths"]["examples"]])
        # Caller-supplied paths still fail with invalid_path.
        with self.assertRaises(BoardError) as error:
            self.service._fingerprint_paths([bad])
        self.assertEqual("invalid_path", error.exception.code)
        with self.assertRaises(BoardError) as error:
            self.service.read_workspace(self.agent, [bad])
        self.assertEqual("invalid_path", error.exception.code)

    def test_unportable_names_are_not_required_reads_of_a_skill_or_an_intake_move(self) -> None:
        pending = INTAKE_ITEM.parent.as_posix()
        moves = [{
            "source": pending,
            "destination": pending.replace("pending", "processed", 1),
            "source_files": {"brief.md": "sha256:0", "Meeting 10:05.md": "sha256:0", "trailing dot.": "sha256:0"},
        }]
        required = self.service._required_skill_revision_paths("po-intake", {}, {}, moves)
        self.assertIn(f"{pending}/brief.md", required)
        self.assertFalse([path for path in required if ":" in path or path.endswith(".")])

        bad_page = "knowledge/wiki/features/F-002 Brief: export.md"
        with patch.object(BoardService, "_feature_context_paths", lambda service, path, frontmatter: {path, bad_page}):
            required = self.service._required_skill_revision_paths("ask", {FEATURE: self.read(FEATURE)}, {FEATURE: self.read(FEATURE)}, [])
        self.assertIn(FEATURE, required)
        self.assertNotIn(bad_page, required)

    # -- L1: sub-folder pages ---------------------------------------------------------------

    def test_skill_writes_must_be_pages_directly_in_a_wiki_directory(self) -> None:
        for skill, relative in (
            ("po-intake", "knowledge/wiki/features/2026/F-009-export.md"),
            ("po-intake", "knowledge/wiki/personas/team/P-009-owner.md"),
            ("design-intake", "knowledge/wiki/design/v2/F-009-design.md"),
            ("ask", "knowledge/wiki/features/archive/F-001-document-review.md"),
        ):
            with self.subTest(relative=relative), self.assertRaises(BoardError) as error:
                self.service.preview_skill(self.agent, skill, [{"path": relative, "content": "x"}])
            self.assertEqual(("write_path_unavailable", 403), (error.exception.code, error.exception.status))
            self.assertIn("sub-folder", error.exception.message)
        self.service._assert_skill_write_path("po-intake", "knowledge/wiki/features/F-009-export.md")
        self.service._assert_skill_write_path("po-intake", "knowledge/intake/processed/brief/MANIFEST.md")

    # -- L2: change cursors -----------------------------------------------------------------

    def test_changes_accepts_only_cursors_it_issues(self) -> None:
        preview = self.ask_preview()
        self.service.apply(self.agent, preview["preview_id"], "op-ask")
        head = self.service.changes(self.agent)["head_cursor"]
        self.assertEqual("1", head)
        for cursor in (None, "", "0", "1", "00", head):
            self.assertIn("changes", self.service.changes(self.agent, cursor))
        for cursor in ("1_0", " 5 ", "+5", "-1", "5.0", "1e3", "0x10", "1_0~3", "3~", "~3", "1~2", "٣", "9" * 19, "abc", 5):
            with self.subTest(cursor=cursor), self.assertRaises(BoardError) as error:
                self.service.changes(self.agent, cursor)
            self.assertEqual(("invalid_cursor", 400), (error.exception.code, error.exception.status))

    # -- L3: stale preview ------------------------------------------------------------------

    def test_a_source_that_became_required_after_the_preview_is_a_stale_preview_at_apply(self) -> None:
        preview = self.ask_preview()
        design = "knowledge/wiki/design/F-001-design.md"
        self.put(design, _design_page())
        with self.assertRaises(BoardError) as error:
            self.service.apply(self.agent, preview["preview_id"], "op-ask")
        self.assertEqual(("stale_preview", 409), (error.exception.code, error.exception.status))
        self.assertIn("preview again", error.exception.message)
        self.assertNotIn("read_workspace", error.exception.message)
        self.assertIn(design, (error.exception.details or {}).get("paths", []))
        self.assertEqual(0, self.service.store.connection.execute("SELECT COUNT(*) FROM operations").fetchone()[0])
        # A fresh preview that reads the new source applies.
        again = self.ask_preview()
        self.assertEqual("applied", self.service.apply(self.agent, again["preview_id"], "op-ask-2")["state"])


if __name__ == "__main__":
    unittest.main()
