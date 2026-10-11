"""Denied cases of CONTRACTS 10.3 that no other module asserts, run on the Lumen Library workspace.

Each class fast-forwards the case to the state its guard needs by taking the proposals of `tests/lumen_steps.py` through the board,
then proposes the write the contract refuses and asserts the error code. The cases are numbered as in the contract.
"""

from __future__ import annotations

import re
import unittest

from prism_cli.board_service import BoardError
from tests import real_temp  # noqa: F401
from tests.lumen_board import LumenBoard
from tests.lumen_library import (
    CATALOG,
    CATALOG_BUILD,
    FEATURE_PATH,
    READER,
    READER_BUILD,
    pending_release_row,
    qa_row,
    ref_2,
    ref_3,
    set_frontmatter,
    table_rows,
    with_rows,
)
from tests.lumen_steps import SEQUENCE, LumenSteps, Proposal, change

ANSWER = "The book page shows how many copies are free."


class GapCase(LumenBoard, LumenSteps):
    def advance(self, last: int) -> None:
        """Take the case through step `last`. Steps 1 to 9 never touch a QA failure."""

        for number, names in SEQUENCE:
            if number > last:
                return
            for name in names:
                self.apply_proposal(getattr(self, name)())

    def ask(self) -> str:
        """Add an open question for the PO after the last one and return its row."""

        page = self.feature_text()
        rows = [line for line in page.splitlines() if re.match(r"\| \d+ \|", line)]
        question = f"| {len(rows) + 1} | Should readers see how many copies are free? | po | open |"
        self.step("ask", [change(FEATURE_PATH, page.replace(rows[-1], rows[-1] + "\n" + question))])
        return question

    def clarified(self, question: str, mutate) -> list[dict[str, str]]:
        """The page with `question` answered and `mutate` applied to it."""

        page = self.feature_text().replace(question, question.replace("open", "resolved: " + ANSWER))
        return [change(FEATURE_PATH, mutate(page))]

    def refusal(self, skill: str, changes: list[dict[str, str]]) -> BoardError:
        with self.assertRaises(BoardError) as caught:
            self.propose(skill, changes)
        return caught.exception

    def qa_pass_without_a_failure(self) -> None:
        """Pass both apps at once after step 9, the short way to `ready-for-release`."""

        rows = [
            *table_rows(self.feature_text(), "QA verification"),
            qa_row(READER, [ref_2()], f"`{READER_BUILD}`", attempt=1),
            qa_row(f"integration:{CATALOG}+{READER}", [ref_3()], f"{CATALOG}=`{CATALOG_BUILD}`; {READER}=`{READER_BUILD}`", attempt=1),
        ]
        page = with_rows(self.feature_text(), "QA verification", "qa", rows)
        page = with_rows(page, "Release", "release", [pending_release_row(CATALOG, CATALOG_BUILD), pending_release_row(READER, READER_BUILD)])
        page = set_frontmatter(page, {"status": "ready-for-release", "owner": "release"})
        self.apply_proposal(Proposal("qa-pass", "qa-pass", [change(FEATURE_PATH, page)], "Quinn"))


class CriteriaMarkTests(GapCase):
    """Case 29: an ID is never reused, and the high-water mark never drops."""

    def specified_without_the_last_criterion(self) -> str:
        self.apply_proposal(self.ingest_feature())
        page = self.feature_text()
        line = next(item for item in page.splitlines() if item.startswith("- [ ] AC-3 "))
        # AC-3 leaves the page while the mark stays at 3, and the feature is specified without it.
        page = set_frontmatter(page.replace(line + "\n", ""), {"status": "specified", "owner": "po"})
        self.step("po-specify", [change(FEATURE_PATH, page)], "Pat")
        return self.ask()

    def test_the_id_of_a_removed_criterion_is_not_assigned_again(self) -> None:
        question = self.specified_without_the_last_criterion()
        added = f"- [ ] AC-3 [{CATALOG}, {READER}] {ANSWER}"

        def reuse(page: str) -> str:
            return page.replace("\n\n## Open questions", "\n" + added + "\n\n## Open questions", 1)

        error = self.refusal("po-clarify", self.clarified(question, reuse))
        self.assertEqual(("criterion_id_reused", 409), (error.code, error.status))
        # AC-4 is the next number after the mark of 3.
        fresh = self.clarified(question, lambda page: set_frontmatter(reuse(page).replace("AC-3 [", "AC-4 ["), {"criteria-high-water": 4}))
        self.assertTrue(self.propose("po-clarify", fresh)["applicable"])

    def test_the_high_water_mark_never_decreases(self) -> None:
        question = self.specified_without_the_last_criterion()
        added = f"- [ ] AC-4 [{CATALOG}, {READER}] {ANSWER}"

        def lowered(page: str) -> str:
            return set_frontmatter(page.replace("\n\n## Open questions", "\n" + added + "\n\n## Open questions", 1), {"criteria-high-water": 2})

        error = self.refusal("po-clarify", self.clarified(question, lowered))
        self.assertEqual(("criteria_high_water_decreased", 409), (error.code, error.status))


class StageGuardTests(GapCase):
    """Cases 23 and 42: the stage of the feature and of its apps decides what a clarification or a skill may change."""

    def test_a_criterion_edit_is_refused_while_an_affected_app_is_ready_for_release(self) -> None:
        self.advance(9)
        self.qa_pass_without_a_failure()
        self.assertEqual(("ready-for-release", "release"), (self.feature()[0]["status"], self.feature()[0]["owner"]))
        question = self.ask()
        edited = self.clarified(question, lambda page: page.replace("A reader can reserve an available copy from the book page.", ANSWER))
        error = self.refusal("po-clarify", edited)
        self.assertEqual(("clarify_stage_unavailable", 409), (error.code, error.status))
        self.assertIn(READER, error.message)

    def test_an_app_scope_edit_is_refused_from_ready_for_dev_on(self) -> None:
        self.advance(5)
        question = self.ask()
        edited = self.clarified(question, lambda page: page.replace("Offer the reservation on the book page.", ANSWER))
        error = self.refusal("po-clarify", edited)
        self.assertEqual(("clarify_stage_unavailable", 409), (error.code, error.status))

    def test_an_action_from_the_wrong_source_pair_is_refused(self) -> None:
        self.advance(6)
        self.assertEqual(("in-dev", "dev"), (self.feature()[0]["status"], self.feature()[0]["owner"]))
        # `design-handoff` moves a feature that is in design to `ready-for-dev` + `dev`; this one is already in development.
        page = set_frontmatter(self.feature_text(), {"status": "ready-for-dev", "owner": "dev"})
        error = self.refusal("design-handoff", [change(FEATURE_PATH, page)])
        # A feature skill names its exact transition, so the board answers with the transition the skill performs; the code
        # `unsupported_source_pair` of the contract is the answer of the bug, release and reopen actions.
        self.assertEqual(("lifecycle_action_required", 409), (error.code, error.status))
        self.assertIn("`ready-for-design`", error.message)
        # A human-direct action is not applicable from the wrong source: the preview names the status it needs.
        preview = self.service.preview_transition(self.people["Pat"], "F-001", "po-handoff", {"semantic_review_acknowledged": True})
        self.assertFalse(preview["applicable"])
        self.assertIn("unsupported-source-stage", {item["code"] for item in preview["checks"]})


if __name__ == "__main__":
    unittest.main()
