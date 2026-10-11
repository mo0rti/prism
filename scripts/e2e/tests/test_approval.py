"""The human approval step of the runner, with the host launches, the browser and the board mocked.

A gated agent step is only previewed by the agent host. The runner then approves the proposal as the human grant that holds
exactly the step's roles, through the board's Proposals dialog, and checks the result through the receipt and the files. An
ungated step keeps the agent's own apply run.
"""

import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prism_e2e import browser_client, config, report as reports, runner, workspace as ws  # noqa: E402
from prism_e2e.browser import HumanBrowser  # noqa: E402
from prism_e2e.browser_client import BrowserClient  # noqa: E402
from prism_e2e.hosts import HostRun  # noqa: E402
from prism_e2e.procs import ProcessResult  # noqa: E402
from prism_e2e.runner import Approver, Journey  # noqa: E402
from prism_e2e.tokens import TokenRegistry  # noqa: E402
from prism_e2e.transcripts import HostTranscript, ToolCall  # noqa: E402

PREVIEW = "0b9a87c6-1111-4222-8333-444455556666"
OPERATION = "7d1f1a58-2222-4333-8444-555566667777"
AGENT_IDS = {"claude": "agent-claude-id", "codex": "agent-codex-id"}


def token_for(label: str) -> str:
    return f"token-of-{label}-" + "x" * 24


def host_run(host: str, kind: str, *, final: str, calls: list[ToolCall], exit_code: int = 0) -> HostRun:
    transcript = HostTranscript(host=host, calls=calls, final_message=final, complete=True)
    model = config.TIERS["smoke"][host]
    return HostRun(host, kind, "scripted", ProcessResult(exit_code, "", "", 1.0, False), transcript, {model.model}, {model.effort} if model.effort else set())


def preview_call(preview_id: str = PREVIEW) -> ToolCall:
    return ToolCall(name="preview_skill", ok=True, result={"preview_id": preview_id})


def preview_for(step: config.Step, host: str = "codex") -> dict:
    return {
        "preview_id": PREVIEW,
        "action": {"dev-redeliver": "dev-done", "release-retry": "release-done", "feature-reopen": "reopen-dev"}.get(step.id, step.id),
        "feature_id": "BUG-001" if step.id.startswith("bug-") else "F-001",
        "classification": "ready", "applicable": True,
        "approval": {"required_roles": {"all_of": list(step.roles), "any_of": []}, "proposer": {"kind": "agent", "participant_id": AGENT_IDS[host]}},
        "writes": [{"path": path, "before": "old", "after": "new"} for path in ws.fixture_files([step.id])],
        "moves": [],
    }


def approval_expectations() -> dict:
    return {
        "action": "po-specify", "item_id": "F-001", "proposer_label": "codex", "proposer_id": AGENT_IDS["codex"],
        "required_roles": {"all_of": ["po"], "any_of": []},
        "permitted_paths": list(ws.fixture_files(["po-specify"])), "permitted_moves": [],
    }


class FakeBrowser:
    def __init__(self) -> None:
        self.approvals: list[tuple[str, str]] = []
        self.performed: list[tuple[str, str]] = []
        self.screenshots: list[Path] = []
        self.recovered = 0
        self.fail: Exception | None = None

    def approve(self, preview_id: str, approver: str, expected: dict) -> dict:
        self.approvals.append((preview_id, approver))
        if self.fail is not None:
            raise self.fail
        return {
            "operation_id": OPERATION,
            "preview_text": "Approve po-specify",
            "applied_text": "Proposal approved and applied.",
            "listed": {"action": "po-specify", "item_id": "F-001", "required_roles": {"all_of": ["po"], "any_of": []}, "proposer": {"name": "agent"}, "stale": False, "preview_id": preview_id},
            "stages": {"specified": ["F-001"]},
            "elapsed_s": 2.5,
        }

    def perform(self, action: str, feature_id: str, workspace: Path, screenshots: Path, approver: str) -> dict:
        self.performed.append((action, approver))
        return {"operation_id": OPERATION, "preview_text": "preview", "applied_text": "applied", "writes": {}, "stages": {}, "elapsed_s": 3.0}

    def failure_screenshot(self, path: Path) -> bool:
        self.screenshots.append(path)
        return True

    def recover(self) -> None:
        self.recovered += 1


def receipt_for(step: config.Step, host: str = "codex", *, roles=None, actor_kind: str = "human", proposer_kind: str = "agent", needed=None) -> dict:
    approver_roles = list(step.roles if roles is None else roles)
    label = config.approver_label(step.roles) if step.roles else None
    return {
        "state": "applied",
        "receipt": {
            "applied_paths": ["knowledge/wiki/features/F-001-review-summary-export.md"],
            "actor": {"kind": actor_kind, "participant_id": f"id-of-{label}", "name": f"Approver {'+'.join(step.roles)} (human)", "roles": approver_roles},
            "proposer": {"kind": proposer_kind, "participant_id": AGENT_IDS[host], "name": "agent"},
        },
        "approval": {"required_roles": {"all_of": list(step.roles if needed is None else needed), "any_of": []}, "proposer": {"kind": proposer_kind, "participant_id": AGENT_IDS[host]}},
    }


class JourneyCase(unittest.TestCase):
    """A Journey with its setup skipped: grants, a board and a fake browser, and a workspace nobody reads."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        out = Path(temporary.name)
        self.journey = Journey.__new__(Journey)
        journey = self.journey
        journey.options = SimpleNamespace(tier="smoke", fixtures=None, hosts=["claude", "codex"], steps=list(config.STEP_IDS), timeout_s=60)
        journey.out, journey.work, journey.transcripts, journey.logs = out, out / "work", out / "transcripts", out / "logs"
        for folder in (journey.work, journey.transcripts, journey.logs):
            folder.mkdir()
        journey.env = SimpleNamespace(workspace=out / "ws")
        journey.board = SimpleNamespace(base_url="http://127.0.0.1:1", port=1)
        journey.tokens = TokenRegistry()
        journey.approvers = {}
        for roles in config.APPROVER_ROLE_SETS:
            label = config.approver_label(roles)
            journey.tokens.add(label, token_for(label))
            journey.approvers[label] = Approver(label, f"Approver {'+'.join(roles)} (human)", roles, f"id-of-{label}")
        journey.agent_ids = dict(AGENT_IDS)
        journey.executables = {}
        journey.run_info = {}
        journey.results = []
        journey.seeds = []
        journey.browser = FakeBrowser()
        self.browser = journey.browser
        self.fetched: list[tuple[str, str]] = []
        self.launches: list[str] = []

    def run_step(self, step_id: str, *, receipt: dict | None = None, launches: list[HostRun] | None = None, status=("specified", "po")):
        step = config.STEPS_BY_ID[step_id]
        host = config.host_for(step, ["claude", "codex"])
        result = reports.StepResult(step=step.id, kind=step.kind, host=host or "")
        if launches is not None:
            runs = list(launches)
        else:
            runs = [] if step.is_human else [host_run(host, "preview", final=f"Preview ID: {PREVIEW}", calls=[preview_call()])]
        feature = ws.FeatureState(status[0], status[1], status[0], status[1], [], "")

        def launch(*args, **kwargs):
            self.launches.append(args[1])
            run = runs.pop(0)
            args[6].append(run)
            return run

        def fetch(board, token, operation_id):
            self.fetched.append((token, operation_id))
            return receipt if receipt is not None else receipt_for(step, host or "codex")

        with patch.object(Journey, "_launch", side_effect=launch), patch.object(ws, "read_feature", return_value=feature), patch.object(
            ws, "fetch_receipt", side_effect=fetch
        ), patch.object(ws, "fetch_preview", return_value=preview_for(step, host or "codex")), patch.object(ws, "run_lint", return_value=ws.LintResult(0, 0, 0)), patch.object(Journey, "_step_specific_checks"):
            if step.is_human:
                self.journey.run_human_step(step, 5, result)
            else:
                self.journey.run_agent_step(step, 4, host, result)
        return result


class GatedStepTests(JourneyCase):
    def test_the_agent_only_previews_and_the_human_grant_with_the_roles_approves_in_the_board(self):
        result = self.run_step("po-specify")
        self.assertEqual(self.launches, ["preview"], "no apply run for a gated step")
        self.assertEqual(self.browser.approvals, [(PREVIEW, "human-po")])
        self.assertEqual(result.status, "passed", result.reason)
        self.assertEqual(result.operation_id, OPERATION)
        self.assertEqual(result.preview_id, PREVIEW)
        self.assertEqual(result.approval["approver"], "human-po")
        self.assertEqual(result.approval["roles"], ["po"])
        self.assertEqual(result.approval["proposer_id"], AGENT_IDS["codex"])
        self.assertEqual(result.approval["route"], "proposals dialog")
        names = [check.name for check in result.checks]
        for expected in ("receipt_applied", "stage_and_owner", "status_board_matches_page", "lint_no_errors", "applied_by_role_holder", "proposed_by_agent", "approval_roles_as_expected"):
            self.assertIn(expected, names)
        self.assertNotIn("apply_called", names, "the agent applied nothing")
        self.assertTrue(all(check.ok for check in result.checks), [check for check in result.checks if not check.ok])
        self.assertGreaterEqual(result.elapsed_s, 2.5, "the approval counts toward the step's time")

    def test_the_receipt_is_read_with_the_approvers_own_token(self):
        self.run_step("po-specify")
        self.assertEqual(self.fetched, [(token_for("human-po"), OPERATION)])

    def test_the_approval_record_is_saved_without_a_token(self):
        self.run_step("po-specify")
        record = json.loads((self.journey.transcripts / "04-po-specify.approval.json").read_text(encoding="utf-8"))
        self.assertEqual((record["preview_id"], record["operation_id"], record["approver"]["approver"]), (PREVIEW, OPERATION, "human-po"))
        self.assertEqual(record["listed"]["required_roles"], {"all_of": ["po"], "any_of": []})
        for label in self.journey.approvers:
            self.assertNotIn(token_for(label), json.dumps(record))

    def test_every_gated_step_is_approved_by_the_grant_named_in_the_table(self):
        for step in config.STEPS:
            if not step.gated:
                continue
            with self.subTest(step=step.id):
                self.browser.approvals.clear()
                result = self.run_step(step.id, status=(step.status, step.owner))
                self.assertEqual(self.browser.approvals, [(PREVIEW, config.approver_label(step.roles))])
                self.assertEqual(result.approval["roles"], list(step.roles))
                self.assertEqual(result.status, "passed", result.reason)

    def test_an_approver_that_does_not_hold_exactly_the_roles_fails_the_step(self):
        step = config.STEPS_BY_ID["qa-pass"]
        result = self.run_step("qa-pass", receipt=receipt_for(step, roles=["qa", "release"]), status=("ready-for-release", "release"))
        self.assertEqual(result.status, "failed")
        self.assertIn("applied_by_role_holder", result.reason)

    def test_an_operation_applied_by_an_agent_is_not_an_approval(self):
        step = config.STEPS_BY_ID["qa-pass"]
        result = self.run_step("qa-pass", receipt=receipt_for(step, actor_kind="agent"), status=("ready-for-release", "release"))
        self.assertEqual(result.status, "failed")
        self.assertIn("applied_by_role_holder", result.reason)

    def test_a_proposal_that_was_not_made_by_the_hosts_agent_fails_the_step(self):
        step = config.STEPS_BY_ID["po-specify"]
        result = self.run_step("po-specify", receipt=receipt_for(step, proposer_kind="human"))
        self.assertEqual(result.status, "failed")
        self.assertIn("proposed_by_agent", result.reason)

    def test_the_board_must_have_required_exactly_the_roles_of_the_table(self):
        step = config.STEPS_BY_ID["design-handoff"]
        result = self.run_step("design-handoff", receipt=receipt_for(step, host="claude", needed=["designer", "tech-lead"]), status=("ready-for-dev", "dev"))
        self.assertEqual(result.status, "failed")
        self.assertIn("approval_roles_as_expected", result.reason)

    def test_a_refused_approval_raises_after_a_screenshot_and_a_reload(self):
        self.browser.fail = AssertionError("The board refused the approval: HTTP 403 role_required")
        with self.assertRaises(AssertionError):
            self.run_step("po-specify")
        self.assertEqual(len(self.browser.screenshots), 1)
        self.assertTrue(self.browser.screenshots[0].name.endswith("04-po-specify-approval-failed.png"))
        self.assertEqual(self.browser.recovered, 1)

    def test_an_agent_that_applies_in_the_preview_run_is_not_approved(self):
        applying = host_run("codex", "preview", final=f"Preview ID: {PREVIEW}", calls=[preview_call(), ToolCall(name="apply", ok=True)])
        result = self.run_step("po-specify", launches=[applying])
        self.assertEqual((result.status, result.reason), ("failed", "agent applied during the preview run"))
        self.assertEqual(self.browser.approvals, [])

    def test_an_apply_the_board_refused_is_a_finding_and_the_proposal_is_still_approved(self):
        refused = ToolCall(name="apply", ok=False, error_code="approval_required", error_text="Error executing tool apply: approval_required: a human approves it")
        tried = host_run("codex", "preview", final=f"Preview ID: {PREVIEW}", calls=[preview_call(), refused])
        result = self.run_step("po-specify", launches=[tried])
        self.assertEqual(self.browser.approvals, [(PREVIEW, "human-po")])
        self.assertEqual(result.status, "passed", result.reason)
        self.assertFalse(result.first_attempt_success, "the agent did not stop at the preview")
        self.assertTrue(any("tried to apply the gated preview" in note and "approval_required" in note for note in result.notes), result.notes)

    def test_no_preview_id_means_no_approval(self):
        silent = host_run("codex", "preview", final="Done.", calls=[preview_call()])
        result = self.run_step("po-specify", launches=[silent])
        self.assertEqual(result.reason, "agent did not report a preview ID it was given")
        self.assertEqual(self.browser.approvals, [])

    def test_a_host_that_failed_is_not_approved(self):
        broken = host_run("codex", "preview", final="", calls=[], exit_code=1)
        result = self.run_step("po-specify", launches=[broken])
        self.assertIn("host exit 1", result.reason)
        self.assertEqual(self.browser.approvals, [])


class UngatedStepTests(JourneyCase):
    def test_an_ungated_step_keeps_the_agents_own_apply_run(self):
        apply_run = host_run("codex", "apply", final="Applied", calls=[ToolCall(name="apply", ok=True)])
        result = self.run_step("ask", launches=[host_run("codex", "preview", final=f"Preview ID: {PREVIEW}", calls=[preview_call()]), apply_run], status=("raw", "po"))
        self.assertEqual(self.launches, ["preview", "apply"])
        self.assertEqual(self.browser.approvals, [])
        self.assertIsNone(result.approval)
        self.assertIn("apply_called", [check.name for check in result.checks])
        self.assertNotIn("applied_by_role_holder", [check.name for check in result.checks])
        self.assertEqual(result.status, "passed", result.reason)

    def test_an_ungated_receipt_is_read_with_the_observer_grant(self):
        apply_run = host_run("codex", "apply", final="Applied", calls=[ToolCall(name="apply", ok=True)])
        receipt = {"state": "applied", "receipt": {"applied_paths": [], "actor": {"kind": "agent", "participant_id": AGENT_IDS["codex"], "roles": []}}}
        self.run_step("ask", receipt=receipt, launches=[host_run("codex", "preview", final=f"Preview ID: {PREVIEW}", calls=[preview_call()]), apply_run], status=("raw", "po"))
        self.assertEqual(self.fetched[0][0], token_for(config.approver_label(config.OBSERVER_ROLES)))
        self.assertNotEqual(self.fetched[0][1], OPERATION, "the operation ID is the one the apply run was given")


class HumanStepTests(JourneyCase):
    def test_a_direct_human_step_signs_in_as_the_grant_with_its_roles(self):
        for step_id, label in (("po-handoff", "human-po"), ("design-start", "human-tech-lead"), ("dev-start", "human-dev")):
            with self.subTest(step=step_id):
                step = config.STEPS_BY_ID[step_id]
                receipt = receipt_for(step)
                receipt["receipt"].pop("proposer")
                result = self.run_step(step_id, receipt=receipt, status=(step.status, step.owner))
                self.assertEqual(self.browser.performed[-1], (step_id, label))
                self.assertEqual(result.approval["route"], "card action")
                self.assertEqual(result.approval["roles"], list(step.roles))
                self.assertEqual(result.status, "passed", result.reason)
                self.assertEqual(self.fetched[-1][0], token_for(label))
                self.assertIn("applied_by_role_holder", [check.name for check in result.checks])
                self.assertNotIn("proposed_by_agent", [check.name for check in result.checks])


class DependencyTests(JourneyCase):
    def test_a_failed_step_skips_its_dependants_and_a_seed_clears_them(self):
        self.journey.options.steps = ["ask", "po-clarify", "po-specify", "dev-start", "dev-done"]
        self.journey.board = SimpleNamespace(base_url="http://127.0.0.1:1", port=1)
        seeded: list[str | None] = []

        def agent(step, number, host, result):
            if step.id == "ask":
                result.fail("check failed: one_question_added")
            else:
                result.status = "passed"

        def human(step, number, result):
            result.status = "passed"

        with patch.object(Journey, "run_agent_step", side_effect=agent), patch.object(Journey, "run_human_step", side_effect=human), patch.object(
            Journey, "seed", side_effect=lambda through: seeded.append(through) or True
        ):
            self.journey.run_steps()
        outcomes = {result.step: (result.status, result.reason) for result in self.journey.results}
        self.assertEqual(outcomes["ask"][0], "failed")
        self.assertEqual(outcomes["po-clarify"], ("skipped", "dependency failed: ask"))
        self.assertEqual(outcomes["po-specify"], ("skipped", "dependency failed: ask"))
        self.assertEqual(seeded, ["po-intake", "dev-clarify"], "the first seed starts the run; the second one clears the failure")
        self.assertEqual((outcomes["dev-start"][0], outcomes["dev-done"][0]), ("passed", "passed"))

    def test_a_failed_seed_skips_what_depends_on_it(self):
        self.journey.options.steps = ["dev-start", "dev-done"]
        with patch.object(Journey, "run_agent_step"), patch.object(Journey, "run_human_step"), patch.object(Journey, "seed", return_value=False):
            self.journey.run_steps()
        self.assertEqual([(result.step, result.status, result.reason) for result in self.journey.results], [("dev-start", "skipped", "seeded state failed lint"), ("dev-done", "skipped", "seeded state failed lint")])


class StepChecksOnTheFixturesTests(unittest.TestCase):
    """The result checks of every step hold on the state its own fixtures record, and fail on the state before it."""

    EXPECTED = {
        "tech-design-done": {"design_tracks_settled", "technical_design_page"},
        "design-handoff": {"requirement_page_generated"},
        "dev-done": {"delivery_evidence_recorded", "requirement_done"},
        "qa-verify": {"qa_rows_recorded", "bug_opened"},
        "qa-fail": {"evidence_archived", "requirement_in_progress"},
        "bug-start": {"bug_in_fix"},
        "bug-fixed": {"bug_fixed_with_fix_row"},
        "dev-redeliver": {"delivery_evidence_recorded", "requirement_done"},
        "bug-verify": {"bug_verified_with_passing_row"},
        "qa-pass": {"qa_second_attempt_passed", "release_row_pending"},
        "release-done": {"release_record_failed", "release_row_failed", "bug_still_verified"},
        "release-retry": {"release_record_retry", "release_row_released", "bug_released", "first_record_unchanged"},
        "ingest-incident": {"incident_recorded", "incident_cause_unknown", "intake_moved", "operations_lists_incident", "no_other_page_created"},
        "feature-reopen": {"evidence_archived", "evidence_tables_empty", "release_records_unchanged"},
    }
    API_ONLY = {
        "tech-design-done": {"api_contract_agreed"},
        "design-handoff": {"requirement_links_contract"},
        "dev-done": {"contract_implemented_and_cited"},
        "qa-fail": {"contract_agreed_again"},
        "dev-redeliver": {"contract_implemented_and_cited"},
    }

    def checks_of(self, root: Path, step: config.Step, fixture_set, previous: str | None):
        if previous is not None:
            ws.seed_state(root, previous, fixture_set)
        before = ws.read_feature(root)
        ws.seed_state(root, step.id, fixture_set)
        journey = Journey.__new__(Journey)
        journey.env = SimpleNamespace(workspace=root)
        result = reports.StepResult(step=step.id, kind=step.kind, host="codex")
        journey._step_specific_checks(step, result, before, ws.read_feature(root))
        return result

    def workspace(self) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / "knowledge/wiki").mkdir(parents=True)
        (root / "knowledge/wiki/status-board.md").write_text((config.REPO_ROOT / "template/knowledge/wiki/status-board.md").read_text(encoding="utf-8"), encoding="utf-8")
        return root

    def test_every_check_holds_on_the_state_its_step_leaves_in_both_sets(self):
        for name, fixture_set in (("default", None), ("api-work", config.API_WORK_FIXTURES_DIR)):
            root = self.workspace()
            for index, step in enumerate(config.STEPS):
                if step.is_human:
                    continue
                with self.subTest(fixture_set=name, step=step.id):
                    previous = config.STEP_IDS[index - 1] if index else None
                    result = self.checks_of(root, step, fixture_set, previous)
                    failed = [check for check in result.checks if not check.ok]
                    self.assertEqual(failed, [])
                    names = {check.name for check in result.checks}
                    self.assertLessEqual(self.EXPECTED.get(step.id, set()), names)
                    if fixture_set is not None:
                        self.assertLessEqual(self.API_ONLY.get(step.id, set()), names)
                    else:
                        self.assertFalse(self.API_ONLY.get(step.id, set()) & names, "no contract check without API work")

    def test_a_check_fails_on_the_state_before_its_step(self):
        cases = {
            "qa-fail": "qa-verify",  # the delivery rows are still active
            "qa-pass": "bug-verify",  # still the first attempt, no passing QA row on the fix
            "release-done": "qa-pass",  # no record yet
            "release-retry": "release-done",  # the record is still the failed attempt
            "ingest-incident": "release-retry",  # no incident page
            "feature-reopen": "ingest-incident",  # the evidence is still active
            "bug-verify": "bug-fixed",
            "dev-redeliver": "bug-fixed",  # still the first delivery
        }
        for step_id, earlier in cases.items():
            with self.subTest(step=step_id):
                root = self.workspace()
                step = config.STEPS_BY_ID[step_id]
                ws.seed_state(root, earlier, None)
                journey = Journey.__new__(Journey)
                journey.env = SimpleNamespace(workspace=root)
                result = reports.StepResult(step=step.id, kind=step.kind, host="codex")
                journey._step_specific_checks(step, result, None, ws.read_feature(root))
                self.assertTrue([check.name for check in result.checks if not check.ok], f"{step_id} passed on the state after {earlier}")


    def test_the_failing_criterion_of_the_first_attempt_must_be_the_one_about_the_comments_not_shown(self):
        root = self.workspace()
        ws.seed_state(root, "qa-verify", None)
        page = ws.find_feature_page(root)
        text = page.read_text(encoding="utf-8")
        failing = next(line for line in text.splitlines() if "| fail |" in line)
        number = next(iter(ws.cited_numbers(failing)))
        page.write_text(text.replace(failing, failing.replace(f"AC-{number}@", "AC-1@")), encoding="utf-8", newline="\n")
        journey = Journey.__new__(Journey)
        journey.env = SimpleNamespace(workspace=root)
        result = reports.StepResult(step="qa-verify", kind="agent", host="codex")
        journey._step_specific_checks(config.STEPS_BY_ID["qa-verify"], result, None, ws.read_feature(root))
        check = next(check for check in result.checks if check.name == "qa_rows_recorded")
        self.assertFalse(check.ok)
        self.assertIn("not the one about the comments not shown", check.detail)


class BrowserApprovalTests(unittest.TestCase):
    """HumanBrowser.approve with Playwright's page replaced: the proposal is found by its preview ID and approved as the right grant."""

    def browser(self, proposals, *, ok=True, payload=None):
        browser = HumanBrowser("http://127.0.0.1:1", {"human-po": "tok-po-" + "p" * 20, "human-qa": "tok-qa-" + "q" * 20})
        browser._module = SimpleNamespace(expect=lambda target: MagicMock())
        page, board = MagicMock(), MagicMock()
        page.evaluate.side_effect = lambda script, *args: {"proposals": proposals} if "/proposals" in script else preview_for(config.STEPS_BY_ID["po-specify"])
        response = MagicMock()
        response.ok, response.status = ok, 200 if ok else 403
        response.url = "http://127.0.0.1:1/api/board/v1/apply"
        response.request.method = "POST"
        response.request.post_data_json = {"preview_id": PREVIEW, "operation_id": OPERATION, "review_revision": "r", "semantic_review_acknowledged": True}
        response.json.return_value = payload or {"state": "applied"}
        manager = MagicMock()
        manager.__enter__.return_value = SimpleNamespace(value=response)
        manager.__exit__.return_value = False
        page.expect_response.return_value = manager
        board.stages.return_value = {"specified": ["F-001"]}
        browser.page, browser.board = page, board
        return browser, page, board

    def listed(self, preview_id=PREVIEW, action="po-specify"):
        return {"preview_id": preview_id, "action": action, "item_id": "F-001", "required_roles": {"all_of": ["po"], "any_of": []}, "proposer": {"name": "agent"}, "stale": False}

    def test_the_proposal_is_found_by_its_preview_id_among_several_and_approved(self):
        browser, page, board = self.browser([self.listed("other-1"), self.listed(PREVIEW), self.listed("other-2")])
        outcome = browser.approve(PREVIEW, "human-po", approval_expectations())
        dialog = page.get_by_role.return_value
        dialog.locator.assert_any_call(f'[data-preview-id="{PREVIEW}"]')
        self.assertEqual(outcome["operation_id"], OPERATION)
        self.assertEqual(outcome["listed"]["action"], "po-specify")
        self.assertEqual(outcome["stages"], {"specified": ["F-001"]})
        board.sign_in.assert_called_once_with("tok-po-" + "p" * 20)
        self.assertEqual(browser.signed_in_as, "human-po")

    def test_a_second_approval_by_the_same_grant_reloads_and_another_grant_signs_out_and_in(self):
        browser, page, board = self.browser([self.listed()])
        browser.approve(PREVIEW, "human-po", approval_expectations())
        browser.approve(PREVIEW, "human-po", approval_expectations())
        page.reload.assert_called_once()
        board.sign_in.assert_called_once()
        browser.approve(PREVIEW, "human-qa", approval_expectations())
        self.assertEqual([call.args[0] for call in board.sign_in.call_args_list], ["tok-po-" + "p" * 20, "tok-qa-" + "q" * 20])
        page.get_by_role.assert_any_call("button", name="Sign out")
        self.assertEqual(browser.signed_in_as, "human-qa")

    def test_a_proposal_the_grant_cannot_see_is_reported_with_the_list_size(self):
        browser, _page, _board = self.browser([self.listed("other-1")])
        with self.assertRaises(AssertionError) as caught:
            browser.approve(PREVIEW, "human-po", approval_expectations())
        self.assertIn(PREVIEW, str(caught.exception))
        self.assertIn("1 proposal", str(caught.exception))

    def test_a_refused_apply_is_reported_with_the_boards_code(self):
        browser, _page, _board = self.browser([self.listed()], ok=False, payload={"error": {"code": "role_required", "message": "You do not hold the roles."}})
        with self.assertRaises(AssertionError) as caught:
            browser.approve(PREVIEW, "human-po", approval_expectations())
        self.assertIn("role_required", str(caught.exception))
        self.assertIn("HTTP 403", str(caught.exception))

    def test_an_approver_without_a_token_is_refused_before_the_browser_moves(self):
        browser, page, _board = self.browser([self.listed()])
        with self.assertRaises(Exception) as caught:
            browser.approve(PREVIEW, "human-release", approval_expectations())
        self.assertIn("human-release", str(caught.exception))
        page.get_by_role.assert_not_called()


class BrowserClientTests(unittest.TestCase):
    TOKENS = {"human-po": "tok-po-" + "p" * 20, "human-dev": "tok-dev-" + "d" * 20}

    def test_the_tokens_reach_the_worker_only_through_its_environment(self):
        client = BrowserClient("http://127.0.0.1:1", self.TOKENS, Path(tempfile.gettempdir()) / "browser-worker-test.err")
        with patch.object(browser_client.subprocess, "Popen") as popen, patch.object(BrowserClient, "_call", return_value={"ok": True, "version": "1"}), patch.object(
            browser_client.threading, "Thread"
        ), patch.object(browser_client, "register_live"):
            client.start()
        command = " ".join(str(part) for part in popen.call_args.args[0])
        environment = popen.call_args.kwargs["env"]
        self.assertEqual(json.loads(environment[browser_client.TOKENS_VARIABLE]), self.TOKENS)
        self.assertNotIn("PRISM_BOARD_TOKEN", environment)
        for token in self.TOKENS.values():
            self.assertNotIn(token, command)

    def test_perform_and_approve_name_the_approver_in_the_request(self):
        client = BrowserClient("http://127.0.0.1:1", self.TOKENS, Path("unused.err"))
        sent = []

        def call(request, timeout):
            sent.append(request)
            return {"ok": True, "outcome": {"operation_id": OPERATION}}

        with patch.object(BrowserClient, "_call", side_effect=call):
            client.perform("dev-start", "F-001", Path("ws"), Path("shots"), "human-dev")
            client.approve(PREVIEW, "human-po", approval_expectations())
        self.assertEqual((sent[0]["op"], sent[0]["approver"], sent[0]["action"]), ("perform", "human-dev", "dev-start"))
        self.assertEqual((sent[1]["op"], sent[1]["approver"], sent[1]["preview_id"]), ("approve", "human-po", PREVIEW))
        self.assertEqual(sent[1]["expected"], approval_expectations())
        for request in sent:
            self.assertNotIn("tok-", json.dumps(request))

    def test_a_failed_worker_reply_raises_with_its_message(self):
        client = BrowserClient("http://127.0.0.1:1", self.TOKENS, Path("unused.err"))
        with patch.object(BrowserClient, "_call", return_value={"ok": False, "error": "AssertionError: The board refused the approval"}):
            with self.assertRaises(RuntimeError) as caught:
                client.approve(PREVIEW, "human-po", approval_expectations())
        self.assertIn("refused the approval", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
