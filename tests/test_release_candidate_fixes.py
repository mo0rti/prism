"""The fixes from the 0.7.2 release-candidate review, each with the case that failed before it.

1. One section parser for every write-scope check and every evidence reader.
2. Separation holds through a chain of repairs and recoveries.
3. A repair binds the files it adopts.
4. A page in `releases/` that is not a valid record carries no authority.
6. An Evidence history heading is checked against the operation's preview day on a replay.

The browser cases for the approval view (5, 7) are in `tests/browser/test_proposal_review_scenarios.py`.
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import yaml

import tests.test_qa_fail as qa_fail
from prism_cli.board_service import BoardError, BoardService, _strip_section
from prism_cli.release_rules import rollback_problems
from prism_cli.wiki_lint import WikiDiagnostic, lint_wiki
from prism_cli.wiki_model import contract_page_citation
from prism_cli.wiki_model import parse_markdown_text, parse_open_question_rows, read_feature_evidence, section_text
from prism_cli.wiki_releases import ReleaseRecord, current_delivery, next_release_number, parse_record_rows, read_release_records, record_kinds
from prism_cli.workflow_assets import asset_digest
from tests.core_workflow_fixture import FEATURE_PATH, create_core_workflow_fixture
from tests.qa_support import FEATURE as FEATURE_PAGE, QaBoard, fix_row, verification_row
from tests.release_pages import RELEASES, delivery, record_page
from tests.release_support import ReleaseTests
from tests.test_board_identity import BOARD, FEATURE, GatedBoardCase
from tests.test_board_separation import JournalCase, subject
from tests.test_bug_actions import BUG, BugBoard, fix as bug_fix, verification as bug_verification
from tests.test_core_workflow_fixture import _feature_page
from tests.test_board_service import _read_revisions
from tests.wiki_files import write_index, write_status_board

OPEN_ROW = "| 1 | Which points should a review summary highlight? | po | open |"
SECOND_QUESTION = "| 2 | How should the review be organized? | designer | open |"
EVIDENCE_TABLE = (
    " | App | Artifact | Contract | Implementation | Tests | Basis |\n"
    " |---|---|---|---|---|---|\n"
    " | backend | `build:backend#1` | none | https://ci.example/pr/1 | https://ci.example/tests/1 | checked |\n"
)
RELEASE_TABLE = (
    " | App | Target | Version | Attempt | Outcome | Record | Basis |\n"
    " |---|---|---|---|---|---|---|\n"
    " | backend | production | `build:backend#1` | release-1 | released | [REL-001](../releases/REL-001.md) | checked |\n"
)
# One space of indentation hides each heading from a reader that matches at column zero and shows it to one that trims the line.
FORGED_TAIL = f"{SECOND_QUESTION}\n ## Delivery evidence\n{EVIDENCE_TABLE} ## Release\n{RELEASE_TABLE}"


class SectionParserTests(unittest.TestCase):
    """Finding 1: a level-two heading is a `## ` line in column zero outside fenced code, for every reader."""

    BODY = (
        "## Open questions\n"
        "| # | Question | Owner | Status |\n|---|---|---|---|\n"
        f"{OPEN_ROW}\n"
        " ## Delivery evidence\n"
        f"{EVIDENCE_TABLE}"
        "```\n## Release\n```\n"
        "\n## App scope\nbackend\n"
    )

    def test_an_indented_heading_and_a_fenced_heading_belong_to_the_section_they_sit_in(self) -> None:
        from prism_cli.wiki_model import markdown_sections

        self.assertEqual(["Open questions", "App scope"], [section.name for section in markdown_sections(self.BODY)])
        self.assertIn(" ## Delivery evidence", section_text(self.BODY, "Open questions"))
        self.assertIn("```\n## Release\n```", section_text(self.BODY, "Open questions"))
        self.assertEqual("", section_text(self.BODY, "Delivery evidence"))
        self.assertEqual("", section_text(self.BODY, "Release"))

    def test_the_evidence_reader_and_the_scope_check_see_the_same_sections(self) -> None:
        forged = self.BODY.replace("```\n## Release\n```\n", f" ## Release\n{RELEASE_TABLE}")
        evidence = read_feature_evidence(forged)
        self.assertEqual(((), ()), (evidence.delivery, evidence.release), "an indented heading starts no evidence section")
        stripped = _strip_section(forged, "Open questions")
        self.assertEqual("## App scope\nbackend\n", stripped, "the scope check removes the whole region the reader sees")
        rows, errors = parse_open_question_rows(forged)
        self.assertEqual(1, len(rows))
        self.assertTrue(errors, "the indented table lines are lines of the Open questions table, and malformed there")

    def test_a_duplicate_or_an_indented_lifecycle_heading_is_ambiguous(self) -> None:
        from prism_cli.wiki_model import section_ambiguities

        names = ("Delivery evidence", "QA verification", "Release", "Evidence history")
        self.assertEqual([], section_ambiguities("## Delivery evidence\nrows\n\n## Release\nrows\n", names))
        twice = section_ambiguities("## Delivery evidence\na\n## Delivery evidence\nb\n", names)
        self.assertEqual(1, len(twice))
        self.assertIn("appears 2 times", twice[0])
        indented = section_ambiguities(self.BODY, names)
        self.assertEqual(1, len(indented))
        self.assertIn("indented `## Delivery evidence`", indented[0])
        self.assertEqual([], section_ambiguities("## Notes\n```\n## Release\n```\n", names), "a heading in fenced code is text")


class ForgedLifecycleSectionTests(unittest.TestCase):
    """Finding 1 through the board: an `ask` answer cannot carry lifecycle evidence in indented headings."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = create_core_workflow_fixture(Path(temporary.name) / "board")
        manifest_path = self.root / "prism.workspace.yml"
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        manifest["workflow"] = {"version": "1", "board_id": "3a8db764-f386-461e-bb0b-165de1dcf3a9", "mode": "workflow", "asset_digest": asset_digest("1")}
        manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
        self.service = BoardService(self.root).start()
        self.addCleanup(self.service.close)
        self.actor = self.service.authenticate(self.service.create_participant("Validator", "agent", writable=True)["token"])
        self.relative = FEATURE_PATH.as_posix()
        path = self.root / FEATURE_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_feature_page(), encoding="utf-8")
        self.original = path.read_text(encoding="utf-8")

    def preview(self, content: str, skill: str = "ask") -> dict:
        changes = [{"path": self.relative, "content": content}]
        revisions = _read_revisions(self.service, self.actor, skill, changes)
        return self.service.preview_skill(self.actor, skill, changes, read_revisions=revisions)

    def refusal(self, content: str, skill: str = "ask") -> str:
        with self.assertRaises(BoardError) as raised:
            self.preview(content, skill)
        self.assertEqual(409, raised.exception.status)
        return raised.exception.code

    def test_forged_indented_sections_in_an_ask_answer_are_refused_and_the_stage_does_not_move(self) -> None:
        forged = self.original.replace(OPEN_ROW, f"{OPEN_ROW}\n{FORGED_TAIL}")
        evidence = read_feature_evidence(parse_markdown_text(Path("forged.md"), forged).body)
        self.assertEqual(((), ()), (evidence.delivery, evidence.release), "no reader takes the indented headings for sections")
        self.assertEqual("ambiguous_lifecycle_section", self.refusal(forged))
        self.assertEqual(self.original, (self.root / FEATURE_PATH).read_text(encoding="utf-8"), "a refused preview writes nothing")
        disk = read_feature_evidence(parse_markdown_text(self.root / FEATURE_PATH, self.original).body)
        self.assertEqual((), disk.delivery + disk.release)

    def test_a_duplicate_lifecycle_section_is_refused_at_preview(self) -> None:
        question = self.original.replace(OPEN_ROW, f"{OPEN_ROW}\n{SECOND_QUESTION}")
        twice = question + "\n## Release\n" + RELEASE_TABLE.replace("\n ", "\n").lstrip() + "\n## Release\nNone.\n"
        self.assertEqual("ambiguous_lifecycle_section", self.refusal(twice))

    def test_a_question_skill_leaves_every_lifecycle_section_byte_identical(self) -> None:
        resolved = self.original.replace(OPEN_ROW, "| 1 | Which points should a review summary highlight? | po | resolved: Capture key points. |")
        with_release = resolved + "\n## Release\n" + RELEASE_TABLE.replace("\n ", "\n").lstrip()
        for skill in ("po-clarify", "design-clarify", "dev-clarify"):
            with self.subTest(skill=skill), self.assertRaises(BoardError) as raised:
                self.service._validate_question_change(skill, self.relative, self.original, with_release)
            self.assertEqual("lifecycle_evidence_changed", raised.exception.code)
        self.service._validate_question_change("po-clarify", self.relative, self.original, resolved)

    def test_an_intake_creates_a_feature_without_evidence(self) -> None:
        released = self.original + "\n## Release\n" + RELEASE_TABLE.replace("\n ", "\n").lstrip()
        for skill in ("po-intake", "ingest"):
            with self.subTest(skill=skill), self.assertRaises(BoardError) as raised:
                self.service._validate_feature_output(self.relative, released, skill)
            self.assertEqual("lifecycle_evidence_changed", raised.exception.code)
        self.service._validate_feature_output(self.relative, self.original, "po-intake")

    def test_lint_names_a_page_with_an_ambiguous_lifecycle_section(self) -> None:
        forged = self.original.replace(OPEN_ROW, f"{OPEN_ROW}\n{FORGED_TAIL}")
        (self.root / FEATURE_PATH).write_text(forged, encoding="utf-8")
        flagged = [item for item in lint_wiki(self.root).diagnostics if item.code == "ambiguous-lifecycle-section"]
        self.assertEqual(2, len(flagged))
        self.assertTrue(all(item.path.endswith("F-001-document-review.md") and item.severity == "error" for item in flagged))
        (self.root / FEATURE_PATH).write_text(self.original + "\n## Release\nNone.\n\n## Release\nNone.\n", encoding="utf-8")
        self.assertEqual(1, len([item for item in lint_wiki(self.root).diagnostics if item.code == "ambiguous-lifecycle-section"]))


class RepairChainSeparationTests(JournalCase):
    """Finding 2: A approves `dev-done`, B starts its repair, C recovers that repair; C cannot approve QA of the evidence."""

    def setUp(self) -> None:
        super().setUp()
        self.recoverer = self.human("Cass", "qa")
        self.quinn = self.human("Quinn", "qa")
        self.insert_operation("dev-done-1", self.dev)
        self.insert_operation("repair-1", self.po, repair_of="dev-done-1", attempts=[self.recoverer])
        self.produce("dev-done-1", subject())
        self.policy(True)

    def test_the_recoverer_of_a_repair_cannot_approve_qa_of_the_repaired_evidence(self) -> None:
        self.assertEqual(
            {self.dev.participant_id, self.po.participant_id, self.recoverer.participant_id},
            self.service._excluded_approvers("dev-done-1"),
        )
        self.assertEqual("separation_required", self.code(lambda: self.check(self.recoverer, subject())))
        self.check(self.quinn, subject())

    def test_a_repair_of_a_repair_counts_and_a_cycle_does_not_loop(self) -> None:
        second = self.human("Remy", "dev")
        third = self.human("Rae", "dev")
        self.insert_operation("repair-2", second, repair_of="repair-1", attempts=[third])
        self.assertEqual(
            {self.dev.participant_id, self.po.participant_id, self.recoverer.participant_id, second.participant_id, third.participant_id},
            self.service._excluded_approvers("dev-done-1"),
        )
        with self.service.store.transaction() as db:
            db.execute("UPDATE operations SET repair_of = 'repair-2' WHERE operation_id = 'dev-done-1'")
        self.assertIn(third.participant_id, self.service._excluded_approvers("dev-done-1"))
        self.assertEqual("separation_required", self.code(lambda: self.check(third, subject())))


class RepairBindsAdoptedFilesTests(GatedBoardCase):
    """Finding 3: a repair binds the current state of the files it adopts, and rechecks them and its lint on every replay."""

    def abandoned_operation(self, operation: str = "pending-1") -> None:
        preview = self.agent_proposal()
        self.crash_after_first_write(self.designer, preview, operation)
        review = self.service.operation(self.designer, operation)["recovery_review_revision"]
        failure = BoardError("checks_changed", "Current workflow checks no longer permit this action.", 409)
        with patch.object(self.service, "_revalidate_recovery", side_effect=failure):
            receipt = self.service.recover(self.designer, operation, review, True, abandon=True)
        self.assertEqual("abandoned", receipt["state"], receipt)

    def repair_preview(self) -> dict:
        return self.service.preview_transition(self.designer, None, "operation-repair", {"semantic_review_acknowledged": True}, operation_id="pending-1")

    def operation_row(self, operation: str):
        return self.service.store.connection.execute("SELECT state FROM operations WHERE operation_id = ?", (operation,)).fetchone()

    def test_the_repair_preview_binds_the_adopted_page(self) -> None:
        self.abandoned_operation()
        preview = self.repair_preview()
        self.assertEqual(["knowledge/wiki/status-board.md", "knowledge/wiki/log.md"], [write["path"] for write in preview["writes"]])
        self.assertIn(FEATURE, preview["source_map"], "the adopted page is a bound source of the repair")

    def test_an_adopted_page_edited_after_the_review_is_a_conflict_and_nothing_is_written(self) -> None:
        self.abandoned_operation()
        preview = self.repair_preview()
        review = self.review(self.designer, preview)
        board, log = self.read(BOARD), self.read("knowledge/wiki/log.md")
        self.put(FEATURE, self.read(FEATURE) + "\nA blocking question added after the review.\n")
        edited = self.read(FEATURE)
        self.assertEqual(
            "stale_approval_review",
            self.code(lambda: self.service.apply(self.designer, preview["preview_id"], "repair-1", review, True)),
        )
        # Reviewing the edited page again does not make this repair applicable: its preview is stale.
        fresh = self.review(self.designer, preview)
        self.assertEqual("stale_preview", self.code(lambda: self.service.apply(self.designer, preview["preview_id"], "repair-1", fresh, True)))
        self.assertEqual((edited, board, log), (self.read(FEATURE), self.read(BOARD), self.read("knowledge/wiki/log.md")))
        self.assertIsNone(self.operation_row("repair-1"))
        self.assertEqual("abandoned", self.operation_row("pending-1")[0])

    def test_the_recovery_of_an_interrupted_repair_rechecks_the_adopted_page(self) -> None:
        self.abandoned_operation()
        preview = self.repair_preview()
        self.crash_after_first_write(self.designer, preview, "repair-1")
        board = self.read(BOARD)
        self.put(FEATURE, self.read(FEATURE) + "\nA blocking question added after the crash.\n")
        receipt = self.service.apply(self.designer, preview["preview_id"], "repair-1")
        self.assertEqual("conflict", receipt["state"], receipt)
        self.assertTrue(any("recovery_source_changed" in str(item["reason"]) for item in receipt["conflicts"]), receipt["conflicts"])
        self.assertEqual(board, self.read(BOARD), "the recovery wrote nothing")

    def test_the_lint_of_the_repair_is_rechecked_when_it_is_recovered(self) -> None:
        self.abandoned_operation()
        preview = self.repair_preview()
        self.crash_after_first_write(self.designer, preview, "repair-1")
        board = self.read(BOARD)

        def diagnose(candidate):
            result = Mock()
            result.diagnostics = [WikiDiagnostic("feature-status-not-minimum", "error", str(candidate / FEATURE), "The status is not the minimum.")]
            return result

        with patch("prism_cli.wiki_lint.lint_wiki", side_effect=diagnose):
            receipt = self.service.apply(self.designer, preview["preview_id"], "repair-1")
        self.assertEqual("conflict", receipt["state"], receipt)
        self.assertTrue(any("repair_invalid" in str(item["reason"]) for item in receipt["conflicts"]), receipt["conflicts"])
        self.assertEqual(board, self.read(BOARD))


ASTRA_NOTES = """---
id: REL-999
---

## Delivery
| Item | App | Target | Version | Attempt | Outcome | Evidence | Basis |
|---|---|---|---|---|---|---|---|
| F-001 | backend | production | `build:backend#99` | release-1 | released | deployment: https://ci.example/deploy/99 | checked |
"""
NOTES_PATH = Path("knowledge/wiki/releases/notes.md")


def parsed(path: str, text: str) -> ReleaseRecord:
    return ReleaseRecord(parse_markdown_text(Path(path), text))


class UnvalidatedReleaseRecordTests(unittest.TestCase):
    """Finding 4 on the pure functions: a page that is not a valid record is no delivery, numbering or rollback authority."""

    def setUp(self) -> None:
        self.good = parsed(f"{RELEASES}/REL-001.md", record_page(1, [delivery("F-001", "backend")]))
        self.notes = parsed(str(NOTES_PATH), ASTRA_NOTES)

    def test_the_malformed_page_does_not_become_the_current_delivery(self) -> None:
        self.assertEqual("REL-999", self.notes.record_id)
        current = current_delivery([self.good, self.notes], "backend", "production")
        self.assertEqual("REL-001", current[0].record_id)
        self.assertIsNone(current_delivery([self.notes], "backend", "production"))

    def test_the_malformed_page_does_not_move_the_numbering(self) -> None:
        self.assertEqual(2, next_release_number([self.good, self.notes]))
        self.assertEqual(1, next_release_number([self.notes]))

    def test_the_malformed_page_is_not_a_rollback_target(self) -> None:
        rollback = parsed(f"{RELEASES}/REL-002.md", record_page(2, [delivery("F-001", "backend", outcome="rolled-back", attempt=None, version="build:backend#99")], rollback_of="REL-999", rollback="Rolled back."))
        rows = parse_record_rows(rollback.page.body)[0]
        records = [self.good, self.notes, rollback]
        problems = rollback_problems(rollback_of="REL-999", rows=rows, records=records, kinds=record_kinds(records))
        self.assertTrue(problems, "REL-999 is not a record that was delivered")

    def test_a_record_whose_target_is_invalid_is_invalid_too(self) -> None:
        failed_page = record_page(2, [delivery("F-001", "backend", outcome="failed", attempt=2)])
        untitled = parsed(f"{RELEASES}/REL-002.md", failed_page.replace("title: Release of F-001" + chr(10), ""))
        failed = parsed(f"{RELEASES}/REL-002.md", failed_page)
        retry = parsed(f"{RELEASES}/REL-003.md", record_page(3, [delivery("F-001", "backend", attempt=3)], retry_of="REL-002"))
        self.assertEqual([self.good, failed, retry], read_valid([self.good, failed, retry]), "the chain is valid when every record in it is")
        self.assertEqual([self.good], read_valid([self.good, untitled, retry]), "the retry names a record that is not valid")

    def test_the_directory_reader_keeps_the_valid_records_and_names_the_rest(self) -> None:
        from prism_cli.wiki_releases import invalid_release_records, read_all_release_records

        with tempfile.TemporaryDirectory() as directory:
            wiki = Path(directory)
            (wiki / "releases").mkdir()
            (wiki / "releases" / "REL-001.md").write_text(record_page(1, [delivery("F-001", "backend")]), encoding="utf-8")
            (wiki / "releases" / "notes.md").write_text(ASTRA_NOTES, encoding="utf-8")
            self.assertEqual(["REL-001"], [record.record_id for record in read_release_records(wiki)])
            self.assertEqual(["REL-001", "REL-999"], [record.record_id for record in read_all_release_records(wiki)])
            invalid = invalid_release_records(wiki)
            self.assertEqual(["notes.md"], [path.name for path in invalid])
            self.assertTrue(any("file name must be `REL-999.md`" in message for message in next(iter(invalid.values()))))

    def test_two_files_that_claim_one_id_are_both_invalid(self) -> None:
        twin = parsed(f"{RELEASES}/notes.md", record_page(1, [delivery("F-001", "backend")]))
        self.assertEqual([], read_valid([self.good, twin]))


def read_valid(records: list[ReleaseRecord]) -> list[ReleaseRecord]:
    from prism_cli.release_lint import validate_release_records

    return validate_release_records(records)[0]


class MalformedReleasePageBoardTests(ReleaseTests):
    """Finding 4 through the board and lint: the release action stays blocked until the page named in the refusal is fixed."""

    def test_a_malformed_page_blocks_release_done_and_lint_names_it(self) -> None:
        self.put(str(NOTES_PATH).replace("\\", "/"), ASTRA_NOTES)
        error = self.refused("release-done", self.release_changes(1), approver=self.owner)
        self.assertEqual(("release_record_invalid", 409), (error.code, error.status))
        self.assertIn("knowledge/wiki/releases/notes.md", error.message)
        self.assertEqual("knowledge/wiki/releases/notes.md", error.details["path"])
        named = [item for item in lint_wiki(self.root).diagnostics if item.code == "release-record-invalid" and item.path.endswith("notes.md")]
        self.assertTrue(named)
        # Fixing the page (here: removing it) opens the release again, with the next free number.
        (self.root / "knowledge/wiki/releases/notes.md").unlink()
        self.assertEqual("release-done", self.release()["action"])


class NextDayRecoveryTests(QaBoard):
    """Finding 6: a partial QA failure is recovered on the next day, against the operation's own preview day."""

    fail_changes = qa_fail.QaFailTests.fail_changes
    record_failure = qa_fail.QaFailTests.record_failure

    def test_a_partial_qa_fail_is_recovered_the_next_day(self) -> None:
        self.record_failure()
        preview = self.ready("qa-fail", self.fail_changes(["worker"], linked="BUG-001"))
        original = self.service._apply_write

        class Crash(Exception):
            pass

        def interrupted(write, **kwargs):
            if write["role"] == "status-board":
                raise Crash()
            return original(write, **kwargs)

        review = self.service.get_preview(self.quinn, preview["preview_id"])["approval"]["review_revision"]
        with patch.object(self.service, "_apply_write", side_effect=interrupted):
            with self.assertRaises(Crash):
                self.service.apply(self.quinn, preview["preview_id"], "pending-1", review, True)
        self.assertIn(f"### {date.today().isoformat()} - qa-fail", self.read("knowledge/wiki/features/F-001-document-review.md"))
        tomorrow = date.today() + timedelta(days=1)

        class Tomorrow(date):
            @classmethod
            def today(cls) -> "Tomorrow":
                return cls(tomorrow.year, tomorrow.month, tomorrow.day)

        with patch("prism_cli.board_service.date", Tomorrow):
            receipt = self.service.apply(self.quinn, preview["preview_id"], "pending-1")
        self.assertEqual("applied", receipt["state"], receipt)
        self.assertEqual(("in-dev", "dev"), self.status())
        self.assertEqual(date.today().isoformat(), preview["preview_date"], "the operation carries the day it was previewed")


API_CONTRACT = "knowledge/wiki/api-contracts/F-001.md"
API_CONTRACT_TEXT = (
    "---\nfeature-id: F-001\nversion: 1\nstatus: implemented\n---\n\n"
    "## Endpoints\n- `GET /api/v1/reviews/:reviewId/summary` returns the summary.\n\n"
    "## Data models\n```\nReviewSummary\n```\n\n## Authentication requirements\nBearer token.\n\n## Notes\nNone.\n"
)


class QaFailWithImplementedContractTests(QaBoard):
    """`qa-fail` of a feature whose API contract is `implemented` is accepted when the contract returns to `agreed` in the same operation."""

    fail_changes = qa_fail.QaFailTests.fail_changes
    record_failure = qa_fail.QaFailTests.record_failure

    def setUp(self) -> None:
        super().setUp()
        page = parse_markdown_text(Path("contract.md"), API_CONTRACT_TEXT)
        citation = contract_page_citation(page.frontmatter, page.body)
        self.put(API_CONTRACT, API_CONTRACT_TEXT)
        delivered = self.read(FEATURE_PAGE)
        for app in ("backend", "worker"):
            delivered = delivered.replace(f"| {app} | `build:{app}#1` | none |", f"| {app} | `build:{app}#1` | {citation} |", 1)
        self.put(FEATURE_PAGE, delivered)

    def test_the_contract_returns_to_agreed_with_the_apps_sent_back(self) -> None:
        self.record_failure()
        changes = self.fail_changes(["worker"], linked="BUG-001")
        # The Evidence history entry lists the contract among the pages the write invalidates.
        marker = "- Requirement/API invalidations: "
        content = changes[0]["content"]
        end = content.index(chr(10), content.index(marker))
        changes[0]["content"] = content[:end] + f", {API_CONTRACT}: implemented -> agreed" + content[end:]
        changes.append({"path": API_CONTRACT, "content": API_CONTRACT_TEXT.replace("status: implemented", "status: agreed")})
        preview = self.ready("qa-fail", changes)
        self.assertEqual("qa-fail", preview["action"])
        self.apply("qa-fail", changes)
        self.assertEqual(("in-dev", "dev"), self.status())
        self.assertIn("status: agreed", self.read(API_CONTRACT))

    def test_a_contract_that_stays_implemented_is_still_demanded_back(self) -> None:
        self.record_failure()
        error = self.refused("qa-fail", self.fail_changes(["worker"], linked="BUG-001"))
        self.assertEqual("lifecycle_write_scope", error.code)
        self.assertIn(API_CONTRACT, error.message)


class NextDayBugRecoveryTests(BugBoard):
    """Finding 6 for a bug: a partly applied `bug-reopen` is recovered the next day against its preview day."""

    def test_a_partial_bug_reopen_is_recovered_the_next_day(self) -> None:
        self.plant("closed", fix=bug_fix(), verification=bug_verification(), extra={"close-reason": "wont-fix: The report was withdrawn."})
        archived = [("Fix", fix_row("worker", "build:worker#2")), ("Verification", verification_row("worker", "build:worker#2"))]
        reopened = self.bug("open", history="\n" + self.entry("bug-reopen", archived))
        preview = self.ready("bug-update", [{"path": BUG, "content": reopened}])
        self.assertEqual("bug-reopen", preview["action"])
        original = self.service._apply_write

        class Crash(Exception):
            pass

        def interrupted(write, **kwargs):
            if write["role"] == "status-board":
                raise Crash()
            return original(write, **kwargs)

        review = self.service.get_preview(self.pat, preview["preview_id"])["approval"]["review_revision"]
        with patch.object(self.service, "_apply_write", side_effect=interrupted):
            with self.assertRaises(Crash):
                self.service.apply(self.pat, preview["preview_id"], "pending-1", review, True)
        self.assertIn(f"### {date.today().isoformat()} - bug-reopen", self.read(BUG))
        tomorrow = date.today() + timedelta(days=1)

        class Tomorrow(date):
            @classmethod
            def today(cls) -> "Tomorrow":
                return cls(tomorrow.year, tomorrow.month, tomorrow.day)

        with patch("prism_cli.board_service.date", Tomorrow):
            receipt = self.service.apply(self.pat, preview["preview_id"], "pending-1")
        self.assertEqual("applied", receipt["state"], receipt)
        self.assertEqual(set(), self.errors())


if __name__ == "__main__":
    unittest.main()
