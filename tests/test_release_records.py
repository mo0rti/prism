"""The release record: its parsers, numbering, kinds, current delivery, snapshots and lint (CONTRACTS 5.3, 6.2; cases 10.2 and 10.3)."""

from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from prism_cli.release_rules import check_record_page, group_conflicts, record_front_matter_problems, snapshot_problems
from prism_cli.wiki_lint import lint_wiki
from prism_cli.wiki_model import contract_page_citation, parse_markdown_text
from prism_cli.wiki_releases import (
    KIND_REDEPLOY,
    KIND_RELEASE,
    KIND_ROLLBACK,
    RELEASE_FILE_PATTERN,
    RELEASE_ID_PATTERN,
    ReleaseRecord,
    current_delivery,
    format_record_id,
    format_snapshot,
    latest_record,
    next_release_number,
    parse_record_rows,
    parse_snapshots,
    read_release_records,
    record_id_of_cell,
    record_kinds,
    record_link,
    record_outcome,
    release_attempt_of,
    release_listing_digest,
)
from tests.release_support import (
    FEATURE,
    FIX_HEADER,
    RELEASE_HEADER,
    RELEASES,
    VERIFICATION_HEADER,
    ReleaseTests,
    bug_page,
    delivery,
    fix_row,
    pending_row,
    record_page,
    record_path,
    release_row,
    table,
    verification_row,
)

CONTRACT_TEXT = (
    "---\nfeature-id: F-001\nversion: 1\nstatus: implemented\n---\n\n"
    "## Endpoints\n- `GET /api/v1/reviews/:reviewId/summary` returns the summary.\n\n"
    "## Data models\n```\nReviewSummary\n```\n\n## Authentication requirements\nBearer token.\n\n## Notes\nNone.\n"
)


def parse(number: int, rows: list[str], **kwargs: object) -> ReleaseRecord:
    path = Path(f"{RELEASES}/REL-{number:03d}.md")
    return ReleaseRecord(parse_markdown_text(path, record_page(number, rows, **kwargs)))  # type: ignore[arg-type]


class IdentifierTests(unittest.TestCase):
    def test_a_record_id_has_three_digits_or_a_number_without_padding(self) -> None:
        for good in ("REL-001", "REL-099", "REL-999", "REL-1000", "REL-1042"):
            with self.subTest(good=good):
                self.assertIsNotNone(RELEASE_ID_PATTERN.match(good))
                self.assertIsNotNone(RELEASE_FILE_PATTERN.match(f"{good}.md"))
        for bad in ("REL-01", "REL-0001", "REL-1", "rel-001", "REL-001a", "REL001"):
            with self.subTest(bad=bad):
                self.assertIsNone(RELEASE_ID_PATTERN.match(bad))

    def test_the_formatter_pads_to_three_digits_and_the_link_points_from_a_feature_or_bug(self) -> None:
        self.assertEqual(["REL-001", "REL-042", "REL-1000"], [format_record_id(number) for number in (1, 42, 1000)])
        self.assertEqual("[REL-001](../releases/REL-001.md)", record_link("REL-001"))

    def test_only_the_canonical_link_names_a_record(self) -> None:
        self.assertEqual("REL-007", record_id_of_cell("[REL-007](../releases/REL-007.md)"))
        self.assertEqual("REL-007", record_id_of_cell("  [REL-007](../releases/REL-007.md)  "))
        for cell in ("—", "", "REL-007", "[REL-007](https://records.example/REL-007)", "[REL-007](../releases/REL-008.md)", "[REL-7](../releases/REL-7.md)"):
            with self.subTest(cell=cell):
                self.assertIsNone(record_id_of_cell(cell))


class RowParsingTests(unittest.TestCase):
    def rows(self, *rows: str):
        return parse_record_rows(record_page(1, list(rows)))

    def test_a_valid_row_is_read_in_full(self) -> None:
        rows, problems = self.rows(delivery("F-001", "backend"))
        self.assertEqual([], problems)
        row = rows[0]
        self.assertEqual(("F-001", "backend", "production", "build:backend#1", 1, "released", "checked"), (row.item, row.app, row.target, row.version, row.attempt, row.outcome, row.basis))
        self.assertEqual(("backend", "production"), row.pair)

    def test_a_dash_attempt_is_no_attempt(self) -> None:
        rows, problems = self.rows(delivery("F-001", "backend", outcome="rolled-back", attempt=None))
        self.assertEqual([], problems)
        self.assertIsNone(rows[0].attempt)

    def test_each_cell_is_checked(self) -> None:
        cases = {
            "item": delivery("X-001", "backend"),
            "outcome": delivery("F-001", "backend", outcome="done"),
            "basis": delivery("F-001", "backend", basis="trusted"),
            "version": delivery("F-001", "backend", version="latest"),
            "evidence": delivery("F-001", "backend", evidence="—"),
            "target": delivery("F-001", "backend", target="the production cluster"),
            "attempt": delivery("F-001", "backend").replace("release-1", "second"),
        }
        for name, row in cases.items():
            with self.subTest(cell=name):
                _rows, problems = self.rows(row)
                self.assertTrue(problems, name)

    def test_the_evidence_is_a_typed_reference(self) -> None:
        for evidence in ("deployment: https://ci.example/deploy/1", "release: https://github.example/acme/releases/1", "store: https://play.example/console/1", "package: https://registry.example/p/1"):
            with self.subTest(evidence=evidence):
                self.assertEqual([], self.rows(delivery("F-001", "backend", evidence=evidence))[1])
        for evidence in ("https://ci.example/deploy/1", "deployed", "deployment: done"):
            with self.subTest(evidence=evidence):
                self.assertTrue(self.rows(delivery("F-001", "backend", evidence=evidence))[1])

    def test_the_columns_are_the_eight_of_the_record(self) -> None:
        _rows, problems = parse_record_rows(record_page(1, [delivery("F-001", "backend")]).replace("| Item | App |", "| App | Item |"))
        self.assertTrue(problems)


class OutcomeAndKindTests(unittest.TestCase):
    def test_the_outcome_follows_the_rows(self) -> None:
        released, failed = delivery("F-001", "backend"), delivery("F-001", "worker", outcome="failed")
        self.assertEqual("released", record_outcome(parse_record_rows(record_page(1, [released]))[0], KIND_RELEASE))
        self.assertEqual("failed", record_outcome(parse_record_rows(record_page(1, [failed]))[0], KIND_RELEASE))
        self.assertEqual("partial", record_outcome(parse_record_rows(record_page(1, [released, failed]))[0], KIND_RELEASE))
        self.assertEqual("rolled-back", record_outcome(parse_record_rows(record_page(1, [released]))[0], KIND_ROLLBACK))

    def test_the_kind_follows_the_retry_chain(self) -> None:
        rolled = delivery("F-001", "backend", outcome="rolled-back", attempt=None)
        redone = delivery("F-001", "backend", attempt=None)
        failed = delivery("F-001", "backend", outcome="failed")
        records = [
            parse(1, [delivery("F-001", "backend")]),
            parse(2, [rolled], rollback_of="REL-001"),
            parse(3, [redone], retry_of="REL-002"),
            parse(4, [delivery("F-002", "backend", outcome="failed")], features=["F-002"]),
            parse(5, [delivery("F-002", "backend", attempt=2)], features=["F-002"], retry_of="REL-004"),
            parse(6, [failed], retry_of="REL-003"),
        ]
        kinds = record_kinds(records)
        self.assertEqual(
            {"REL-001": KIND_RELEASE, "REL-002": KIND_ROLLBACK, "REL-003": KIND_REDEPLOY, "REL-004": KIND_RELEASE, "REL-005": KIND_RELEASE, "REL-006": KIND_REDEPLOY},
            kinds,
        )

    def test_a_retry_cycle_does_not_loop(self) -> None:
        records = [parse(1, [delivery("F-001", "backend")], retry_of="REL-002"), parse(2, [delivery("F-001", "backend")], retry_of="REL-001")]
        self.assertEqual({"REL-001", "REL-002"}, set(record_kinds(records)))


class DeliveryTests(unittest.TestCase):
    def test_the_next_number_follows_the_highest_on_disk(self) -> None:
        self.assertEqual(1, next_release_number([]))
        self.assertEqual(5, next_release_number([parse(1, [delivery("F-001", "backend")]), parse(4, [delivery("F-001", "backend")])]))

    def test_the_current_delivery_is_the_highest_record_with_a_released_row(self) -> None:
        records = [
            parse(1, [delivery("F-001", "backend")]),
            parse(2, [delivery("F-002", "backend", version="build:backend#2")], features=["F-002"]),
            parse(3, [delivery("F-003", "backend", outcome="failed")], features=["F-003"]),
            parse(4, [delivery("F-001", "backend", outcome="rolled-back", attempt=None)], rollback_of="REL-002"),
        ]
        current = current_delivery(records, "backend", "production")
        self.assertEqual("REL-002", current[0].record_id)
        self.assertEqual(["F-002"], [row.item for row in current[1]])
        self.assertIsNone(current_delivery(records, "worker", "production"))
        self.assertIsNone(current_delivery(records, "backend", "staging"))

    def test_the_latest_record_counts_failures_and_rollbacks_too(self) -> None:
        records = [parse(1, [delivery("F-001", "backend")]), parse(2, [delivery("F-001", "backend", outcome="rolled-back", attempt=None)], rollback_of="REL-001")]
        self.assertEqual("REL-002", latest_record(records, "backend", "production").record_id)
        self.assertIsNone(latest_record(records, "worker", "production"))

    def test_the_status_board_reads_the_latest_record_and_the_outcome_of_an_app(self) -> None:
        records = [
            parse(1, [delivery("F-001", "backend"), delivery("F-001", "worker")]),
            parse(2, [delivery("F-001", "backend", outcome="rolled-back", attempt=None)], rollback_of="REL-001"),
            parse(3, [delivery("F-001", "backend", attempt=None, outcome="failed")], retry_of="REL-002"),
        ]
        self.assertEqual(["backend", "worker"], records[0].apps)
        self.assertEqual(["REL-003", "REL-001"], [latest_record(records, "backend").record_id, latest_record(records, "worker").record_id])
        self.assertEqual(["released", "rolled-back", "failed"], [record.outcome_for("backend") for record in records])
        self.assertIsNone(records[1].outcome_for("worker"))
        self.assertIsNone(latest_record(records, "elsewhere"))

    def test_an_attempt_counts_the_release_records_of_the_item_and_app(self) -> None:
        records = [
            parse(1, [delivery("F-001", "backend", outcome="failed")]),
            parse(2, [delivery("F-001", "backend", outcome="rolled-back", attempt=None)], rollback_of="REL-001"),
            parse(3, [delivery("F-002", "backend")], features=["F-002"]),
        ]
        kinds = record_kinds(records)
        self.assertEqual(2, release_attempt_of(records, kinds, "F-001", "backend"))
        self.assertEqual(1, release_attempt_of(records, kinds, "F-001", "worker"))
        self.assertEqual(2, release_attempt_of(records, kinds, "F-002", "backend"))


class RecordPageTests(unittest.TestCase):
    def problems(self, text: str, name: str = "REL-001.md", *, proposal: bool = False, today: date | None = None) -> list[str]:
        page = parse_markdown_text(Path(f"{RELEASES}/{name}"), text)
        return [item.code for item in check_record_page(f"{RELEASES}/{name}", page.frontmatter, page.body, today=today, proposal=proposal, parse_errors=page.parse_errors)]

    def test_a_record_page_in_the_form_has_no_problem(self) -> None:
        self.assertEqual([], self.problems(record_page(1, [delivery("F-001", "backend")])))

    def test_the_fields_and_sections_are_exact(self) -> None:
        good = record_page(1, [delivery("F-001", "backend")])
        for name, text in {
            "unknown field": good.replace("bugs: []", "bugs: []\nowner: me"),
            "missing field": good.replace("title: Release of F-001\n", ""),
            "bad id": good.replace("id: REL-001", "id: REL-1"),
            "id and name differ": good.replace("id: REL-001", "id: REL-002"),
            "bad outcome": good.replace("outcome: released", "outcome: done"),
            "bad date": good.replace(f"date: {date.today().isoformat()}", "date: someday"),
            "features not a list": good.replace("features: [F-001]", "features: F-001"),
            "both retry-of and rollback-of": good.replace("bugs: []", "bugs: []\nretry-of: REL-002\nrollback-of: REL-002"),
            "retry-of is not an id": good.replace("bugs: []", "bugs: []\nretry-of: yesterday"),
            "missing section": good.replace("## Notes\nNone.\n", ""),
            "empty summary": good.replace("F-001 is delivered to production.", ""),
        }.items():
            with self.subTest(case=name):
                self.assertTrue(self.problems(text), name)

    def test_a_proposal_carries_the_preview_day_and_the_placeholder(self) -> None:
        today = date(2026, 10, 9)
        self.assertEqual([], self.problems(record_page(1, [delivery("F-001", "backend")], day="2026-10-09"), proposal=True, today=today))
        self.assertEqual(["record_date_invalid"], self.problems(record_page(1, [delivery("F-001", "backend")], day="2026-10-08"), proposal=True, today=today))
        self.assertEqual(["release_record_invalid"], self.problems(record_page(1, [delivery("F-001", "backend")], day="2026-10-09", operation="op-1"), proposal=True, today=today))
        # On disk the operation names the producer and the date is any valid day.
        self.assertEqual([], self.problems(record_page(1, [delivery("F-001", "backend")], day="2026-10-08", operation="op-1")))

    def test_rows_for_one_app_and_target_agree_on_version_and_outcome(self) -> None:
        rows, _ = parse_record_rows(record_page(1, [delivery("F-001", "backend"), delivery("F-002", "backend", version="build:backend#2")]))
        self.assertEqual(["release_artifact_conflict"], [item.code for item in group_conflicts(rows)])
        rows, _ = parse_record_rows(record_page(1, [delivery("F-001", "backend"), delivery("F-002", "backend", outcome="failed")]))
        self.assertEqual(["release_artifact_conflict"], [item.code for item in group_conflicts(rows)])
        rows, _ = parse_record_rows(record_page(1, [delivery("F-001", "backend"), delivery("F-002", "backend"), delivery("F-001", "worker", version="build:worker#4")]))
        self.assertEqual([], group_conflicts(rows))

    def test_the_front_matter_follows_the_rows(self) -> None:
        rows, _ = parse_record_rows(record_page(1, [delivery("F-001", "backend"), delivery("BUG-002", "backend")]))
        frontmatter = {"features": ["F-001"], "bugs": ["BUG-002"], "outcome": "released"}
        self.assertEqual([], record_front_matter_problems("p", frontmatter, rows, KIND_RELEASE))
        for wrong in ({"features": []}, {"bugs": []}, {"outcome": "failed"}):
            with self.subTest(wrong=wrong):
                self.assertTrue(record_front_matter_problems("p", {**frontmatter, **wrong}, rows, KIND_RELEASE))


class SnapshotTests(unittest.TestCase):
    def citation(self, text: str = CONTRACT_TEXT) -> str:
        page = parse_markdown_text(Path("snapshot.md"), text)
        return contract_page_citation(page.frontmatter, page.body)

    def body(self, text: str = CONTRACT_TEXT) -> str:
        return f"## Contracts\n{format_snapshot('F-001', 'backend', self.citation(text), text)}\n"

    def test_a_snapshot_round_trips_and_its_digest_is_the_citation(self) -> None:
        snapshots, problems = parse_snapshots(self.body())
        self.assertEqual([], problems)
        self.assertEqual(("F-001", "backend", self.citation()), (snapshots[0].feature, snapshots[0].app, snapshots[0].citation))
        self.assertEqual(self.citation(), snapshots[0].digest_citation)
        self.assertTrue(self.citation().startswith("F-001@v1:c1:"))

    def test_the_fence_is_longer_than_any_run_of_backticks_inside_the_contract(self) -> None:
        text = CONTRACT_TEXT.replace("ReviewSummary", "````nested````")
        entry = format_snapshot("F-001", "backend", self.citation(text), text)
        self.assertIn("`````markdown", entry)
        snapshots, problems = parse_snapshots(f"## Contracts\n{entry}\n")
        self.assertEqual([], problems)
        self.assertEqual(self.citation(text), snapshots[0].digest_citation)

    def test_the_text_of_a_snapshot_cannot_differ_from_its_citation(self) -> None:
        tampered = CONTRACT_TEXT.replace("returns the summary", "returns everything")
        entry = format_snapshot("F-001", "backend", self.citation(), tampered)
        snapshots, _ = parse_snapshots(f"## Contracts\n{entry}\n")
        problems = snapshot_problems(snapshots, [], expected={("F-001", "backend"): (self.citation(), CONTRACT_TEXT)}, path="REL-001.md")
        self.assertEqual(["release_contract_snapshot_invalid"], [item.code for item in problems])

    def test_a_missing_or_unexpected_snapshot_is_reported(self) -> None:
        snapshots, _ = parse_snapshots(self.body())
        expected = {("F-001", "backend"): (self.citation(), CONTRACT_TEXT)}
        self.assertEqual([], snapshot_problems(snapshots, [], expected=expected, path="p"))
        self.assertEqual(["release_contract_snapshot_invalid"], [item.code for item in snapshot_problems([], [], expected=expected, path="p")])
        self.assertEqual(["release_contract_snapshot_invalid"], [item.code for item in snapshot_problems(snapshots, [], expected={}, path="p")])

    def test_two_entries_for_one_feature_and_app_are_one_too_many(self) -> None:
        snapshots, _ = parse_snapshots(self.body() + format_snapshot("F-001", "backend", self.citation(), CONTRACT_TEXT))
        problems = snapshot_problems(snapshots, [], expected={("F-001", "backend"): (self.citation(), CONTRACT_TEXT)}, path="p")
        self.assertTrue(problems)

    def test_a_heading_inside_the_fence_is_not_an_entry(self) -> None:
        text = CONTRACT_TEXT.replace("## Notes\nNone.", "## Notes\n### F-002 worker\n")
        snapshots, problems = parse_snapshots(self.body(text))
        self.assertEqual([], problems)
        self.assertEqual(1, len(snapshots))


class ListingTests(unittest.TestCase):
    def test_the_listing_digest_changes_with_a_record_and_ignores_the_format_page(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            wiki = Path(folder)
            self.assertEqual([], read_release_records(wiki))
            empty = release_listing_digest(wiki)
            (wiki / "releases").mkdir()
            (wiki / "releases" / "_FORMAT.md").write_text("# Format\n", encoding="utf-8")
            self.assertEqual(empty, release_listing_digest(wiki))
            (wiki / "releases" / "REL-001.md").write_text(record_page(1, [delivery("F-001", "backend")]), encoding="utf-8")
            self.assertNotEqual(empty, release_listing_digest(wiki))
            self.assertEqual(["REL-001"], [record.record_id for record in read_release_records(wiki)])

    def test_records_are_read_in_number_order(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            wiki = Path(folder)
            (wiki / "releases").mkdir()
            for number in (10, 2, 1000, 3):
                (wiki / "releases" / f"REL-{number:03d}.md").write_text(record_page(number, [delivery("F-001", "backend")]), encoding="utf-8")
            self.assertEqual(["REL-002", "REL-003", "REL-010", "REL-1000"], [record.record_id for record in read_release_records(wiki)])


class LintTests(ReleaseTests):
    def codes(self) -> set[str]:
        return {item.code for item in lint_wiki(self.root).diagnostics if item.severity == "error"}

    def test_a_clean_release_is_clean(self) -> None:
        self.release()
        self.assertEqual(set(), self.codes())

    def test_a_malformed_record_is_reported(self) -> None:
        self.release()
        self.put(record_path(2), record_page(2, [delivery("F-001", "backend")]).replace("outcome: released", "outcome: sideways"))
        self.assertIn("release-record-invalid", self.codes())

    def test_a_delivery_row_names_an_item_of_the_wiki_and_one_of_its_apps(self) -> None:
        self.release()
        self.put(record_path(2), record_page(2, [delivery("F-009", "backend")], features=["F-009"]))
        self.assertIn("release-record-invalid", self.codes())
        self.put(record_path(2), record_page(2, [delivery("F-001", "mobile")]))
        self.assertIn("release-record-invalid", self.codes())

    def test_a_release_row_that_disagrees_with_its_record_is_reported(self) -> None:
        self.release()
        page = self.read(FEATURE)
        for name, change in {
            "version": ("`build:backend#1` | release-1 | released", "`build:backend#5` | release-1 | released"),
            "target": ("| backend | production |", "| backend | staging |"),
            "outcome": ("release-1 | released | [REL-001]", "release-1 | failed | [REL-001]"),
        }.items():
            with self.subTest(case=name):
                self.assertIn(change[0], page, name)
                self.put(FEATURE, page.replace(*change, 1))
                self.assertIn("release-row-record-mismatch", self.codes())
        self.put(FEATURE, page)
        self.assertEqual(set(), self.codes())

    def test_a_release_row_that_links_a_record_the_wiki_does_not_have_is_reported(self) -> None:
        self.release()
        self.put(FEATURE, self.read(FEATURE).replace("[REL-001](../releases/REL-001.md)", "[REL-009](../releases/REL-009.md)", 1))
        self.assertTrue(self.codes() & {"release-row-record-mismatch", "broken-link"})

    def test_a_released_bug_has_a_released_row_for_each_of_its_apps(self) -> None:
        self.put("knowledge/wiki/bugs/BUG-001-open.md", bug_page("BUG-001", status="released", apps=["backend"]))
        self.assertIn("bug-page-invalid", self.codes())

    def test_a_rollback_names_an_earlier_record_and_the_deliveries_it_rolls_back(self) -> None:
        self.release()
        rows = [delivery("F-001", "backend", outcome="rolled-back", attempt=None, version="build:backend#9")]
        self.put(record_path(2), record_page(2, rows, rollback_of="REL-001", title="Rollback", rollback="Rolled back."))
        self.assertIn("release-record-invalid", self.codes())
        self.put(record_path(2), record_page(2, [delivery("F-001", "backend", outcome="rolled-back", attempt=None)], rollback_of="REL-007", title="Rollback", rollback="Rolled back."))
        self.assertIn("release-record-invalid", self.codes())

    def test_a_retry_names_a_record_with_a_failed_delivery(self) -> None:
        self.release()
        self.put(record_path(2), record_page(2, [delivery("F-001", "worker", attempt=2)], retry_of="REL-001"))
        self.assertIn("release-record-invalid", self.codes())

    def test_the_wiki_index_lists_the_records_in_their_own_group(self) -> None:
        self.release()
        index = self.read("knowledge/wiki/index.md")
        self.assertIn("## Releases", index)
        self.assertIn("(releases/REL-001.md)", index)

    def test_pending_rows_are_not_a_delivery(self) -> None:
        self.assertEqual(set(), self.codes())
        self.assertEqual("pending", self.evidence().release[0].outcome)
        self.assertEqual(pending_row("backend"), "| backend | — | `build:backend#1` | release-1 | pending | — | — |")
        self.assertEqual(release_row("backend", 1), "| backend | production | `build:backend#1` | release-1 | released | [REL-001](../releases/REL-001.md) | checked |")


class ContractSnapshotLintTests(ReleaseTests):
    """A released app is checked against the snapshot in its record, because the contract may be revised later."""

    CONTRACT = "knowledge/wiki/api-contracts/F-001.md"

    def setUp(self) -> None:
        super().setUp()
        self.put(self.CONTRACT, CONTRACT_TEXT)
        self.citation = contract_page_citation(*self.parts(CONTRACT_TEXT))
        self.put(FEATURE, self.cite(self.read(FEATURE)))

    def cite(self, page: str) -> str:
        """The delivery rows of both apps cite the contract as it is."""

        for app in ("backend", "worker"):
            page = page.replace(f"| {app} | `build:{app}#1` | none |", f"| {app} | `build:{app}#1` | {self.citation} |", 1)
        return page

    @staticmethod
    def parts(text: str):
        page = parse_markdown_text(Path("page.md"), text)
        return page.frontmatter, page.body

    def release_with(self, contracts: str) -> tuple[str, str]:
        feature, _record = self.all_released()
        feature = self.cite(feature)
        record = record_page(1, [delivery("F-001", "backend"), delivery("F-001", "worker")], contracts=contracts)
        return feature, record

    def snapshot(self, text: str = CONTRACT_TEXT, apps: tuple[str, ...] = ("backend", "worker")) -> str:
        return "\n\n".join(format_snapshot("F-001", app, self.citation, text).rstrip("\n") for app in apps)

    def codes(self) -> set[str]:
        return {item.code for item in lint_wiki(self.root).diagnostics if item.severity == "error"}

    def test_a_release_snapshots_the_contract_its_delivery_cites(self) -> None:
        self.settle(*self.release_with(self.snapshot()))
        self.assertEqual(("released", "none"), self.status())
        self.assertIn(self.citation, self.read(record_path(1)))
        self.assertEqual(set(), self.codes())

    def test_the_snapshot_is_required_and_verbatim(self) -> None:
        self.assertEqual(("release_contract_snapshot_invalid", 409), self.refuse(*self.release_with("None.")))
        self.assertEqual(("release_contract_snapshot_invalid", 409), self.refuse(*self.release_with(self.snapshot(CONTRACT_TEXT.replace("returns the summary", "returns everything")))))

    def test_a_snapshot_for_a_contract_no_row_cites_is_refused(self) -> None:
        self.assertEqual(("release_contract_snapshot_invalid", 409), self.refuse(*self.release_with(self.snapshot(apps=("backend", "worker", "mobile")))))
        self.assertEqual(("release_contract_snapshot_invalid", 409), self.refuse(*self.release_with(self.snapshot(apps=("backend",)))))

    def test_a_revised_contract_does_not_make_a_released_app_stale(self) -> None:
        self.settle(*self.release_with(self.snapshot()))
        revised = CONTRACT_TEXT.replace("version: 1", "version: 2").replace("returns the summary", "returns the summary and the reviewer")
        self.put(self.CONTRACT, revised)
        self.assertNotIn("stale-delivery-evidence", self.codes())

    def test_a_bug_fix_of_a_released_feature_snapshots_the_contract_its_delivery_row_cites(self) -> None:
        self.settle(*self.release_with(self.snapshot()))
        fix = table(FIX_HEADER, [fix_row("backend", "build:backend#2")])
        verification = table(VERIFICATION_HEADER, [verification_row("backend", "build:backend#2")])
        self.put("knowledge/wiki/bugs/BUG-001-fix.md", bug_page("BUG-001", status="verified", apps=["backend"], fix=fix, verification=verification))
        released_bug = bug_page(
            "BUG-001", status="released", apps=["backend"], fix=fix, verification=verification, release=table(RELEASE_HEADER, [release_row("backend", 2, version="build:backend#2")])
        )
        feature = self.read(FEATURE).replace(release_row("backend", 1), release_row("backend", 2, version="build:backend#2"))

        def proposal(contracts: str) -> list[dict[str, str]]:
            rows = [delivery("BUG-001", "backend", version="build:backend#2")]
            record = record_page(2, rows, features=[], bugs=["BUG-001"], title="Fix of BUG-001", summary="BUG-001 is delivered to production.", contracts=contracts)
            return [{"path": FEATURE, "content": feature}, {"path": "knowledge/wiki/bugs/BUG-001-fix.md", "content": released_bug}, {"path": record_path(2), "content": record}]

        self.assertEqual(("release_contract_snapshot_invalid", 409), self.refusal(proposal("None.")))
        self.apply("release-done", proposal(self.snapshot(apps=("backend",))), approver=self.owner)
        self.assertEqual(set(), self.codes())

    def test_a_snapshot_that_no_longer_matches_its_row_is_reported(self) -> None:
        self.settle(*self.release_with(self.snapshot()))
        record = self.read(record_path(1))
        self.put(record_path(1), record.replace("returns the summary", "returns everything", 1))
        self.assertTrue(self.codes() & {"stale-delivery-evidence", "release-record-invalid"})


if __name__ == "__main__":
    unittest.main()
