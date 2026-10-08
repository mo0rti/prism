"""Scenario P: a human who holds the role approves an agent's gated proposal in the board page.

An agent proposes `po-handoff` through the real MCP client and cannot apply it. A human grant that holds `po` signs in to the
page, finds the proposal in the Proposals dialog, reads it, acknowledges it and approves it. The feature page, the status
board and the log change as the preview said, and the record names the approving human and the proposing agent.
"""

from __future__ import annotations

import re
import unittest

import yaml

from tests.browser.agent_client import AgentClient, AgentToolError
from tests.browser.board_page import expect
from tests.browser.harness import FEATURES_BY_ID, requires_browser_e2e
from tests.browser.scenario_support import BOARD_PATH, LOG_PATH, UUID, ScenarioCase, changed_paths, workspace_tree


def hand_off(text: str) -> str:
    """What an agent's `po-handoff` proposes: the feature moves to design under the design owner of its scope (no UI: the tech lead)."""

    return text.replace("status: specified\n", "status: ready-for-design\n", 1).replace("owner: po\n", "owner: tech-lead\n", 1)


@requires_browser_e2e
class ProposalApprovalTests(ScenarioCase):
    def test_scenario_p_a_human_with_the_role_approves_an_agents_po_handoff(self) -> None:
        with self.scenario("P-proposal-approval") as run:
            page = self.page
            harness = self.harness
            feature = FEATURES_BY_ID["F-001"]
            path = feature.path.as_posix()
            harness.add_participant("po", "human", roles="po")
            agent_actor = harness.actor("agent")
            po_actor = harness.actor("po")

            clean = workspace_tree(harness.root)
            with AgentClient(harness.url, harness.token("agent")) as agent:
                proposal = agent.propose("po-handoff", path, hand_off)
                self.assertTrue(proposal["applicable"], proposal)
                self.assertEqual("awaiting-approval", proposal["approval"]["state"])
                self.assertEqual({"all_of": ["po"], "any_of": []}, proposal["approval"]["required_roles"])
                self.assertNotIn("review_revision", proposal["approval"], "the proposing agent does not review")
                with self.assertRaises(AgentToolError) as refused:
                    agent.apply(proposal["preview_id"], "agent-po-handoff")
                self.assertIn("approval_required", refused.exception.text)
            self.assertEqual(clean, workspace_tree(harness.root), "a proposal and a refused agent apply write nothing")
            run.effect("the agent's po-handoff proposal awaits approval; its own apply was refused with approval_required; nothing was written")

            board = self.sign_in("po")
            self.open_board(board)
            expect(board.proposals_button()).to_be_visible()
            board.proposals_button().click()
            dialog = page.get_by_role("dialog", name="Proposals waiting for approval")
            expect(dialog).to_be_visible()
            expect(dialog).to_contain_text("po-handoff")
            expect(dialog).to_contain_text(feature.feature_id)
            expect(dialog).to_contain_text("roles: po")
            expect(dialog).to_contain_text("proposed by Browser agent")
            run.screenshot(page, "proposal-listed")

            dialog.get_by_role("button", name="Review", exact=True).click()
            expect(dialog.get_by_role("heading", name="Approve po-handoff")).to_be_visible()
            expect(dialog).to_contain_text(path)
            approve = dialog.get_by_role("button", name="Approve and apply")
            expect(approve).to_be_disabled()
            dialog.get_by_role("checkbox", name=re.compile(r"^I reviewed this change")).check()
            expect(approve).to_be_enabled()
            run.screenshot(page, "proposal-reviewed")
            self.assertEqual(clean, workspace_tree(harness.root), "reviewing writes nothing")
            approve.click()
            expect(dialog.get_by_text("Proposal approved and applied.")).to_be_visible()
            expect(dialog.get_by_text("No proposal is waiting for you.")).to_be_visible()
            run.screenshot(page, "proposal-approved")

            # The applied state: the feature page, the status board row and one log entry.
            after = workspace_tree(harness.root)
            self.assertEqual({path, BOARD_PATH, LOG_PATH}, changed_paths(clean, after))
            frontmatter = yaml.safe_load(harness.read(path).split("---", 2)[1])
            self.assertEqual(("ready-for-design", "tech-lead"), (frontmatter["status"], frontmatter["owner"]))
            row = [line for line in harness.read(BOARD_PATH).splitlines() if line.startswith(f"| {feature.feature_id} ")]
            self.assertEqual([f"| {feature.feature_id} | {feature.title} | ready-for-design | tech-lead | not-needed | — | — | — |"], row)
            run.effect("the feature page, the status board row and the log changed as the preview said")

            log = harness.read(LOG_PATH)
            entry = log[log.rindex("<!-- prism:board-history:v1"):]
            match = re.fullmatch(
                r"<!-- prism:board-history:v1 preview=(?P<preview>" + UUID.pattern + r") -->\n"
                rf"## \d{{4}}-\d{{2}}-\d{{2}} board-po-handoff \| {feature.feature_id}\n"
                r"- paths: [^\n]+\n"
                r"- evidence: board preview (?P<evidence>" + UUID.pattern + r")\n"
                r"- by: Browser po \(human; roles po\) approving Browser agent \(agent\)\n"
                r"<!-- prism:board-actor:v1 (?P<actor>\{[^\n]*\}) -->\n?",
                entry,
            )
            self.assertIsNotNone(match, entry)
            self.assertEqual(proposal["preview_id"], match.group("preview"))
            marker = yaml.safe_load(match.group("actor"))
            self.assertEqual(
                {
                    "action": "po-handoff",
                    "kind": "human",
                    "name": "Browser po",
                    "participant_id": po_actor.participant_id,
                    "preview_id": proposal["preview_id"],
                    "approver_id": po_actor.participant_id,
                    "proposer_id": agent_actor.participant_id,
                    "roles": ["po"],
                },
                marker,
            )
            run.effect("the log line names the approving human with their roles and the agent they approved")

            operations = harness.service.discover(po_actor)
            self.assertEqual([], operations["pending_operations"])
            self.assertEqual([], harness.service.list_proposals(po_actor)["proposals"])
            applied = [item["event"]["receipt"] for item in harness.service.changes(po_actor)["changes"] if item["event"]["type"] == "operation-applied"]
            self.assertEqual(1, len(applied))
            self.assertEqual(("po-handoff", po_actor.participant_id), (applied[0]["action"], applied[0]["actor"]["participant_id"]))
            run.effect("one operation is applied under the approving human; no proposal or operation is left pending")
            self.assertEqual([], self.page_errors)


if __name__ == "__main__":
    unittest.main()
