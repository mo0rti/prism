"""The runner refuses an unexpected proposal before asking the browser to approve it."""

import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prism_e2e import config, report, workspace
import test_approval as approval_tests
from test_approval import AGENT_IDS, PREVIEW, JourneyCase, approval_expectations


def preview():
    return {
        "preview_id": PREVIEW, "action": "po-specify", "feature_id": "F-001", "classification": "ready", "applicable": True,
        "approval": {"required_roles": {"all_of": ["po"], "any_of": []}, "proposer": {"kind": "agent", "participant_id": AGENT_IDS["codex"]}},
        "writes": [{"path": "knowledge/wiki/features/F-001-review-summary-export.md", "before": "old", "after": "new"}], "moves": [],
    }


class ApprovalBindingTests(JourneyCase):
    def test_unexpected_action_item_proposer_roles_or_writes_are_not_approved(self):
        mutations = {
            "action": lambda value: value.update(action="dev-return-design"),
            "item": lambda value: value.update(feature_id="F-009"),
            "proposer": lambda value: value["approval"]["proposer"].update(participant_id=AGENT_IDS["claude"]),
            "roles": lambda value: value["approval"].update(required_roles={"all_of": ["dev"], "any_of": []}),
            "writes": lambda value: value["writes"].append({"path": "knowledge/wiki/features/F-999-extra.md", "before": "", "after": "new"}),
            "move": lambda value: value["moves"].append({"source": "knowledge/intake/pending/other", "destination": "knowledge/intake/processed/other"}),
        }
        step = config.STEPS_BY_ID["po-specify"]
        for name, mutate in mutations.items():
            with self.subTest(mismatch=name):
                value = copy.deepcopy(preview())
                mutate(value)
                with patch.object(workspace, "fetch_preview", return_value=value, create=True):
                    with self.assertRaises(AssertionError):
                        self.journey._approve_in_board(step, 4, "codex", PREVIEW, report.StepResult(step=step.id, kind=step.kind, host="codex"))
                self.assertEqual([], self.browser.approvals)


class BrowserBindingTests(unittest.TestCase):
    def test_the_browser_refuses_an_unexpected_action_item_or_proposer_before_acknowledgement(self):
        case = approval_tests.BrowserApprovalTests()
        for mismatch in ("action", "item", "proposer"):
            with self.subTest(mismatch=mismatch):
                browser, page, _board = case.browser([case.listed()])
                value = preview()
                if mismatch == "action":
                    value["action"] = "dev-return-spec"
                elif mismatch == "item":
                    value["feature_id"] = "F-009"
                else:
                    value["approval"]["proposer"]["participant_id"] = AGENT_IDS["claude"]
                page.evaluate.side_effect = lambda script, *args: {"proposals": [case.listed()]} if "/proposals" in script else value
                with self.assertRaises(AssertionError):
                    browser.approve(PREVIEW, "human-po", approval_expectations())
                page.get_by_role.assert_not_called()


if __name__ == "__main__":
    unittest.main()
