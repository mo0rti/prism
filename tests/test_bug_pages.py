"""The bug page kind: parsing, the blocking and duplicate rules, lint, the index and search (CONTRACTS 6.2)."""

from __future__ import annotations

import unittest
from pathlib import Path

from prism_cli.wiki_bugs import (
    BugPage,
    blocks,
    bug_listing_digest,
    bugs_by_id,
    duplicate_problems,
    duplicate_target_problem,
    feature_cites_bug,
    next_bug_number,
    parse_fix_rows,
    parse_verification_rows,
    read_bug_pages,
    verification_artifact,
)
from prism_cli.wiki_index import is_current_state_page, page_group
from prism_cli.wiki_lint import lint_wiki
from prism_cli.wiki_model import parse_markdown_text, read_feature_evidence
from prism_cli.wiki_query import wiki_search
from tests.qa_support import FIX_HEADER, VERIFICATION_HEADER, bug_page, fix_row, verification_row
from tests.test_lifecycle_model import TEXT_ONE, TEXT_TWO, ARTIFACT, _Workspace, delivery_row, qa_row, ref, release_row, table

BOTH = ["backend", "worker"]
BUGS = "knowledge/wiki/bugs"


def page(text: str, name: str = "BUG-001-x.md") -> BugPage:
    return BugPage(parse_markdown_text(Path(name), text))


class BugParserTests(unittest.TestCase):
    def test_a_bug_page_reads_its_fields(self) -> None:
        bug = page(bug_page("BUG-007", status="closed", extra={"close-reason": "wont-fix: Accepted.", "deferred-reason": "Later."}, blocking=False))
        self.assertEqual(("BUG-007", "closed", "none", "wont-fix", True), (bug.bug_id, bug.status, bug.owner, bug.disposition, bug.deferred))
        self.assertEqual(["worker"], bug.apps)
        self.assertEqual("F-001", bug.feature)
        self.assertIsNone(page(bug_page(feature="none")).feature)

    def test_fix_and_verification_rows(self) -> None:
        rows, problems = parse_fix_rows(bug_page(fix=table(FIX_HEADER, [fix_row()])))
        self.assertEqual(([], ("worker", "build:worker#2")), (problems, (rows[0].app, rows[0].artifact)))
        rows, problems = parse_verification_rows(bug_page(verification=table(VERIFICATION_HEADER, [verification_row()])))
        self.assertEqual(([], ("worker", 1, "pass")), (problems, (rows[0].app, rows[0].attempt, rows[0].result)))
        bad_fix = table(FIX_HEADER, ["| worker | `build-2` | [PR](https://x.example/1) | tests | maybe |"])
        codes = {item.code for item in parse_fix_rows(bug_page(fix=bad_fix))[1]}
        self.assertEqual({"artifact_reference_invalid", "basis_invalid"}, codes)
        bad_verification = table(VERIFICATION_HEADER, ["| worker | guess | `build:worker#2` | not valid! | later | pass | [n](https://x.example) | checked |"])
        self.assertGreaterEqual(len(parse_verification_rows(bug_page(verification=bad_verification))[1]), 3)
        # A table with another header is a problem and yields no rows.
        wrong = "| App | Artifact | Contract | Implementation | Tests | Basis |\n|---|---|---|---|---|---|\n| worker | `build:worker#2` | none | x | y | checked |"
        rows, problems = parse_fix_rows(bug_page(fix=wrong))
        self.assertEqual(([], 1), (rows, len(problems)))

    def test_the_listing_digest_changes_with_the_file_names(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            wiki = Path(folder)
            (wiki / "bugs").mkdir()
            empty = bug_listing_digest(wiki)
            (wiki / "bugs" / "BUG-001-x.md").write_text(bug_page(), encoding="utf-8")
            one = bug_listing_digest(wiki)
            (wiki / "bugs" / "BUG-001-x.md").write_text(bug_page(title="Edited"), encoding="utf-8")
            self.assertNotEqual(empty, one)
            self.assertEqual(one, bug_listing_digest(wiki), "an edit of a page does not change the listing")
            self.assertEqual(2, next_bug_number(read_bug_pages(wiki)))

    def test_the_page_kind_is_registered(self) -> None:
        self.assertEqual("bugs", page_group("bugs/BUG-001-x.md"))
        self.assertTrue(is_current_state_page("bugs/BUG-001-x.md"))


class BlockingTests(unittest.TestCase):
    def test_a_bug_blocks_until_it_is_verified_released_closed_or_deferred(self) -> None:
        cases = {
            "open": (bug_page(status="open"), True),
            "in-fix": (bug_page(status="in-fix"), True),
            "fixed": (bug_page(status="fixed"), True),
            "verified": (bug_page(status="verified"), False),
            "released": (bug_page(status="released"), False),
            "closed": (bug_page(status="closed", extra={"close-reason": "wont-fix: ok"}), False),
            "deferred": (bug_page(blocking=False, extra={"deferred-reason": "Later."}), False),
        }
        for name, (text, expected) in cases.items():
            with self.subTest(name=name):
                self.assertEqual(expected, blocks(page(text), "F-001", "worker"))

    def test_a_bug_blocks_only_its_feature_and_its_apps(self) -> None:
        bug = page(bug_page(apps=["worker"]))
        self.assertFalse(blocks(bug, "F-001", "backend"))
        self.assertFalse(blocks(bug, "F-002", "worker"))
        self.assertFalse(blocks(page(bug_page(feature="none")), "F-001", "worker"))

    def test_the_verification_artifact(self) -> None:
        body = (
            "## Delivery evidence\n"
            + table("| App | Artifact | Contract | Implementation | Tests | Basis |", [delivery_row("worker", "build:worker#5")])
            + "\n\n## QA verification\n\n## Release\n"
        )
        evidence = read_feature_evidence(body)
        fixed = page(bug_page(status="fixed", fix=table(FIX_HEADER, [fix_row("worker", "build:worker#2")])))
        # The app is delivered and not in QA yet beyond ready-for-qa: the delivered artifact verifies the bug.
        self.assertEqual("build:worker#5", verification_artifact(fixed, "worker", evidence))
        self.assertEqual("build:worker#2", verification_artifact(fixed, "worker", None))
        unlinked = page(bug_page(feature="none", status="fixed", fix=table(FIX_HEADER, [fix_row("worker", "build:worker#2")])))
        self.assertEqual("build:worker#2", verification_artifact(unlinked, "worker", evidence))


class DuplicateRuleTests(unittest.TestCase):
    def index(self, *texts: str) -> dict:
        return bugs_by_id([page(text, f"BUG-00{n}-x.md") for n, text in enumerate(texts, start=1)])

    def test_each_clause_of_the_rule(self) -> None:
        duplicate = bug_page("BUG-001", status="closed", extra={"close-reason": "duplicate", "duplicate-of": "BUG-002"})
        canonical = bug_page("BUG-002", title="Canonical")
        index = self.index(duplicate, canonical)
        self.assertIsNone(duplicate_target_problem(index["bug-001"], index))
        cases = {
            "missing canonical": self.index(duplicate),
            "closed canonical": self.index(duplicate, bug_page("BUG-002", status="closed", extra={"close-reason": "wont-fix: ok"})),
            "other feature": self.index(duplicate, bug_page("BUG-002", feature="F-009")),
            "no feature": self.index(duplicate, bug_page("BUG-002", feature="none")),
            "fewer apps": self.index(bug_page("BUG-001", status="closed", apps=["backend", "worker"], extra={"close-reason": "duplicate", "duplicate-of": "BUG-002"}), canonical),
            "deferred": self.index(duplicate, bug_page("BUG-002", blocking=False, extra={"deferred-reason": "Later."})),
            "itself": self.index(bug_page("BUG-001", status="closed", extra={"close-reason": "duplicate", "duplicate-of": "BUG-001"})),
            "cycle": self.index(duplicate, bug_page("BUG-002", extra={"duplicate-of": "BUG-001"})),
        }
        for name, bugs in cases.items():
            with self.subTest(name=name):
                self.assertIsNotNone(duplicate_target_problem(bugs["bug-001"], bugs))
        # A feature-less duplicate may point at a bug of a feature.
        free = self.index(bug_page("BUG-001", feature="none", status="closed", extra={"close-reason": "duplicate", "duplicate-of": "BUG-002"}), canonical)
        self.assertIsNone(duplicate_target_problem(free["bug-001"], free))
        # A non-blocking duplicate may point at a deferred canonical bug.
        relaxed = self.index(bug_page("BUG-001", blocking=False, status="closed", extra={"close-reason": "duplicate", "duplicate-of": "BUG-002"}), bug_page("BUG-002", blocking=False, extra={"deferred-reason": "Later."}))
        self.assertIsNone(duplicate_target_problem(relaxed["bug-001"], relaxed))

    def test_the_problems_of_a_wiki_are_listed_per_feature(self) -> None:
        pages = [
            page(bug_page("BUG-001", status="closed", extra={"close-reason": "duplicate", "duplicate-of": "BUG-002"}), "BUG-001-x.md"),
            page(bug_page("BUG-002", status="closed", extra={"close-reason": "wont-fix: ok"}), "BUG-002-x.md"),
        ]
        self.assertEqual(["BUG-001"], [duplicate.bug_id for duplicate, _reason in duplicate_problems(pages)])
        self.assertEqual(["BUG-001"], [duplicate.bug_id for duplicate, _reason in duplicate_problems(pages, feature_id="F-001")])
        self.assertEqual([], duplicate_problems(pages, feature_id="F-009"))

    def test_a_feature_cites_a_bug_in_sources_or_in_its_latest_history_entry(self) -> None:
        path = "knowledge/wiki/bugs/BUG-001-x.md"
        self.assertTrue(feature_cites_bug({"sources": [path]}, "", path, "BUG-001"))
        self.assertTrue(feature_cites_bug({"sources": []}, "## Evidence history\n### 2026-10-08 - reopen-spec\n- Reason: x\n- Linked bugs: BUG-001\n", path, "BUG-001"))
        self.assertFalse(feature_cites_bug({"sources": []}, "## Evidence history\n### 2026-10-08 - reopen-spec\n- Linked bugs: none\n", path, "BUG-001"))


class BugLintTests(_Workspace):
    def put_bug(self, text: str, name: str = "BUG-001-summary-export.md") -> None:
        path = self.root / BUGS / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))

    def seed_feature(self, status="in-dev", owner="dev", **rows) -> None:
        criteria = [f"AC-1 [backend, worker] {TEXT_ONE}", f"AC-2 [backend] {TEXT_TWO}"]
        self.seed(status, owner, self.page(status, owner, BOTH, criteria, **rows))

    def findings(self) -> dict[str, list[str]]:
        found: dict[str, list[str]] = {}
        for item in lint_wiki(self.root).diagnostics:
            found.setdefault(item.code, []).append(item.message)
        return found

    def test_a_valid_bug_lints_clean_and_is_indexed(self) -> None:
        self.put_bug(bug_page())
        self.seed_feature()
        found = self.findings()
        self.assertEqual({}, {code: items for code, items in found.items() if code.startswith(("bug", "invalid-bug", "duplicate-target", "promoted"))})
        self.assertIn("bugs/BUG-001-summary-export.md", (self.root / "knowledge/wiki/index.md").read_text(encoding="utf-8"))

    def test_each_finding_has_its_code(self) -> None:
        cases = {
            "bug-page-invalid": bug_page().replace("severity: high", "severity: awful"),
            "invalid-bug-status-owner": bug_page().replace("owner: dev", "owner: qa"),
            "bug-close-reason-required": bug_page(status="closed"),
            "bug-feature-missing": bug_page(feature="F-009"),
            "promoted-bug-unreopened": bug_page(status="closed", extra={"close-reason": "promoted", "promoted-to": "F-001"}),
            "duplicate-target-invalid": bug_page(status="closed", extra={"close-reason": "duplicate", "duplicate-of": "BUG-009"}),
        }
        for code, text in cases.items():
            with self.subTest(code=code):
                self.put_bug(text)
                self.seed_feature()
                self.assertIn(code, self.findings())

    def test_a_bug_page_with_the_wrong_file_name_or_a_twin_id_is_reported(self) -> None:
        self.put_bug(bug_page(), "BUG-002-wrong-number.md")
        self.seed_feature()
        self.assertIn("bug-page-invalid", self.findings())
        self.put_bug(bug_page(), "BUG-002-wrong-number.md")
        (self.root / BUGS / "BUG-002-wrong-number.md").unlink()
        self.put_bug(bug_page())
        self.put_bug(bug_page(title="Twin"), "BUG-001-twin.md")
        self.seed_feature()
        self.assertTrue(any("Duplicate bug id" in message for message in self.findings().get("bug-page-invalid", [])))

    def test_a_fixed_bug_needs_its_evidence(self) -> None:
        self.put_bug(bug_page(status="fixed"))
        self.seed_feature()
        self.assertTrue(any("Fix row" in message for message in self.findings().get("bug-page-invalid", [])))
        self.put_bug(bug_page(status="verified", fix=table(FIX_HEADER, [fix_row()])))
        self.seed_feature()
        self.assertTrue(any("Verification row" in message for message in self.findings().get("bug-page-invalid", [])))
        self.put_bug(bug_page(status="open", fix=table(FIX_HEADER, [fix_row()])))
        self.seed_feature()
        self.assertTrue(any("no active Fix" in message for message in self.findings().get("bug-page-invalid", [])))

    def test_a_blocking_bug_of_an_app_ready_for_release_is_a_blocker(self) -> None:
        qa = [
            qa_row("backend", [ref(1, BOTH, TEXT_ONE), ref(2, ["backend"], TEXT_TWO)], f"`{ARTIFACT['backend']}`"),
        ]
        self.put_bug(bug_page(apps=["backend"]))
        self.seed_feature(
            "in-dev",
            "dev",
            delivery=[delivery_row("backend")],
            qa=qa,
            release=[release_row("backend")],
        )
        found = self.findings()
        self.assertIn("open-bug-blocks-qa", found)
        # The finding is a blocker, not an integrity error, and the bug of an app without a Release row does not trigger it.
        result = lint_wiki(self.root)
        self.assertIn("open-bug-blocks-qa", [item.code for item in result.readiness_blockers])
        self.put_bug(bug_page(apps=["worker"]))
        self.seed_feature("in-dev", "dev", delivery=[delivery_row("backend")], qa=qa, release=[release_row("backend")])
        self.assertNotIn("open-bug-blocks-qa", self.findings())

    def test_bug_pages_are_found_by_search(self) -> None:
        self.put_bug(bug_page(title="Summary export drops comments"))
        self.seed_feature()
        result = wiki_search(self.root, "drops comments")
        self.assertIn("bug", [item["type"] for item in result["facts"]["results"]])


if __name__ == "__main__":
    unittest.main()
