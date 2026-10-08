"""Page object for the connected Prism board, using accessible locators.

Most locators are roles and labels. The board hides its background from the
accessibility tree while a review dialog is open (``aria-hidden`` and
``inert``), so the helpers that read the board behind the dialog pass
``include_hidden=True`` to still find the cards and columns by role.
"""

from __future__ import annotations

import re
import time
from typing import TYPE_CHECKING, Any, Callable

try:
    from playwright.sync_api import Error as PlaywrightError, expect
except ImportError:  # The optional `e2e` extra is absent; the tests are skipped.
    expect = None  # type: ignore[assignment]
    PlaywrightError = Exception  # type: ignore[assignment,misc]

if TYPE_CHECKING:
    from playwright.sync_api import Locator, Page

ACTION_TITLES = {
    "po-handoff": "Review handoff",
    "design-start": "Review design start",
    "dev-start": "Review development start",
}
REVIEWED_TEXT = re.compile(r"I reviewed the current source and every exact")


class BoardPage:
    def __init__(self, page: Page, base_url: str) -> None:
        self.page = page
        self.base_url = base_url
        self._held: list[Any] = []
        self._hold_graph = False
        self._gate_installed = False
        self.graph_requests_after_hold = 0

    # -- sign-in and navigation -------------------------------------------------

    def goto_home(self) -> None:
        """Open the board's address. Windows can briefly run out of socket buffers when many
        loopback connections were just closed (``ERR_NO_BUFFER_SPACE``); that one error is retried,
        any other navigation error is raised at once."""

        for attempt in range(4):
            try:
                self.page.goto(self.base_url + "/")
                return
            except PlaywrightError as error:
                if "ERR_NO_BUFFER_SPACE" not in str(error) or attempt == 3:
                    raise
                self.page.wait_for_timeout(1000)

    def sign_in(self, token: str) -> None:
        """Use the board's token form exactly as a person would."""

        self.goto_home()
        expect(self.page.get_by_role("heading", name="Connect to your Prism board")).to_be_visible()
        self.page.get_by_label("Participant token").fill(token)
        self.page.get_by_role("button", name="Connect").click()
        expect(self.page.get_by_role("button", name="Board", exact=True)).to_be_visible()
        expect(self.page.get_by_role("button", name="Sign out")).to_be_visible()

    def open_board(self) -> None:
        self.page.get_by_role("button", name="Board", exact=True).click()
        expect(self.column("specified")).to_be_visible()

    def wait_until_current(self, timeout: float = 20.0) -> None:
        """Wait until the board has adopted the newest snapshot the server holds.

        A write makes the server publish more than one version when its poller sees the files
        mid-write, and the browser adopts them one after the other. A live update that arrives
        while a drag is in flight cancels the drag, and one that arrives while a dialog is open
        re-renders it and moves focus. A test that starts a gesture right after an apply calls this
        first, so no later update can land in the middle of the gesture.
        """

        expect(self.freshness()).to_have_text("LIVE")
        self.page.wait_for_function(
            "async () => (await (await fetch('/data.json', { cache: 'no-store' })).json()).version === state.liveVersion",
            polling=100,
            timeout=timeout * 1000,
        )

    # -- board structure --------------------------------------------------------

    def column(self, stage: str) -> Locator:
        heading = self.page.get_by_role("heading", name=re.compile(rf"^{re.escape(stage)}(?![\w-])"), include_hidden=True)
        return heading.locator("xpath=..")

    def column_heading(self, stage: str) -> Locator:
        return self.page.get_by_role("heading", name=re.compile(rf"^{re.escape(stage)}(?![\w-])"), include_hidden=True)

    def card(self, feature_id: str) -> Locator:
        return self.page.get_by_role("group", name=re.compile(rf"^Feature {re.escape(feature_id)}:"), include_hidden=True)

    def card_in(self, stage: str, feature_id: str) -> Locator:
        return self.column(stage).get_by_role("group", name=re.compile(rf"^Feature {re.escape(feature_id)}:"), include_hidden=True)

    def action_button(self, feature_id: str, action_label: str) -> Locator:
        return self.page.get_by_role("button", name=f"Review and apply {action_label} for {feature_id}")

    # -- review dialog ----------------------------------------------------------

    def dialog(self, action: str) -> Locator:
        return self.page.get_by_role("dialog", name=ACTION_TITLES[action])

    @staticmethod
    def apply_button(dialog: Locator) -> Locator:
        return dialog.get_by_role("button", name="Apply reviewed changes")

    @staticmethod
    def acknowledgement(dialog: Locator) -> Locator:
        return dialog.get_by_role("checkbox", name=REVIEWED_TEXT)

    def read_writes(self, dialog: Locator, paths: list[str]) -> dict[str, dict[str, str]]:
        """Exact before and after text of every previewed write, keyed by path."""

        result: dict[str, dict[str, str]] = {}
        for path in paths:
            # The summary names the written path; a log entry's text may mention another path too.
            section = dialog.get_by_role("group").filter(has=dialog.page.locator("summary", has_text=path)).filter(has=dialog.page.get_by_role("heading", name="Before", exact=True))
            expect(section).to_have_count(1)
            result[path] = {
                "before": section.get_by_role("heading", name="Before", exact=True).locator("xpath=following-sibling::pre").text_content(),
                "after": section.get_by_role("heading", name="After", exact=True).locator("xpath=following-sibling::pre").text_content(),
            }
        return result

    def operation_id(self, dialog: Locator) -> str:
        """The operation ID the dialog reports for the applied operation."""

        expect(dialog.get_by_text("Operation ID · applied", exact=False)).to_be_visible()
        text = dialog.text_content() or ""
        match = re.search(r"Operation ID · applied\s*([0-9a-f-]{36})", text, re.IGNORECASE)
        if match is None:
            raise AssertionError("The dialog did not show an operation ID for the applied operation.")
        return match.group(1)

    # -- pointer ----------------------------------------------------------------

    def drag_card_to_stage(self, feature_id: str, title: str, stage: str, *, release: bool = True) -> None:
        """Press on the card's title, move the mouse over the destination column, release.

        With ``release=False`` the drag stays in flight over the column so a
        test can inspect the column's drop marker; call ``page.mouse.up()`` to finish.
        """

        # A live re-render can replace the board between lookups, so wait for both
        # elements and measure them again until a measurement is not interrupted.
        card_title = self.card(feature_id).get_by_text(title, exact=True)
        heading = self.column_heading(stage)
        source = target = None
        for _attempt in range(20):
            card_title.wait_for(state="visible")
            heading.wait_for(state="visible")
            source = card_title.bounding_box()
            target = heading.bounding_box()
            if source is not None and target is not None:
                break
            self.page.wait_for_timeout(100)
        if source is None or target is None:
            raise AssertionError("The card or the destination column is not visible to drag between.")
        mouse = self.page.mouse
        start = (source["x"] + source["width"] / 2, source["y"] + source["height"] / 2)
        mouse.move(*start)
        mouse.down()
        # The first small move starts the browser's native drag session.
        mouse.move(start[0] + 12, start[1] + 12)
        mouse.move(target["x"] + target["width"] / 2, target["y"] + target["height"] / 2, steps=15)
        if release:
            mouse.up()

    # -- keyboard ---------------------------------------------------------------

    def _active_label(self) -> str:
        return self.page.evaluate(
            """() => {
                const el = document.activeElement;
                if (!el) return "";
                const labelled = el.getAttribute("aria-label");
                if (labelled) return labelled;
                if (el.labels && el.labels.length) return el.labels[0].textContent.trim();
                return (el.textContent || "").trim();
            }"""
        )

    def tab_to(self, pattern: re.Pattern[str] | str, *, limit: int = 250) -> None:
        """Press Tab until the focused control's accessible name matches ``pattern``."""

        matcher: Callable[[str], bool] = (lambda text: pattern.search(text) is not None) if isinstance(pattern, re.Pattern) else (lambda text: pattern in text)
        for _ in range(limit):
            if matcher(self._active_label()):
                return
            self.page.keyboard.press("Tab")
        raise AssertionError(f"Keyboard focus never reached a control named {pattern!r} within {limit} Tab presses.")

    # -- live state, session and notices ----------------------------------------

    def freshness(self) -> Locator:
        """The LIVE / STALE / SNAPSHOT indicator in the header."""

        return self.page.locator("#freshness")

    def toast(self, text: str) -> Locator:
        return self.page.get_by_role("status").filter(has_text=text)

    def session_bar(self) -> Locator:
        return self.page.locator("#board-session")

    def operations_button(self) -> Locator:
        return self.page.get_by_role("button", name=re.compile(r"^Review \d+ pending board operations$"))

    def proposals_button(self) -> Locator:
        """The session-bar button that opens the proposals waiting for approval (a human who may write sees it)."""

        return self.page.get_by_role("button", name="Review the proposals that wait for approval")

    def agent_request_button(self, feature_id: str, label: str) -> Locator:
        """The card button that opens a provider-neutral MCP request for an agent-only action.

        A feature with several workflow actions has a picker on its card; the action named by `label` is chosen there first.
        """

        picker = self.page.get_by_role("combobox", name=f"Workflow action for {feature_id}")
        if picker.count():
            option = picker.locator("option", has_text=label).first
            picker.select_option(value=option.get_attribute("value"))
        return self.page.get_by_role("button", name=f"Prepare {label} for {feature_id}")

    def stages(self) -> dict[str, list[str]]:
        """Feature IDs per board column, as the board currently shows them."""

        return self.page.evaluate(
            """() => Object.fromEntries(Array.from(document.querySelectorAll('#board-view .column[data-stage]'))
                .filter(column => column.dataset.stage !== 'intake')
                .map(column => [column.dataset.stage, Array.from(column.querySelectorAll('.card[data-id] .cid')).map(el => el.textContent.trim())]))"""
        )

    def focus_description(self) -> dict[str, Any]:
        """What has keyboard focus: its accessible label and whether the browser draws a focus ring."""

        return self.page.evaluate(
            """() => {
                const el = document.activeElement;
                if (!el || el === document.body) return { label: "", ring: false, inDialog: false };
                const style = getComputedStyle(el);
                const outline = style.outlineStyle !== "none" && parseFloat(style.outlineWidth) > 0;
                const shadow = style.boxShadow && style.boxShadow !== "none";
                const label = el.getAttribute("aria-label") || (el.labels && el.labels[0] && el.labels[0].textContent.trim()) || (el.textContent || "").trim().slice(0, 80);
                return { label, ring: !!(outline || shadow), inDialog: !!el.closest('[role="dialog"]'), tag: el.tagName.toLowerCase() };
            }"""
        )

    # -- data.json refresh control ---------------------------------------------

    def install_graph_gate(self) -> None:
        """Let the test hold the board's refresh requests (browser-side only).

        This only delays responses inside the browser; the service and its
        files are untouched, and nothing in production code knows about it.
        """

        if self._gate_installed:
            return
        self._gate_installed = True

        def handler(route: Any) -> None:
            if self._hold_graph:
                self._held.append(route)
                self.graph_requests_after_hold += 1
            else:
                route.continue_()

        self.page.route(re.compile(r".*/data\.json(\?.*)?$"), handler)

    def hold_graph_refreshes(self) -> None:
        self._hold_graph = True
        self._held.clear()
        self.graph_requests_after_hold = 0

    def wait_for_held_refresh(self, timeout: float = 20.0) -> None:
        deadline = time.monotonic() + timeout
        while not self._held:
            if time.monotonic() > deadline:
                raise AssertionError("The board never requested a refresh after the apply.")
            self.page.wait_for_timeout(50)

    def release_graph_refreshes(self) -> None:
        self._hold_graph = False
        held, self._held = self._held, []
        for route in held:
            route.continue_()
