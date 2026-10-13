"""Scenario L: the board page explains a feature's status with its per-app stages and offers the registry's return actions.

A feature's status is the minimum of its apps' stages. The card and the panel list each app with its stage, a feature in
design lists its design tracks, the Apps view shows each app's operational facts, and the page reads its action rules from
the registry the server sends, so a return action of a feature in development is a request it can open. The page is a
static export, which is copy-only and needs no session.
"""

from __future__ import annotations

from pathlib import Path
import re
import shutil
import tempfile
import unittest
from typing import Any, Callable

from prism_cli.wiki_graph import build_graph
from prism_cli.wiki_graph_html import render_html
from tests.board_page_fixture import two_app_workspace
from tests.browser.board_page import BoardPage, expect
from tests.browser.harness import EXTRA_FEATURES, BrowserCase, build_workspace, e2e_directory, requires_browser_e2e

IN_DESIGN = EXTRA_FEATURES["in-design"]
# An app ID of 80 characters in one word, a stage name of several words, and a design state of several words.
LONG_APP = "app" + "0123456789" * 7 + "abcdefg"
LONG_STAGE = "ready-for-qa-then-a-long-stage-name-with-many-more-words-than-fit-in-a-panel"
LONG_STATE = "waiting-for-the-design-review-that-is-scheduled-after-the-next-planning-meeting"

# Measures a row of the panel: the text of each part, whether a part is cut, and whether anything leaves the row or the panel.
MEASURE_ROW = """row => {
    const panel = document.querySelector('#panel');
    const box = row.getBoundingClientRect();
    const parts = [row, ...row.querySelectorAll('*')];
    return {
        cut: parts.filter(part => part.scrollWidth > part.clientWidth).map(part => part.className || part.tagName),
        outside: parts.filter(part => part.getBoundingClientRect().right > box.right + 0.5).map(part => part.className || part.tagName),
        ellipsis: parts.filter(part => getComputedStyle(part).textOverflow === 'ellipsis').map(part => part.className),
        titled: parts.filter(part => part.hasAttribute('title')).map(part => part.className || part.tagName),
        rowRight: box.right,
        panelRight: panel.getBoundingClientRect().right,
        panelScroll: [panel.scrollWidth, panel.clientWidth],
    };
}"""


def squeezed(texts: list[str]) -> list[str]:
    return [re.sub(r"\s+", "", text) for text in texts]


@requires_browser_e2e
class StagesAndReturnsTests(BrowserCase):
    serve_in_process = False

    def export(self, root: Path, name: str, edit: Callable[[dict[str, Any]], None] | None = None) -> str:
        """Write the static page of the workspace `root` and return its address.

        `edit` changes the graph data before it is embedded, for a case the workspace rules do not let a page hold.
        """

        work = e2e_directory() / "work"
        work.mkdir(parents=True, exist_ok=True)
        parent = Path(tempfile.mkdtemp(prefix="stages-", dir=work))
        self.addCleanup(shutil.rmtree, parent, True)
        target = parent / f"{name}.html"
        envelope = build_graph(root)
        if edit is not None:
            edit(envelope)
        target.write_text(render_html(envelope), encoding="utf-8")
        return target.as_uri()

    def test_scenario_l_stages_tracks_operations_and_returns(self) -> None:
        with self.scenario("L-stages-tracks-operations-returns") as run:
            page = self.page
            self.start_trace()

            # 1. One app released and one in QA: the card and the panel show both stages beside the aggregate status.
            with two_app_workspace("released-and-in-qa") as root:
                address = self.export(root, "released-and-in-qa")
            page.goto(address)
            board = BoardPage(page, address)
            expect(board.freshness()).to_contain_text("SNAPSHOT")
            board.open_board()
            card = board.card_in("in-qa", "F-001")
            expect(card).to_have_count(1)
            stages = card.locator("[data-app-stages] .app-stage")
            expect(stages).to_have_count(2)
            self.assertEqual(["backend·released", "worker·in-qa"], squeezed(stages.all_inner_texts()))
            expect(card.locator("[data-design-tracks]")).to_have_count(0)
            run.screenshot(page, "card-with-app-stages")
            card.locator(".ctitle").click()
            panel_stages = page.locator("#panel [data-panel-app-stages] .app-stage")
            expect(panel_stages).to_have_count(2)
            self.assertEqual(["backend·released", "worker·in-qa"], squeezed(panel_stages.all_inner_texts()))
            expect(page.locator("#panel")).to_contain_text("in-qa")
            run.screenshot(page, "panel-with-app-stages")
            run.effect("card and panel list `backend · released` and `worker · in-qa`; the feature stays in the in-qa column")

            # 2. The Apps view shows each app's operational facts, the same rows as the status board's Operations table.
            page.locator('.views button[data-view="app"]').click()
            expect(page.locator("#app-view")).to_be_visible()
            expect(page.locator("#app-view")).to_have_css("opacity", "1")
            backend = page.locator('[data-app-operations="backend"]')
            worker = page.locator('[data-app-operations="worker"]')
            expect(backend).to_be_visible()
            expect(backend).to_contain_text("Released features")
            expect(backend).to_contain_text("F-001")
            expect(worker).to_contain_text("Open bugs")
            expect(worker).to_contain_text("BUG-001")
            run.screenshot(page, "apps-operations")
            run.effect("Apps view: backend lists F-001 as released, worker lists BUG-001 as open")

            # 3. A feature in development offers the return actions of the registry, and the page can open one.
            with two_app_workspace("in-dev") as root:
                address = self.export(root, "in-dev")
            page.goto(address)
            board = BoardPage(page, address)
            board.open_board()
            card = board.card_in("in-dev", "F-001")
            expect(card).to_have_count(1)
            expect(card.locator("[data-app-stages] .app-stage")).to_have_count(2)
            self.assertEqual(["backend·ready-for-qa", "worker·in-dev"], squeezed(card.locator("[data-app-stages] .app-stage").all_inner_texts()))
            picker = page.get_by_role("combobox", name="Workflow action for F-001")
            options = picker.locator("option")
            labels = [text.strip() for text in options.all_text_contents()]
            returns = [label for label in labels if label.startswith(("return to specification ->", "return to design ->"))]
            self.assertEqual(2, len(returns), labels)
            # `backend` is at `ready-for-qa`, so the QA returns are offered too; the option is the one that starts with the label.
            option = options.filter(has_text=re.compile(r"^\s*return to specification ->"))
            picker.select_option(value=option.get_attribute("value"))
            prepare = card.locator("button[data-transition-id]")
            expect(prepare).not_to_have_attribute("aria-disabled", "true")
            prepare.click()
            dialog = page.get_by_role("dialog", name="Prepare return to specification")
            expect(dialog).to_be_visible()
            expect(dialog.get_by_role("button", name=re.compile(r"Apply|Recover"))).to_have_count(0)
            run.screenshot(page, "return-action-request")
            run.effect("a return action of a feature in development opens its copy-only request; no Apply control")
            page.keyboard.press("Escape")

            # 4. A feature in design lists its design tracks on the card and in the panel.
            with tempfile.TemporaryDirectory(dir=e2e_directory() / "work") as temporary:
                root = build_workspace(Path(temporary) / "document-review", (IN_DESIGN,))
                address = self.export(root, "in-design")
            page.goto(address)
            board = BoardPage(page, address)
            board.open_board()
            card = board.card_in("in-design", IN_DESIGN.feature_id)
            expect(card).to_have_count(1)
            tracks = card.locator("[data-design-tracks] .design-track")
            expect(tracks).to_have_count(2)
            self.assertEqual(["ui·not-applicable", "technical·done"], squeezed(tracks.all_inner_texts()))
            card.locator(".ctitle").click()
            panel_tracks = page.locator("#panel [data-panel-design-tracks] .design-track")
            expect(panel_tracks).to_have_count(2)
            self.assertEqual(["ui·not-applicable", "technical·done"], squeezed(panel_tracks.all_inner_texts()))
            run.effect("a feature in design lists `ui · not-applicable` and `technical · done` on its card and in its panel")
            self.assertEqual([], self.page_errors)

    def test_scenario_l_an_app_with_only_a_standalone_bug_or_incident_is_in_the_apps_view(self) -> None:
        with self.scenario("L-standalone-operations-in-apps-view") as run:
            page = self.page
            self.start_trace()
            with two_app_workspace("standalone-operations") as root:
                address = self.export(root, "standalone-operations")
            page.goto(address)
            page.locator('.views button[data-view="app"]').click()
            expect(page.locator("#app-view")).to_be_visible()
            expect(page.locator("#app-view")).to_have_css("opacity", "1")
            expect(page.locator("#app-view")).not_to_contain_text("No app targets found")
            backend = page.locator('[data-app-operations="backend"]')
            worker = page.locator('[data-app-operations="worker"]')
            expect(backend).to_be_visible()
            expect(backend).to_contain_text("BUG-002")
            expect(worker).to_be_visible()
            expect(worker).to_contain_text("INC-001")
            expect(page.locator("#app-view .lane")).to_have_count(2)
            expect(page.locator("#app-view")).to_contain_text("No features target this app yet.")
            run.screenshot(page, "standalone-operations")
            run.effect("Apps view: backend lists its standalone bug and worker its open incident although no feature targets either")
            self.assertEqual([], self.page_errors)

    def test_scenario_l_an_app_stage_line_never_breaks_inside_the_app_id_or_the_stage(self) -> None:
        with self.scenario("L-app-stage-narrow") as run:
            page = self.page
            self.start_trace()
            with two_app_workspace("in-dev") as root:
                address = self.export(root, "narrow-in-dev")
            page.goto(address)
            board = BoardPage(page, address)
            board.open_board()
            card = board.card_in("in-dev", "F-001")
            expect(card).to_have_count(1)
            lines = """elements => elements.map(element => {
                const style = getComputedStyle(element);
                const lineHeight = parseFloat(style.lineHeight) || parseFloat(style.fontSize) * 1.4;
                return Math.round(element.getBoundingClientRect().height / lineHeight);
            })"""

            def assert_whole_words(rows, label: str) -> None:
                words = rows.locator(".as-name, .as-stage")
                self.assertEqual([1] * words.count(), words.evaluate_all(lines), f"{label}: an app ID or a stage wrapped inside itself")

            # 1. A card narrower than `backend · ready-for-qa`: the line wraps at the separator, and no word is split.
            page.add_style_tag(content=".card { width: 104px !important; max-width: 104px !important; }")
            rows = card.locator("[data-app-stages] .app-stage")
            expect(rows).to_have_count(2)
            assert_whole_words(rows, "card")
            tops = rows.first.evaluate("row => [...row.querySelectorAll('.as-name, .as-stage')].map(item => Math.round(item.getBoundingClientRect().top))")
            self.assertGreater(tops[1], tops[0], "the stage moves to its own line when the card is too narrow for both")
            run.screenshot(page, "narrow-card-app-stages")

            # 2. A card narrower than a word: the value is cut with an ellipsis and its full text stays in a title.
            page.add_style_tag(content=".card { width: 60px !important; max-width: 60px !important; }")
            assert_whole_words(rows, "narrower card")
            cut = rows.first.locator(".as-stage")
            self.assertEqual("ellipsis", cut.evaluate("item => getComputedStyle(item).textOverflow"))
            self.assertEqual("ready-for-qa", cut.get_attribute("title"))
            self.assertEqual("backend", rows.first.locator(".as-name").get_attribute("title"))
            self.assertTrue(cut.evaluate("item => item.scrollWidth > item.clientWidth"), "the stage is wider than the card, so it is cut")

            # 3. The panel keeps the same rule at a phone width, and the Apps view chip keeps its stage label on one line.
            page.set_viewport_size({"width": 320, "height": 800})
            card.locator(".ctitle").click()
            panel_rows = page.locator("#panel [data-panel-app-stages] .app-stage")
            expect(panel_rows).to_have_count(2)
            assert_whole_words(panel_rows, "panel")
            page.locator('.views button[data-view="app"]').click()
            expect(page.locator("#app-view")).to_have_css("opacity", "1")
            page.add_style_tag(content=".lane { width: 150px !important; }")
            chips = page.locator("#app-view .fchip .req")
            self.assertGreater(chips.count(), 0)
            self.assertEqual([1] * chips.count(), chips.evaluate_all(lines), "an Apps view chip label wrapped inside itself")
            run.effect("a narrow card, the panel at a phone width and an Apps view chip keep each app ID and stage on one line")
            self.assertEqual([], self.page_errors)

    def test_scenario_l_the_panel_shows_a_long_app_id_and_stage_in_full_while_the_card_cuts_them(self) -> None:
        self.assertEqual(80, len(LONG_APP))
        with self.scenario("L-panel-app-stage-full") as run:
            page = self.page
            self.start_trace()

            def lengthen(envelope: dict[str, Any]) -> None:
                feature = next(node for node in envelope["facts"]["nodes"] if node["id"] == "F-001")
                feature["app_stages"] = [{"app": LONG_APP, "stage": LONG_STAGE}, {"app": "worker", "stage": "in-dev"}]

            with two_app_workspace("in-dev") as root:
                address = self.export(root, "long-app-stage", lengthen)
            page.goto(address)
            board = BoardPage(page, address)
            board.open_board()
            card = board.card_in("in-dev", "F-001")
            expect(card).to_have_count(1)

            # 1. The card keeps its look: the app ID and the stage are cut with an ellipsis and carry their full value in a title.
            card_row = card.locator("[data-app-stages] .app-stage").first
            card_name = card_row.locator(".as-name")
            card_stage = card_row.locator(".as-stage")
            self.assertEqual("ellipsis", card_name.evaluate("item => getComputedStyle(item).textOverflow"))
            self.assertTrue(card_name.evaluate("item => item.scrollWidth > item.clientWidth"), "the card cuts the app ID")
            self.assertEqual(LONG_APP, card_name.get_attribute("title"))
            self.assertEqual(LONG_STAGE, card_stage.get_attribute("title"))
            self.assertTrue(card_stage.inner_text().endswith("\u2026"), card_stage.inner_text())
            self.assertLess(len(card_stage.inner_text()), len(LONG_STAGE))

            # 2. The panel shows both whole, wrapped, with nothing cut or leaving the row, at a desktop and at a phone width.
            card.locator(".ctitle").click()
            expect(page.locator("#panel")).to_have_class(re.compile(r"\bopen\b"))
            rows = page.locator("#panel [data-panel-app-stages] .app-stage")
            expect(rows).to_have_count(2)
            for label, size in (("desktop", {"width": 1500, "height": 950}), ("phone", {"width": 320, "height": 800})):
                with self.subTest(width=label):
                    page.set_viewport_size(size)
                    expect(page.locator("#panel")).to_have_class(re.compile(r"\bopen\b"))
                    long_row = rows.first
                    self.assertEqual(LONG_APP, long_row.locator(".as-name").inner_text())
                    self.assertEqual(LONG_STAGE, long_row.locator(".as-stage").inner_text())
                    self.assertEqual(f"{LONG_APP}\u00b7{LONG_STAGE}", squeezed([long_row.inner_text()])[0])
                    for index in range(rows.count()):
                        measured = rows.nth(index).evaluate(MEASURE_ROW)
                        self.assertEqual([], measured["cut"], f"{label} row {index}: a part is cut")
                        self.assertEqual([], measured["outside"], f"{label} row {index}: a part leaves the row")
                        self.assertEqual([], measured["ellipsis"], f"{label} row {index}: a part ellipsizes")
                        self.assertEqual([], measured["titled"], f"{label} row {index}: the full text needs no title")
                        self.assertLessEqual(measured["rowRight"], measured["panelRight"] + 0.5)
                        self.assertLessEqual(measured["panelScroll"][0], measured["panelScroll"][1], f"{label}: the panel scrolls horizontally")
                    run.screenshot(page, f"panel-long-app-stage-{label}")
            run.effect("the card cuts an 80-character app ID and a long stage with an ellipsis and a title; the panel shows both whole at desktop and phone widths")
            self.assertEqual([], self.page_errors)

    def test_scenario_l_the_panel_shows_a_long_design_track_state_in_full_while_the_card_cuts_it(self) -> None:
        with self.scenario("L-panel-design-track-full") as run:
            page = self.page
            self.start_trace()

            def lengthen(envelope: dict[str, Any]) -> None:
                feature = next(node for node in envelope["facts"]["nodes"] if node["id"] == IN_DESIGN.feature_id)
                feature["design_tracks"] = {"ui": LONG_STATE, "technical": "done"}

            with tempfile.TemporaryDirectory(dir=e2e_directory() / "work") as temporary:
                root = build_workspace(Path(temporary) / "document-review", (IN_DESIGN,))
                address = self.export(root, "long-design-track", lengthen)
            page.goto(address)
            board = BoardPage(page, address)
            board.open_board()
            card = board.card_in("in-design", IN_DESIGN.feature_id)
            expect(card).to_have_count(1)

            # 1. The card cuts the state and keeps its full value in a title.
            card_state = card.locator("[data-design-tracks] .design-track").first.locator("span").last
            self.assertTrue(card_state.inner_text().endswith("\u2026"), card_state.inner_text())
            self.assertEqual(LONG_STATE, card_state.get_attribute("title"))

            # 2. The panel shows the track and the state whole, with nothing cut or leaving the row.
            card.locator(".ctitle").click()
            expect(page.locator("#panel")).to_have_class(re.compile(r"\bopen\b"))
            rows = page.locator("#panel [data-panel-design-tracks] .design-track")
            expect(rows).to_have_count(2)
            for label, size in (("desktop", {"width": 1500, "height": 950}), ("phone", {"width": 320, "height": 800})):
                with self.subTest(width=label):
                    page.set_viewport_size(size)
                    expect(page.locator("#panel")).to_have_class(re.compile(r"\bopen\b"))
                    self.assertEqual([f"ui\u00b7{LONG_STATE}", "technical\u00b7done"], squeezed(rows.all_inner_texts()))
                    self.assertEqual(LONG_STATE, rows.first.locator("span").last.inner_text())
                    for index in range(rows.count()):
                        measured = rows.nth(index).evaluate(MEASURE_ROW)
                        self.assertEqual([], measured["cut"], f"{label} row {index}: a part is cut")
                        self.assertEqual([], measured["outside"], f"{label} row {index}: a part leaves the row")
                        self.assertEqual([], measured["titled"], f"{label} row {index}: the full text needs no title")
                        self.assertLessEqual(measured["panelScroll"][0], measured["panelScroll"][1], f"{label}: the panel scrolls horizontally")
                    run.screenshot(page, f"panel-long-design-track-{label}")
            run.effect("the card cuts a long design state with an ellipsis and a title; the panel shows track and state whole at desktop and phone widths")
            self.assertEqual([], self.page_errors)

    def test_scenario_l_a_released_feature_keeps_a_retired_app_with_its_stage(self) -> None:
        with self.scenario("L-released-feature-retired-app") as run:
            page = self.page
            self.start_trace()
            with two_app_workspace("released-worker-retired") as root:
                address = self.export(root, "released-worker-retired")
            page.goto(address)
            board = BoardPage(page, address)
            board.open_board()
            card = board.card_in("released", "F-001")
            expect(card).to_have_count(1)
            stages = card.locator("[data-app-stages] .app-stage")
            expect(stages).to_have_count(2)
            self.assertEqual(["backend·released", "worker·released·retired"], squeezed(stages.all_inner_texts()))
            card.locator(".ctitle").click()
            panel_stages = page.locator("#panel [data-panel-app-stages] .app-stage")
            expect(panel_stages).to_have_count(2)
            self.assertEqual(["backend·released", "worker·released·retired"], squeezed(panel_stages.all_inner_texts()))
            run.screenshot(page, "released-feature-retired-app-panel")
            page.locator('.views button[data-view="app"]').click()
            expect(page.locator("#app-view")).to_have_css("opacity", "1")
            lane = page.locator("#app-view .lane").filter(has=page.locator('[data-app-operations="worker"]'))
            expect(lane).to_contain_text("(retired)")
            expect(lane.locator('.fchip[data-id="F-001"]')).to_contain_text("released · retired")
            expect(lane.locator('[data-app-operations="worker"]')).to_contain_text("F-001")
            run.screenshot(page, "released-feature-retired-app-lane")
            run.effect("a released feature lists worker as `released · retired` on the card, in the panel and on worker's lane")
            self.assertEqual([], self.page_errors)

    def test_scenario_l_a_feature_in_qa_offers_its_return_requests(self) -> None:
        with self.scenario("L-qa-returns") as run:
            page = self.page
            self.start_trace()
            with two_app_workspace("in-qa") as root:
                address = self.export(root, "in-qa")
            page.goto(address)
            board = BoardPage(page, address)
            board.open_board()
            card = board.card_in("in-qa", "F-001")
            expect(card).to_have_count(1)
            picker = page.get_by_role("combobox", name="Workflow action for F-001")
            options = picker.locator("option")
            labels = [text.strip() for text in options.all_text_contents()]
            returns = [label for label in labels if label.startswith(("QA return to specification ->", "QA return to design ->"))]
            self.assertEqual(2, len(returns), labels)
            for title in ("QA return to specification", "QA return to design"):
                with self.subTest(title=title):
                    option = options.filter(has_text=f"{title} ->")
                    picker.select_option(value=option.get_attribute("value"))
                    prepare = card.locator("button[data-transition-id]")
                    expect(prepare).not_to_have_attribute("aria-disabled", "true")
                    prepare.click()
                    dialog = page.get_by_role("dialog", name=f"Prepare {title}")
                    expect(dialog).to_be_visible()
                    expect(dialog.get_by_role("button", name=re.compile(r"Apply|Recover"))).to_have_count(0)
                    if title.endswith("specification"):
                        run.screenshot(page, "qa-return-request")
                    page.keyboard.press("Escape")
                    expect(dialog).to_have_count(0)
            run.effect("a feature in QA opens its QA return requests; they are copy-only, with no Apply control")
            self.assertEqual([], self.page_errors)


if __name__ == "__main__":
    unittest.main()
