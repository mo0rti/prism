"""Board core fixes from the 0.7.1 review: released provenance, the exact log entry, malformed review revisions, one tree walk
per list, repair from the browser, a state reset with no window, and the order of the repair and operation-ID checks."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from starlette.testclient import TestClient

from prism_cli import board_store
from prism_cli.board_server import create_app
from prism_cli.board_service import BoardError, BoardService
from prism_cli.board_store import reset_board_state
from prism_cli.wiki_model import read_feature_evidence, row_digest
from prism_cli.workflow_install import apply_install, plan_install
from tests import real_temp  # noqa: F401
from tests import test_lifecycle_model as lifecycle
from tests.board_approval import apply_preview
from tests.test_board_identity import FEATURE, LOG, GatedBoardCase, _Crash
from tests.test_board_identity_transport import API, ORIGIN, _Transport
from tests.test_board_separation import JournalCase, subject

REPO_ROOT = Path(__file__).resolve().parents[1]
LIFECYCLE_FEATURE = lifecycle.FEATURE


class AbandonedDevDoneTests(lifecycle.FlowTests):
    """A `dev-done` that is interrupted before its feature page is written, then abandoned (review finding 1)."""

    def interrupt_dev_done(self, operation: str) -> dict:
        preview = self.skill("dev-done", self.deliver("backend", "in-dev", "dev"))
        self.assertIsInstance(preview.get("approval"), dict, "dev-done is a gated action")
        revision = self.service.get_preview(self.human, preview["preview_id"])["approval"]["review_revision"]
        with patch.object(self.service, "_apply_write", side_effect=_Crash):
            with self.assertRaises(_Crash):
                self.service.apply(self.human, preview["preview_id"], operation, revision, True)
        return preview

    def abandon(self, operation: str) -> dict:
        revision = self.service.operation(self.human, operation)["recovery_review_revision"]
        receipt = self.service.recover(self.human, operation, revision, True, abandon=True)
        self.assertEqual("abandoned", receipt["state"], receipt)
        return receipt

    def provenance(self) -> list[tuple]:
        return self.service.store.connection.execute(
            "SELECT operation_id, kind, item_id, app, generation FROM provenance WHERE board_id = ? ORDER BY operation_id, app",
            (self.service._board_id,),
        ).fetchall()

    def test_an_abandoned_operation_releases_the_evidence_its_page_write_never_landed(self) -> None:
        self.walk_to_dev()
        preview = self.interrupt_dev_done("dev-done-1")
        self.assertEqual([("dev-done-1", "delivery", "F-001", "backend", 1)], self.provenance(), "reserved with the intent")
        # The page is edited directly, so recovery fails and the approver abandons the operation.
        self.put_page(self.read(LIFECYCLE_FEATURE) + "\nA reviewer note added by hand.\n")
        receipt = self.abandon("dev-done-1")
        self.assertEqual([], receipt["applied_paths"])
        self.assertEqual([], self.provenance(), "the journal binds only evidence that exists")
        # The next dev-done for the app applies, and the journal binds its row to the new operation.
        second = self.skill("dev-done", self.deliver("backend", "in-dev", "dev"))
        applied = apply_preview(self.service, self.agent, second, "dev-done-2", approver=self.human)
        self.assertEqual("applied", applied["state"], applied)
        self.assertEqual([("dev-done-2", "delivery", "F-001", "backend", 1)], self.provenance())
        produced = second["produces_evidence"][0]
        found = self.service._producing_operation("delivery", "F-001", "backend", 1, produced["row_digest"])
        self.assertEqual({"status": "match", "operation_id": "dev-done-2"}, found)
        self.assertEqual({self.human.participant_id}, self.service._excluded_approvers("dev-done-2"))
        self.assertEqual(preview["preview_id"], self.service.store.connection.execute("SELECT preview_id FROM operations WHERE operation_id = 'dev-done-1'").fetchone()[0])

    def test_evidence_whose_write_landed_stays_bound_and_the_rest_is_released(self) -> None:
        self.walk_to_dev()
        self.apply_skill("dev-done", self.deliver("backend", "in-dev", "dev"))
        intent = json.loads(self.service.store.connection.execute("SELECT intent_json FROM operations WHERE state = 'applied' ORDER BY created_at DESC LIMIT 1").fetchone()[0])
        self.assertEqual("backend", intent["produces_evidence"][0]["app"])
        self.assertEqual([], self.service._unlanded_provenance(intent, [LIFECYCLE_FEATURE]), "the page landed: the row stays bound")
        self.assertEqual([], self.service._unlanded_provenance(intent, []), "the page still holds the row, so it is not shown absent")
        before = next(write["before"] for write in intent["writes"] if write["path"] == LIFECYCLE_FEATURE)
        self.put_page(before)
        self.assertEqual(intent["produces_evidence"], self.service._unlanded_provenance(intent, []), "the page does not hold the row: released")
        self.assertEqual(intent["produces_evidence"], self.service._unlanded_provenance(intent, ["knowledge/wiki/status-board.md"]))
        self.assertEqual([], self.service._unlanded_provenance(intent, [LIFECYCLE_FEATURE]), "a landed write is kept whatever the page says")
        unrelated = {**intent, "writes": [write for write in intent["writes"] if write["path"] != LIFECYCLE_FEATURE]}
        self.assertEqual([], self.service._unlanded_provenance(unrelated, []), "a row that no write of the operation holds is not released")

    def test_a_repair_binds_the_released_evidence_to_the_abandoned_operation_again(self) -> None:
        self.walk_to_dev()
        self.interrupt_dev_done("dev-done-1")
        failure = BoardError("checks_changed", "Current workflow checks no longer permit this action.", 409)
        revision = self.service.operation(self.human, "dev-done-1")["recovery_review_revision"]
        with patch.object(self.service, "_revalidate_recovery", side_effect=failure):
            self.assertEqual("abandoned", self.service.recover(self.human, "dev-done-1", revision, True, abandon=True)["state"])
        self.assertEqual([], self.provenance())
        repair = self.service.preview_transition(self.human, None, "operation-repair", {"semantic_review_acknowledged": True}, operation_id="dev-done-1")
        self.assertEqual("applied", apply_preview(self.service, self.human, repair, "repair-1")["state"])
        self.assertEqual([("dev-done-1", "delivery", "F-001", "backend", 1)], self.provenance())
        cells = read_feature_evidence(lifecycle._parse_markdown(self.read(LIFECYCLE_FEATURE))[1]).delivery[0].cells
        found = self.service._producing_operation("delivery", "F-001", "backend", 1, row_digest(cells))
        self.assertEqual({"status": "match", "operation_id": "dev-done-1"}, found)
        self.assertEqual({self.human.participant_id}, self.service._excluded_approvers("dev-done-1"))

    def test_a_second_dev_done_while_the_first_is_unresolved_names_the_operation_and_its_state(self) -> None:
        self.walk_to_dev()
        self.interrupt_dev_done("dev-done-1")
        with self.service.store.transaction() as db:
            with self.assertRaises(BoardError) as raised:
                self.service._record_provenance(db, {"produces_evidence": [subject("F-001", "backend", 1, "sha256:other")]}, "dev-done-2", "now")
        error = raised.exception
        self.assertEqual(("evidence_generation_conflict", 409), (error.code, error.status))
        self.assertIn("`dev-done-1`", error.message)
        self.assertIn("`pending`", error.message)
        self.assertEqual(("dev-done-1", "pending"), (error.details["operation_id"], error.details["operation_state"]))

    def interrupt_after_the_page_write(self, operation: str) -> dict:
        """Apply the `dev-done` and stop the process right after its feature page is written."""

        preview = self.skill("dev-done", self.deliver("backend", "in-dev", "dev"))
        revision = self.service.get_preview(self.human, preview["preview_id"])["approval"]["review_revision"]
        original = self.service._apply_write
        written = []

        def stop_after_the_page(write, **kwargs):
            if LIFECYCLE_FEATURE in written:
                raise _Crash()
            written.append(write["path"])
            return original(write, **kwargs)

        with patch.object(self.service, "_apply_write", side_effect=stop_after_the_page):
            with self.assertRaises(_Crash):
                self.service.apply(self.human, preview["preview_id"], operation, revision, True)
        self.assertIn(LIFECYCLE_FEATURE, written)
        return preview

    def test_evidence_that_is_still_on_an_edited_page_stays_bound_and_separation_still_verifies(self) -> None:
        self.walk_to_dev()
        preview = self.interrupt_after_the_page_write("dev-done-1")
        produced = preview["produces_evidence"][0]
        # An unrelated note is appended by hand: the page is now a conflict, but its Delivery row is byte-identical.
        self.put_page(self.read(LIFECYCLE_FEATURE) + "\nAn unrelated note added by hand.\n")
        cells = read_feature_evidence(lifecycle._parse_markdown(self.read(LIFECYCLE_FEATURE))[1]).delivery[0].cells
        self.assertEqual(produced["row_digest"], row_digest(cells))
        self.abandon("dev-done-1")
        self.assertEqual([("dev-done-1", "delivery", "F-001", "backend", 1)], self.provenance(), "the evidence exists, so its binding stays")
        found = self.service._separation_lookup({"kind": "delivery", "item_id": "F-001", "app": "backend", "generation": 1, "row_digest": produced["row_digest"]})
        self.assertEqual(("match", "dev-done-1", [self.human.participant_id]), (found["status"], found["operation_id"], found["excluded"]))
        # A later verification by the approver of the evidence is still refused as separation requires.
        self.assertEqual({self.human.participant_id}, self.service._excluded_approvers("dev-done-1"))

    def test_evidence_edited_away_after_the_crash_is_released(self) -> None:
        self.walk_to_dev()
        self.interrupt_after_the_page_write("dev-done-1")
        intent = json.loads(self.service.store.connection.execute("SELECT intent_json FROM operations WHERE operation_id = 'dev-done-1'").fetchone()[0])
        before = next(write["before"] for write in intent["writes"] if write["path"] == LIFECYCLE_FEATURE)
        self.put_page(before + "\nThe delivery row was removed by hand.\n")
        self.abandon("dev-done-1")
        self.assertEqual([], self.provenance())
        second = self.skill("dev-done", self.deliver("backend", "in-dev", "dev"))
        self.assertEqual("applied", apply_preview(self.service, self.agent, second, "dev-done-2", approver=self.human)["state"])
        self.assertEqual([("dev-done-2", "delivery", "F-001", "backend", 1)], self.provenance())

    def test_a_page_that_cannot_be_inspected_keeps_the_binding(self) -> None:
        self.walk_to_dev()
        self.interrupt_dev_done("dev-done-1")
        intent = json.loads(self.service.store.connection.execute("SELECT intent_json FROM operations WHERE operation_id = 'dev-done-1'").fetchone()[0])
        produced = intent["produces_evidence"]
        self.assertEqual(produced, self.service._unlanded_provenance(intent, []), "the page is readable and has no row: released")
        with patch.object(self.service, "_optional_text", side_effect=OSError("sharing violation")):
            self.assertEqual([], self.service._unlanded_provenance(intent, []), "an unreadable page keeps the binding")
        self.put_page("not a wiki page: the front matter is gone")
        self.assertEqual([], self.service._unlanded_provenance(intent, []), "an unparseable page keeps the binding")
        (self.root / LIFECYCLE_FEATURE).unlink()
        self.assertEqual(produced, self.service._unlanded_provenance(intent, []), "a page that is missing holds no row")

    def assert_binding_kept_after_abandon(self, produced: dict, original_page: str) -> None:
        self.abandon("dev-done-1")
        self.assertEqual([("dev-done-1", "delivery", "F-001", "backend", 1)], self.provenance(), "the page still holds the row: the binding stays")
        # The original table comes back: the evidence still resolves to the operation that produced it, and its approver stays excluded.
        self.put_page(original_page)
        found = self.service._separation_lookup({"kind": "delivery", "item_id": "F-001", "app": "backend", "generation": 1, "row_digest": produced["row_digest"]})
        self.assertEqual(("match", "dev-done-1", [self.human.participant_id]), (found["status"], found["operation_id"], found["excluded"]))
        self.assertEqual({self.human.participant_id}, self.service._excluded_approvers("dev-done-1"))

    def test_a_changed_delivery_header_does_not_release_the_binding(self) -> None:
        self.walk_to_dev()
        preview = self.interrupt_after_the_page_write("dev-done-1")
        original = self.read(LIFECYCLE_FEATURE)
        self.assertIn("| App | Artifact | Contract |", original)
        self.put_page(original.replace("| App | Artifact | Contract |", "| App | Build | Contract |", 1))
        self.assert_binding_kept_after_abandon(preview["produces_evidence"][0], original)

    def test_another_delivery_row_for_the_same_app_does_not_release_the_binding(self) -> None:
        self.walk_to_dev()
        preview = self.interrupt_after_the_page_write("dev-done-1")
        original = self.read(LIFECYCLE_FEATURE)
        row = "| backend | `build:backend#1` | none | Reviewed source record | Review check passed | checked |"
        self.assertIn(row, original)
        other = "| backend | `build:backend#2` | none | Another source record | Another check passed | checked |"
        self.put_page(original.replace(row, f"{other}\n{row}", 1))
        evidence = read_feature_evidence(lifecycle._parse_markdown(self.read(LIFECYCLE_FEATURE))[1])
        self.assertEqual(2, len(evidence.delivery))
        self.assertNotEqual(preview["produces_evidence"][0]["row_digest"], row_digest(evidence.delivery_row("backend").cells), "the first row is not the produced one")
        self.assert_binding_kept_after_abandon(preview["produces_evidence"][0], original)

    def test_a_repeated_section_or_a_malformed_row_keeps_the_binding_and_a_clean_page_without_the_row_releases(self) -> None:
        self.walk_to_dev()
        preview = self.interrupt_after_the_page_write("dev-done-1")
        intent = json.loads(self.service.store.connection.execute("SELECT intent_json FROM operations WHERE operation_id = 'dev-done-1'").fetchone()[0])
        original = self.read(LIFECYCLE_FEATURE)
        row = "| backend | `build:backend#1` | none | Reviewed source record | Review check passed | checked |"
        for label, page in (
            ("a repeated section", original + "\n## Delivery evidence\nNone.\n"),
            ("a short row", original.replace(row, f"| backend | `build:backend#2` |\n{row}", 1)),
        ):
            with self.subTest(label):
                self.put_page(page)
                self.assertEqual([], self.service._unlanded_provenance(intent, []))
        self.put_page(original.replace(row + "\n", "", 1))
        self.assertEqual(preview["produces_evidence"], self.service._unlanded_provenance(intent, []), "a table that parses cleanly and lacks the row releases")

    def put_page(self, content: str) -> None:
        (self.root / LIFECYCLE_FEATURE).write_bytes(content.encode("utf-8"))


# The inherited flow tests belong to FlowTests; this class adds its own.
for _name in [name for name in dir(lifecycle.FlowTests) if name.startswith("test")]:
    setattr(AbandonedDevDoneTests, _name, None)
del _name


class ReviewedLogEntryTests(GatedBoardCase):
    def log_write(self, shown: dict) -> dict:
        return next(write for write in shown["writes"] if write["role"] == "log")

    def test_the_reviewer_sees_the_log_entry_the_apply_writes(self) -> None:
        preview = self.agent_proposal()
        stored = self.log_write(self.service.get_preview(self.agent, preview["preview_id"]))
        self.assertIn(f"by: {self.agent.name} (agent)", stored["after"], "the proposer sees its own entry")
        shown = self.service.get_preview(self.designer, preview["preview_id"])
        entry = self.log_write(shown)
        self.assertIn("approving", entry["after"])
        self.assertIn(self.designer.name, entry["after"])
        self.assertIn(f'"approver_id":"{self.designer.participant_id}"', entry["after"].replace(" ", ""))
        self.assertIn(f'"proposer_id":"{self.agent.participant_id}"', entry["after"].replace(" ", ""))
        revision = shown["approval"]["review_revision"]
        self.assertEqual(revision, self.review(self.designer, preview), "the review revision does not depend on the attribution")
        receipt = self.service.apply(self.designer, preview["preview_id"], "attributed-1", revision, True)
        self.assertEqual("applied", receipt["state"], receipt)
        self.assertEqual(entry["after"], self.read(LOG), "what the reviewer saw is what was written")
        self.assertIn(entry["merge"]["entry"], entry["after"])

    def test_a_human_who_may_not_review_sees_the_stored_entry(self) -> None:
        preview = self.agent_proposal()
        stored = self.log_write(self.service.get_preview(self.agent, preview["preview_id"]))
        self.assertIn("(agent)", stored["merge"]["entry"])
        with self.assertRaises(BoardError) as raised:
            self.service.get_preview(self.po, preview["preview_id"])
        self.assertEqual("preview_not_found", raised.exception.code)


class MalformedReviewRevisionTests(_Transport, GatedBoardCase):
    MALFORMED = ("é" * 71, "sha256:" + "é" * 64, "sha256:abc", "x" * 71, "sha256:" + "A" * 64)

    def test_a_malformed_review_revision_is_approval_review_required(self) -> None:
        preview = self.agent_proposal()
        for index, value in enumerate(self.MALFORMED):
            with self.subTest(value=value):
                self.assertEqual("approval_review_required", self.code(lambda: self.service.apply(self.designer, preview["preview_id"], f"malformed-{index}", value, True)))
        receipt = self.service.apply(self.designer, preview["preview_id"], "valid-1", self.review(self.designer, preview), True)
        self.assertEqual("applied", receipt["state"], receipt)

    def test_a_wrong_but_well_formed_review_revision_is_still_stale(self) -> None:
        preview = self.agent_proposal()
        well_formed = "sha256:" + "0" * 64
        self.assertEqual("stale_approval_review", self.code(lambda: self.service.apply(self.designer, preview["preview_id"], "wrong-1", well_formed, True)))

    def test_over_http_a_malformed_review_revision_is_a_409_and_never_a_500(self) -> None:
        app = create_app(self.root, port=8765, service=self.service)
        with TestClient(app, base_url=ORIGIN) as client:
            changes, revisions = self.agent_changes()
            proposed = client.post(
                f"{API}/previews/skill",
                json={"skill": "design-start", "changes": changes, "read_revisions": revisions},
                headers={"Authorization": "Bearer " + self.tokens["Coding agent"]},
            )
            self.assertEqual(200, proposed.status_code, proposed.text)
            preview_id = proposed.json()["preview_id"]
            exchanged = client.post(f"{API}/auth/exchange", json={"token": self.tokens["Dana"]}, headers={"Origin": ORIGIN})
            headers = {"Origin": ORIGIN, "X-Prism-CSRF": exchanged.json()["csrf_token"]}
            for index, value in enumerate(self.MALFORMED):
                with self.subTest(value=value):
                    response = client.post(
                        f"{API}/apply",
                        json={"preview_id": preview_id, "operation_id": f"http-{index}", "review_revision": value, "semantic_review_acknowledged": True},
                        headers=headers,
                    )
                    self.assertEqual((409, "approval_review_required"), (response.status_code, response.json()["error"]["code"]), response.text)


class McpMalformedReviewRevisionTests(_Transport, GatedBoardCase, unittest.IsolatedAsyncioTestCase):
    """Over MCP the transport restriction answers first, with the same code for a malformed value as for a well-formed one."""

    def error_text(self, result) -> str:
        self.assertTrue(result.is_error, result)
        return " ".join(part.text for part in result.content if getattr(part, "type", None) == "text")

    async def test_a_malformed_review_revision_over_mcp_is_refused_without_an_internal_error(self) -> None:
        app = create_app(self.root, port=8765, service=self.service)
        preview = self.agent_proposal()
        async with app.router.lifespan_context(app):
            transport = httpx2.ASGITransport(app=app)
            for name, expected in (("Dana", "approval_requires_board_session"), ("Coding agent", "approval_required")):
                headers = {"Authorization": "Bearer " + self.tokens[name]}
                async with httpx2.AsyncClient(transport=transport, base_url=ORIGIN, headers=headers) as http:
                    async with streamable_http_client(ORIGIN + "/mcp", http_client=http) as (reader, writer):
                        async with ClientSession(reader, writer) as client:
                            await client.initialize()
                            for index, value in enumerate(MalformedReviewRevisionTests.MALFORMED):
                                result = await client.call_tool(
                                    "apply",
                                    {"preview_id": preview["preview_id"], "operation_id": f"mcp-{name[0]}-{index}", "review_revision": value, "semantic_review_acknowledged": True},
                                )
                                text = self.error_text(result)
                                self.assertIn(expected, text)
                                self.assertNotIn("internal_error", text)
        self.assertIn("status: ready-for-design", self.read(FEATURE), "nothing was approved over a token")


class _AbandonsAnOperation:
    """A gated `design-start` that is interrupted after its first write and then abandoned by the designer."""

    def abandoned_operation(self, operation: str = "pending-1") -> None:
        preview = self.agent_proposal()
        self.crash_after_first_write(self.designer, preview, operation)
        failure = BoardError("checks_changed", "Current workflow checks no longer permit this action.", 409)
        revision = self.service.operation(self.designer, operation)["recovery_review_revision"]
        with patch.object(self.service, "_revalidate_recovery", side_effect=failure):
            self.assertEqual("abandoned", self.service.recover(self.designer, operation, revision, True, abandon=True)["state"])


class AbandonedOperationListingTests(_AbandonsAnOperation, _Transport, GatedBoardCase):
    def listed(self, actor) -> list[dict]:
        return self.service.discover(actor)["abandoned_operations"]

    def test_an_abandoned_operation_is_listed_for_a_permitted_human_with_what_the_repair_control_needs(self) -> None:
        self.assertEqual([], self.listed(self.designer))
        self.abandoned_operation()
        entry, = self.listed(self.designer)
        self.assertEqual(["abandoned_at", "action", "operation_id", "required_roles", "subject"], sorted(entry))
        self.assertEqual(("pending-1", "design-start", "F-001"), (entry["operation_id"], entry["action"], entry["subject"]))
        self.assertEqual({"all_of": ["designer"], "any_of": []}, entry["required_roles"])
        self.assertEqual(self.service.operation(self.designer, "pending-1")["receipt"]["abandoned_at"], entry["abandoned_at"])

    def test_it_is_not_listed_to_an_agent_or_a_grant_without_the_roles(self) -> None:
        self.abandoned_operation()
        outsider = self.human("Olga", "qa")
        read_only = self.human("Rita", None, writable=False)
        for name, actor in (("agent", self.agent), ("po", self.po), ("dev", self.dev), ("outsider", outsider), ("read-only", read_only)):
            with self.subTest(actor=name):
                self.assertEqual([], self.listed(actor))
        successor = self.human("Dora", "designer")
        self.assertEqual(["pending-1"], [item["operation_id"] for item in self.listed(successor)])

    def test_it_is_listed_over_http_and_leaves_the_list_once_its_repair_is_recorded_and_applied(self) -> None:
        self.abandoned_operation()
        app = create_app(self.root, port=8765, service=self.service)
        with TestClient(app, base_url=ORIGIN) as client:
            exchanged = client.post(f"{API}/auth/exchange", json={"token": self.tokens["Dana"]}, headers={"Origin": ORIGIN})
            headers = {"Origin": ORIGIN, "X-Prism-CSRF": exchanged.json()["csrf_token"]}
            over_http = client.get(f"{API}/discover").json()["abandoned_operations"]
            self.assertEqual(self.listed(self.designer), over_http)
            repair = self.service.preview_transition(self.designer, None, "operation-repair", {"semantic_review_acknowledged": True}, operation_id="pending-1")
            self.assertEqual(["pending-1"], [item["operation_id"] for item in self.listed(self.designer)], "a preview alone changes nothing")
            applied = client.post(
                f"{API}/apply",
                json={"preview_id": repair["preview_id"], "operation_id": "repair-1", "review_revision": self.review(self.designer, repair), "semantic_review_acknowledged": True},
                headers=headers,
            )
            self.assertEqual("applied", applied.json()["state"], applied.text)
            self.assertEqual([], client.get(f"{API}/discover").json()["abandoned_operations"])

    def test_the_list_is_bounded(self) -> None:
        self.abandoned_operation()
        row = self.service.store.connection.execute("SELECT * FROM operations WHERE operation_id = 'pending-1'").fetchone()
        columns = [item[0] for item in self.service.store.connection.execute("SELECT * FROM operations LIMIT 0").description]
        with self.service.store.transaction() as db:
            for index in range(25):
                copy = dict(zip(columns, row))
                copy["operation_id"] = f"copy-{index:02d}"
                copy["preview_id"] = f"copy-preview-{index:02d}"
                db.execute(f"INSERT INTO operations({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})", [copy[name] for name in columns])
        self.assertEqual(20, len(self.listed(self.designer)))


class ListingWorkTests(GatedBoardCase):
    def count_validations(self):
        calls = []
        original = self.service.validate_graph_inputs

        def counted(*args, **kwargs):
            calls.append(1)
            return original(*args, **kwargs)

        return calls, patch.object(self.service, "validate_graph_inputs", side_effect=counted)

    def test_discover_and_list_proposals_validate_the_tree_once_per_call(self) -> None:
        proposals = [self.agent_proposal() for _ in range(3)]
        for call in (lambda: self.service.discover(self.designer), lambda: self.service.list_proposals(self.designer), lambda: self.service.list_proposals(self.agent)):
            calls, patcher = self.count_validations()
            with patcher:
                result = call()
            self.assertEqual(1, len(calls))
            listed = result.get("pending_proposals", result.get("proposals"))
            self.assertEqual(sorted(item["preview_id"] for item in proposals), sorted(item["preview_id"] for item in listed))
            self.assertEqual([False, False, False], [item["stale"] for item in listed])

    def test_a_call_with_no_proposal_does_not_walk_the_tree(self) -> None:
        calls, patcher = self.count_validations()
        with patcher:
            self.assertEqual([], self.service.list_proposals(self.designer)["proposals"])
        self.assertEqual([], calls)

    def test_staleness_is_computed_only_for_the_proposals_returned(self) -> None:
        for _ in range(3):
            self.agent_proposal()
        checked = []
        original = self.service._assert_preview_fresh

        def counted(payload, **kwargs):
            checked.append(payload["preview_id"])
            return original(payload, **kwargs)

        with patch.object(self.service, "_assert_preview_fresh", side_effect=counted):
            entries = self.service._proposal_entries(self.designer, limit=2)
        self.assertEqual(2, len(entries))
        self.assertEqual([item["preview_id"] for item in entries], checked)
        self.assertEqual(3, self.service.list_proposals(self.designer)["total"], "the total counts every proposal")

    def test_the_answers_stay_the_same_when_the_proposals_are_stale_or_the_tree_is_unreadable(self) -> None:
        self.agent_proposal()
        self.agent_proposal()
        self.put(FEATURE, self.read(FEATURE) + "\nEdited after the proposals.\n")
        self.assertEqual([True, True], [item["stale"] for item in self.service.list_proposals(self.designer)["proposals"]])
        self.put(FEATURE, self.read(FEATURE).replace("\nEdited after the proposals.\n", ""))
        self.assertEqual([False, False], [item["stale"] for item in self.service.list_proposals(self.designer)["proposals"]])
        unreadable = BoardError("reparse_point", "A linked folder is not allowed.", 409)
        with patch.object(self.service, "validate_graph_inputs", side_effect=unreadable):
            self.assertEqual([True, True], [item["stale"] for item in self.service.list_proposals(self.designer)["proposals"]])


class RepairFromTheBrowserTests(_AbandonsAnOperation, _Transport, GatedBoardCase):
    def login(self, client: TestClient, name: str) -> dict:
        client.cookies.clear()
        response = client.post(f"{API}/auth/exchange", json={"token": self.tokens[name]}, headers={"Origin": ORIGIN})
        self.assertEqual(200, response.status_code, response.text)
        return {"Origin": ORIGIN, "X-Prism-CSRF": response.json()["csrf_token"]}

    def test_the_route_the_repair_button_calls_starts_a_gated_preview_that_proposals_lists(self) -> None:
        self.abandoned_operation()
        # The body the button sends.
        body = {"action": "operation-repair", "operation_id": "pending-1", "inputs": {"semantic_review_acknowledged": True}}
        app = create_app(self.root, port=8765, service=self.service)
        with TestClient(app, base_url=ORIGIN) as client:
            other = self.login(client, "Pat")
            refused = client.post(f"{API}/previews/transition", json=body, headers=other)
            self.assertEqual((403, "role_required"), (refused.status_code, refused.json()["error"]["code"]), "a human without the original roles cannot start it")
            headers = self.login(client, "Dana")
            started = client.post(f"{API}/previews/transition", json=body, headers=headers)
            self.assertEqual(200, started.status_code, started.text)
            preview = started.json()
            self.assertEqual(("operation-repair", True, "awaiting-approval"), (preview["action"], preview["applicable"], preview["approval"]["state"]))
            self.assertEqual({"all_of": ["designer"], "any_of": []}, preview["approval"]["required_roles"])
            listed = client.get(f"{API}/proposals").json()
            self.assertEqual([preview["preview_id"]], [item["preview_id"] for item in listed["proposals"]], "approved from Proposals")
            missing = client.post(f"{API}/previews/transition", json={**body, "operation_id": "no-such-operation"}, headers=headers)
            self.assertEqual((404, "operation_not_found"), (missing.status_code, missing.json()["error"]["code"]))
            shown = client.get(f"{API}/previews/{preview['preview_id']}").json()
            applied = client.post(
                f"{API}/apply",
                json={"preview_id": preview["preview_id"], "operation_id": "repair-1", "review_revision": shown["approval"]["review_revision"], "semantic_review_acknowledged": True},
                headers=headers,
            )
            self.assertEqual(200, applied.status_code, applied.text)
            self.assertEqual(("applied", "pending-1"), (applied.json()["state"], applied.json()["repair_of"]))

    def test_the_repair_preview_is_not_applied_with_a_bearer_token(self) -> None:
        self.abandoned_operation()
        app = create_app(self.root, port=8765, service=self.service)
        with TestClient(app, base_url=ORIGIN) as client:
            bearer = {"Authorization": "Bearer " + self.tokens["Dana"]}
            started = client.post(f"{API}/previews/transition", json={"action": "operation-repair", "operation_id": "pending-1"}, headers=bearer)
            self.assertEqual(200, started.status_code, started.text)
            refused = client.post(f"{API}/apply", json={"preview_id": started.json()["preview_id"], "operation_id": "repair-1", "review_revision": "x", "semantic_review_acknowledged": True}, headers=bearer)
            self.assertEqual((403, "approval_requires_board_session"), (refused.status_code, refused.json()["error"]["code"]))


class RepairControlTemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = (REPO_ROOT / "prism_cli" / "assets" / "graph_template.html").read_text(encoding="utf-8")

    def function(self, name: str) -> str:
        start = self.html.index(f"function {name}(")
        return self.html[start : self.html.index("\nfunction ", start + 1)]

    def test_an_abandoned_operation_has_a_repair_control_that_previews_operation_repair(self) -> None:
        self.assertIn("data-operation-repair", self.html)
        self.assertIn("Repair operation</button>", self.html)
        shown = self.function("renderBoardOperationsDialog")
        self.assertIn('selected.state === "abandoned"', shown)
        self.assertIn("operationRepairHtml(selected", shown)
        self.assertIn("[data-operation-repair]", shown)
        request = self.function("repairBoardOperation")
        self.assertIn('"/api/board/v1/previews/transition"', request)
        self.assertIn('action: "operation-repair"', request)
        self.assertIn("operation_id: operationId", request)
        self.assertIn("openBoardProposals(", request, "the preview is approved from Proposals")
        self.assertNotIn("/api/board/v1/apply", request, "the control never applies")

    def test_a_listed_abandoned_operation_has_the_control_after_a_reload(self) -> None:
        shown = self.function("renderBoardOperationsDialog")
        self.assertIn("preview.abandoned", shown)
        self.assertIn("abandonedOperationRecord(item)", shown)
        self.assertIn("operationRepairHtml(record, preview.loading)", shown)
        self.assertIn("Abandoned operations open to repair", shown)
        self.assertIn("discovery.abandoned_operations", self.html)
        self.assertIn("state.boardAbandonedOperations", self.function("invalidateBoardSession"))
        self.assertIn("abandonedCount", self.function("renderBoardSession"))
        record = self.function("operationRepairRecord")
        self.assertIn("preview.abandoned.find(", record)
        self.assertIn("record.required_roles", self.function("operationRepairAllowed"))

    def test_the_control_is_gated_by_the_original_roles(self) -> None:
        allowed = self.function("operationRepairAllowed")
        self.assertIn("connectedHumanWriter()", allowed)
        self.assertIn("required.all_of", allowed)
        self.assertIn("required.any_of", allowed)
        self.assertIn("state.boardActor.roles", allowed)
        control = self.function("operationRepairHtml")
        self.assertIn("operationRepairAllowed(record)", control)
        self.assertIn('allowed && !loading ? "" : " disabled"', control)
        self.assertIn("!operationRepairAllowed(record)", self.function("repairBoardOperation"))
        self.assertIn("approval: recordedApproval", self.function("recoverBoardOperation"), "an abandoned record keeps the roles of the original")


class StateResetTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        apply_install(self.root, plan_install(self.root, name="Reset", apps=["backend"]))
        with BoardService(self.root) as service:
            service.create_participant("Dana", "human", True, roles="designer")
        self.state = self.root / ".prism" / "state"

    def test_a_reset_removes_the_state_folder_when_nothing_else_is_in_it(self) -> None:
        result = reset_board_state(self.root)
        self.assertTrue(result["reset"])
        self.assertFalse(self.state.exists())
        self.assertTrue(Path(result["audit_export"]).is_file())

    def test_a_file_that_appears_when_the_lock_is_released_is_not_removed_silently(self) -> None:
        released = board_store._release_lock_stream

        def release_then_start_a_server(stream) -> None:
            released(stream)
            (self.state / "board.sqlite3").write_bytes(b"a journal that a board server just created")

        with patch.object(board_store, "_release_lock_stream", side_effect=release_then_start_a_server):
            with self.assertRaises(ValueError) as raised:
                reset_board_state(self.root)
        self.assertIn("changed during the reset", str(raised.exception))
        self.assertEqual(b"a journal that a board server just created", (self.state / "board.sqlite3").read_bytes())

    def test_an_unexpected_file_in_the_state_folder_stops_the_removal(self) -> None:
        (self.state / "notes.txt").write_text("kept", encoding="utf-8")
        with self.assertRaises(ValueError):
            reset_board_state(self.root)
        self.assertEqual("kept", (self.state / "notes.txt").read_text(encoding="utf-8"))
        self.assertFalse((self.state / "board.sqlite3").exists(), "the journal that was exported is gone")


class RepairRecoveryAndOrderTests(_AbandonsAnOperation, GatedBoardCase):
    def test_a_pending_repair_is_revalidated_as_reviewed_on_a_plain_retry(self) -> None:
        self.abandoned_operation()
        repair = self.service.preview_transition(self.designer, None, "operation-repair", {"semantic_review_acknowledged": True}, operation_id="pending-1")
        self.crash_after_first_write(self.designer, repair, "repair-1")
        self.assertEqual("pending", self.service.operation(self.designer, "repair-1")["state"])
        seen = []
        original = BoardService._revalidate_operation

        def recorded(service, actor, payload, **kwargs):
            seen.append(kwargs.get("reviewed"))
            return original(service, actor, payload, **kwargs)

        with patch.object(BoardService, "_revalidate_operation", recorded):
            receipt = self.service.apply(self.designer, repair["preview_id"], "repair-1")
        self.assertEqual("applied", receipt["state"], receipt)
        self.assertTrue(seen, "the retry revalidated the repair")
        self.assertEqual({True}, set(seen), "a repair is revalidated against the live files, as its first apply was")

    def test_a_pending_repair_recovers_after_an_unrelated_read_changed(self) -> None:
        self.abandoned_operation()
        # A source the original proposal read changes after it, before the repair is previewed against the live files.
        schema = "knowledge/wiki/SCHEMA.md"
        self.put(schema, self.read(schema) + "\nA note added after the original proposal.\n")
        repair = self.service.preview_transition(self.designer, None, "operation-repair", {"semantic_review_acknowledged": True}, operation_id="pending-1")
        self.crash_after_first_write(self.designer, repair, "repair-1")
        receipt = self.service.apply(self.designer, repair["preview_id"], "repair-1")
        self.assertEqual("applied", receipt["state"], receipt)

    def test_proposer_revoked_precedes_operation_id_reused(self) -> None:
        preview = self.agent_proposal()
        revision = self.review(self.designer, preview)
        self.assertEqual("applied", self.service.apply(self.designer, preview["preview_id"], "taken-1", revision, True)["state"])
        other = self.human("Dora", "designer")
        self.assertEqual("operation_id_reused", self.code(lambda: self.service.apply(other, preview["preview_id"], "taken-1", revision, True)))
        self.service.revoke_participant(self.agent.participant_id)
        self.assertEqual("proposer_revoked", self.code(lambda: self.service.apply(other, preview["preview_id"], "taken-1", revision, True)))
        # The rightful retry is unaffected: a revoked proposer has no effect once the intent is recorded.
        self.assertEqual("applied", self.service.apply(self.designer, preview["preview_id"], "taken-1", revision, True)["state"])


if __name__ == "__main__":
    unittest.main()
