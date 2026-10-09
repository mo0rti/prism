"""Scenarios A and B: apply human workflow actions through the real board UI.

Scenario A drives ``po-handoff`` with the mouse. Scenario B drives the same
action by keyboard, compares it with a pointer-driven twin feature, and runs
``design-start`` and ``dev-start`` by keyboard. Each scenario checks the files
on disk, the journal receipt, and writes a trace, screenshot and summary.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any
import unittest

import yaml

from prism_cli.wiki_model import NO_UI_TRACK_REASON, DesignTracks
from prism_cli.wiki_operations import design_tracks_text
from tests.browser.board_page import REVIEWED_TEXT, BoardPage, expect
from tests.browser.harness import FEATURES_BY_ID, BrowserCase, FixtureFeature, requires_browser_e2e
from tests.test_core_workflow_fixture import CHECK_DATE

BOARD_PATH = "knowledge/wiki/status-board.md"
LOG_PATH = "knowledge/wiki/log.md"
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)

# action -> (card button label, source stage, target stage, target owner)
ACTIONS = {
    "po-handoff": ("handoff", "specified", "ready-for-design", "tech-lead"),
    "design-start": ("design start", "ready-for-design", "in-design", "tech-lead"),
    "dev-start": ("development start", "ready-for-dev", "in-dev", "dev"),
}


def snapshot(root) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in (root / "knowledge").rglob("*") if path.is_file()}


def split_page(text: str) -> tuple[dict[str, Any], str]:
    match = FRONTMATTER.match(text)
    assert match is not None, "feature page has no frontmatter"
    return yaml.safe_load(match.group(1)), match.group(2)


@dataclass
class Applied:
    feature: FixtureFeature
    action: str
    previewed: dict[str, dict[str, str]]
    operation_id: str
    before: dict[str, bytes]
    after: dict[str, bytes]


@requires_browser_e2e
class ApplyScenarioTests(BrowserCase):
    # -- shared flows -----------------------------------------------------------

    @staticmethod
    def mask_ids(previewed: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
        """Each preview gets a fresh ID that appears in its log text; mask it to compare previews."""

        return {path: {key: UUID.sub("<id>", text) for key, text in texts.items()} for path, texts in previewed.items()}

    def preview_paths(self, feature: FixtureFeature) -> list[str]:
        return [feature.path.as_posix(), BOARD_PATH, LOG_PATH]

    def sign_in_and_trace(self, board: BoardPage) -> None:
        board.sign_in(self.harness.token("human"))
        # Tracing starts after sign-in so the trace never records the token.
        self.start_trace()

    def wait_for_preview(self, board: BoardPage, dialog, feature: FixtureFeature) -> dict[str, dict[str, str]]:
        expect(dialog.get_by_role("heading", name=re.compile(r"^Exact file changes"))).to_be_visible()
        return board.read_writes(dialog, self.preview_paths(feature))

    def pointer_apply(self, board: BoardPage, feature: FixtureFeature, action: str, *, hold_refresh: bool = True) -> Applied:
        """Drag, review, acknowledge and apply with the mouse, checking each gate.

        With ``hold_refresh`` the board's refresh is held to observe the order
        "applied, then refreshed, then moved". Without it the apply runs
        unobserved, and the card must already be in its new column at the moment
        the success message is shown.
        """

        harness = self.harness
        label, source_stage, target_stage, _owner = ACTIONS[action]
        # An earlier apply can still be publishing snapshots; a live update during the drag would cancel it.
        board.wait_until_current()
        before = snapshot(harness.root)
        expect(board.card_in(source_stage, feature.feature_id)).to_be_visible()

        board.drag_card_to_stage(feature.feature_id, feature.title, target_stage)
        dialog = board.dialog(action)
        expect(dialog).to_be_visible()
        first_preview = self.wait_for_preview(board, dialog, feature)

        # The preview shows exact before and after text and writes nothing.
        for path, texts in first_preview.items():
            self.assertEqual(before[path].decode("utf-8"), texts["before"], path)
        self.assertEqual(before, snapshot(harness.root), "Previewing must not write files.")
        # The disclosed frontmatter reserialization notice is visible.
        expect(dialog.get_by_role("note")).to_contain_text("rewrites the full YAML frontmatter")
        # The card has not moved merely because a preview opened.
        expect(board.card_in(source_stage, feature.feature_id)).to_have_count(1)

        # Apply is disabled until the acknowledgement is checked.
        apply = board.apply_button(dialog)
        acknowledgement = board.acknowledgement(dialog)
        expect(acknowledgement).not_to_be_checked()
        expect(apply).to_be_disabled()
        acknowledgement.check()
        expect(acknowledgement).to_be_checked()
        expect(apply).to_be_enabled()
        expect(dialog).to_contain_text("ready · applicable")
        # Acknowledging re-requests the preview; it must describe the same writes.
        final_preview = self.wait_for_preview(board, dialog, feature)
        self.assertEqual(self.mask_ids(first_preview), self.mask_ids(final_preview))

        if hold_refresh:
            # Hold the board's refresh so the order "applied, then refreshed, then moved" is observable.
            board.install_graph_gate()
            board.hold_graph_refreshes()
            apply.click()
            operation_id = board.operation_id(dialog)
            board.wait_for_held_refresh()
            expect(dialog.get_by_role("alert")).to_contain_text("Refreshing and validating the dashboard view")
            after = snapshot(harness.root)
            self.assertNotEqual(before, after, "The apply must already be on disk while the refresh is pending.")
            # The card has not moved: the board only moves it after the refresh that follows the apply.
            expect(board.card_in(source_stage, feature.feature_id)).to_have_count(1)
            expect(board.card_in(target_stage, feature.feature_id)).to_have_count(0)

            board.release_graph_refreshes()
            expect(board.card_in(target_stage, feature.feature_id)).to_have_count(1)
            expect(board.card_in(source_stage, feature.feature_id)).to_have_count(0)
            expect(dialog.get_by_role("alert")).to_contain_text("Dashboard view refreshed and validated")
        else:
            apply.click()
            operation_id = board.operation_id(dialog)
            expect(dialog.get_by_role("alert")).to_contain_text("Dashboard view refreshed and validated")
            # Read the board at once, without waiting: the snapshot the board validated
            # already included the apply, so the card moved before the message was shown.
            self.assertEqual(1, board.card_in(target_stage, feature.feature_id).count())
            self.assertEqual(0, board.card_in(source_stage, feature.feature_id).count())
            after = snapshot(harness.root)
            self.assertNotEqual(before, after)
        dialog.get_by_role("button", name="Close").click()
        expect(dialog).to_have_count(0)
        self.assertEqual(after, snapshot(harness.root), "Nothing may write after the apply completed.")
        return Applied(feature, action, final_preview, operation_id, before, after)

    def keyboard_apply(self, board: BoardPage, feature: FixtureFeature, action: str) -> Applied:
        """Open, review, acknowledge and apply using Tab, Enter, Space and Escape only."""

        harness = self.harness
        page = self.page
        label, source_stage, target_stage, _owner = ACTIONS[action]
        # A live update while the dialog is open would re-render it and move focus mid-walk.
        board.wait_until_current()
        before = snapshot(harness.root)
        expect(board.card_in(source_stage, feature.feature_id)).to_be_visible()

        board.tab_to(re.compile(rf"^Review and apply {re.escape(label)} for {feature.feature_id}$"))
        page.keyboard.press("Enter")
        dialog = board.dialog(action)
        expect(dialog).to_be_visible()
        first_preview = self.wait_for_preview(board, dialog, feature)
        for path, texts in first_preview.items():
            self.assertEqual(before[path].decode("utf-8"), texts["before"], path)
        self.assertEqual(before, snapshot(harness.root), "Previewing must not write files.")
        expect(dialog.get_by_role("note")).to_contain_text("rewrites the full YAML frontmatter")

        apply = board.apply_button(dialog)
        expect(apply).to_be_disabled()
        board.tab_to(REVIEWED_TEXT)
        page.keyboard.press("Space")
        expect(board.acknowledgement(dialog)).to_be_checked()
        expect(apply).to_be_enabled()
        expect(dialog).to_contain_text("ready · applicable")
        final_preview = self.wait_for_preview(board, dialog, feature)
        self.assertEqual(self.mask_ids(first_preview), self.mask_ids(final_preview))

        board.tab_to("Apply reviewed changes")
        page.keyboard.press("Enter")
        operation_id = board.operation_id(dialog)
        expect(board.card_in(target_stage, feature.feature_id)).to_have_count(1)
        expect(board.card_in(source_stage, feature.feature_id)).to_have_count(0)
        expect(dialog.get_by_role("alert")).to_contain_text("Dashboard view refreshed and validated")
        page.keyboard.press("Escape")
        expect(dialog).to_have_count(0)
        return Applied(feature, action, final_preview, operation_id, before, snapshot(harness.root))

    # -- disk and journal verification -----------------------------------------

    def verify_applied(self, run, applied: Applied) -> dict[str, Any]:
        """Check files, preview exactness and the journal receipt; return a normalized effect."""

        harness = self.harness
        feature, action = applied.feature, applied.action
        _label, source_stage, target_stage, target_owner = ACTIONS[action]
        feature_path = feature.path.as_posix()
        before, after = applied.before, applied.after

        changed = {path for path in before.keys() | after.keys() if before.get(path) != after.get(path)}
        self.assertEqual({feature_path, BOARD_PATH, LOG_PATH}, changed)
        run.effect(f"{feature.feature_id} {action}: only the feature page, status board and log changed under knowledge/")

        for path in changed:
            self.assertEqual(before[path].decode("utf-8"), applied.previewed[path]["before"], f"{path} before")
            self.assertEqual(after[path].decode("utf-8"), applied.previewed[path]["after"], f"{path} after")
        run.effect(f"{feature.feature_id} {action}: previewed before/after text equals the bytes read from disk")

        old_meta, old_body = split_page(before[feature_path].decode("utf-8"))
        new_meta, new_body = split_page(after[feature_path].decode("utf-8"))
        expected_meta = dict(old_meta, status=target_stage, owner=target_owner)
        if action == "design-start":
            # Starting design initializes the tracks of a backend-only scope: no UI to design, the technical track pending.
            expected_meta.update(DesignTracks("not-applicable", "pending", NO_UI_TRACK_REASON, None).frontmatter())
        self.assertEqual(expected_meta, new_meta)
        self.assertEqual(list(old_meta), list(new_meta)[: len(old_meta)], "Frontmatter key order is preserved.")
        self.assertNotIn("last-updated", new_meta, "A transition writes no date into the feature page.")
        self.assertEqual(old_body, new_body, "The page body is untouched.")
        run.effect(f"{feature.feature_id} {action}: frontmatter status {source_stage} -> {target_stage}, owner {target_owner}, body unchanged")

        old_rows = before[BOARD_PATH].decode("utf-8").splitlines()
        new_rows = after[BOARD_PATH].decode("utf-8").splitlines()
        stages = "backend: in-dev" if target_stage == "in-dev" else "\u2014"
        # The design tracks cell follows the page: nothing before design starts, then `ui: <state>; technical: <state>`.
        tracks = design_tracks_text(new_meta)
        if action == "design-start":
            self.assertEqual("ui: not-applicable; technical: pending", tracks)
        expected_row = f"| {feature.feature_id} | {feature.title} | {target_stage} | {target_owner} | not-needed | {tracks} | {stages} | \u2014 |"
        self.assertEqual([expected_row], [row for row in new_rows if row.startswith(f"| {feature.feature_id} ")])
        self.assertEqual(
            [row for row in old_rows if not row.startswith(f"| {feature.feature_id} ")],
            [row for row in new_rows if not row.startswith(f"| {feature.feature_id} ")],
        )
        run.effect(f"{feature.feature_id} {action}: status board row updated, every other row unchanged")

        old_log, new_log = before[LOG_PATH].decode("utf-8"), after[LOG_PATH].decode("utf-8")
        self.assertTrue(new_log.startswith(old_log), "The log is append-only.")
        entry = new_log[len(old_log):]
        actor = harness.actor("human")
        # A gated action is recorded under its approving human: their roles on the `by:` line, both IDs in the actor comment.
        roles = ", ".join(actor.roles)
        match = re.fullmatch(
            r"\n?<!-- prism:board-history:v1 preview=(?P<preview>" + UUID.pattern + r") -->\n"
            rf"## {CHECK_DATE.isoformat()} board-{action} \| {feature.feature_id}\n"
            rf"- paths: {re.escape(feature_path)}, {re.escape(BOARD_PATH)}\n"
            r"- evidence: board preview (?P<evidence>" + UUID.pattern + r")\n"
            rf"- by: Browser human \(human; roles {re.escape(roles)}\)\n"
            r"<!-- prism:board-actor:v1 (?P<actor>\{[^\n]*\}) -->\n",
            entry,
        )
        self.assertIsNotNone(match, entry)
        self.assertEqual(match.group("preview"), match.group("evidence"), "The entry's evidence is the preview that produced it.")
        actor_comment = yaml.safe_load(match.group("actor"))
        self.assertEqual(
            {
                "action": action,
                "kind": "human",
                "name": "Browser human",
                "participant_id": actor.participant_id,
                "preview_id": match.group("preview"),
                "approver_id": actor.participant_id,
                "proposer_id": actor.participant_id,
                "roles": list(actor.roles),
            },
            actor_comment,
        )
        run.effect(f"{feature.feature_id} {action}: log entry appended with the human actor comment")

        record = harness.service.operation(actor, applied.operation_id)
        receipt = record["receipt"]
        self.assertEqual("applied", record["state"])
        self.assertEqual("applied", receipt["state"])
        self.assertEqual(action, receipt["action"])
        self.assertEqual(feature.feature_id, receipt["feature_id"])
        self.assertEqual(sorted(changed), sorted(receipt["applied_paths"]))
        self.assertEqual(match.group("preview"), receipt["preview_id"])
        self.assertEqual(actor.participant_id, receipt["actor"]["participant_id"])
        self.assertEqual([], receipt["moved_folders"])
        run.effect(f"{feature.feature_id} {action}: journal operation is `applied` with the expected paths and actor")

        def normal(text: str) -> str:
            return UUID.sub("<id>", text.replace(feature.feature_id, "F-XXX"))

        return {
            "feature_before": normal(applied.previewed[feature_path]["before"]),
            "feature_after": normal(applied.previewed[feature_path]["after"]),
            "status_board_row": normal(expected_row),
            "log_entry": normal(entry),
            "applied_paths": [normal(path) for path in receipt["applied_paths"]],
        }

    # -- scenarios --------------------------------------------------------------

    def test_scenario_a_po_handoff_by_pointer(self) -> None:
        with self.scenario("A-apply-by-pointer") as run:
            board = BoardPage(self.page, self.harness.url)
            self.sign_in_and_trace(board)
            board.open_board()
            applied = self.pointer_apply(board, FEATURES_BY_ID["F-001"], "po-handoff")
            self.verify_applied(run, applied)
            run.effect("F-001 po-handoff: card stayed in `specified` until the refresh after the apply, then moved to `ready-for-design`")
            # A second apply with the refresh left alone: the first snapshot the board
            # receives after the apply already shows the new stage, with no waiting.
            unobserved = self.pointer_apply(board, FEATURES_BY_ID["F-004"], "po-handoff", hold_refresh=False)
            self.verify_applied(run, unobserved)
            run.effect("F-004 po-handoff: with the refresh not held, the card was already in `ready-for-design` when the success message appeared")
            # The other features are untouched.
            for feature_id in ("F-002", "F-003"):
                feature = FEATURES_BY_ID[feature_id]
                self.assertEqual(applied.before[feature.path.as_posix()], applied.after[feature.path.as_posix()])
            self.assertEqual([], self.page_errors)

    def test_scenario_b_keyboard_parity(self) -> None:
        with self.scenario("B-keyboard-parity") as run:
            board = BoardPage(self.page, self.harness.url)
            self.sign_in_and_trace(board)
            # Reach the Board tab with the keyboard as well.
            board.tab_to(re.compile(r"^Board$"))
            self.page.keyboard.press("Enter")
            expect(board.column("specified")).to_be_visible()

            keyboard = self.keyboard_apply(board, FEATURES_BY_ID["F-001"], "po-handoff")
            keyboard_effect = self.verify_applied(run, keyboard)

            # F-004 is F-001's twin; drive it with the mouse in the same session.
            pointer = self.pointer_apply(board, FEATURES_BY_ID["F-004"], "po-handoff")
            pointer_effect = self.verify_applied(run, pointer)
            self.assertEqual(pointer_effect, keyboard_effect)
            run.effect("po-handoff: keyboard and pointer previews, file writes, log entry and receipt are equivalent")

            for feature_id, action in (("F-002", "design-start"), ("F-003", "dev-start")):
                applied = self.keyboard_apply(board, FEATURES_BY_ID[feature_id], action)
                self.verify_applied(run, applied)
            self.assertEqual([], self.page_errors)


if __name__ == "__main__":
    unittest.main()
