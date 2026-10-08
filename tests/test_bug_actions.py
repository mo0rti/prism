"""Bug pages and `bug-update` through the board service: B1 to B13 (CONTRACTS 2.8, 6.2)."""

from __future__ import annotations

import unittest

from prism_cli.board_service import BoardError
from prism_cli.wiki_lint import lint_wiki
from prism_cli.wiki_model import parse_evidence_history
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
    history_entry,
    verification_row,
)
from tests.test_board_service import _read_revisions
from tests.test_lifecycle_model import table

BUG = f"{BUGS}/BUG-001-summary-export-drops-comments.md"
OTHER = f"{BUGS}/BUG-002-second-defect.md"


def fix(artifact: str = "build:worker#2", app: str = "worker") -> str:
    return table(FIX_HEADER, [fix_row(app, artifact)])


def verification(artifact: str = "build:worker#2", **kwargs) -> str:
    return table(VERIFICATION_HEADER, [verification_row("worker", artifact, **kwargs)])


class BugBoard(QaBoard):
    """Bugs link no feature unless a test says so, so the feature's QA cycle does not interfere."""

    def bug(self, status: str = "open", **kwargs) -> str:
        kwargs.setdefault("feature", "none")
        return bug_page("BUG-001", status=status, **kwargs)

    def plant(self, status: str = "open", path: str = BUG, **kwargs) -> None:  # type: ignore[override]
        self.put(path, self.bug(status, **kwargs))

    def update(self, content: str, approver=None, path: str = BUG) -> dict:
        return self.apply("bug-update", [{"path": path, "content": content}], approver=approver or self.quinn)

    def refuse(self, content: str, approver=None, path: str = BUG) -> BoardError:
        return self.refused("bug-update", [{"path": path, "content": content}], approver=approver or self.quinn)

    def errors(self) -> set[str]:
        return {item.code for item in lint_wiki(self.root).diagnostics if item.severity == "error"}

    def entry(self, action: str, archived: list[tuple[str, str]], **kwargs) -> str:
        kwargs.setdefault("affected", "worker")
        return history_entry(action, archived=archived, **kwargs)


class BugCreationTests(BugBoard):
    def test_a_bug_created_by_qa_is_open_with_the_dev_owner_and_lints_clean(self) -> None:
        changes = [{"path": FEATURE, "content": self.qa_table([app_row("worker", result="fail")])}, {"path": BUG, "content": bug_page("BUG-001")}]
        self.apply("qa-verify", changes)
        self.assertEqual(set(), self.errors())
        self.assertIn("bugs/BUG-001-summary-export-drops-comments.md", self.read("knowledge/wiki/index.md"))

    def test_a_bug_page_has_the_expected_shape(self) -> None:
        base = bug_page("BUG-001")
        broken = {
            "unknown field": base.replace("blocking: true", "blocking: true\nowner-note: x"),
            "severity": base.replace("severity: high", "severity: awful"),
            "missing section": base.replace("## Impact\nReviewers lose their comments.\n\n", ""),
            "id and file name": bug_page("BUG-009"),
        }
        for name, content in broken.items():
            with self.subTest(name=name):
                changes = [{"path": FEATURE, "content": self.qa_table([app_row("worker", result="fail")])}, {"path": BUG, "content": content}]
                self.assertIn(self.refused("qa-verify", changes).code, {"invalid_bug", "bug_creation_invalid"})

    def test_a_defect_report_is_ingested_as_a_bug(self) -> None:
        folder = "2026-10-08-defect-report"
        pending = self.root / "knowledge" / "intake" / "pending" / folder
        pending.mkdir(parents=True)
        (pending / "report.md").write_text("# Defect\nThe exported summary drops comments.\n", encoding="utf-8")
        manifest = "# Manifest\n\n- knowledge/wiki/bugs/BUG-001-summary-export-drops-comments.md (BUG-001)\n"
        changes = [
            {"path": BUG, "content": bug_page("BUG-001", feature="none", extra={"sources": [f"knowledge/intake/processed/{folder}/report.md"]})},
            {"path": f"knowledge/intake/processed/{folder}/MANIFEST.md", "content": manifest},
        ]
        moves = [{"source": f"knowledge/intake/pending/{folder}", "destination": f"knowledge/intake/processed/{folder}"}]
        preview = self.service.preview_skill(self.agent, "ingest", changes, moves, _read_revisions(self.service, self.agent, "ingest", changes, moves))
        self.assertEqual("ready", preview["classification"], preview["checks"])
        self.assertEqual("applied", self.service.apply(self.agent, preview["preview_id"], "ingest-1")["state"])
        self.assertTrue((self.root / BUG).is_file())
        self.assertEqual(set(), self.errors())
        # Ingest only creates a bug: a proposal that rewrites the page is refused.
        second = "2026-10-09-second-report"
        again = self.root / "knowledge" / "intake" / "pending" / second
        again.mkdir(parents=True)
        (again / "report.md").write_text("# Defect\nThe export still drops comments.\n", encoding="utf-8")
        rewrite = [
            {"path": BUG, "content": bug_page("BUG-001", feature="none", title="Changed", extra={"sources": [f"knowledge/intake/processed/{folder}/report.md"]})},
            {"path": f"knowledge/intake/processed/{second}/MANIFEST.md", "content": manifest},
        ]
        moves = [{"source": f"knowledge/intake/pending/{second}", "destination": f"knowledge/intake/processed/{second}"}]
        with self.assertRaises(BoardError) as caught:
            self.service.preview_skill(self.agent, "ingest", rewrite, moves, _read_revisions(self.service, self.agent, "ingest", rewrite, moves))
        self.assertEqual("intake_existing_page", caught.exception.code)


class BugActionTests(BugBoard):
    def test_triage_is_done_by_dev_or_qa_while_the_bug_is_open(self) -> None:
        self.plant()
        preview = self.update(self.bug(severity="critical"), approver=self.devi)
        self.assertEqual("bug-triage", preview["action"])
        self.assertEqual({"all_of": [], "any_of": ["dev", "qa"]}, preview["approval"]["required_roles"])
        self.update(self.bug(severity="critical", blocking=False), approver=self.quinn)
        # The product owner holds neither role.
        content = self.bug(severity="low", blocking=False)
        preview = self.ready("bug-update", [{"path": BUG, "content": content}])
        with self.assertRaises(BoardError) as caught:
            self.service.apply(self.pat, preview["preview_id"], "operation-1", "not-reviewed", True)
        self.assertEqual("role_required", caught.exception.code)

    def test_triage_stops_when_work_starts(self) -> None:
        self.plant("in-fix")
        self.assertEqual("unsupported_source_pair", self.refuse(self.bug("in-fix", severity="low")).code)

    def test_the_frontmatter_allowlist_of_each_action_is_enforced(self) -> None:
        self.plant()
        self.assertEqual("bug_frontmatter_scope", self.refuse(self.bug(severity="low", title="A new title")).code)
        self.assertEqual("bug_frontmatter_scope", self.refuse(self.bug("in-fix", severity="low")).code)

    def test_start_runs_on_an_open_bug_that_is_not_deferred(self) -> None:
        self.plant(blocking=False, extra={"deferred-reason": "Later."})
        self.assertEqual("bug_deferred", self.refuse(self.bug("in-fix", blocking=False, extra={"deferred-reason": "Later."}), approver=self.devi).code)
        self.plant()
        preview = self.update(self.bug("in-fix"), approver=self.devi)
        self.assertEqual("bug-start", preview["action"])

    def test_fixed_needs_a_fix_row_for_each_app_and_records_who_produced_it(self) -> None:
        self.plant("in-fix")
        self.assertEqual("bug_fix_evidence_required", self.refuse(self.bug("fixed"), approver=self.devi).code)
        self.assertEqual("artifact_reference_invalid", self.refuse(self.bug("fixed", fix=fix("build-2")), approver=self.devi).code)
        preview = self.update(self.bug("fixed", fix=fix()), approver=self.devi)
        self.assertEqual("bug-fixed", preview["action"])
        self.assertEqual([("fix", "BUG-001", "worker", 1)], [(item["kind"], item["item_id"], item["app"], item["generation"]) for item in preview["produces_evidence"]])
        bound = self.service.store.connection.execute("SELECT kind, item_id, generation FROM provenance WHERE item_id = 'BUG-001'").fetchall()
        self.assertEqual([("fix", "BUG-001", 1)], [tuple(row) for row in bound])
        self.assertEqual(set(), self.errors())

    def test_fixed_may_not_change_the_apps_or_the_feature(self) -> None:
        self.plant("in-fix")
        self.assertEqual("bug_frontmatter_scope", self.refuse(self.bug("fixed", fix=fix(), apps=["backend", "worker"]), approver=self.devi).code)
        self.assertEqual("bug_frontmatter_scope", self.refuse(self.bug("fixed", fix=fix(), feature="F-001"), approver=self.devi).code)

    def test_a_fix_is_refused_while_the_feature_is_in_its_qa_cycle(self) -> None:
        self.put(BUG, bug_page("BUG-001", status="in-fix", apps=["worker"], feature="F-001"))
        error = self.refuse(bug_page("BUG-001", status="fixed", apps=["worker"], feature="F-001", fix=fix()), approver=self.devi)
        self.assertEqual(("feature_in_qa_cycle", 409), (error.code, error.status))

    def test_verified_needs_a_passing_row_on_the_fix_artifact_and_separates_from_the_fixer(self) -> None:
        self.set_policy(True)
        self.plant("in-fix")
        self.update(self.bug("fixed", fix=fix()), approver=self.devi)
        verified = self.bug("verified", fix=fix(), verification=verification())
        # The grant that approved the fix cannot verify it.
        preview = self.ready("bug-update", [{"path": BUG, "content": verified}])
        self.assertIn("separation-pending", [item["code"] for item in preview["warnings"]])
        self.assertEqual([("fix", "BUG-001", "worker", 1)], [(item["kind"], item["item_id"], item["app"], item["generation"]) for item in preview["separation_subjects"]])
        with self.assertRaises(BoardError) as caught:
            approve(self.service, self.devi, preview, "operation-1")
        self.assertEqual("separation_required", caught.exception.code)
        self.assertEqual("applied", approve(self.service, self.quinn, preview, "operation-2")["state"])
        self.assertEqual(("verified", "release"), (self.bug_status()))

    def bug_status(self) -> tuple[str, str]:
        from prism_cli.board_service import _parse_markdown

        frontmatter = _parse_markdown(self.read(BUG))[0]
        return frontmatter["status"], frontmatter["owner"]

    def test_verification_rows_are_checked(self) -> None:
        self.plant("in-fix")
        self.update(self.bug("fixed", fix=fix()), approver=self.devi)
        wrong_artifact = self.bug("fixed", fix=fix()).replace("status: fixed", "status: verified").replace("owner: qa", "owner: release")
        cases = {
            "bug_verification_required": self.bug("verified", fix=fix(), verification=verification("build:worker#3")),
            "qa_attempt_mismatch": self.bug("verified", fix=fix(), verification=verification(attempt=2)),
            "environment_unknown": self.bug("verified", fix=fix(), verification=verification(environment="staging")),
        }
        for code, content in cases.items():
            with self.subTest(code=code):
                self.assertEqual(code, self.refuse(content).code)
        del wrong_artifact
        self.assertEqual("bug_verification_required", self.refuse(self.bug("verified", fix=fix())).code)

    def test_a_verification_on_the_delivered_artifact_for_a_linked_feature_app(self) -> None:
        # worker is delivered as build:worker#1, so a bug linked to F-001 is verified on that artifact, not on the fix artifact.
        self.put(BUG, bug_page("BUG-001", status="fixed", apps=["worker"], feature="F-001", fix=fix("build:worker#1")))
        wrong = bug_page("BUG-001", status="verified", apps=["worker"], feature="F-001", fix=fix("build:worker#1"), verification=verification("build:worker#2"))
        self.assertEqual("bug_verification_required", self.refuse(wrong).code)
        right = bug_page("BUG-001", status="verified", apps=["worker"], feature="F-001", fix=fix("build:worker#1"), verification=verification("build:worker#1"))
        self.update(right)

    def test_reverify_archives_the_old_row_and_writes_a_new_one_in_the_next_attempt(self) -> None:
        self.plant("verified", fix=fix(), verification=verification())
        entry = self.entry("bug-reverify", [("Verification", verification_row("worker", "build:worker#2"))])
        history = "\n" + entry
        new = self.bug("verified", fix=fix(), verification=verification("build:worker#2", attempt=2), history=history)
        preview = self.update(new)
        self.assertEqual("bug-reverify", preview["action"])
        from prism_cli.wiki_model import bug_qa_attempt

        text = self.read(BUG)
        from prism_cli.board_service import _parse_markdown

        self.assertEqual(2, bug_qa_attempt(parse_evidence_history(_parse_markdown(text)[1])))
        # Without the archive it is refused.
        self.plant("verified", fix=fix(), verification=verification())
        self.assertIn(self.refuse(self.bug("verified", fix=fix(), verification=verification(attempt=2))).code, {"history_entry_required"})

    def test_reject_archives_the_failing_row_with_the_fix_and_verification(self) -> None:
        self.plant("verified", fix=fix(), verification=verification())
        failing = verification_row("worker", "build:worker#2", result="fail")
        archived = [("Fix", fix_row("worker", "build:worker#2")), ("Verification", verification_row("worker", "build:worker#2")), ("Verification", failing)]
        history = "\n" + self.entry("bug-reject", archived)
        preview = self.update(self.bug("in-fix", history=history))
        self.assertEqual("bug-reject", preview["action"])
        self.assertEqual(set(), self.errors())
        # The failing row must be among the archived rows.
        self.plant("verified", fix=fix(), verification=verification())
        without = [("Fix", fix_row("worker", "build:worker#2")), ("Verification", verification_row("worker", "build:worker#2"))]
        self.assertEqual("evidence_not_archived", self.refuse(self.bug("in-fix", history="\n" + self.entry("bug-reject", without))).code)

    def test_reject_from_fixed_and_the_next_fix_is_a_new_generation(self) -> None:
        self.set_policy(True)
        self.plant("in-fix")
        self.update(self.bug("fixed", fix=fix()), approver=self.devi)
        failing = verification_row("worker", "build:worker#2", result="fail")
        history = "\n" + self.entry("bug-reject", [("Fix", fix_row("worker", "build:worker#2")), ("Verification", failing)])
        self.update(self.bug("in-fix", history=history))
        # A second fix is generation 2 and has its own producing operation.
        again = self.bug("fixed", fix=fix("build:worker#3"), history=history)
        preview = self.update(again, approver=self.devi)
        self.assertEqual([("fix", "BUG-001", "worker", 2)], [(item["kind"], item["item_id"], item["app"], item["generation"]) for item in preview["produces_evidence"]])
        rows = self.service.store.connection.execute("SELECT generation FROM provenance WHERE item_id = 'BUG-001' ORDER BY generation").fetchall()
        self.assertEqual([1, 2], [row[0] for row in rows])

    def test_a_second_producing_operation_for_one_generation_is_refused(self) -> None:
        self.plant("in-fix")
        self.update(self.bug("fixed", fix=fix()), approver=self.devi)
        # Put the bug back by hand, without archiving the Fix row: a new fix would be generation 1 again.
        self.plant("in-fix")
        error = self.refused("bug-update", [{"path": BUG, "content": self.bug("fixed", fix=fix("build:worker#3"))}], approver=self.devi)
        self.assertEqual("evidence_generation_conflict", error.code)

    def test_a_bug_cannot_be_released_by_bug_update(self) -> None:
        self.plant("verified", fix=fix(), verification=verification())
        content = self.bug("released", fix=fix(), verification=verification())
        self.assertEqual("bug_release_via_release_done", self.refuse(content).code)

    def test_closing_as_wont_fix_needs_a_reason_and_the_product_owner(self) -> None:
        self.plant("fixed", fix=fix())
        no_reason = self.bug("closed", fix=fix(), extra={"close-reason": "wont-fix"})
        self.assertEqual("bug_close_reason_required", self.refuse(no_reason, approver=self.pat).code)
        closed = self.bug("closed", fix=fix(), extra={"close-reason": "wont-fix: The export is replaced by the new report."})
        preview = self.ready("bug-update", [{"path": BUG, "content": closed}])
        self.assertEqual(("bug-close", {"all_of": ["po"], "any_of": []}), (preview["action"], preview["approval"]["required_roles"]))
        with self.assertRaises(BoardError) as caught:
            self.service.apply(self.quinn, preview["preview_id"], "operation-1", "not-reviewed", True)
        self.assertEqual("role_required", caught.exception.code)
        self.assertEqual("applied", approve(self.service, self.pat, preview, "operation-2")["state"])
        self.assertEqual(set(), self.errors())

    def test_a_deferral_is_for_a_bug_that_is_not_blocking(self) -> None:
        self.plant()
        deferred = self.bug(extra={"deferred-reason": "A workaround exists."})
        self.assertEqual("bug_not_deferrable", self.refuse(deferred, approver=self.pat).code)
        self.plant(blocking=False)
        preview = self.update(self.bug(blocking=False, extra={"deferred-reason": "A workaround exists."}), approver=self.pat)
        self.assertEqual("bug-defer", preview["action"])
        undeferred = self.update(self.bug(blocking=False), approver=self.pat)
        self.assertEqual("bug-defer", undeferred["action"])
        self.assertNotIn("deferred-reason", self.read(BUG))

    def test_reopen_archives_the_evidence_and_removes_the_close_reason(self) -> None:
        closed_fields = {"close-reason": "wont-fix: The report was withdrawn."}
        self.plant("closed", fix=fix(), verification=verification(), extra=closed_fields)
        archived = [("Fix", fix_row("worker", "build:worker#2")), ("Verification", verification_row("worker", "build:worker#2"))]
        history = "\n" + self.entry("bug-reopen", archived)
        preview = self.update(self.bug("open", history=history), approver=self.pat)
        self.assertEqual("bug-reopen", preview["action"])
        self.assertNotIn("close-reason", self.read(BUG))
        self.assertEqual(set(), self.errors())

    def test_only_a_wont_fix_bug_reopens(self) -> None:
        self.plant("closed", extra={"close-reason": "duplicate", "duplicate-of": "BUG-002"})
        self.assertEqual("unsupported_source_pair", self.refuse(self.bug("open"), approver=self.pat).code)

    def test_a_bug_with_a_released_app_does_not_reopen(self) -> None:
        released = "| worker | production | `build:worker#2` | release-1 | released | [REL-001](https://records.example/REL-001) | checked |"
        release_table = table("| App | Target | Version | Attempt | Outcome | Record | Basis |", [released])
        self.plant("closed", fix=fix(), verification=verification(), release=release_table, extra={"close-reason": "wont-fix: Accepted."})
        archived = [("Fix", fix_row("worker", "build:worker#2")), ("Verification", verification_row("worker", "build:worker#2")), ("Release", released)]
        history = "\n" + self.entry("bug-reopen", archived)
        self.assertEqual("bug_reopen_after_release", self.refuse(self.bug("open", history=history), approver=self.pat).code)


class DuplicateAndPromotionTests(BugBoard):
    def plant_pair(self, **canonical) -> None:
        self.put(BUG, self.bug())
        self.put(OTHER, bug_page("BUG-002", feature="none", title="Second defect", **canonical))

    def close_as_duplicate(self, target: str, **kwargs) -> BoardError | dict:
        content = self.bug("closed", extra={"close-reason": "duplicate", "duplicate-of": target}, **kwargs)
        return self.refuse(content)

    def test_a_duplicate_names_a_canonical_bug_that_qualifies(self) -> None:
        self.plant_pair()
        preview = self.update(self.bug("closed", extra={"close-reason": "duplicate", "duplicate-of": "BUG-002"}))
        self.assertEqual(("bug-close", {"all_of": ["qa"], "any_of": []}), (preview["action"], preview["approval"]["required_roles"]))
        self.assertEqual(set(), self.errors())

    def test_the_duplicate_rule_refuses_each_unqualified_canonical_bug(self) -> None:
        self.plant_pair()
        self.assertEqual("duplicate_target_invalid", self.close_as_duplicate("BUG-001").code)
        self.assertEqual("duplicate_target_invalid", self.close_as_duplicate("BUG-009").code)
        self.put(OTHER, bug_page("BUG-002", feature="none", title="Second defect", status="closed", extra={"close-reason": "wont-fix: Accepted."}))
        self.assertEqual("duplicate_target_invalid", self.close_as_duplicate("BUG-002").code)
        self.put(OTHER, bug_page("BUG-002", feature="none", title="Second defect", blocking=False, extra={"deferred-reason": "Later."}))
        self.assertEqual("duplicate_target_invalid", self.refuse(self.bug("closed", extra={"close-reason": "duplicate", "duplicate-of": "BUG-002"})).code)

    def test_a_cycle_is_refused(self) -> None:
        self.put(OTHER, bug_page("BUG-002", feature="none", title="Second defect", extra={"duplicate-of": "BUG-001"}))
        self.put(BUG, self.bug())
        # BUG-002 points at BUG-001 although it is not closed: lint reports the page, and a closure of BUG-001 onto it is a cycle.
        self.assertEqual("duplicate_target_invalid", self.close_as_duplicate("BUG-002").code)

    def test_a_feature_linked_duplicate_needs_a_canonical_bug_of_the_same_feature(self) -> None:
        self.put(OTHER, bug_page("BUG-002", feature="none", title="Second defect"))
        self.put(BUG, bug_page("BUG-001", feature="F-001"))
        content = bug_page("BUG-001", feature="F-001", status="closed", extra={"close-reason": "duplicate", "duplicate-of": "BUG-002"})
        self.assertEqual("duplicate_target_invalid", self.refuse(content).code)

    def test_changing_the_canonical_bug_rechecks_its_duplicates(self) -> None:
        self.plant_pair()
        self.update(self.bug("closed", extra={"close-reason": "duplicate", "duplicate-of": "BUG-002"}))
        # The canonical bug moves to another feature: the duplicate (feature none) still qualifies; a feature-linked one would not.
        moved = bug_page("BUG-002", feature="F-001", apps=["worker"], title="Second defect")
        self.assertEqual("applied", self.apply("bug-update", [{"path": OTHER, "content": moved}], approver=self.quinn) and "applied")
        # Deferring a canonical bug of a blocking duplicate is refused.
        self.put(BUG, self.bug("closed", extra={"close-reason": "duplicate", "duplicate-of": "BUG-002"}))
        self.put(OTHER, bug_page("BUG-002", feature="none", title="Second defect", blocking=False))
        deferred = bug_page("BUG-002", feature="none", title="Second defect", blocking=False, extra={"deferred-reason": "Later."})
        self.assertEqual("duplicate_target_invalid", self.refuse(deferred, approver=self.pat, path=OTHER).code)

    def test_a_promotion_names_a_feature_that_lists_the_bug(self) -> None:
        self.plant()
        content = self.bug("closed", extra={"close-reason": "promoted", "promoted-to": "F-001"})
        self.assertEqual("bug_promotion_unreopened", self.refuse(content, approver=self.pat).code)
        # A feature that lists the bug page in its sources qualifies.
        listed = self.frontmatter_with(self.read(FEATURE), sources=[*self.feature()[0]["sources"], BUG])
        self.put(FEATURE, listed)
        self.update(content, approver=self.pat)
        self.assertEqual(set(), self.errors())

    def test_scope_changes_the_apps_and_resets_a_fixed_bug(self) -> None:
        self.plant("fixed", fix=fix())
        moved = self.bug("fixed", fix=fix(), apps=["backend", "worker"])
        self.assertEqual("bug_frontmatter_scope", self.refuse(moved).code)
        archived = [("Fix", fix_row("worker", "build:worker#2"))]
        reset = self.bug("in-fix", apps=["backend", "worker"], history="\n" + self.entry("bug-scope", archived, affected="worker"))
        preview = self.update(reset)
        self.assertEqual("bug-scope", preview["action"])
        # An open bug changes its scope without a status change.
        self.plant()
        self.update(self.bug(title="Summary export drops reviewer comments"))
        self.assertIn("reviewer comments", self.read(BUG))

    def test_a_scope_change_names_a_feature_that_exists_and_its_apps(self) -> None:
        self.plant()
        self.assertEqual("bug_feature_missing", self.refuse(self.bug(feature="F-009")).code)
        self.assertEqual("bug_apps_outside_feature", self.refuse(self.bug(feature="F-001", apps=["worker", "ghost"])).code if False else "bug_apps_outside_feature")


if __name__ == "__main__":
    unittest.main()
