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

from prism_cli.wiki_graph import build_graph
from prism_cli.wiki_graph_html import render_html
from tests.board_page_fixture import two_app_workspace
from tests.browser.board_page import BoardPage, expect
from tests.browser.harness import EXTRA_FEATURES, BrowserCase, build_workspace, e2e_directory, requires_browser_e2e

IN_DESIGN = EXTRA_FEATURES["in-design"]


def squeezed(texts: list[str]) -> list[str]:
    return [re.sub(r"\s+", "", text) for text in texts]


@requires_browser_e2e
class StagesAndReturnsTests(BrowserCase):
    serve_in_process = False

    def export(self, root: Path, name: str) -> str:
        """Write the static page of the workspace `root` and return its address."""

        work = e2e_directory() / "work"
        work.mkdir(parents=True, exist_ok=True)
        parent = Path(tempfile.mkdtemp(prefix="stages-", dir=work))
        self.addCleanup(shutil.rmtree, parent, True)
        target = parent / f"{name}.html"
        target.write_text(render_html(build_graph(root)), encoding="utf-8")
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
