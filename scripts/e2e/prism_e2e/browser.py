"""Human steps in headless Chromium, through the board's own page object.

``tests/browser/board_page.py`` is imported from the repository and not
changed. ``PRISM_BROWSER_E2E_EXECUTABLE`` selects an existing Chromium, as in
the browser test suite; without it Playwright's bundled browser runs.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import re
import time
from typing import Any

from . import config
from .approval import check_preview

EXECUTABLE_VARIABLE = "PRISM_BROWSER_E2E_EXECUTABLE"
STEP_TIMEOUT_MS = 20_000


class BrowserUnavailable(RuntimeError):
    pass


def _load_board_page() -> Any:
    path = config.REPO_ROOT / "tests" / "browser" / "board_page.py"
    spec = importlib.util.spec_from_file_location("prism_e2e_board_page", path)
    if spec is None or spec.loader is None:
        raise BrowserUnavailable(f"Cannot load {path}.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class HumanBrowser:
    def __init__(self, base_url: str, human_tokens: dict[str, str]) -> None:
        self._base_url = base_url
        self._tokens = dict(human_tokens)  # approver label -> the token of the human grant that holds exactly its roles
        self._pw: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._module: Any = None
        self.page: Any = None
        self.board: Any = None
        self.version = "unknown"
        self.signed_in_as: str | None = None  # the label of the grant whose session the browser holds

    # -- lifecycle ---------------------------------------------------------------

    def start(self) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as error:
            raise BrowserUnavailable("Playwright is not installed for this Python. Install the `e2e` extra: pip install playwright.") from error
        self._module = _load_board_page()
        self._pw = sync_playwright().start()
        executable = os.environ.get(EXECUTABLE_VARIABLE)
        try:
            self._browser = self._pw.chromium.launch(executable_path=executable or None, headless=True)
        except Exception as error:  # noqa: BLE001 - Playwright raises its own error types
            self.close()
            raise BrowserUnavailable(f"Chromium did not start: {str(error).splitlines()[0] if str(error) else type(error).__name__}") from error
        self.version = self._browser.version
        self._context = self._browser.new_context(viewport={"width": 1500, "height": 950}, service_workers="block")
        self._context.set_default_timeout(STEP_TIMEOUT_MS)
        self.page = self._context.new_page()
        self.board = self._module.BoardPage(self.page, self._base_url)

    def close(self) -> str:
        notes: list[str] = []
        for name, handle in (("context", self._context), ("browser", self._browser)):
            try:
                if handle is not None:
                    handle.close()
            except Exception as error:  # noqa: BLE001
                notes.append(f"{name} close error: {type(error).__name__}")
        try:
            if self._pw is not None:
                self._pw.stop()
        except Exception as error:  # noqa: BLE001
            notes.append(f"playwright stop error: {type(error).__name__}")
        self._pw = self._browser = self._context = None
        return "closed" + (f" ({'; '.join(notes)})" if notes else "")

    # -- sessions ------------------------------------------------------------------------

    @property
    def signed_in(self) -> bool:
        return self.signed_in_as is not None

    def _sign_in_as(self, approver: str) -> None:
        """Hold the session of the grant ``approver``: sign in, or sign out and in again when another grant's session is open.

        A page reload on the same session keeps the board current. The token is typed into the board's own form, as a person would.
        """

        expect = self._module.expect
        if approver not in self._tokens:
            raise BrowserUnavailable(f"No token for the approver {approver}.")
        if self.signed_in_as == approver:
            self.page.reload()
            return
        if self.signed_in_as is not None:
            self.page.get_by_role("button", name="Sign out").click()
            expect(self.page.get_by_role("heading", name="Connect to your Prism board")).to_be_visible()
            self.signed_in_as = None
        self.board.sign_in(self._tokens[approver])
        self.signed_in_as = approver

    # -- one human action --------------------------------------------------------------

    def perform(self, action: str, feature_id: str, workspace: Path, screenshot_dir: Path, approver: str) -> dict[str, Any]:
        """Preview and apply one human lifecycle action on the board, signed in as the grant ``approver``, as a person would.

        Returns the dialog texts, the exact writes the preview showed, the operation ID the dialog reports and
        the board's columns afterwards. Any failed expectation raises; the caller marks the step failed.
        """

        label = config.HUMAN_ACTION_LABELS[action]
        expect = self._module.expect
        board = self.board
        page = self.page
        started = time.monotonic()
        self._sign_in_as(approver)
        board.open_board()
        board.action_button(feature_id, label).click()
        dialog = board.dialog(action)
        expect(dialog).to_be_visible()
        expect(dialog.get_by_role("heading", name=re.compile(r"^Exact file changes"))).to_be_visible()
        feature_page = next((workspace / "knowledge/wiki/features").glob(f"{feature_id}-*.md")).relative_to(workspace).as_posix()
        writes = board.read_writes(dialog, [feature_page, "knowledge/wiki/status-board.md", "knowledge/wiki/log.md"])
        preview_text = dialog.inner_text()
        acknowledgement = board.acknowledgement(dialog)
        apply_button = board.apply_button(dialog)
        expect(apply_button).to_be_disabled()
        acknowledgement.check()
        expect(apply_button).to_be_enabled()
        expect(dialog).to_contain_text("ready · applicable")
        apply_button.click()
        operation_id = board.operation_id(dialog)
        expect(dialog.get_by_role("alert")).to_contain_text("Dashboard view refreshed and validated")
        applied_text = dialog.inner_text()
        dialog.get_by_role("button", name="Close").click()
        expect(dialog).to_have_count(0)
        return {
            "operation_id": operation_id,
            "preview_text": preview_text,
            "applied_text": applied_text,
            "writes": writes,
            "stages": board.stages(),
            "elapsed_s": round(time.monotonic() - started, 1),
        }

    # -- one approval --------------------------------------------------------------------

    def approve(self, preview_id: str, approver: str, expected: dict[str, Any]) -> dict[str, Any]:
        """Approve an agent's gated proposal in the Proposals dialog, signed in as the grant ``approver``, as a person would.

        The dialog lists the proposals the signed-in grant may decide. The row is found by the preview ID the agent reported
        (read from the board's own list through this session), opened with Review, acknowledged and approved. Returns the
        review text, the proposal's list entry, the operation ID the browser submitted and the dialog text afterwards. Any
        failed expectation, an unlisted proposal or a refused apply raises; the caller marks the step failed.
        """

        expect = self._module.expect
        board = self.board
        page = self.page
        started = time.monotonic()
        self._sign_in_as(approver)
        preview = page.evaluate(
            "async id => (await (await fetch('/api/board/v1/previews/' + encodeURIComponent(id), {credentials: 'same-origin', cache: 'no-store', headers: {Accept: 'application/json'}})).json())",
            preview_id,
        )
        check_preview(preview, preview_id, expected)
        board.open_board()
        expect(board.freshness()).to_have_text("LIVE")
        expect(board.proposals_button()).to_be_visible()
        board.proposals_button().click()
        dialog = page.get_by_role("dialog", name="Proposals waiting for approval")
        expect(dialog).to_be_visible()
        expect(dialog.get_by_text("Loading…")).to_have_count(0)
        listing = page.evaluate(
            "async () => (await (await fetch('/api/board/v1/proposals', {credentials: 'same-origin', cache: 'no-store', headers: {Accept: 'application/json'}})).json())"
        )
        items = listing.get("proposals", [])
        index = next((position for position, item in enumerate(items) if item.get("preview_id") == preview_id), None)
        if index is None:
            raise AssertionError(f"The proposal {preview_id} is not in the proposals list of {approver}; the list holds {len(items)} proposal(s).")
        listed = items[index]
        row = dialog.locator(f'[data-preview-id={json.dumps(preview_id)}]')
        expect(row).to_contain_text(str(listed.get("action")))
        row.get_by_role("button", name="Review", exact=True).click()
        expect(dialog.get_by_role("heading", name=f"Approve {listed.get('action')}")).to_be_visible()
        expect(dialog.locator("[data-reviewed-preview-id]")).to_have_attribute("data-reviewed-preview-id", preview_id)
        # Re-read immediately before acknowledgement; the UI row and its detail carry this same immutable preview ID.
        reviewed = page.evaluate(
            "async id => (await (await fetch('/api/board/v1/previews/' + encodeURIComponent(id), {credentials: 'same-origin', cache: 'no-store', headers: {Accept: 'application/json'}})).json())",
            preview_id,
        )
        check_preview(reviewed, preview_id, expected)
        expect(dialog.get_by_role("heading", name=re.compile(rf"^Exact file changes . {len(reviewed['writes'])}$"))).to_be_visible()
        for write in reviewed["writes"]:
            expect(dialog.locator("details.connected-write > summary").filter(has_text=write["path"])).to_be_visible()
        review_text = dialog.inner_text()
        approve_button = dialog.get_by_role("button", name="Approve and apply")
        expect(approve_button).to_be_disabled()
        dialog.get_by_role("checkbox", name=re.compile(r"^I reviewed this change")).check()
        expect(approve_button).to_be_enabled()
        with page.expect_response(lambda response: response.url.split("?")[0].endswith("/api/board/v1/apply") and response.request.method == "POST") as submitted:
            approve_button.click()
        response = submitted.value
        sent = response.request.post_data_json or {}
        payload: Any = {}
        try:
            payload = response.json()
        except Exception:  # noqa: BLE001 - an unreadable body is reported by its status
            pass
        if not response.ok:
            error = payload.get("error", {}) if isinstance(payload, dict) else {}
            raise AssertionError(f"The board refused the approval: HTTP {response.status} {error.get('code', 'unknown')}: {str(error.get('message', ''))[:200]}")
        expect(dialog.get_by_text("Proposal approved and applied.")).to_be_visible()
        applied_text = dialog.inner_text()
        dialog.get_by_role("button", name="Close").click()
        expect(dialog).to_have_count(0)
        return {
            "operation_id": sent.get("operation_id", ""),
            "preview_text": review_text,
            "applied_text": applied_text,
            "listed": {key: listed.get(key) for key in ("action", "item_id", "required_roles", "proposer", "stale", "preview_id")},
            "stages": board.stages(),
            "elapsed_s": round(time.monotonic() - started, 1),
        }

    def failure_screenshot(self, path: Path) -> bool:
        """Best-effort page screenshot after a failed step. Never taken before sign-in, while the token form is on screen."""

        if not self.signed_in or self.page is None:
            return False
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            self.page.screenshot(path=str(path))
            return True
        except Exception:  # noqa: BLE001
            return False

    def recover(self) -> None:
        """Close an open dialog and reload, so the next human step starts from the board."""

        if self.page is None:
            return
        try:
            self.page.reload()
        except Exception:  # noqa: BLE001
            pass
