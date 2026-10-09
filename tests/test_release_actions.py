"""`release-done` through the board service: the release of a feature, its record and its gates (CONTRACTS F18, F19; cases 10.2 and 10.3)."""

from __future__ import annotations

import unittest
from datetime import date, timedelta

from tests.release_support import (
    BUGS,
    FEATURE,
    SETTINGS,
    TARGETS,
    ReleaseTests,
    bug_page,
    delivery,
    pending_row,
    record_page,
    record_path,
    release_row,
)


class ReleaseDoneTests(ReleaseTests):
    def test_a_clean_release_settles_both_apps_in_one_approval(self) -> None:
        preview = self.release()
        self.assertEqual("release-done", preview["action"])
        self.assertEqual(("released", "none"), self.status())
        self.assertEqual(["REL-001.md"], self.records())
        self.assertEqual(set(), self.errors())
        self.assertEqual({"released"}, {row.outcome for row in self.evidence().release})
        self.assertIn("backend: released", self.read("knowledge/wiki/status-board.md"))
        self.assertIn("REL-001", self.read("knowledge/wiki/log.md"))
        self.assertIn("releases/REL-001.md", self.read("knowledge/wiki/index.md"))

    def test_the_approval_needs_the_release_role(self) -> None:
        preview = self.ready("release-done", self.release_changes())
        self.assertEqual({"all_of": ["release"], "any_of": []}, preview["approval"]["required_roles"])
        error = self.refused("release-done", self.release_changes(), approver=self.quinn)
        self.assertIn(error.status, {403, 404, 409})
        self.assertEqual([], self.records())
        self.assertEqual(("ready-for-release", "release"), self.status())

    def test_the_service_stamps_the_operation_that_wrote_the_record(self) -> None:
        self.release()
        frontmatter, _body = self.record(1)
        self.assertNotEqual("pending", frontmatter["operation"])
        operations = {row[0] for row in self.service.store.connection.execute("SELECT operation_id FROM operations WHERE state = 'applied'").fetchall()}
        self.assertIn(frontmatter["operation"], operations)
        self.assertEqual("released", frontmatter["outcome"])
        self.assertEqual(date.today().isoformat(), str(frontmatter["date"]))

    def test_a_partial_release_leaves_the_failed_app_ready_and_a_retry_settles_it(self) -> None:
        feature = self.released_page([release_row("backend", 1), release_row("worker", 1, outcome="failed")], status="ready-for-release", owner="release")
        record = record_page(1, [delivery("F-001", "backend"), delivery("F-001", "worker", outcome="failed", evidence="deployment: https://ci.example/deploy/aborted-1")])
        self.settle(feature, record)
        self.assertEqual(("ready-for-release", "release"), self.status())
        self.assertEqual("partial", self.record(1)[0]["outcome"])
        self.assertEqual({"backend": "released", "worker": "failed"}, {row.app: row.outcome for row in self.evidence().release})
        self.assertEqual(set(), self.errors())
        # The retry is the second attempt of the worker; the backend keeps its released row.
        retried = self.released_page([release_row("backend", 1), release_row("worker", 2, attempt=2)])
        second = record_page(2, [delivery("F-001", "worker", attempt=2)], retry_of="REL-001")
        self.settle(retried, second, number=2)
        self.assertEqual(("released", "none"), self.status())
        self.assertEqual(["REL-001.md", "REL-002.md"], self.records())
        self.assertEqual(set(), self.errors())

    def test_every_attempt_is_one_more_than_the_records_that_delivered_it(self) -> None:
        feature, record = self.one_app("backend", attempt=2)
        self.assertEqual(("release_attempt_mismatch", 409), self.refuse(feature, record))
        failed = self.released_page([release_row("backend", 1, outcome="failed"), pending_row("worker")], status="ready-for-release", owner="release")
        failed_record = record_page(1, [delivery("F-001", "backend", outcome="failed", evidence="deployment: https://ci.example/deploy/aborted-2")])
        self.settle(failed, failed_record)
        again = self.released_page([release_row("backend", 2, attempt=1), pending_row("worker")], status="ready-for-release", owner="release")
        self.assertEqual(("release_attempt_mismatch", 409), self.refuse(again, record_page(2, [delivery("F-001", "backend", attempt=1)], retry_of="REL-001"), number=2))

    def test_the_retry_of_a_record_names_a_record_with_a_failed_delivery(self) -> None:
        feature, record = self.one_app("backend")
        self.settle(feature, record)
        both = self.released_page([release_row("backend", 1), release_row("worker", 2, attempt=2)])
        retry = record_page(2, [delivery("F-001", "worker", attempt=2)], retry_of="REL-001")
        self.assertEqual(("release_record_invalid", 409), self.refuse(both, retry, number=2))

    # -- the target ------------------------------------------------------------------------------------------------------

    def test_the_target_comes_from_the_current_settings_and_stays_on_the_released_row(self) -> None:
        self.put(SETTINGS, TARGETS.replace("backend: {kind: deployment, target: production", "backend: {kind: deployment, target: eu-production"))
        self.assertEqual(("release_target_mismatch", 409), self.refuse(*self.all_released()))
        feature = self.released_page([release_row("backend", 1, target="eu-production"), release_row("worker", 1)])
        record = record_page(1, [delivery("F-001", "backend", target="eu-production"), delivery("F-001", "worker")])
        self.settle(feature, record)
        # A later change of the target affects only future releases: the released rows keep theirs, and lint stays clean.
        self.put(SETTINGS, TARGETS.replace("target: production", "target: us-production"))
        self.assertEqual({"backend": "eu-production", "worker": "production"}, {row.app: row.target for row in self.evidence().release})
        self.assertEqual(set(), self.errors())

    def test_an_app_without_a_delivery_target_cannot_be_released(self) -> None:
        self.put(SETTINGS, "---\nwiki-stale-after-days: 365\ndelivery-targets:\n  backend: {kind: deployment, target: production}\n---\n")
        self.assertEqual(("delivery_target_missing", 409), self.refuse(*self.all_released()))
        self.settle(*self.one_app("backend"))
        self.assertEqual(("ready-for-release", "release"), self.status())

    def test_a_staging_row_is_informational_and_names_a_declared_environment(self) -> None:
        staging = "| backend | staging | `build:backend#1` | — | released | — | checked |"
        feature = self.released_page([staging, release_row("backend", 1), release_row("worker", 1)])
        record = record_page(1, [delivery("F-001", "backend"), delivery("F-001", "worker")])
        self.settle(feature, record)
        self.assertEqual(("released", "none"), self.status())
        self.assertEqual(set(), self.errors())

    def test_a_staging_row_with_an_undeclared_environment_is_refused(self) -> None:
        staging = "| backend | canary | `build:backend#1` | — | released | — | checked |"
        feature = self.released_page([staging, release_row("backend", 1), release_row("worker", 1)])
        record = record_page(1, [delivery("F-001", "backend"), delivery("F-001", "worker")])
        self.assertEqual(("environment_unknown", 409), self.refuse(feature, record))

    def test_the_version_is_the_artifact_qa_verified(self) -> None:
        feature = self.released_page([release_row("backend", 1, version="build:backend#9"), release_row("worker", 1)])
        record = record_page(1, [delivery("F-001", "backend", version="build:backend#9"), delivery("F-001", "worker")])
        self.assertEqual(("release_version_not_verified", 409), self.refuse(feature, record))

    # -- the record ------------------------------------------------------------------------------------------------------

    def test_a_release_without_a_record_or_with_two_is_refused(self) -> None:
        feature, record = self.all_released()
        self.assertEqual(("release_record_required", 409), self.refusal([{"path": FEATURE, "content": feature}]))
        extra = record_page(2, [delivery("F-001", "backend"), delivery("F-001", "worker")])
        self.assertEqual(
            ("release_record_required", 409),
            self.refusal([{"path": FEATURE, "content": feature}, {"path": record_path(1), "content": record}, {"path": record_path(2), "content": extra}]),
        )

    def test_a_record_takes_the_number_after_the_highest_on_disk(self) -> None:
        feature, record = self.all_released(number=2)
        self.assertEqual(("release_sequence_invalid", 409), self.refuse(feature, record, number=2))
        self.put(record_path(4), record_page(4, [delivery("F-002", "backend")], features=["F-002"]))
        feature, record = self.all_released(number=4)
        self.assertEqual(("release_id_taken", 409), self.refuse(feature, record, number=4))
        feature, record = self.all_released(number=5)
        self.settle(feature, record, number=5)
        self.assertIn("REL-005.md", self.records())

    def test_a_record_that_exists_is_never_rewritten(self) -> None:
        self.release()
        feature, record = self.all_released()
        self.assertEqual(("release_id_taken", 409), self.refuse(feature, record.replace("is delivered to production", "was delivered")))

    def test_the_record_date_is_the_preview_day_and_the_operation_is_the_placeholder(self) -> None:
        feature, _record = self.all_released()
        rows = [delivery("F-001", "backend"), delivery("F-001", "worker")]
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        self.assertEqual(("record_date_invalid", 409), self.refuse(feature, record_page(1, rows, day=yesterday)))
        self.assertEqual(("record_date_invalid", 409), self.refuse(feature, record_page(1, rows, day="someday")))
        self.assertEqual(("release_record_invalid", 409), self.refuse(feature, record_page(1, rows, operation="op-123")))

    def test_the_record_must_follow_the_form_of_a_record(self) -> None:
        feature, _record = self.all_released()
        good = record_page(1, [delivery("F-001", "backend"), delivery("F-001", "worker")])
        cases = {
            "no summary": good.replace("F-001 is delivered to production.", ""),
            "missing section": good.replace("## Rollback\nNone.\n\n", ""),
            "unknown field": good.replace("bugs: []", "bugs: []\nowner: me"),
            "wrong features": good.replace("features: [F-001]", "features: [F-002]"),
            "wrong outcome": good.replace("outcome: released", "outcome: failed"),
            "both retry-of and rollback-of": good.replace("bugs: []", "bugs: []\nretry-of: REL-001\nrollback-of: REL-001"),
        }
        for name, page in cases.items():
            with self.subTest(case=name):
                self.assertEqual(("release_record_invalid", 409), self.refuse(feature, page))

    def test_the_record_rows_must_equal_the_rows_of_the_pages(self) -> None:
        feature, _record = self.all_released()
        self.assertEqual(("release_record_mismatch", 409), self.refuse(feature, record_page(1, [delivery("F-001", "backend")])))
        extra = record_page(1, [delivery("F-001", "backend"), delivery("F-001", "worker"), delivery("F-001", "backend", target="staging")])
        code, status = self.refuse(feature, extra)
        self.assertEqual(409, status)
        self.assertIn(code, {"release_record_mismatch", "release_artifact_conflict", "release_record_invalid"})
        wrong_basis = record_page(1, [delivery("F-001", "backend", basis="attested"), delivery("F-001", "worker")])
        self.assertEqual(("release_record_mismatch", 409), self.refuse(feature, wrong_basis))

    def test_a_row_names_the_record_of_the_proposal(self) -> None:
        feature = self.released_page([release_row("backend", 7), release_row("worker", 7)])
        record = record_page(1, [delivery("F-001", "backend"), delivery("F-001", "worker")])
        self.assertEqual(("release_row_invalid", 409), self.refuse(feature, record))

    def test_the_evidence_of_a_delivery_is_substantive(self) -> None:
        feature, _record = self.all_released()
        for evidence in ("done", "https://ci.example/deploy/1", "deployment: "):
            with self.subTest(evidence=evidence):
                record = record_page(1, [delivery("F-001", "backend", evidence=evidence), delivery("F-001", "worker")])
                code, status = self.refuse(feature, record)
                self.assertEqual(409, status)
                self.assertNotEqual("", code)

    def test_a_release_names_the_apps_it_settles(self) -> None:
        unchanged = self.released_page([pending_row("backend"), pending_row("worker")], status="ready-for-release", owner="release")
        self.assertEqual(("release_apps_required", 409), self.refuse(unchanged, record_page(1, [delivery("F-001", "backend")])))

    # -- the gates -------------------------------------------------------------------------------------------------------

    def test_the_status_follows_the_minimum_of_the_app_stages(self) -> None:
        feature, record = self.one_app("backend")
        wrong = self.with_status("released", "none", feature)
        self.assertEqual(("app_stage_mismatch", 409), self.refuse(wrong, record))

    def test_an_open_blocking_bug_blocks_the_release_of_its_app(self) -> None:
        self.put(f"{BUGS}/BUG-001-open.md", bug_page("BUG-001", status="open", apps=["backend"]))
        self.assertEqual(("open_bug_blocks_release", 409), self.refuse(*self.all_released()))
        self.settle(*self.one_app("worker"))
        self.assertEqual(("ready-for-release", "release"), self.status())

    def test_pending_release_revalidation_of_the_other_app_stays_after_a_partial_release(self) -> None:
        self.put(FEATURE, self.frontmatter_with(self.read(FEATURE), **{"app-revalidation": {"backend": ["release"], "worker": ["release"]}}))
        feature, record = self.one_app("backend")
        self.settle(self.frontmatter_with(feature, **{"app-revalidation": {"worker": ["release"]}}), record)
        self.assertEqual(("ready-for-release", "release"), self.status())

    def test_a_release_clears_only_the_release_domain_it_settles(self) -> None:
        self.put(FEATURE, self.frontmatter_with(self.read(FEATURE), **{"app-revalidation": {"backend": ["release"], "worker": ["release"]}}))
        feature, record = self.all_released()
        untouched = self.frontmatter_with(feature, **{"app-revalidation": {"backend": ["release"], "worker": ["release"]}})
        self.assertEqual(("revalidation_scope", 409), self.refuse(untouched, record))
        self.settle(self.frontmatter_with(feature, **{"app-revalidation": {}}), record)
        self.assertEqual(("released", "none"), self.status())

    def test_blocking_revalidation_of_an_app_blocks_its_release(self) -> None:
        self.put(FEATURE, self.frontmatter_with(self.read(FEATURE), **{"app-revalidation": {"backend": ["qa"]}}))
        feature, record = self.all_released()
        self.assertEqual(("revalidation_required", 409), self.refuse(self.frontmatter_with(feature, **{"app-revalidation": {}}), record))

    def test_qa_evidence_that_went_stale_blocks_the_release(self) -> None:
        # The criterion changed after QA verified it: the QA row cites a revision that is no longer current.
        edited = self.read(FEATURE).replace("A reviewer can record the outcome of a backend review.", "A reviewer can record the outcome of a backend review quickly.")
        self.put(FEATURE, edited)
        feature, record = self.all_released()
        feature = feature.replace("A reviewer can record the outcome of a backend review.", "A reviewer can record the outcome of a backend review quickly.")
        self.assertEqual(("qa_evidence_stale", 409), self.refuse(feature, record))

    def test_release_resolves_the_questions_it_owns(self) -> None:
        old = "| 1 | Which details should the summary emphasize? | po | resolved: The key points. |"
        asked = self.read(FEATURE).replace(old, old + "\n| 2 | Which window do we deploy in? | release | open |")
        self.put(FEATURE, asked)
        released = [release_row("backend", 1), release_row("worker", 1)]
        record = record_page(1, [delivery("F-001", "backend"), delivery("F-001", "worker")])
        answered = asked.replace("| 2 | Which window do we deploy in? | release | open |", "| 2 | Which window do we deploy in? | release | resolved: Tuesday evening. |")
        self.settle(self.released_page(released, content=answered), record)
        self.assertEqual(("released", "none"), self.status())


if __name__ == "__main__":
    unittest.main()
