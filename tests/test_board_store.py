"""Concurrency coverage for the shared connected-board SQLite journal."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import threading
import unittest

import yaml

from prism_cli.board_service import BoardError, BoardService
from prism_cli.board_store import BoardStore, count_active_grants, unresolved_board_operations, workspace_process_lock
from prism_cli.fs_safety import CLOUD_SYNC_MESSAGE, CloudSyncPathError
from prism_cli.workflow_install import apply_install, plan_install
from tests.test_core_workflow_fixture import _feature_page, _write_index
from tests.test_fs_safety import CLOUD_TAG, JUNCTION_TAG, fake_reparse
from tests import real_temp  # noqa: F401


class BoardStoreConcurrencyTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.assertEqual(
            "applied",
            apply_install(self.root, plan_install(self.root, name="Document review", platforms=["backend"]))["status"],
        )
        feature = self.root / "knowledge/wiki/features/F-001-document-review.md"
        feature.write_text(_feature_page(), encoding="utf-8")
        _write_index(self.root, "raw", "po")
        self.service = BoardService(self.root).start()
        self.addCleanup(self.service.close)

    def test_read_lock_blocks_transaction_until_cursor_consumption_finishes(self) -> None:
        store = self.service.store
        self.assertIsNotNone(store)
        entered = threading.Event()
        writer_started = threading.Event()
        writer_done = threading.Event()
        release_reader = threading.Event()

        def reader() -> tuple[bool, int]:
            with store.read() as db:
                cursor = db.execute("SELECT COUNT(*) FROM grants")
                entered.set()
                writer_started.wait(1)
                blocked = not writer_done.wait(0.1)
                count = cursor.fetchone()[0]
                release_reader.wait(1)
            return blocked, count

        def writer() -> bool:
            self.assertTrue(entered.wait(1))
            writer_started.set()
            with store.transaction() as db:
                db.execute("INSERT INTO events(operation_id, participant_id, event_json, created_at) VALUES (NULL, NULL, ?, ?)", ("{}", "test"))
            writer_done.set()
            return True

        with ThreadPoolExecutor(max_workers=2) as executor:
            read_future = executor.submit(reader)
            self.assertTrue(entered.wait(1))
            write_future = executor.submit(writer)
            self.assertTrue(writer_started.wait(1))
            self.assertFalse(writer_done.wait(0.1))
            release_reader.set()
            self.assertEqual((True, 0), read_future.result())
            self.assertTrue(write_future.result())
        self.assertTrue(writer_done.is_set())

    def test_close_waits_for_an_active_read(self) -> None:
        store = self.service.store
        self.assertIsNotNone(store)
        entered = threading.Event()
        release_reader = threading.Event()
        close_started = threading.Event()
        close_done = threading.Event()

        def reader() -> None:
            with store.read() as db:
                db.execute("SELECT COUNT(*) FROM grants").fetchone()
                entered.set()
                release_reader.wait(1)

        def closer() -> None:
            close_started.set()
            store.close()
            close_done.set()

        with ThreadPoolExecutor(max_workers=2) as executor:
            read_future = executor.submit(reader)
            self.assertTrue(entered.wait(1))
            close_future = executor.submit(closer)
            self.assertTrue(close_started.wait(1))
            self.assertFalse(close_done.wait(0.1))
            release_reader.set()
            read_future.result()
            close_future.result()
        self.assertTrue(close_done.is_set())

    def test_concurrent_multi_participant_queries_keep_grants_bound(self) -> None:
        agent = self.service.create_participant("Concurrent agent", "agent", writable=True)
        human = self.service.create_participant("Concurrent human", "human", writable=True)
        revoked = self.service.create_participant("Revoked agent", "agent", writable=True)
        self.service.revoke_participant(revoked["participant"]["participant_id"])
        valid_tokens = (agent["token"], human["token"])
        expected_actors = {
            item["token"]: (
                item["participant"]["participant_id"],
                item["participant"]["name"],
                item["participant"]["kind"],
                item["participant"]["writable"],
            )
            for item in (agent, human)
        }
        jobs = []
        for _round in range(8):
            jobs.extend((token, None) for token in valid_tokens)
            jobs.extend(((revoked["token"], "unauthorized"), (agent["token"] + "wrong", "unauthorized")))

        barrier = threading.Barrier(len(jobs))

        def invoke(
            job: tuple[str, str | None],
        ) -> tuple[str, str | None, str | None, str | None, bool | None, str | None]:
            token, expected_error = job
            barrier.wait(5)
            try:
                actor = self.service.authenticate(token)
                if expected_error is not None:
                    return "unexpected-valid", actor.participant_id, actor.name, actor.kind, actor.writable, None
                result = self.service.query(actor, "blockers")
                return "ok", actor.participant_id, actor.name, actor.kind, actor.writable, result["snapshot"]["revision"]
            except BoardError as exc:
                return exc.code, None, None, None, None, None

        with ThreadPoolExecutor(max_workers=len(jobs)) as executor:
            results = list(executor.map(invoke, jobs))

        self.assertEqual(len(jobs), len(results))
        for job, result in zip(jobs, results):
            if job[1] is None:
                self.assertEqual("ok", result[0])
                self.assertEqual(expected_actors[job[0]], result[1:5])
            else:
                self.assertEqual("unauthorized", result[0])

    def test_invalid_tokens_remain_rejected_after_serialized_reads(self) -> None:
        grant = self.service.create_participant("Valid participant", "agent", writable=True)
        actor = self.service.authenticate(grant["token"])
        self.assertEqual(actor.participant_id, self.service.authenticate(grant["token"]).participant_id)
        self.service.revoke_participant(actor.participant_id)
        for token in (grant["token"], grant["token"] + "wrong"):
            with self.subTest(token_kind="revoked" if token == grant["token"] else "unknown"), self.assertRaises(BoardError) as error:
                self.service.authenticate(token)
            self.assertEqual("unauthorized", error.exception.code)


if __name__ == "__main__":
    unittest.main()


class BoardStoreCloudSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / ".prism" / "state").mkdir(parents=True)

    def test_cloud_state_directory_is_rejected_with_cloud_guidance(self) -> None:
        for target in (self.root / ".prism", self.root / ".prism" / "state"):
            with self.subTest(target=target.name), fake_reparse(target, CLOUD_TAG):
                with self.assertRaises(ValueError) as raised:
                    BoardStore(self.root, process_lock=False)

                self.assertIsInstance(raised.exception, CloudSyncPathError)
                self.assertEqual(CLOUD_SYNC_MESSAGE, str(raised.exception))

    def test_cloud_state_file_is_rejected_with_cloud_guidance(self) -> None:
        database = self.root / ".prism" / "state" / "board.sqlite3"
        database.write_bytes(b"")
        with fake_reparse(database, 0x9000701A):
            with self.assertRaises(ValueError) as raised:
                BoardStore(self.root, process_lock=False)
            with self.assertRaises(ValueError) as journal:
                unresolved_board_operations(self.root)

        self.assertEqual(CLOUD_SYNC_MESSAGE, str(raised.exception))
        self.assertEqual(CLOUD_SYNC_MESSAGE, str(journal.exception))

    def test_cloud_lock_file_is_rejected_with_cloud_guidance(self) -> None:
        lock = self.root / ".prism" / "state" / "board.lock"
        lock.write_bytes(b"\0")
        with fake_reparse(lock, CLOUD_TAG):
            with self.assertRaises(ValueError) as raised:
                with workspace_process_lock(self.root, create=True):
                    self.fail("the process lock must not be acquired")

        self.assertEqual(CLOUD_SYNC_MESSAGE, str(raised.exception))

    def test_non_cloud_reparse_keeps_the_existing_messages(self) -> None:
        state = self.root / ".prism" / "state"
        database = state / "board.sqlite3"
        database.write_bytes(b"")
        with fake_reparse(state, JUNCTION_TAG):
            with self.assertRaises(ValueError) as directory:
                BoardStore(self.root, process_lock=False)
        with fake_reparse(database, JUNCTION_TAG):
            with self.assertRaises(ValueError) as file:
                BoardStore(self.root, process_lock=False)
            with self.assertRaises(ValueError) as journal:
                unresolved_board_operations(self.root)

        self.assertEqual("Prism state path must be a real directory: state.", str(directory.exception))
        self.assertEqual("Prism state file must be a regular file: board.sqlite3.", str(file.exception))
        self.assertEqual("Prism board journal must be a regular file before workflow upgrade.", str(journal.exception))


class ActiveGrantCountTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.assertEqual(
            "applied",
            apply_install(self.root, plan_install(self.root, name="Grant count", platforms=["backend"]))["status"],
        )
        workflow = yaml.safe_load((self.root / "prism.workspace.yml").read_text(encoding="utf-8"))["workflow"]
        self.identity = (workflow["board_id"], workflow["version"], workflow["asset_digest"])

    def test_no_board_state_returns_none_and_creates_nothing(self) -> None:
        self.assertIsNone(count_active_grants(self.root, self.identity))
        self.assertFalse((self.root / ".prism").exists())

    def test_state_directory_without_a_journal_returns_none(self) -> None:
        (self.root / ".prism" / "state").mkdir(parents=True)

        self.assertIsNone(count_active_grants(self.root))
        self.assertEqual([], list((self.root / ".prism" / "state").iterdir()))

    def test_counts_only_active_grants_for_the_current_identity(self) -> None:
        with BoardService(self.root) as service:
            service.create_participant("First", "agent")
            service.create_participant("Second", "human", writable=True)
            revoked = service.create_participant("Third", "agent")["participant"]["participant_id"]
            service.revoke_participant(revoked)
        state = self.root / ".prism" / "state"
        before = sorted(path.name for path in state.iterdir())

        self.assertEqual((2, 2), count_active_grants(self.root, self.identity))
        self.assertEqual((2, 2), count_active_grants(self.root))
        self.assertEqual((2, 0), count_active_grants(self.root, ("other-board", *self.identity[1:])))
        self.assertEqual(before, sorted(path.name for path in state.iterdir()))

    def test_unreadable_journal_raises_a_value_error(self) -> None:
        state = self.root / ".prism" / "state"
        state.mkdir(parents=True)
        (state / "board.sqlite3").write_bytes(b"not a database" * 30)

        with self.assertRaises(ValueError):
            count_active_grants(self.root)

    def test_cloud_placeholder_journal_is_rejected_with_cloud_guidance(self) -> None:
        with BoardService(self.root) as service:
            service.create_participant("First", "agent")
        database = self.root / ".prism" / "state" / "board.sqlite3"
        with fake_reparse(database, CLOUD_TAG):
            with self.assertRaises(CloudSyncPathError):
                count_active_grants(self.root)
