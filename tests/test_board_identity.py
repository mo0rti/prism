"""Roles on grants, gated approval, recovery by role and operation-repair (CONTRACTS section 1, 9 and F27).

`required_roles` is the lifecycle registry's answer; these tests patch it to gate real actions, so the board's identity
machinery is exercised on its own.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import dataclasses
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from prism_cli import board_service, wiki_transitions
from prism_cli.board_service import Actor, BoardError, BoardService
from prism_cli.board_store import BoardStore
from prism_cli.roles import RolePredicate
from prism_cli.wiki_transitions import lookup_action
from prism_cli.workflow_install import apply_install, plan_install
from tests.board_approval import give_apps_a_ui
from tests.test_board_service import _read_revisions
from tests.test_core_workflow_fixture import _feature_page, _write_index
from tests import real_temp  # noqa: F401

FEATURE = "knowledge/wiki/features/F-001-document-review.md"
BOARD = "knowledge/wiki/status-board.md"
LOG = "knowledge/wiki/log.md"
SETTINGS = "knowledge/wiki/SETTINGS.md"

# The gates the tests lay over the registry: design-start needs the designer role, po-handoff the po role.
GATES = {
    "design-start": RolePredicate(all_of=("designer",)),
    "po-handoff": RolePredicate(all_of=("po",)),
}


def fake_required_roles(action, context=None):
    return GATES.get(action)


class _Crash(BaseException):
    """A process crash that no handler in the service may swallow."""


class GatedBoardCase(unittest.TestCase):
    """An adopted workspace with F-001 ready for design, a human per role, an agent and `design-start` gated."""

    gates = True

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        apply_install(self.root, plan_install(self.root, name="Document review", apps=["backend"]))
        give_apps_a_ui(self.root)  # the design owner of a scope with a UI is the designer
        source = self.root / "knowledge/intake/processed/2026-10-06-document-review-brief/brief.md"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"# Document review\nRecord a summary and outcome.\n")
        page = (
            _feature_page()
            .replace("status: raw", "status: ready-for-design")
            .replace("owner: po", "owner: designer")
            .replace("| po | open |", "| po | resolved: Summarize key points. |")
        )
        self.put(FEATURE, page)
        _write_index(self.root, "ready-for-design", "designer")
        if self.gates:
            patcher = patch("prism_cli.roles.required_roles", side_effect=fake_required_roles)
            self.required_roles = patcher.start()
            self.addCleanup(patcher.stop)
        self.service = BoardService(self.root).start()
        self.addCleanup(self.service.close)
        self.tokens: dict[str, str] = {}
        self.designer = self.human("Dana", "designer")
        self.po = self.human("Pat", "po")
        self.dev = self.human("Devi", "dev")
        self.agent = self.agent_actor("Coding agent")

    # -- helpers -----------------------------------------------------------------

    def put(self, relative: str, content: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode("utf-8"))

    def read(self, relative: str) -> str:
        return (self.root / relative).read_bytes().decode("utf-8")

    def human(self, name: str, roles: str | None = None, *, writable: bool = True, session: bool = True) -> Actor:
        grant = self.service.create_participant(name, "human", writable, roles=roles)
        self.tokens[name] = grant["token"]
        return self.service.authenticate(grant["token"], via_session=session)

    def bearer(self, name: str) -> Actor:
        return self.service.authenticate(self.tokens[name])

    def agent_actor(self, name: str) -> Actor:
        grant = self.service.create_participant(name, "agent", True)
        self.tokens[name] = grant["token"]
        return self.service.authenticate(grant["token"])

    def agent_proposal(self, agent: Actor | None = None):
        agent = agent or self.agent
        content = self.read(FEATURE).replace("status: ready-for-design", "status: in-design")
        changes = [{"path": FEATURE, "content": content}]
        revisions = _read_revisions(self.service, agent, "design-start", changes)
        preview = self.service.preview_skill(agent, "design-start", changes, read_revisions=revisions)
        self.assertTrue(preview["applicable"], preview)
        return preview

    def review(self, actor: Actor, preview: dict) -> str:
        return self.service.get_preview(actor, preview["preview_id"])["approval"]["review_revision"]

    def approve(self, actor: Actor, preview: dict, operation: str = "approve-1") -> dict:
        return self.service.apply(actor, preview["preview_id"], operation, self.review(actor, preview), True)

    def code(self, call) -> str:
        with self.assertRaises(BoardError) as raised:
            call()
        return raised.exception.code

    def crash_after_first_write(self, actor: Actor, preview: dict, operation: str) -> None:
        """Apply a preview and stop the process before the status board is written."""

        original = self.service._apply_write

        def interrupted(write, **kwargs):
            if write["role"] == "status-board":
                raise _Crash()
            return original(write, **kwargs)

        with patch.object(self.service, "_apply_write", side_effect=interrupted):
            with self.assertRaises(_Crash):
                self.service.apply(actor, preview["preview_id"], operation, self.review(actor, preview), True)


class GrantRoleTests(GatedBoardCase):
    gates = False

    def test_roles_are_stored_sorted_and_reach_the_actor_and_discovery(self) -> None:
        actor = self.human("Multi", "qa,dev", session=False)
        self.assertEqual(("dev", "qa"), actor.roles)
        self.assertFalse(actor.session)
        discovered = self.service.discover(actor)
        self.assertEqual(["dev", "qa"], discovered["participant"]["roles"])
        self.assertIs(False, discovered["participant"]["session"])
        self.assertEqual({"version": 1, "roles": ["po", "designer", "tech-lead", "dev", "qa", "release"]}, discovered["capability"]["role_model"])
        row = self.service.store.connection.execute("SELECT roles FROM grants WHERE participant_id = ?", (actor.participant_id,)).fetchone()
        self.assertEqual("dev,qa", row[0])
        self.assertEqual("", self.service.store.connection.execute("SELECT roles FROM grants WHERE participant_id = ?", (self.agent.participant_id,)).fetchone()[0])

    def test_only_the_cookie_branch_marks_an_actor_as_a_session(self) -> None:
        self.assertFalse(self.service.authenticate(self.tokens["Dana"]).session)
        self.assertTrue(self.service.authenticate(self.tokens["Dana"], via_session=True).session)

    def test_refused_roles_store_nothing(self) -> None:
        before = self.service.store.connection.execute("SELECT COUNT(*) FROM grants").fetchone()[0]
        cases = [
            ("human", True, "chief", "invalid_role"),
            ("human", True, "qa,qa", "invalid_role"),
            ("agent", True, "dev", "agent_role_forbidden"),
            ("human", False, "dev", "role_requires_write"),
        ]
        for kind, writable, roles, expected in cases:
            with self.subTest(kind=kind, writable=writable, roles=roles):
                with self.assertRaises(BoardError) as raised:
                    self.service.create_participant("Nobody", kind, writable, roles=roles)
                self.assertEqual((expected, 400), (raised.exception.code, raised.exception.status))
        self.assertEqual(before, self.service.store.connection.execute("SELECT COUNT(*) FROM grants").fetchone()[0])

    def test_an_actor_whose_roles_differ_from_the_grant_is_refused(self) -> None:
        forged = dataclasses.replace(self.designer, roles=("designer", "po"))
        for call in (lambda: self.service.discover(forged), lambda: self.service.list_proposals(forged)):
            self.assertEqual("actor_mismatch", self.code(call))
        lost = dataclasses.replace(self.designer, roles=())
        self.assertEqual("actor_mismatch", self.code(lambda: self.service.discover(lost)))

    def test_a_state_database_without_roles_is_refused(self) -> None:
        root = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(root, ignore_errors=True))
        apply_install(root, plan_install(root, name="Old state", apps=["backend"]))
        state = root / ".prism" / "state"
        state.mkdir(parents=True)
        connection = sqlite3.connect(state / "board.sqlite3")
        connection.executescript(
            "CREATE TABLE grants (participant_id TEXT PRIMARY KEY, token_hash TEXT NOT NULL UNIQUE, name TEXT NOT NULL, kind TEXT NOT NULL, "
            "writable INTEGER NOT NULL, active INTEGER NOT NULL, board_id TEXT NOT NULL, workflow_version TEXT NOT NULL, "
            "asset_digest TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, revoked_at TEXT);"
        )
        connection.close()
        with self.assertRaises(BoardError) as started:
            BoardService(root).start()
        self.assertEqual(("unsupported_board_state", 409), (started.exception.code, started.exception.status))
        with BoardService(root) as unstarted:
            with self.assertRaises(BoardError) as granted:
                unstarted.create_participant("Someone", "human", True)
        self.assertEqual("unsupported_board_state", granted.exception.code)
        with self.assertRaises(ValueError):
            BoardStore(root)


class ApprovalFlowTests(GatedBoardCase):
    def test_a_gated_preview_carries_its_predicate_proposer_and_state(self) -> None:
        preview = self.agent_proposal()
        approval = preview["approval"]
        self.assertEqual({"all_of": ["designer"], "any_of": []}, approval["required_roles"])
        self.assertEqual("awaiting-approval", approval["state"])
        self.assertEqual(self.agent.participant_id, approval["proposer"]["participant_id"])
        self.assertNotIn("review_revision", approval, "the proposing agent does not review")
        # The predicate is asked of the registry once per preview, with what the preview knows.
        context = [call.args[1] for call in self.required_roles.call_args_list if call.args[0] == "design-start"][-1]
        self.assertEqual({"action": "design-start", "feature_path": FEATURE, "apps": ["backend"], "status": "ready-for-design", "root": self.root}, context)

    def test_an_ungated_action_keeps_the_creator_flow(self) -> None:
        with patch("prism_cli.roles.required_roles", return_value=None):
            preview = self.agent_proposal()
            self.assertNotIn("approval", preview)
            receipt = self.service.apply(self.agent, preview["preview_id"], "agent-own")
        self.assertEqual("applied", receipt["state"], receipt)

    def test_the_agent_is_refused_first_and_other_participants_see_nothing(self) -> None:
        preview = self.agent_proposal()
        self.assertEqual("approval_required", self.code(lambda: self.service.apply(self.agent, preview["preview_id"], "agent-op")))
        other = self.agent_actor("Other agent")
        self.assertEqual("preview_not_found", self.code(lambda: self.service.apply(other, preview["preview_id"], "other-op")))
        self.assertEqual("preview_not_found", self.code(lambda: self.service.get_preview(other, preview["preview_id"])))

    def test_approval_over_a_token_instead_of_a_session_is_refused(self) -> None:
        preview = self.agent_proposal()
        revision = self.review(self.designer, preview)
        bearer = self.bearer("Dana")
        self.assertEqual(
            "approval_requires_board_session",
            self.code(lambda: self.service.apply(bearer, preview["preview_id"], "bearer-op", revision, True)),
        )
        self.assertEqual("approval_requires_board_session", self.code(lambda: self.service.decline_proposal(bearer, preview["preview_id"], "no")))

    def test_a_human_without_the_predicate_is_refused(self) -> None:
        preview = self.agent_proposal()
        self.assertEqual("role_required", self.code(lambda: self.service.apply(self.po, preview["preview_id"], "po-op", "x", True)))
        self.assertEqual("role_required", self.code(lambda: self.service.decline_proposal(self.po, preview["preview_id"], "no")))
        self.assertEqual("preview_not_found", self.code(lambda: self.service.get_preview(self.po, preview["preview_id"])))

    def test_the_review_and_a_literal_acknowledgement_are_required(self) -> None:
        preview = self.agent_proposal()
        revision = self.review(self.designer, preview)
        for supplied, acknowledged in [(None, True), (revision, False), (revision, "true"), (revision, 1), ("", True)]:
            with self.subTest(revision=supplied, acknowledged=acknowledged):
                self.assertEqual(
                    "approval_review_required",
                    self.code(lambda: self.service.apply(self.designer, preview["preview_id"], "op-review", supplied, acknowledged)),
                )

    def test_a_human_approves_an_agents_proposal_and_the_record_names_both(self) -> None:
        preview = self.agent_proposal()
        receipt = self.approve(self.designer, preview)
        self.assertEqual("applied", receipt["state"], receipt)
        self.assertEqual(self.designer.participant_id, receipt["actor"]["participant_id"])
        self.assertEqual(self.agent.participant_id, receipt["proposer"]["participant_id"])
        self.assertIn("status: in-design", self.read(FEATURE))
        log = self.read(LOG)
        self.assertIn("- by: Dana (human; roles designer) approving Coding agent (agent)", log)
        marker = json.loads(log.split("<!-- prism:board-actor:v1 ", 1)[1].split(" -->", 1)[0])
        self.assertEqual((self.designer.participant_id, self.agent.participant_id), (marker["approver_id"], marker["proposer_id"]))
        row = self.service.store.connection.execute("SELECT participant_id, intent_json FROM operations WHERE operation_id = 'approve-1'").fetchone()
        self.assertEqual(self.designer.participant_id, row[0], "the operation's owner is its approver")
        approval = json.loads(row[1])["approval"]
        self.assertEqual(self.designer.participant_id, approval["approver"]["participant_id"])
        self.assertEqual(self.agent.participant_id, approval["proposer"]["participant_id"])
        self.assertEqual({"all_of": ["designer"], "any_of": []}, approval["required_roles"])
        for key in ("policy_revision", "review_revision", "trusted_facts"):
            self.assertTrue(approval[key], key)
        self.assertEqual(["designer"], approval["trusted_facts"]["approver"]["roles"])
        self.assertEqual(receipt, self.service.apply(self.designer, preview["preview_id"], "approve-1", "anything", True), "a replay returns the receipt")

    def test_a_human_direct_preview_is_gated_for_its_creator_too(self) -> None:
        preview = self.service.preview_transition(self.designer, "F-001", "design-start", {"semantic_review_acknowledged": True})
        self.assertEqual("awaiting-approval", preview["approval"]["state"])
        self.assertEqual(self.designer.participant_id, preview["approval"]["proposer"]["participant_id"])
        self.assertTrue(preview["approval"]["review_revision"])
        self.assertEqual("role_required", self.code(lambda: self.service.preview_transition(self.po, "F-001", "design-start", {"semantic_review_acknowledged": True})))
        self.assertEqual("approval_requires_board_session", self.code(lambda: self.service.apply(self.bearer("Dana"), preview["preview_id"], "hd-op", "x", True)))
        receipt = self.approve(self.designer, preview, "hd-op")
        self.assertEqual("applied", receipt["state"], receipt)
        self.assertIn("- by: Dana (human; roles designer)\n", self.read(LOG))
        self.assertNotIn("approving", self.read(LOG))

    def test_a_page_that_changes_after_the_review_stales_it(self) -> None:
        preview = self.agent_proposal()
        revision = self.review(self.designer, preview)
        self.put(FEATURE, self.read(FEATURE) + "\nAn editor added a line.\n")
        self.assertEqual("stale_approval_review", self.code(lambda: self.service.apply(self.designer, preview["preview_id"], "stale-1", revision, True)))
        # A fresh read of the changed page gives a matching review, and the preview is then stale for its own sources.
        fresh = self.review(self.designer, preview)
        self.assertNotEqual(revision, fresh)
        self.assertIn(self.code(lambda: self.service.apply(self.designer, preview["preview_id"], "stale-2", fresh, True)), {"stale_preview", "stale_write"})

    def test_the_review_is_bound_to_its_reviewer(self) -> None:
        preview = self.agent_proposal()
        other = self.human("Dora", "designer")
        mine, theirs = self.review(self.designer, preview), self.review(other, preview)
        self.assertNotEqual(mine, theirs)
        self.assertEqual("stale_approval_review", self.code(lambda: self.service.apply(other, preview["preview_id"], "bound-1", mine, True)))

    def test_a_policy_change_after_the_preview_is_stale_policy_and_a_malformed_one_invalid(self) -> None:
        preview = self.agent_proposal()
        revision = self.review(self.designer, preview)
        self.put(SETTINGS, self.read(SETTINGS).replace("wiki-stale-after-days: 14", "wiki-stale-after-days: 14\nqa-separate-from-dev: true"))
        self.assertEqual("stale_policy", self.code(lambda: self.service.apply(self.designer, preview["preview_id"], "policy-1", revision, True)))
        self.put(SETTINGS, self.read(SETTINGS).replace("qa-separate-from-dev: true", "qa-separate-from-dev: maybe"))
        self.assertEqual("invalid_policy", self.code(lambda: self.service.apply(self.designer, preview["preview_id"], "policy-2", revision, True)))
        self.assertEqual("invalid_policy", self.code(lambda: self.service.get_preview(self.designer, preview["preview_id"])))
        self.assertEqual("invalid_policy", self.code(lambda: self.agent_proposal()))
        discovered = self.service.discover(self.designer)["capability"]["policy"]
        self.assertEqual({"qa_separate_from_dev": None, "revision": None, "error": "invalid_policy"}, discovered)

    def test_the_policy_revision_changes_with_the_setting(self) -> None:
        off = self.service.discover(self.designer)["capability"]["policy"]
        self.assertEqual(False, off["qa_separate_from_dev"])
        self.put(SETTINGS, self.read(SETTINGS).replace("wiki-stale-after-days: 14", "wiki-stale-after-days: 14\nqa-separate-from-dev: true"))
        on = self.service.discover(self.designer)["capability"]["policy"]
        self.assertEqual(True, on["qa_separate_from_dev"])
        self.assertNotEqual(off["revision"], on["revision"])

    def test_a_proposer_revoked_before_approval_is_proposer_revoked(self) -> None:
        preview = self.agent_proposal()
        revision = self.review(self.designer, preview)
        self.service.revoke_participant(self.agent.participant_id)
        self.assertEqual("proposer_revoked", self.code(lambda: self.service.apply(self.designer, preview["preview_id"], "revoked-1", revision, True)))

    def test_revoking_the_proposer_after_the_intent_is_recorded_changes_nothing(self) -> None:
        preview = self.agent_proposal()
        self.crash_after_first_write(self.designer, preview, "pending-1")
        self.service.revoke_participant(self.agent.participant_id)
        receipt = self.service.apply(self.designer, preview["preview_id"], "pending-1")
        self.assertEqual("applied", receipt["state"], receipt)

    def test_error_precedence_on_a_gated_apply(self) -> None:
        preview = self.agent_proposal()
        self.service.revoke_participant(self.agent.participant_id)
        bearer_po = self.bearer("Pat")
        # The session, then the role, then the revoked proposer; the agent is refused before any of them.
        self.assertEqual("approval_requires_board_session", self.code(lambda: self.service.apply(bearer_po, preview["preview_id"], "p2")))
        self.assertEqual("role_required", self.code(lambda: self.service.apply(self.po, preview["preview_id"], "p3")))
        self.assertEqual("proposer_revoked", self.code(lambda: self.service.apply(self.designer, preview["preview_id"], "p4")))

    def test_the_roles_resolve_again_at_apply(self) -> None:
        preview = self.agent_proposal()
        revision = self.review(self.designer, preview)
        with patch.dict(GATES, {"design-start": RolePredicate(all_of=("tech-lead",))}):
            self.assertEqual("stale_preview", self.code(lambda: self.service.apply(self.designer, preview["preview_id"], "roles-1", revision, True)))
        with patch.dict(GATES, {}, clear=True):
            self.assertEqual("stale_preview", self.code(lambda: self.service.apply(self.designer, preview["preview_id"], "roles-2", revision, True)))
        self.assertEqual("applied", self.service.apply(self.designer, preview["preview_id"], "roles-3", revision, True)["state"])

    def test_a_revoked_approver_is_unauthorized(self) -> None:
        preview = self.agent_proposal()
        revision = self.review(self.designer, preview)
        self.service.revoke_participant(self.designer.participant_id)
        self.assertEqual("unauthorized", self.code(lambda: self.service.apply(self.designer, preview["preview_id"], "gone-1", revision, True)))


class DeclineTests(GatedBoardCase):
    def test_a_decline_marks_the_preview_and_writes_nothing_else(self) -> None:
        preview = self.agent_proposal()
        feature, board = self.read(FEATURE), self.read(BOARD)
        result = self.service.decline_proposal(self.designer, preview["preview_id"], "Not this sprint.")
        self.assertTrue(result["declined"])
        self.assertEqual((feature, board), (self.read(FEATURE), self.read(BOARD)))
        self.assertEqual("declined", self.service.get_preview(self.designer, preview["preview_id"])["approval"]["state"])
        revision = "stale-by-design"
        self.assertEqual("proposal_declined", self.code(lambda: self.service.apply(self.designer, preview["preview_id"], "after-decline", revision, True)))
        self.assertEqual("proposal_declined", self.code(lambda: self.service.decline_proposal(self.designer, preview["preview_id"], "again")))
        self.assertNotIn(preview["preview_id"], [item["preview_id"] for item in self.service.list_proposals(self.designer)["proposals"]])
        event = [item["event"] for item in self.service.changes(self.designer)["changes"] if item["event"]["type"] == "proposal-declined"]
        self.assertEqual(1, len(event))
        self.assertEqual(preview["preview_id"], event[0]["preview_id"])
        self.assertEqual(self.designer.participant_id, event[0]["declined_by"]["participant_id"])
        self.assertEqual("Not this sprint.", event[0]["reason"])

    def test_a_reason_is_required(self) -> None:
        preview = self.agent_proposal()
        for reason in ("", "   ", None, 5):
            with self.subTest(reason=reason):
                self.assertEqual("invalid_text", self.code(lambda: self.service.decline_proposal(self.designer, preview["preview_id"], reason)))

    def test_the_agent_and_a_human_without_the_predicate_cannot_decline(self) -> None:
        preview = self.agent_proposal()
        self.assertEqual("approval_required", self.code(lambda: self.service.decline_proposal(self.agent, preview["preview_id"], "mine")))
        self.assertEqual("role_required", self.code(lambda: self.service.decline_proposal(self.po, preview["preview_id"], "no")))
        self.assertEqual("preview_not_found", self.code(lambda: self.service.decline_proposal(self.designer, "no-such-preview", "no")))

    def test_an_ungated_preview_has_nothing_to_decline(self) -> None:
        with patch("prism_cli.roles.required_roles", return_value=None):
            preview = self.agent_proposal()
        self.assertEqual("preview_not_found", self.code(lambda: self.service.decline_proposal(self.designer, preview["preview_id"], "no")))

    def test_the_first_of_two_approvers_wins(self) -> None:
        preview = self.agent_proposal()
        other = self.human("Dora", "designer")
        self.approve(self.designer, preview, "first")
        self.assertEqual(
            "preview_already_submitted",
            self.code(lambda: self.service.apply(other, preview["preview_id"], "second", "unread", True)),
        )
        self.assertEqual("preview_already_submitted", self.code(lambda: self.service.decline_proposal(other, preview["preview_id"], "late")))
        # The second approver reusing the first operation ID is not another approver's receipt.
        self.assertEqual("operation_id_reused", self.code(lambda: self.service.apply(other, preview["preview_id"], "first", "x", True)))

    def test_approve_and_decline_at_once_leave_exactly_one_winner(self) -> None:
        for _round in range(3):
            preview = self.agent_proposal()
            revision = self.review(self.designer, preview)
            start = threading.Barrier(2)
            outcomes: list[str] = []

            def approve() -> None:
                start.wait()
                try:
                    self.service.apply(self.designer, preview["preview_id"], f"race-{preview['preview_id']}", revision, True)
                    outcomes.append("approved")
                except BoardError as exc:
                    outcomes.append(exc.code)

            def decline() -> None:
                start.wait()
                try:
                    self.service.decline_proposal(self.designer, preview["preview_id"], "race")
                    outcomes.append("declined")
                except BoardError as exc:
                    outcomes.append(exc.code)

            with ThreadPoolExecutor(2) as pool:
                for future in [pool.submit(approve), pool.submit(decline)]:
                    future.result()
            self.assertEqual(1, outcomes.count("approved") + outcomes.count("declined"), outcomes)
            loser = next(item for item in outcomes if item not in {"approved", "declined"})
            self.assertEqual("preview_already_submitted" if "approved" in outcomes else "proposal_declined", loser)
            # Reset the page for the next round: the approved round moved the feature to in-design.
            self.put(FEATURE, self.read(FEATURE).replace("status: in-design", "status: ready-for-design"))
            self.put(BOARD, self.read(BOARD).replace("| in-design |", "| ready-for-design |"))
            self.service.revoke_participant(self.agent.participant_id)
            self.agent = self.agent_actor(f"Round agent {_round}")


class ProposalListTests(GatedBoardCase):
    def test_each_participant_sees_what_its_roles_allow(self) -> None:
        preview = self.agent_proposal()
        seen = {name: [item["preview_id"] for item in self.service.list_proposals(actor)["proposals"]] for name, actor in {
            "designer": self.designer, "po": self.po, "dev": self.dev, "agent": self.agent,
        }.items()}
        self.assertEqual({"designer": [preview["preview_id"]], "po": [], "dev": [], "agent": [preview["preview_id"]]}, seen)
        entry = self.service.list_proposals(self.designer)["proposals"][0]
        self.assertEqual(
            {"preview_id", "action", "item_id", "required_roles", "proposer", "created_at", "stale"},
            set(entry),
        )
        self.assertEqual(("design-start", "F-001", False), (entry["action"], entry["item_id"], entry["stale"]))
        self.assertEqual([preview["preview_id"]], [item["preview_id"] for item in self.service.discover(self.designer)["pending_proposals"]])
        self.assertEqual([], self.service.discover(self.po)["pending_proposals"])

    def test_a_multi_role_human_sees_proposals_per_predicate_and_declines_one(self) -> None:
        multi = self.human("Multi", "designer,po")
        design = self.agent_proposal()
        self.put(FEATURE, self.read(FEATURE).replace("status: in-design", "status: ready-for-design"))
        self.assertEqual([design["preview_id"]], [item["preview_id"] for item in self.service.list_proposals(multi)["proposals"]])
        self.service.decline_proposal(multi, design["preview_id"], "Duplicate of another proposal.")
        self.assertEqual([], self.service.list_proposals(multi)["proposals"])

    def test_consumed_declined_and_orphaned_proposals_leave_the_list(self) -> None:
        approved = self.agent_proposal()
        self.approve(self.designer, approved)
        self.assertEqual([], self.service.list_proposals(self.designer)["proposals"])
        self.put(FEATURE, self.read(FEATURE).replace("status: in-design", "status: ready-for-design"))
        self.put(BOARD, self.read(BOARD).replace("| in-design |", "| ready-for-design |"))
        revoked_agent = self.agent_actor("Short-lived agent")
        self.agent_proposal(revoked_agent)
        self.assertEqual(1, len(self.service.list_proposals(self.designer)["proposals"]))
        self.service.revoke_participant(revoked_agent.participant_id)
        self.assertEqual([], self.service.list_proposals(self.designer)["proposals"], "a proposer whose grant is revoked is not listed")

    def test_a_proposal_whose_page_changed_is_listed_as_stale(self) -> None:
        self.agent_proposal()
        self.put(FEATURE, self.read(FEATURE) + "\nAn editor added a line.\n")
        self.assertTrue(self.service.list_proposals(self.designer)["proposals"][0]["stale"])


class PendingRetryAndRecoveryTests(GatedBoardCase):
    def test_a_pending_retry_by_the_approver_is_not_stale_from_its_own_writes(self) -> None:
        preview = self.agent_proposal()
        self.crash_after_first_write(self.designer, preview, "pending-1")
        self.assertIn("status: in-design", self.read(FEATURE))
        with patch.object(self.service, "_revalidate_recovery", wraps=self.service._revalidate_recovery) as revalidation:
            receipt = self.service.apply(self.designer, preview["preview_id"], "pending-1")
        self.assertEqual("applied", receipt["state"], receipt)
        self.assertEqual(1, revalidation.call_count)
        self.assertIn("| in-design | designer |", self.read(BOARD))

    def test_a_pending_retry_rechecks_the_session_and_the_role(self) -> None:
        preview = self.agent_proposal()
        self.crash_after_first_write(self.designer, preview, "pending-1")
        self.assertEqual("approval_requires_board_session", self.code(lambda: self.service.apply(self.bearer("Dana"), preview["preview_id"], "pending-1")))
        self.assertEqual("approval_required", self.code(lambda: self.service.apply(self.agent, preview["preview_id"], "pending-1")))
        self.assertEqual("operation_id_reused", self.code(lambda: self.service.apply(self.human("Dora", "designer"), preview["preview_id"], "pending-1", "x", True)))
        self.assertEqual("role_required", self.code(lambda: self.service.apply(self.po, preview["preview_id"], "pending-1")))

    def test_a_pending_retry_after_a_policy_change_needs_a_renewed_review(self) -> None:
        preview = self.agent_proposal()
        self.crash_after_first_write(self.designer, preview, "pending-1")
        self.put(SETTINGS, self.read(SETTINGS).replace("wiki-stale-after-days: 14", "wiki-stale-after-days: 14\nqa-separate-from-dev: true"))
        self.assertEqual("stale_recovery_review", self.code(lambda: self.service.apply(self.designer, preview["preview_id"], "pending-1")))
        self.assertEqual("stale_recovery_review", self.code(lambda: self.service.recover(self.designer, "pending-1")))
        review = self.service.operation(self.designer, "pending-1")["recovery_review_revision"]
        self.assertEqual("stale_recovery_review", self.code(lambda: self.service.recover(self.designer, "pending-1", "wrong", True)))
        receipt = self.service.recover(self.designer, "pending-1", review, True)
        self.assertEqual("applied", receipt["state"], receipt)

    def test_another_holder_of_the_predicate_sees_and_recovers_after_the_approver_is_revoked(self) -> None:
        preview = self.agent_proposal()
        self.crash_after_first_write(self.designer, preview, "pending-1")
        self.service.revoke_participant(self.designer.participant_id)
        successor = self.human("Dora", "designer")
        self.assertIn("pending-1", [item["operation_id"] for item in self.service.discover(successor)["pending_operations"]])
        for outsider in (self.po, self.dev, self.agent):
            self.assertNotIn("pending-1", [item["operation_id"] for item in self.service.discover(outsider)["pending_operations"]])
            self.assertEqual("operation_not_found", self.code(lambda: self.service.operation(outsider, "pending-1")))
        inspected = self.service.operation(successor, "pending-1")
        self.assertEqual(self.designer.participant_id, inspected["actor"]["participant_id"])
        self.assertEqual(self.agent.participant_id, inspected["approval"]["proposer"]["participant_id"])
        self.assertEqual("recovery_review_required", self.code(lambda: self.service.recover(successor, "pending-1")))
        self.assertEqual("approval_requires_board_session", self.code(lambda: self.service.recover(self.bearer("Dora"), "pending-1", inspected["recovery_review_revision"], True)))
        receipt = self.service.recover(successor, "pending-1", inspected["recovery_review_revision"], True)
        self.assertEqual("applied", receipt["state"], receipt)
        self.assertEqual(successor.participant_id, receipt["recovered_by"]["participant_id"])
        self.assertEqual(self.designer.participant_id, receipt["actor"]["participant_id"])

    def test_the_proposing_agent_cannot_recover_its_gated_operation(self) -> None:
        preview = self.agent_proposal()
        self.crash_after_first_write(self.designer, preview, "pending-1")
        self.assertEqual("approval_required", self.code(lambda: self.service.recover(self.agent, "pending-1")))

    def test_an_operation_that_can_still_roll_forward_is_not_abandoned_by_its_successor(self) -> None:
        preview = self.agent_proposal()
        self.crash_after_first_write(self.designer, preview, "pending-1")
        self.service.revoke_participant(self.designer.participant_id)
        successor = self.human("Dora", "designer")
        review = self.service.operation(successor, "pending-1")["recovery_review_revision"]
        # A successor who sees the operation may ask to abandon it, but one that can still be rolled forward is not abandoned.
        self.assertEqual("abandon_not_needed", self.code(lambda: self.service.recover(successor, "pending-1", review, True, abandon=True)))


class ActionAvailabilityTests(GatedBoardCase):
    def test_an_action_whose_package_has_not_landed_is_refused_and_discovered_as_unavailable(self) -> None:
        # One registry answers availability: an action whose package is not enabled is unavailable everywhere.
        spec = dataclasses.replace(lookup_action("design-start"), package="D9")
        with patch.dict(wiki_transitions.ACTION_BY_ID, {"design-start": spec}), patch.object(
            board_service, "_REGISTERED_ACTION_SPECS", tuple(spec if item.action == "design-start" else item for item in board_service._REGISTERED_ACTION_SPECS)
        ):
            with self.assertRaises(BoardError) as raised:
                self.service.preview_transition(self.designer, "F-001", "design-start", {"semantic_review_acknowledged": True})
            self.assertEqual(("action_unavailable", 409), (raised.exception.code, raised.exception.status))
            self.assertEqual("action_unavailable", self.code(lambda: self.agent_proposal()))
            entry = next(item for item in self.service.discover(self.designer)["capability"]["actions"] if item["action"] == "design-start")
            self.assertEqual((False, spec.unavailable_reason, False), (entry["available"], entry["unavailable_reason"], entry["available_to_participant"]))
            self.assertIn("work package D9", entry["unavailable_reason"])

    def test_discovery_lists_each_action_with_its_roles_modes_and_who_may_take_part(self) -> None:
        actions = {item["action"]: item for item in self.service.discover(self.designer)["capability"]["actions"]}
        self.assertIn("operation-repair", actions)
        entry = actions["design-start"]
        self.assertEqual({"action", "command", "sources", "target", "required_roles", "modes", "available", "available_to_participant"}, set(entry))
        self.assertEqual({"all_of": ["designer"], "any_of": []}, entry["required_roles"])
        self.assertEqual(["HD", "AP"], entry["modes"])
        # The owner `D` is the design owner of the feature's scope; discovery names the symbol, a preview the concrete owner.
        self.assertEqual([{"status": "ready-for-design", "owner": "D"}], entry["sources"])
        self.assertTrue(entry["available_to_participant"])
        for actor, expected in ((self.po, False), (self.agent, True)):
            seen = {item["action"]: item for item in self.service.discover(actor)["capability"]["actions"]}["design-start"]
            self.assertEqual(expected, seen["available_to_participant"])
        self.assertIsNone(actions["dev-done"]["required_roles"])
        self.assertEqual(["AP"], actions["dev-done"]["modes"])

    def test_skills_report_the_roles_that_approve_them(self) -> None:
        skills = {item["name"]: item for item in self.service.list_skills(self.designer)["skills"]}
        gated = skills["design-start"]
        self.assertEqual({"all_of": ["designer"], "any_of": []}, gated["required_roles"])
        self.assertEqual({"preview_skill": ["agent"], "preview_transition": ["human"], "apply": ["human"]}, gated["write_tools"])
        self.assertIsNone(skills["dev-done"]["required_roles"])
        self.assertEqual({"preview_skill": ["agent"]}, skills["dev-done"]["write_tools"])
        self.assertIsNone(skills["verify-pages"]["required_roles"])


if __name__ == "__main__":
    unittest.main()
