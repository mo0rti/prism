"""`qa-pass` through the board service: coverage, the bug rule, separation and revalidation (CONTRACTS F13, F14)."""

from __future__ import annotations

import unittest

from prism_cli.board_service import BoardError
from prism_cli.wiki_lint import lint_wiki
from tests.board_approval import approve
from tests.qa_support import (
    BUGS,
    FEATURE,
    FIX_HEADER,
    VERIFICATION_HEADER,
    QaBoard,
    app_row,
    bug_page,
    fix_row,
    integration_row,
    release_row,
    verification_row,
)
from tests.test_lifecycle_model import table

BUG = f"{BUGS}/BUG-001-summary-export-drops-comments.md"


class QaPassTests(QaBoard):
    def clean_backend(self) -> str:
        """The proposal that verifies backend and its integration and passes backend in one approval."""

        page = self.qa_table([app_row("backend"), integration_row()])
        return self.with_status("in-qa", "qa", self.release_table([release_row("backend")], page))

    def pass_both(self) -> str:
        page = self.qa_table([app_row("backend"), app_row("worker"), integration_row()])
        return self.with_status("ready-for-release", "release", self.release_table([release_row("backend"), release_row("worker")], page))

    def errors(self) -> set[str]:
        return {item.code for item in lint_wiki(self.root).diagnostics if item.severity == "error"}

    def test_a_clean_run_passes_an_app_in_one_approval(self) -> None:
        preview = self.apply("qa-pass", [{"path": FEATURE, "content": self.clean_backend()}])
        self.assertEqual("qa-pass", preview["action"])
        # backend is ready for release; worker was verified through the integration row, so the minimum is in-qa.
        self.assertEqual(("in-qa", "qa"), self.status())
        self.assertIn("backend: ready-for-release; worker: in-qa", self.read("knowledge/wiki/status-board.md"))
        subjects = [(item["kind"], item["item_id"], item["app"], item["generation"]) for item in preview["separation_subjects"]]
        self.assertEqual([("delivery", "F-001", "backend", 1)], subjects)
        self.assertEqual(set(), self.errors())

    def test_the_last_app_completes_the_pass(self) -> None:
        self.apply("qa-pass", [{"path": FEATURE, "content": self.clean_backend()}])
        page = self.qa_table([*self.active_rows("qa"), app_row("worker")])
        page = self.release_table([*self.active_rows("release"), release_row("worker")], page)
        self.apply("qa-pass", [{"path": FEATURE, "content": self.with_status("ready-for-release", "release", page)}])
        self.assertEqual(("ready-for-release", "release"), self.status())
        self.assertEqual(set(), self.errors())

    def test_both_apps_pass_in_one_run(self) -> None:
        self.apply("qa-pass", [{"path": FEATURE, "content": self.pass_both()}])
        self.assertEqual(("ready-for-release", "release"), self.status())

    def test_coverage_gaps_are_refused_with_their_codes(self) -> None:
        release = [release_row("backend")]
        cases = {
            "criterion_not_covered": self.qa_table([integration_row()]),
            "integration_not_covered": self.qa_table([app_row("backend")]),
            "qa_result_failed": self.qa_table([app_row("backend", result="fail"), integration_row()]),
        }
        for code, page in cases.items():
            with self.subTest(code=code):
                content = self.with_status("in-qa", "qa", self.release_table(release, page))
                self.assertEqual(code, self.refused("qa-pass", [{"path": FEATURE, "content": content}]).code)

    def test_a_pass_names_the_apps_it_passes(self) -> None:
        page = self.with_status("in-qa", "qa", self.qa_table([app_row("backend"), integration_row()]))
        self.assertEqual("qa_pass_apps_required", self.refused("qa-pass", [{"path": FEATURE, "content": page}]).code)

    def test_the_release_row_carries_the_artifact_and_the_next_attempt(self) -> None:
        base = self.qa_table([app_row("backend"), integration_row()])
        wrong_version = self.with_status("in-qa", "qa", self.release_table([release_row("backend", artifact="build:backend#9")], base))
        self.assertEqual("qa_artifact_mismatch", self.refused("qa-pass", [{"path": FEATURE, "content": wrong_version}]).code)
        wrong_attempt = self.with_status("in-qa", "qa", self.release_table([release_row("backend", attempt=2)], base))
        self.assertEqual("release_attempt_mismatch", self.refused("qa-pass", [{"path": FEATURE, "content": wrong_attempt}]).code)

    def test_an_app_that_has_passed_is_not_passed_again(self) -> None:
        self.apply("qa-pass", [{"path": FEATURE, "content": self.clean_backend()}])
        again = self.release_table([release_row("backend", 2)], self.with_status("in-qa", "qa"))
        error = self.refused("qa-pass", [{"path": FEATURE, "content": again}])
        self.assertIn(error.code, {"app_stage_mismatch", "release_row_invalid"})

    def test_an_open_bug_of_the_app_blocks_the_pass(self) -> None:
        self.apply("qa-verify", [{"path": FEATURE, "content": self.qa_table([app_row("worker")])}, {"path": BUG, "content": bug_page("BUG-001", apps=["worker"])}])
        rows = [*self.active_rows("qa"), app_row("backend"), integration_row()]
        both = self.with_status("ready-for-release", "release", self.release_table([release_row("backend"), release_row("worker")], self.qa_table(rows)))
        error = self.refused("qa-pass", [{"path": FEATURE, "content": both}])
        self.assertEqual(("open_bug_blocks_qa", "worker"), (error.code, error.details["app"]))
        # The bug lists worker only, so backend passes.
        only_backend = self.with_status("in-qa", "qa", self.release_table([release_row("backend")], self.qa_table(rows)))
        self.apply("qa-pass", [{"path": FEATURE, "content": only_backend}])

    def test_a_bug_created_in_the_same_proposal_counts(self) -> None:
        changes = [{"path": FEATURE, "content": self.pass_both()}, {"path": BUG, "content": bug_page("BUG-001", apps=["worker"])}]
        self.assertEqual("open_bug_blocks_qa", self.refused("qa-pass", changes).code)

    def test_a_deferred_bug_does_not_block(self) -> None:
        self.put(BUG, bug_page("BUG-001", blocking=False, apps=["worker"], extra={"deferred-reason": "A workaround exists."}))
        self.apply("qa-pass", [{"path": FEATURE, "content": self.pass_both()}])

    def test_a_bug_verified_on_another_artifact_is_refused(self) -> None:
        verified = bug_page(
            "BUG-001",
            status="verified",
            apps=["worker"],
            fix=table(FIX_HEADER, [fix_row("worker", "build:worker#2")]),
            verification=table(VERIFICATION_HEADER, [verification_row("worker", "build:worker#2")]),
        )
        self.put(BUG, verified)
        self.assertEqual("bug_verified_on_other_artifact", self.refused("qa-pass", [{"path": FEATURE, "content": self.pass_both()}]).code)
        on_current = bug_page(
            "BUG-001",
            status="verified",
            apps=["worker"],
            fix=table(FIX_HEADER, [fix_row("worker", "build:worker#1")]),
            verification=table(VERIFICATION_HEADER, [verification_row("worker", "build:worker#1")]),
        )
        self.put(BUG, on_current)
        self.apply("qa-pass", [{"path": FEATURE, "content": self.pass_both()}])

    def test_with_separation_the_producer_of_the_delivery_cannot_pass_the_app(self) -> None:
        self.set_policy(True)
        preview = self.ready("qa-pass", [{"path": FEATURE, "content": self.pass_both()}])
        self.assertIn("separation-pending", [item["code"] for item in preview["warnings"]])
        # `owner` approved both dev-done operations, so it is excluded; Quinn is not.
        with self.assertRaises(BoardError) as caught:
            approve(self.service, self.owner, preview, "operation-1")
        self.assertEqual(("separation_required", 403), (caught.exception.code, caught.exception.status))
        self.assertEqual("applied", approve(self.service, self.quinn, preview, "operation-2")["state"])

    def test_a_missing_journal_entry_cannot_be_verified(self) -> None:
        self.set_policy(True)
        with self.service.store.transaction() as db:
            db.execute("DELETE FROM provenance")
        preview = self.ready("qa-pass", [{"path": FEATURE, "content": self.pass_both()}])
        with self.assertRaises(BoardError) as caught:
            approve(self.service, self.quinn, preview, "operation-1")
        self.assertEqual(("separation_unverifiable", 409), (caught.exception.code, caught.exception.status))

    def test_an_open_question_of_the_developer_blocks_the_pass_and_a_qa_question_is_resolved_with_it(self) -> None:
        questions = (
            "| # | Question | Owner | Status |\n|---|----------|-------|--------|\n"
            "| 1 | Which details should the summary emphasize? | po | resolved: The key points. |\n"
            "| 2 | Which browsers does QA cover? | qa | open |\n"
            "| 3 | Which database does the worker use? | dev | open |"
        )
        self.put(FEATURE, self.with_section("Open questions", questions))
        answered = questions.replace("| qa | open |", "| qa | resolved: Chrome and Firefox. |")
        page = self.with_section("Open questions", answered, self.pass_both())
        preview = self.propose("qa-pass", [{"path": FEATURE, "content": page}])
        self.assertEqual("blocked", preview["classification"])
        self.assertIn("open-questions", [item["code"] for item in preview["blockers"]])
        # A QA action does not answer the developer's question; dev-clarify does, and then the pass goes through.
        self.assertEqual("question_owner_mismatch", self.refused("qa-pass", [{"path": FEATURE, "content": self.with_section("Open questions", answered.replace("| dev | open |", "| dev | resolved: PostgreSQL. |"), self.pass_both())}]).code)
        clarified = questions.replace("| dev | open |", "| dev | resolved: PostgreSQL. |")
        self.put(FEATURE, self.with_section("Open questions", clarified))
        self.apply("qa-pass", [{"path": FEATURE, "content": self.with_section("Open questions", clarified.replace("| qa | open |", "| qa | resolved: Chrome and Firefox. |"), self.pass_both())}])

    def test_the_qa_revalidation_domain_of_a_passed_app_is_cleared(self) -> None:
        domains = {"backend": ["qa"], "worker": ["qa", "release"]}
        self.put(FEATURE, self.frontmatter_with(self.read(FEATURE), **{"app-revalidation": domains}))
        untouched = self.frontmatter_with(self.pass_both(), **{"app-revalidation": domains})
        self.assertEqual("revalidation_scope", self.refused("qa-pass", [{"path": FEATURE, "content": untouched}]).code)
        cleared = self.frontmatter_with(self.pass_both(), **{"app-revalidation": {"worker": ["release"]}})
        self.apply("qa-pass", [{"path": FEATURE, "content": cleared}])
        self.assertEqual({"worker": ["release"]}, self.feature()[0]["app-revalidation"])

    def test_pending_implementation_revalidation_blocks_the_pass(self) -> None:
        pending = {"app-revalidation": {"worker": ["implementation"]}}
        self.put(FEATURE, self.frontmatter_with(self.read(FEATURE), **pending))
        preview = self.propose("qa-pass", [{"path": FEATURE, "content": self.frontmatter_with(self.pass_both(), **pending)}])
        self.assertEqual("blocked", preview["classification"])
        self.assertIn("app-revalidation-gate", [item["code"] for item in preview["blockers"]])

    def test_a_bug_created_between_preview_and_apply_makes_the_pass_stale(self) -> None:
        preview = self.ready("qa-pass", [{"path": FEATURE, "content": self.pass_both()}])
        self.put(f"{BUGS}/BUG-002-late-defect.md", bug_page("BUG-002", apps=["worker"], title="Late defect"))
        with self.assertRaises(BoardError) as caught:
            approve(self.service, self.quinn, preview, "operation-1")
        self.assertIn(caught.exception.code, {"stale_preview", "stale_approval_review"})


if __name__ == "__main__":
    unittest.main()
