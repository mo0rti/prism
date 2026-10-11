"""The "Lumen Library" acceptance case (CONTRACTS 10.1): nineteen steps through the board service, then the same case with no board.

An Agent proposes each step and the named person approves it in a board session. After every step the pages, the status board
and the three read surfaces are compared with the state the contract describes. The direct-file run writes the same pages with
no board and lets lint alone check them: lint gives the same structural results and no role is enforced.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import Mock, patch

from prism_cli.board_reads import query
from prism_cli.wiki_lint import lint_wiki
from tests import real_temp  # noqa: F401
from tests.lumen_board import LumenBoard
from tests.lumen_checks import FIXTURE_ROOT, WRITE_FIXTURE_VARIABLE, LumenChecks, committed_end_state, end_state
from tests.lumen_library import DAY, FEATURE_ID, FEATURE_PATH, RELEASE_DIR, create_lumen_workspace
from tests.lumen_steps import APPROVALS, EXPECTED, HAPPY_PATH, SEQUENCE, LumenSteps
from tests.wiki_files import refresh_status_board, write_index


BOARD_NOTE = "This file is maintained by the AI agent. Do not edit directly."


class LumenAcceptanceTests(LumenBoard, LumenSteps, LumenChecks):
    def test_the_nineteen_steps_through_the_board(self) -> None:
        for number, names in SEQUENCE:
            for name in names:
                self.apply_proposal(getattr(self, name)())
            self.assert_step(number)
            self.assert_the_board_agrees(number)
        self.assert_the_human_approvals()
        self.assert_the_end_state_is_the_fixture()

    def assert_the_board_agrees(self, number: int) -> None:
        """The board's own reads (`show`, `lint` and the connected `transition-preflight`) say what the pages and the CLI say."""

        expected = EXPECTED[number]
        shown = query(self.service, self.agent, "show", FEATURE_ID)["facts"]["feature"]
        self.assertEqual(expected.status, (shown["status"], shown["owner"]), f"after step {number}: board show")
        linted = query(self.service, self.agent, "lint")["facts"]
        self.assertEqual((0, 0), (linted["error_count"], linted["warning_count"]), f"after step {number}: board lint")
        connected = query(self.service, self.agent, "transition-preflight", FEATURE_ID, expected.next_action)["facts"]["transition"]
        copied = self.cli("wiki", "transition-preflight", FEATURE_ID, str(self.root), "--action", expected.next_action, "--json")["facts"]["transition"]
        keys = ("action", "source_status", "source_owner", "target_status", "target_owner")
        self.assertEqual({key: copied[key] for key in keys}, {key: connected[key] for key in keys}, f"after step {number}: preflight")

    def assert_the_human_approvals(self) -> None:
        """CONTRACTS 10.1 counts seven confirmations on a happy path with distinct people: po-specify, po-handoff, tech-design-done,
        design-handoff, dev-done for both apps, qa-pass with its rows and release-done. The apps are delivered separately here,
        which makes eight, and neither optional pickup (design-start, dev-start) is taken. The routes of the case add the rest."""

        self.assertEqual(APPROVALS, self.approvals)
        self.assertEqual(25, len(self.approvals))
        remaining = Counter(action for _person, action in self.approvals)
        for action in HAPPY_PATH:
            self.assertGreater(remaining[action], 0, action)
            remaining[action] -= 1
        self.assertEqual(8, len(HAPPY_PATH))
        self.assertEqual(0, remaining["design-start"] + remaining["dev-start"])
        self.assertEqual({"Pat", "Dana", "Theo", "Devi", "Quinn", "Remy"}, {person for person, _action in self.approvals})

    def assert_the_end_state_is_the_fixture(self) -> None:
        """The pages the case ends with are `tests/fixtures/lumen_library`. After a change of the case or of the pages the board
        writes, rewrite the fixture with `PRISM_WRITE_LUMEN_FIXTURE=1` and review the diff."""

        if os.environ.get(WRITE_FIXTURE_VARIABLE) == "1":
            shutil.rmtree(FIXTURE_ROOT, ignore_errors=True)
            for relative, text in end_state(self.root).items():
                target = FIXTURE_ROOT / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(text.encode("utf-8"))
        self.assertEqual(committed_end_state(), end_state(self.root))


class LumenDirectFileTests(unittest.TestCase, LumenSteps, LumenChecks):
    """The same case written straight into the files: lint checks the structure and no role is enforced."""

    def setUp(self) -> None:
        clock = Mock(wraps=type(DAY))
        clock.today.return_value = DAY
        for module in ("wiki_lint", "wiki_transitions"):
            started = patch(f"prism_cli.{module}.date", clock)
            started.start()
            self.addCleanup(started.stop)
        temporary = tempfile.TemporaryDirectory(prefix="prism-lumen-")
        self.addCleanup(temporary.cleanup)
        self.root = create_lumen_workspace(Path(temporary.name))

    def read(self, relative: str) -> str:
        return (self.root / relative).read_text(encoding="utf-8")

    def put(self, relative: str, text: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))

    def exists(self, relative: str) -> bool:
        return (self.root / relative).exists()

    def write(self, proposal) -> None:
        """What a person does with no board: write the pages, move the intake folder, then keep the index and the status board."""

        for item in proposal.changes:
            self.put(item["path"], item["content"].replace("operation: pending", "operation: direct-file"))
        for move in proposal.moves or []:
            source = self.root / move["source"]
            destination = self.root / move["destination"]
            for path in sorted(source.rglob("*")):
                if path.is_file():
                    target = destination / path.relative_to(source)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(path, target)
            shutil.rmtree(source)
        self.refresh_views()

    def refresh_views(self) -> None:
        """Rewrite the index and the status board from the pages, keeping the note the template puts at the top of the board."""

        write_index(self.root)
        refresh_status_board(self.root)
        board = self.root / "knowledge" / "wiki" / "status-board.md"
        text = board.read_text(encoding="utf-8")
        if BOARD_NOTE not in text:
            board.write_text(text.replace("# Feature Status Board\n\n", f"# Feature Status Board\n\n{BOARD_NOTE}\n\n", 1), encoding="utf-8", newline="")

    def lint_codes(self, root: Path) -> set[str]:
        return {item.code for item in lint_wiki(root).diagnostics if item.severity == "error"}

    def test_the_nineteen_steps_written_straight_into_the_files(self) -> None:
        self.refresh_views()
        for number, names in SEQUENCE:
            for name in names:
                # No board refuses a developer who verifies a fix of their own (steps 13 and 14): the pages are the same and lint raises nothing.
                self.write(getattr(self, name)())
            self.assert_step(number)
        self.assertEqual(set(), self.lint_codes(self.root))
        # The board and the files end in the same pages; only the operation that a record names differs.
        direct = {path: text.replace("operation: direct-file", "operation: lumen-op") for path, text in end_state(self.root).items()}
        committed = {path: re.sub(r"(?m)^operation: lumen-op-\d+$", "operation: lumen-op", text) for path, text in committed_end_state().items()}
        self.assertEqual(committed, direct)
        self.assert_lint_finds_what_is_structurally_wrong()

    def assert_lint_finds_what_is_structurally_wrong(self) -> None:
        """Lint, and nothing else, notices a page that no longer fits the others."""

        def broken(mutate) -> set[str]:
            copy = Path(tempfile.mkdtemp(prefix="prism-lumen-copy-"))
            self.addCleanup(shutil.rmtree, copy, True)
            shutil.copytree(self.root, copy / "workspace")
            mutate(copy / "workspace")
            return self.lint_codes(copy / "workspace")

        def without_record(root: Path) -> None:
            (root / RELEASE_DIR / "REL-003.md").unlink()

        def wrong_contract_citation(root: Path) -> None:
            page = root / FEATURE_PATH
            page.write_text(re.sub(r"F-001@v1:c1:[0-9a-f]{64}", "F-001@v1:c1:" + "0" * 64, page.read_text(encoding="utf-8"), count=1), encoding="utf-8")

        def lowered_status(root: Path) -> None:
            page = root / FEATURE_PATH
            page.write_text(page.read_text(encoding="utf-8").replace("status: released", "status: in-qa", 1).replace("owner: none", "owner: qa", 1), encoding="utf-8")

        def dropped_tracks(root: Path) -> None:
            page = root / FEATURE_PATH
            text = page.read_text(encoding="utf-8")
            page.write_text(re.sub(r"(?m)^design-tracks:\n(?:  .*\n)+", "", text), encoding="utf-8")

        self.assertIn("release-row-record-mismatch", broken(without_record))
        self.assertIn("stale-delivery-evidence", broken(wrong_contract_citation))
        self.assertIn("feature-status-not-minimum", broken(lowered_status))
        self.assertIn("design-tracks-invalid", broken(dropped_tracks))


if __name__ == "__main__":
    unittest.main()
