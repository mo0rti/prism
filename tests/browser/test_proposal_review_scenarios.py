"""Scenario R: the approval view shows what is approved, and reports what the service did.

A human who holds the role opens an agent's gated proposal in the Proposals dialog. The dialog renders the exact before and
after text of every write before the acknowledgement can be given (finding 5), and it reports success only for an `applied`
receipt: a conflict receipt keeps the operation ID, the completed writes and the recovery controls in view (finding 7).
"""

from __future__ import annotations

import json
import re
import time
import unittest
from unittest.mock import patch

from tests.browser.agent_client import AgentClient
from tests.browser.board_page import expect
from tests.browser.harness import FEATURES_BY_ID, requires_browser_e2e
from tests.browser.scenario_support import BOARD_PATH, ScenarioCase, workspace_tree
from tests.browser.test_proposal_scenarios import hand_off

PREVIEW_URL = re.compile(r".*/api/board/v1/previews/[^/?]+(\?.*)?$")
ACKNOWLEDGEMENT = re.compile(r"^I reviewed this change")


@requires_browser_e2e
class ProposalReviewTests(ScenarioCase):
    def propose(self) -> tuple[str, dict]:
        feature = FEATURES_BY_ID["F-001"]
        path = feature.path.as_posix()
        self.harness.add_participant("po", "human", roles="po")
        with AgentClient(self.harness.url, self.harness.token("agent")) as agent:
            proposal = agent.propose("po-handoff", path, hand_off)
        self.assertTrue(proposal["applicable"], proposal)
        return path, proposal

    def board_row(self, feature_id: str) -> str:
        return next(line for line in self.harness.read(BOARD_PATH).splitlines() if line.startswith(f"| {feature_id} "))

    def open_proposal(self, board) -> object:
        self.open_board(board)
        board.proposals_button().click()
        dialog = self.page.get_by_role("dialog", name="Proposals waiting for approval")
        expect(dialog).to_be_visible()
        return dialog

    def test_scenario_r1_the_approval_view_shows_the_changed_text_before_the_acknowledgement_is_enabled(self) -> None:
        with self.scenario("R1-approval-view-shows-the-change") as run:
            page = self.page
            path, _proposal = self.propose()
            clean = workspace_tree(self.harness.root)
            board = self.sign_in("po")
            dialog = self.open_proposal(board)

            # The service answers a preview without its write set: nothing is shown, so nothing can be acknowledged.
            def without_writes(route) -> None:
                response = route.fetch()
                payload = response.json()
                payload.pop("writes", None)
                route.fulfill(status=response.status, headers={"content-type": "application/json"}, body=json.dumps(payload))

            page.route(PREVIEW_URL, without_writes)
            dialog.get_by_role("button", name="Review", exact=True).click()
            expect(dialog.get_by_role("heading", name="Approve po-handoff")).to_be_visible()
            expect(dialog).to_contain_text("The service did not return an exact write set.")
            expect(dialog.get_by_role("checkbox", name=ACKNOWLEDGEMENT)).to_be_disabled()
            expect(dialog.get_by_role("button", name="Approve and apply")).to_be_disabled()
            run.screenshot(page, "approval-without-changes")
            page.unroute(PREVIEW_URL)

            # The real preview renders the exact text of every write, escaped, and then the acknowledgement can be given.
            dialog.get_by_role("button", name="Review", exact=True).click()
            expect(dialog.get_by_role("heading", name=re.compile(r"^Exact file changes · 3$"))).to_be_visible()
            expect(dialog.locator("details.connected-write > summary").filter(has_text=f"{path} · canonical")).to_be_visible()
            changes = dialog.locator("details.connected-write pre")
            expect(changes.filter(has_text="status: specified")).not_to_have_count(0)
            expect(changes.filter(has_text="status: ready-for-design")).not_to_have_count(0)
            expect(changes.filter(has_text="owner: tech-lead")).not_to_have_count(0)
            acknowledgement = dialog.get_by_role("checkbox", name=ACKNOWLEDGEMENT)
            expect(acknowledgement).to_be_enabled()
            expect(dialog.get_by_role("button", name="Approve and apply")).to_be_disabled()
            acknowledgement.check()
            expect(dialog.get_by_role("button", name="Approve and apply")).to_be_enabled()
            run.screenshot(page, "approval-with-changes")
            self.assertEqual(clean, workspace_tree(self.harness.root), "reviewing writes nothing")
            run.effect("the dialog showed the before and after text of the proposed page before the acknowledgement could be given")
            self.assertEqual([], self.page_errors)

    def test_scenario_r2_a_conflict_receipt_is_not_reported_as_applied(self) -> None:
        with self.scenario("R2-conflict-receipt-is-not-applied") as run:
            page = self.page
            harness = self.harness
            path, _proposal = self.propose()
            board = self.sign_in("po")
            po_actor = harness.actor("po")
            dialog = self.open_proposal(board)
            dialog.get_by_role("button", name="Review", exact=True).click()
            expect(dialog.get_by_role("heading", name="Approve po-handoff")).to_be_visible()
            dialog.get_by_role("checkbox", name=re.compile(r"^I reviewed this change")).check()

            service = harness.service
            original = service._apply_write

            def fail_on_the_status_board(write, **kwargs):
                if write["role"] == "status-board":
                    raise OSError("the disk refused the write")
                return original(write, **kwargs)

            with patch.object(service, "_apply_write", side_effect=fail_on_the_status_board):
                dialog.get_by_role("button", name="Approve and apply").click()
                outcome = dialog.locator("[data-proposal-outcome]")
                expect(outcome).to_be_visible()
            expect(dialog.get_by_text("Proposal approved and applied.")).to_have_count(0)
            expect(outcome).to_contain_text("Operation conflict")
            expect(outcome).to_contain_text("filesystem error: OSError")
            expect(outcome.locator(".transition-check.pass", has_text=path)).to_be_visible()
            pending = harness.service.discover(po_actor)["pending_operations"]
            self.assertEqual(1, len(pending), pending)
            operation_id = pending[0]["operation_id"]
            expect(outcome).to_contain_text(operation_id)
            run.screenshot(page, "conflict-receipt")
            # The feature page was written and the status board was not: the view says what is half done.
            self.assertIn("status: ready-for-design", harness.read(path))
            self.assertIn("| specified |", self.board_row("F-001"))
            run.effect("the dialog showed the conflict, the operation ID and the page that was written; it did not say applied")

            # The recovery controls act on the same operation, and with the disk healthy the recovery finishes it.
            dialog.get_by_role("button", name="Inspect and recover this operation").click()
            operations = page.get_by_role("dialog", name="Review pending operations")
            expect(operations).to_be_visible()
            expect(operations).to_contain_text("Operation record · conflict")
            expect(operations).to_contain_text(operation_id)
            operations.get_by_role("checkbox", name=re.compile(r"^I inspected the original actor")).check()
            operations.get_by_role("button", name="Recover recorded operation").click()
            deadline = time.monotonic() + 20
            state = ""
            while time.monotonic() < deadline:
                state = harness.service.operation(po_actor, operation_id)["state"]
                if state == "applied":
                    break
                time.sleep(0.2)
            self.assertEqual("applied", state)
            self.assertIn("| ready-for-design |", self.board_row("F-001"))
            run.effect("the recovery controls finished the same operation")
            self.assertEqual([], self.page_errors)


if __name__ == "__main__":
    unittest.main()
