"""Evidence labels, decision supersession, processed sources and conflict records: the mechanical lint checks."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path

from prism_cli.wiki_lint import EVIDENCE_LABELS, lint_wiki
from prism_cli.wiki_model import CONFLICT_STATUSES, intake_item_name_problem, parse_conflict_report
from tests import real_temp  # noqa: F401

FIXTURES = Path(__file__).parent / "fixtures" / "wiki_contract"
CHECK_DATE = date(2026, 10, 6)

SOURCE = "../../intake/processed/2026-10-06-client-call/notes.md"


class WorkspaceCase(unittest.TestCase):
    """A copy of the healthy wiki-contract workspace to add pages and intake items to."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        shutil.copytree(FIXTURES / "healthy", self.root, dirs_exist_ok=True)
        self.wiki = self.root / "knowledge" / "wiki"
        self.intake = self.root / "knowledge" / "intake"

    def write(self, relative: str, text: str) -> Path:
        path = self.wiki / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        return path

    def write_intake(self, relative: str, text: str) -> Path:
        path = self.intake / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        return path

    def lint(self):
        return lint_wiki(self.root, today=CHECK_DATE)

    def diagnostics(self, code: str) -> list:
        return [item for item in self.lint().diagnostics if item.code == code]

    def set_feature_summary(self, summary: str) -> Path:
        feature = self.wiki / "features" / "F-001-checkout.md"
        text = feature.read_text(encoding="utf-8")
        feature.write_text(text.replace("Customers can complete a checkout.\n", summary), encoding="utf-8", newline="\n")
        return feature


class EvidenceLabelTests(WorkspaceCase):
    def test_the_five_labels_are_the_defined_vocabulary(self) -> None:
        self.assertEqual(("Decided", "Observed", "Proposed", "Assumed", "Unknown"), EVIDENCE_LABELS)

    def test_labeled_and_linked_claims_are_clean(self) -> None:
        self.set_feature_summary(
            "Customers can complete a checkout.\n"
            f"- **Observed:** Support sees abandoned carts ([client call]({SOURCE})).\n"
            "- **Decided:** Checkout stays one page ([vendor note](https://example.com/vendor-note)).\n"
            "- **Proposed:** Offer a guest checkout.\n"
            "- **Assumed:** Carts expire after a day. Confirm with support.\n"
            "- **Unknown:** Whether gift cards are in scope.\n"
        )
        result = self.lint()
        self.assertEqual([], result.diagnostics)

    def test_a_decided_or_observed_claim_without_a_link_is_a_warning(self) -> None:
        feature = self.set_feature_summary(
            "Customers can complete a checkout.\n"
            "- **Observed:** Support sees abandoned carts.\n"
            f"- **Decided:** Checkout stays one page ([client call]({SOURCE})).\n"
            "**Decided:** A paragraph claim with no evidence at all.\n"
        )
        found = self.diagnostics("unlinked-claim")
        self.assertEqual(2, len(found), found)
        for item in found:
            self.assertEqual("warning", item.severity)
            self.assertEqual(feature.resolve(), Path(item.path).resolve())
            self.assertEqual("F-001", item.feature_id)
            self.assertIn("links no evidence", item.message)
        self.assertEqual(["Decided", "Observed"], sorted(item.message.split("`")[1] for item in found))
        self.assertTrue(self.lint().is_clean, "an unlinked claim is a warning, never an error")

    def test_a_link_on_a_continuation_line_belongs_to_the_claim(self) -> None:
        self.set_feature_summary(
            "Customers can complete a checkout.\n"
            "- **Observed:** Support sees abandoned carts after the\n"
            f"  payment step ([client call]({SOURCE})).\n"
            "- **Observed:** A claim whose link sits in the next item does not count.\n"
            f"- Related: [client call]({SOURCE}).\n"
        )
        found = self.diagnostics("unlinked-claim")
        self.assertEqual(1, len(found), found)
        self.assertIn("body line 6", found[0].message)

    def test_proposed_assumed_and_unknown_need_no_link(self) -> None:
        self.set_feature_summary(
            "Customers can complete a checkout.\n- **Proposed:** One.\n- **Assumed:** Two.\n- **Unknown:** Three.\n"
        )
        self.assertEqual([], self.diagnostics("unlinked-claim"))
        self.assertEqual([], self.diagnostics("unknown-evidence-label"))

    def test_a_bold_run_in_label_that_is_not_one_of_the_five_is_a_warning(self) -> None:
        self.set_feature_summary(
            "Customers can complete a checkout.\n"
            "- **Note:** Remember the guest flow.\n"
            "**Fact:** A paragraph label.\n"
            "- **decided:** Wrong case.\n"
        )
        found = self.diagnostics("unknown-evidence-label")
        self.assertEqual(3, len(found), found)
        self.assertEqual({"warning"}, {item.severity for item in found})
        for label in ("**Note:**", "**Fact:**", "**decided:**"):
            self.assertEqual(1, sum(f"`{label}`" in item.message for item in found), label)
        self.assertTrue(all("Decided" in item.message for item in found))

    def test_names_and_inline_bold_are_not_labels(self) -> None:
        self.set_feature_summary(
            "Customers can complete a checkout.\n"
            "- **backend**: Store the order.\n"
            "A sentence with **bold: inline** text and a **Note:** mid-line.\n"
            "```text\n**Note:** inside a fence.\n```\n"
        )
        self.assertEqual([], self.diagnostics("unknown-evidence-label"))

    def test_every_current_state_page_kind_is_checked_and_records_are_not(self) -> None:
        bad = "- **Note:** Not a label.\n"
        pages = {
            "personas/operator.md": f"---\nid: P-001\nname: Operator\nsources: []\n---\n\n## Who they are\n{bad}",
            "business-rules/BR-001-rule.md": f"---\nid: BR-001\ntitle: Rule\nsource: brief\n---\n\n## Rule\n{bad}",
            "design/F-001-checkout.md": f"---\nfeature-id: F-001\ntitle: Design\nfigma: not applicable\n---\n\n## Summary\n{bad}",
            "api-contracts/F-001.md": f"---\nfeature-id: F-001\nversion: 1\nstatus: draft\n---\n\n## Notes\n{bad}",
            "app-requirements/F-001-backend.md": f"---\nfeature-id: F-001\napp: backend\nstatus: pending\n---\n\n## What to build\n{bad}",
        }
        for relative, text in pages.items():
            self.write(relative, text)
        checked = {Path(item.path).resolve().relative_to(self.wiki.resolve()).as_posix() for item in self.diagnostics("unknown-evidence-label")}
        self.assertEqual(set(pages), checked)

        self.write("decisions/ADR-001-auth.md", f"---\nid: ADR-001\ntitle: Auth\ndate: 2026-01-01\nstatus: accepted\n---\n\n## Context\n{bad}")
        self.write("advisory/F-001-review.md", f"---\nfeature-id: F-001\nreviewed: 2026-01-02\nboard-members-consulted: [Riley]\n---\n\n## 1. Conflicts\n{bad}")
        after = {Path(item.path).resolve().relative_to(self.wiki.resolve()).as_posix() for item in self.diagnostics("unknown-evidence-label")}
        self.assertEqual(set(pages), after)


class DecisionSupersessionTests(WorkspaceCase):
    OLD = "---\nid: ADR-001\ntitle: Sessions\ndate: 2026-01-01\nstatus: accepted\n---\n\n## Context\nWhy.\n\n## Decision\nUse sessions.\n"
    OLD_SUPERSEDED = "---\nid: ADR-001\ntitle: Sessions\ndate: 2026-01-01\nstatus: superseded\nsuperseded-by: ADR-002\n---\n\n## Context\nWhy.\n\n## Decision\nUse sessions.\n"
    NEW = "---\nid: ADR-002\ntitle: Tokens\ndate: 2026-06-01\nstatus: accepted\nsupersedes: ADR-001\n---\n\n## Context\nWhy now.\n\n## Decision\nUse tokens.\n"

    def decisions(self, old: str, new: str | None) -> None:
        self.write("decisions/ADR-001-sessions.md", old)
        if new is not None:
            self.write("decisions/ADR-002-tokens.md", new)

    def mismatches(self) -> list:
        return self.diagnostics("supersession-mismatch")

    def test_a_consistent_pair_is_clean(self) -> None:
        self.decisions(self.OLD_SUPERSEDED, self.NEW)
        result = self.lint()
        self.assertEqual([], result.diagnostics)

    def test_a_decision_that_supersedes_nothing_is_clean(self) -> None:
        self.decisions(self.OLD, None)
        self.assertEqual([], self.lint().diagnostics)

    def test_the_new_adr_without_the_old_adrs_links_is_an_error_on_the_new_adr(self) -> None:
        self.decisions(self.OLD, self.NEW)
        found = self.mismatches()
        self.assertEqual(1, len(found), found)
        self.assertEqual("error", found[0].severity)
        self.assertTrue(Path(found[0].path).name.startswith("ADR-002"))
        self.assertIn("ADR-001", found[0].message)
        self.assertFalse(self.lint().is_clean)

    def test_the_old_adr_without_the_new_adrs_supersedes_is_an_error_on_the_old_adr(self) -> None:
        new = self.NEW.replace("supersedes: ADR-001\n", "")
        self.decisions(self.OLD_SUPERSEDED, new)
        found = self.mismatches()
        self.assertEqual(1, len(found), found)
        self.assertTrue(Path(found[0].path).name.startswith("ADR-001"))
        self.assertIn("does not declare `supersedes: ADR-001`", found[0].message)

    def test_the_two_links_must_name_each_other(self) -> None:
        wrong_old = self.OLD_SUPERSEDED.replace("superseded-by: ADR-002", "superseded-by: ADR-003")
        self.decisions(wrong_old, self.NEW)
        names = sorted(Path(item.path).name for item in self.mismatches())
        self.assertEqual(2, len(names), names)
        self.assertTrue(names[0].startswith("ADR-001") and names[1].startswith("ADR-002"))

    def test_status_and_superseded_by_must_agree(self) -> None:
        self.decisions(self.OLD_SUPERSEDED.replace("superseded-by: ADR-002\n", ""), None)
        found = self.mismatches()
        self.assertEqual(1, len(found), found)
        self.assertIn("no `superseded-by", found[0].message)

        self.decisions(self.OLD_SUPERSEDED.replace("status: superseded", "status: accepted"), self.NEW)
        messages = [item.message for item in self.mismatches() if Path(item.path).name.startswith("ADR-001")]
        self.assertEqual(1, len(messages), messages)
        self.assertIn("its status is `accepted`", messages[0])

    def test_a_link_to_a_missing_or_malformed_adr_is_an_error(self) -> None:
        for label, old, new in (
            ("missing target", self.OLD, self.NEW.replace("supersedes: ADR-001", "supersedes: ADR-007")),
            ("malformed value", self.OLD, self.NEW.replace("supersedes: ADR-001", "supersedes: the first one")),
            ("self", self.OLD, self.NEW.replace("supersedes: ADR-001", "supersedes: ADR-002")),
        ):
            with self.subTest(label):
                self.decisions(old, new)
                found = [item for item in self.mismatches() if Path(item.path).name.startswith("ADR-002")]
                self.assertEqual(1, len(found), found)

    def test_superseded_is_a_decision_status_and_the_old_inline_form_is_not(self) -> None:
        self.decisions(self.OLD_SUPERSEDED, self.NEW)
        self.assertEqual([], self.diagnostics("invalid-decision-status"))
        old_form = self.OLD.replace("status: accepted", "status: superseded-by ADR-002")
        self.decisions(old_form, self.NEW)
        self.assertEqual(1, len(self.diagnostics("invalid-decision-status")))

    def test_a_current_state_page_that_links_a_superseded_adr_is_a_warning(self) -> None:
        self.decisions(self.OLD_SUPERSEDED, self.NEW)
        feature = self.set_feature_summary(
            "Customers can complete a checkout.\n- **Decided:** Sign-in uses sessions ([ADR-001](../decisions/ADR-001-sessions.md)).\n"
        )
        found = self.diagnostics("superseded-decision-cited")
        self.assertEqual(1, len(found), found)
        self.assertEqual("warning", found[0].severity)
        self.assertEqual(feature.resolve(), Path(found[0].path).resolve())
        self.assertIn("ADR-001", found[0].message)
        self.assertIn("ADR-002", found[0].message)
        self.assertTrue(self.lint().is_clean)

        text = feature.read_text(encoding="utf-8").replace("ADR-001-sessions.md", "ADR-002-tokens.md").replace("sessions ([ADR-001]", "tokens ([ADR-002]")
        feature.write_text(text, encoding="utf-8", newline="\n")
        self.assertEqual([], self.lint().diagnostics)

    def test_records_and_the_index_may_link_a_superseded_adr(self) -> None:
        self.decisions(self.OLD_SUPERSEDED, self.NEW)
        self.write("decisions/ADR-002-tokens.md", self.NEW + "\nSupersedes [ADR-001](ADR-001-sessions.md).\n")
        self.assertEqual([], self.diagnostics("superseded-decision-cited"))


class ProcessedSourceTests(WorkspaceCase):
    def test_a_processed_item_without_a_manifest_is_a_warning(self) -> None:
        self.write_intake("processed/2026-10-06-client-call/notes.md", "# Notes\n")
        found = self.diagnostics("processed-source-without-manifest")
        self.assertEqual(1, len(found), found)
        self.assertEqual("warning", found[0].severity)
        self.assertEqual((self.intake / "processed" / "2026-10-06-client-call").resolve(), Path(found[0].path).resolve())
        self.assertTrue(self.lint().is_clean)

    def test_a_manifest_clears_the_warning_and_files_are_not_items(self) -> None:
        self.write_intake("processed/2026-10-06-client-call/notes.md", "# Notes\n")
        self.write_intake("processed/2026-10-06-client-call/MANIFEST.md", "# Manifest\n\nNo pages extracted.\n")
        self.write_intake("processed/.gitkeep", "")
        self.assertEqual([], self.lint().diagnostics)

    def test_the_intake_item_name_rule(self) -> None:
        for name in ("2026-10-06-client-call", "2026-10-06-f003-feasibility-notes", "2026-02-28-a"):
            with self.subTest(name=name):
                self.assertIsNone(intake_item_name_problem(name))
        for name in ("client-call", "2026-10-06", "2026-10-06-", "2026-10-06-Client-Call", "2026-13-06-client-call", "2026-02-30-client-call", "2026-10-06--call", "20261006-call"):
            with self.subTest(name=name):
                self.assertIsNotNone(intake_item_name_problem(name))


VALID_CONFLICT = """---
status: open
---

# Conflict: payout cadence

## Existing claim
- **Claim:** The page says payouts settle once per day.
- **Scope:** Checkout payouts for the web app.
- **Evidence:** [F-001](../../../wiki/features/F-001-checkout.md)

## Incoming claim
- **Claim:** The note says payouts settle twice per day.
- **Scope:** Checkout payouts for the web app.
- **Evidence:** [notes.md](notes.md)

## Decision needed
Which cadence holds.
"""


class ConflictRecordTests(WorkspaceCase):
    def write_conflict(self, text: str, name: str = "2026-10-07-payout-note") -> Path:
        self.write_intake(f"quarantined/{name}/notes.md", "# Note\n")
        return self.write_intake(f"quarantined/{name}/CONFLICT.md", text)

    def test_an_open_conflict_is_a_warning_that_links_the_file(self) -> None:
        report = self.write_conflict(VALID_CONFLICT)
        result = self.lint()
        found = [item for item in result.diagnostics if item.code == "unresolved-conflict"]
        self.assertEqual(1, len(found), result.diagnostics)
        self.assertEqual("warning", found[0].severity)
        self.assertEqual(report.resolve(), Path(found[0].path).resolve())
        self.assertIn("knowledge/intake/quarantined/2026-10-07-payout-note/CONFLICT.md", found[0].message)
        self.assertEqual([], [item for item in result.diagnostics if item.code != "unresolved-conflict"])
        self.assertTrue(result.is_clean, "a non-empty quarantine is not a gate")

    def test_a_resolved_conflict_is_clean_history(self) -> None:
        self.write_conflict(VALID_CONFLICT.replace("status: open", "status: resolved") + "\n## Resolution\nThe existing page holds; no page changed.\n")
        self.assertEqual([], self.lint().diagnostics)

    def test_a_quarantined_item_without_a_conflict_file_is_an_error(self) -> None:
        self.write_intake("quarantined/2026-10-07-payout-note/notes.md", "# Note\n")
        found = self.diagnostics("malformed-conflict")
        self.assertEqual(1, len(found), found)
        self.assertEqual("error", found[0].severity)
        self.assertFalse(self.lint().is_clean)

    def test_each_structural_problem_is_malformed_conflict(self) -> None:
        # (text, whether the file still states a valid `open` status)
        cases = {
            "no front matter": (VALID_CONFLICT.split("---\n", 2)[2], False),
            "bad status": (VALID_CONFLICT.replace("status: open", "status: pending"), False),
            "no status": (VALID_CONFLICT.replace("status: open\n", ""), False),
            "no existing claim": (VALID_CONFLICT.replace("## Existing claim", "## Existing"), True),
            "no incoming claim": (VALID_CONFLICT.replace("## Incoming claim", "## Incoming"), True),
            "no scope": (VALID_CONFLICT.replace("- **Scope:** Checkout payouts for the web app.\n", "", 1), True),
            "blank claim": (VALID_CONFLICT.replace("- **Claim:** The note says payouts settle twice per day.", "- **Claim:**"), True),
            "evidence without a link": (VALID_CONFLICT.replace("[notes.md](notes.md)", "the note"), True),
            "resolved without a resolution": (VALID_CONFLICT.replace("status: open", "status: resolved"), False),
        }
        for label, (text, still_open) in cases.items():
            with self.subTest(label):
                report = self.write_conflict(text)
                result = self.lint()
                malformed = [item for item in result.diagnostics if item.code == "malformed-conflict"]
                self.assertTrue(malformed, label)
                self.assertEqual({"error"}, {item.severity for item in malformed})
                self.assertEqual({report.resolve()}, {Path(item.path).resolve() for item in malformed})
                self.assertEqual(still_open, any(item.code == "unresolved-conflict" for item in result.diagnostics))
                self.assertFalse(result.is_clean)

    def test_the_report_parser_returns_status_and_problems(self) -> None:
        self.assertEqual(("open", []), parse_conflict_report(VALID_CONFLICT))
        status, problems = parse_conflict_report(VALID_CONFLICT.replace("status: open", "status: nope"))
        self.assertIsNone(status)
        self.assertEqual(1, len(problems))
        self.assertEqual(("open", "resolved"), CONFLICT_STATUSES)


if __name__ == "__main__":
    unittest.main()
