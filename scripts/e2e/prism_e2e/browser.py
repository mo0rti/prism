"""Human steps in headless Chromium, through the board's own page object.

``tests/browser/board_page.py`` is imported from the repository and not
changed. ``PRISM_BROWSER_E2E_EXECUTABLE`` selects an existing Chromium, as in
the browser test suite; without it Playwright's bundled browser runs.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import re
import time
from typing import Any

from . import config

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
    def __init__(self, base_url: str, human_token: str) -> None:
        self._base_url = base_url
        self._token = human_token
        self._pw: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._module: Any = None
        self.page: Any = None
        self.board: Any = None
        self.version = "unknown"
        self.signed_in = False

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

    # -- one human action --------------------------------------------------------------

    def perform(self, action: str, feature_id: str, workspace: Path, screenshot_dir: Path) -> dict[str, Any]:
        """Preview and apply one human lifecycle action on the board, as a person would.

        Returns the dialog texts, the exact writes the preview showed, the operation ID the dialog reports and
        the board's columns afterwards. Any failed expectation raises; the caller marks the step failed.
        """

        label = config.HUMAN_ACTION_LABELS[action]
        expect = self._module.expect
        board = self.board
        page = self.page
        started = time.monotonic()
        if not self.signed_in:
            board.sign_in(self._token)
            self.signed_in = True
        else:
            page.reload()
        board.open_board()
        board.action_button(feature_id, label).click()
        dialog = board.dialog(action)
        expect(dialog).to_be_visible()
        expect(dialog.get_by_role("heading", name=re.compile(r"^Exact file changes"))).to_be_visible()
        feature_page = next((workspace / "knowledge/wiki/features").glob(f"{feature_id}-*.md")).relative_to(workspace).as_posix()
        writes = board.read_writes(dialog, [feature_page, "knowledge/wiki/index.md", "knowledge/wiki/log.md"])
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
