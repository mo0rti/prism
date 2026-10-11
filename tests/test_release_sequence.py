"""F09 regressions: release reads and previews agree on chronological authority."""

from __future__ import annotations

import unittest
from pathlib import Path

from prism_cli.board_service import BoardError
from prism_cli.release_lint import lint_release_records, validate_release_records
from prism_cli.wiki_model import parse_markdown_text, parse_release_rows
from prism_cli.wiki_releases import ReleaseRecord, current_delivery, next_release_number, read_release_records, record_kinds
from tests.qa_support import FEATURE, release_row as pending_row
from tests.release_pages import delivery, record_id, record_page, record_path, release_row
from tests.release_support import ReleaseTests
from tests.test_release_bugs import BUG, BUG_TWO, ReleaseBugTests


def parsed(number: int, rows: list[str], **kwargs: object) -> ReleaseRecord:
    return ReleaseRecord(parse_markdown_text(Path(record_path(number)), record_page(number, rows, **kwargs)))  # type: ignore[arg-type]


class ReleaseSequenceTests(unittest.TestCase):
    def test_obsolete_rollback_and_redeploy_have_no_authority(self) -> None:
        records = [
            parsed(1, [delivery("F-001", "backend")]),
            parsed(2, [delivery("F-002", "backend", version="build:backend#2")], features=["F-002"]),
            parsed(3, [delivery("F-001", "backend", outcome="rolled-back", attempt=None)], rollback_of="REL-001", rollback="Restore the preceding deployment."),
            parsed(4, [delivery("F-001", "backend", attempt=None)], retry_of="REL-003"),
        ]
        current = current_delivery(records, "backend", "production")
        self.assertEqual(("REL-002", "build:backend#2"), (current[0].record_id, current[1][0].version))
        valid, problems = validate_release_records(records[::-1])
        self.assertEqual(records[:2], valid)
        self.assertEqual({records[2].page.path, records[3].page.path}, set(problems))
        self.assertEqual(3, next_release_number(records))
        self.assertEqual(set(problems), {finding.path for finding in lint_release_records(records, items={"F-001": ["backend"], "F-002": ["backend"]})})

    def test_1100_forward_references_are_diagnostics(self) -> None:
        records = [parsed(number, [delivery("F-001", "backend", outcome="failed")], retry_of=record_id(number + 1)) for number in range(1, 1101)]
        valid, problems = validate_release_records(records)
        self.assertEqual([], valid)
        self.assertEqual(1100, len(problems))
        self.assertTrue(all(any("earlier valid" in message for message in messages) for messages in problems.values()))
        self.assertEqual({}, record_kinds(records))
        self.assertEqual(1100, len({finding.path for finding in lint_release_records(records, items={"F-001": ["backend"]})}))
        self.assertIsNone(current_delivery(records, "backend", "production"))
        self.assertEqual(1, next_release_number(records))

    def test_a_retry_must_include_the_failed_item_and_app(self) -> None:
        first = parsed(1, [delivery("BUG-001", "backend", outcome="failed")], features=[], bugs=["BUG-001"])
        unrelated = parsed(2, [delivery("BUG-002", "backend")], features=[], bugs=["BUG-002"], retry_of="REL-001")
        valid, problems = validate_release_records([first, unrelated])
        self.assertEqual([first], valid)
        self.assertIn(unrelated.page.path, problems)

    def test_reference_edges_are_rejected_before_kind_derivation(self) -> None:
        first = parsed(1, [delivery("F-001", "backend", outcome="failed")])
        for target in ("REL-002", "REL-003", "REL-999"):
            with self.subTest(target=target):
                retry = parsed(2, [delivery("F-001", "backend", attempt=2)], retry_of=target)
                valid, problems = validate_release_records([retry, first])
                self.assertEqual([first], valid)
                self.assertIn(retry.page.path, problems)
                self.assertEqual({"REL-001": "release"}, record_kinds([retry, first]))
        broken = ReleaseRecord(parse_markdown_text(first.page.path, record_page(1, [delivery("F-001", "backend", outcome="failed")]).replace("## Notes\nNone.\n", "")))
        retry = parsed(2, [delivery("F-001", "backend", attempt=2)], retry_of="REL-001")
        self.assertEqual([], validate_release_records([broken, retry])[0])
        self.assertEqual({broken.page.path, retry.page.path}, set(validate_release_records([broken, retry])[1]))

    def test_1100_valid_backward_retries_are_derived_iteratively(self) -> None:
        records = [
            parsed(number, [delivery("F-001", "backend", outcome="failed", attempt=number)], retry_of=record_id(number - 1) if number > 1 else None)
            for number in range(1, 1101)
        ]
        self.assertEqual((records, {}), validate_release_records(records[::-1]))
        self.assertEqual({record.record_id: "release" for record in records}, record_kinds(records))
        self.assertEqual(1101, next_release_number(records))

    def test_a_later_delivery_invalidates_redeploy_of_a_valid_old_rollback(self) -> None:
        records = [
            parsed(1, [delivery("F-001", "backend")]),
            parsed(2, [delivery("F-001", "backend", outcome="rolled-back", attempt=None)], rollback_of="REL-001"),
            parsed(3, [delivery("F-002", "backend", version="build:backend#2")], features=["F-002"]),
            parsed(4, [delivery("F-001", "backend", attempt=None)], retry_of="REL-002"),
        ]
        valid, problems = validate_release_records(records)
        self.assertEqual(records[:3], valid)
        self.assertIn(records[3].page.path, problems)
        self.assertEqual("REL-003", current_delivery(records, "backend", "production")[0].record_id)


class ReleaseSequenceBoardTests(ReleaseTests):
    verified = ReleaseBugTests.verified
    released_bug = ReleaseBugTests.released_bug

    def test_a_spanning_bug_ships_one_app_then_the_other(self) -> None:
        self.put(BUG, self.verified(apps=("backend", "worker"), feature="none"))
        first_row = release_row("backend", 1)
        first = self.released_bug([first_row], apps=("backend", "worker"), feature="none", status="verified")
        self.assertEqual(("release_row_invalid", 409), self.refusal([
            {"path": BUG, "content": first},
            {"path": record_path(1), "content": record_page(1, [delivery("BUG-001", "worker")], features=[], bugs=["BUG-001"])},
        ]))
        self.apply("release-done", [
            {"path": BUG, "content": first},
            {"path": record_path(1), "content": record_page(1, [delivery("BUG-001", "backend")], features=[], bugs=["BUG-001"])},
        ], approver=self.owner)
        self.assertIn("status: verified", self.read(BUG))
        self.assertIn("owner: release", self.read(BUG))
        self.assertEqual(["backend"], [row.app for row in parse_release_rows(self.read(BUG))[0]])
        self.assertEqual(("release_row_invalid", 409), self.refusal([
            {"path": BUG, "content": self.released_bug([release_row("worker", 2)], apps=("backend", "worker"), feature="none", status="verified")},
            {"path": record_path(2), "content": record_page(2, [delivery("BUG-001", "worker")], features=[], bugs=["BUG-001"])},
        ]))
        final = self.released_bug([first_row, release_row("worker", 2)], apps=("backend", "worker"), feature="none")
        self.apply("release-done", [
            {"path": BUG, "content": final},
            {"path": record_path(2), "content": record_page(2, [delivery("BUG-001", "worker")], features=[], bugs=["BUG-001"])},
        ], approver=self.owner)
        self.assertIn(first_row, self.read(BUG))
        self.assertIn("status: released", self.read(BUG))
        self.assertIn("owner: none", self.read(BUG))
        self.assertEqual(set(), self.errors())

    def test_a_feature_releases_per_app_with_a_spanning_bug(self) -> None:
        self.put(BUG, self.verified(apps=("backend", "worker")))
        backend_row = release_row("backend", 1)
        first = self.released_page([backend_row, pending_row("worker")], status="ready-for-release", owner="release")
        partial_bug = self.released_bug([backend_row], apps=("backend", "worker"), status="verified")
        self.apply("release-done", [
            {"path": FEATURE, "content": first}, {"path": BUG, "content": partial_bug},
            {"path": record_path(1), "content": record_page(1, [delivery("F-001", "backend"), delivery("BUG-001", "backend")], bugs=["BUG-001"])},
        ], approver=self.owner)
        self.assertEqual(("ready-for-release", "release"), self.status())
        self.assertIn("status: verified", self.read(BUG))
        final = self.released_page([backend_row, release_row("worker", 2)])
        final_bug = self.released_bug([backend_row, release_row("worker", 2)], apps=("backend", "worker"))
        self.apply("release-done", [
            {"path": FEATURE, "content": final}, {"path": BUG, "content": final_bug},
            {"path": record_path(2), "content": record_page(2, [delivery("F-001", "worker"), delivery("BUG-001", "worker")], bugs=["BUG-001"])},
        ], approver=self.owner)
        self.assertEqual(("released", "none"), self.status())
        self.assertIn(backend_row, self.read(BUG))
        self.assertIn("status: released", self.read(BUG))
        self.assertEqual(set(), self.errors())

    def retry_plus_new_bug(self, failed_app: str, new_app: str) -> None:
        self.put(BUG, self.verified(apps=(failed_app,), feature="none"))
        failed = self.released_bug([release_row(failed_app, 1, outcome="failed")], apps=(failed_app,), feature="none", status="verified")
        self.apply("release-done", [
            {"path": BUG, "content": failed},
            {"path": record_path(1), "content": record_page(1, [delivery("BUG-001", failed_app, outcome="failed")], features=[], bugs=["BUG-001"])},
        ], approver=self.owner)
        self.put(BUG_TWO, self.verified("BUG-002", apps=(new_app,), feature="none"))
        pages = [
            {"path": BUG, "content": self.released_bug([release_row(failed_app, 2, attempt=2)], apps=(failed_app,), feature="none")},
            {"path": BUG_TWO, "content": self.released_bug([release_row(new_app, 2)], "BUG-002", apps=(new_app,), feature="none")},
        ]
        rows = [delivery("BUG-001", failed_app, attempt=2), delivery("BUG-002", new_app)]
        first = read_release_records(self.root / "knowledge/wiki")
        for ordered in (rows, rows[::-1]):
            with self.subTest(rows=ordered):
                text = record_page(2, ordered, features=[], bugs=["BUG-001", "BUG-002"], retry_of="REL-001")
                changes = [*pages, {"path": record_path(2), "content": text}]
                self.ready("release-done", changes)
                candidate = ReleaseRecord(parse_markdown_text(self.root / record_path(2), text))
                self.assertEqual(([first[0], candidate], {}), validate_release_records([*first, candidate]))
                self.assertEqual([], lint_release_records([*first, candidate], items={"BUG-001": [failed_app], "BUG-002": [new_app]}))
        self.apply("release-done", changes, approver=self.owner)
        self.assertEqual(2, len(read_release_records(self.root / "knowledge/wiki")))
        self.assertEqual(set(), self.errors())

    def test_retry_plus_new_bug_is_accepted_by_reads_and_writes(self) -> None:
        self.retry_plus_new_bug("backend", "worker")

    def test_new_bug_plus_retry_is_accepted_by_reads_and_writes(self) -> None:
        self.retry_plus_new_bug("worker", "backend")

    def test_an_unrelated_failed_item_cannot_authorize_a_retry_preview(self) -> None:
        self.put(BUG, self.verified(feature="none"))
        self.put(record_path(1), record_page(1, [delivery("BUG-002", "backend", outcome="failed")], features=[], bugs=["BUG-002"]))
        self.put(BUG_TWO, self.verified("BUG-002", feature="none"))
        text = record_page(2, [delivery("BUG-001", "backend")], features=[], bugs=["BUG-001"], retry_of="REL-001")
        with self.assertRaises(BoardError) as caught:
            self.ready("release-done", [{"path": BUG, "content": self.released_bug([release_row("backend", 2)], feature="none")}, {"path": record_path(2), "content": text}])
        self.assertEqual("release_record_invalid", caught.exception.code)


if __name__ == "__main__":
    unittest.main()
