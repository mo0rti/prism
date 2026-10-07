"""Shared steps for the browser scenarios beyond A and B.

``ScenarioCase`` adds what the later scenarios repeat: signing in and tracing,
opening a review dialog, waiting for a service preview, and proving a
byte-identical workspace. Nothing here weakens a check; it only names steps.
"""

from __future__ import annotations

from contextlib import contextmanager
import functools
import hashlib
from pathlib import Path
import re
import time
from typing import Any, Callable, Iterator
import unittest
from unittest.mock import patch

from tests.browser.agent_client import AgentClient
from tests.browser.board_page import BoardPage, expect
from tests.browser.harness import STEP_TIMEOUT_MS, BrowserCase, FixtureFeature

BOARD_PATH = "knowledge/wiki/status-board.md"
LOG_PATH = "knowledge/wiki/log.md"
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
# The journal is the board service's own state. Previews legitimately add rows
# to it, so the "nothing is written" comparison covers every other workspace file.
JOURNAL_DIRECTORY = (".prism", "state")


def workspace_tree(root: Path) -> dict[str, str]:
    """Every file under the workspace root (and every directory) mapped to its content digest.

    Excludes only the board journal under ``.prism/state``. Directories are
    included so a created or removed empty folder counts as a change.
    """

    tree: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if relative.parts[: len(JOURNAL_DIRECTORY)] == JOURNAL_DIRECTORY:
            continue
        if path.is_dir():
            tree[relative.as_posix() + "/"] = "dir"
        elif path.is_file():
            tree[relative.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return tree


class DefectObserved(AssertionError):
    """The product showed the documented defect (as opposed to a test or setup problem)."""


@contextmanager
def defect_observed() -> Iterator[None]:
    """Wrap the assertions that state the correct behavior; their failure *is* the defect."""

    try:
        yield
    except AssertionError as exc:
        raise DefectObserved(str(exc)) from exc


def known_defect(test: Callable[[Any], None]) -> Callable[[Any], None]:
    """Mark a test as an expected failure caused only by the defect it documents.

    Plain ``unittest.expectedFailure`` also hides a broken setup. Here only a
    ``DefectObserved`` counts as the expected failure. Any other exception is
    re-raised from a cleanup, which unittest reports as a real error, and the
    test body then ends normally (an "unexpected success"), so the problem
    cannot pass unnoticed.
    """

    @functools.wraps(test)
    def wrapper(self: Any) -> None:
        try:
            test(self)
        except DefectObserved:
            raise
        except BaseException as exc:
            def rethrow(exc: BaseException = exc) -> None:
                raise exc

            self.addCleanup(rethrow)

    return unittest.expectedFailure(wrapper)


class SimulatedCrash(BaseException):
    """Stands in for a process that dies part-way through an apply."""


def changed_paths(before: dict[str, str], after: dict[str, str]) -> set[str]:
    return {path for path in before.keys() | after.keys() if before.get(path) != after.get(path)}


class ScenarioCase(BrowserCase):
    """A browser case with the signed-in board steps the scenarios share."""

    def sign_in(self, label: str = "human", *, page: Any = None, trace: bool = True) -> BoardPage:
        """Sign in with a participant token the way a person would, then start tracing."""

        target = page if page is not None else self.page
        board = BoardPage(target, self.harness.url)
        board.sign_in(self.harness.token(label))
        if trace:
            context = target.context
            self.start_trace(context if context is not self.context else None)
        # Remember this session's cookie and CSRF token for redaction right away.
        self.session_secrets()
        return board

    def open_board(self, board: BoardPage) -> None:
        """Open the Board tab and wait until the page reports LIVE: actions are refused while it is refreshing."""

        board.open_board()
        expect(board.freshness()).to_have_text("LIVE")

    @contextmanager
    def untraced(self, run: Any, context: Any) -> Iterator[None]:
        """Run a block with tracing fully stopped, so a token typed into the sign-in form is never recorded.

        The recording so far is saved as its own trace file (a paused chunk still
        records network traffic, so tracing stops completely) and a new
        recording starts when the block ends.
        """

        parts = len(list(run.directory.glob("trace-part*.zip"))) + 1
        context.tracing.stop(path=str(run.directory / f"trace-part{parts}.zip"))
        try:
            yield
        finally:
            context.tracing.start(screenshots=True, snapshots=True, sources=False)
            self.session_secrets()

    def sign_in_again(self, run: Any, board: BoardPage, label: str = "human") -> None:
        """Sign in again in a traced context without the token ever entering a trace."""

        with self.untraced(run, board.page.context):
            board.sign_in(self.harness.token(label))

    def open_review(self, board: BoardPage, feature: FixtureFeature, action_label: str, action: str, *, expect_ready: bool = True) -> Any:
        """Click the card's review button and wait for the service preview to render."""

        # A person waits for LIVE before previewing: while the board is refreshing it refuses to preview.
        expect(board.freshness()).to_have_text("LIVE")
        board.action_button(feature.feature_id, action_label).click()
        dialog = board.dialog(action)
        expect(dialog).to_be_visible()
        expect(dialog.get_by_role("heading", name=re.compile(r"^Exact file changes"))).to_be_visible()
        return dialog

    def acknowledge(self, board: BoardPage, dialog: Any) -> None:
        """Check the review acknowledgement and wait for the re-requested preview to be applicable."""

        acknowledgement = board.acknowledgement(dialog)
        acknowledgement.check()
        expect(acknowledgement).to_be_checked()
        expect(dialog).to_contain_text("ready · applicable")

    def seed_interrupted_agent_operation(self, feature: FixtureFeature, operation_id: str) -> dict[str, Any]:
        """Leave a pending operation from an agent whose grant is then revoked (test-only setup).

        The agent proposes ``design-start`` through the real MCP client. Its apply
        is interrupted in the service after the feature page is written and
        before the status board and log, exactly as a crash would leave it, then the
        agent's grant is revoked. Nothing in the product is changed or hooked:
        the interruption patches one method of the in-process service for the
        duration of one call.
        """

        harness = self.harness
        service = harness.service
        path = feature.path.as_posix()
        with AgentClient(harness.url, harness.token("agent")) as agent:
            preview = agent.propose("design-start", path, lambda text: text.replace("status: ready-for-design\n", "status: in-design\n", 1))
        self.assertTrue(preview["applicable"], preview)
        original = service._apply_write

        def interrupted(write: Any, **kwargs: Any) -> Any:
            if write["role"] == "status-board":
                raise SimulatedCrash()
            return original(write, **kwargs)

        with patch.object(service, "_apply_write", side_effect=interrupted):
            with self.assertRaises(SimulatedCrash):
                service.apply(harness.actor("agent"), preview["preview_id"], operation_id)
        harness.revoke("agent")
        return preview

    def wait_until_current(self, board: BoardPage) -> None:
        """Wait until the board has adopted the newest snapshot the server holds, so no live update re-renders it mid-test.

        A live update re-renders an open dialog and moves focus to its heading,
        which a keyboard walk would otherwise hit at a random step.
        """

        board.wait_until_current(STEP_TIMEOUT_MS / 1000)

    def wait_applied(self, board: BoardPage, dialog: Any, feature: FixtureFeature, target_stage: str) -> None:
        """Wait until the dialog reports the operation as applied and the board shows the card in its new column.

        These two facts are what a person relies on. The dialog's alert text
        ("Dashboard view refreshed and validated") is not used here: it changes
        as the refresh settles, so only the scenarios that control that
        ordering assert it.
        """

        expect(dialog.get_by_text("Operation ID · applied")).to_be_visible()
        expect(board.card_in(target_stage, feature.feature_id)).to_have_count(1)

    def journal_is_empty(self, label: str = "human") -> None:
        """No operation was ever submitted: the service holds no pending operation and has recorded no change event."""

        service = self.harness.service
        actor = self.harness.actor(label)
        self.assertEqual([], service.discover(actor)["pending_operations"])
        self.assertEqual([], service.changes(actor)["changes"])

    def assert_unchanged(self, run: Any, before: dict[str, str], description: str) -> None:
        after = workspace_tree(self.harness.root)
        self.assertEqual(set(), changed_paths(before, after), f"{description}: the workspace tree must be byte-identical")
        run.effect(f"{description}: workspace tree is byte-identical (every file under the workspace except the board journal)")
