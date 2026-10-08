"""Scenarios G, H and I: more than one person, a revoked grant, and recovery of an agent's operation.

G signs two different humans in, in two browser profiles, and checks that both
see the same state after one of them applies. H revokes the signed-in human's
grant and checks that the next action fails without writing. I leaves an
operation interrupted by an agent whose grant was then revoked and has a human
inspect, acknowledge and recover it, with both actors kept on the record.
"""

from __future__ import annotations

import re
import unittest

import yaml

from prism_cli.board_service import BoardError
from tests.browser.board_page import BoardPage, expect
from tests.browser.harness import FEATURES_BY_ID, requires_browser_e2e
from tests.browser.scenario_support import BOARD_PATH, LOG_PATH, UUID, ScenarioCase, changed_paths, workspace_tree

ACTOR_COMMENT = re.compile(r"<!-- prism:board-actor:v1 (\{[^\n]*\}) -->")


def actor_comments(log: str) -> list[dict]:
    return [yaml.safe_load(match.group(1)) for match in ACTOR_COMMENT.finditer(log)]


@requires_browser_e2e
class TwoViewerTests(ScenarioCase):
    def apply_in(self, board: BoardPage, feature, label: str, action: str, target_stage: str) -> None:
        dialog = self.open_review(board, feature, label, action)
        self.acknowledge(board, dialog)
        board.apply_button(dialog).click()
        self.wait_applied(board, dialog, feature, target_stage)
        dialog.get_by_role("button", name="Close").click()
        expect(dialog).to_have_count(0)

    def test_scenario_g_two_viewers_see_consistent_state(self) -> None:
        with self.scenario("G-two-viewers") as run:
            harness = self.harness
            feature = FEATURES_BY_ID["F-001"]
            harness.add_participant("human2", "human")
            first = self.sign_in("human")
            second_viewer = self.new_viewer("second")
            second = self.sign_in("human2", page=second_viewer.page)
            self.open_board(first)
            self.open_board(second)
            expect(first.session_bar()).to_contain_text("Browser human ·")
            expect(second.session_bar()).to_contain_text("Browser human2 ·")
            self.assertEqual(first.stages(), second.stages())
            run.effect("two different human participants are signed in, each in its own browser profile, and see the same board")

            # The second person has the same handoff open when the first person applies it.
            pending = self.open_review(second, feature, "handoff", "po-handoff")
            self.acknowledge(second, pending)
            before = workspace_tree(harness.root)
            self.apply_in(first, feature, "handoff", "po-handoff", "ready-for-design")
            after_first = workspace_tree(harness.root)
            self.assertEqual({feature.path.as_posix(), BOARD_PATH, LOG_PATH}, changed_paths(before, after_first))
            run.effect("viewer 1's po-handoff changed only the feature page, the status board and the log")

            expect(second.card("F-001")).to_have_count(1)
            expect(pending.get_by_role("alert")).to_contain_text("Feature source changed while this connected preview was open")
            expect(second.apply_button(pending)).to_be_disabled()
            expect(second.acknowledgement(pending)).to_be_disabled()
            run.screenshot(second_viewer.page, "viewer2-stale-after-viewer1-applied")
            pending.get_by_role("button", name="Close").click()
            expect(pending).to_have_count(0)
            expect(second.card_in("ready-for-design", "F-001")).to_have_count(1)
            self.assertEqual(after_first, workspace_tree(harness.root), "The second viewer's stale preview must not write.")
            run.effect("viewer 2 saw the card move without reloading; its open preview went stale and wrote nothing")

            # The second person continues from the new state.
            self.apply_in(second, feature, "design start", "design-start", "in-design")
            expect(first.card_in("in-design", "F-001")).to_have_count(1)
            expect(second.card_in("in-design", "F-001")).to_have_count(1)
            expected = {"specified": ["F-004"], "ready-for-design": ["F-002"], "in-design": ["F-001"], "ready-for-dev": ["F-003"]}
            for board in (first, second):
                stages = {stage: ids for stage, ids in board.stages().items() if ids}
                self.assertEqual(expected, stages)
            run.screenshot(self.page, "viewer1-final")
            run.screenshot(second_viewer.page, "viewer2-final")
            run.effect("both viewers show F-001 in `in-design` after viewer 2's design-start, with identical columns")

            log = harness.read(LOG_PATH)
            comments = actor_comments(log)
            self.assertEqual([("po-handoff", "Browser human"), ("design-start", "Browser human2")], [(item["action"], item["name"]) for item in comments])
            self.assertEqual([harness.actor("human").participant_id, harness.actor("human2").participant_id], [item["participant_id"] for item in comments])
            for label, action in (("human", "po-handoff"), ("human2", "design-start")):
                actor = harness.actor(label)
                receipts = [event["event"]["receipt"] for event in harness.service.changes(actor)["changes"] if event["event"]["type"] == "operation-applied"]
                mine = [receipt for receipt in receipts if receipt["action"] == action]
                self.assertEqual(1, len(mine))
                self.assertEqual(actor.participant_id, mine[0]["actor"]["participant_id"])
            run.effect("the log holds one actor comment per apply, and each receipt names the participant who applied")
            self.assertEqual([], self.page_errors)


@requires_browser_e2e
class RevocationTests(ScenarioCase):
    def prepare(self):
        harness = self.harness
        harness.add_participant("auditor", "human")  # a second human, to read the journal after the first is revoked
        harness.add_participant("replacement", "human")
        board = self.sign_in("human")
        self.open_board(board)
        return board, workspace_tree(harness.root)

    def test_scenario_h_revoked_grant_fails_cleanly_and_writes_nothing(self) -> None:
        with self.scenario("H-revocation") as run:
            page = self.page
            harness = self.harness
            feature = FEATURES_BY_ID["F-001"]
            board, before = self.prepare()
            dialog = self.open_review(board, feature, "handoff", "po-handoff")
            self.acknowledge(board, dialog)
            expect(board.apply_button(dialog)).to_be_enabled()

            harness.revoke("human")
            with page.expect_response(lambda response: response.url.endswith("/api/board/v1/apply")) as sent:
                board.apply_button(dialog).click()
            self.assertEqual(401, sent.value.status)
            self.assertEqual("unauthorized", sent.value.json()["error"]["code"])
            expect(board.apply_button(dialog)).to_be_disabled()
            run.screenshot(page, "apply-after-revocation")
            self.assertEqual(before, workspace_tree(harness.root), "A revoked grant must not write.")
            self.journal_is_empty("auditor")
            run.effect("Apply after revocation was refused with HTTP 401 `unauthorized`: the tree is byte-identical and the journal holds no operation")

            # The session is over: the header offers to reconnect once the dialog is closed.
            dialog.get_by_role("button", name="Close").click()
            expect(dialog).to_have_count(0)
            expect(board.session_bar()).to_contain_text("Board session expired")
            self.assertEqual([], [cookie for cookie in self.context.cookies() if cookie["name"].startswith("prism_board_") and cookie["value"]])
            run.effect("the board shows `Board session expired` with a Reconnect button and the session cookie was cleared")

            # Reconnecting asks for a token; the revoked token is refused with a clear message.
            page.get_by_role("button", name="Reconnect").click()
            expect(page.get_by_role("heading", name="Connect to your Prism board")).to_be_visible()
            with self.untraced(run, self.context):  # tokens are typed here, so nothing records
                page.get_by_label("Participant token").fill(harness.token("human"))
                page.get_by_role("button", name="Connect").click()
                expect(page.get_by_role("status")).to_contain_text("The Prism participant token is invalid or revoked.")
                expect(page.get_by_role("heading", name="Connect to your Prism board")).to_be_visible()
                run.effect("signing in again with the revoked token is refused with `The Prism participant token is invalid or revoked.`")
                # A replacement grant works and shows the unchanged workspace.
                board.sign_in(harness.token("replacement"))
            self.open_board(board)
            expect(board.card_in("specified", feature.feature_id)).to_have_count(1)
            self.assertEqual(before, workspace_tree(harness.root))
            run.effect("a new human grant signs in, the board is LIVE, and the workspace is still byte-identical")
            self.assertEqual([], self.page_errors)

    def test_scenario_h_new_action_after_revocation_explains_and_writes_nothing(self) -> None:
        with self.scenario("H-revocation-new-action") as run:
            page = self.page
            harness = self.harness
            feature = FEATURES_BY_ID["F-001"]
            board, before = self.prepare()
            harness.revoke("human")
            board.action_button(feature.feature_id, "handoff").click()
            dialog = board.dialog("po-handoff")
            expect(dialog).to_be_visible()
            expect(dialog.get_by_role("alert")).to_contain_text("The Prism participant token is invalid or revoked.")
            expect(board.apply_button(dialog)).to_be_disabled()
            run.screenshot(page, "review-after-revocation")
            dialog.get_by_role("button", name="Close").click()
            expect(board.session_bar()).to_contain_text("Board session expired")
            expect(page.get_by_role("button", name="Reconnect")).to_be_visible()
            self.assertEqual(before, workspace_tree(harness.root))
            self.journal_is_empty("auditor")
            run.effect("a new review after revocation explained `The Prism participant token is invalid or revoked.`, offered Reconnect and wrote nothing")
            self.assertEqual([], self.page_errors)

    def test_scenario_h_defect_apply_after_revocation_hides_the_reason(self) -> None:
        """Confirming after a revocation says why it failed and offers Reconnect.

        The apply is refused with 401, so no operation exists: the dialog shows
        the session-expired message with a Reconnect action, and offers no
        Inspect or Recover for an operation that was never created.
        """

        with self.scenario("H-defect-revocation-reason-hidden"):
            page = self.page
            feature = FEATURES_BY_ID["F-001"]
            board, _before = self.prepare()
            dialog = self.open_review(board, feature, "handoff", "po-handoff")
            self.acknowledge(board, dialog)
            self.harness.revoke("human")
            board.apply_button(dialog).click()
            expect(board.apply_button(dialog)).to_be_disabled()
            expect(dialog.get_by_role("alert")).to_contain_text(re.compile(r"revoked|expired|sign in", re.IGNORECASE), timeout=3000)
            expect(dialog.get_by_role("button", name="Inspect operation")).to_have_count(0)
            expect(dialog.get_by_role("button", name="Recover recorded operation")).to_have_count(0)
            expect(dialog.get_by_text("Operation ID")).to_have_count(0)
            expect(dialog.get_by_role("button", name="Reconnect")).to_be_visible()
            expect(board.session_bar()).to_contain_text("Board session expired")


@requires_browser_e2e
class RecoveryTests(ScenarioCase):
    def test_scenario_i_human_recovers_a_revoked_agents_operation(self) -> None:
        with self.scenario("I-recovery") as run:
            page = self.page
            harness = self.harness
            feature = FEATURES_BY_ID["F-002"]
            operation_id = "agent-interrupted-operation"
            clean = workspace_tree(harness.root)
            preview = self.seed_interrupted_agent_operation(feature, operation_id)
            interrupted = workspace_tree(harness.root)
            self.assertEqual({feature.path.as_posix()}, changed_paths(clean, interrupted))
            self.assertIn("status: in-design", harness.read(feature.path))
            self.assertNotIn("in-design", harness.read(BOARD_PATH).split(f"| {feature.feature_id} |", 1)[1].split("\n", 1)[0])
            run.effect("seeded (test-only): the agent's apply was interrupted after the feature page and before the status board and log; the agent's grant is revoked")

            human = harness.actor("human")
            pending = harness.service.discover(human)["pending_operations"]
            self.assertEqual([operation_id], [item["operation_id"] for item in pending])

            board = self.sign_in("human")
            self.open_board(board)
            expect(board.operations_button()).to_be_visible()
            board.operations_button().click()
            dialog = page.get_by_role("dialog", name="Review pending operations")
            expect(dialog).to_be_visible()
            expect(dialog.get_by_text(operation_id)).to_be_visible()
            expect(dialog.get_by_role("button", name="Recover without an agent")).to_be_disabled()

            # Inspecting shows the original actor and each remaining write, and writes nothing.
            dialog.get_by_role("button", name="Inspect", exact=True).click()
            expect(dialog.get_by_text("Original actor", exact=True)).to_be_visible()
            expect(dialog).to_contain_text(f"Browser agent · agent · {harness.actor('agent').participant_id}")
            expect(dialog.get_by_text("Recorded exact file changes · 3")).to_be_visible()
            expect(dialog.get_by_text(f"{feature.path.as_posix()} · applied")).to_be_visible()
            expect(dialog.get_by_text(f"{BOARD_PATH} · pending")).to_be_visible()
            expect(dialog.get_by_text(f"{LOG_PATH} · pending")).to_be_visible()
            recover = dialog.get_by_role("button", name="Recover recorded operation")
            expect(recover).to_be_disabled()
            run.screenshot(page, "inspected")
            self.assertEqual(interrupted, workspace_tree(harness.root), "Inspecting must not write.")
            run.effect("inspect shows the revoked agent as the original actor and the three recorded writes (feature applied; status board and log pending); nothing was written")

            # Recovery needs an explicit acknowledgement.
            acknowledgement = dialog.get_by_role("checkbox", name=re.compile(r"^I inspected the original actor"))
            acknowledgement.check()
            expect(recover).to_be_enabled()
            recover.click()
            expect(dialog.get_by_text("Recovered by", exact=True)).to_be_visible()
            expect(dialog).to_contain_text(f"Browser human · human · {human.participant_id}")
            expect(dialog).to_contain_text("Dashboard view refreshed and validated")
            run.screenshot(page, "recovered")
            dialog.get_by_role("button", name="Close").click()
            expect(dialog).to_have_count(0)
            expect(board.operations_button()).to_have_count(0)

            after = workspace_tree(harness.root)
            self.assertEqual({BOARD_PATH, LOG_PATH}, changed_paths(interrupted, after))
            run.effect("recovery wrote only the missing status board row and the log entry")
            board_row = [line for line in harness.read(BOARD_PATH).splitlines() if line.startswith(f"| {feature.feature_id} ")]
            self.assertEqual([f"| {feature.feature_id} | {feature.title} | in-design | tech-lead | not-needed | \u2014 | \u2014 | \u2014 |"], board_row)
            log = harness.read(LOG_PATH)
            self.assertEqual(1, log.count(f"<!-- prism:board-history:v1 preview={preview['preview_id']} -->"))
            comments = actor_comments(log)
            self.assertEqual(1, len(comments))
            self.assertEqual(("design-start", "agent", "Browser agent", harness.actor("agent").participant_id), (comments[0]["action"], comments[0]["kind"], comments[0]["name"], comments[0]["participant_id"]))
            run.effect("the wiki log holds one history entry whose actor comment names the original agent")

            record = harness.service.operation(human, operation_id)
            receipt = record["receipt"]
            self.assertEqual("applied", record["state"])
            self.assertEqual(harness.actor("agent").participant_id, receipt["actor"]["participant_id"])
            self.assertEqual(human.participant_id, receipt["recovered_by"]["participant_id"])
            self.assertEqual(1, len(receipt["recovery_attempts"]))
            self.assertEqual(human.participant_id, receipt["recovery_attempts"][0]["actor"]["participant_id"])
            events = [event["event"] for event in harness.service.changes(human)["changes"]]
            self.assertEqual(["operation-recovery-started", "operation-applied"], [event["type"] for event in events if event["type"].startswith("operation")][-2:])
            self.assertEqual(human.participant_id, events[-2]["actor"]["participant_id"])
            self.assertEqual(harness.actor("agent").participant_id, events[-1]["receipt"]["actor"]["participant_id"])
            self.assertEqual(human.participant_id, events[-1]["receipt"]["recovered_by"]["participant_id"])
            run.effect("the receipt and the journal keep both actors: the agent as original actor, the human as the one who recovered")
            self.assertEqual([], self.page_errors)

    def test_scenario_i_defect_operations_dialog_does_not_trap_focus(self) -> None:
        """The pending-operations dialog traps Tab and Shift+Tab like the other dialogs.

        After its last control (Close) one more Tab wraps to the first control,
        and Shift+Tab from the first wraps to the last, so focus never leaves
        the dialog.
        """

        with self.scenario("I-defect-operations-dialog-focus-trap"):
            page = self.page
            self.seed_interrupted_agent_operation(FEATURES_BY_ID["F-002"], "agent-interrupted-operation")
            board = self.sign_in("human")
            self.open_board(board)
            board.operations_button().click()
            dialog = page.get_by_role("dialog", name="Review pending operations")
            expect(dialog).to_be_visible()
            dialog.get_by_role("button", name="Inspect", exact=True).click()
            expect(dialog.get_by_text("Original actor", exact=True)).to_be_visible()
            for key in ("Tab", "Shift+Tab"):
                for _ in range(16):
                    page.keyboard.press(key)
                    self.assertTrue(board.focus_description()["inDialog"], f"focus left the dialog on {key}: {board.focus_description()}")


if __name__ == "__main__":
    unittest.main()
