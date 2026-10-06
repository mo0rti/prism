"""Scenario L: the apply flow and a no-write flow across themes and viewport sizes.

Each test takes one viewport (desktop, tablet, phone) and runs, in a light and
a dark browser profile (emulated ``color_scheme``), scenario A (review and
apply a po-handoff) and a no-write flow (a blocked review that is closed). After
each flow the in-app day/night toggle flips the theme and the screen is saved
again. The tests check visible keyboard focus, the dialog's focus trap, focus
return, and that neither the page nor the dialog scrolls sideways. Every
screenshot is saved under the scenario's evidence folder as
``<viewport>-<scheme>-<step>.png`` for a contact sheet.
"""

from __future__ import annotations

import re
import unittest
from typing import Any

from tests.browser.board_page import BoardPage, expect
from tests.browser.harness import EXTRA_FEATURES, FEATURES_BY_ID, FixtureFeature, requires_browser_e2e
from tests.browser.scenario_support import BOARD_PATH, LOG_PATH, ScenarioCase, changed_paths, workspace_tree

BLOCKED = EXTRA_FEATURES["blocked"]
VIEWPORTS = {
    "desktop": {"width": 1500, "height": 950},
    "tablet": {"width": 768, "height": 1024},
    "phone": {"width": 390, "height": 844},
}
# One apply per scheme: each uses its own feature so the two runs do not depend on each other.
APPLY_FEATURE = {"light": FEATURES_BY_ID["F-001"], "dark": FEATURES_BY_ID["F-004"]}
TAB_PRESSES = 14


@requires_browser_e2e
class MatrixTests(ScenarioCase):
    extra_features = (BLOCKED,)

    # -- measurements ------------------------------------------------------------

    def theme(self, page: Any) -> str:
        return page.evaluate("() => document.documentElement.getAttribute('data-theme')")

    def assert_no_sideways_scroll(self, page: Any, label: str, *, dialog: Any = None) -> None:
        overflow = page.evaluate(
            "() => ({ scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth, body: document.body.scrollWidth })"
        )
        self.assertLessEqual(overflow["scroll"], overflow["client"], f"{label}: the page scrolls sideways {overflow}")
        if dialog is not None:
            inner = dialog.evaluate("el => ({ scroll: el.scrollWidth, client: el.clientWidth })")
            self.assertLessEqual(inner["scroll"], inner["client"], f"{label}: the dialog scrolls sideways {inner}")

    def assert_focus_in_dialog(self, board: BoardPage, label: str) -> None:
        focus = board.focus_description()
        self.assertTrue(focus["inDialog"], f"{label}: focus left the dialog and is on {focus}")

    def trap_check(self, page: Any, board: BoardPage, label: str) -> None:
        """Tab and Shift+Tab around the dialog's controls more times than there are controls; focus must never leave it.

        The walk starts on the Close button and presses a key wherever focus is,
        including the file-change rows and the dialog heading a live re-render
        focuses.
        """

        self.wait_until_current(board)
        board.tab_to("Close")
        self.assert_focus_in_dialog(board, f"{label} (on Close)")
        for key, count in (("Tab", TAB_PRESSES), ("Shift+Tab", TAB_PRESSES * 2)):
            for _ in range(count):
                page.keyboard.press(key)
                self.assert_focus_in_dialog(board, f"{label} ({key})")

    def assert_focus_returned(self, board: BoardPage, feature: FixtureFeature, label: str) -> None:
        """After the dialog closes, focus is on the feature's review button or its card."""

        inside = board.page.evaluate(
            """id => {
                const el = document.activeElement;
                const card = el && el.closest('.card[data-id]');
                return !!card && card.dataset.id === id;
            }""",
            feature.feature_id,
        )
        self.assertTrue(inside, f"{label}: focus did not return to {feature.feature_id}'s card: {board.focus_description()}")

    # -- flows -------------------------------------------------------------------

    def apply_flow(self, run: Any, board: BoardPage, page: Any, prefix: str, feature: FixtureFeature) -> None:
        harness = self.harness
        before = workspace_tree(harness.root)
        self.wait_until_current(board)
        expect(board.card_in("specified", feature.feature_id)).to_be_visible()

        # Reach the review button with the keyboard: it must show a focus ring.
        board.tab_to(re.compile(rf"^Review and apply handoff for {feature.feature_id}$"))
        focus = board.focus_description()
        self.assertTrue(focus["ring"], f"{prefix}: the Review button has no visible focus indicator: {focus}")
        run.screenshot(page, f"{prefix}-focus-on-review-button")
        page.keyboard.press("Enter")
        dialog = board.dialog("po-handoff")
        expect(dialog).to_be_visible()
        expect(dialog.get_by_role("heading", name=re.compile(r"^Exact file changes"))).to_be_visible()
        self.assert_focus_in_dialog(board, f"{prefix} dialog opened")
        run.screenshot(page, f"{prefix}-review-dialog")
        self.trap_check(page, board, f"{prefix} review dialog")
        self.assert_no_sideways_scroll(page, f"{prefix} review dialog", dialog=dialog)

        self.acknowledge(board, dialog)
        board.apply_button(dialog).scroll_into_view_if_needed()
        board.apply_button(dialog).click()
        self.wait_applied(board, dialog, feature, "ready-for-design")
        self.assert_no_sideways_scroll(page, f"{prefix} applied dialog", dialog=dialog)
        run.screenshot(page, f"{prefix}-applied-dialog")
        dialog.get_by_role("button", name="Close").click()
        expect(dialog).to_have_count(0)
        self.assert_focus_returned(board, feature, f"{prefix} after apply")
        expect(board.card_in("ready-for-design", feature.feature_id)).to_have_count(1)
        self.assert_no_sideways_scroll(page, f"{prefix} board after apply")
        run.screenshot(page, f"{prefix}-board-after-apply")

        changed = changed_paths(before, workspace_tree(harness.root))
        self.assertEqual({feature.path.as_posix(), BOARD_PATH, LOG_PATH}, changed)
        run.effect(f"{prefix}: apply changed only {feature.feature_id}'s page, the status board and the log")

    def no_write_flow(self, run: Any, board: BoardPage, page: Any, prefix: str) -> None:
        harness = self.harness
        before = workspace_tree(harness.root)
        self.wait_until_current(board)
        board.action_button(BLOCKED.feature_id, "handoff").click()
        dialog = board.dialog("po-handoff")
        expect(dialog).to_be_visible()
        expect(dialog.get_by_role("heading", name=re.compile(r"^Exact file changes"))).to_be_visible()
        expect(dialog.get_by_text("1 open PO-owned question remains: question 1.")).to_be_visible()
        expect(board.apply_button(dialog)).to_be_disabled()
        run.screenshot(page, f"{prefix}-blocked-dialog")
        self.trap_check(page, board, f"{prefix} blocked dialog")
        self.assert_no_sideways_scroll(page, f"{prefix} blocked dialog", dialog=dialog)
        page.keyboard.press("Escape")
        expect(dialog).to_have_count(0)
        self.assert_focus_returned(board, BLOCKED, f"{prefix} after Escape")
        self.assertEqual(before, workspace_tree(harness.root), f"{prefix}: a blocked review must not write")
        run.effect(f"{prefix}: blocked review explained, Apply disabled, closed with Escape; focus returned; workspace byte-identical")

    def toggle_theme(self, run: Any, board: BoardPage, page: Any, prefix: str, scheme: str) -> None:
        """Flip the theme with the in-app toggle and save the board and a dialog in the other theme."""

        other = "dark" if scheme == "light" else "light"
        self.wait_until_current(board)
        page.get_by_title("Day / night").click()
        self.assertEqual(other, self.theme(page))
        self.assert_no_sideways_scroll(page, f"{prefix} toggled board")
        run.screenshot(page, f"{prefix}-toggled-to-{other}-board")
        board.action_button(BLOCKED.feature_id, "handoff").click()
        dialog = board.dialog("po-handoff")
        expect(dialog).to_be_visible()
        expect(dialog.get_by_role("heading", name=re.compile(r"^Exact file changes"))).to_be_visible()
        self.assertEqual(other, self.theme(page))
        self.assert_no_sideways_scroll(page, f"{prefix} toggled dialog", dialog=dialog)
        run.screenshot(page, f"{prefix}-toggled-to-{other}-dialog")
        page.keyboard.press("Escape")
        expect(dialog).to_have_count(0)
        page.get_by_title("Day / night").click()
        self.assertEqual(scheme, self.theme(page))
        run.effect(f"{prefix}: the in-app toggle switched {scheme} -> {other} and back; the dialog rendered in both themes without sideways scroll")

    def run_viewport(self, name: str) -> None:
        size = VIEWPORTS[name]
        with self.scenario(f"L-matrix-{name}") as run:
            for scheme in ("light", "dark"):
                prefix = f"{name}-{scheme}"
                viewer = self.new_viewer(prefix, viewport=dict(size), color_scheme=scheme)
                page = viewer.page
                board = self.sign_in("human", page=page, trace=False)
                self.start_trace(viewer.context)
                self.assertEqual(scheme, self.theme(page), f"{prefix}: the emulated color scheme sets the theme")
                self.open_board(board)
                self.assert_no_sideways_scroll(page, f"{prefix} board")
                run.screenshot(page, f"{prefix}-board")
                self.apply_flow(run, board, page, prefix, APPLY_FEATURE[scheme])
                self.no_write_flow(run, board, page, prefix)
                self.toggle_theme(run, board, page, prefix, scheme)
            self.assertEqual([], self.page_errors)

    def test_scenario_l_matrix_desktop(self) -> None:
        self.run_viewport("desktop")

    def test_scenario_l_matrix_tablet(self) -> None:
        self.run_viewport("tablet")

    def test_scenario_l_matrix_phone(self) -> None:
        self.run_viewport("phone")

    def test_scenario_l_defect_tablet_page_scrolls_sideways(self) -> None:
        """At 768x1024 the page does not scroll sideways.

        The header's right-hand group (the confidence light, LIVE indicator,
        session bar and theme toggle) wraps instead of sticking out past the
        viewport. Every tested width is measured, here also with the session bar
        showing.
        """

        with self.scenario("L-defect-tablet-sideways-scroll"):
            size = VIEWPORTS["tablet"]
            viewer = self.new_viewer("tablet-light", viewport=dict(size), color_scheme="light")
            board = self.sign_in("human", page=viewer.page)
            self.open_board(board)
            self.assert_no_sideways_scroll(viewer.page, "tablet board")

    def test_scenario_l_defect_dialog_loses_focus_on_shift_tab(self) -> None:
        """Shift+Tab from the dialog's first text region stays in the dialog.

        The file-change sections (``summary`` rows and scrollable before/after
        text) are keyboard-focusable and come before the first button. After
        opening the dialog, one Tab lands on the first file-change row and one
        Shift+Tab wraps to the last control instead of leaving the dialog; the
        same holds from the dialog heading.
        """

        with self.scenario("L-defect-dialog-focus-trap-shift-tab"):
            page = self.page
            board = self.sign_in("human")
            self.open_board(board)
            board.action_button(BLOCKED.feature_id, "handoff").click()
            dialog = board.dialog("po-handoff")
            expect(dialog.get_by_role("heading", name=re.compile(r"^Exact file changes"))).to_be_visible()
            page.keyboard.press("Tab")
            self.assert_focus_in_dialog(board, "after the first Tab")
            page.keyboard.press("Shift+Tab")
            self.assert_focus_in_dialog(board, "after Shift+Tab")
            # From the heading (where a live re-render leaves focus) Shift+Tab wraps to the last control too.
            dialog.get_by_role("heading", name=re.compile(r"^Review ")).focus()
            page.keyboard.press("Shift+Tab")
            self.assert_focus_in_dialog(board, "after Shift+Tab from the heading")


if __name__ == "__main__":
    unittest.main()
