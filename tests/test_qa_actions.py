"""QA verification, QA pass, QA fail and the routes back from QA through the board service (CONTRACTS F12 to F17)."""

from __future__ import annotations

import unittest

from prism_cli.board_service import BoardError
from prism_cli.wiki_lint import lint_wiki
from tests.qa_support import (
    AC1,
    AC2,
    AC3,
    BOTH,
    BUGS,
    FEATURE,
    SETTINGS,
    QaBoard,
    app_row,
    bug_page,
    integration_row,
    qa_row,
    release_row,
)


class QaVerifyTests(QaBoard):
    def errors(self) -> set[str]:
        return {item.code for item in lint_wiki(self.root).diagnostics if item.severity == "error"}

    def test_the_first_result_of_an_app_opens_its_stage(self) -> None:
        page = self.qa_table([app_row("backend")])
        preview = self.apply("qa-verify", [{"path": FEATURE, "content": page}])
        self.assertEqual("qa-verify", preview["action"])
        self.assertEqual({"all_of": ["qa"], "any_of": []}, preview["approval"]["required_roles"])
        # worker is still ready-for-qa, so the feature stays there; the board row shows backend in-qa.
        self.assertEqual(("ready-for-qa", "qa"), self.status())
        self.assertIn("backend: in-qa; worker: ready-for-qa", self.read("knowledge/wiki/status-board.md"))
        self.assertEqual(set(), self.errors())

    def test_the_feature_follows_the_minimum_once_every_app_has_a_row(self) -> None:
        self.apply("qa-verify", [{"path": FEATURE, "content": self.qa_table([app_row("backend")])}])
        page = self.qa_table([*self.active_rows("qa"), app_row("worker")])
        self.apply("qa-verify", [{"path": FEATURE, "content": self.with_status("in-qa", "qa", page)}])
        self.assertEqual(("in-qa", "qa"), self.status())
        # The status that is not the minimum is refused.
        wrong = self.refused("qa-verify", [{"path": FEATURE, "content": self.qa_table([*self.active_rows("qa"), integration_row()], self.with_status("ready-for-qa", "qa"))}])
        self.assertEqual("app_stage_mismatch", wrong.code)

    def test_an_integration_row_is_verified_by_both_participants(self) -> None:
        self.apply("qa-verify", [{"path": FEATURE, "content": self.with_status("in-qa", "qa", self.qa_table([integration_row()]))}])
        self.assertIn("backend: in-qa; worker: in-qa", self.read("knowledge/wiki/status-board.md"))
        self.assertEqual(("in-qa", "qa"), self.status())

    def test_no_row_is_refused(self) -> None:
        error = self.refused("qa-verify", [{"path": FEATURE, "content": self.read(FEATURE)}])
        self.assertIn(error.code, {"qa_evidence_required", "lifecycle_action_required"})

    def test_the_row_is_checked_against_the_delivered_artifact_the_criterion_and_the_attempt(self) -> None:
        cases = {
            "qa_artifact_mismatch": qa_row("backend", [AC1], "`build:backend#9`"),
            "qa_attempt_mismatch": app_row("backend", attempt=2),
            "criterion_revision_stale": qa_row("backend", ["AC-1@v1:" + "0" * 64], "`build:backend#1`"),
            "criterion_not_applicable": app_row("backend", [AC2]),
            "environment_unknown": app_row("backend", environment="staging"),
        }
        for code in ("qa_artifact_mismatch", "qa_attempt_mismatch", "criterion_revision_stale", "criterion_not_applicable", "environment_unknown"):
            with self.subTest(code=code):
                error = self.refused("qa-verify", [{"path": FEATURE, "content": self.qa_table([cases[code]])}])
                self.assertEqual((code, 409), (error.code, error.status), error.message)

    def test_an_integration_criterion_needs_an_integration_row_and_a_per_app_criterion_an_app_row(self) -> None:
        error = self.refused("qa-verify", [{"path": FEATURE, "content": self.qa_table([app_row("backend", [AC3])])}])
        self.assertEqual("criterion_not_applicable", error.code)
        error = self.refused("qa-verify", [{"path": FEATURE, "content": self.qa_table([qa_row("integration:backend+worker", [AC1], "backend=`build:backend#1`; worker=`build:worker#1`")])}])
        self.assertEqual("criterion_not_applicable", error.code)

    def test_an_environment_the_delivery_target_declares_is_accepted(self) -> None:
        self.put(SETTINGS, "---\nwiki-stale-after-days: 365\ndelivery-targets:\n  backend: { kind: deployment, target: production, environments: [staging] }\n---\n")
        self.apply("qa-verify", [{"path": FEATURE, "content": self.qa_table([app_row("backend", environment="staging")])}])
        self.assertIn("staging", self.read(FEATURE))

    def test_a_row_is_replaced_by_the_same_key_and_criterion_in_the_attempt(self) -> None:
        self.apply("qa-verify", [{"path": FEATURE, "content": self.qa_table([app_row("backend", result="fail")])}])
        replaced = self.qa_table([app_row("backend", result="pass")])
        self.apply("qa-verify", [{"path": FEATURE, "content": replaced}])
        self.assertEqual(["pass"], [row.result for row in self.evidence().qa])

    def test_a_row_that_leaves_the_table_without_a_replacement_is_not_archived(self) -> None:
        self.apply("qa-verify", [{"path": FEATURE, "content": self.qa_table([app_row("backend")])}])
        error = self.refused("qa-verify", [{"path": FEATURE, "content": self.qa_table([app_row("worker")])}])
        self.assertEqual("evidence_not_archived", error.code)

    def test_a_qa_question_is_resolved_in_the_same_proposal(self) -> None:
        questions = (
            "| # | Question | Owner | Status |\n|---|----------|-------|--------|\n"
            "| 1 | Which details should the summary emphasize? | po | resolved: The key points. |\n"
            "| 2 | Which browsers does QA cover? | qa | open |"
        )
        self.put(FEATURE, self.with_section("Open questions", questions))
        answered = questions.replace("| qa | open |", "| qa | resolved: Chrome and Firefox. |")
        page = self.with_section("Open questions", answered, self.qa_table([app_row("backend")]))
        self.apply("qa-verify", [{"path": FEATURE, "content": page}])
        # A question of another owner is not QA's to resolve.
        po_open = questions.replace("resolved: The key points.", "open")
        self.put(FEATURE, self.with_section("Open questions", po_open))
        bad = self.with_section("Open questions", po_open.replace("| po | open |", "| po | resolved: Done. |"), self.qa_table([*self.active_rows("qa"), app_row("worker")]))
        self.assertEqual("question_owner_mismatch", self.refused("qa-verify", [{"path": FEATURE, "content": bad}]).code)

    def test_a_defect_found_while_testing_is_created_in_the_same_proposal(self) -> None:
        bug = bug_page("BUG-001", apps=["worker"])
        page = self.qa_table([app_row("worker", result="fail")])
        changes = [{"path": FEATURE, "content": page}, {"path": f"{BUGS}/BUG-001-summary-export-drops-comments.md", "content": bug}]
        preview = self.apply("qa-verify", changes)
        self.assertIn("knowledge/wiki/bugs/BUG-001-summary-export-drops-comments.md", [write["path"] for write in preview["writes"]])
        self.assertIn("(bugs/BUG-001-summary-export-drops-comments.md)", self.read("knowledge/wiki/index.md"))
        self.assertEqual(set(), self.errors())

    def test_a_new_bug_meets_the_creation_invariants(self) -> None:
        path = f"{BUGS}/BUG-001-summary-export-drops-comments.md"
        page = self.qa_table([app_row("worker", result="fail")])
        deferred = bug_page("BUG-001", blocking=False, extra={"deferred-reason": "later"})
        fixed = bug_page("BUG-001", fix="| App | Artifact | Implementation | Tests | Basis |\n|---|---|---|---|---|\n| worker | `build:worker#2` | [PR](https://x.example/1) | tests | checked |")
        started = bug_page("BUG-001", status="in-fix")
        for name, content in {"deferred": deferred, "a Fix row": fixed, "in-fix": started}.items():
            with self.subTest(name=name):
                error = self.refused("qa-verify", [{"path": FEATURE, "content": page}, {"path": path, "content": content}])
                self.assertEqual("bug_creation_invalid", error.code, error.message)
        elsewhere = bug_page("BUG-001", feature="none", apps=["worker"])
        self.apply("qa-verify", [{"path": FEATURE, "content": page}, {"path": path, "content": elsewhere}])

    def test_a_bug_id_that_exists_is_taken(self) -> None:
        path = f"{BUGS}/BUG-001-summary-export-drops-comments.md"
        self.apply("qa-verify", [{"path": FEATURE, "content": self.qa_table([app_row("worker", result="fail")])}, {"path": path, "content": bug_page("BUG-001")}])
        again = [
            {"path": FEATURE, "content": self.qa_table([*self.active_rows("qa"), app_row("backend")])},
            {"path": f"{BUGS}/BUG-001-another.md", "content": bug_page("BUG-001", title="Another")},
        ]
        self.assertEqual("bug_id_taken", self.refused("qa-verify", again).code)

    def test_a_bug_of_another_feature_is_refused(self) -> None:
        path = f"{BUGS}/BUG-001-summary-export-drops-comments.md"
        error = self.refused("qa-verify", [{"path": FEATURE, "content": self.qa_table([app_row("worker", result="fail")])}, {"path": path, "content": bug_page("BUG-001", feature="F-009")}])
        self.assertEqual("bug_creation_invalid", error.code)

    def test_the_role_that_approves_is_qa(self) -> None:
        preview = self.ready("qa-verify", [{"path": FEATURE, "content": self.qa_table([app_row("backend")])}])
        with self.assertRaises(BoardError) as caught:
            self.service.apply(self.pat, preview["preview_id"], "operation-1", "not-reviewed", True)
        self.assertEqual("role_required", caught.exception.code)


if __name__ == "__main__":
    unittest.main()
