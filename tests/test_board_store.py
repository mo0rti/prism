"""Concurrency coverage for the shared connected-board SQLite journal."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import threading
import unittest

from prism_cli.board_service import BoardError, BoardService
from prism_cli.workflow_install import apply_install, plan_install
from tests.test_core_workflow_fixture import _feature_page, _write_index


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
