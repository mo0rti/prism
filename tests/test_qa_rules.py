"""The QA rules on page text: rows, release rows, the bug gate, support for a failure and the archive of a failure."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from prism_cli.qa_rules import (
    bug_gate_problems,
    check_qa_pass_release_rows,
    check_qa_rows,
    coverage_problems,
    every_row,
    merged_app_revalidation,
    qa_fail_archive,
    qa_fail_support,
    qa_row_changes,
    release_attempt_for,
)
from prism_cli.wiki_bugs import BugPage
from prism_cli.wiki_model import app_stages, parse_criteria, parse_evidence_history, parse_markdown_text, read_feature_evidence
from tests.qa_support import bug_page
from tests.test_lifecycle_model import ARTIFACT, TEXT_ONE, TEXT_TWO, body_of, delivery_row, qa_row, ref, release_row

BOTH = ["backend", "worker"]
CRITERIA = [f"AC-1 [backend, worker] {TEXT_ONE}", f"AC-2 [backend] {TEXT_TWO}"]
AC1 = ref(1, BOTH, TEXT_ONE)
AC2 = ref(2, ["backend"], TEXT_TWO)
POLICY = {"delivery_targets": {"backend": {"environments": ["staging"]}}}


def evidence_of(**sections):
    return read_feature_evidence(body_of(CRITERIA, **sections))


def bug(text: str, name: str = "BUG-001-x.md") -> BugPage:
    return BugPage(parse_markdown_text(Path(name), text))


class QaRowTests(unittest.TestCase):
    def check(self, old, new, *, active=BOTH, scope=BOTH, history=()):
        body = body_of(CRITERIA)
        return check_qa_rows(
            old=old,
            new=new,
            criteria=parse_criteria(body, "F-001"),
            history=list(history),
            scope=scope,
            active=active,
            policy=POLICY,
        )

    def delivered(self, apps=BOTH, **extra):
        return evidence_of(delivery=[delivery_row(app) for app in apps], **extra)

    def test_a_row_for_an_app_in_development_is_a_stage_mismatch(self) -> None:
        old = self.delivered(["backend"])
        new = evidence_of(delivery=[delivery_row("backend")], qa=[qa_row("worker", [AC1], f"`{ARTIFACT['worker']}`")])
        self.assertEqual(["app_stage_mismatch"], [item.code for item in self.check(old, new)])

    def test_an_integration_row_needs_every_participant_delivered_and_one_in_qa(self) -> None:
        row = qa_row("integration: backend + worker", [AC1], "backend=`build:backend#1`; worker=`build:worker#1`")
        # AC-1 is a per-app criterion, so this row is also not applicable; the stage comes first.
        old = self.delivered(["backend"])
        new = evidence_of(delivery=[delivery_row("backend")], qa=[row])
        self.assertEqual("app_stage_mismatch", self.check(old, new)[0].code)
        released = self.delivered(release=[release_row("backend", "released"), release_row("worker", "released")])
        self.assertEqual("app_stage_mismatch", self.check(released, evidence_of(delivery=[delivery_row(app) for app in BOTH], qa=[row], release=[release_row("backend", "released"), release_row("worker", "released")]))[0].code)

    def test_a_row_naming_an_app_outside_the_scope_is_undeclared(self) -> None:
        old = self.delivered()
        new = evidence_of(delivery=[delivery_row(app) for app in BOTH], qa=[qa_row("backend", [AC1], "`build:backend#1`")])
        self.assertEqual("undeclared_app_row", self.check(old, new, scope=["worker"], active=["worker"])[0].code)

    def test_a_removed_row_must_be_replaced_for_each_of_its_criteria(self) -> None:
        both = qa_row("backend", [AC1, AC2], "`build:backend#1`")
        old = self.delivered(qa=[both])
        replaced = evidence_of(delivery=[delivery_row(app) for app in BOTH], qa=[qa_row("backend", [AC1, AC2], "`build:backend#1`", result="fail")])
        self.assertEqual([], self.check(old, replaced))
        partial = evidence_of(delivery=[delivery_row(app) for app in BOTH], qa=[qa_row("backend", [AC1], "`build:backend#1`")])
        self.assertEqual(["evidence_not_archived"], [item.code for item in self.check(old, partial)])
        gone = evidence_of(delivery=[delivery_row(app) for app in BOTH])
        self.assertEqual(["evidence_not_archived"], [item.code for item in self.check(old, gone)])

    def test_a_criterion_that_no_longer_exists_does_not_hold_a_row_back(self) -> None:
        stale = qa_row("backend", ["AC-9@v1:" + "a" * 64], "`build:backend#1`")
        old = self.delivered(qa=[stale])
        self.assertEqual([], self.check(old, self.delivered()))

    def test_two_rows_for_one_key_and_criterion_are_refused(self) -> None:
        old = self.delivered()
        twin = [qa_row("backend", [AC2], "`build:backend#1`"), qa_row("backend", [AC2], "`build:backend#1`", result="fail")]
        new = evidence_of(delivery=[delivery_row(app) for app in BOTH], qa=twin)
        self.assertEqual("qa_row_invalid", self.check(old, new)[0].code)

    def test_the_attempt_follows_the_history(self) -> None:
        history = parse_evidence_history(
            "## Evidence history\n### 2026-10-01 - qa-fail\n- Reason: failed once\n- Affected apps: backend\n- Participants: none\n- Affected tracks: none\n"
            "- Archived evidence:\n  | QA verification | backend | " + AC2 + " | automated | `build:backend#1` | ci | qa-1 | fail | [run](https://ci.example/1) | checked |\n"
            "- Reaffirmed evidence: none\n- Requirement/API invalidations: none\n- Linked bugs: none\n"
        )
        old = self.delivered()
        new = evidence_of(delivery=[delivery_row(app) for app in BOTH], qa=[qa_row("backend", [AC2], "`build:backend#1`", attempt=2)])
        self.assertEqual([], self.check(old, new, history=history))
        wrong = evidence_of(delivery=[delivery_row(app) for app in BOTH], qa=[qa_row("backend", [AC2], "`build:backend#1`", attempt=1)])
        self.assertEqual(["qa_attempt_mismatch"], [item.code for item in self.check(old, wrong, history=history)])

    def test_environments_come_from_the_delivery_target(self) -> None:
        old = self.delivered()
        for environment, expected in (("ci", []), ("local", []), ("staging", []), ("prod", ["environment_unknown"])):
            with self.subTest(environment=environment):
                row = qa_row("backend", [AC2], "`build:backend#1`").replace("| ci |", f"| {environment} |")
                new = evidence_of(delivery=[delivery_row(app) for app in BOTH], qa=[row])
                self.assertEqual(expected, [item.code for item in self.check(old, new)])
        # `staging` belongs to backend only.
        worker = qa_row("worker", [AC1], "`build:worker#1`").replace("| ci |", "| staging |")
        self.assertEqual(["environment_unknown"], [item.code for item in self.check(old, evidence_of(delivery=[delivery_row(app) for app in BOTH], qa=[worker]))])

    def test_row_changes_compare_cells(self) -> None:
        a = evidence_of(qa=[qa_row("backend", [AC2], "`build:backend#1`")]).qa
        b = evidence_of(qa=[qa_row("backend", [AC2], "`build:backend#1`", result="fail")]).qa
        self.assertEqual(([], []), qa_row_changes(a, a))
        added, removed = qa_row_changes(a, b)
        self.assertEqual((["fail"], ["pass"]), ([row.result for row in added], [row.result for row in removed]))


class ReleaseRowTests(unittest.TestCase):
    def run_check(self, old, new, *, stages=None, attempt=1):
        active = BOTH
        return check_qa_pass_release_rows(old=old, new=new, stages=stages or app_stages(active, old), active=active, policy=POLICY, attempt_of=lambda app: attempt)

    def test_the_apps_a_pass_names_are_those_that_gain_a_pending_row(self) -> None:
        old = evidence_of(delivery=[delivery_row(app) for app in BOTH])
        new = evidence_of(delivery=[delivery_row(app) for app in BOTH], release=[release_row("backend")])
        self.assertEqual((("backend",), []), (self.run_check(old, new)[0], self.run_check(old, new)[1]))

    def test_an_existing_authoritative_row_is_never_changed(self) -> None:
        old = evidence_of(delivery=[delivery_row(app) for app in BOTH], release=[release_row("backend")])
        new = evidence_of(delivery=[delivery_row(app) for app in BOTH])
        stages = {"backend": "ready-for-release", "worker": "ready-for-qa"}
        self.assertEqual(["release_row_invalid"], [item.code for item in self.run_check(old, new, stages=stages)[1]])

    def test_a_staging_row_names_an_environment_of_the_app(self) -> None:
        old = evidence_of(delivery=[delivery_row(app) for app in BOTH])
        for target, codes in (("staging", []), ("nowhere", ["environment_unknown"])):
            with self.subTest(target=target):
                row = f"| backend | {target} | `build:backend#1` | — | released | — | checked |"
                new = evidence_of(delivery=[delivery_row(app) for app in BOTH], release=[row])
                named, problems = self.run_check(old, new)
                self.assertEqual(((), codes), (named, [item.code for item in problems]))

    def test_the_release_attempt_counts_records_that_delivered_the_item(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            wiki = Path(folder)
            self.assertEqual(1, release_attempt_for(wiki, "F-001", "backend"))
            (wiki / "releases").mkdir()
            record = (
                "---\nid: REL-001\ntitle: First\ndate: 2026-10-08\noperation: op\noutcome: released\nfeatures: [F-001]\nbugs: []\n---\n\n"
                "## Summary\nFirst.\n\n## Delivery\n| Item | App | Target | Version | Attempt | Outcome | Evidence | Basis |\n|---|---|---|---|---|---|---|---|\n"
                "| F-001 | backend | production | `build:backend#1` | release-1 | released | [r](https://x.example) | checked |\n"
            )
            (wiki / "releases" / "REL-001.md").write_text(record, encoding="utf-8")
            (wiki / "releases" / "REL-002.md").write_text(record.replace("id: REL-001", "id: REL-002").replace("operation: op", "operation: op\nrollback-of: REL-001"), encoding="utf-8")
            self.assertEqual(2, release_attempt_for(wiki, "F-001", "backend"))
            self.assertEqual(1, release_attempt_for(wiki, "F-001", "worker"))
            self.assertEqual(1, release_attempt_for(wiki, "F-002", "backend"))


class BugGateTests(unittest.TestCase):
    def gate(self, *texts: str, named=("worker",), evidence=None):
        bugs = [bug(text, f"BUG-00{n}-x.md") for n, text in enumerate(texts, start=1)]
        return bug_gate_problems(bugs, feature_id="F-001", named=list(named), evidence=evidence or evidence_of(delivery=[delivery_row(app) for app in BOTH]))

    def test_an_open_bug_names_itself_in_the_refusal(self) -> None:
        problems = self.gate(bug_page("BUG-001"))
        self.assertEqual(["open_bug_blocks_qa"], [item.code for item in problems])
        self.assertIn("BUG-001", problems[0].message)
        self.assertEqual([], self.gate(bug_page("BUG-001"), named=("backend",)))

    def test_the_release_code_can_be_asked_for(self) -> None:
        bugs = [bug(bug_page("BUG-001"))]
        problems = bug_gate_problems(bugs, feature_id="F-001", named=["worker"], evidence=evidence_of(), code_blocks="open_bug_blocks_release")
        self.assertEqual(["open_bug_blocks_release"], [item.code for item in problems])


class FailureTests(unittest.TestCase):
    def test_the_archive_of_a_failure(self) -> None:
        integration = qa_row("integration: backend + worker", [AC1], "backend=`build:backend#1`; worker=`build:worker#1`")
        evidence = evidence_of(
            delivery=[delivery_row(app) for app in BOTH],
            qa=[qa_row("backend", [AC2], "`build:backend#1`"), qa_row("worker", [AC1], "`build:worker#1`", result="fail"), integration],
            release=[release_row("backend")],
        )
        stages = {"backend": "ready-for-release", "worker": "in-qa"}
        archive, participants = qa_fail_archive(evidence, ["worker"], stages)
        sections = [section for section, _cells in archive]
        self.assertEqual(["Delivery evidence", "QA verification", "QA verification", "Release"], sections)
        self.assertEqual(["backend"], participants)
        # A released participant keeps everything.
        released = evidence_of(
            delivery=[delivery_row(app) for app in BOTH],
            qa=[integration],
            release=[release_row("backend", "released")],
        )
        archive, participants = qa_fail_archive(released, ["worker"], {"backend": "released", "worker": "in-qa"})
        self.assertEqual(([], ["Delivery evidence", "QA verification"]), (participants, [section for section, _cells in archive]))

    def test_support_for_a_failure(self) -> None:
        evidence = evidence_of(delivery=[delivery_row(app) for app in BOTH], qa=[qa_row("worker", [AC1], "`build:worker#1`", result="blocked")])
        self.assertEqual([], qa_fail_support(named=["worker"], evidence=evidence, history=[], bugs=[], linked=[], feature_id="F-001"))
        passing = evidence_of(delivery=[delivery_row(app) for app in BOTH], qa=[qa_row("worker", [AC1], "`build:worker#1`")])
        self.assertEqual(["qa_failure_unsupported"], [item.code for item in qa_fail_support(named=["worker"], evidence=passing, history=[], bugs=[], linked=[], feature_id="F-001")])
        linked = [bug(bug_page("BUG-001", status="fixed"))]
        self.assertEqual([], qa_fail_support(named=["worker"], evidence=passing, history=[], bugs=linked, linked=["BUG-001"], feature_id="F-001"))
        # A bug that is not listed, belongs to another app, is verified or is deferred does not count.
        for text, listed in (
            (bug_page("BUG-001"), []),
            (bug_page("BUG-001", apps=["backend"]), ["BUG-001"]),
            (bug_page("BUG-001", status="verified"), ["BUG-001"]),
            (bug_page("BUG-001", blocking=False, extra={"deferred-reason": "Later."}), ["BUG-001"]),
        ):
            with self.subTest(listed=listed):
                problems = qa_fail_support(named=["worker"], evidence=passing, history=[], bugs=[bug(text)], linked=listed, feature_id="F-001")
                self.assertEqual(["qa_failure_unsupported"], [item.code for item in problems])

    def test_every_row_and_the_merged_domains(self) -> None:
        evidence = evidence_of(delivery=[delivery_row("backend")], qa=[qa_row("backend", [AC2], "`build:backend#1`")], release=[release_row("backend")])
        self.assertEqual(["Delivery evidence", "QA verification", "Release"], [section for section, _cells in every_row(evidence)])
        merged = merged_app_revalidation({"backend": ["qa"], "worker": ["release"]}, {"backend": ["tests", "implementation"], "web": ["qa"]}, drop=["worker"])
        self.assertEqual({"backend": ["implementation", "tests", "qa"], "web": ["qa"]}, merged)

    def test_coverage_problems_lead_with_a_failed_result(self) -> None:
        evidence = evidence_of(delivery=[delivery_row(app) for app in BOTH], qa=[qa_row("backend", [AC2], "`build:backend#1`", result="fail")])
        problems = coverage_problems("backend", parse_criteria(body_of(CRITERIA), "F-001"), evidence, [])
        self.assertEqual("qa_result_failed", problems[0].code)


if __name__ == "__main__":
    unittest.main()
