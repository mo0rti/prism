"""The board of the Lumen Library case: a service, the seven grants, and the steps an Agent proposes and a human approves.

`LumenBoard` is a base class without tests. Every gated step is proposed by the Agent grant and approved by the named person in
a board session (`tests/board_approval.py`); an ungated write is applied by the Agent itself. `approvals` lists each human
approval as (person, action) in the order it happened, which the acceptance test counts against CONTRACTS 10.1.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

from prism_cli.board_service import Actor, BoardError, BoardService
from prism_cli.wiki_model import read_feature_evidence
from tests import real_temp  # noqa: F401
from tests.board_approval import approve, human_with_roles
from tests.lumen_library import (
    DAY,
    FEATURE_ID,
    FEATURE_PATH,
    PEOPLE,
    create_lumen_workspace,
    split_page,
)
from tests.test_board_service import _read_revisions


class LumenBoard(unittest.TestCase):
    """The workspace of the case, served in process, with the Agent and one grant for each person."""

    def setUp(self) -> None:
        clock = Mock(wraps=type(DAY))
        clock.today.return_value = DAY
        for module in ("board_service", "board_release", "wiki_lint", "wiki_transitions"):
            started = patch(f"prism_cli.{module}.date", clock)
            started.start()
            self.addCleanup(started.stop)
        temporary = tempfile.TemporaryDirectory(prefix="prism-lumen-")
        self.addCleanup(temporary.cleanup)
        self.root = create_lumen_workspace(Path(temporary.name))
        self.service = BoardService(self.root).start()
        self.addCleanup(self.service.close)
        self.agent = self.service.authenticate(self.service.create_participant("Agent", "agent", True)["token"])
        self.people: dict[str, Actor] = {name: human_with_roles(self.service, name, roles) for name, roles in PEOPLE.items()}
        self.approvals: list[tuple[str, str]] = []
        self.operations = 0

    # -- reading ---------------------------------------------------------------------------------------------------------

    def read(self, relative: str) -> str:
        return (self.root / relative).read_text(encoding="utf-8")

    def exists(self, relative: str) -> bool:
        return (self.root / relative).exists()

    def put(self, relative: str, text: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))

    def feature(self) -> tuple[dict[str, Any], str]:
        return split_page(self.read(FEATURE_PATH))

    def evidence(self):
        return read_feature_evidence(self.feature()[1])

    # -- proposing and approving -----------------------------------------------------------------------------------------

    def next_operation(self) -> str:
        self.operations += 1
        return f"lumen-op-{self.operations:02d}"

    def propose(self, skill: str, changes: list[dict[str, str]], moves: list[dict[str, str]] | None = None) -> dict[str, Any]:
        """The Agent previews `skill`; the preview is returned whatever it classifies as."""

        return self.service.preview_skill(self.agent, skill, changes, moves, _read_revisions(self.service, self.agent, skill, changes, moves))

    def ready(self, skill: str, changes: list[dict[str, str]], moves: list[dict[str, str]] | None = None) -> dict[str, Any]:
        preview = self.propose(skill, changes, moves)
        problems = [item for item in preview["checks"] if item["status"] not in ("pass", "warning")]
        self.assertEqual("ready", preview["classification"], f"{skill}: {problems}")
        self.assertTrue(preview["applicable"], f"{skill}: {preview['blockers']}")
        return preview

    def apply_preview(self, preview: dict[str, Any], person: str | None) -> dict[str, Any]:
        """Apply a ready preview: a gated one is approved by `person` in a session, an ungated one is applied by the Agent."""

        operation = self.next_operation()
        if isinstance(preview.get("approval"), dict):
            self.assertIsNotNone(person, f"{preview['action']} is gated and needs a person")
            required = preview["approval"]["required_roles"]
            holder = self.people[person]
            self.assertTrue(set(required["all_of"]) <= set(holder.roles), f"{person} holds {sorted(holder.roles)} and {preview['action']} needs {required}")
            receipt = approve(self.service, holder, preview, operation)
            self.approvals.append((person, preview["action"]))
        else:
            receipt = self.service.apply(self.agent, preview["preview_id"], operation)
        self.assertEqual("applied", receipt["state"], f"{preview['action']}: {receipt}")
        return {**receipt, "operation_id": operation}

    def step(self, skill: str, changes: list[dict[str, str]], person: str | None = None, moves: list[dict[str, str]] | None = None) -> dict[str, Any]:
        """Propose `skill` as the Agent and apply it; returns the preview with the receipt under `receipt`."""

        preview = self.ready(skill, changes, moves)
        receipt = self.apply_preview(preview, person)
        return {**preview, "receipt": receipt}

    def direct(self, action: str, person: str) -> dict[str, Any]:
        """A human-direct action (`po-handoff`, `design-start`, `dev-start`): the person previews it and applies it in the board."""

        holder = self.people[person]
        preview = self.service.preview_transition(holder, FEATURE_ID, action, {"semantic_review_acknowledged": True})
        self.assertEqual("ready", preview["classification"], f"{action}: {[item for item in preview['checks'] if item['status'] not in ('pass', 'warning')]}")
        self.assertTrue(preview["applicable"], preview["blockers"])
        receipt = approve(self.service, holder, preview, self.next_operation())
        self.assertEqual("applied", receipt["state"], receipt)
        self.approvals.append((person, action))
        return {**preview, "receipt": receipt}

    def refused(self, skill: str, changes: list[dict[str, str]], person: str, moves: list[dict[str, str]] | None = None) -> BoardError:
        """The error of a proposal that `person` is not allowed to approve, or that the board refuses at preview."""

        try:
            preview = self.propose(skill, changes, moves)
        except BoardError as error:
            return error
        self.assertTrue(preview["applicable"], preview["blockers"])
        holder = self.people[person]
        review = self.service.get_preview(holder, preview["preview_id"])["approval"]["review_revision"]
        with self.assertRaises(BoardError) as caught:
            self.service.apply(holder, preview["preview_id"], self.next_operation(), review, True)
        return caught.exception

    def apply_proposal(self, proposal) -> dict[str, Any]:
        """Take one proposal through the board: the refusal the contract names first, then the approval."""

        if proposal.refused is not None:
            person, code = proposal.refused
            error = self.refused(proposal.skill, proposal.changes, person, proposal.moves)
            self.assertEqual(code, error.code, f"{proposal.label}: {person} must be refused")
        if proposal.direct is not None:
            return self.direct(proposal.direct, proposal.person)
        return self.step(proposal.skill, proposal.changes, proposal.person, proposal.moves)
