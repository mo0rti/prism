"""Scenarios C and J: paths that must not write, and actions only an agent may take.

C drives every way a person can start a connected action and not finish it: a
blocked preview, a same-column drop, a drop on a destination no human action
targets, and Cancel. Each must leave the workspace byte-identical and leave no
operation in the journal.

J checks the agent-only actions. The board offers a provider-neutral MCP
request for them, never a human apply, and the request can be copied only while
the service's own fresh preflight allows it.
"""

from __future__ import annotations

import re
import unittest

from prism_cli.board_service import BoardError
from tests.browser.board_page import BoardPage, expect
from tests.browser.harness import EXTRA_FEATURES, FEATURES_BY_ID, requires_browser_e2e
from tests.browser.scenario_support import ScenarioCase, workspace_tree

BLOCKED = EXTRA_FEATURES["blocked"]
IN_DESIGN = EXTRA_FEATURES["in-design"]
RAW = EXTRA_FEATURES["raw"]
IN_DEV = EXTRA_FEATURES["in-dev"]


@requires_browser_e2e
class NoWritePathTests(ScenarioCase):
    extra_features = (BLOCKED,)

    def test_scenario_c_no_write_paths(self) -> None:
        with self.scenario("C-no-write-paths") as run:
            page = self.page
            board = self.sign_in()
            self.open_board(board)
            ready = FEATURES_BY_ID["F-001"]
            before = workspace_tree(self.harness.root)

            # 1. A blocked drop: the feature has an open question.
            board.drag_card_to_stage(BLOCKED.feature_id, BLOCKED.title, "ready-for-design")
            dialog = board.dialog("po-handoff")
            expect(dialog).to_be_visible()
            expect(dialog.get_by_role("heading", name=re.compile(r"^Exact file changes"))).to_be_visible()
            expect(dialog.get_by_text("1 open PO-owned question remains: question 1.")).to_be_visible()
            expect(dialog).to_contain_text("blocked or review required")
            apply = board.apply_button(dialog)
            expect(apply).to_be_disabled()
            # Acknowledging the review does not unblock a blocked preflight.
            board.acknowledgement(dialog).check()
            expect(dialog).to_contain_text("blocked or review required")
            expect(apply).to_be_disabled()
            run.screenshot(page, "blocked-drop")
            dialog.get_by_role("button", name="Close").click()
            expect(dialog).to_have_count(0)
            expect(board.card_in("specified", BLOCKED.feature_id)).to_have_count(1)
            self.assert_unchanged(run, before, "blocked drop on a feature with an open question (explained, Apply disabled)")
            self.journal_is_empty()
            run.effect("blocked drop: the journal holds no operation and no change event")

            # 2. A same-column drop does nothing. The browser never fires `drop` for it
            # (the column is marked invalid), so the drag simply ends.
            board.drag_card_to_stage(ready.feature_id, ready.title, "specified")
            expect(page.get_by_role("dialog")).to_have_count(0)
            expect(page.get_by_text("Workflow drag canceled.")).to_have_count(1)
            expect(board.card_in("specified", ready.feature_id)).to_have_count(1)
            self.assert_unchanged(run, before, "same-column drop (nothing opens, the card stays)")

            # 3. A drop on a destination no human action targets: the column is marked
            # invalid while the card hovers it, nothing opens, and the card stays.
            board.drag_card_to_stage(ready.feature_id, ready.title, "in-dev", release=False)
            expect(board.column("in-dev")).to_have_class(re.compile(r"drop-invalid"))
            run.screenshot(page, "unsupported-drop-hover")
            page.mouse.up()
            expect(page.get_by_role("dialog")).to_have_count(0)
            expect(board.card_in("specified", ready.feature_id)).to_have_count(1)
            self.assert_unchanged(run, before, "drop on an unsupported destination (marked invalid, nothing opens, the card stays)")

            # 4. Cancel writes nothing, from a ready and acknowledged preview, by button and by Escape.
            for how in ("Close button", "Escape"):
                dialog = self.open_review(board, ready, "handoff", "po-handoff")
                self.acknowledge(board, dialog)
                expect(board.apply_button(dialog)).to_be_enabled()
                if how == "Escape":
                    page.keyboard.press("Escape")
                else:
                    dialog.get_by_role("button", name="Close").click()
                expect(dialog).to_have_count(0)
                expect(board.card_in("specified", ready.feature_id)).to_have_count(1)
                self.assert_unchanged(run, before, f"cancel a ready, acknowledged preview ({how})")
            self.journal_is_empty()
            run.effect("cancel: the journal holds no operation and no change event")
            self.assertEqual([], self.page_errors)

    def test_scenario_c_defect_unsupported_drop_is_not_explained(self) -> None:
        """A drop on an unsupported destination is explained.

        ``onBoardDragOver`` sets ``dropEffect = "none"`` for an unsupported
        column, so the browser never fires ``drop``; the board explains the
        refusal when the drag ends: the "Unsupported drop - card stayed in its
        source stage" toast and a screen-reader announcement.
        """

        with self.scenario("C-defect-unsupported-drop-explanation"):
            board = self.sign_in()
            self.open_board(board)
            ready = FEATURES_BY_ID["F-001"]
            board.drag_card_to_stage(ready.feature_id, ready.title, "in-dev")
            expect(board.toast("Unsupported drop - card stayed in its source stage")).to_be_visible(timeout=3000)
            expect(self.page.locator("#sr-status")).to_have_text(re.compile(r"card stayed in its source stage"))
            expect(board.card_in("specified", ready.feature_id)).to_have_count(1)


@requires_browser_e2e
class AgentOnlyActionTests(ScenarioCase):
    extra_features = (IN_DESIGN, RAW, IN_DEV)

    def request_dialog(self, board: BoardPage, label: str):
        return self.page.get_by_role("dialog", name=f"Prepare {label}")

    def copy_button(self, dialog):
        return dialog.get_by_role("button", name="Copy MCP request")

    def test_scenario_j_agent_only_actions(self) -> None:
        with self.scenario("J-agent-only-actions") as run:
            page = self.page
            harness = self.harness
            self.context.grant_permissions(["clipboard-read", "clipboard-write"])
            board = self.sign_in()
            self.open_board(board)
            before = workspace_tree(harness.root)
            human = harness.actor("human")

            # Agent-only stages offer a request, never a human review-and-apply control.
            for feature in (IN_DESIGN, RAW, IN_DEV):
                expect(page.get_by_role("button", name=re.compile(rf"^Review and apply .* for {feature.feature_id}$"))).to_have_count(0)
            with self.assertRaises(BoardError) as refused:
                harness.service.preview_transition(human, IN_DESIGN.feature_id, "design-handoff")
            self.assertEqual("human_action_unavailable", refused.exception.code)
            run.effect("the service refuses a human preview for an agent-only action (human_action_unavailable)")

            # A ready preflight enables Copy, and the copied request carries the service's own revision.
            board.agent_request_button(IN_DESIGN.feature_id, "development handoff").click()
            dialog = self.request_dialog(board, "development handoff")
            expect(dialog).to_be_visible()
            copy = self.copy_button(dialog)
            expect(dialog.get_by_text("Provider-neutral MCP request")).to_be_visible()
            expect(copy).not_to_have_attribute("aria-disabled", "true")
            expect(dialog.get_by_role("button", name="Apply reviewed changes")).to_have_count(0)
            revision = harness.service.query(human, "transition-preflight", IN_DESIGN.feature_id, action="design-handoff")["snapshot"]["revision"]
            request_text = dialog.locator("pre").text_content()
            self.assertIn('Skill: "design-handoff"', request_text)
            self.assertIn(f'Feature ID: "{IN_DESIGN.feature_id}"', request_text)
            self.assertIn(f'Connected preflight revision: "{revision}"', request_text)
            page.evaluate("() => navigator.clipboard.writeText('sentinel')")
            copy.click()
            expect(dialog.get_by_text("Request text copied. No agent was dispatched.")).to_be_visible()
            # The clipboard turns each line break into CRLF on Windows.
            self.assertEqual(request_text, page.evaluate("() => navigator.clipboard.readText()").replace("\r\n", "\n"))
            run.screenshot(page, "copy-enabled")
            run.effect("ready preflight: Copy MCP request is enabled and copies the request with the service's preflight revision")
            page.keyboard.press("Escape")
            expect(dialog).to_have_count(0)

            # A blocked preflight keeps Copy disabled and shows why instead of a request.
            board.agent_request_button(IN_DEV.feature_id, "delivery").click()
            blocked = self.request_dialog(board, "delivery")
            expect(blocked).to_be_visible()
            expect(blocked.get_by_text("missing requirement for `backend`.").first).to_be_visible()
            blocked_copy = self.copy_button(blocked)
            expect(blocked_copy).to_have_attribute("aria-disabled", "true")
            self.assertNotIn("Board binding", blocked.locator("pre").text_content())
            page.evaluate("() => navigator.clipboard.writeText('sentinel')")
            blocked_copy.click(force=True)  # Playwright treats aria-disabled as not enabled; a person can still click it
            self.assertEqual("sentinel", page.evaluate("() => navigator.clipboard.readText()"), "a disabled Copy must not copy")
            run.screenshot(page, "copy-disabled-blocked")
            run.effect("blocked preflight: Copy MCP request is disabled, the reason replaces the request, and nothing is copied")
            page.keyboard.press("Escape")
            expect(blocked).to_have_count(0)

            # The service's fresh preflight decides each time a request is opened.
            path = IN_DESIGN.path.as_posix()
            original = harness.read(path)
            resolved = "| po | resolved: Capture key points and requested follow-up. |"
            self.assertIn(resolved, original)
            harness.write(path, original.replace(resolved, "| po | open |"))
            board.agent_request_button(IN_DESIGN.feature_id, "development handoff").click()
            fresh = self.request_dialog(board, "development handoff")
            expect(fresh).to_be_visible()
            expect(fresh.get_by_text("1 open action-relevant question remains: question 1.").first).to_be_visible()
            expect(self.copy_button(fresh)).to_have_attribute("aria-disabled", "true")
            # Restoring the page lets a recheck allow the copy again.
            harness.write(path, original)
            expect(fresh.get_by_role("button", name="Recheck")).to_be_visible()
            fresh.get_by_role("button", name="Recheck").click()
            expect(self.copy_button(fresh)).not_to_have_attribute("aria-disabled", "true")
            run.effect("a fresh preflight after an external edit disables Copy; restoring the page and rechecking enables it again")
            page.keyboard.press("Escape")

            # A drag of an agent-only card offers the same request dialog, still with no apply.
            board.drag_card_to_stage(IN_DESIGN.feature_id, IN_DESIGN.title, "ready-for-dev")
            dragged = self.request_dialog(board, "development handoff")
            expect(dragged).to_be_visible()
            expect(dragged.get_by_role("button", name="Apply reviewed changes")).to_have_count(0)
            page.keyboard.press("Escape")
            expect(dragged).to_have_count(0)

            # A human action's review dialog offers no MCP request: the person applies it.
            human_feature = FEATURES_BY_ID["F-001"]
            dialog = self.open_review(board, human_feature, "handoff", "po-handoff")
            expect(dialog.get_by_role("button", name="Copy MCP request")).to_have_count(0)
            page.keyboard.press("Escape")

            after = workspace_tree(harness.root)
            self.assertEqual(before, after, "Copying a request, rechecking and previewing must leave the workspace byte-identical.")
            run.effect("agent-only actions: the workspace tree is byte-identical after every request, copy, recheck and drag")
            self.journal_is_empty()
            self.assertEqual([], self.page_errors)

    def test_scenario_j_a_card_with_several_actions_names_each_and_opens_the_chosen_request(self) -> None:
        """An in-design card offers the two track actions beside the development handoff, each under a readable name."""

        with self.scenario("J-several-actions-on-one-card") as run:
            page = self.page
            harness = self.harness
            board = self.sign_in()
            self.open_board(board)
            before = workspace_tree(harness.root)
            picker = page.get_by_role("combobox", name=f"Workflow action for {IN_DESIGN.feature_id}")
            expect(picker).to_be_visible()
            options = [text.strip() for text in picker.locator("option").all_text_contents()]
            self.assertEqual(
                ["Choose a workflow action...", "development handoff -> ready-for-dev (ready)", "UI design -> in-design (ready)", "technical design -> in-design (ready)"],
                options,
            )
            for raw in ("design-ui-done", "tech-design-done", "design ui done", "tech design done"):
                self.assertFalse(any(raw in option for option in options), f"{raw!r} is not a readable name")
            run.effect("the card lists development handoff, UI design and technical design, each under a readable name")

            board.agent_request_button(IN_DESIGN.feature_id, "technical design").click()
            dialog = self.request_dialog(board, "technical design")
            expect(dialog).to_be_visible()
            expect(dialog.get_by_text("Provider-neutral MCP request")).to_be_visible()
            expect(self.copy_button(dialog)).not_to_have_attribute("aria-disabled", "true")
            expect(dialog.get_by_role("button", name="Apply reviewed changes")).to_have_count(0)
            request_text = dialog.locator("pre").text_content()
            self.assertIn('Skill: "tech-design-done"', request_text)
            self.assertIn('Action: "tech-design-done"', request_text)
            self.assertIn(f'Feature ID: "{IN_DESIGN.feature_id}"', request_text)
            run.screenshot(page, "technical-design-request")
            run.effect("choosing technical design opens its request for the tech-design-done skill, with Copy enabled and no apply control")
            page.keyboard.press("Escape")
            expect(dialog).to_have_count(0)

            self.assertEqual(before, workspace_tree(harness.root), "Choosing an action and opening its request writes nothing.")
            self.journal_is_empty()
            self.assertEqual([], self.page_errors)


if __name__ == "__main__":
    unittest.main()
