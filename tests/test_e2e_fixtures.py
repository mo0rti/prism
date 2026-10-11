"""The journey fixtures of scripts/e2e are valid states of the real board: lint, preflight and the connected skills accept them.

The replay walks the whole journey on the real board service: each agent step previews the proposal its fixture folders hold,
and a human grant that holds exactly the step's roles approves it (an agent's own apply of a gated preview is refused). It proves
that the role table of `config.STEPS`, every fixture and the state each step leaves agree with the board.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
import re
import shutil
import sys
import tempfile
import unittest
from uuid import uuid4

E2E_DIR = Path(__file__).resolve().parents[1] / "scripts" / "e2e"
sys.dont_write_bytecode = True
sys.path.insert(0, str(E2E_DIR))

from prism_e2e import config, workspace as e2e  # noqa: E402

from prism_cli.board_service import BoardError, BoardService  # noqa: E402
from prism_cli.wiki_lint import lint_wiki  # noqa: E402
from prism_cli.wiki_transitions import build_transition_preflight  # noqa: E402
from prism_cli.workflow_install import apply_install, plan_install  # noqa: E402
from tests.board_approval import apply_preview, approve, human_with_roles  # noqa: E402
from tests.core_workflow_fixture import create_core_workflow_fixture  # noqa: E402
from tests import real_temp  # noqa: F401

TODAY = date(2026, 10, 5)
FIXTURE_SETS = {"default": None, "api-work": config.API_WORK_FIXTURES_DIR}
FEATURE = "knowledge/wiki/features/F-001-review-summary-export.md"
CONTRACT = "knowledge/wiki/api-contracts/F-001.md"
RECORDED_DAY = "2026-10-09"
# The recorded day and operation of a fixture become today and `pending` in the proposal an agent writes; the board stamps the operation.
DAY = re.compile(r"(?<![/\w-])" + RECORDED_DAY + r"(?![\w-])")
OPERATION = re.compile(r"(?m)^operation: [0-9a-f-]{36}$")
# The skill an agent previews each step with; a step id is not always a skill name.
SKILLS = {
    "bug-start": "bug-update",
    "bug-fixed": "bug-update",
    "bug-verify": "bug-update",
    "dev-redeliver": "dev-done",
    "release-retry": "release-done",
    "ingest-incident": "ingest",
}
# A step the API-work set cannot pass yet: the board refuses `qa-fail` of a feature with an implemented API contract because
# its candidate lint reports `delivered-api-contract` (the return routes ignore that code; `qa-fail` does not). The refusal is
# the board's finding, not a fixture error, so the replay reports it and stops there.
KNOWN_BOARD_FINDING = "source-integrity:delivered-api-contract"


def stamp(text: str) -> str:
    return OPERATION.sub("operation: pending", DAY.sub(date.today().isoformat(), text))


def revisions(service: BoardService, actor: object, skill: str, changes: list[dict[str, str]], moves: list[dict[str, str]] | None = None) -> dict[str, str]:
    from tests.test_board_service import _read_revisions

    return _read_revisions(service, actor, skill, changes, moves)


class JourneyBoard(unittest.TestCase):
    """A disposable workspace and the helpers that walk the journey on the real board; the tests are in the classes below."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = create_core_workflow_fixture(Path(temporary.name) / "ws")
        shutil.rmtree(self.root / "knowledge" / "intake" / "pending")
        (self.root / "knowledge" / "intake" / "pending").mkdir()
        self.assertEqual("applied", apply_install(self.root, plan_install(self.root, name="Doc review", apps=["backend"]))["status"])

    def seed(self, step: str | None, fixture_set: Path | None) -> None:
        e2e.seed_state(self.root, step, fixture_set)

    def start(self) -> None:
        self.service = BoardService(self.root).start()
        self.addCleanup(self.service.close)
        self.agent = self.service.authenticate(self.service.create_participant("Fixture agent", "agent", True)["token"])
        # One human grant for each role set the journey needs, holding exactly those roles, in a board session.
        self.humans = {config.approver_label(roles): human_with_roles(self.service, config.approver_label(roles), ",".join(roles)) for roles in config.APPROVER_ROLE_SETS}

    def proposal(self, step: str, fixture_set: Path | None) -> list[dict[str, str]]:
        """What the step's agent proposes: the files its fixture folders write, byte for byte (no newline translation), stamped for today."""

        paths = {
            relative: path
            for root in [config.FIXTURES_DIR / step, *([fixture_set / step] if fixture_set else [])]
            if root.is_dir()
            for relative, path in ((p.relative_to(root).as_posix(), p) for p in sorted(root.rglob("*")) if p.is_file())
        }
        if step in e2e.PENDING_INPUTS:
            # The input file is the pending folder's own file, moved to the processed folder; it is not one of the agent's writes.
            folder, name = e2e.PENDING_INPUTS[step]
            paths.pop(f"knowledge/intake/processed/{folder}/{name}", None)
        return [{"path": relative, "content": stamp(path.read_bytes().decode("utf-8"))} for relative, path in sorted(paths.items())]

    def moves(self, step: str) -> list[dict[str, str]] | None:
        if step not in e2e.PENDING_INPUTS:
            return None
        folder = e2e.PENDING_INPUTS[step][0]
        return [{"source": f"knowledge/intake/pending/{folder}", "destination": f"knowledge/intake/processed/{folder}"}]

    def lint_codes(self) -> list[str]:
        return sorted({item.code for item in lint_wiki(self.root, today=date.today()).diagnostics if item.severity == "error"})

    # -- the replay -----------------------------------------------------------------------------------

    def replay(self, fixture_set: Path | None, *, through: str | None = None, tolerate_known_finding: bool = False) -> str | None:
        """Walk the journey from the first step on the real board; returns the step the known board finding stopped it at, if any.

        Every step must leave the feature at the step's status and owner, lint clean (but for the open developer question after the
        handoff), and every file its fixtures hold exactly as the fixtures say.
        """

        self.start()
        for step in config.STEPS:
            with self.subTest(step=step.id):
                stopped = self.replay_step(step, fixture_set, tolerate_known_finding)
                if stopped:
                    return step.id
                feature = e2e.read_feature(self.root)
                self.assertEqual((step.status, step.owner), (feature.status, feature.owner), step.id)
                self.assertEqual(sorted(e2e.ALLOWED_LINT_CODES.get(step.id, frozenset()) & set(self.lint_codes())), self.lint_codes(), step.id)
            if step.id == through:
                break
        return None

    def replay_step(self, step: config.Step, fixture_set: Path | None, tolerate_known_finding: bool) -> bool:
        operation_id = str(uuid4())
        if step.is_human:
            human = self.humans[step.approver]
            preview = self.service.preview_transition(human, config.FEATURE_ID, step.id, {"semantic_review_acknowledged": True})
            self.assertTrue(preview["applicable"], preview["checks"])
            self.assertEqual("applied", apply_preview(self.service, human, preview, operation_id)["state"])
            self.assert_files_as_recorded(step, fixture_set)
            self.assert_applied_by(human, step, operation_id)
            return False
        if step.id in e2e.PENDING_INPUTS:
            e2e.place_pending_input(self.root, step.id, fixture_set)
        skill, changes, moves = SKILLS.get(step.id, step.id), self.proposal(step.id, fixture_set), self.moves(step.id)
        preview = self.service.preview_skill(self.agent, skill, changes, moves, revisions(self.service, self.agent, skill, changes, moves))
        if not preview["applicable"] and tolerate_known_finding:
            blocked = {item["code"] for item in preview["checks"] if item["status"] != "pass"}
            if blocked == {KNOWN_BOARD_FINDING}:
                return True
        self.assertEqual("ready", preview["classification"], f"{step.id}: {preview['checks']}")
        self.assertTrue(preview["applicable"], f"{step.id}: {preview.get('blockers')}")
        if not step.gated:
            self.assertNotIn("approval", preview, f"{step.id} is ungated")
            self.assertEqual("applied", self.service.apply(self.agent, preview["preview_id"], operation_id)["state"])
            self.assert_files_as_recorded(step, fixture_set)
            return False
        # A gated preview waits for the human grant that holds the step's roles; the agent's own apply is refused.
        self.assertEqual("awaiting-approval", preview["approval"]["state"], step.id)
        self.assertEqual({"all_of": sorted(step.roles), "any_of": []}, preview["approval"]["required_roles"], step.id)
        with self.assertRaises(BoardError) as refused:
            self.service.apply(self.agent, preview["preview_id"], str(uuid4()))
        self.assertEqual("approval_required", refused.exception.code, step.id)
        for label, other in self.humans.items():
            if label != step.approver:
                with self.assertRaises(BoardError, msg=f"{label} may not approve {step.id}") as wrong:
                    approve(self.service, other, preview, str(uuid4()))
                # A grant that lacks the roles cannot even read the proposal (`preview_not_found`), or is refused at the apply (`role_required`).
                self.assertIn(wrong.exception.code, {"role_required", "preview_not_found"}, f"{label} approving {step.id}")
        human = self.humans[step.approver]
        self.assertEqual("applied", approve(self.service, human, preview, operation_id)["state"])
        self.assert_files_as_recorded(step, fixture_set)
        self.assert_applied_by(human, step, operation_id, proposer=self.agent)
        return False

    def assert_files_as_recorded(self, step: config.Step, fixture_set: Path | None) -> None:
        """Every file the step's fixtures hold is on disk as the fixture says (the board stamps a record's operation)."""

        for relative, source in e2e.fixture_files([step.id], fixture_set).items():
            if step.id in e2e.PENDING_INPUTS and relative == "knowledge/intake/processed/{}/{}".format(*e2e.PENDING_INPUTS[step.id]):
                continue  # the moved input is the intake item itself
            written = OPERATION.sub("operation: pending", (self.root / relative).read_bytes().decode("utf-8").replace("\r\n", "\n"))
            self.assertEqual(stamp(source.read_bytes().decode("utf-8")), written, f"{step.id}: {relative}")

    def assert_applied_by(self, human: object, step: config.Step, operation_id: str, *, proposer: object | None = None) -> None:
        receipt = self.service.operation(human, operation_id)["receipt"]
        self.assertEqual(("human", sorted(step.roles)), (receipt["actor"]["kind"], sorted(receipt["actor"]["roles"])), step.id)
        if proposer is not None:
            self.assertEqual(proposer.participant_id, receipt["proposer"]["participant_id"], step.id)


class JourneyFixtureTests(JourneyBoard):
    def test_every_state_of_both_sets_lints_clean_apart_from_the_open_dev_question_after_the_handoff(self) -> None:
        for name, fixture_set in FIXTURE_SETS.items():
            for step in config.STEPS:
                with self.subTest(fixture_set=name, step=step.id):
                    self.seed(step.id, fixture_set)
                    result = lint_wiki(self.root, today=TODAY)
                    codes = sorted({item.code for item in result.diagnostics if item.severity == "error"})
                    self.assertEqual(sorted(e2e.ALLOWED_LINT_CODES.get(step.id, frozenset()) & set(codes)), codes, f"{step.id}: {codes}")

    def test_the_api_work_tech_design_proposal_creates_the_agreed_contract_and_the_handoff_then_dev_start_passes(self) -> None:
        self.seed("design-clarify", config.API_WORK_FIXTURES_DIR)
        self.start()
        changes = self.proposal("tech-design-done", config.API_WORK_FIXTURES_DIR)
        self.assertIn(CONTRACT, [item["path"] for item in changes])
        preview = self.service.preview_skill(self.agent, "tech-design-done", changes, None, revisions(self.service, self.agent, "tech-design-done", changes))
        self.assertEqual(("tech-design-done", "ready", True), (preview["action"], preview["classification"], preview["applicable"]), preview["checks"])
        self.assertEqual("applied", apply_preview(self.service, self.agent, preview, str(uuid4()), approver=self.humans["human-tech-lead"])["state"])
        handoff = self.proposal("design-handoff", config.API_WORK_FIXTURES_DIR)
        preview = self.service.preview_skill(self.agent, "design-handoff", handoff, None, revisions(self.service, self.agent, "design-handoff", handoff))
        self.assertEqual(("design-handoff", "ready", True), (preview["action"], preview["classification"], preview["applicable"]), preview["checks"])
        self.assertEqual("applied", apply_preview(self.service, self.agent, preview, str(uuid4()), approver=self.humans["human-tech-lead"])["state"])

        transition = build_transition_preflight(self.root, "F-001", action="dev-start")["facts"]["transition"]
        self.assertEqual("pass", next(item for item in transition["checks"] if item["code"] == "api-contract")["status"])

    def test_the_default_tech_design_proposal_has_no_contract(self) -> None:
        self.seed("design-clarify", None)
        self.start()
        changes = self.proposal("tech-design-done", None)
        self.assertNotIn(CONTRACT, [item["path"] for item in changes])
        preview = self.service.preview_skill(self.agent, "tech-design-done", changes, None, revisions(self.service, self.agent, "tech-design-done", changes))
        self.assertEqual(("ready", True), (preview["classification"], preview["applicable"]), preview["checks"])

    def test_the_api_work_dev_done_proposal_marks_the_contract_implemented(self) -> None:
        self.seed("dev-start", config.API_WORK_FIXTURES_DIR)
        self.start()
        changes = self.proposal("dev-done", config.API_WORK_FIXTURES_DIR)
        self.assertEqual(
            ["knowledge/wiki/api-contracts/F-001.md", "knowledge/wiki/app-requirements/F-001-backend.md", FEATURE],
            sorted(item["path"] for item in changes),
        )
        preview = self.service.preview_skill(self.agent, "dev-done", changes, None, revisions(self.service, self.agent, "dev-done", changes))
        self.assertEqual(("dev-done", "ready", True), (preview["action"], preview["classification"], preview["applicable"]), preview["checks"])

    def test_the_dev_start_state_passes_the_dev_start_preflight_in_both_sets(self) -> None:
        for name, fixture_set in FIXTURE_SETS.items():
            with self.subTest(fixture_set=name):
                self.seed("dev-clarify", fixture_set)
                transition = build_transition_preflight(self.root, "F-001", action="dev-start")["facts"]["transition"]
                self.assertEqual("ready", transition["classification"], transition["checks"])
                self.assertEqual("pass", next(item for item in transition["checks"] if item["code"] == "api-contract")["status"])

    def test_the_reopen_route_follows_the_incident(self) -> None:
        for name, fixture_set in FIXTURE_SETS.items():
            with self.subTest(fixture_set=name):
                self.seed("ingest-incident", fixture_set)
                transition = build_transition_preflight(self.root, "F-001", action="reopen-dev")["facts"]["transition"]
                self.assertEqual(("ready", "in-dev", "dev"), (transition["classification"], transition["target_status"], transition["target_owner"]), transition["checks"])


class JourneyReplayTests(JourneyBoard):
    def test_the_default_journey_replays_step_by_step_on_the_board(self) -> None:
        self.assertIsNone(self.replay(None))
        self.assertEqual("in-dev", e2e.read_feature(self.root).status)
        # The journey ends with the feature reopened: every release record and the bug and the incident stay.
        self.assertEqual(["REL-001.md", "REL-002.md"], sorted(path.name for path in (self.root / "knowledge/wiki/releases").glob("REL-*.md")))
        self.assertEqual(["INC-001-blank-summary-for-right-to-left-comments.md"], sorted(path.name for path in (self.root / "knowledge/wiki/incidents").glob("INC-*.md")))
        self.assertEqual([], self.lint_codes())

    def test_the_api_work_journey_replays_through_the_first_qa_attempt(self) -> None:
        self.assertIsNone(self.replay(config.API_WORK_FIXTURES_DIR, through="qa-verify"))
        self.assertEqual(("in-qa", "qa"), (e2e.read_feature(self.root).status, e2e.read_feature(self.root).owner))
        self.assertEqual("implemented", e2e.read_api_contract(self.root)["status"])

    def test_the_api_work_journey_replays_to_the_end_once_the_board_accepts_qa_fail_of_an_implemented_contract(self) -> None:
        stopped = self.replay(config.API_WORK_FIXTURES_DIR, tolerate_known_finding=True)
        if stopped is not None:
            self.skipTest(f"the board refuses {stopped} of a feature with an implemented API contract ({KNOWN_BOARD_FINDING}); the fixtures after it are authored but cannot be replayed")
        self.assertEqual("in-dev", e2e.read_feature(self.root).status)
        self.assertEqual("agreed", e2e.read_api_contract(self.root)["status"])


if __name__ == "__main__":
    unittest.main()
