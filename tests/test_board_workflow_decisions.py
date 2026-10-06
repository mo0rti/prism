"""Workflow decisions on the connected board: raw intake, dev-clarify and dev-done evidence."""

from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

import yaml

from prism_cli.board_service import BoardError, BoardService, _parse_markdown
from prism_cli.wiki_lint import lint_wiki
from prism_cli.wiki_transitions import build_transition_preflight
from prism_cli.workflow_install import apply_install, plan_install
from tests.core_workflow_fixture import FEATURE_PATH, INTAKE_ITEM, create_core_workflow_fixture
from tests.test_board_service import (
    _journey_business_rule_page,
    _journey_feature_page,
    _journey_persona_page,
    _journey_requirement_page,
    _read_revisions,
    _replace_body_section,
    _replace_body_section_text,
    _set_feature_stage,
    _set_requirement_status,
    _unquote_yaml_date_fields,
    _write_index_rows,
)
from tests.test_core_workflow_fixture import CHECK_DATE
from tests import real_temp  # noqa: F401


FEATURE = FEATURE_PATH.as_posix()
REQUIREMENT = "knowledge/wiki/app-requirements/F-001-backend.md"
DESIGN = "knowledge/wiki/design/F-001-document-review.md"
PO_QUESTION = "| 1 | Which details should the summary emphasize? | po | open |"
DEV_QUESTION = "| 2 | Is there a limit on the number of comments in one summary? | dev | open |"
DESIGNER_QUESTION = "| 3 | Where should the next steps appear? | designer | open |"
DEV_ANSWER = "At most 200 comments are exported; the rest are summarized as a count."
EVIDENCE_ROW = "| backend | Pull request 42 merged as 3f9c2ab | CI run 1187: 31 tests passed | Version 1.4.0 deployed |"
EVIDENCE_TABLE = f"| App | Implementation | Tests | Release |\n|---|---|---|---|\n{EVIDENCE_ROW}"
EMPTY_EVIDENCE = "| App | Implementation | Tests | Release |\n|---|---|---|---|"


class _BoardWorkspace(unittest.TestCase):
    """A disposable adopted workspace with one agent grant."""

    def setUp(self) -> None:
        clock = Mock(wraps=date)
        clock.today.return_value = CHECK_DATE
        for module in ("board_service", "wiki_lint", "wiki_transitions"):
            clock_patch = patch(f"prism_cli.{module}.date", clock)
            clock_patch.start()
            self.addCleanup(clock_patch.stop)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = create_core_workflow_fixture(Path(temporary.name) / "workspace")
        self.assertEqual("applied", apply_install(self.root, plan_install(self.root, name="Document review", apps=["backend"]))["status"])

    def start(self) -> None:
        self.service = BoardService(self.root).start()
        self.addCleanup(self.service.close)
        self.agent = self.service.authenticate(self.service.create_participant("Workflow agent", "agent", True)["token"])
        self.human = self.service.authenticate(self.service.create_participant("Workflow owner", "human", True)["token"])

    def write(self, relative: str, content: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode("utf-8"))

    def read(self, relative: str) -> str:
        return self.service._read_text(self.root / relative)

    def preview(self, skill: str, changes: list[dict[str, str]], moves: list[dict[str, str]] | None = None) -> dict:
        return self.service.preview_skill(self.agent, skill, changes, moves, _read_revisions(self.service, self.agent, skill, changes, moves))

    def rejection(self, skill: str, changes: list[dict[str, str]]) -> BoardError:
        with self.assertRaises(BoardError) as caught:
            self.preview(skill, changes)
        return caught.exception

    def apply(self, preview: dict) -> dict:
        self.assertTrue(preview["applicable"], preview["blockers"])
        receipt = self.service.apply(self.agent, preview["preview_id"], str(uuid4()))
        self.assertEqual("applied", receipt["state"], receipt)
        return receipt


class RawIntakeTests(_BoardWorkspace):
    """D12: po-intake writes raw features and po-specify completes them."""

    PENDING = INTAKE_ITEM.parent.as_posix()
    PROCESSED = PENDING.replace("pending", "processed", 1)
    PERSONA = "knowledge/wiki/personas/P-001-reviewer.md"
    RULE = "knowledge/wiki/business-rules/BR-001-review-record.md"
    MANIFEST = PROCESSED + "/MANIFEST.md"

    def setUp(self) -> None:
        super().setUp()
        self.start()

    def feature_page(self, status: str, owner: str = "po", *, blank_trailing: bool = False) -> str:
        page = _unquote_yaml_date_fields(
            _journey_feature_page("F-001", "Document review", status, owner, [self.PROCESSED + "/brief.md"], [PO_QUESTION])
        )
        if blank_trailing:
            for heading in ("Design", "Related features", "Board review summary", "Post-ship notes"):
                page = _replace_body_section(self.service, page, heading, "")
        return page

    def intake_changes(self, status: str, *, blank_trailing: bool = False) -> list[dict[str, str]]:
        manifest = (
            "# Processed intake\n\n"
            f"- {FEATURE} (F-001)\n- {self.PERSONA} (P-001)\n- {self.RULE} (BR-001)\n"
        )
        return [
            {"path": FEATURE, "content": self.feature_page(status, blank_trailing=blank_trailing)},
            {"path": self.PERSONA, "content": _unquote_yaml_date_fields(_journey_persona_page())},
            {"path": self.RULE, "content": _journey_business_rule_page()},
            {"path": self.MANIFEST, "content": manifest},
        ]

    def intake(self, status: str, *, blank_trailing: bool = False) -> dict:
        changes = self.intake_changes(status, blank_trailing=blank_trailing)
        moves = [{"source": self.PENDING, "destination": self.PROCESSED}]
        return self.preview("po-intake", changes, moves)

    def test_intake_creates_a_raw_feature_that_lint_and_preflight_accept(self) -> None:
        preview = self.intake("raw", blank_trailing=True)
        self.assertEqual("ready", preview["classification"], preview["checks"])
        self.apply(preview)

        frontmatter, _body = _parse_markdown(self.read(FEATURE))
        self.assertEqual(("raw", "po"), (frontmatter["status"], frontmatter["owner"]))
        self.assertIn("| F-001 | Document review | raw | po |", self.read("knowledge/wiki/index.md"))
        self.assertEqual(0, lint_wiki(self.root).error_count)
        specify = build_transition_preflight(self.root, "F-001", action="po-specify")["facts"]["transition"]
        self.assertEqual(("po-specify", "raw", "specified", "ready"), (specify["action"], specify["source_status"], specify["target_status"], specify["classification"]))

    def test_intake_rejects_a_specified_feature_and_names_the_fix(self) -> None:
        for status, owner in (("specified", "po"), ("ready-for-design", "designer")):
            with self.subTest(status=status):
                changes = self.intake_changes(status)
                changes[0]["content"] = self.feature_page(status, owner)
                with self.assertRaises(BoardError) as caught:
                    self.preview("po-intake", changes, [{"source": self.PENDING, "destination": self.PROCESSED}])
                error = caught.exception
                self.assertEqual(("invalid_intake_feature", 409), (error.code, error.status))
                self.assertIn("`raw` + `po`", error.message)
                self.assertIn("po-specify", error.message)
                self.assertEqual(
                    {"path": FEATURE, "status": status, "owner": owner, "expected_status": "raw", "expected_owner": "po"},
                    error.details,
                )
        self.assertFalse((self.root / FEATURE).exists())

    def test_a_path_segment_windows_cannot_hold_is_rejected_at_preview_and_nothing_is_written(self) -> None:
        name = FEATURE.rsplit("/", 1)[1]
        directory = FEATURE.rsplit("/", 1)[0]
        paths = {
            "colon (alternate data stream)": (f"{directory}/{name}:stream.md", ":"),
            "less-than": (f"{directory}/F-001<x.md", "<"),
            "greater-than": (f"{directory}/F-001>x.md", ">"),
            "double quote": (f'{directory}/F-001"x.md', '"'),
            "pipe": (f"{directory}/F-001|x.md", "|"),
            "question mark": (f"{directory}/F-001?x.md", "?"),
            "asterisk": (f"{directory}/F-001*x.md", "*"),
            "control character": (f"{directory}/F-001\x07x.md", "control character"),
            "trailing dot": (f"{directory}/F-001-document-review.", "ends in a dot"),
            "trailing space in a folder": (f"{directory} /{name}", "ends in a dot or a space"),
            "device name": (f"{directory}/CON", "reserved device name"),
            "device name, lower case, with an extension": (f"{directory}/nul.md", "reserved device name"),
            "numbered device name": (f"{directory}/Com1.txt.md", "reserved device name"),
            "last numbered device name": (f"{directory}/LPT9.md", "reserved device name"),
        }
        for label, (bad, reason) in paths.items():
            with self.subTest(case=label):
                changes = self.intake_changes("raw", blank_trailing=True)
                changes[0]["path"] = bad
                changes[3]["content"] = changes[3]["content"].replace(FEATURE, bad)
                with self.assertRaises(BoardError) as caught:
                    self.preview("po-intake", changes, [{"source": self.PENDING, "destination": self.PROCESSED}])
                error = caught.exception
                self.assertEqual(("invalid_path", 400), (error.code, error.status))
                self.assertIn(reason, error.message + error.details["reason"])
                self.assertIn("every operating system", error.message)
                self.assertNotIn("\x07", error.message + json.dumps(error.details))
                self.assertLessEqual(len(error.details["segment"]), 80)
                self.assertTrue((self.root / self.PENDING).is_dir())
                self.assertFalse((self.root / self.PROCESSED).exists())
                self.assertFalse((self.root / FEATURE).exists())
                self.assertEqual([], self.service.discover(self.agent).get("pending_operations"))

    def test_a_folder_move_to_a_segment_windows_cannot_hold_is_rejected_at_preview(self) -> None:
        for destination in (self.PROCESSED + ":stream", self.PROCESSED + ".", "knowledge/intake/processed/aux"):
            with self.subTest(destination=destination), self.assertRaises(BoardError) as caught:
                self.preview("po-intake", self.intake_changes("raw", blank_trailing=True), [{"source": self.PENDING, "destination": destination}])
            self.assertEqual("invalid_path", caught.exception.code)
        self.assertTrue((self.root / self.PENDING).is_dir())

    def test_portable_names_are_still_accepted(self) -> None:
        for name in ("F-001-document-review.md", "notes v1.2.md", "CONSOLE.md", "console-1.md", "COM10.md", "auxiliary", "a.b.c.md", "Résumé.md", "_FORMAT.md"):
            with self.subTest(name=name):
                self.assertEqual(f"knowledge/wiki/{name}", self.service._relative_path(f"knowledge/wiki/{name}"))

    def test_po_specify_names_the_empty_sections_of_a_fresh_raw_feature_and_then_completes_it(self) -> None:
        self.apply(self.intake("raw", blank_trailing=True))
        raw = self.read(FEATURE)
        specified = _set_feature_stage(raw, "specified", "po", self.service)

        error = self.rejection("po-specify", [{"path": FEATURE, "content": specified}])
        self.assertEqual(("required_section_missing", 409), (error.code, error.status))
        self.assertEqual(["Board review summary", "Design", "Post-ship notes", "Related features"], error.details["sections"])
        self.assertEqual(FEATURE, error.details["path"])
        for hint in ("Not started.", "None identified.", "Not shipped yet."):
            self.assertIn(hint, error.message)

        completed = specified
        for heading, line in (
            ("Design", "Not started."),
            ("Related features", "None identified."),
            ("Board review summary", "Not reviewed yet."),
            ("Post-ship notes", "Not shipped yet."),
        ):
            completed = _replace_body_section(self.service, completed, heading, line)
        preview = self.preview("po-specify", [{"path": FEATURE, "content": completed}])
        self.assertEqual(("po-specify", "ready"), (preview["action"], preview["classification"]))
        self.apply(preview)

        frontmatter, _body = _parse_markdown(self.read(FEATURE))
        self.assertEqual(("specified", "po"), (frontmatter["status"], frontmatter["owner"]))
        self.assertIn("| F-001 | Document review | specified | po |", self.read("knowledge/wiki/index.md"))
        self.assertEqual(0, lint_wiki(self.root).error_count)

    def test_po_specify_keeps_a_complete_raw_body_and_an_existing_specified_feature_stays_valid(self) -> None:
        self.apply(self.intake("raw"))
        raw = self.read(FEATURE)
        specified = _set_feature_stage(raw, "specified", "po", self.service)
        self.assertEqual(_parse_markdown(raw)[1], _parse_markdown(specified)[1])
        self.apply(self.preview("po-specify", [{"path": FEATURE, "content": specified}]))

        # A specified feature keeps working as before: po-clarify answers its PO
        # question and the PO handoff then becomes ready.
        current = self.read(FEATURE)
        answered = current.replace(PO_QUESTION, "| 1 | Which details should the summary emphasize? | po | resolved: Key points and follow-up. |")
        self.apply(self.preview("po-clarify", [{"path": FEATURE, "content": answered}]))
        self.assertEqual(0, lint_wiki(self.root).error_count)
        handoff = build_transition_preflight(self.root, "F-001", action="po-handoff")["facts"]["transition"]
        self.assertEqual(("specified", "ready"), (handoff["source_status"], handoff["classification"]))


class DevClarifyTests(_BoardWorkspace):
    """D13: dev-clarify answers dev-owned questions."""

    def setUp(self) -> None:
        super().setUp()
        self.set_stage("in-dev", "dev")
        self.start()

    def set_stage(self, status: str, owner: str, questions: list[str] | None = None, requirement: bool = True) -> None:
        questions = questions or [PO_QUESTION.replace("| po | open |", "| po | resolved: Key points and follow-up. |"), DEV_QUESTION, DESIGNER_QUESTION]
        page = _unquote_yaml_date_fields(
            _journey_feature_page("F-001", "Document review", status, owner, ["knowledge/intake/processed/document-review-brief"], questions)
        )
        self.write(FEATURE, page)
        _write_index_rows(self.root, [("F-001", "Document review", status, owner)])
        if requirement:
            self.write(REQUIREMENT, _journey_requirement_page("in-progress"))

    def answered(self, content: str, answer: str = DEV_ANSWER) -> str:
        return content.replace(DEV_QUESTION, f"| 2 | Is there a limit on the number of comments in one summary? | dev | resolved: {answer} |")

    def proposal(self, *, scope: str | None = DEV_ANSWER, requirement: str | None = DEV_ANSWER) -> list[dict[str, str]]:
        feature = self.answered(self.read(FEATURE))
        if scope is not None:
            feature = _replace_body_section(self.service, feature, "App scope", f"- **backend**: Store the review summary and recorded outcome. {scope}")
        changes = [{"path": FEATURE, "content": feature}]
        if requirement is not None:
            page = _replace_body_section(
                self.service, self.read(REQUIREMENT), "Technical constraints", f"Use the existing workspace storage. {requirement}"
            )
            changes.append({"path": REQUIREMENT, "content": page})
        return changes

    def test_the_skill_is_discoverable_as_an_agent_write_with_its_scopes(self) -> None:
        listed = {item["name"]: item for item in self.service.list_skills(self.agent)["skills"]}["dev-clarify"]
        self.assertTrue(listed["write_supported"])
        self.assertEqual(["knowledge/wiki/features/*.md", "knowledge/wiki/app-requirements/*.md"], listed["write_scopes"])
        self.assertEqual(["agent"], listed["participant_kinds"])
        self.assertEqual({"preview_skill": ["agent"]}, listed["write_tools"])
        self.assertTrue(any("Resolves only dev-owned open questions" in text for text in listed["limitations"]))
        self.assertTrue(any("full text of at least one answer" in text for text in listed["limitations"]))
        self.assertIn("dev-clarify", self.service.discover(self.agent)["capability"]["supported_write_skills"])
        skill = self.service.get_skill(self.agent, "dev-clarify")["skill"]
        self.assertIn("$dev-clarify", skill["instructions"])
        self.assertIn("knowledge/wiki/app-requirements/_FORMAT.md", {item["path"] for item in skill["references"]})

    def test_a_dev_answer_updates_the_feature_and_the_linked_requirement_through_one_preview(self) -> None:
        preview = self.preview("dev-clarify", self.proposal())
        self.assertEqual(("ready", True, None), (preview["classification"], preview["applicable"], preview["action"]))
        self.assertEqual({FEATURE, REQUIREMENT, "knowledge/wiki/log.md"}, {item["path"] for item in preview["writes"]})
        before_index = self.read("knowledge/wiki/index.md")
        self.apply(preview)

        frontmatter, body = _parse_markdown(self.read(FEATURE))
        self.assertEqual(("in-dev", "dev"), (frontmatter["status"], frontmatter["owner"]))
        self.assertIn(f"dev | resolved: {DEV_ANSWER} |", body)
        self.assertIn(DEV_ANSWER, self.read(REQUIREMENT))
        self.assertEqual("in-progress", _parse_markdown(self.read(REQUIREMENT))[0]["status"])
        self.assertEqual(before_index, self.read("knowledge/wiki/index.md"))
        self.assertIn("dev-clarify", self.read("knowledge/wiki/log.md"))
        # The designer's question stays open and the dev question no longer blocks dev-done.
        self.assertIn("designer | open", body)

    def test_a_feature_only_answer_is_accepted(self) -> None:
        feature = self.answered(self.read(FEATURE))
        preview = self.preview("dev-clarify", [{"path": FEATURE, "content": feature}])
        self.assertEqual("ready", preview["classification"])
        self.apply(preview)
        self.assertIn(f"resolved: {DEV_ANSWER}", self.read(FEATURE))

    def test_questions_owned_by_other_roles_are_rejected(self) -> None:
        for number, question, owner in ((1, PO_QUESTION, "po"), (3, DESIGNER_QUESTION, "designer")):
            with self.subTest(owner=owner):
                self.set_stage("in-dev", "dev", [PO_QUESTION, DEV_QUESTION, DESIGNER_QUESTION])
                current = self.read(FEATURE)
                text = question.split("|")[2].strip()
                changed = current.replace(question, f"| {number} | {text} | {owner} | resolved: An answer from the wrong role. |")
                error = self.rejection("dev-clarify", [{"path": FEATURE, "content": changed}])
                self.assertEqual(("question_owner_mismatch", 409), (error.code, error.status))
                self.assertIn(f"cannot resolve {owner}-owned question {number}", error.message)

    def test_a_proposal_that_resolves_no_dev_question_is_rejected(self) -> None:
        feature = _replace_body_section(self.service, self.read(FEATURE), "App scope", "- **backend**: Store it somewhere else.")
        error = self.rejection("dev-clarify", [{"path": FEATURE, "content": feature}])
        self.assertEqual("answer_required", error.code)

    def test_a_paraphrase_of_the_answer_in_a_requirement_section_is_rejected_with_the_answer_to_paste(self) -> None:
        error = self.rejection("dev-clarify", self.proposal(scope=None, requirement="Only some comments are exported."))
        self.assertEqual(("requirement_answer_unlinked", 409), (error.code, error.status))
        self.assertEqual(REQUIREMENT, error.details["path"])
        self.assertEqual("Technical constraints", error.details["section"])
        self.assertEqual(["2"], error.details["resolved_questions"])
        self.assertTrue(error.details["resolved_answers"]["2"].startswith("At most 200 comments"))
        self.assertIn("dev-owned question(s) 2", error.message)
        self.assertIn("verbatim", error.message)

    def test_a_paraphrase_in_a_feature_section_is_rejected(self) -> None:
        error = self.rejection("dev-clarify", self.proposal(scope="Export is capped.", requirement=None))
        self.assertEqual(("clarify_answer_unlinked", 409), (error.code, error.status))
        self.assertEqual("App scope", error.details["section"])
        self.assertIn("dev-owned question(s) 2", error.message)

    def test_an_answer_is_matched_as_whole_words_not_inside_other_words(self) -> None:
        feature = self.answered(self.read(FEATURE), answer="no")
        for text in (
            "Any reviewer can delete any document without notice.",
            "The limit is not stated; ask who may know it.",
            "Nothing is exported, and nobody noticed.",
        ):
            with self.subTest(text=text):
                changed = _replace_body_section(self.service, feature, "Acceptance criteria", f"- [ ] {text}")
                error = self.rejection("dev-clarify", [{"path": FEATURE, "content": changed}])
                self.assertEqual(("clarify_answer_unlinked", 409), (error.code, error.status))
                self.assertEqual("Acceptance criteria", error.details["section"])
        for text in ("No.", "Is a limit needed? NO, none.", "The answer was no\nfor now.", "(no)"):
            with self.subTest(accepted=text):
                changed = _replace_body_section(self.service, feature, "Acceptance criteria", f"- [ ] {text}")
                self.assertEqual("ready", self.preview("dev-clarify", [{"path": FEATURE, "content": changed}])["classification"])

    def test_an_answer_with_punctuation_at_its_edges_still_matches(self) -> None:
        answer = "$5 per export (max)"
        feature = self.answered(self.read(FEATURE), answer=answer)
        changed = _replace_body_section(self.service, feature, "App scope", f"- **backend**: The fee is {answer}.")
        self.assertEqual("ready", self.preview("dev-clarify", [{"path": FEATURE, "content": changed}])["classification"])
        glued = _replace_body_section(self.service, feature, "App scope", f"- **backend**: The fee is {answer}s.")
        self.assertEqual("clarify_answer_unlinked", self.rejection("dev-clarify", [{"path": FEATURE, "content": glued}]).code)

    def test_case_and_spacing_of_the_answer_do_not_matter(self) -> None:
        loose = DEV_ANSWER.upper().replace(" ", "  ")
        preview = self.preview("dev-clarify", self.proposal(scope=loose, requirement=loose))
        self.assertEqual("ready", preview["classification"])

    def test_a_requirement_page_with_no_changed_section_is_rejected(self) -> None:
        changes = [{"path": FEATURE, "content": self.answered(self.read(FEATURE))}, {"path": REQUIREMENT, "content": self.read(REQUIREMENT)}]
        error = self.rejection("dev-clarify", changes)
        self.assertEqual("requirement_answer_unlinked", error.code)
        self.assertIn("changes no requirement section", error.message)

    def test_requirement_identity_status_and_other_sections_are_protected(self) -> None:
        changes = self.proposal(scope=None)
        page = changes[1]["content"]

        status = [changes[0], {"path": REQUIREMENT, "content": _set_requirement_status(page, "done")}]
        error = self.rejection("dev-clarify", status)
        self.assertEqual(("requirement_frontmatter_change", 409), (error.code, error.status))
        self.assertEqual({"path": REQUIREMENT, "fields": ["status"]}, error.details)

        dependencies = _replace_body_section(self.service, page, "Dependencies", f"Waits for F-009. {DEV_ANSWER}")
        error = self.rejection("dev-clarify", [changes[0], {"path": REQUIREMENT, "content": dependencies}])
        self.assertEqual(("requirement_clarify_scope_exceeded", 409), (error.code, error.status))
        self.assertIn("What to build", error.message)
        self.assertEqual({"sections": ["Dependencies"]}, error.details)
        self.assertIn("changes section(s) `Dependencies`", error.message)

    def test_feature_status_owner_and_other_sections_are_protected(self) -> None:
        feature = self.answered(self.read(FEATURE))
        error = self.rejection("dev-clarify", [{"path": FEATURE, "content": _set_feature_stage(feature, "done", "none", self.service)}])
        self.assertEqual("lifecycle_action_required", error.code)
        error = self.rejection("dev-clarify", [{"path": FEATURE, "content": feature.replace("title: Document review", "title: Renamed", 1)}])
        self.assertEqual(("clarify_frontmatter_change", 409), (error.code, error.status))
        self.assertEqual({"path": FEATURE, "fields": ["title"]}, error.details)

        summary = _replace_body_section(self.service, feature, "Summary", f"A new summary. {DEV_ANSWER}")
        error = self.rejection("dev-clarify", [{"path": FEATURE, "content": summary}])
        self.assertEqual(("clarify_scope_exceeded", 409), (error.code, error.status))
        self.assertIn("Acceptance criteria, App scope and API surface", error.message)
        self.assertEqual({"sections": ["Summary"]}, error.details)

    def test_it_cannot_create_or_write_other_page_types(self) -> None:
        feature = {"path": FEATURE, "content": self.answered(self.read(FEATURE))}
        pages = {
            DESIGN: "---\nfeature-id: F-001\ntitle: Review\ndate: 2026-09-22\nfigma: not applicable\n---\n\n## Summary\nx\n",
            "knowledge/wiki/api-contracts/F-001.md": "---\nfeature-id: F-001\nversion: 1\nstatus: draft\n---\n\n## Endpoints\nx\n",
        }
        for path, content in pages.items():
            with self.subTest(path=path):
                error = self.rejection("dev-clarify", [feature, {"path": path, "content": content}])
                self.assertEqual(("write_path_unavailable", 403), (error.code, error.status))
        changes = self.proposal(scope=None)
        (self.root / REQUIREMENT).unlink()
        error = self.rejection("dev-clarify", changes)
        self.assertEqual(("requirement_page_unavailable", 409), (error.code, error.status))

    def test_it_works_before_dev_and_not_on_a_done_feature(self) -> None:
        for status, owner in (("raw", "po"), ("specified", "po"), ("ready-for-design", "designer"), ("in-design", "designer"), ("ready-for-dev", "dev"), ("in-dev", "dev")):
            with self.subTest(status=status):
                self.set_stage(status, owner, requirement=False)
                (self.root / REQUIREMENT).unlink(missing_ok=True)
                feature = self.answered(self.read(FEATURE))
                self.assertEqual("ready", self.preview("dev-clarify", [{"path": FEATURE, "content": feature}])["classification"])
        self.set_stage("done", "none", requirement=False)
        error = self.rejection("dev-clarify", [{"path": FEATURE, "content": self.answered(self.read(FEATURE))}])
        self.assertEqual(("clarify_stage_unavailable", 409), (error.code, error.status))
        self.assertEqual({"path": FEATURE, "status": "done"}, error.details)
        self.assertIn("feature-reopen", error.message)

    def test_the_answer_unblocks_the_dev_owned_question_check(self) -> None:
        before = build_transition_preflight(self.root, "F-001", action="dev-done")["facts"]["transition"]
        blocked = next(item for item in before["checks"] if item["code"] == "open-questions")
        self.assertEqual("blocked", blocked["status"])
        self.assertIn("questions 2, 3", blocked["message"])
        self.apply(self.preview("dev-clarify", self.proposal()))
        after = build_transition_preflight(self.root, "F-001", action="dev-done")["facts"]["transition"]
        open_questions = next(item for item in after["checks"] if item["code"] == "open-questions")
        self.assertEqual("blocked", open_questions["status"])
        self.assertIn("question 3", open_questions["message"])
        self.assertNotIn("2", open_questions["message"])


class _DevDoneWorkspace(_BoardWorkspace):
    """F-001 is in-dev on the backend, with an in-progress requirement and no delivery evidence."""

    def setUp(self) -> None:
        super().setUp()
        page = _unquote_yaml_date_fields(
            _journey_feature_page("F-001", "Document review", "in-dev", "dev", ["knowledge/intake/processed/document-review-brief"], [PO_QUESTION.replace("| po | open |", "| po | resolved: Key points. |")])
        )
        self.write(FEATURE, page)
        self.write(REQUIREMENT, _journey_requirement_page("in-progress"))
        _write_index_rows(self.root, [("F-001", "Document review", "in-dev", "dev")])
        self.start()


class DevDoneEvidenceTests(_DevDoneWorkspace):
    """D14: dev-done takes the delivery evidence in its proposal."""

    def done(self, evidence: str | None) -> list[dict[str, str]]:
        feature = _set_feature_stage(self.read(FEATURE), "done", "none", self.service)
        if evidence is not None:
            feature = _replace_body_section(self.service, feature, "Delivery evidence", evidence)
        feature = _replace_body_section(self.service, feature, "Post-ship notes", "Shipped as reported by the developer.")
        requirement = _set_requirement_status(self.read(REQUIREMENT), "done")
        return [{"path": FEATURE, "content": feature}, {"path": REQUIREMENT, "content": requirement}]

    def test_evidence_in_the_proposal_is_written_in_the_same_preview(self) -> None:
        self.assertEqual("blocked", _evidence_check(self.root)["status"])
        preview = self.preview("dev-done", self.done(EVIDENCE_TABLE))
        self.assertEqual(("dev-done", "ready", True), (preview["action"], preview["classification"], preview["applicable"]))
        self.assertEqual("pass", next(item for item in preview["checks"] if item["code"] == "delivery-evidence")["status"])
        feature_write = next(item for item in preview["writes"] if item["path"] == FEATURE)
        self.assertNotIn(EVIDENCE_ROW, feature_write["before"])
        self.assertIn(EVIDENCE_ROW, feature_write["after"])

        self.apply(preview)
        frontmatter, body = _parse_markdown(self.read(FEATURE))
        self.assertEqual(("done", "none"), (frontmatter["status"], frontmatter["owner"]))
        self.assertIn(EVIDENCE_ROW, body)
        self.assertEqual("done", _parse_markdown(self.read(REQUIREMENT))[0]["status"])
        self.assertEqual(0, lint_wiki(self.root).error_count)

    def test_missing_evidence_is_rejected_with_the_row_to_add(self) -> None:
        cases = {"empty table": EMPTY_EVIDENCE, "no table": "Shipped, trust me.", "section absent from the proposal": None}
        for name, evidence in cases.items():
            with self.subTest(case=name):
                changes = self.done(evidence)
                if evidence is None:
                    changes[0]["content"] = _replace_body_section(self.service, changes[0]["content"], "Delivery evidence", "")
                error = self.rejection("dev-done", changes)
                self.assertEqual(("delivery_evidence_required", 409), (error.code, error.status))
                self.assertIn("## Delivery evidence", error.message)
                self.assertIn("`backend`", error.message)
                self.assertIn("| backend | <implementation reference> | <test command and result> | <release artifact or target> |", error.message)
                self.assertIn("do not invent", error.message)
                self.assertEqual(FEATURE, error.details["path"])
                self.assertEqual(["backend"], error.details["apps"])
                self.assertEqual(["backend"], error.details["missing_apps"])
                self.assertTrue(error.details["problems"])
                self.assertLess(len(error.message) + len(json.dumps(error.details)), 2000)
        self.assertEqual("in-dev", _parse_markdown(self.read(FEATURE))[0]["status"])

    def test_invalid_evidence_is_rejected_with_each_problem(self) -> None:
        header = "| App | Implementation | Tests | Release |\n|---|---|---|---|\n"
        cases = {
            "placeholder cell": (header + "| backend | Pull request 42 | n/a | Version 1.4.0 |", "delivery_evidence_invalid", "`tests` for `backend` is empty or still a placeholder", []),
            "template cell": (header + "| backend | [artifact or source reference] | CI run 1187 | Version 1.4.0 |", "delivery_evidence_invalid", "`implementation` for `backend`", []),
            "wrong platform": (header + "| web-user-app | Pull request 42 | CI run 1187 | Version 1.4.0 |", "delivery_evidence_invalid", "undeclared app(s): web-user-app", ["backend"]),
            "duplicate platform": (header + EVIDENCE_ROW + "\n" + EVIDENCE_ROW, "delivery_evidence_invalid", "duplicate app `backend`", []),
            "short row": (header + "| backend | Pull request 42 | CI run 1187 |", "delivery_evidence_required", "exactly App, Implementation, Tests, and Release cells", ["backend"]),
        }
        for name, (evidence, code, problem, missing) in cases.items():
            with self.subTest(case=name):
                error = self.rejection("dev-done", self.done(evidence))
                self.assertEqual((code, 409), (error.code, error.status))
                self.assertIn(problem, " ".join(error.details["problems"]))
                if code == "delivery_evidence_invalid":
                    self.assertIn(problem, error.message)
                self.assertEqual(missing, error.details["missing_apps"])
                self.assertEqual(FEATURE, error.details["path"])
                self.assertLess(len(error.message) + len(json.dumps(error.details)), 2000)

    def test_evidence_that_an_earlier_edit_recorded_is_still_valid_input(self) -> None:
        self.write(FEATURE, _replace_body_section(self.service, self.read(FEATURE), "Delivery evidence", EVIDENCE_TABLE))
        self.assertEqual("pass", _evidence_check(self.root)["status"])
        self.apply(self.preview("dev-done", self.done(None)))
        self.assertEqual("done", _parse_markdown(self.read(FEATURE))[0]["status"])

    def test_evidence_does_not_widen_what_dev_done_may_change(self) -> None:
        changes = self.done(EVIDENCE_TABLE)
        changes[0]["content"] = _replace_body_section(self.service, changes[0]["content"], "Summary", "A different summary.")
        error = self.rejection("dev-done", changes)
        self.assertEqual(("lifecycle_body_scope", 409), (error.code, error.status))
        self.assertEqual({"sections": ["Summary"]}, error.details)
        self.assertIn("restore them to their current text", error.message)

    def test_a_linked_requirement_may_change_only_its_status_and_the_error_names_the_page(self) -> None:
        changes = self.done(EVIDENCE_TABLE)
        edited = _replace_body_section(self.service, changes[1]["content"], "Acceptance criteria", "- Everything is ticked off.")
        error = self.rejection("dev-done", [changes[0], {"path": REQUIREMENT, "content": edited}])
        self.assertEqual(("linked_page_scope", 409), (error.code, error.status))
        self.assertEqual({"path": REQUIREMENT}, error.details)
        self.assertIn(f"`{REQUIREMENT}`", error.message)
        self.assertIn("Restore everything except `status`", error.message)

    def test_dev_done_has_no_direct_human_action_and_advertises_the_evidence_rule(self) -> None:
        for actor, code in ((self.human, "human_action_unavailable"), (self.agent, "participant_kind_required")):
            with self.assertRaises(BoardError) as caught:
                self.service.preview_transition(actor, "F-001", "dev-done", {"semantic_review_acknowledged": True})
            self.assertEqual(code, caught.exception.code)
        listed = {item["name"]: item for item in self.service.list_skills(self.agent)["skills"]}["dev-done"]
        self.assertEqual(["agent"], listed["participant_kinds"])
        self.assertTrue(any("delivery_evidence_required" in text for text in listed["limitations"]))


class ApiSurfaceDeclarationTests(_DevDoneWorkspace):
    """The API surface text that po-specify writes decides whether an API contract is needed, in lint and in preflight alike."""

    NONE_LIKE = ("", "None", "None.", " no  API ", "N/A.", "Not applicable", "No API changes identified.", "No API changes required.")
    DECLARED = ("No API contract defined yet.", "POST /exports returns the PDF.")

    def test_a_plain_statement_of_no_api_work_declares_nothing(self) -> None:
        from prism_cli.wiki_model import api_surface_declared

        for text in self.NONE_LIKE:
            self.assertFalse(api_surface_declared(text), repr(text))
        for text in self.DECLARED:
            self.assertTrue(api_surface_declared(text), repr(text))

    def test_lint_and_preflight_agree_for_every_text(self) -> None:
        base = self.read(FEATURE)
        for text in (*self.NONE_LIKE, *self.DECLARED):
            declared = text in self.DECLARED
            with self.subTest(text=text):
                feature = _replace_body_section(self.service, base, "API surface", text)
                self.write(FEATURE, feature)
                check = next(item for item in build_transition_preflight(self.root, "F-001", action="dev-done")["facts"]["transition"]["checks"] if item["code"] == "api-contract")
                self.assertEqual("blocked" if declared else "pass", check["status"], check["message"])
                done = _replace_body_section(self.service, _set_feature_stage(feature, "done", "none", self.service), "Delivery evidence", EVIDENCE_TABLE)
                self.write(FEATURE, done)
                self.write(REQUIREMENT, _set_requirement_status(self.read(REQUIREMENT), "done"))
                codes = {item.code for item in lint_wiki(self.root).diagnostics}
                self.assertEqual(declared, "done-api-contract" in codes, sorted(codes))
                self.write(FEATURE, base)
                self.write(REQUIREMENT, _journey_requirement_page("in-progress"))


class HandoffApiContractTests(_BoardWorkspace):
    """D16: design-handoff creates the feature's API contract at `agreed` when its API surface declares API work."""

    CONTRACT = "knowledge/wiki/api-contracts/F-001.md"
    SURFACE = "A new endpoint `POST /api/v1/reviews/{id}/exports` returns the review summary as a PDF export for the signed-in reviewer."

    def setUp(self) -> None:
        super().setUp()
        self.set_surface(self.SURFACE)
        self.start()

    def set_surface(self, surface: str) -> None:
        questions = [
            PO_QUESTION.replace("| po | open |", "| po | resolved: Key points. |"),
            DEV_QUESTION.replace("| dev | open |", "| dev | resolved: At most 200 comments. |"),
        ]
        page = _unquote_yaml_date_fields(
            _journey_feature_page("F-001", "Document review", "in-design", "designer", ["knowledge/intake/processed/document-review-brief"], questions)
        )
        self.write(FEATURE, _replace_body_section(None, page, "API surface", surface))
        _write_index_rows(self.root, [("F-001", "Document review", "in-design", "designer")])

    def contract(
        self,
        *,
        status: str = "agreed",
        feature_id: str = "F-001",
        endpoint: str = "POST /api/v1/reviews/{reviewId}/exports",
        model: str = "ReviewExport",
        endpoints: str | None = None,
    ) -> str:
        endpoints = endpoints if endpoints is not None else f"- `{endpoint}` creates a review export. Request body: none. Response body: `{model}` (201). Errors: 401, 404.\n"
        return (
            f"---\nfeature-id: {feature_id}\nversion: 1\nstatus: {status}\n---\n\n"
            f"## Endpoints\n{endpoints}\n"
            f"## Data models\n### {model}\n- `reviewId`: string\n- `url`: string\n\n"
            "## Authentication requirements\nBearer token of the signed-in reviewer.\n\n"
            "## Notes\nThe export is generated when it is requested.\n"
        )

    def handoff(self, contract: str | None, *, path: str | None = None, link: str | None = None) -> list[dict[str, str]]:
        feature = _set_feature_stage(self.read(FEATURE), "ready-for-dev", "dev", self.service)
        requirement = _journey_requirement_page("pending")
        if link is None and contract is not None:
            link = (path or self.CONTRACT).replace("knowledge/wiki/", "../")
        if link:
            requirement = _replace_body_section(self.service, requirement, "API contract reference", f"See [the API contract]({link}) for the export endpoint.")
        changes = [{"path": FEATURE, "content": feature}, {"path": REQUIREMENT, "content": requirement}]
        if contract is not None:
            changes.append({"path": path or self.CONTRACT, "content": contract})
        return changes

    def check(self, preview: dict, code: str) -> dict:
        return next(item for item in preview["checks"] if item["code"] == code)

    def test_the_handoff_creates_the_agreed_contract_and_dev_start_then_passes(self) -> None:
        preview = self.preview("design-handoff", self.handoff(self.contract()))
        self.assertEqual(("design-handoff", "ready", True), (preview["action"], preview["classification"], preview["applicable"]))
        self.assertIn(self.CONTRACT, [item["path"] for item in preview["writes"]])
        self.apply(preview)

        frontmatter, _body = _parse_markdown(self.read(self.CONTRACT))
        self.assertEqual(("F-001", 1, "agreed"), (frontmatter["feature-id"], frontmatter["version"], frontmatter["status"]))
        self.assertEqual(("ready-for-dev", "dev"), tuple(_parse_markdown(self.read(FEATURE))[0][key] for key in ("status", "owner")))
        self.assertEqual(0, lint_wiki(self.root).error_count)

        transition = build_transition_preflight(self.root, "F-001", action="dev-start")["facts"]["transition"]
        self.assertEqual("pass", next(item for item in transition["checks"] if item["code"] == "api-contract")["status"])
        start = self.service.preview_transition(self.human, "F-001", "dev-start", {"semantic_review_acknowledged": True})
        self.assertEqual(("ready", True), (start["classification"], start["applicable"]))
        self.assertEqual("pass", self.check(start, "api-contract")["status"])
        receipt = self.service.apply(self.human, start["preview_id"], str(uuid4()))
        self.assertEqual("applied", receipt["state"])
        self.assertEqual(("in-dev", "dev"), tuple(_parse_markdown(self.read(FEATURE))[0][key] for key in ("status", "owner")))

    def test_declared_api_work_without_a_contract_is_rejected_with_the_page_to_add(self) -> None:
        error = self.rejection("design-handoff", self.handoff(None))
        self.assertEqual(("api_contract_required", 409), (error.code, error.status))
        self.assertEqual(self.CONTRACT, error.details["path"])
        self.assertEqual(("F-001", "agreed"), (error.details["feature_id"], error.details["status"]))
        self.assertEqual(["Endpoints", "Data models", "Authentication requirements", "Notes"], error.details["sections"])
        self.assertIn("status: agreed", error.message)
        self.assertLess(len(error.message), 900)
        self.assertFalse((self.root / self.CONTRACT).exists())
        self.assertEqual("in-design", _parse_markdown(self.read(FEATURE))[0]["status"])

    def test_without_declared_api_work_no_contract_is_needed_and_none_may_be_created(self) -> None:
        for surface in ("None.", "", "No API changes required."):
            with self.subTest(surface=surface):
                self.set_surface(surface)
                preview = self.preview("design-handoff", self.handoff(None))
                self.assertEqual("ready", preview["classification"])
                error = self.rejection("design-handoff", self.handoff(self.contract()))
                self.assertEqual(("api_contract_not_applicable", 409), (error.code, error.status))
                self.assertEqual({"path": self.CONTRACT, "feature_id": "F-001"}, error.details)

    def test_a_new_contract_must_be_agreed(self) -> None:
        for status in ("draft", "implemented"):
            with self.subTest(status=status):
                error = self.rejection("design-handoff", self.handoff(self.contract(status=status)))
                self.assertEqual(("api_contract_initial_status", 409), (error.code, error.status))
                self.assertEqual({"path": self.CONTRACT, "status": status, "expected_status": "agreed"}, error.details)
        self.assertFalse((self.root / self.CONTRACT).exists())

    def test_a_contract_for_another_feature_or_path_is_rejected(self) -> None:
        error = self.rejection("design-handoff", self.handoff(self.contract(feature_id="F-002")))
        self.assertEqual(("feature_context_mismatch", 409), (error.code, error.status))
        error = self.rejection("design-handoff", self.handoff(self.contract(feature_id="F-002"), path="knowledge/wiki/api-contracts/F-002.md"))
        self.assertEqual(("feature_context_mismatch", 409), (error.code, error.status))
        error = self.rejection("design-handoff", self.handoff(self.contract(), path="knowledge/wiki/api-contracts/F-002.md"))
        self.assertEqual(("api_contract_path_mismatch", 409), (error.code, error.status))
        error = self.rejection("design-handoff", self.handoff(self.contract(), path="knowledge/wiki/api-contracts/F-001-exports.md"))
        self.assertEqual(("api_contract_path_mismatch", 409), (error.code, error.status))

    def test_an_existing_contract_is_never_rewritten_and_is_not_required_again(self) -> None:
        existing = self.contract(status="agreed")
        self.write(self.CONTRACT, existing)
        # Present and untouched: the handoff needs no new page, and may repeat the current text.
        self.assertEqual("ready", self.preview("design-handoff", self.handoff(None, link="../api-contracts/F-001.md"))["classification"])
        self.assertEqual("ready", self.preview("design-handoff", self.handoff(existing))["classification"])
        for rewritten in (existing.replace("status: agreed", "status: implemented"), existing.replace("Errors: 401, 404.", "Errors: 401.")):
            with self.subTest(rewritten=rewritten[-60:]):
                error = self.rejection("design-handoff", self.handoff(rewritten))
                self.assertEqual(("api_contract_exists", 409), (error.code, error.status))
                self.assertEqual({"path": self.CONTRACT, "feature_id": "F-001"}, error.details)
        self.assertEqual(existing, self.read(self.CONTRACT))

    def test_a_linked_shared_contract_covers_the_feature(self) -> None:
        self.write("knowledge/wiki/api-contracts/SHARED.md", self.contract())
        feature = _replace_body_section(self.service, self.read(FEATURE), "API surface", "See [the shared contract](../api-contracts/SHARED.md) for the export endpoint.")
        self.write(FEATURE, feature)
        self.assertEqual("ready", self.preview("design-handoff", self.handoff(None, link="../api-contracts/SHARED.md"))["classification"])
        error = self.rejection("design-handoff", self.handoff(self.contract()))
        self.assertEqual(("api_contract_exists", 409), (error.code, error.status))
        self.assertEqual(["knowledge/wiki/api-contracts/SHARED.md"], error.details["existing"])

    def test_endpoints_and_models_must_trace_to_the_api_surface(self) -> None:
        error = self.rejection("design-handoff", self.handoff(self.contract(endpoint="DELETE /api/v1/users/{id}")))
        self.assertEqual(("api_contract_untraceable", 409), (error.code, error.status))
        self.assertEqual(["DELETE /api/v1/users/{}"], error.details["endpoints"])
        self.assertIn("/api/v1/reviews/{}/exports", error.message)

        error = self.rejection("design-handoff", self.handoff(self.contract(endpoints="- `POST /api/v1/reviews/{id}/exports` and `GET /api/v1/reviews/{id}/exports/{exportId}`.\n")))
        self.assertEqual(["GET /api/v1/reviews/{}/exports/{}"], error.details["endpoints"])

        error = self.rejection("design-handoff", self.handoff(self.contract(endpoints="Creates an export.\n")))
        self.assertEqual(("invalid_api_contract", 409), (error.code, error.status))
        self.assertEqual({"path": self.CONTRACT, "section": "Endpoints"}, error.details)

        orphan = self.contract() + "\n"
        orphan = orphan.replace("## Authentication requirements", "### AuditTrail\n- `at`: string\n\n## Authentication requirements")
        error = self.rejection("design-handoff", self.handoff(orphan))
        self.assertEqual(("api_contract_untraceable", 409), (error.code, error.status))
        self.assertEqual(["AuditTrail"], error.details["models"])
        self.assertFalse((self.root / self.CONTRACT).exists())

    def test_a_prose_api_surface_needs_a_shared_resource_word_for_every_endpoint(self) -> None:
        self.set_surface("The summary can be exported as a PDF file for each review.")
        self.assertEqual("ready", self.preview("design-handoff", self.handoff(self.contract(endpoint="POST /api/v1/reviews/{id}/export")))["classification"])
        error = self.rejection("design-handoff", self.handoff(self.contract(endpoint="POST /api/v1/invoices")))
        self.assertEqual(("api_contract_untraceable", 409), (error.code, error.status))
        self.assertEqual(["POST /api/v1/invoices"], error.details["endpoints"])
        self.assertIn("po-clarify", error.message)

    def test_the_other_skills_still_cannot_write_a_contract(self) -> None:
        feature = self.read(FEATURE)
        error = self.rejection("dev-clarify", [{"path": FEATURE, "content": feature}, {"path": self.CONTRACT, "content": self.contract()}])
        self.assertEqual(("write_path_unavailable", 403), (error.code, error.status))
        error = self.rejection("design-clarify", [{"path": FEATURE, "content": feature}, {"path": self.CONTRACT, "content": self.contract()}])
        self.assertEqual(("write_path_unavailable", 403), (error.code, error.status))

    def test_the_skill_listing_reports_the_scope_and_the_rule(self) -> None:
        listed = {item["name"]: item for item in self.service.list_skills(self.agent)["skills"]}["design-handoff"]
        self.assertIn("knowledge/wiki/api-contracts/*.md", listed["write_scopes"])
        self.assertTrue(any("api_contract_required" in text and "status: agreed" in text for text in listed["limitations"]))


class ApprovedReadPathTests(_BoardWorkspace):
    """A read of the workspace manifest fails with the path and the way to get the identity instead."""

    def test_a_path_outside_the_approved_folders_names_the_path_and_points_to_discover(self) -> None:
        self.start()
        for path in ("prism.workspace.yml", ".copier-answers.yml"):
            with self.subTest(path=path), self.assertRaises(BoardError) as caught:
                self.service.read_workspace(self.agent, ["knowledge/wiki/SCHEMA.md", path])
            error = caught.exception
            self.assertEqual(("path_not_approved", 403), (error.code, error.status))
            self.assertIn(f"`{path}`", error.message)
            self.assertIn("discover", error.message)
            self.assertEqual({"path": path, "approved": ["knowledge/wiki/", "knowledge/intake/"]}, error.details)
        self.assertEqual(2, len(self.service.read_workspace(self.agent, ["knowledge/wiki/SCHEMA.md", "knowledge/wiki/log.md"])["files"]))


def _evidence_check(root: Path) -> dict:
    transition = build_transition_preflight(root, "F-001", action="dev-done")["facts"]["transition"]
    return next(item for item in transition["checks"] if item["code"] == "delivery-evidence")


if __name__ == "__main__":
    unittest.main()
