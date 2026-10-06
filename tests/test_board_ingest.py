"""Generic ingest through the in-process board: any role, any page kind, with the index lines the board writes itself.

Complete proposals are submitted the way the board tests do, with no agent host. The status-board and index merges keep
the conflict, idempotence and recovery guarantees that the feature status rows always had.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import yaml

from prism_cli.board_service import BoardError
from prism_cli.wiki_index import parse_index_entries
from tests import real_temp  # noqa: F401
from tests.test_board_evidence_workflows import BoardWorkspaceCase
from tests.test_board_service import (
    _journey_business_rule_page,
    _journey_feature_page,
    _journey_persona_page,
    _read_revisions,
)

INDEX = "knowledge/wiki/index.md"
BOARD = "knowledge/wiki/status-board.md"
LOG = "knowledge/wiki/log.md"
NAME_TOKEN = "NAME"

TOPIC = (
    "---\nkind: topic\ntitle: Payment flows\nstatus: current\nsources:\n- knowledge/intake/processed/NAME/note.md\n---\n\n"
    "## Summary\nPayments settle within one business day. Refunds follow a separate path.\n\n"
    "## Key points\n- **Observed:** Settlement takes one business day ([note](../../intake/processed/NAME/note.md)).\n"
    "- **Assumed:** Weekends are excluded.\n\n## Related pages\nNone yet.\n"
)
RESEARCH = (
    "---\nkind: research\ntitle: Offline sync options\nstatus: open\nsources:\n- knowledge/intake/processed/NAME/note.md\n---\n\n"
    "## Question\nWhich sync model fits offline editing?\n\n## Summary\nA last-writer-wins model fits the current needs.\n\n"
    "## Findings\n- **Observed:** Two vendors support it ([note](../../intake/processed/NAME/note.md)).\n\n## Gaps\n- **Unknown:** The cost at scale.\n"
)
PLAN = (
    "---\nkind: plan\ntitle: Launch\nstatus: active\nsources:\n- knowledge/intake/processed/NAME/note.md\n---\n\n"
    "## Summary\nThe launch is in its second phase.\n\n## Goal\n- **Decided:** Ship to all customers ([note](../../intake/processed/NAME/note.md)).\n\n"
    "## Current status\nThe beta runs.\n\n## Next steps\n- **Proposed:** Invite the first hundred customers.\n\n## Blockers\nNo blockers.\n"
)
DIRECTION = (
    "---\nkind: direction\nsources:\n- knowledge/intake/processed/NAME/note.md\n---\n\n## Summary\nThe product serves reviewers first.\n\n"
    "## Direction\n- **Decided:** Reviewers come first ([note](../intake/processed/NAME/note.md)).\n\n## Principles\n- Keep records.\n"
)
ROADMAP = (
    "---\nkind: roadmap\nsources:\n- knowledge/intake/processed/NAME/note.md\n---\n\n## Summary\nThe next release ships the export.\n\n"
    "## Next\n- The export ships on 2026-12-01.\n\n## Later\n- Offline editing.\n"
)
ADR_OLD = (
    "---\nid: ADR-001\ntitle: Sessions for sign-in\ndate: 2026-09-01\nstatus: accepted\n---\n\n"
    "## Context\nReviewers sign in from one browser.\n\n## Decision\nUse server sessions.\n\n"
    "## Rationale\nThe simplest option.\n\n## Consequences\nSessions expire with the browser.\n"
)
ADR_NEW = (
    "---\nid: ADR-002\ntitle: Tokens for sign-in\ndate: 2026-10-08\nstatus: accepted\nsupersedes: ADR-001\n---\n\n"
    "## Context\nReviewers also sign in from a mobile app.\n\n## Decision\nUse signed tokens.\n\n"
    "## Rationale\nTokens work on both clients.\n\n## Consequences\nTokens need revocation.\n"
)
ADR_OLD_PATH = "decisions/ADR-001-auth-sessions.md"
ADR_NEW_PATH = "decisions/ADR-002-auth-tokens.md"


def manifest(pages: dict[str, str]) -> str:
    """A MANIFEST.md that lists every page by full path and, where the page has one, its canonical ID."""

    lines = ["# Processed intake", ""]
    for relative, content in pages.items():
        identifier = yaml.safe_load(content.split("---", 2)[1]).get("id")
        lines.append(f"- knowledge/wiki/{relative}" + (f" ({identifier})" if identifier else ""))
    return "\n".join(lines) + "\n"


class IngestCase(BoardWorkspaceCase):
    """A board with one agent; `ingest` drops a dated folder and processes it into the given pages."""

    NOTE = "Captured: 2026-10-08\n\nThe source says what the pages record.\n"

    def proposal(self, name: str, pages: dict[str, str]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
        folder = f"knowledge/intake/pending/{name}"
        if not (self.root / folder).exists():
            self.drop_pending(name, self.NOTE)
        destination = folder.replace("pending", "processed", 1)
        changes = [{"path": f"knowledge/wiki/{relative}", "content": content.replace(NAME_TOKEN, name)} for relative, content in pages.items()]
        changes.append({"path": f"{destination}/MANIFEST.md", "content": manifest(pages)})
        return changes, [{"source": folder, "destination": destination}]

    def ingest(self, name: str, pages: dict[str, str]) -> dict:
        changes, moves = self.proposal(name, pages)
        return self.submit("ingest", changes, moves)

    def reject(self, name: str, pages: dict[str, str]) -> BoardError:
        changes, moves = self.proposal(name, pages)
        error = self.rejected("ingest", changes, moves)
        self.assertTrue((self.root / moves[0]["source"]).is_dir(), "a rejected proposal moves nothing")
        return error

    def index_lines(self) -> dict[str, str]:
        return {entry.target: entry.line for entry in parse_index_entries(self.read(INDEX))}

    def headings(self) -> list[str]:
        return [line for line in self.read(INDEX).splitlines() if line.startswith("## ")]


class PageKindIngestTests(IngestCase):
    def test_each_new_page_kind_is_ingested_with_its_index_line_and_lint_is_clean(self) -> None:
        kinds = {
            "topics/payment-flows.md": (TOPIC, "- [Payment flows](topics/payment-flows.md): Payments settle within one business day."),
            "research/offline-sync.md": (RESEARCH, "- [Offline sync options](research/offline-sync.md): A last-writer-wins model fits the current needs."),
            "plans/launch.md": (PLAN, "- [Launch](plans/launch.md): The launch is in its second phase."),
            "direction.md": (DIRECTION, "- [Direction](direction.md): The product serves reviewers first."),
            "roadmap.md": (ROADMAP, "- [Roadmap](roadmap.md): The next release ships the export."),
        }
        for number, (relative, (content, line)) in enumerate(kinds.items(), start=1):
            name = f"2026-10-0{number}-{Path(relative).stem}"
            with self.subTest(page=relative):
                receipt = self.ingest(name, {relative: content})
                self.assertIn(f"knowledge/wiki/{relative}", receipt["applied_paths"])
                self.assertIn(INDEX, receipt["applied_paths"])
                self.assertEqual(content.replace(NAME_TOKEN, name), self.read(f"knowledge/wiki/{relative}"))
                self.assertEqual(line, self.index_lines()[relative])
                self.assertTrue((self.root / f"knowledge/intake/processed/{name}/note.md").is_file())
                self.assertFalse((self.root / f"knowledge/intake/pending/{name}").exists())
                entry = self.log_entries()[-1]
                self.assertEqual(("board-ingest", name), (entry["operation"], entry["subject"]))
                self.assertIn(f"knowledge/wiki/{relative}", entry["paths"])
                self.assertIn(INDEX, entry["paths"])
                self.assertIn(f"knowledge/intake/processed/{name}", entry["evidence"])
        self.assert_lint_clean()
        # One line per page, grouped under the headings of the kinds, in group order.
        self.assertEqual(
            ["## Direction and roadmap", "## Plans", "## Topics", "## Research", "## Advisory", "## Meta"],
            [heading for heading in self.headings()],
        )
        for relative in kinds:
            self.assertEqual(1, sum(1 for entry in parse_index_entries(self.read(INDEX)) if entry.target == relative))

    def test_one_ingest_writes_pages_of_several_kinds(self) -> None:
        pages = {
            "topics/payment-flows.md": TOPIC,
            "plans/launch.md": PLAN,
            "personas/P-001-reviewer.md": _journey_persona_page().replace("2026-10-06-document-review-brief/brief.md", "NAME/note.md"),
            "business-rules/BR-001-retain.md": _journey_business_rule_page().replace("2026-10-06-document-review-brief/brief.md", "NAME/note.md"),
            "decisions/ADR-001-auth-sessions.md": ADR_OLD,
        }
        receipt = self.ingest("2026-10-08-planning-notes", pages)
        for relative in pages:
            self.assertIn(f"knowledge/wiki/{relative}", receipt["applied_paths"])
        self.assertEqual(set(pages), set(self.index_lines()) & set(pages))
        self.assertEqual("- [P-001 Reviewer](personas/P-001-reviewer.md): A person assigned to review a document.", self.index_lines()["personas/P-001-reviewer.md"])
        self.assertEqual("- [ADR-001 Sessions for sign-in](decisions/ADR-001-auth-sessions.md): Use server sessions.", self.index_lines()["decisions/ADR-001-auth-sessions.md"])
        self.assert_lint_clean()

    def test_a_participant_of_any_role_can_ingest(self) -> None:
        # The board knows participants, not roles: a developer's agent ingests exactly as a product owner's does.
        grant = self.service.create_participant("Developer agent", "agent", True)
        developer = self.service.authenticate(grant["token"])
        changes, moves = self.proposal("2026-10-08-spike", {"research/offline-sync.md": RESEARCH})
        preview = self.service.preview_skill(developer, "ingest", changes, moves, _read_revisions(self.service, developer, "ingest", changes, moves))
        self.assertTrue(preview["applicable"], preview["blockers"])
        receipt = self.service.apply(developer, preview["preview_id"], str(uuid4()))
        self.assertEqual("applied", receipt["state"])
        self.assertIn("Developer agent (agent)", self.log_entries()[-1]["by"])

    def test_a_page_is_replaced_in_place_and_its_index_line_with_it(self) -> None:
        self.ingest("2026-10-08-first", {"topics/payment-flows.md": TOPIC})
        before = self.index_lines()
        changed = (
            TOPIC.replace("within one business day", "within two business days")
            .replace("Settlement takes one business day", "Settlement takes two business days")
        )
        self.ingest("2026-10-09-second", {"topics/payment-flows.md": changed})

        page = self.read("knowledge/wiki/topics/payment-flows.md")
        self.assertIn("two business days", page)
        self.assertNotIn("one business day", page)
        self.assertNotIn("was", page.lower().split("## key points")[0])
        after = self.index_lines()
        self.assertEqual("- [Payment flows](topics/payment-flows.md): Payments settle within two business days.", after["topics/payment-flows.md"])
        self.assertEqual({key: value for key, value in before.items() if key != "topics/payment-flows.md"}, {key: value for key, value in after.items() if key != "topics/payment-flows.md"})
        self.assertEqual(1, self.read(INDEX).count("topics/payment-flows.md"))
        self.assertEqual(["board-ingest", "board-ingest"], [entry["operation"] for entry in self.log_entries()][-2:])
        self.assert_lint_clean()

    def test_an_unchanged_line_is_not_rewritten(self) -> None:
        self.ingest("2026-10-08-first", {"research/offline-sync.md": RESEARCH})
        text = RESEARCH.replace("Two vendors support it", "Three vendors support it")
        changes, moves = self.proposal("2026-10-09-second", {"research/offline-sync.md": text})
        preview = self.service.preview_skill(self.agent, "ingest", changes, moves, _read_revisions(self.service, self.agent, "ingest", changes, moves))
        self.assertNotIn(INDEX, [write["path"] for write in preview["writes"]], "the summary sentence is unchanged, so is the line")

    def test_a_proposal_that_replaces_an_existing_page_must_have_read_it(self) -> None:
        self.ingest("2026-10-08-first", {"topics/payment-flows.md": TOPIC})
        changes, moves = self.proposal("2026-10-09-second", {"topics/payment-flows.md": TOPIC.replace("one business day", "two business days")})
        with self.assertRaises(BoardError) as caught:
            self.service.preview_skill(self.agent, "ingest", changes, moves, {})
        self.assertEqual("missing_read_revisions", caught.exception.code)
        self.assertIn("knowledge/wiki/topics/payment-flows.md", caught.exception.details["paths"])

    def test_a_quarantine_through_ingest_writes_only_the_conflict_record(self) -> None:
        self.ingest("2026-10-08-first", {"topics/payment-flows.md": TOPIC})
        wiki_before = {path: self.read(path) for path in ("knowledge/wiki/topics/payment-flows.md", INDEX, BOARD)}
        folder = self.drop_pending("2026-10-09-contradiction", "Captured: 2026-10-09\n\nPayments settle in a week.\n")
        quarantined = folder.replace("pending", "quarantined", 1)
        conflict = (
            "---\nstatus: open\n---\n\n# Conflict: settlement time\n\n## Existing claim\n- **Claim:** Payments settle within one business day.\n"
            "- **Scope:** All payments.\n- **Evidence:** [Payment flows](../../../wiki/topics/payment-flows.md)\n\n"
            "## Incoming claim\n- **Claim:** Payments settle in a week.\n- **Scope:** All payments.\n- **Evidence:** [note](note.md)\n\n"
            "## Decision needed\nWhich claim holds.\n"
        )
        self.submit("ingest", [{"path": f"{quarantined}/CONFLICT.md", "content": conflict}], [{"source": folder, "destination": quarantined}])
        self.assertEqual(wiki_before, {path: self.read(path) for path in wiki_before})
        self.assertIn("unresolved-conflict", [item.code for item in self.lint().diagnostics])
        error = self.rejected(
            "ingest",
            [{"path": f"{quarantined}x/CONFLICT.md", "content": conflict}, {"path": "knowledge/wiki/topics/other.md", "content": TOPIC}],
            [{"source": self.drop_pending("2026-10-10-other"), "destination": quarantined.replace("contradiction", "other") + "x"}],
        )
        self.assertIn(error.code, {"quarantine_write_scope", "invalid_intake_move", "intake_name_invalid"})


class FeatureThroughIngestTests(IngestCase):
    def feature(self, **changes: str) -> str:
        page = _journey_feature_page("F-001", "Document review", "raw", "po", ["knowledge/intake/processed/NAME/note.md"], ["| 1 | Which details should the summary emphasize? | po | open |"])
        for old, new in changes.items():
            self.assertIn(old, page)
            page = page.replace(old, new)
        return page

    def test_a_feature_through_ingest_is_raw_and_has_its_status_row_and_index_line(self) -> None:
        receipt = self.ingest("2026-10-08-review-brief", {"features/F-001-document-review.md": self.feature()})
        self.assertIn(BOARD, receipt["applied_paths"])
        self.assertIn("| F-001 | Document review | raw | po | not-needed |", self.read(BOARD))
        self.assertEqual(
            "- [F-001 Document review](features/F-001-document-review.md): Review a document, summarize its key points, and record the review outcome.",
            self.index_lines()["features/F-001-document-review.md"],
        )
        self.assert_lint_clean()

    def test_a_feature_through_ingest_is_held_to_every_po_intake_rule(self) -> None:
        folder_pages = lambda page: {"features/F-001-document-review.md": page}  # noqa: E731
        cases = {
            "not raw": (self.feature(**{"status: raw": "status: specified"}), "invalid_intake_feature"),
            "not owned by po": (self.feature(**{"owner: po": "owner: designer"}), "invalid_intake_feature"),
            "no user story": (re.sub(r"(?s)## User story.*?(?=## )", "", self.feature()), "required_section_missing"),
            "an unknown app": (self.feature(**{"- backend": "- ghost"}), "invalid_feature_output"),
            "a pending source": (self.feature(**{"knowledge/intake/processed/NAME/note.md": "knowledge/intake/pending/NAME/note.md"}), "intake_source_not_processed"),
            "a missing source": (self.feature(**{"knowledge/intake/processed/NAME/note.md": "knowledge/intake/processed/NAME/absent.md"}), "source_link_missing"),
            "placeholder text": (self.feature(**{"Review a document": "TODO Review a document"}), "template_placeholder"),
        }
        for label, (page, code) in cases.items():
            with self.subTest(label):
                error = self.reject(f"2026-10-08-{re.sub(r'[^a-z]+', '-', label)}", folder_pages(page))
                self.assertEqual(code, error.code, error.message)
        self.assertFalse((self.root / "knowledge/wiki/features/F-001-document-review.md").exists())

    def test_an_existing_feature_is_never_rewritten_by_ingest(self) -> None:
        self.ingest("2026-10-08-first", {"features/F-001-document-review.md": self.feature()})
        error = self.reject("2026-10-09-again", {"features/F-001-document-review.md": self.feature().replace("Which details", "Which points")})
        self.assertEqual("intake_existing_feature", error.code)

    def test_the_manifest_must_list_each_page_with_its_canonical_id(self) -> None:
        persona = _journey_persona_page().replace("2026-10-06-document-review-brief/brief.md", "NAME/note.md")
        pages = {"features/F-001-document-review.md": self.feature(), "personas/reviewer.md": persona, "topics/payment-flows.md": TOPIC}
        changes, moves = self.proposal("2026-10-08-brief", pages)
        manifest_change = changes[-1]
        for label, text, code in (
            ("no id", manifest_change["content"].replace(" (P-001)", ""), "intake_manifest_incomplete"),
            ("no topic", manifest_change["content"].replace("- knowledge/wiki/topics/payment-flows.md\n", ""), "intake_manifest_incomplete"),
            ("empty", "", "intake_manifest_required"),
        ):
            with self.subTest(label):
                error = self.rejected("ingest", [*changes[:-1], {"path": manifest_change["path"], "content": text}], moves)
                self.assertEqual(code, error.code)
        extra = [*changes, {"path": manifest_change["path"].replace("MANIFEST.md", "NOTES.md"), "content": "# Extra\n"}]
        self.assertEqual("intake_manifest_scope", self.rejected("ingest", extra, moves).code)
        only_manifest = self.rejected("ingest", [manifest_change], moves)
        self.assertEqual("intake_manifest_required", only_manifest.code)
        self.submit("ingest", changes, moves)


class PageRuleTests(IngestCase):
    def rejection(self, pages: dict[str, str], name: str = "2026-10-08-bad") -> BoardError:
        return self.reject(name, pages)

    def test_a_general_page_is_checked_for_its_kind_status_sources_sections_and_name(self) -> None:
        cases = {
            "wrong kind": (TOPIC.replace("kind: topic", "kind: research"), "invalid_topic"),
            "bad status": (TOPIC.replace("status: current", "status: active"), "invalid_topic"),
            "no title": (TOPIC.replace("title: Payment flows\n", "title: ''\n"), "invalid_topic"),
            "no sources": (TOPIC.replace("sources:\n- knowledge/intake/processed/NAME/note.md\n", "sources: []\n"), "invalid_topic"),
            "a history date": (TOPIC.replace("sources:", "updated: 2026-10-08\nsources:", 1), "unknown_frontmatter_fields"),
            "a missing section": (TOPIC.replace("## Related pages\nNone yet.\n", ""), "required_section_missing"),
            "an empty section": (TOPIC.replace("None yet.", ""), "required_section_missing"),
            "placeholder text": (TOPIC.replace("None yet.", "TBD"), "template_placeholder"),
            "a source that does not exist": (TOPIC.replace("NAME/note.md", "NAME/absent.md", 1), "source_link_missing"),
        }
        for label, (content, code) in cases.items():
            with self.subTest(label):
                error = self.rejection({"topics/payment-flows.md": content})
                self.assertEqual(code, error.code, error.message)
        self.assertEqual("wiki_path_invalid", self.rejection({"topics/Payment Flows.md": TOPIC}).code)
        for relative, content, code in (
            ("direction.md", DIRECTION.replace("kind: direction", "kind: roadmap"), "invalid_direction"),
            ("roadmap.md", ROADMAP.replace("## Later\n- Offline editing.\n", ""), "required_section_missing"),
            ("plans/launch.md", PLAN.replace("status: active", "status: current"), "invalid_plan"),
            ("research/offline-sync.md", RESEARCH.replace("## Gaps\n- **Unknown:** The cost at scale.\n", ""), "required_section_missing"),
        ):
            with self.subTest(page=relative):
                self.assertEqual(code, self.rejection({relative: content}).code)

    def test_direction_and_roadmap_have_no_title_or_status_field(self) -> None:
        for relative, content in (("direction.md", DIRECTION), ("roadmap.md", ROADMAP)):
            with self.subTest(page=relative):
                bad = content.replace("sources:", "title: Extra\nsources:", 1)
                self.assertEqual("unknown_frontmatter_fields", self.rejection({relative: bad}).code)

    def test_ingest_writes_only_the_kinds_it_owns_and_never_a_managed_file(self) -> None:
        folder = self.drop_pending("2026-10-08-scope")
        destination = folder.replace("pending", "processed", 1)
        moves = [{"source": folder, "destination": destination}]
        manifest_change = {"path": f"{destination}/MANIFEST.md", "content": "# Processed intake\n\n- knowledge/wiki/topics/x.md\n"}
        for path, code, status in (
            ("knowledge/wiki/design/F-001-x.md", "write_path_unavailable", 403),
            ("knowledge/wiki/app-requirements/F-001-backend.md", "write_path_unavailable", 403),
            ("knowledge/wiki/advisory/F-001-review.md", "write_path_unavailable", 403),
            ("knowledge/wiki/SCHEMA.md", "write_path_unavailable", 403),
            ("knowledge/wiki/topics/nested/x.md", "write_path_unavailable", 403),
            ("knowledge/wiki/index.md", "managed_file", 403),
            ("knowledge/wiki/status-board.md", "managed_file", 403),
            ("knowledge/wiki/log.md", "managed_file", 403),
        ):
            with self.subTest(path=path):
                error = self.rejected("ingest", [{"path": path, "content": TOPIC}, manifest_change], moves)
                self.assertEqual((code, status), (error.code, error.status))

    def test_a_persona_or_business_rule_is_created_and_never_rewritten(self) -> None:
        persona = _journey_persona_page().replace("2026-10-06-document-review-brief/brief.md", "NAME/note.md")
        rule = _journey_business_rule_page().replace("2026-10-06-document-review-brief/brief.md", "NAME/note.md")
        self.ingest("2026-10-08-first", {"personas/P-001-reviewer.md": persona, "business-rules/BR-001-retain.md": rule})
        for relative, content in (("personas/P-001-reviewer.md", persona), ("business-rules/BR-001-retain.md", rule)):
            with self.subTest(page=relative):
                error = self.reject("2026-10-09-again", {relative: content.replace("Record key points", "Record every point").replace("A recorded review", "Every recorded review")})
                self.assertEqual("intake_existing_page", error.code)

    def test_ids_stay_unique_across_pages(self) -> None:
        persona = _journey_persona_page().replace("2026-10-06-document-review-brief/brief.md", "NAME/note.md")
        self.ingest("2026-10-08-first", {"personas/P-001-reviewer.md": persona})
        error = self.reject("2026-10-09-second", {"personas/P-001-second.md": persona})
        self.assertEqual("duplicate_wiki_id", error.code)
        self.ingest("2026-10-10-adr", {ADR_OLD_PATH: ADR_OLD})
        error = self.reject("2026-10-11-adr", {"decisions/ADR-001-other.md": ADR_OLD})
        self.assertEqual("duplicate_wiki_id", error.code)


class DecisionIngestTests(IngestCase):
    def supersede_pages(self, **old_changes: str) -> dict[str, str]:
        old = ADR_OLD.replace("status: accepted\n", "status: superseded\nsuperseded-by: ADR-002\n")
        for before, after in old_changes.items():
            self.assertIn(before, old)
            old = old.replace(before, after)
        return {ADR_OLD_PATH: old, ADR_NEW_PATH: ADR_NEW}

    def test_a_new_decision_supersedes_an_old_one_in_one_operation(self) -> None:
        self.ingest("2026-10-08-first", {ADR_OLD_PATH: ADR_OLD})
        old_body = self.read(f"knowledge/wiki/{ADR_OLD_PATH}").split("\n---\n", 1)[1]
        receipt = self.ingest("2026-10-09-second", self.supersede_pages())
        self.assertIn(f"knowledge/wiki/{ADR_OLD_PATH}", receipt["applied_paths"])
        old = self.read(f"knowledge/wiki/{ADR_OLD_PATH}")
        self.assertIn("status: superseded\nsuperseded-by: ADR-002\n", old)
        self.assertEqual(old_body, old.split("\n---\n", 1)[1], "the old body is unchanged")
        self.assertIn("supersedes: ADR-001\n", self.read(f"knowledge/wiki/{ADR_NEW_PATH}"))
        self.assertEqual(
            "- [ADR-002 Tokens for sign-in](decisions/ADR-002-auth-tokens.md): Use signed tokens.",
            self.index_lines()[ADR_NEW_PATH],
        )
        self.assertEqual(
            "- [ADR-001 Sessions for sign-in](decisions/ADR-001-auth-sessions.md): ADR-002 supersedes this decision.",
            self.index_lines()[ADR_OLD_PATH],
        )
        self.assert_lint_clean()

    def test_each_broken_supersession_is_rejected_with_its_reason(self) -> None:
        self.ingest("2026-10-08-first", {ADR_OLD_PATH: ADR_OLD})
        cases = {
            "the old body changes": (self.supersede_pages(**{"Use server sessions.": "Use cookies."}), "record_immutable"),
            "another field of the old record changes": (self.supersede_pages(**{"title: Sessions for sign-in": "title: Cookies"}), "record_immutable"),
            "the old record is not marked superseded": ({ADR_OLD_PATH: ADR_OLD.replace("Use server", "Use signed"), ADR_NEW_PATH: ADR_NEW}, "record_immutable"),
            "the old page is not in the proposal": ({ADR_NEW_PATH: ADR_NEW}, "supersession_incomplete"),
            "the old record names no successor in the proposal": ({ADR_OLD_PATH: self.supersede_pages()[ADR_OLD_PATH]}, "supersession_incomplete"),
            "the new decision is not accepted or proposed": ({ADR_OLD_PATH: self.supersede_pages()[ADR_OLD_PATH], ADR_NEW_PATH: ADR_NEW.replace("status: accepted", "status: deprecated")}, "invalid_decision"),
            "the new decision names itself": ({ADR_NEW_PATH: ADR_NEW.replace("supersedes: ADR-001", "supersedes: ADR-002")}, "invalid_decision"),
        }
        for label, (pages, code) in cases.items():
            with self.subTest(label):
                error = self.reject(f"2026-10-09-{re.sub(r'[^a-z]+', '-', label)[:30]}", pages)
                self.assertEqual(code, error.code, error.message)
        self.assertIn("status: accepted", self.read(f"knowledge/wiki/{ADR_OLD_PATH}"))

    def test_a_new_decision_is_checked_for_its_fields_and_sections(self) -> None:
        cases = {
            "a bad id": (ADR_OLD.replace("id: ADR-001", "id: ADR-X"), "invalid_decision"),
            "no date": (ADR_OLD.replace("date: 2026-09-01\n", ""), "invalid_decision"),
            "a missing section": (ADR_OLD.replace("## Consequences\nSessions expire with the browser.\n", ""), "required_section_missing"),
            "an unknown field": (ADR_OLD.replace("status: accepted", "status: accepted\nowner: po"), "unknown_frontmatter_fields"),
            "an id the file name does not carry": (ADR_OLD.replace("id: ADR-001", "id: ADR-007"), "decision_path_mismatch"),
        }
        for label, (content, code) in cases.items():
            with self.subTest(label):
                self.assertEqual(code, self.reject("2026-10-08-bad-decision", {ADR_OLD_PATH: content}).code)

    def test_an_existing_decision_cannot_be_rewritten_by_any_ingest(self) -> None:
        self.ingest("2026-10-08-first", {ADR_OLD_PATH: ADR_OLD})
        error = self.reject("2026-10-09-rewrite", {ADR_OLD_PATH: ADR_OLD.replace("Use server sessions.", "Use cookies.")})
        self.assertEqual("record_immutable", error.code)


class IndexMergeGuaranteeTests(IngestCase):
    """The index lines merge row by row: unrelated lines and log entries survive, a changed target line does not."""

    def preview(self, name: str, pages: dict[str, str], agent=None) -> tuple[dict, list, list]:
        actor = agent or self.agent
        changes, moves = self.proposal(name, pages)
        preview = self.service.preview_skill(actor, "ingest", changes, moves, _read_revisions(self.service, actor, "ingest", changes, moves))
        self.assertTrue(preview["applicable"], preview["blockers"])
        return preview, changes, moves

    def test_the_preview_carries_the_exact_index_write(self) -> None:
        preview, _changes, _moves = self.preview("2026-10-08-first", {"topics/payment-flows.md": TOPIC})
        roles = {write["path"]: write["role"] for write in preview["writes"]}
        self.assertEqual("index", roles[INDEX])
        self.assertEqual("log", roles[LOG])
        index = next(write for write in preview["writes"] if write["path"] == INDEX)
        self.assertIn("topics/payment-flows.md", index["after"])
        self.assertNotIn("topics/payment-flows.md", index["before"])
        self.assertNotIn(BOARD, roles, "no feature changes, so no status board row")

    def test_an_unrelated_line_added_after_the_preview_is_kept(self) -> None:
        preview, _changes, _moves = self.preview("2026-10-08-first", {"topics/payment-flows.md": TOPIC})
        extra = "- [Other](topics/other.md): Written by someone else."
        (self.root / "knowledge/wiki/topics/other.md").write_text(TOPIC.replace("Payment flows", "Other"), encoding="utf-8", newline="\n")
        (self.root / INDEX).write_text(self.read(INDEX).replace("\n## Advisory", f"\n## Topics\n{extra}\n\n## Advisory", 1), encoding="utf-8", newline="\n")
        receipt = self.service.apply(self.agent, preview["preview_id"], "merge-operation")
        self.assertEqual("applied", receipt["state"], receipt)
        lines = self.index_lines()
        self.assertEqual(extra, lines["topics/other.md"])
        self.assertIn("topics/payment-flows.md", lines)
        self.assertEqual(["topics/other.md", "topics/payment-flows.md"], [t for t in lines if t.startswith("topics/")])

    def test_a_target_line_that_changed_after_the_preview_is_a_conflict(self) -> None:
        preview, _changes, _moves = self.preview("2026-10-08-first", {"topics/payment-flows.md": TOPIC})
        (self.root / INDEX).write_text(self.read(INDEX).replace("\n## Advisory", "\n## Topics\n- [Someone else](topics/payment-flows.md): Added first.\n\n## Advisory", 1), encoding="utf-8", newline="\n")
        with self.assertRaises(BoardError) as caught:
            self.service.apply(self.agent, preview["preview_id"], "stale-operation")
        self.assertEqual(("stale_index_entry", 409), (caught.exception.code, caught.exception.status))
        self.assertFalse((self.root / "knowledge/wiki/topics/payment-flows.md").exists(), "nothing was written")

    def test_a_duplicate_line_is_refused_before_it_can_be_replaced(self) -> None:
        self.ingest("2026-10-08-first", {"topics/payment-flows.md": TOPIC})
        (self.root / INDEX).write_text(self.read(INDEX) + "- [Again](topics/payment-flows.md): Twice.\n", encoding="utf-8", newline="\n")
        changes, moves = self.proposal("2026-10-09-second", {"topics/payment-flows.md": TOPIC.replace("one business day", "two business days")})
        with self.assertRaises(BoardError) as caught:
            self.service.preview_skill(self.agent, "ingest", changes, moves, _read_revisions(self.service, self.agent, "ingest", changes, moves))
        self.assertEqual("duplicate_index_entry", caught.exception.code)

    def test_applying_the_same_operation_twice_writes_the_line_once(self) -> None:
        preview, _changes, _moves = self.preview("2026-10-08-first", {"topics/payment-flows.md": TOPIC})
        first = self.service.apply(self.agent, preview["preview_id"], "same-operation")
        again = self.service.apply(self.agent, preview["preview_id"], "same-operation")
        self.assertEqual(first, again)
        self.assertEqual(1, self.read(INDEX).count("topics/payment-flows.md"))
        self.assertEqual(1, self.read(LOG).count(f"preview={preview['preview_id']}"))

    def test_an_interrupted_index_write_is_recovered_by_a_human_with_unrelated_lines_kept(self) -> None:
        agent_grant = self.service.create_participant("Interrupted agent", "agent", True)
        agent = self.service.authenticate(agent_grant["token"])
        preview, _changes, _moves = self.preview("2026-10-08-first", {"topics/payment-flows.md": TOPIC}, agent)
        original = self.service._apply_write

        class Crash(BaseException):
            pass

        def interrupted(write, **kwargs):
            if write["role"] == "index":
                raise Crash()
            return original(write, **kwargs)

        with patch.object(self.service, "_apply_write", side_effect=interrupted), self.assertRaises(Crash):
            self.service.apply(agent, preview["preview_id"], "interrupted-index")
        self.assertTrue((self.root / "knowledge/wiki/topics/payment-flows.md").exists())
        self.assertNotIn("topics/payment-flows.md", self.index_lines())

        human = self.service.authenticate(self.service.create_participant("Human reviewer", "human", True)["token"])
        self.service.revoke_participant(agent.participant_id)
        inspected = self.service.operation(human, "interrupted-index")
        states = {item["path"]: item["state"] for item in inspected["remaining_changes"]}
        self.assertEqual({INDEX: "pending", LOG: "pending"}, {path: states[path] for path in (INDEX, LOG)})
        extra = "- [Unrelated](SCHEMA.md): Added while the human reviewed."
        (self.root / INDEX).write_text(self.read(INDEX) + "\n" + extra + "\n", encoding="utf-8", newline="\n")
        receipt = self.service.recover(human, "interrupted-index", inspected["recovery_review_revision"], True)
        self.assertEqual("applied", receipt["state"], receipt)
        self.assertIn("topics/payment-flows.md", self.index_lines())
        self.assertIn(extra, self.read(INDEX))
        self.assertEqual(1, self.read(LOG).count(f"preview={preview['preview_id']}"))

    def test_the_status_board_and_the_index_are_both_written_for_a_new_feature(self) -> None:
        feature = _journey_feature_page("F-001", "Document review", "raw", "po", ["knowledge/intake/processed/NAME/note.md"], ["| 1 | Which details? | po | open |"])
        preview, _changes, _moves = self.preview("2026-10-08-first", {"features/F-001-document-review.md": feature})
        roles = {write["path"]: write["role"] for write in preview["writes"]}
        self.assertEqual({"status-board", "index", "log", "canonical"}, set(roles.values()))
        self.assertEqual("status-board", roles[BOARD])
        board = next(write for write in preview["writes"] if write["path"] == BOARD)
        self.assertEqual({"F-001": None}, board["merge"]["expected_rows"])


if __name__ == "__main__":
    unittest.main()
