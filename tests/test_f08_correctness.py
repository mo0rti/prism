"""Correctness review regressions: archive deltas, release rows and record authority."""

from __future__ import annotations

import unittest
from pathlib import Path

from prism_cli.board_service import BoardError, BoardService, _parse_markdown
from prism_cli.release_lint import validate_release_records
from prism_cli.release_rules import check_feature_release_rows, rollback_problems
from prism_cli.wiki_model import parse_markdown_text, read_feature_evidence
from prism_cli.wiki_releases import ReleaseRecord, current_delivery, next_release_number, parse_record_rows, record_kinds
from tests.qa_support import FEATURE, QaBoard, app_row, requirement_path
from tests.release_pages import delivery, record_page, record_path, release_row
from tests.release_support import ReleaseTests
from tests.test_bug_actions import BUG, OTHER, BugBoard, fix, verification
from tests import test_feature_scope_edit as scope_tests
from tests.test_feature_scope_edit import with_apps
from tests.test_lifecycle_model import DELIVERY_HEADER, delivery_row, table
from tests import test_qa_fail as fail_tests
from tests import test_qa_returns as return_tests
from tests import test_release_bugs as bug_release_tests
from tests import test_release_reopen as reopen_tests
from tests import test_design_tracks as track_tests
from tests import test_release_variants as variant_tests
from tests.qa_support import append_history, history_entry
from tests.test_board_service import _replace_body_section_text


class ArchiveDeltaTests(QaBoard):
    """Every archiving route rejects additions, replacements and duplicate additions."""

    def test_every_feature_archive_route_rejects_added_active_evidence(self) -> None:
        original = self.read(FEATURE)
        old = self.feature()[0]
        for action in (
            "scope-edit", "qa-fail", "release-return-dev", "dev-return-spec", "dev-return-design",
            "qa-return-spec", "qa-return-design", "reopen-spec", "reopen-design", "reopen-dev",
        ):
            for row in (delivery_row("backend", "build:backend#99"), self.active_rows("delivery")[0]):
                with self.subTest(action=action, row=row):
                    with self.assertRaises(BoardError) as caught:
                        proposed = self.with_section("Delivery evidence", table(DELIVERY_HEADER, [*self.active_rows("delivery"), row]))
                        self.service._validate_evidence_history(action, original, proposed, old, relative=FEATURE, require_entry=False)
                    self.assertEqual("evidence_unexpectedly_added", caught.exception.code)

    def test_a_scope_edit_rejects_a_replacement_row(self) -> None:
        original = self.read(FEATURE)
        proposed = original.replace("build:backend#1", "build:backend#99")
        with self.assertRaises(BoardError) as caught:
            self.service._validate_evidence_history("scope-edit", original, proposed, self.feature()[0], relative=FEATURE, require_entry=False)
        self.assertEqual("evidence_unexpectedly_added", caught.exception.code)

    def test_an_archive_cannot_replace_a_case_sensitive_evidence_cell(self) -> None:
        original = self.read(FEATURE)
        proposed = original.replace("Reviewed source record", "REVIEWED source record")
        self.assertNotEqual(original, proposed)
        with self.assertRaises(BoardError) as caught:
            self.service._validate_evidence_history("scope-edit", original, proposed, self.feature()[0], relative=FEATURE, require_entry=False)
        self.assertEqual("evidence_unexpectedly_added", caught.exception.code)

    def test_qa_fail_cannot_add_a_duplicate_to_the_unaffected_app(self) -> None:
        fail_tests.QaFailTests.record_failure(self)
        changes = fail_tests.QaFailTests.fail_changes(self, ["worker"], linked="BUG-001")
        kept = self.active_rows("delivery")[0]
        changes[0]["content"] = self.with_section("Delivery evidence", table(DELIVERY_HEADER, [kept, kept]), changes[0]["content"])
        self.assertEqual("evidence_unexpectedly_added", self.refused("qa-fail", changes).code)


class ScopeForgeryTests(unittest.TestCase):
    setUp = scope_tests.ScopeEditBoardTests.setUp
    read = scope_tests.ScopeEditBoardTests.read
    preview = scope_tests.ScopeEditBoardTests.preview
    apply = scope_tests.ScopeEditBoardTests.apply

    def test_f26_cannot_create_the_remaining_apps_first_delivery(self) -> None:
        from tests.test_feature_scope_edit import FEATURE_ONE

        original = self.read(FEATURE_ONE)
        old = _parse_markdown(original)[0]
        old.update(status="in-dev", owner="dev")
        original = self.service._replace_frontmatter(original, old)
        (self.root / FEATURE_ONE).write_text(original, encoding="utf-8", newline="\n")
        proposed = with_apps(original, ["backend"])
        proposed = self.service._replace_frontmatter(proposed, {**_parse_markdown(proposed)[0], "status": "ready-for-qa", "owner": "qa"})
        from tests.test_board_service import _replace_body_section_text

        proposed = _replace_body_section_text(proposed, "Delivery evidence", table(DELIVERY_HEADER, [delivery_row("backend", "build:backend#1")]))
        with self.assertRaises(BoardError) as caught:
            self.preview("feature-scope", [{"path": FEATURE_ONE, "content": proposed}])
        self.assertEqual("evidence_unexpectedly_added", caught.exception.code)
        self.assertEqual(original, self.read(FEATURE_ONE))

    def test_f26_then_design_return_and_handoff_keeps_the_removed_requirement(self) -> None:
        from tests.board_approval import human_with_roles
        from tests.test_board_service import _set_requirement_status

        path = scope_tests.FEATURE_ONE
        tracks = {"ui": "not-applicable", "ui-reason": "No app in scope has a UI.", "technical": "done"}
        page = self.read(path)
        fm, _body = _parse_markdown(page)
        fm["design-tracks"] = tracks
        page = self.service._replace_frontmatter(page, fm)
        (self.root / path).write_text(page, encoding="utf-8", newline="\n")
        technical = "knowledge/wiki/technical-design/F-001-document-review.md"
        technical_page = track_tests.technical_page(apps="[backend]", strategy=["| AC-1 | backend | automated | integration | Verify the recorded review outcome |"], impact=["| backend | reviews | Record the review outcome |"])
        (self.root / technical).write_bytes(technical_page.encode("utf-8"))
        removed = scope_tests.requirement_path("F-001", "legacy-batch")
        historical = self.read(removed)
        self.apply(self.preview("feature-scope", [{"path": path, "content": with_apps(page, ["backend"])}]))
        scoped = self.read(path)
        entry = history_entry("dev-return-design", affected="backend", archived=[], tracks="technical", invalidations="No requirement or API page is invalidated.").replace(track_tests.CHECK_DATE.isoformat(), self.service._history_day()).replace("- Archived evidence:\n", "- Archived evidence: none\n")
        returned = append_history(scoped, entry)
        fm, _body = _parse_markdown(returned)
        fm.update({"status": "in-design", "owner": "tech-lead", "revalidation": ["design", "technical-design"], "app-revalidation": {"backend": return_tests.ALL_DOMAINS}, "design-tracks": {**tracks, "technical": "pending"}})
        returned = self.service._replace_frontmatter(returned, fm)
        self.apply(self.preview("feature-reopen", [{"path": path, "content": returned}]), approver=human_with_roles(self.service, "Developer", "dev"))
        fm.update({"status": "ready-for-dev", "owner": "dev", "revalidation": [], "design-tracks": tracks})
        handoff = self.service._replace_frontmatter(self.read(path), fm)
        handoff = _replace_body_section_text(handoff, "Design", "- Technical: [Technical design](../technical-design/F-001-document-review.md)")
        requirement = scope_tests.requirement_path("F-001", "backend")
        changes = [
            {"path": path, "content": handoff},
            {"path": technical, "content": technical_page},
            {"path": requirement, "content": _set_requirement_status(self.read(requirement), "pending")},
        ]
        self.apply(self.preview("design-handoff", changes), approver=human_with_roles(self.service, "Design owner", "tech-lead"))
        self.assertEqual(("ready-for-dev", "dev"), tuple(_parse_markdown(self.read(path))[0][key] for key in ("status", "owner")))
        self.assertEqual(historical, self.read(removed))


class HandoffScopeTests(QaBoard):
    def test_a_removed_apps_requirement_is_no_handoff_obligation(self) -> None:
        original = self.read(requirement_path("worker"))
        feature = {"id": "F-001", "path": FEATURE, "after": {**self.feature()[0], "apps": ["backend"]}}
        self.service._assert_requirement_pages_complete({}, {}, feature)
        self.assertEqual(original, self.read(requirement_path("worker")))
        # A duplicate of the removed app is also historical, but scoped duplicates still block.
        self.put("knowledge/wiki/app-requirements/F-001-worker-old.md", original)
        self.service._assert_requirement_pages_complete({}, {}, feature)
        self.put("knowledge/wiki/app-requirements/F-001-backend-old.md", self.read(requirement_path("backend")))
        with self.assertRaises(BoardError) as caught:
            self.service._assert_requirement_pages_complete({}, {}, feature)
        self.assertEqual("requirements_incomplete", caught.exception.code)


def duplicate_archive(changes: list[dict[str, str]]) -> None:
    text = changes[0]["content"]
    row = next(line for line in text.splitlines() if line.lstrip().startswith("| Delivery evidence |"))
    changes[0]["content"] = text.replace(row, row + "\n" + row, 1)


class QaArchiveRouteTests(QaBoard):
    seed_tracks = return_tests.ReturnTests.seed_tracks
    every_row = return_tests.ReturnTests.every_row
    return_changes = return_tests.ReturnTests.return_changes
    parts = return_tests.ReturnTests.parts

    def test_qa_return_spec_counts_duplicate_archives(self) -> None:
        self.seed_tracks()
        changes = self.return_changes("qa-return-spec")
        duplicate_archive(changes)
        self.assertEqual("evidence_not_archived", self.refused("feature-reopen", changes).code)

    def test_qa_return_design_counts_duplicate_archives(self) -> None:
        self.seed_tracks()
        changes = self.return_changes("qa-return-design", tracks="technical")
        duplicate_archive(changes)
        self.assertEqual("evidence_not_archived", self.refused("feature-reopen", changes).code)


class DevArchiveRouteTests(track_tests.TrackCase):
    BACKEND_ROW = track_tests.DevReturnTests.BACKEND_ROW
    settled_pages = track_tests.DevReturnTests.settled_pages
    in_dev = track_tests.DevReturnTests.in_dev
    entry = track_tests.DevReturnTests.entry
    returned = track_tests.DevReturnTests.returned

    def check_route(self, route: str) -> None:
        self.in_dev(delivered=True)
        row = self.evidence_row()
        changes = self.returned(route, tracks=None if route == "specified" else track_tests.DesignTracks("done", "pending", None, None, ("ui",)), affected="ui, technical" if route == "specified" else "technical", archived="| Delivery evidence " + row, invalidations=f"{track_tests.BACKEND_REQ}: done -> in-progress", extra=((track_tests.BACKEND_REQ, track_tests.requirement_page("backend", "in-progress")),))
        duplicate_archive(changes)
        self.assertEqual("evidence_not_archived", self.rejected("feature-reopen", changes).code)

    def evidence_row(self) -> str:
        cells = read_feature_evidence(_parse_markdown(self.read(track_tests.FEATURE))[1]).delivery[0].cells
        return "| " + " | ".join(cells) + " |"

    def test_dev_return_spec_counts_duplicate_archives(self) -> None:
        self.check_route("specified")

    def test_dev_return_design_counts_duplicate_archives(self) -> None:
        self.check_route("in-design")


class ReopenArchiveRouteTests(reopen_tests.ReopenBoard):
    def check_route(self, route: str) -> None:
        self.seed_tracks()
        changes = self.dev_changes(("backend",)) if route == "reopen-dev" else self.reopen_changes(route, tracks="ui, technical" if route == "reopen-spec" else "technical")
        duplicate_archive(changes)
        self.assertEqual("evidence_not_archived", self.refused("feature-reopen", changes).code)

    def test_reopen_spec_counts_duplicate_archives(self) -> None:
        self.check_route("reopen-spec")

    def test_reopen_design_counts_duplicate_archives(self) -> None:
        self.check_route("reopen-design")

    def test_reopen_dev_counts_duplicate_archives(self) -> None:
        self.check_route("reopen-dev")


class ReleaseReturnArchiveTests(ReleaseTests):
    return_changes = variant_tests.ReleaseReturnTests.return_changes

    def test_release_return_dev_counts_duplicate_archives(self) -> None:
        changes = self.return_changes(["backend"], participants=["worker"])
        duplicate_archive(changes)
        self.assertEqual("evidence_not_archived", self.refused("release-done", changes).code)


class ReleasePreservationTests(ReleaseTests):
    def test_releasing_b_cannot_omit_as_pending_row(self) -> None:
        old = self.evidence()
        page = self.released_page([release_row("worker", 1)], status="in-qa", owner="qa")
        new = read_feature_evidence(_parse_markdown(page)[1])
        _named, problems = check_feature_release_rows(
            feature_id="F-001", old=old, new=new,
            stages={"backend": "ready-for-release", "worker": "ready-for-release"},
            active=["backend", "worker"], policy=self.service._read_policy(), attempt_of=lambda app: 1, record_id="REL-001",
        )
        self.assertIn("release_row_invalid", [problem.code for problem in problems])
        record = record_page(1, [delivery("F-001", "worker")])
        self.assertEqual(("release_row_invalid", 409), self.refuse(page, record))


class BugIntegrityTests(BugBoard):
    def test_the_canonical_bug_cannot_close_under_its_duplicate(self) -> None:
        self.plant()
        self.put(OTHER, self.bug("closed", extra={"close-reason": "duplicate", "duplicate-of": "BUG-001"}).replace("id: BUG-001", "id: BUG-002"))
        self.put("knowledge/wiki/bugs/BUG-003-canonical.md", self.bug("open").replace("id: BUG-001", "id: BUG-003"))
        self.put(FEATURE, self.frontmatter_with(self.read(FEATURE), sources=[*self.feature()[0]["sources"], BUG]))
        for disposition in (
            {"close-reason": "promoted", "promoted-to": "F-001"},
            {"close-reason": "wont-fix: The export is replaced."},
            {"close-reason": "duplicate", "duplicate-of": "BUG-003"},
        ):
            with self.subTest(disposition=disposition):
                with self.assertRaises(BoardError) as caught:
                    self.ready("bug-update", [{"path": BUG, "content": self.bug("closed", extra=disposition)}])
                self.assertEqual("duplicate_target_invalid", caught.exception.code)
                self.assertIn("BUG-002", caught.exception.message)

    def test_bug_reject_and_reopen_count_each_archived_occurrence(self) -> None:
        from tests.qa_support import fix_row, verification_row

        for action, status, extra, destination in (
            ("bug-reject", "verified", {}, "in-fix"),
            ("bug-reopen", "closed", {"close-reason": "wont-fix: The report was withdrawn."}, "open"),
        ):
            self.plant(status, fix=fix(), verification=verification(), extra=extra)
            archived = [("Fix", fix_row("worker", "build:worker#2")), ("Verification", verification_row("worker", "build:worker#2"))]
            if action == "bug-reject":
                archived.append(("Verification", verification_row("worker", "build:worker#2", result="fail")))
            archived.append(archived[0])
            proposed = self.bug(destination, history="\n" + self.entry(action, archived))
            with self.subTest(action=action):
                with self.assertRaises(BoardError) as caught:
                    self.ready("bug-update", [{"path": BUG, "content": proposed}])
                self.assertEqual("evidence_not_archived", caught.exception.code)


class BugReleaseRowTests(ReleaseTests):
    verified = bug_release_tests.ReleaseBugTests.verified
    released_bug = bug_release_tests.ReleaseBugTests.released_bug

    def test_contradictory_bug_release_rows_are_refused_in_both_orders(self) -> None:
        self.put(BUG, self.verified(feature="none"))
        failed, released = release_row("backend", 1, outcome="failed"), release_row("backend", 1)
        record = record_page(1, [delivery("BUG-001", "backend")], features=[], bugs=["BUG-001"])
        for rows in ([failed, released], [released, failed], [released, released]):
            with self.subTest(rows=rows):
                with self.assertRaises(BoardError) as caught:
                    self.ready("release-done", [{"path": BUG, "content": self.released_bug(rows, feature="none")}, {"path": record_path(1), "content": record}])
                self.assertEqual("release_row_invalid", caught.exception.code)

    def test_record_comparison_does_not_collapse_duplicate_bug_rows(self) -> None:
        rows = parse_record_rows(record_page(1, [delivery("BUG-001", "backend", outcome="failed"), delivery("BUG-001", "backend")], features=[], bugs=["BUG-001"]))[0]
        expected = {("BUG-001", "backend"): ("production", "build:backend#1", 1, "released", "checked")}
        for ordered in (rows, rows[::-1]):
            with self.subTest(order=[row.outcome for row in ordered]):
                problems = self.service._d4_record_rows_problems(record_path(1), ordered, expected)
                self.assertIn("release_row_invalid", [problem.code for problem in problems])

    def test_each_retained_bug_release_row_is_compared_with_its_record(self) -> None:
        old = self.released_bug([release_row("backend", 1, version="build:backend#99")], feature="none", apps=["backend", "worker"], status="verified")
        new = self.released_bug([release_row("backend", 1, version="build:backend#99"), release_row("worker", 2)], feature="none", apps=["backend", "worker"])
        record = ReleaseRecord(parse_markdown_text(Path(record_path(1)), record_page(1, [delivery("BUG-001", "backend")], features=[], bugs=["BUG-001"])))
        with self.assertRaises(BoardError) as caught:
            self.service._d4_bug(BUG, {BUG: new}, {BUG: old}, "REL-002", [record], record_kinds([record]), self.service._read_policy())
        self.assertEqual("release_row_invalid", caught.exception.code)


class ReleaseAuthorityTests(unittest.TestCase):
    def parsed(self, number: int, text: str) -> ReleaseRecord:
        return ReleaseRecord(parse_markdown_text(Path(record_path(number)), text))

    def assert_no_authority(self, bad: ReleaseRecord, earlier: list[ReleaseRecord] | None = None) -> None:
        records = [*(earlier or []), bad]
        valid, problems = validate_release_records(records)
        self.assertNotIn(bad, valid)
        self.assertIn(bad.page.path, problems)
        self.assertEqual(max((record.number for record in earlier or []), default=0) + 1, next_release_number(records))
        current = current_delivery(records, "backend", "production")
        self.assertTrue(current is None or current[0].record_id != bad.record_id)
        rollback = parse_record_rows(record_page(1000, [delivery("F-001", "backend", outcome="rolled-back", attempt=None)], rollback_of=bad.record_id))[0]
        self.assertIn("rollback_target_invalid", [problem.code for problem in rollback_problems(rollback_of=bad.record_id, rows=rollback, records=valid, kinds=record_kinds(valid))])

    def test_astras_missing_sections_probe_has_no_authority(self) -> None:
        text = record_page(999, [delivery("F-001", "backend")]).split("\n## Contracts", 1)[0]
        self.assert_no_authority(self.parsed(999, text))

    def test_astras_contradictory_rows_probe_has_no_authority_in_either_order(self) -> None:
        for rows in ([delivery("F-001", "backend", outcome="failed"), delivery("F-001", "backend")], [delivery("F-001", "backend"), delivery("F-001", "backend", outcome="failed")]):
            with self.subTest(rows=rows):
                self.assert_no_authority(self.parsed(999, record_page(999, rows)))

    def test_duplicate_rows_outcome_and_metadata_disagreement_have_no_authority(self) -> None:
        cases = [
            record_page(999, [delivery("F-001", "backend")] * 2),
            record_page(999, [delivery("F-001", "backend")], outcome="failed"),
            record_page(999, [delivery("F-001", "backend")], features=["F-002"]),
        ]
        for text in cases:
            with self.subTest(text=text):
                self.assert_no_authority(self.parsed(999, text))

    def test_a_broken_snapshot_has_no_authority(self) -> None:
        contracts = "### F-001 backend\n\n- Contract: `F-001@v1:sha256:" + "a" * 64 + "`\n\n````markdown\n---\nfeature-id: F-001\nversion: 1\nstatus: agreed\n---\nChanged contract.\n````\n"
        self.assert_no_authority(self.parsed(999, record_page(999, [delivery("F-001", "backend")], contracts=contracts)))

    def test_an_unclosed_snapshot_is_refused(self) -> None:
        from prism_cli.wiki_releases import format_snapshot, parse_snapshots
        from prism_cli.wiki_model import contract_page_citation

        text = track_tests.contract_page()
        citation = contract_page_citation(*_parse_markdown(text))
        snapshot = format_snapshot("F-001", "backend", citation, text).rsplit("````", 1)[0]
        _snapshots, problems = parse_snapshots("## Contracts\n" + snapshot)
        self.assertTrue(problems, "the snapshot fence must close")

    def test_a_snapshot_cannot_name_a_different_feature_from_its_contract(self) -> None:
        from prism_cli.wiki_releases import format_snapshot
        from prism_cli.wiki_model import contract_page_citation

        text = track_tests.contract_page(feature_id="F-002")
        snapshot = format_snapshot("F-001", "backend", contract_page_citation(*_parse_markdown(text)), text)
        self.assert_no_authority(self.parsed(999, record_page(999, [delivery("F-001", "backend")], contracts=snapshot)))

    def test_retry_and_rollback_reference_semantics_are_checked(self) -> None:
        first = self.parsed(1, record_page(1, [delivery("F-001", "backend", outcome="failed")]))
        cases = [
            record_page(999, [delivery("F-001", "backend", attempt=2)], retry_of="REL-001"),
            record_page(999, [delivery("F-001", "worker", attempt=2)], retry_of="REL-001"),
            record_page(999, [delivery("F-001", "backend", outcome="rolled-back", attempt=None)], rollback_of="REL-001"),
        ]
        valid_retry = self.parsed(999, cases[0])
        self.assertEqual([first, valid_retry], validate_release_records([first, valid_retry])[0])
        for text in cases[1:]:
            with self.subTest(text=text):
                self.assert_no_authority(self.parsed(999, text), [first])

    def test_wrong_kind_and_wrong_app_rollback_targets_have_no_authority(self) -> None:
        first = self.parsed(1, record_page(1, [delivery("F-001", "backend")]))
        rollback = self.parsed(2, record_page(2, [delivery("F-001", "backend", outcome="rolled-back", attempt=None)], rollback_of="REL-001"))
        self.assertEqual([first, rollback], validate_release_records([first, rollback])[0])
        for text in (
            record_page(999, [delivery("F-001", "worker", outcome="rolled-back", attempt=None)], rollback_of="REL-001"),
            record_page(999, [delivery("F-001", "backend", outcome="rolled-back", attempt=None)], rollback_of="REL-002"),
            record_page(999, [delivery("F-001", "backend", attempt=2)], retry_of="REL-001"),
            record_page(999, [delivery("F-001", "backend", attempt=2)], retry_of="REL-002"),
        ):
            with self.subTest(text=text):
                self.assert_no_authority(self.parsed(999, text), [first, rollback])


if __name__ == "__main__":
    unittest.main()
