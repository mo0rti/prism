"""Scenario M: the board page shows the bugs, the release records and the incidents.

The page is a static export of a synthetic graph envelope (tests/records_views_fixture.py) that follows the shape of
`facts.bugs`, `facts.releases` and `facts.incidents`. The test opens each view, a panel from each, follows links between
records and from a record to its feature, and checks the filters, the keyboard and the phone width.
"""

from __future__ import annotations

from pathlib import Path
import re
import shutil
import tempfile
import unittest

from prism_cli.wiki_graph_html import render_html
from tests.browser.board_page import BoardPage, expect
from tests.browser.harness import BrowserCase, e2e_directory, requires_browser_e2e
from tests.records_views_fixture import records_envelope


@requires_browser_e2e
class RecordsViewsTests(BrowserCase):
    serve_in_process = False

    def export(self) -> str:
        """Write the static page of the synthetic envelope and return its address."""

        work = e2e_directory() / "work"
        work.mkdir(parents=True, exist_ok=True)
        parent = Path(tempfile.mkdtemp(prefix="records-", dir=work))
        self.addCleanup(shutil.rmtree, parent, True)
        target = parent / "records.html"
        target.write_text(render_html(records_envelope(parent)), encoding="utf-8")
        return target.as_uri()

    def open_view(self, name: str) -> None:
        self.page.get_by_role("button", name=name, exact=True).click()
        view = self.page.locator("#app-view" if name == "Apps" else f"#{name.lower()}-view")
        expect(view).to_be_visible()
        expect(view).to_have_css("opacity", "1")

    def panel(self):
        return self.page.locator("#panel")

    def test_scenario_m_bugs_releases_and_incidents_views(self) -> None:
        with self.scenario("M-records-views") as run:
            page = self.page
            self.start_trace()
            address = self.export()
            page.goto(address)
            board = BoardPage(page, address)
            expect(board.freshness()).to_contain_text("SNAPSHOT")

            # 1. The header tile counts the open bugs, says how many block, and opens the Bugs view.
            tile = page.get_by_role("button", name=re.compile(r"^Open bugs: 6, 1 blocking"))
            expect(tile).to_be_visible()
            tile.click()
            expect(page.locator("#bugs-view")).to_be_visible()
            expect(page.locator("#bugs-view")).to_have_css("opacity", "1")
            run.screenshot(page, "bugs-view")
            columns = page.locator("#bugs-view .column[data-stage]")
            self.assertEqual(["open", "in-fix", "fixed", "verified", "released", "closed", "invalid"], columns.evaluate_all("els => els.map(el => el.dataset.stage)"))
            expect(page.get_by_role("heading", name="Bug status released")).to_have_count(1)
            # A feature's own column keeps its name: the bug columns do not take over the board's headings.
            expect(board.column_heading("released")).to_have_count(1)
            critical = page.get_by_role("group", name=re.compile(r"^Bug BUG-001:"))
            expect(critical).to_contain_text("critical")
            expect(critical).to_contain_text("blocking")
            expect(page.get_by_role("group", name=re.compile(r"^Bug BUG-009:"))).to_contain_text("invalid")
            run.effect("Bugs view: a column per status plus an invalid one; BUG-001 shows critical and blocking; the invalid page shows a warning")

            # 2. A bug card opens its panel; a link in the panel opens the release record's panel.
            page.get_by_role("group", name=re.compile(r"^Bug BUG-005:")).locator(".ctitle").click()
            panel = self.panel()
            expect(panel).to_have_class(re.compile(r"\bopen\b"))
            expect(panel.get_by_role("heading", name="Wrong locale in the sign-in mail")).to_be_visible()
            expect(panel.locator("[data-panel-fix]")).to_contain_text("commit:77c0de1")
            expect(panel.locator("[data-panel-verification]")).to_contain_text("qa-3")
            expect(panel.locator("[data-panel-release]")).to_contain_text("production")
            expect(panel).to_contain_text("knowledge/wiki/bugs/BUG-005-")
            expect(panel.get_by_role("link", name="Copy")).to_be_visible()
            run.screenshot(page, "bug-panel")
            panel.get_by_role("button", name="Open REL-002").click()
            expect(panel.get_by_role("heading", name="Review summary export, retry")).to_be_visible()
            expect(panel.locator("[data-panel-deliveries]")).to_contain_text("build:web#31")
            expect(panel.locator("[data-panel-chain]")).to_contain_text("Retry of")
            expect(panel.locator("[data-panel-chain]")).to_contain_text("Rolled back by")
            run.screenshot(page, "release-panel-from-a-bug")
            run.effect("a bug panel lists its fix, verification and release rows; its REL-002 link opens that record's panel with deliveries and chain")

            # 3. The follow-up chain: the retry names the earlier record, and a link opens it.
            panel.get_by_role("button", name="Open REL-001").click()
            expect(panel.locator("[data-panel-chain]")).to_contain_text("Retried by")
            page.keyboard.press("Escape")
            expect(panel).not_to_have_class(re.compile(r"\bopen\b"))

            # 4. The filters: by app and blocking only; the control keeps keyboard focus.
            app_filter = page.get_by_role("combobox", name="Filter bugs by app")
            # A person focuses the control before choosing; `select_option` alone leaves focus where it was.
            app_filter.focus()
            app_filter.select_option("web")
            expect(page.locator("#bugs-view [data-record-id]")).to_have_count(2)
            expect(page.get_by_role("combobox", name="Filter bugs by app")).to_be_focused()
            blocking = page.get_by_role("button", name=re.compile(r"^Blocking only"))
            blocking.click()
            expect(page.locator("#bugs-view")).to_contain_text("No bugs match the filters.")
            expect(page.get_by_role("button", name=re.compile(r"^Blocking only"))).to_have_attribute("aria-pressed", "true")
            page.get_by_role("combobox", name="Filter bugs by app").select_option("")
            expect(page.locator("#bugs-view [data-record-id]")).to_have_count(1)
            page.get_by_role("button", name=re.compile(r"^Blocking only")).click()
            expect(page.locator("#bugs-view [data-record-id]")).to_have_count(12)
            run.effect("the app filter and blocking-only toggle narrow the board and keep focus on the control")

            # 5. The Releases view: newest first, with the kind, the outcome, the current mark, the chain and the deliveries.
            self.open_view("Releases")
            run.screenshot(page, "releases-view")
            ids = page.locator("#releases-view [data-record-id]").evaluate_all("els => els.map(el => el.dataset.recordId)")
            self.assertEqual(["REL-006", "REL-004", "REL-003", "REL-002", "REL-001", "REL-005", "REL-007"], ids)
            retry = page.get_by_role("group", name=re.compile(r"^Release record REL-002:"))
            expect(retry).to_contain_text("retry")
            expect(retry).to_contain_text("released")
            expect(retry).to_contain_text("current")
            expect(retry).to_contain_text("retry of")
            expect(retry).to_contain_text("build:backend#412")
            expect(page.get_by_role("group", name=re.compile(r"^Release record REL-003:"))).to_contain_text("rollback of")
            page.get_by_role("combobox", name="Filter releases by app").select_option("web")
            page.get_by_role("combobox", name="Filter releases by target").select_option("staging")
            self.assertEqual(["REL-002"], page.locator("#releases-view [data-record-id]").evaluate_all("els => els.map(el => el.dataset.recordId)"))
            page.get_by_role("combobox", name="Filter releases by app").select_option("")
            page.get_by_role("combobox", name="Filter releases by target").select_option("")
            expect(page.locator("#releases-view [data-record-id]")).to_have_count(7)
            # The chain link on a card opens the earlier record without opening the card itself.
            page.get_by_role("group", name=re.compile(r"^Release record REL-003:")).get_by_role("button", name="Open REL-002").click()
            expect(panel.get_by_role("heading", name="Review summary export, retry")).to_be_visible()
            page.keyboard.press("Escape")
            run.effect("Releases view: newest first, kind, outcome and current badges, chain links and delivery rows; the filters match one delivery")

            # 6. The Incidents view and its panel, then from the incident to its feature, and from the feature to a bug.
            self.open_view("Incidents")
            run.screenshot(page, "incidents-view")
            expect(page.get_by_role("heading", name="Incident status mitigated")).to_be_visible()
            self.assertEqual(
                ["INC-004", "INC-001", "INC-005"],
                page.locator('#incidents-view .column[data-stage="open"] [data-record-id]').evaluate_all("els => els.map(el => el.dataset.recordId)"),
            )
            expect(page.get_by_role("group", name=re.compile(r"^Incident INC-001:"))).to_contain_text("cause unknown")
            page.get_by_role("group", name=re.compile(r"^Incident INC-002:")).locator(".ctitle").click()
            expect(panel.locator("[data-panel-timeline]")).to_contain_text("Showing the last 20 lines; more lines on the page.")
            run.screenshot(page, "incident-panel")
            page.get_by_role("group", name=re.compile(r"^Incident INC-001:")).locator(".ctitle").click()
            panel.get_by_role("button", name="Open feature F-001").click()
            expect(panel.get_by_role("heading", name="Review summary export")).to_be_visible()
            expect(panel.locator("[data-panel-bugs]")).to_contain_text("BUG-001")
            expect(panel.locator("[data-panel-releases]")).to_contain_text("REL-003")
            run.screenshot(page, "feature-panel-with-records")
            panel.get_by_role("button", name="Open BUG-002").click()
            expect(panel.get_by_role("heading", name="Export drops right-to-left text")).to_be_visible()
            run.effect("an incident panel shows its timeline and the truncation note; its feature link opens the feature panel, which lists the feature's bugs and release records")

            # 7. The Apps view opens a record from the operations facts.
            page.keyboard.press("Escape")
            self.open_view("Apps")
            page.locator("#app-view").get_by_role("button", name="Open INC-001").first.click()
            expect(panel.get_by_role("heading", name="Blank summary for right-to-left comments")).to_be_visible()
            page.keyboard.press("Escape")

            # 8. Keyboard: a card is reachable with Tab and opens with Enter.
            self.open_view("Bugs")
            page.get_by_role("group", name=re.compile(r"^Bug BUG-004:")).focus()
            expect(page.get_by_role("group", name=re.compile(r"^Bug BUG-004:"))).to_be_focused()
            page.keyboard.press("Enter")
            expect(panel.get_by_role("heading", name="Timeout on a long document")).to_be_visible()
            page.keyboard.press("Escape")
            run.effect("the Apps view links open the record panels; a focused card opens with Enter")

            # 9. Both themes and the phone width: nothing makes the page itself scroll sideways.
            page.locator("#theme-toggle").click()
            run.screenshot(page, "bugs-view-other-theme")
            page.set_viewport_size({"width": 390, "height": 844})
            for name in ("Bugs", "Releases", "Incidents"):
                self.open_view(name)
                overflow = page.evaluate("() => document.documentElement.scrollWidth - window.innerWidth")
                self.assertLessEqual(overflow, 0, f"the {name} view made the page scroll sideways at a phone width")
                switcher = page.locator("#views")
                self.assertTrue(switcher.evaluate("el => el.scrollWidth >= el.clientWidth"))
                run.screenshot(page, f"{name.lower()}-view-phone")
            page.get_by_role("group", name=re.compile(r"^Incident INC-001:")).scroll_into_view_if_needed()
            self.assertEqual([], self.page_errors)
            run.effect("the record views fit a 390 px wide phone: the page does not scroll sideways, and the view switcher scrolls inside itself")

    def test_scenario_m_an_empty_view_says_so(self) -> None:
        with self.scenario("M-records-empty") as run:
            page = self.page
            self.start_trace()
            work = e2e_directory() / "work"
            work.mkdir(parents=True, exist_ok=True)
            parent = Path(tempfile.mkdtemp(prefix="records-empty-", dir=work))
            self.addCleanup(shutil.rmtree, parent, True)
            envelope = records_envelope(parent)
            envelope["facts"]["bugs"] = []
            envelope["facts"]["releases"] = []
            envelope["facts"]["incidents"] = []
            target = parent / "empty.html"
            target.write_text(render_html(envelope), encoding="utf-8")
            page.goto(target.as_uri())
            for name, message in (("Bugs", "No bugs recorded."), ("Releases", "No release records."), ("Incidents", "No incidents recorded.")):
                self.open_view(name)
                expect(page.locator(f"#{name.lower()}-view")).to_contain_text(message)
            run.screenshot(page, "incidents-empty")
            run.effect("each record view without records shows a short message instead of empty columns")
            self.assertEqual([], self.page_errors)


if __name__ == "__main__":
    unittest.main()
