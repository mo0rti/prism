"""Representative knowledge workflows through the in-process board: ingest, update, decision supersession, conflict.

Each workflow submits complete proposals the way the board tests do, with no agent host, then checks the
resulting workspace with the mechanical lint. The board has no skill that writes an ADR, so the decision
supersession is the direct-file operation that `SCHEMA.md` defines, checked by lint.
"""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

import yaml

from prism_cli.board_service import BoardError, BoardService
from prism_cli.wiki_lint import lint_wiki
from prism_cli.workflow_install import apply_install, plan_install
from tests import real_temp  # noqa: F401
from tests.wiki_files import write_index
from tests.core_workflow_fixture import INTAKE_ITEM, create_core_workflow_fixture
from tests.test_board_service import (
    _journey_business_rule_page,
    _journey_design_page,
    _journey_feature_page,
    _read_revisions,
    _replace_body_section,
    _set_feature_stage,
)

PENDING = INTAKE_ITEM.parent.as_posix()
PROCESSED = PENDING.replace("pending", "processed", 1)
ITEM = PENDING.rsplit("/", 1)[1]
FEATURE_PATH = "knowledge/wiki/features/F-001-document-review.md"
DESIGN_PATH = "knowledge/wiki/design/F-001-document-review.md"
LOG_PATH = "knowledge/wiki/log.md"
ADR_OLD = "knowledge/wiki/decisions/ADR-001-auth-sessions.md"
ADR_NEW = "knowledge/wiki/decisions/ADR-002-auth-tokens.md"

SUMMARY = (
    "Reviewers record a document review with its outcome and follow-up.\n\n"
    f"- **Observed:** Reviewers keep outcomes in informal notes ([review brief](../../intake/processed/{ITEM}/brief.md)).\n"
    "- **Assumed:** A review covers exactly one document.\n"
)
CRITERIA = (
    f"- [ ] **Decided:** A reviewer can record the outcome and the requested follow-up ([review brief](../../intake/processed/{ITEM}/brief.md)).\n"
    "- [ ] **Proposed:** The summary lists the key points.\n"
)

CONFLICT = """---
status: open
---

# Conflict: recording outcomes

## Existing claim
- **Claim:** A reviewer can record the outcome and the requested follow-up.
- **Scope:** Document review feature F-001, every reviewer.
- **Evidence:** [F-001 feature page](../../../wiki/features/F-001-document-review.md)

## Incoming claim
- **Claim:** Reviewers must not record outcomes in the product.
- **Scope:** Document review feature F-001, every reviewer.
- **Evidence:** [contradicting note](note.md)

## Decision needed
Whether reviewers record outcomes in the product.
"""


class BoardWorkspaceCase(unittest.TestCase):
    """A generated workflow workspace served by an in-process board, with one agent and one human participant."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = create_core_workflow_fixture(Path(temporary.name) / "generated-project")
        install = plan_install(self.root, name="Document review", apps=["backend"])
        self.assertEqual([], install["conflicts"])
        self.assertEqual("applied", apply_install(self.root, install)["status"])
        manifest_path = self.root / "prism.workspace.yml"
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        manifest["generated_by"] = {"tool": "fixture"}
        manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
        install = plan_install(self.root, name="Document review", apps=["backend"])
        self.assertEqual([], install["conflicts"])
        self.assertEqual("applied", apply_install(self.root, install)["status"])
        # The installer adds pages to a wiki whose index it preserves; this workspace's index lists them all.
        write_index(self.root)

        self.service = BoardService(self.root).start()
        self.addCleanup(self.service.close)
        self.agent = self.service.authenticate(self.service.create_participant("Workflow agent", "agent", True)["token"])

    # -- helpers -------------------------------------------------------------------------------------

    def read(self, relative: str) -> str:
        return (self.root / relative).read_text(encoding="utf-8")

    def snapshot(self, relative: str) -> dict[str, bytes]:
        base = self.root / relative
        return {path.relative_to(base).as_posix(): path.read_bytes() for path in sorted(base.rglob("*")) if path.is_file()}

    def submit(self, skill: str, changes: list[dict[str, str]], moves: list[dict[str, str]] | None = None) -> dict:
        preview = self.service.preview_skill(
            self.agent, skill, changes, moves, _read_revisions(self.service, self.agent, skill, changes, moves)
        )
        self.assertEqual("ready", preview["classification"], f"{skill}: {preview['checks']}")
        self.assertTrue(preview["applicable"], f"{skill}: {preview['blockers']}")
        receipt = self.service.apply(self.agent, preview["preview_id"], str(uuid4()))
        self.assertEqual("applied", receipt["state"], f"{skill}: {receipt}")
        return receipt

    def rejected(self, skill: str, changes: list[dict[str, str]], moves: list[dict[str, str]] | None = None) -> BoardError:
        with self.assertRaises(BoardError) as caught:
            self.service.preview_skill(
                self.agent, skill, changes, moves, _read_revisions(self.service, self.agent, skill, changes, moves)
            )
        return caught.exception

    def lint(self):
        return lint_wiki(self.root)

    def assert_lint_clean(self) -> None:
        result = self.lint()
        self.assertEqual([], [item.to_dict() for item in result.diagnostics])

    def log_entries(self) -> list[dict[str, str]]:
        entries = []
        for block in re.split(r"(?m)^(?=## )", self.read(LOG_PATH)):
            heading = re.match(r"## (\d{4}-\d{2}-\d{2}) (\S+) \| (.*)", block)
            if heading is None:
                continue
            fields = dict(re.findall(r"(?m)^- (paths|evidence|by): (.*)$", block))
            entries.append({"date": heading.group(1), "operation": heading.group(2), "subject": heading.group(3), **fields})
        return entries

    def drop_pending(self, name: str, text: str = "Captured: 2026-10-08\n\nA note.\n") -> str:
        folder = f"knowledge/intake/pending/{name}"
        (self.root / folder).mkdir(parents=True)
        (self.root / folder / "note.md").write_text(text, encoding="utf-8")
        return folder

    def ingest_feature(self, *, summary: str = SUMMARY, criteria: str = CRITERIA) -> None:
        """Process the pending review brief into the raw feature F-001, with labeled and linked claims."""

        page = _journey_feature_page(
            "F-001", "Document review", "raw", "po", [f"{PROCESSED}/brief.md"], ["| 1 | Which details should the summary emphasize? | po | open |"]
        )
        page = _replace_body_section(self.service, page, "Summary", summary)
        page = _replace_body_section(self.service, page, "Acceptance criteria", criteria)
        self.submit(
            "po-intake",
            [
                {"path": FEATURE_PATH, "content": page},
                {"path": f"{PROCESSED}/MANIFEST.md", "content": f"# Processed intake\n\n- {FEATURE_PATH} (F-001)\n"},
            ],
            [{"source": PENDING, "destination": PROCESSED}],
        )

    def specify_feature(self) -> None:
        current = self.read(FEATURE_PATH)
        self.submit("po-specify", [{"path": FEATURE_PATH, "content": _set_feature_stage(current, "specified", "po", self.service)}])


class IngestWorkflowTests(BoardWorkspaceCase):
    def test_a_po_intake_creates_a_feature_with_labeled_linked_claims_and_lint_is_clean(self) -> None:
        brief_before = (self.root / PENDING / "brief.md").read_bytes()
        self.ingest_feature()

        self.assertFalse((self.root / PENDING).exists())
        self.assertEqual(brief_before, (self.root / PROCESSED / "brief.md").read_bytes())
        self.assertTrue((self.root / PROCESSED / "MANIFEST.md").is_file())
        page = self.read(FEATURE_PATH)
        self.assertIn("**Observed:**", page)
        self.assertIn(f"](../../intake/processed/{ITEM}/brief.md)", page)
        self.assertNotIn("/intake/pending/", page)
        self.assert_lint_clean()

        entry = self.log_entries()[-1]
        self.assertEqual("board-po-intake", entry["operation"])
        self.assertEqual("F-001", entry["subject"])
        self.assertIn(FEATURE_PATH, entry["paths"])
        self.assertIn(f"{PROCESSED}/MANIFEST.md", entry["paths"])
        self.assertIn(PROCESSED, entry["evidence"])

    def test_the_board_requires_the_dated_name_for_the_folder_it_moves(self) -> None:
        folder = self.drop_pending("client-call")
        destination = folder.replace("pending", "processed", 1)
        page = _journey_feature_page("F-001", "Document review", "raw", "po", [], ["| 1 | Which details? | po | open |"])
        changes = [
            {"path": FEATURE_PATH, "content": page},
            {"path": f"{destination}/MANIFEST.md", "content": f"# Processed intake\n\n- {FEATURE_PATH} (F-001)\n"},
        ]
        error = self.rejected("po-intake", changes, [{"source": folder, "destination": destination}])
        self.assertEqual(("intake_name_invalid", 409), (error.code, error.status))
        self.assertEqual(destination, error.details["path"])
        self.assertTrue((self.root / folder).is_dir())
        self.assertFalse((self.root / FEATURE_PATH).exists())

        for name in ("2026-13-01-client-call", "2026-10-08-Client-Call", "2026-10-08"):
            with self.subTest(name=name):
                folder = self.drop_pending(name)
                destination = folder.replace("pending", "processed", 1)
                error = self.rejected(
                    "po-intake",
                    [{"path": f"{destination}/MANIFEST.md", "content": f"# Processed intake\n\n- {FEATURE_PATH} (F-001)\n"}, {"path": FEATURE_PATH, "content": page}],
                    [{"source": folder, "destination": destination}],
                )
                self.assertEqual("intake_name_invalid", error.code)

    def test_a_design_intake_needs_a_manifest_that_lists_its_pages(self) -> None:
        self.ingest_feature()
        self.specify_feature()
        folder = self.drop_pending("2026-10-08-design-notes")
        destination = folder.replace("pending", "processed", 1)
        feature = _replace_body_section(self.service, self.read(FEATURE_PATH), "Design", "[Document review design](../design/F-001-document-review.md)")
        changes = [{"path": FEATURE_PATH, "content": feature}, {"path": DESIGN_PATH, "content": _journey_design_page()}]
        moves = [{"source": folder, "destination": destination}]
        error = self.rejected("design-intake", changes, moves)
        self.assertEqual("intake_manifest_scope", error.code)
        incomplete = [*changes, {"path": f"{destination}/MANIFEST.md", "content": "# Processed intake\n\nNothing listed.\n"}]
        self.assertEqual("intake_manifest_incomplete", self.rejected("design-intake", incomplete, moves).code)
        complete = [*changes, {"path": f"{destination}/MANIFEST.md", "content": f"# Processed intake\n\n- {DESIGN_PATH}\n- {FEATURE_PATH} (F-001)\n"}]
        self.submit("design-intake", complete, moves)
        self.assertTrue((self.root / destination / "MANIFEST.md").is_file())


class UpdateWorkflowTests(BoardWorkspaceCase):
    FIRST = "2026-10-07-design-notes"
    SECOND = "2026-10-09-design-revision"

    def design_page(self, claim: str) -> str:
        return _journey_design_page().replace("Keep the review outcome beside the source document.", claim)

    def design_intake(self, name: str, claim: str, feature_claim: str, text: str) -> None:
        folder = self.drop_pending(name, text)
        destination = folder.replace("pending", "processed", 1)
        feature = _replace_body_section(
            self.service, self.read(FEATURE_PATH), "Design", f"[Document review design](../design/F-001-document-review.md)\n\n{feature_claim}"
        )
        self.submit(
            "design-intake",
            [
                {"path": FEATURE_PATH, "content": feature},
                {"path": DESIGN_PATH, "content": self.design_page(claim)},
                {"path": f"{destination}/MANIFEST.md", "content": f"# Processed intake\n\n- {DESIGN_PATH}\n- {FEATURE_PATH} (F-001)\n"},
            ],
            [{"source": folder, "destination": destination}],
        )

    def test_a_later_intake_replaces_a_fact_in_place_and_the_log_lists_paths_and_evidence(self) -> None:
        self.ingest_feature()
        self.specify_feature()
        first_link = f"../../intake/processed/{self.FIRST}/note.md"
        second_link = f"../../intake/processed/{self.SECOND}/note.md"
        self.design_intake(
            self.FIRST,
            f"- **Decided:** The outcome sits beside the source document ([design notes]({first_link})).",
            f"- **Decided:** The outcome sits beside the source document ([design notes]({first_link})).",
            "Captured: 2026-10-07\n\nShow the outcome beside the document.\n",
        )
        self.assert_lint_clean()
        first_item = self.snapshot(f"knowledge/intake/processed/{self.FIRST}")
        self.assertEqual({"MANIFEST.md", "note.md"}, set(first_item))

        self.design_intake(
            self.SECOND,
            f"- **Decided:** The outcome sits below the summary ([design revision]({second_link})).",
            f"- **Decided:** The outcome sits below the summary ([design revision]({second_link})).",
            "Captured: 2026-10-09\n\nShow the outcome below the summary.\n",
        )

        for path in (DESIGN_PATH, FEATURE_PATH):
            page = self.read(path)
            self.assertIn("The outcome sits below the summary", page, path)
            self.assertIn(second_link, page, path)
            self.assertNotIn("beside the source document", page, path)
            self.assertNotIn(first_link, page, path)
        # The superseded source is untouched: it stays the record of what was captured then.
        self.assertEqual(first_item, self.snapshot(f"knowledge/intake/processed/{self.FIRST}"))
        self.assert_lint_clean()

        entry = self.log_entries()[-1]
        self.assertEqual("board-design-intake", entry["operation"])
        self.assertEqual("F-001", entry["subject"])
        for path in (DESIGN_PATH, FEATURE_PATH, f"knowledge/intake/processed/{self.SECOND}/MANIFEST.md"):
            self.assertIn(path, entry["paths"])
        self.assertIn(f"knowledge/intake/processed/{self.SECOND}", entry["evidence"])

    def test_a_processed_item_is_immutable_on_the_board(self) -> None:
        self.ingest_feature()
        self.specify_feature()
        first_link = f"../../intake/processed/{self.FIRST}/note.md"
        claim = f"- **Decided:** The outcome sits beside the source document ([design notes]({first_link}))."
        self.design_intake(self.FIRST, claim, claim, "Captured: 2026-10-07\n\nShow the outcome beside the document.\n")
        item = f"knowledge/intake/processed/{self.FIRST}"
        before = self.snapshot(item)
        feature = self.read(FEATURE_PATH)
        manifest = {"path": f"{item}/MANIFEST.md", "content": "# Processed intake\n\nRewritten.\n"}

        # A change inside the existing item, with or without a move.
        error = self.rejected("design-intake", [{"path": FEATURE_PATH, "content": feature}, {"path": DESIGN_PATH, "content": self.read(DESIGN_PATH)}, manifest])
        self.assertEqual(("processed_source_immutable", 409), (error.code, error.status))
        self.assertEqual({"path": manifest["path"], "item": item}, error.details)
        self.assertIn("YYYY-MM-DD-slug", error.message)

        # A move onto an existing processed item.
        folder = self.drop_pending(self.FIRST)
        error = self.rejected(
            "design-intake",
            [{"path": FEATURE_PATH, "content": feature}, {"path": DESIGN_PATH, "content": self.read(DESIGN_PATH)}],
            [{"source": folder, "destination": item}],
        )
        self.assertEqual("processed_source_immutable", error.code)

        self.assertEqual(before, self.snapshot(item))
        self.assertTrue((self.root / folder).is_dir())


class DecisionSupersessionWorkflowTests(BoardWorkspaceCase):
    OLD_ADR = (
        "---\nid: ADR-001\ntitle: Sessions for sign-in\ndate: 2026-09-01\nstatus: accepted\n---\n\n"
        "## Context\nReviewers sign in from one browser.\n\n## Decision\nUse server sessions.\n\n"
        "## Rationale\nThe simplest option.\n\n## Consequences\nSessions expire with the browser.\n"
    )
    NEW_ADR = (
        "---\nid: ADR-002\ntitle: Tokens for sign-in\ndate: 2026-10-08\nstatus: accepted\nsupersedes: ADR-001\n---\n\n"
        "## Context\nReviewers also sign in from a mobile app.\n\n## Decision\nUse signed tokens.\n\n"
        "## Rationale\nTokens work on both clients.\n\n## Consequences\nTokens need revocation.\n"
    )

    def write(self, relative: str, text: str) -> None:
        (self.root / relative).write_text(text, encoding="utf-8", newline="\n")

    def body(self, relative: str) -> str:
        return self.read(relative).split("\n---\n", 1)[1]

    def supersede(self) -> None:
        """The decision-supersession workflow of SCHEMA.md as one direct-file operation."""

        old = self.read(ADR_OLD)
        old = old.replace("status: accepted\n", "status: superseded\nsuperseded-by: ADR-002\n", 1)
        self.write(ADR_OLD, old)
        self.write(ADR_NEW, self.NEW_ADR)
        feature = self.read(FEATURE_PATH).replace("ADR-001-auth-sessions.md", "ADR-002-auth-tokens.md").replace("sessions ([ADR-001]", "signed tokens ([ADR-002]")
        self.write(FEATURE_PATH, feature)
        log = self.read(LOG_PATH).rstrip("\n")
        self.write(
            LOG_PATH,
            f"{log}\n\n## 2026-10-08 decision-supersession | ADR-002\n- paths: {ADR_OLD}, {ADR_NEW}, {FEATURE_PATH}, knowledge/wiki/index.md\n- evidence: {ADR_NEW}\n- by: Claude Code (confirmed by the maintainer)\n",
        )
        write_index(self.root)

    def start(self) -> None:
        self.write(ADR_OLD, self.OLD_ADR)
        write_index(self.root)
        claim = "- **Decided:** Sign-in uses server sessions ([ADR-001](../decisions/ADR-001-auth-sessions.md)).\n"
        self.ingest_feature(summary=SUMMARY + claim)
        self.assert_lint_clean()
        self.assertIn("ADR-001", self.read(FEATURE_PATH))

    def test_the_supersession_sets_both_links_keeps_the_old_body_and_moves_the_citation(self) -> None:
        self.start()
        old_body = self.body(ADR_OLD)
        self.supersede()

        old = self.read(ADR_OLD)
        self.assertIn("status: superseded\nsuperseded-by: ADR-002\n", old)
        self.assertIn("supersedes: ADR-001\n", self.read(ADR_NEW))
        self.assertEqual(old_body, self.body(ADR_OLD))
        feature = self.read(FEATURE_PATH)
        self.assertIn("ADR-002-auth-tokens.md", feature)
        self.assertNotIn("ADR-001", feature)
        self.assert_lint_clean()

    def test_each_broken_variant_has_its_code(self) -> None:
        self.start()
        self.supersede()
        good = {path: self.read(path) for path in (ADR_OLD, ADR_NEW, FEATURE_PATH)}

        def reset() -> None:
            for path, text in good.items():
                self.write(path, text)

        # The new ADR does not name the old one.
        self.write(ADR_NEW, good[ADR_NEW].replace("supersedes: ADR-001\n", ""))
        found = [item for item in self.lint().diagnostics if item.code == "supersession-mismatch"]
        self.assertEqual(("error", ADR_OLD.rsplit("/", 1)[1]), (found[0].severity, Path(found[0].path).name))
        self.assertFalse(self.lint().is_clean)
        reset()

        # The old ADR is not marked superseded.
        self.write(ADR_OLD, good[ADR_OLD].replace("status: superseded\nsuperseded-by: ADR-002\n", "status: accepted\n"))
        found = [item for item in self.lint().diagnostics if item.code == "supersession-mismatch"]
        self.assertEqual([ADR_NEW.rsplit("/", 1)[1]], [Path(item.path).name for item in found])
        reset()

        # The links name different ADRs.
        self.write(ADR_OLD, good[ADR_OLD].replace("superseded-by: ADR-002", "superseded-by: ADR-005"))
        self.assertTrue([item for item in self.lint().diagnostics if item.code == "supersession-mismatch"])
        reset()

        # A current-state page still cites the superseded ADR: a warning, not an error.
        self.write(FEATURE_PATH, good[FEATURE_PATH].replace("ADR-002-auth-tokens.md", "ADR-001-auth-sessions.md"))
        result = self.lint()
        found = [item for item in result.diagnostics if item.code == "superseded-decision-cited"]
        self.assertEqual(1, len(found), result.diagnostics)
        self.assertEqual("warning", found[0].severity)
        self.assertEqual(FEATURE_PATH.rsplit("/", 1)[1], Path(found[0].path).name)
        self.assertIn("ADR-002", found[0].message)
        self.assertTrue(result.is_clean)
        reset()
        self.assert_lint_clean()


class ConflictWorkflowTests(BoardWorkspaceCase):
    def setUp(self) -> None:
        super().setUp()
        self.ingest_feature()
        self.name = "2026-10-08-contradicting-note"
        self.folder = self.drop_pending(self.name, "Captured: 2026-10-08\n\nReviewers must not record outcomes in the product.\n")
        self.quarantined = self.folder.replace("pending", "quarantined", 1)
        self.moves = [{"source": self.folder, "destination": self.quarantined}]

    def conflict_change(self, text: str = CONFLICT) -> dict[str, str]:
        return {"path": f"{self.quarantined}/CONFLICT.md", "content": text}

    def test_a_contradicting_source_is_quarantined_and_the_page_is_untouched(self) -> None:
        wiki_before = {path: self.read(path) for path in (FEATURE_PATH, "knowledge/wiki/index.md")}
        feature_bytes = (self.root / FEATURE_PATH).read_bytes()
        note = (self.root / self.folder / "note.md").read_bytes()

        self.submit("po-intake", [self.conflict_change()], self.moves)

        self.assertFalse((self.root / self.folder).exists())
        self.assertEqual(note, (self.root / self.quarantined / "note.md").read_bytes())
        self.assertEqual(feature_bytes, (self.root / FEATURE_PATH).read_bytes())
        self.assertEqual(wiki_before["knowledge/wiki/index.md"], self.read("knowledge/wiki/index.md"))
        result = self.lint()
        self.assertEqual(["unresolved-conflict"], [item.code for item in result.diagnostics])
        found = result.diagnostics[0]
        self.assertEqual("warning", found.severity)
        self.assertEqual(Path(self.quarantined) / "CONFLICT.md", Path(found.path).resolve().relative_to(self.root.resolve()))
        self.assertIn(f"{self.quarantined}/CONFLICT.md", found.message)
        self.assertTrue(result.is_clean)
        entry = self.log_entries()[-1]
        self.assertEqual(f"{self.quarantined}/CONFLICT.md", entry["paths"])

    def test_a_quarantine_must_be_a_valid_open_conflict_and_change_no_page(self) -> None:
        feature = self.read(FEATURE_PATH)
        cases = {
            "resolved": (self.conflict_change(CONFLICT.replace("status: open", "status: resolved") + "\n## Resolution\nDone.\n"), "conflict_report_invalid"),
            "no incoming claim": (self.conflict_change(CONFLICT.replace("## Incoming claim", "## Other")), "conflict_report_invalid"),
            "no front matter": (self.conflict_change(CONFLICT.split("---\n", 2)[2]), "conflict_report_invalid"),
            "evidence without a link": (self.conflict_change(CONFLICT.replace("[contradicting note](note.md)", "the note")), "conflict_report_invalid"),
            "too short": (self.conflict_change("---\nstatus: open\n---\n"), "quarantine_write_scope"),
        }
        for label, (change, code) in cases.items():
            with self.subTest(label):
                error = self.rejected("po-intake", [change], self.moves)
                self.assertEqual((code, 409), (error.code, error.status))
                self.assertTrue((self.root / self.folder).is_dir())
                self.assertFalse((self.root / self.quarantined).exists())

        edited = feature.replace("The summary lists the key points.", "Changed by the quarantine.")
        # The contradicted page cannot change (an existing feature is never rewritten by intake), and nothing
        # but the conflict record may be written beside it.
        error = self.rejected("po-intake", [self.conflict_change(), {"path": FEATURE_PATH, "content": edited}], self.moves)
        self.assertEqual(("intake_existing_feature", 409), (error.code, error.status))
        self.assertEqual(feature, self.read(FEATURE_PATH))
        rule = _journey_business_rule_page().replace("2026-10-06-document-review-brief", ITEM)
        error = self.rejected(
            "po-intake", [self.conflict_change(), {"path": "knowledge/wiki/business-rules/BR-001-review-record.md", "content": rule}], self.moves
        )
        self.assertEqual(("quarantine_write_scope", 409), (error.code, error.status))
        self.assertFalse((self.root / "knowledge/wiki/business-rules/BR-001-review-record.md").exists())

        misnamed = self.drop_pending("contradicting-note")
        moves = [{"source": misnamed, "destination": misnamed.replace("pending", "quarantined", 1)}]
        error = self.rejected("po-intake", [{"path": f"{moves[0]['destination']}/CONFLICT.md", "content": CONFLICT}], moves)
        self.assertEqual("intake_name_invalid", error.code)

    def test_after_the_human_resolves_it_lint_is_clean(self) -> None:
        self.submit("po-intake", [self.conflict_change()], self.moves)
        self.assertEqual(["unresolved-conflict"], [item.code for item in self.lint().diagnostics])

        # The human chooses to keep the existing claim and reword one criterion; both edits are direct.
        feature = self.read(FEATURE_PATH).replace("The summary lists the key points.", "The summary lists the key points and the outcome.")
        (self.root / FEATURE_PATH).write_text(feature, encoding="utf-8", newline="\n")
        report = self.root / self.quarantined / "CONFLICT.md"
        resolved = CONFLICT.replace("status: open", "status: resolved") + (
            "\n## Resolution\nThe existing claim holds. The acceptance criterion was reworded in "
            "[F-001](../../../wiki/features/F-001-document-review.md).\n"
        )
        report.write_text(resolved, encoding="utf-8", newline="\n")
        self.assert_lint_clean()


if __name__ == "__main__":
    unittest.main()
