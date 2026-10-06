"""Scenarios D and E: a preview that goes stale, and an apply whose response is lost.

D opens a human review, changes a relevant file behind it (an agent through the
real MCP SDK client, or an external edit), then confirms. The service must
reject the stale preview and write nothing.

E applies for real but aborts the response on its way back to the page. The
board must report the outcome as unknown, keep the operation ID, retrieve the
receipt on request, and leave exactly one log entry.
"""

from __future__ import annotations

import re
import time
from typing import Any
import unittest

from prism_cli.board_service import BoardError
from tests.browser.agent_client import AgentClient
from tests.browser.board_page import BoardPage, expect
from tests.browser.harness import EXTRA_FEATURES, FEATURES_BY_ID, requires_browser_e2e
from tests.browser.scenario_support import INDEX_PATH, LOG_PATH, UUID, ScenarioCase, changed_paths, workspace_tree

ADVISORY = EXTRA_FEATURES["advisory"]
FOLLOW_UP = FEATURES_BY_ID["F-003"]
REQUIREMENT_PATH = "knowledge/wiki/app-requirements/F-003-backend.md"
RESOLVED_ROW = "| 1 | Which points should a review summary highlight? | po | resolved: Capture key points and requested follow-up. |"
SKIP_REASON = "Typed before the change: the advisory review is covered elsewhere."


def add_open_question(text: str) -> str:
    """What an agent's `ask` proposes: one new open question after the existing row."""

    assert RESOLVED_ROW in text
    return text.replace(RESOLVED_ROW, RESOLVED_ROW + "\n| 2 | Who signs off the summary? | po | open |")


@requires_browser_e2e
class StalePreviewTests(ScenarioCase):
    extra_features = (ADVISORY,)

    # -- shared flow ------------------------------------------------------------

    def open_advisory_preview_with_inputs(self, board: BoardPage) -> Any:
        """Open the advisory feature's handoff, propose the skip with a reason, and acknowledge it."""

        dialog = self.open_review(board, ADVISORY, "handoff", "po-handoff")
        dialog.get_by_role("checkbox", name=re.compile(r"^Propose skipping the pending advisory review")).check()
        dialog.get_by_label("Reason for skipping advisory review").fill(SKIP_REASON)
        dialog.get_by_role("button", name="Preview this skip proposal").click()
        expect(dialog.get_by_role("checkbox", name=re.compile(r"^I reviewed the current source"))).to_be_enabled()
        self.acknowledge(board, dialog)
        expect(board.apply_button(dialog)).to_be_enabled()
        return dialog

    def agent_asks_a_question(self, feature_path: str, operation_id: str) -> None:
        """A connected agent adds an open question to the feature through the real MCP client."""

        with AgentClient(self.harness.url, self.harness.token("agent")) as agent:
            preview = agent.propose("ask", feature_path, add_open_question)
            self.assertTrue(preview["applicable"], preview)
            receipt = agent.apply(preview["preview_id"], operation_id)
            self.assertEqual("applied", receipt["state"], receipt)

    def confirm(self, board: BoardPage, dialog: Any) -> Any:
        """Click Apply and return the service's response to that one apply request."""

        with self.page.expect_response(lambda response: response.url.endswith("/api/board/v1/apply") and response.request.method == "POST") as sent:
            board.apply_button(dialog).click()
        return sent.value

    def assert_rejected_as_stale(self, run: Any, response: Any, source_path: str) -> str:
        self.assertEqual(409, response.status)
        error = response.json()["error"]
        self.assertEqual("stale_preview", error["code"])
        self.assertIn(source_path, error["message"])
        run.effect(f"the service rejected the apply as stale_preview (HTTP 409) and named `{source_path}`")
        return response.request.post_data_json["operation_id"]

    def assert_no_operation_recorded(self, run: Any, operation_id: str) -> None:
        harness = self.harness
        human = harness.actor("human")
        with self.assertRaises(BoardError) as missing:
            harness.service.operation(human, operation_id)
        self.assertEqual("operation_not_found", missing.exception.code)
        self.assertEqual([], harness.service.discover(human)["pending_operations"])
        run.effect("the journal holds no operation for the rejected apply")

    # -- scenarios --------------------------------------------------------------

    def test_scenario_d_stale_after_agent_change(self) -> None:
        with self.scenario("D-stale-after-agent-change") as run:
            page = self.page
            harness = self.harness
            board = self.sign_in()
            self.open_board(board)
            dialog = self.open_advisory_preview_with_inputs(board)
            path = ADVISORY.path.as_posix()

            before_agent = workspace_tree(harness.root)
            self.agent_asks_a_question(path, "agent-ask-question")
            after_agent = workspace_tree(harness.root)
            self.assertEqual({path, LOG_PATH}, changed_paths(before_agent, after_agent))
            run.effect(f"the agent's `ask` through the MCP client changed only `{path}` and the log")
            self.assertIn("| 2 | Who signs off the summary? | po | open |", harness.read(path))

            # The board's own stage checks cannot see this change (status, owner and path are
            # unchanged), so Apply is still offered: the service is the authority.
            expect(board.apply_button(dialog)).to_be_enabled()
            response = self.confirm(board, dialog)
            expect(board.apply_button(dialog)).to_be_disabled()
            operation_id = self.assert_rejected_as_stale(run, response, path)
            run.screenshot(page, "after-stale-rejection")

            self.assertEqual(after_agent, workspace_tree(harness.root), "A rejected stale apply must not write.")
            run.effect("the rejected apply wrote nothing: the tree equals the tree right after the agent's change")
            self.assert_no_operation_recorded(run, operation_id)

            # Unsent inputs are kept: the reason text and the acknowledgement.
            expect(dialog.get_by_label("Reason for skipping advisory review")).to_have_value(SKIP_REASON)
            expect(board.acknowledgement(dialog)).to_be_checked()
            run.effect("the typed skip reason and the acknowledgement are still in the dialog")
            expect(board.card_in("specified", ADVISORY.feature_id)).to_have_count(1)
            self.assertEqual([], self.page_errors)

    def test_scenario_d_stale_after_external_edit(self) -> None:
        with self.scenario("D-stale-after-external-edit") as run:
            page = self.page
            harness = self.harness
            board = self.sign_in()
            self.open_board(board)
            dialog = self.open_review(board, FOLLOW_UP, "development start", "dev-start")
            self.acknowledge(board, dialog)
            expect(board.apply_button(dialog)).to_be_enabled()

            # An editor changes a linked page this action depends on (not the feature's stage).
            before_edit = workspace_tree(harness.root)
            original = harness.read(REQUIREMENT_PATH)
            harness.write(REQUIREMENT_PATH, original.replace("Store a document review summary and outcome.", "Store a document review summary, outcome and reviewer."))
            self.assertEqual({REQUIREMENT_PATH}, changed_paths(before_edit, workspace_tree(harness.root)))
            after_edit = workspace_tree(harness.root)

            response = self.confirm(board, dialog)
            expect(board.apply_button(dialog)).to_be_disabled()
            operation_id = self.assert_rejected_as_stale(run, response, REQUIREMENT_PATH)
            run.screenshot(page, "after-stale-rejection")
            self.assertEqual(after_edit, workspace_tree(harness.root), "A rejected stale apply must not write.")
            run.effect("the rejected apply wrote nothing: the tree equals the tree right after the external edit")
            self.assert_no_operation_recorded(run, operation_id)
            expect(board.acknowledgement(dialog)).to_be_checked()
            expect(board.card_in("ready-for-dev", FOLLOW_UP.feature_id)).to_have_count(1)
            self.assertEqual([], self.page_errors)

    def test_scenario_d_board_detects_changed_stage_before_confirming(self) -> None:
        with self.scenario("D-stale-source-detected-by-board") as run:
            page = self.page
            harness = self.harness
            board = self.sign_in()
            self.open_board(board)
            applies: list[str] = []
            page.on("request", lambda request: applies.append(request.url) if request.url.endswith("/api/board/v1/apply") else None)
            dialog = self.open_advisory_preview_with_inputs(board)
            path = ADVISORY.path.as_posix()

            # An external edit changes the feature's owner, which the board does track.
            before_edit = workspace_tree(harness.root)
            harness.write(path, harness.read(path).replace("owner: po\n", "owner: designer\n", 1))
            after_edit = workspace_tree(harness.root)
            self.assertEqual({path}, changed_paths(before_edit, after_edit))

            expect(dialog.get_by_role("alert")).to_contain_text("Feature source changed while this connected preview was open")
            expect(board.apply_button(dialog)).to_be_disabled()
            # Re-approval is never carried over: the acknowledgement is cleared and locked,
            # while the typed reason stays.
            expect(board.acknowledgement(dialog)).not_to_be_checked()
            expect(board.acknowledgement(dialog)).to_be_disabled()
            expect(dialog.get_by_label("Reason for skipping advisory review")).to_have_value(SKIP_REASON)
            run.screenshot(page, "board-marked-stale")
            self.assertEqual([], applies, "Nothing was confirmed, so no apply request was sent.")
            self.assertEqual(after_edit, workspace_tree(harness.root))
            run.effect("the board itself marked the preview stale, disabled Apply, cleared the acknowledgement and kept the typed reason; nothing was sent or written")
            self.assertEqual([], self.page_errors)

    def test_scenario_d_defect_stale_rejection_reason_is_hidden(self) -> None:
        """Confirming a stale preview shows the service's reason and offers a fresh preview.

        The service answers 409 `stale_preview` naming the changed source. No
        operation was created, so the dialog shows that message (not an unknown
        outcome with Inspect and Recover), marks the preview stale, keeps the
        typed inputs, and offers "Preview again". A fresh preview needs a new
        acknowledgement.
        """

        with self.scenario("D-defect-stale-rejection-reason"):
            page = self.page
            board = self.sign_in()
            self.open_board(board)
            dialog = self.open_advisory_preview_with_inputs(board)
            self.agent_asks_a_question(ADVISORY.path.as_posix(), "agent-ask-question")
            response = self.confirm(board, dialog)
            expect(board.apply_button(dialog)).to_be_disabled()
            self.assertEqual(409, response.status)
            expect(dialog.get_by_text("changed after this preview").first).to_be_visible(timeout=3000)
            expect(dialog.get_by_text("Operation ID · outcome unknown")).to_have_count(0)
            expect(dialog.get_by_role("button", name="Inspect operation")).to_have_count(0)
            expect(dialog.get_by_label("Reason for skipping advisory review")).to_have_value(SKIP_REASON)
            # A fresh preview is requested from the service and needs its own acknowledgement.
            dialog.get_by_role("button", name="Preview again").click()
            expect(dialog.get_by_role("heading", name=re.compile(r"^Exact file changes"))).to_be_visible()
            expect(board.acknowledgement(dialog)).not_to_be_checked()
            expect(board.apply_button(dialog)).to_be_disabled()
            expect(dialog.get_by_label("Reason for skipping advisory review")).to_have_value(SKIP_REASON)


@requires_browser_e2e
class LostResponseTests(ScenarioCase):
    def test_scenario_e_lost_apply_response_keeps_the_operation_id(self) -> None:
        with self.scenario("E-lost-response") as run:
            page = self.page
            harness = self.harness
            feature = FEATURES_BY_ID["F-001"]
            board = self.sign_in()
            self.open_board(board)
            before = workspace_tree(harness.root)

            sent: list[str] = []
            lookups: list[str] = []

            def lose_the_response(route: Any) -> None:
                sent.append(route.request.post_data_json["operation_id"])
                route.fetch()  # the service receives and applies the request ...
                route.abort()  # ... but the answer never reaches the page.

            def fail_first_lookup(route: Any) -> None:
                lookups.append(route.request.url.rsplit("/", 1)[1])
                if len(lookups) == 1:
                    route.abort()
                else:
                    route.continue_()

            page.route(re.compile(r".*/api/board/v1/apply$"), lose_the_response)
            page.route(re.compile(r".*/api/board/v1/operations/[^/]+$"), fail_first_lookup)

            dialog = self.open_review(board, feature, "handoff", "po-handoff")
            self.acknowledge(board, dialog)
            board.apply_button(dialog).click()

            # The page cannot know the result: it says so, and keeps the same ID.
            expect(dialog.get_by_text("Operation ID · outcome unknown")).to_be_visible()
            self.assertEqual(1, len(sent))
            operation_id = sent[0]
            expect(dialog.get_by_text(operation_id)).to_be_visible()
            expect(dialog.get_by_role("alert")).to_contain_text("The operation could not be checked. Keep this operation ID and retry the lookup.")
            expect(board.apply_button(dialog)).to_be_disabled()
            # The live event stream already moved the card, though the dialog cannot confirm the outcome.
            expect(board.card_in("ready-for-design", feature.feature_id)).to_have_count(1)
            run.screenshot(page, "outcome-unknown")
            after_apply = workspace_tree(harness.root)
            self.assertEqual({feature.path.as_posix(), INDEX_PATH, LOG_PATH}, changed_paths(before, after_apply))
            run.effect("the service applied the request although the response was lost: feature page, index and log changed")

            # Retrieving the receipt uses the same operation ID and does not apply again.
            dialog.get_by_role("button", name="Inspect operation").click()
            expect(dialog.get_by_text("Operation ID · applied")).to_be_visible()
            expect(dialog.get_by_text(operation_id)).to_be_visible()
            expect(dialog.get_by_text(f"Applied {feature.path.as_posix()}, {INDEX_PATH}, {LOG_PATH}.")).to_be_visible()
            expect(board.card_in("ready-for-design", feature.feature_id)).to_have_count(1)
            expect(board.card_in("specified", feature.feature_id)).to_have_count(0)
            self.assertEqual([operation_id, operation_id], [item for item in lookups if item == operation_id][:2])
            self.assertEqual([operation_id], sent, "The board must not resend the apply request.")
            run.effect("Inspect operation retrieved the receipt for the same operation ID; the apply request was sent exactly once")

            self.assertEqual(after_apply, workspace_tree(harness.root), "Retrieving a receipt must not write.")
            log = harness.read(LOG_PATH)
            self.assertEqual(1, log.count("<!-- prism:board-history:v1 "), "The log must hold one history entry.")
            self.assertEqual(1, log.count("<!-- prism:board-actor:v1 "))
            self.assertEqual(1, len(UUID.findall(log.split("<!-- prism:board-history:v1 ", 1)[1].split(" -->", 1)[0])))
            run.effect("the log has exactly one history entry and one actor comment")
            record = harness.service.operation(harness.actor("human"), operation_id)
            self.assertEqual("applied", record["state"])
            events = harness.service.changes(harness.actor("human"))["changes"]
            self.assertEqual(["operation-applied"], [event["event"]["type"] for event in events])
            run.effect("the journal holds one applied operation and one operation-applied event")
            self.assertEqual([], self.page_errors)

    def test_scenario_e_defect_receipt_retrieved_after_lost_response_still_says_source_changed(self) -> None:
        """After a lost response, the retrieved receipt is not shadowed by a stale warning.

        While the outcome is unknown the live event stream shows the card in its
        new column. That stage change is the operation's own effect, so the
        board does not mark the open review stale, and after Inspect operation
        retrieves the applied receipt the alert says "Operation applied...".
        """

        with self.scenario("E-defect-receipt-shadowed-by-stale-warning"):
            page = self.page
            feature = FEATURES_BY_ID["F-001"]
            board = self.sign_in()
            self.open_board(board)
            lookups: list[str] = []

            def lose_the_response(route: Any) -> None:
                route.fetch()
                route.abort()

            def fail_first_lookup(route: Any) -> None:
                lookups.append(route.request.url)
                route.abort() if len(lookups) == 1 else route.continue_()

            page.route(re.compile(r".*/api/board/v1/apply$"), lose_the_response)
            page.route(re.compile(r".*/api/board/v1/operations/[^/]+$"), fail_first_lookup)
            dialog = self.open_review(board, feature, "handoff", "po-handoff")
            self.acknowledge(board, dialog)
            board.apply_button(dialog).click()
            expect(dialog.get_by_text("Operation ID · outcome unknown")).to_be_visible()
            # Once the live stream has moved the card, the board has seen the source change.
            expect(board.card_in("ready-for-design", feature.feature_id)).to_have_count(1)
            dialog.get_by_role("button", name="Inspect operation").click()
            expect(dialog.get_by_text("Operation ID · applied")).to_be_visible()
            expect(dialog.get_by_role("alert")).to_contain_text("Operation applied", timeout=3000)
            expect(dialog.get_by_text("Feature source changed while this connected preview was open")).to_have_count(0)

    def test_scenario_e_defect_live_event_before_apply_response_shows_stale_warning(self) -> None:
        """A live update that beats the apply response does not mark the preview stale.

        The service applies and refreshes its snapshot before it answers, so the
        event stream can announce the new stage a moment before the apply
        response reaches the page. While the apply is in flight the board does
        not mark the preview stale, so the applied operation is shown with
        "Operation applied...". Here the response is held until the board has
        moved the card, which makes the ordering deterministic; unheld, it is
        the intermittent ordering scenarios A and B can meet under load.
        """

        with self.scenario("E-defect-live-event-before-apply-response"):
            page = self.page
            feature = FEATURES_BY_ID["F-001"]
            board = self.sign_in()
            self.open_board(board)
            held: list[tuple[Any, Any]] = []
            page.route(re.compile(r".*/api/board/v1/apply$"), lambda route: held.append((route, route.fetch())))
            dialog = self.open_review(board, feature, "handoff", "po-handoff")
            self.acknowledge(board, dialog)
            board.apply_button(dialog).click()
            deadline = time.monotonic() + 20
            while not held:
                self.assertLess(time.monotonic(), deadline, "The apply request never reached the page's route.")
                page.wait_for_timeout(50)
            # The service has applied; the live event moves the card while the response is still held.
            expect(board.card_in("ready-for-design", feature.feature_id)).to_have_count(1)
            route, response = held[0]
            route.fulfill(response=response)
            expect(dialog.get_by_text("Operation ID · applied")).to_be_visible()
            expect(dialog.get_by_role("alert")).to_contain_text("Operation applied", timeout=3000)
            expect(dialog.get_by_text("Feature source changed while this connected preview was open")).to_have_count(0)


if __name__ == "__main__":
    unittest.main()
