"""`qa-fail` through the board service: the archive, the participants, the failure it needs and a second delivery (CONTRACTS F15)."""

from __future__ import annotations

import unittest

from prism_cli.wiki_lint import lint_wiki
from prism_cli.wiki_model import qa_attempt, read_feature_evidence
from tests.board_approval import approve
from tests.qa_support import (
    BUGS,
    FEATURE,
    QaBoard,
    app_row,
    append_history,
    bug_page,
    history_entry,
    integration_row,
    release_row,
    requirement_path,
)
from tests.test_board_service import _set_requirement_status
from tests.test_lifecycle_model import DELIVERY_HEADER, delivery_row, table

BUG = f"{BUGS}/BUG-001-summary-export-drops-comments.md"


def line(cells: tuple[str, ...]) -> str:
    return "| " + " | ".join(cells) + " |"


class QaFailTests(QaBoard):
    def errors(self) -> set[str]:
        return {item.code for item in lint_wiki(self.root).diagnostics if item.severity == "error"}

    def record_failure(self) -> None:
        """qa-verify: worker fails AC-2 and BUG-001 is opened."""

        self.apply(
            "qa-verify",
            [{"path": FEATURE, "content": self.qa_table([app_row("worker", result="fail")])}, {"path": BUG, "content": bug_page("BUG-001", apps=["worker"])}],
        )

    def fail_changes(self, apps: list[str], *, linked: str = "none", participants: list[str] | None = None, mutate=None) -> list[dict[str, str]]:
        """The qa-fail proposal for `apps`, built from the page as it is: every row that moves is archived in one entry."""

        evidence = self.evidence()
        named = set(apps)
        lost = set(participants or [])
        archive = [("Delivery evidence", line(row.cells)) for row in evidence.delivery if row.app in named]
        archive += [("QA verification", line(row.cells)) for row in evidence.qa if named & set(row.apps)]
        archive += [("Release", line(row.cells)) for row in evidence.release if row.app in named or row.app in lost]
        page = self.read(FEATURE)
        page = self.with_section("Delivery evidence", table(DELIVERY_HEADER, [line(row.cells) for row in evidence.delivery if row.app not in named]), page)
        page = self.qa_table([line(row.cells) for row in evidence.qa if not named & set(row.apps)], page)
        page = self.release_table([line(row.cells) for row in evidence.release if row.app not in named and row.app not in lost], page)
        invalidations = ", ".join(f"{requirement_path(app)}: done -> in-progress" for app in apps)
        entry = history_entry(
            "qa-fail",
            affected=", ".join(apps),
            archived=archive,
            participants=", ".join(participants) if participants else "none",
            invalidations=invalidations,
            linked=linked,
        )
        page = append_history(page, entry)
        domains = {app: ["implementation", "tests", "qa", "release"] for app in apps}
        domains.update({app: ["qa", "release"] for app in participants or []})
        page = self.frontmatter_with(self.with_status("in-dev", "dev", page), **{"app-revalidation": domains})
        changes = [{"path": FEATURE, "content": page}]
        changes += [{"path": requirement_path(app), "content": _set_requirement_status(self.read(requirement_path(app)), "in-progress")} for app in apps]
        if mutate is not None:
            mutate(changes)
        return changes

    def test_an_app_is_sent_back_and_its_evidence_archived(self) -> None:
        self.record_failure()
        preview = self.apply("qa-fail", self.fail_changes(["worker"], linked="BUG-001"))
        self.assertEqual("qa-fail", preview["action"])
        self.assertEqual(("in-dev", "dev"), self.status())
        evidence = self.evidence()
        self.assertEqual(["backend"], [row.app for row in evidence.delivery])
        self.assertEqual([], list(evidence.qa))
        self.assertIn("backend: ready-for-qa; worker: in-dev", self.read("knowledge/wiki/status-board.md"))
        self.assertEqual({"worker": ["implementation", "tests", "qa", "release"]}, self.feature()[0]["app-revalidation"])
        self.assertIn("status: in-progress", self.read(requirement_path("worker")))
        self.assertEqual(set(), self.errors())

    def test_a_failing_row_alone_supports_the_failure(self) -> None:
        self.apply("qa-verify", [{"path": FEATURE, "content": self.qa_table([app_row("worker", result="fail")])}])
        self.apply("qa-fail", self.fail_changes(["worker"]))
        self.assertEqual(("in-dev", "dev"), self.status())

    def test_a_failure_with_nothing_on_record_is_unsupported(self) -> None:
        error = self.refused("qa-fail", self.fail_changes(["worker"]))
        self.assertEqual("qa_failure_unsupported", error.code)
        # A passing row is no failure.
        self.apply("qa-verify", [{"path": FEATURE, "content": self.qa_table([app_row("worker")])}])
        self.assertEqual("qa_failure_unsupported", self.refused("qa-fail", self.fail_changes(["worker"])).code)

    def test_a_linked_bug_in_progress_supports_the_failure_and_a_deferred_one_does_not(self) -> None:
        deferred = bug_page("BUG-001", blocking=False, apps=["worker"], extra={"deferred-reason": "Later."})
        self.put(BUG, deferred)
        self.assertEqual("qa_failure_unsupported", self.refused("qa-fail", self.fail_changes(["worker"], linked="BUG-001")).code)
        self.put(BUG, bug_page("BUG-001", status="in-fix", apps=["worker"]))
        self.apply("qa-fail", self.fail_changes(["worker"], linked="BUG-001"))
        self.assertEqual(("in-dev", "dev"), self.status())

    def test_a_listed_bug_must_exist(self) -> None:
        self.assertEqual("linked_bug_invalid", self.refused("qa-fail", self.fail_changes(["worker"], linked="BUG-099")).code)

    def test_a_participant_of_an_archived_integration_row_loses_its_pending_release_row(self) -> None:
        page = self.qa_table([app_row("backend"), integration_row()])
        self.apply("qa-pass", [{"path": FEATURE, "content": self.with_status("in-qa", "qa", self.release_table([release_row("backend")], page))}])
        self.apply("qa-verify", [{"path": FEATURE, "content": self.qa_table([*self.active_rows("qa"), app_row("worker", result="fail")])}])
        self.apply("qa-fail", self.fail_changes(["worker"], participants=["backend"]))
        evidence = self.evidence()
        # backend keeps its delivery and app row, loses its Release row and re-verifies QA and release.
        self.assertEqual(["backend"], [row.app for row in evidence.delivery])
        self.assertEqual(["backend"], [row.key for row in evidence.qa])
        self.assertEqual([], list(evidence.release))
        self.assertEqual({"worker": ["implementation", "tests", "qa", "release"], "backend": ["qa", "release"]}, self.feature()[0]["app-revalidation"])
        # Its attempt is unchanged; worker's advanced because a QA row naming it was archived.
        history = self.feature()[1]
        from prism_cli.wiki_model import parse_evidence_history

        entries = parse_evidence_history(history)
        self.assertEqual((1, 2), (qa_attempt("backend", entries), qa_attempt("worker", entries)))

    def test_the_participants_must_be_listed(self) -> None:
        page = self.qa_table([app_row("backend"), integration_row()])
        self.apply("qa-pass", [{"path": FEATURE, "content": self.with_status("in-qa", "qa", self.release_table([release_row("backend")], page))}])
        self.apply("qa-verify", [{"path": FEATURE, "content": self.qa_table([*self.active_rows("qa"), app_row("worker", result="fail")])}])
        changes = self.fail_changes(["worker"], participants=["backend"])
        changes[0]["content"] = changes[0]["content"].replace("- Participants: backend", "- Participants: none")
        self.assertEqual("history_participants_mismatch", self.refused("qa-fail", changes).code)

    def test_every_removed_row_is_archived_and_no_archived_row_stays_active(self) -> None:
        self.record_failure()
        changes = self.fail_changes(["worker"], linked="BUG-001")
        without_archive = changes[0]["content"].replace("  | QA verification |", "  | Delivery evidence |", 1)
        self.assertIn(self.refused("qa-fail", [{"path": FEATURE, "content": without_archive}, *changes[1:]]).code, {"evidence_not_archived"})
        still_active = self.with_section("Delivery evidence", table(DELIVERY_HEADER, [line(row.cells) for row in self.evidence().delivery]), changes[0]["content"])
        self.assertEqual("evidence_still_active", self.refused("qa-fail", [{"path": FEATURE, "content": still_active}, *changes[1:]]).code)

    def test_the_requirement_page_of_a_failed_app_goes_back_to_in_progress(self) -> None:
        self.record_failure()
        changes = self.fail_changes(["worker"], linked="BUG-001")
        # The entry lists the page as invalidated, and the proposal leaves it out.
        self.assertEqual("reopen_invalidation_mismatch", self.refused("qa-fail", changes[:1]).code)
        # A proposal that does not list it fails the same check from the other side.
        unlisted = changes[0]["content"].replace(f"{requirement_path('worker')}: done -> in-progress", "No requirement or API page is invalidated.")
        self.assertEqual("lifecycle_write_scope", self.refused("qa-fail", [{"path": FEATURE, "content": unlisted}]).code)

    def test_the_revalidation_domains_are_written_exactly(self) -> None:
        self.record_failure()
        changes = self.fail_changes(["worker"], linked="BUG-001")
        wrong = self.frontmatter_with(changes[0]["content"], **{"app-revalidation": {"worker": ["implementation"]}})
        self.assertEqual("revalidation_required", self.refused("qa-fail", [{"path": FEATURE, "content": wrong}, *changes[1:]]).code)

    def test_the_status_is_in_dev(self) -> None:
        self.record_failure()
        changes = self.fail_changes(["worker"], linked="BUG-001")
        wrong = self.with_status("ready-for-qa", "qa", changes[0]["content"])
        self.assertEqual("lifecycle_action_required", self.refused("qa-fail", [{"path": FEATURE, "content": wrong}, *changes[1:]]).code)

    def test_an_app_that_is_released_cannot_fail(self) -> None:
        released = "| backend | production | `build:backend#1` | release-1 | released | [REL-001](https://records.example/REL-001) | checked |"
        page = self.qa_table([app_row("backend"), integration_row(), app_row("worker", result="fail")])
        self.put(FEATURE, self.release_table([released], page))
        error = self.refused("qa-fail", self.fail_changes(["backend"]))
        self.assertEqual("app_stage_mismatch", error.code)

    def test_a_second_delivery_starts_a_new_generation_and_attempt(self) -> None:
        self.set_policy(True)
        self.record_failure()
        self.apply("qa-fail", self.fail_changes(["worker"], linked="BUG-001"))
        # dev-done delivers worker again; its delivery row is generation 2 and its QA attempt is qa-2.
        current = self.read(FEATURE)
        rows = [line(row.cells) for row in self.evidence().delivery] + [delivery_row("worker", "build:worker#2")]
        page = self.with_section("Delivery evidence", table(DELIVERY_HEADER, rows), self.with_status("ready-for-qa", "qa", current))
        page = self.frontmatter_with(page, **{"app-revalidation": {"worker": ["qa", "release"]}})
        done = _set_requirement_status(self.read(requirement_path("worker")), "done")
        preview = self.apply("dev-done", [{"path": FEATURE, "content": page}, {"path": requirement_path("worker"), "content": done}], approver=self.devi)
        self.assertEqual([("delivery", "F-001", "worker", 2)], [(item["kind"], item["item_id"], item["app"], item["generation"]) for item in preview["produces_evidence"]])
        row = app_row("worker", attempt=2)
        row = row.replace("build:worker#1", "build:worker#2")
        self.apply("qa-verify", [{"path": FEATURE, "content": self.qa_table([row])}])
        self.assertEqual(2, self.evidence().qa[0].attempt)
        self.assertEqual("qa_attempt_mismatch", self.refused("qa-verify", [{"path": FEATURE, "content": self.qa_table([*self.active_rows("qa"), app_row("backend", attempt=3)])}]).code)


if __name__ == "__main__":
    unittest.main()
