"""Scenario K: the legacy live dashboard and the static export stay copy-only.

Only the connected board, behind a participant token, may apply a human action.
`prism wiki graph --open` (the legacy read-only server) and a static export
written by `prism wiki graph --html` offer copy-only workflow requests: no
Apply controls, no session, and no writes to the workspace.
"""

from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import urllib.request

from tests.browser.board_page import BoardPage, expect
from tests.browser.harness import BrowserCase, build_workspace, e2e_directory, free_port, requires_browser_e2e
from tests.browser.process_support import GRAPH_COMMAND_WITHOUT_BROWSER, REPOSITORY, ServedProcess
from tests.browser.scenario_support import workspace_tree

PREPARE_BUTTONS = {
    "F-001": "Prepare handoff for F-001",
    "F-002": "Prepare design start for F-002",
    "F-003": "Prepare development start for F-003",
    "F-004": "Prepare handoff for F-004",
}


@requires_browser_e2e
class LegacyAndStaticTests(BrowserCase):
    serve_in_process = False

    def workspace(self) -> Path:
        work = e2e_directory() / "work"
        work.mkdir(parents=True, exist_ok=True)
        parent = Path(tempfile.mkdtemp(prefix="legacy-", dir=work))
        self.addCleanup(shutil.rmtree, parent, True)
        self.parent = parent
        return build_workspace(parent / "document-review")

    def requests_made(self) -> list[tuple[str, str]]:
        made: list[tuple[str, str]] = []
        self.page.on("request", lambda request: made.append((request.method, request.url)))
        return made

    def assert_copy_only(self, run, board: BoardPage, label: str) -> None:
        page = self.page
        board.open_board()
        # No connected controls: no session, no human review-and-apply button, no connected dialog.
        expect(page.get_by_role("button", name=re.compile(r"^Review and apply "))).to_have_count(0)
        expect(page.get_by_role("button", name="Sign out")).to_have_count(0)
        expect(board.session_bar()).to_be_hidden()
        expect(page.locator("[data-board-action]")).to_have_count(0)
        # Every card offers the copy-only request instead.
        for feature_id, name in PREPARE_BUTTONS.items():
            expect(page.get_by_role("button", name=name)).to_have_count(1)
        run.effect(f"{label}: no Apply controls and no session; each card offers a copy-only `Prepare ...` request")

        page.get_by_role("button", name=PREPARE_BUTTONS["F-001"]).click()
        dialog = page.get_by_role("dialog", name="Prepare handoff")
        expect(dialog).to_be_visible()
        expect(dialog.get_by_text("COPY-ONLY WORKFLOW REQUEST", exact=False)).to_have_count(1)
        expect(dialog.get_by_text("The Board does not run it or move the card.")).to_be_visible()
        expect(dialog.get_by_role("button", name="Copy request")).to_be_visible()
        expect(dialog.get_by_role("button", name=re.compile(r"Apply|Recover"))).to_have_count(0)
        run.screenshot(page, f"{label}-copy-only-dialog".replace(" ", "-"))

    def copy_request(self, dialog) -> str:
        self.context.grant_permissions(["clipboard-read", "clipboard-write"])
        self.page.evaluate("() => navigator.clipboard.writeText('sentinel')")
        dialog.get_by_role("button", name="Copy request").click()
        # The clipboard turns each line break into CRLF on Windows.
        return self.page.evaluate("() => navigator.clipboard.readText()").replace("\r\n", "\n")

    # -- static export -----------------------------------------------------------

    def test_scenario_k_static_export_is_copy_only(self) -> None:
        with self.scenario("K-static-export") as run:
            page = self.page
            root = self.workspace()
            before = workspace_tree(root)
            export = self.parent / "export.html"
            result = subprocess.run(
                [sys.executable, "-B", "-m", "prism_cli", "wiki", "graph", str(root), "--html", str(export)],
                cwd=REPOSITORY, capture_output=True, text=True, timeout=120,
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertTrue(export.is_file())
            self.assertEqual(before, workspace_tree(root), "Exporting must not write inside the workspace.")
            run.effect("`prism wiki graph --html` wrote only the export file, outside the workspace")

            made = self.requests_made()
            self.start_trace()
            page.goto(export.as_uri())
            board = BoardPage(page, export.as_uri())
            expect(board.freshness()).to_contain_text("SNAPSHOT")
            self.assert_copy_only(run, board, "static export")
            dialog = page.get_by_role("dialog", name="Prepare handoff")
            copied = self.copy_request(dialog)
            self.assertIn("Prepare the existing workflow action for review.", copied)
            self.assertIn('Feature ID: "F-001"', copied)
            run.effect("static export: Copy request puts the workflow request text on the clipboard")
            page.keyboard.press("Escape")

            # A static page talks to nobody and never moves a card.
            self.assertEqual([], [item for item in made if item[0] != "GET" or item[1].startswith("http")])
            self.assertEqual(before, workspace_tree(root))
            run.effect("static export: the page made no HTTP request at all, and the workspace is byte-identical")
            self.assertEqual([], self.page_errors)

    # -- legacy live dashboard ---------------------------------------------------

    def test_scenario_k_legacy_open_server_is_copy_only(self) -> None:
        with self.scenario("K-legacy-open") as run:
            page = self.page
            root = self.workspace()
            before = workspace_tree(root)
            port = free_port()
            server = ServedProcess(
                ["-c", GRAPH_COMMAND_WITHOUT_BROWSER, "wiki", "graph", str(root), "--open", "--port", str(port)],
                r"Prism graph dashboard: (http://127\.0\.0\.1:\d+/)",
            )
            self.addCleanup(server.kill)
            url = server.start()

            made = self.requests_made()
            self.start_trace()
            page.goto(url)
            board = BoardPage(page, url)
            expect(board.freshness()).to_have_text("LIVE")
            self.assert_copy_only(run, board, "legacy open")
            dialog = page.get_by_role("dialog", name="Prepare handoff")
            copied = self.copy_request(dialog)
            self.assertIn("Prepare the existing workflow action for review.", copied)
            run.effect("legacy open: Copy request puts the workflow request text on the clipboard")
            page.keyboard.press("Escape")

            # A drag opens the same copy-only request; it never moves the card.
            board.drag_card_to_stage("F-001", "Document review", "ready-for-design")
            dragged = page.get_by_role("dialog", name="Prepare handoff")
            expect(dragged).to_be_visible()
            expect(dragged.get_by_role("button", name=re.compile(r"Apply|Recover"))).to_have_count(0)
            page.keyboard.press("Escape")
            expect(board.card_in("specified", "F-001")).to_have_count(1)

            # The page only reads. The server has no board API and refuses writes.
            self.assertEqual([], [item for item in made if item[0] != "GET"])
            session = [item for item in made if item[1].endswith("/api/board/v1/auth/session")]
            self.assertTrue(session, "The page asks the server whether a board session exists.")
            for path in ("/api/board/v1/apply", "/api/board/v1/previews/transition"):
                request = urllib.request.Request(url.rstrip("/") + path, data=b"{}", method="POST", headers={"Content-Type": "application/json"})
                # The read-only server has no POST handler: it answers 501 or closes the connection.
                with self.assertRaises((urllib.error.HTTPError, ConnectionError)) as refused:
                    urllib.request.urlopen(request, timeout=10)
                if isinstance(refused.exception, urllib.error.HTTPError):
                    self.assertIn(refused.exception.code, (404, 405, 501))
            with self.assertRaises(urllib.error.HTTPError) as missing:
                urllib.request.urlopen(url.rstrip("/") + "/api/board/v1/auth/session", timeout=10)
            self.assertEqual(404, missing.exception.code)
            self.assertEqual(before, workspace_tree(root))
            run.effect("legacy open: every browser request was a GET, the board API answers 404 and write attempts are refused, and the workspace is byte-identical")

            code = server.stop(30)
            self.assertIsNotNone(code, "The legacy server did not stop on an interrupt: " + server.transcript[-500:])
            self.assertEqual(before, workspace_tree(root))
            self.assertEqual([], self.page_errors)


if __name__ == "__main__":
    unittest.main()
