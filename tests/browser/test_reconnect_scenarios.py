"""Scenario F: the board loses its server, or only its event stream, and comes back.

A relay between the browser and the board lets a test cut every open
connection, event stream included, and refuse new ones until it resumes. Each
test opens a review first. While the board cannot refresh it must say STALE and
disable Apply and Copy. When it recovers it must refetch its data, and an
already-open preview must never be silently approved again.
"""

from __future__ import annotations

from pathlib import Path
import re
import shutil
import tempfile
import time
import unittest

from prism_cli.board_service import BoardService
from tests.browser.board_page import BoardPage, expect
from tests.browser.harness import EXTRA_FEATURES, FEATURES_BY_ID, STEP_TIMEOUT_MS, build_workspace, e2e_directory, free_port, requires_browser_e2e
from tests.browser.process_support import ServedProcess
from tests.browser.scenario_support import ScenarioCase, changed_paths, workspace_tree

IN_DESIGN = EXTRA_FEATURES["in-design"]
TWIN = FEATURES_BY_ID["F-004"]
RENAMED = "Renamed while the board was offline"
STALE_MESSAGE = "Live refresh unavailable for version disconnected; copying is disabled."


@requires_browser_e2e
class ReconnectTests(ScenarioCase):
    use_relay = True
    extra_features = (IN_DESIGN,)

    def rename_twin_externally(self) -> None:
        path = TWIN.path.as_posix()
        text = self.harness.read(path)
        self.assertIn("title: Document review\n", text)
        self.harness.write(path, text.replace("title: Document review\n", f"title: {RENAMED}\n", 1))

    def wait_for_reconnect_attempt(self, accepted_before: int) -> None:
        """Wait until the browser has opened a new connection through the relay."""

        deadline = time.monotonic() + STEP_TIMEOUT_MS / 1000
        while self.harness.relay.accepted <= accepted_before:
            self.assertLess(time.monotonic(), deadline, "The browser never tried to reconnect.")
            self.page.wait_for_timeout(100)

    def review_button(self, feature_id: str):
        return self.page.get_by_role("button", name=f"Review and apply handoff for {feature_id}", include_hidden=True)

    # -- (b) the event stream drops ----------------------------------------------

    def test_scenario_f_event_stream_drop_human_review(self) -> None:
        with self.scenario("F-reconnect-stream-drop-review") as run:
            page = self.page
            harness = self.harness
            feature = FEATURES_BY_ID["F-001"]
            board = self.sign_in()
            self.open_board(board)
            expect(board.freshness()).to_have_text("LIVE")
            dialog = self.open_review(board, feature, "handoff", "po-handoff")
            self.acknowledge(board, dialog)
            expect(board.apply_button(dialog)).to_be_enabled()
            before = workspace_tree(harness.root)

            harness.relay.pause()  # every connection, the event stream included, is cut
            expect(board.freshness()).to_have_text("STALE")
            expect(dialog.get_by_role("alert")).to_contain_text(STALE_MESSAGE)
            expect(board.apply_button(dialog)).to_be_disabled()
            expect(board.acknowledgement(dialog)).to_be_disabled()
            expect(self.review_button("F-004")).to_have_attribute("aria-disabled", "true")
            run.screenshot(page, "stale-while-disconnected")
            run.effect("event stream cut: the indicator reads STALE, Apply and the acknowledgement are disabled, and other Review buttons are aria-disabled")

            self.rename_twin_externally()  # the workspace changes while the board cannot hear about it
            accepted = harness.relay.accepted
            harness.relay.resume()
            self.wait_for_reconnect_attempt(accepted)
            expect(board.freshness()).to_have_text("LIVE")
            # The board refetched: it shows the change it missed.
            expect(board.card("F-004").get_by_text(RENAMED)).to_have_count(1)
            run.effect("after the stream returned the board refetched its data (the externally renamed card) and showed LIVE again")

            # The open preview is not re-approved by the recovery.
            expect(board.apply_button(dialog)).to_be_disabled()
            expect(board.acknowledgement(dialog)).to_be_disabled()
            expect(dialog.get_by_role("alert")).to_contain_text(STALE_MESSAGE)
            run.screenshot(page, "live-again-preview-still-blocked")
            run.effect("LIVE restored, but the open preview stays blocked: Apply and the acknowledgement remain disabled")

            # A new approval is required: a reopened preview starts unacknowledged.
            dialog.get_by_role("button", name="Close").click()
            expect(dialog).to_have_count(0)
            reopened = self.open_review(board, feature, "handoff", "po-handoff")
            expect(board.acknowledgement(reopened)).not_to_be_checked()
            expect(board.apply_button(reopened)).to_be_disabled()
            self.acknowledge(board, reopened)
            expect(board.apply_button(reopened)).to_be_enabled()
            reopened.get_by_role("button", name="Close").click()
            after = workspace_tree(harness.root)
            self.assertEqual({TWIN.path.as_posix()}, changed_paths(before, after))
            run.effect("a reopened preview needs a fresh acknowledgement; the only file change in the whole scenario is the external rename")
            self.assertEqual([], self.page_errors)

    def test_scenario_f_event_stream_drop_agent_request(self) -> None:
        with self.scenario("F-reconnect-stream-drop-copy") as run:
            page = self.page
            harness = self.harness
            board = self.sign_in()
            self.open_board(board)
            board.agent_request_button(IN_DESIGN.feature_id, "development handoff").click()
            dialog = page.get_by_role("dialog", name="Prepare development handoff")
            copy = dialog.get_by_role("button", name="Copy MCP request")
            expect(copy).to_be_visible()
            expect(dialog.get_by_text("Provider-neutral MCP request")).to_be_visible()
            expect(copy).not_to_have_attribute("aria-disabled", "true")
            before = workspace_tree(harness.root)

            harness.relay.pause()
            expect(board.freshness()).to_have_text("STALE")
            expect(copy).to_have_attribute("aria-disabled", "true")
            expect(dialog.get_by_text("Live dashboard data has not been refreshed and validated.").first).to_be_visible()
            run.screenshot(page, "copy-disabled-while-stale")
            run.effect("event stream cut: STALE, and Copy MCP request is disabled with the reason shown")

            accepted = harness.relay.accepted
            harness.relay.resume()
            self.wait_for_reconnect_attempt(accepted)
            expect(board.freshness()).to_have_text("LIVE")
            # Recovery does not re-enable the stale request by itself; a recheck asks the service again.
            expect(copy).to_have_attribute("aria-disabled", "true")
            dialog.get_by_role("button", name="Recheck").click()
            expect(copy).not_to_have_attribute("aria-disabled", "true")
            run.effect("LIVE restored: Copy stays disabled until Recheck gets a fresh service preflight, then it is enabled")
            self.assertEqual(before, workspace_tree(harness.root))
            self.assertEqual([], self.page_errors)

    # -- (a) the server restarts -------------------------------------------------

    def restart_with_open_review(self, run) -> tuple[object, object, dict[str, str]]:
        page = self.page
        harness = self.harness
        feature = FEATURES_BY_ID["F-001"]
        board = self.sign_in()
        self.open_board(board)
        expect(board.freshness()).to_have_text("LIVE")
        dialog = self.open_review(board, feature, "handoff", "po-handoff")
        self.acknowledge(board, dialog)
        expect(board.apply_button(dialog)).to_be_enabled()
        before = workspace_tree(harness.root)

        # What a stopped process does to the network, then a new process on the same port.
        harness.relay.pause()
        harness.stop_server()
        expect(board.freshness()).to_have_text("STALE")
        expect(board.apply_button(dialog)).to_be_disabled()
        run.screenshot(page, "server-down")
        run.effect("server stopped: STALE, Apply disabled")
        harness.start_server()
        self.accepted_before_resume = harness.relay.accepted
        harness.relay.resume()
        return board, dialog, before

    def test_scenario_f_server_restart_never_reapproves_and_recovers_by_signing_in(self) -> None:
        with self.scenario("F-reconnect-server-restart") as run:
            page = self.page
            harness = self.harness
            board, dialog, before = self.restart_with_open_review(run)
            self.wait_for_reconnect_attempt(self.accepted_before_resume)

            # The browser has found the server again; the old preview must still not be approvable.
            expect(board.apply_button(dialog)).to_be_disabled()
            expect(board.acknowledgement(dialog)).to_be_disabled()
            run.screenshot(page, "server-back-preview-blocked")
            run.effect("server back on the same port: the open preview stays blocked (Apply and the acknowledgement disabled)")

            # The restarted server has no browser sessions, so a reload asks for the token again.
            page.reload()
            expect(page.get_by_role("heading", name="Connect to your Prism board")).to_be_visible()
            self.sign_in_again(run, board)
            self.open_board(board)
            expect(board.freshness()).to_have_text("LIVE")
            expect(board.card_in("specified", "F-001")).to_have_count(1)
            expect(page.get_by_role("dialog")).to_have_count(0)
            self.assertEqual(before, workspace_tree(harness.root), "A restart must not write.")
            run.effect("after a reload and a new sign-in the board is LIVE, the preview is gone, and the workspace is byte-identical")
            self.assertEqual([], self.page_errors)

    def test_scenario_f_defect_restart_does_not_return_to_live(self) -> None:
        """After a server restart the open board says its session expired and offers Reconnect.

        The restarted server has no browser session table, so the event stream
        reconnect is answered with 401 and the browser stops retrying. The board
        cannot return to LIVE on its own: it shows "Board session expired" with a
        Reconnect action, in the header and in the open review, instead of a
        silent STALE. Reconnect returns to the token sign-in.
        """

        with self.scenario("F-defect-restart-no-live-recovery") as run:
            page = self.page
            board, dialog, _before = self.restart_with_open_review(run)
            self.wait_for_reconnect_attempt(self.accepted_before_resume)
            expect(board.session_bar()).to_contain_text("Board session expired", timeout=15000)
            expect(board.freshness()).to_have_text("STALE")
            expect(dialog.get_by_role("alert")).to_contain_text("The board session has expired. Reconnect")
            expect(board.apply_button(dialog)).to_be_disabled()
            reconnect = dialog.get_by_role("button", name="Reconnect")
            expect(reconnect).to_be_visible()
            run.screenshot(page, "session-expired-after-restart")
            reconnect.click()
            expect(page.get_by_role("heading", name="Connect to your Prism board")).to_be_visible()
            run.effect("after the restart the board showed `Board session expired` with Reconnect in the header and the review; Reconnect returned to the token sign-in")


@requires_browser_e2e
class ServeStopTests(ScenarioCase):
    serve_in_process = False

    def test_scenario_f_defect_serve_does_not_stop_while_a_browser_is_connected(self) -> None:
        """Stopping `prism board serve` ends the process while a board tab is open.

        The first step of restarting a server is stopping it. With a signed-in
        tab holding the event stream open, one interrupt (the same one that
        stops it when no browser is connected) ends the stream and the process.
        """

        with self.scenario("F-defect-serve-stop-with-browser") as run:
            work = e2e_directory() / "work"
            work.mkdir(parents=True, exist_ok=True)
            parent = Path(tempfile.mkdtemp(prefix="serve-stop-", dir=work))
            self.addCleanup(shutil.rmtree, parent, True)
            root = build_workspace(parent / "document-review")
            with BoardService(root) as service:
                token = service.create_participant("Browser human", "human", writable=True)["token"]
            port = free_port()
            server = ServedProcess(["-m", "prism_cli", "board", "serve", str(root), "--port", str(port), "--no-open"], r"Prism board: (http://127\.0\.0\.1:\d+/)")
            self.addCleanup(server.kill)
            url = server.start()
            board = BoardPage(self.page, url.rstrip("/"))
            board.sign_in(token)
            self.start_trace()
            self.open_board(board)
            expect(board.freshness()).to_have_text("LIVE")
            code = server.stop(15)
            self.assertIsNotNone(code, "`prism board serve` did not stop within 15 seconds of an interrupt while a browser was connected.")
            run.effect("the server stopped on an interrupt with a browser connected")


if __name__ == "__main__":
    unittest.main()
