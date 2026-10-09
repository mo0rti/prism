"""The journey: setup, steps, checks, report and cleanup."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import time
import traceback
from typing import Any
import uuid

from . import answers, config, report as reports, workspace as ws
from .browser import BrowserUnavailable
from .browser_client import BrowserClient
from .config import Step
from .hosts import HostRun, run_host
from .procs import clean_env, find_claude, find_codex, kill_all_live, run_captured
from .tokens import TokenRegistry
from .transcripts import collapse_models, first_reported_preview_id, model_matches

PREVIEW_NAMES = ("preview_skill", "preview_transition")


@dataclass(frozen=True)
class Approver:
    """A human grant of this run: it holds exactly ``roles`` and signs in to the board to approve or apply the steps that need them."""

    label: str
    name: str
    roles: tuple[str, ...]
    participant_id: str


@dataclass
class Options:
    tier: str
    out: Path
    steps: list[str]
    hosts: list[str]
    wheel: Path | None = None
    keep_work: bool = False
    timeout_s: float = config.DEFAULT_TIMEOUT_SECONDS
    fixtures: Path | None = None  # a fixture set overlaid on the default fixtures and prompts


def load_prompt(step_id: str, fixture_set: Path | None = None) -> str:
    if fixture_set is not None and (fixture_set / "prompts" / f"{step_id}.txt").is_file():
        return (fixture_set / "prompts" / f"{step_id}.txt").read_text(encoding="utf-8")
    return (config.PROMPTS_DIR / f"{step_id}.txt").read_text(encoding="utf-8")


def build_preview_prompt(step_id: str, fixture_set: Path | None, feature: ws.FeatureState | None) -> str:
    """The preview prompt. A clarify step's answers are filled in from the open questions its role owns on the live feature page."""

    text = load_prompt(step_id, fixture_set)
    role = answers.CLARIFY_ROLES.get(step_id)
    if role is None:
        return text
    open_questions = [(question.number, question.text) for question in feature.open_questions(role)] if feature else []
    return answers.fill(text, role, open_questions)


def render_apply_prompt(step: Step, preview_id: str, operation_id: str) -> str:
    template = (config.PROMPTS_DIR / "apply.txt").read_text(encoding="utf-8")
    return template.format(preview_id=preview_id, operation_id=operation_id, summary=step.summary)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class Journey:
    def __init__(self, options: Options) -> None:
        options.out = options.out.resolve()
        if options.wheel is not None:
            options.wheel = options.wheel.resolve()
        self.options = options
        self.tokens = TokenRegistry()
        self.out = options.out
        self.work = options.out / "work"
        self.transcripts = options.out / "transcripts"
        self.logs = options.out / "logs"
        self.setup_log: list[str] = []
        self.env: ws.Environment | None = None
        self.board: ws.Board | None = None
        self.browser: BrowserClient | None = None
        self.approvers: dict[str, Approver] = {}  # by label (`human-qa`): the human grants and their roles
        self.agent_ids: dict[str, str] = {}  # host -> the participant ID of its agent grant
        self.results: list[reports.StepResult] = []
        self.seeds: list[dict[str, Any]] = []
        self.run_info: dict[str, Any] = {}
        self.executables: dict[str, Path] = {}
        self.cleanup_notes: list[str] = []
        self.started = time.monotonic()

    # -- the whole run ------------------------------------------------------------------

    def run(self) -> int:
        options = self.options
        for folder in (self.out, self.work, self.transcripts, self.logs):
            folder.mkdir(parents=True, exist_ok=True)
        self.run_info = {
            "tier": options.tier,
            "hosts": options.hosts,
            "steps_selected": options.steps,
            "timeout_s": options.timeout_s,
            "fixtures": str(options.fixtures) if options.fixtures else "default",
            "started": _now(),
            "models": {host: vars_of(model) for host, model in config.TIERS[options.tier].items() if host in options.hosts},
            "verdict": "failed",
        }
        interrupted = False
        try:
            try:
                self.setup()
                self.run_steps()
            except KeyboardInterrupt:
                interrupted = True
                self.run_info["verdict_reason"] = "interrupted"
            except ws.SetupError as error:
                self.run_info["verdict_reason"] = f"setup failed: {error}"
            except Exception as error:  # noqa: BLE001 - the report must still be written
                traceback.print_exc()
                self.run_info["verdict_reason"] = f"unexpected {type(error).__name__}: {self.tokens.redact(str(error))[:300]}"
        finally:
            self.teardown()
        passed = bool(self.results) and all(result.status == "passed" for result in self.results) and not interrupted and "verdict_reason" not in self.run_info
        scan_clean = self.run_info.get("token_scan", "").startswith("clean")
        self.run_info["verdict"] = "passed" if passed and scan_clean else "failed"
        if self.run_info["verdict"] == "failed" and "verdict_reason" not in self.run_info:
            failed = [result.step for result in self.results if result.status != "passed"]
            self.run_info["verdict_reason"] = (f"steps not passed: {', '.join(failed)}" if failed else "token scan found a token")
        self.write_report()
        self.rescan_report_files()
        return 0 if self.run_info["verdict"] == "passed" else (130 if interrupted else 1)

    # -- setup ----------------------------------------------------------------------------

    def setup(self) -> None:
        options = self.options
        needed_hosts = {host for step_id in options.steps if (host := config.host_for(config.STEPS_BY_ID[step_id], options.hosts))}
        for host in sorted(needed_hosts):
            executable = find_claude() if host == "claude" else find_codex()
            if executable is None or not executable.is_file():
                raise ws.SetupError(f"The {host} executable was not found. Set PRISM_E2E_{host.upper()} to its path.")
            self.executables[host] = executable
            version = run_captured([str(executable), "--version"], cwd=self.work, env=clean_env(), timeout=60).stdout.strip().splitlines()
            self.run_info[f"{host}_version"] = version[0] if version else "unknown"
            self.run_info[f"{host}_executable"] = str(executable)
        wheel = options.wheel
        if wheel is None:
            wheel = ws.build_wheel(config.REPO_ROOT, self.work, self.setup_log)
        elif not wheel.is_file():
            raise ws.SetupError(f"--wheel {wheel} is not a file.")
        self.run_info["wheel"] = wheel.name
        self.env = ws.create_environment(wheel.resolve(), self.work, self.setup_log)
        self.run_info["wheel_sha256"] = self.env.wheel_sha256
        self.run_info["prism_version"] = ws.prism_version(self.env)
        ws.install_workspace(self.env, self.setup_log)
        # One human grant for each role set a step needs, holding exactly those roles; an agent grant never holds a role.
        for roles in config.APPROVER_ROLE_SETS:
            label = config.approver_label(roles)
            name = f"Approver {'+'.join(roles)} (human)"
            participant_id = ws.issue_grant(self.env, self.tokens, label, name, "human", self.setup_log, roles)
            self.approvers[label] = Approver(label, name, roles, participant_id)
        self.agent_ids["claude"] = ws.issue_grant(self.env, self.tokens, "claude", "Claude Code agent", "agent", self.setup_log)
        self.agent_ids["codex"] = ws.issue_grant(self.env, self.tokens, "codex", "Codex agent", "agent", self.setup_log)
        self.board = ws.Board(self.env, self.logs / "board-serve.out")
        self.board.start()
        self.setup_log.append(f"board serving on port {self.board.port}")
        self.save_setup_log()

    def save_setup_log(self) -> None:
        text = self.tokens.redact("\n\n".join(self.setup_log))
        (self.logs / "setup.log").write_text(text + "\n", encoding="utf-8", newline="\n")

    # -- steps ----------------------------------------------------------------------------

    def run_steps(self) -> None:
        assert self.env is not None and self.board is not None
        tainted_by: str | None = None
        seed_failed = False
        for action in config.plan_actions(self.options.steps):
            if action.kind == "seed":
                seed_failed = not self.seed(action.step)
                tainted_by = None
                continue
            step = config.STEPS_BY_ID[action.step]  # type: ignore[index]
            host = "browser" if step.is_human else config.host_for(step, self.options.hosts)
            result = reports.StepResult(step=step.id, kind=step.kind, host=host or "")
            self.results.append(result)
            if seed_failed or tainted_by:
                result.status = "skipped"
                result.reason = "seeded state failed lint" if seed_failed else f"dependency failed: {tainted_by}"
                continue
            number = config.STEP_IDS.index(step.id) + 1
            try:
                if step.is_human:
                    self.run_human_step(step, number, result)
                else:
                    self.run_agent_step(step, number, host or "", result)
            except KeyboardInterrupt:
                result.fail("interrupted")
                raise
            except BrowserUnavailable as error:
                result.fail(f"browser unavailable: {error}")
            except Exception as error:  # noqa: BLE001 - one step's failure must not stop the report
                result.fail(f"{type(error).__name__}: {self.tokens.redact(str(error))[:300]}")
            if result.status != "passed":
                result.status = "failed"
                tainted_by = step.id
            if step.kind == "agent" and result.first_attempt_success is None and not result.not_applicable:
                result.first_attempt_success = False

    def seed(self, through: str | None) -> bool:
        """Seed the state after ``through`` from the fixtures; True when lint accepts it."""

        assert self.env is not None
        files = ws.seed_state(self.env.workspace, through, self.options.fixtures)
        lint = ws.run_lint(self.env)
        allowed = ws.ALLOWED_LINT_CODES.get(through or "", frozenset())
        ok = not lint.unexpected(allowed)
        self.seeds.append({"through": through, "files": files, "lint_errors": lint.errors, "lint_ok": ok})
        return ok

    # -- one agent step ---------------------------------------------------------------------

    def run_agent_step(self, step: Step, number: int, host: str, result: reports.StepResult) -> None:
        assert self.env is not None and self.board is not None
        model = config.TIERS[self.options.tier][host]
        result.expected_model, result.expected_effort = model.model, model.effort
        before = ws.read_feature(self.env.workspace)
        role = answers.CLARIFY_ROLES.get(step.id)
        if role is not None and before is not None and not before.open_questions(role):
            # A clarify step with no open question for its role has nothing to do; the journey
            # continues instead of counting the agent's correct refusal as a failure.
            result.status = "passed"
            result.not_applicable = True
            result.notes.append(f"nothing to do: no open {role}-owned question on the feature, so no host was launched")
            return
        if step.id in ws.PENDING_INPUTS:
            # The input of an ingest step is placed right before the step, so a seeded state never carries a half-processed folder.
            ws.place_pending_input(self.env.workspace, step.id, self.options.fixtures)
        runs: list[HostRun] = []

        preview = self._launch(host, "preview", build_preview_prompt(step.id, self.options.fixtures, before), number, step, result, runs)
        transcript = preview.transcript
        preview_calls = transcript.preview_calls
        result.preview_attempts = len(preview_calls)
        result.preview_error_codes = [call.error_code or "error" for call in preview_calls if not call.ok]
        result.other_error_codes = [call.error_code or "error" for call in transcript.calls if not call.ok and call.name not in PREVIEW_NAMES]
        first_ok = bool(preview_calls) and preview_calls[0].ok
        if not preview.exit_ok:
            result.fail("host timed out" if preview.result.timed_out else f"host exit {preview.result.exit_code}")
            return
        applies = transcript.calls_named("apply")
        refused_apply = False
        if applies and step.gated and not any(call.ok for call in applies):
            # The board refused the agent's apply of a gated preview (approval_required). Nothing was written, so the step goes on to the
            # approval; the attempt is a finding against the prompt and the first attempt does not count as a success.
            refused_apply = True
            result.notes.append(f"the agent tried to apply the gated preview and the board refused it ({', '.join(call.error_code or 'error' for call in applies)})")
        elif applies:
            result.fail("agent applied during the preview run")
            return
        known = transcript.successful_preview_ids()
        if not known:
            result.fail("no preview produced" + (f" ({', '.join(result.preview_error_codes)})" if result.preview_error_codes else ""))
            return
        preview_id = first_reported_preview_id(transcript.final_message, known)
        if preview_id is None:
            result.fail("agent did not report a preview ID it was given")
            return
        result.preview_id = preview_id

        if step.gated:
            # A gated preview is only proposed by the agent. The human grant that holds exactly the step's roles approves it in the
            # board; the agent gets no apply run, and the board would refuse its apply with approval_required.
            operation_id = self._approve_in_board(step, number, host, preview_id, result)
        else:
            operation_id = str(uuid.uuid4())
            result.operation_id = operation_id
            apply_run = self._launch(host, "apply", render_apply_prompt(step, preview_id, operation_id), number, step, result, runs)
            if not apply_run.exit_ok:
                result.fail("host timed out" if apply_run.result.timed_out else f"host exit {apply_run.result.exit_code}")
                return
            applies = apply_run.transcript.calls_named("apply")
            result.add_check("apply_called", bool(applies) and applies[-1].ok, "the agent called apply" if applies else "the agent never called apply")
            extra_previews = len(apply_run.transcript.preview_calls)
            if extra_previews:
                result.notes.append(f"the apply run made {extra_previews} extra preview call(s)")
            result.other_error_codes += [call.error_code or "error" for call in apply_run.transcript.calls if not call.ok]

        self._check_models(result, runs, model)
        self._check_state(step, result, before, operation_id, receipt_token=self._receipt_token(step), host=host)
        result.first_attempt_success = first_ok and not refused_apply and all(check.ok for check in result.checks)
        if all(check.ok for check in result.checks):
            result.status = "passed"
        else:
            result.fail("check failed: " + ", ".join(check.name for check in result.checks if not check.ok))

    def _receipt_token(self, step: Step) -> str:
        """The token that reads the step's receipt: the approver's own (the owner of a gated operation), else any writable human's."""

        return self.tokens.get(step.approver or config.approver_label(config.OBSERVER_ROLES))

    def _ensure_browser(self) -> BrowserClient:
        assert self.board is not None
        if self.browser is None:
            tokens = {label: self.tokens.get(label) for label in self.approvers}
            client = BrowserClient(self.board.base_url, tokens, self.logs / "browser-worker.err")
            client.start()
            self.browser = client
            self.run_info["chromium_version"] = client.version
        return self.browser

    def _approve_in_board(self, step: Step, number: int, host: str, preview_id: str, result: reports.StepResult) -> str:
        """Approve a gated agent proposal as the human grant that holds exactly the step's roles. Returns the operation ID the browser submitted."""

        assert step.approver is not None
        approver = self.approvers[step.approver]
        browser = self._ensure_browser()
        try:
            outcome = browser.approve(preview_id, approver.label)
        except Exception:
            browser.failure_screenshot(self.out / "screenshots" / f"{number:02d}-{step.id}-approval-failed.png")
            browser.recover()
            raise
        result.elapsed_s = round(result.elapsed_s + outcome["elapsed_s"], 1)
        result.operation_id = outcome["operation_id"]
        result.approval = {
            "approver": approver.label,
            "approver_name": approver.name,
            "approver_id": approver.participant_id,
            "roles": list(approver.roles),
            "proposer_id": self.agent_ids.get(host),
            "route": "proposals dialog",
        }
        record = {
            "step": step.id,
            "preview_id": preview_id,
            "operation_id": outcome["operation_id"],
            "approver": result.approval,
            "listed": outcome["listed"],
            "review_text": outcome["preview_text"],
            "applied_text": outcome["applied_text"],
            "stages": outcome["stages"],
        }
        (self.transcripts / f"{number:02d}-{step.id}.approval.json").write_text(
            self.tokens.redact(json.dumps(record, indent=2, ensure_ascii=False)) + "\n", encoding="utf-8", newline="\n"
        )
        return outcome["operation_id"]

    def _launch(self, host: str, kind: str, prompt: str, number: int, step: Step, result: reports.StepResult, runs: list[HostRun]) -> HostRun:
        assert self.env is not None and self.board is not None
        run = run_host(
            host=host,
            run_kind=kind,
            prompt=prompt,
            token=self.tokens.get(host),
            model=config.TIERS[self.options.tier][host],
            executable=self.executables[host],
            workspace=self.env.workspace,
            port=self.board.port,
            work=self.work,
            timeout_s=self.options.timeout_s,
            base_name=f"{number:02d}-{step.id}.{kind}",
            tokens=self.tokens,
            transcripts_dir=self.transcripts,
        )
        runs.append(run)
        result.elapsed_s = round(result.elapsed_s + run.result.elapsed_s, 1)
        usage = run.transcript.usage.as_dict() if run.transcript.usage else None
        result.add_usage(usage, run.transcript.cost_usd)
        result.models = collapse_models([*result.models, *run.recorded_models])
        for effort in sorted(run.recorded_efforts):
            if effort not in result.efforts:
                result.efforts.append(effort)
        if run.transcript.host_error:
            result.notes.append(f"{kind} run: host reported {self.tokens.redact(run.transcript.host_error)[:160]}")
        return run

    def _check_models(self, result: reports.StepResult, runs: list[HostRun], model: config.HostModel) -> None:
        recorded_models = {name for run in runs for name in run.recorded_models}
        result.add_check(
            "model_as_configured",
            model_matches(model.model, recorded_models),
            f"expected {model.model}, transcript records {', '.join(sorted(recorded_models)) or 'none'}",
        )
        recorded_efforts = {effort for run in runs for effort in run.recorded_efforts}
        if model.effort:
            result.add_check(
                "effort_as_configured",
                recorded_efforts == {model.effort},
                f"expected {model.effort}, transcript records {', '.join(sorted(recorded_efforts)) or 'none'}",
            )
        elif recorded_efforts:
            result.notes.append(f"{model.model} has no effort setting but the transcript records {', '.join(sorted(recorded_efforts))}")

    # -- one human step -----------------------------------------------------------------------

    def run_human_step(self, step: Step, number: int, result: reports.StepResult) -> None:
        assert self.env is not None and self.board is not None and step.approver is not None
        approver = self.approvers[step.approver]
        browser = self._ensure_browser()
        before = ws.read_feature(self.env.workspace)
        try:
            outcome = browser.perform(step.id, config.FEATURE_ID, self.env.workspace, self.out / "screenshots", approver.label)
        except Exception:
            browser.failure_screenshot(self.out / "screenshots" / f"{number:02d}-{step.id}-failed.png")
            browser.recover()
            raise
        result.elapsed_s = outcome["elapsed_s"]
        result.operation_id = outcome["operation_id"]
        result.approval = {
            "approver": approver.label,
            "approver_name": approver.name,
            "approver_id": approver.participant_id,
            "roles": list(approver.roles),
            "proposer_id": None,
            "route": "card action",
        }
        record = {
            "step": step.id,
            "operation_id": outcome["operation_id"],
            "approver": result.approval,
            "preview_text": outcome["preview_text"],
            "applied_text": outcome["applied_text"],
            "writes": outcome["writes"],
            "stages": outcome["stages"],
        }
        (self.transcripts / f"{number:02d}-{step.id}.human.json").write_text(
            self.tokens.redact(json.dumps(record, indent=2, ensure_ascii=False)) + "\n", encoding="utf-8", newline="\n"
        )
        self._check_state(step, result, before, outcome["operation_id"], receipt_token=self._receipt_token(step))
        if all(check.ok for check in result.checks):
            result.status = "passed"
        else:
            result.fail("check failed: " + ", ".join(check.name for check in result.checks if not check.ok))

    # -- checks after an apply ------------------------------------------------------------------

    def _check_state(
        self, step: Step, result: reports.StepResult, before: ws.FeatureState | None, operation_id: str, *, receipt_token: str, host: str | None = None
    ) -> None:
        assert self.env is not None and self.board is not None
        receipt = ws.fetch_receipt(self.board, receipt_token, operation_id)
        state = receipt.get("state")
        result.apply_state = state or receipt.get("error")
        inner = receipt.get("receipt") or {}
        result.applied_paths = list(inner.get("applied_paths") or [])
        result.add_check("receipt_applied", state == "applied", f"receipt state {result.apply_state}")
        if step.approver is not None:
            self._check_approval(step, result, receipt, host)

        feature = ws.read_feature(self.env.workspace)
        found = (feature.status, feature.owner) if feature else None
        result.add_check(
            "stage_and_owner",
            found == (step.status, step.owner),
            f"expected {step.status}/{step.owner}, found {'/'.join(found) if found else 'no feature page'}",
        )
        if feature is not None:
            result.add_check(
                "status_board_matches_page",
                (feature.board_status, feature.board_owner) == (feature.status, feature.owner),
                f"status board row {feature.board_status}/{feature.board_owner}, page {feature.status}/{feature.owner}",
            )
        lint = ws.run_lint(self.env)
        allowed = ws.ALLOWED_LINT_CODES.get(step.id, frozenset())
        result.add_check(
            "lint_no_errors",
            not lint.unexpected(allowed),
            f"{lint.errors} error(s)" + (f" ({', '.join(lint.error_codes)})" if lint.error_codes else "") + (f", {len(allowed)} code(s) expected after this step" if allowed else ""),
        )
        self._step_specific_checks(step, result, before, feature)

    def _check_approval(self, step: Step, result: reports.StepResult, receipt: dict, host: str | None) -> None:
        """Who applied the operation, read from the board's receipt: a human grant that holds exactly the step's roles.

        For a gated agent step it is also the approval: the proposer is the host's agent grant and the board recorded the
        predicate the step needs. The receipt is the board's record, never what the agent or the browser said.
        """

        assert step.approver is not None
        approver = self.approvers[step.approver]
        inner = receipt.get("receipt") or {}
        actor = inner.get("actor") or {}
        held = sorted(actor.get("roles") or [])
        result.add_check(
            "applied_by_role_holder",
            actor.get("kind") == "human" and actor.get("participant_id") == approver.participant_id and held == sorted(approver.roles),
            f"applied by {actor.get('name', 'no actor')} ({actor.get('kind', '?')}) with roles {', '.join(held) or 'none'}; expected {approver.label} with {', '.join(approver.roles)}",
        )
        if not step.gated:
            return
        approval = receipt.get("approval") or {}
        proposer = inner.get("proposer") or approval.get("proposer") or {}
        expected = self.agent_ids.get(host or "")
        result.add_check(
            "proposed_by_agent",
            proposer.get("kind") == "agent" and bool(expected) and proposer.get("participant_id") == expected,
            f"proposed by {proposer.get('name', 'nobody')} ({proposer.get('kind', '?')})",
        )
        required = approval.get("required_roles") or {}
        needed = sorted(required.get("all_of") or [])
        result.add_check(
            "approval_roles_as_expected",
            needed == sorted(step.roles) and not required.get("any_of"),
            f"the board required {', '.join(needed) or 'no role'}; the step needs {', '.join(step.roles)}",
        )

    def _step_specific_checks(self, step: Step, result: reports.StepResult, before: ws.FeatureState | None, feature: ws.FeatureState | None) -> None:
        assert self.env is not None
        if feature is None:
            return
        workspace = self.env.workspace
        page = ws.Page(ws.find_feature_page(workspace) or workspace, ws.parse_front_matter(feature.text), feature.text)
        api_work = ws.declares_api_work(feature.text)
        requirement = ws.read_requirement(workspace)
        contract = ws.read_api_contract(workspace)
        bug = ws.read_page(workspace, "bugs", ws.BUG_ID)
        first_record = ws.read_page(workspace, "releases", "REL-001")
        second_record = ws.read_page(workspace, "releases", "REL-002")
        delivery = page.rows("Delivery evidence")
        qa_rows = page.rows("QA verification")
        release_rows = page.rows("Release")
        check = result.add_check

        def delivery_artifact(commit: str) -> bool:
            return len(delivery) == 1 and delivery[0][0] == "backend" and delivery[0][1].strip("`") == f"commit:{commit}"

        def contract_cited() -> bool:
            return bool(delivery) and delivery[0][2].startswith("F-001@v1:c1:")

        def contract_is(status: str) -> bool:
            return bool(contract) and contract.get("status") == status

        def requirement_is(status: str) -> bool:
            return requirement is not None and requirement.front.get("status") == status

        def bug_is(status: str, owner: str) -> bool:
            return bug is not None and (bug.front.get("status"), bug.front.get("owner")) == (status, owner)

        def bug_rows(name: str) -> list[list[str]]:
            return bug.rows(name) if bug is not None else []

        if step.id == "po-intake":
            check("intake_moved", (workspace / "knowledge/intake/processed/2026-09-30-review-summary").is_dir() and not (workspace / ws.PENDING_INTAKE).exists(), "the pending folder moved to processed")
            owners = {owner: sum(1 for question in feature.questions if question.owner == owner) for owner in ("po", "designer", "dev")}
            if not owners["designer"] or not owners["dev"]:
                result.notes.append(
                    "the intake routed questions to " + ", ".join(f"{owner} {count}" for owner, count in owners.items())
                    + "; the later design-clarify and dev-clarify steps answer a designer and a developer question"
                )
        elif step.id == "ask":
            grown = before is not None and len(feature.questions) == len(before.questions) + 1
            check("one_question_added", grown, f"{len(before.questions) if before else '?'} -> {len(feature.questions)} question rows")
            newest = feature.questions[-1] if feature.questions else None
            check("question_routed_to_po", bool(newest and newest.owner == "po" and newest.is_open), f"newest row owner {newest.owner if newest else 'none'}")
        elif step.id == "po-clarify":
            check("no_open_po_questions", not feature.open_questions("po"), f"{len(feature.open_questions('po'))} open")
        elif step.id == "design-clarify":
            check("no_open_designer_questions", not feature.open_questions("designer"), f"{len(feature.open_questions('designer'))} open")
        elif step.id == "dev-clarify":
            check("no_open_dev_questions", not feature.open_questions("dev"), f"{len(feature.open_questions('dev'))} open")
        elif step.id == "tech-design-done":
            tracks = ws.design_tracks(feature.text)
            check(
                "design_tracks_settled",
                tracks.get("technical") == "done" and tracks.get("ui") in {"done", "not-applicable"},
                f"design tracks ui {tracks.get('ui', 'missing')}, technical {tracks.get('technical', 'missing')}",
            )
            technical = ws.find_technical_design(workspace)
            check("technical_design_page", technical is not None, "the technical design page exists" if technical else "no technical design page")
            if api_work:
                check("api_contract_agreed", bool(contract) and contract.get("feature-id") == config.FEATURE_ID and contract_is("agreed"), f"API contract page {contract.get('status') if contract else 'missing'}")
        elif step.id == "design-handoff":
            check("requirement_page_generated", requirement is not None and requirement_is("pending"), "the backend requirement page exists and is pending" if requirement else "no requirement page for the backend app")
            if api_work:
                linked = requirement is not None and "api-contracts/F-001" in requirement.text
                check("requirement_links_contract", linked, "the requirement page links the contract" if linked else "the requirement page does not link the contract")
        elif step.id in {"dev-done", "dev-redeliver"}:
            commit = "3f9c2ab" if step.id == "dev-done" else "5d7a1e4"
            check("delivery_evidence_recorded", delivery_artifact(commit), f"the active Delivery evidence row names commit:{commit}" if delivery_artifact(commit) else f"the active Delivery evidence rows are {[row[1] for row in delivery]}")
            check("requirement_done", requirement_is("done"), f"the requirement page is {requirement.front.get('status') if requirement else 'missing'}")
            if api_work:
                check("contract_implemented_and_cited", contract_is("implemented") and contract_cited(), f"contract {contract.get('status') if contract else 'missing'}, cited {contract_cited()}")
        elif step.id == "qa-verify":
            results = {row[6] for row in qa_rows if row[0] == "backend" and row[5] == "qa-1"}
            failing = [row for row in qa_rows if row[6] == "fail"]
            # The failing criterion is the one about the line that counts the comments left out; its number is the agent's own.
            failed_numbers = sorted(ws.cited_numbers(failing[0][1])) if failing else []
            about_overflow = len(failed_numbers) == 1 and "not shown" in ws.criterion_text(feature.text, failed_numbers[0])
            check("qa_rows_recorded", results == {"pass", "fail"} and about_overflow, f"QA results of qa-1: {', '.join(sorted(results)) or 'none'}; failing criteria {failed_numbers or 'none'}" + ("" if about_overflow or not failed_numbers else " (not the one about the comments not shown)"))
            check(
                "bug_opened",
                bug_is("open", "dev") and bug is not None and bug.front.get("feature") == config.FEATURE_ID and "backend" in bug.front_list("apps"),
                "BUG-001 is open, owned by dev, linked to F-001" if bug else "no BUG-001 page",
            )
        elif step.id == "qa-fail":
            archived = not delivery and not qa_rows and not release_rows
            check("evidence_archived", archived and "qa-fail" in page.section("Evidence history") and "BUG-001" in page.section("Evidence history"), "the delivery and QA rows left the active tables for a qa-fail entry that links BUG-001" if archived else "an evidence table still holds rows")
            check("requirement_in_progress", requirement_is("in-progress"), f"the requirement page is {requirement.front.get('status') if requirement else 'missing'}")
            if api_work:
                check("contract_agreed_again", contract_is("agreed"), f"contract {contract.get('status') if contract else 'missing'}")
        elif step.id == "bug-start":
            check("bug_in_fix", bug_is("in-fix", "dev"), f"BUG-001 is {bug.front.get('status') if bug else 'missing'}")
        elif step.id == "bug-fixed":
            fix = bug_rows("Fix")
            check("bug_fixed_with_fix_row", bug_is("fixed", "qa") and len(fix) == 1 and fix[0][1].strip("`") == "commit:5d7a1e4", f"BUG-001 is {bug.front.get('status') if bug else 'missing'} with {len(fix)} Fix row(s)")
        elif step.id == "bug-verify":
            verification = bug_rows("Verification")
            passed = len(verification) == 1 and verification[0][5] == "pass" and verification[0][2].strip("`") == "commit:5d7a1e4" and verification[0][4] == "qa-1"
            check("bug_verified_with_passing_row", bug_is("verified", "release") and passed, f"BUG-001 is {bug.front.get('status') if bug else 'missing'} with {len(verification)} Verification row(s)")
        elif step.id == "qa-pass":
            numbers = ws.criterion_numbers(feature.text)
            covered = set().union(*(ws.cited_numbers(row[1]) for row in qa_rows)) if qa_rows else set()
            second = bool(qa_rows) and all(row[6] == "pass" and row[5] == "qa-2" and row[3].strip("`") == "commit:5d7a1e4" for row in qa_rows)
            check("qa_second_attempt_passed", second and covered == set(numbers) and bool(numbers), f"{len(qa_rows)} active QA row(s) cite {len(covered)} of {len(numbers)} criteria; all passing on qa-2: {second}")
            pending = len(release_rows) == 1 and release_rows[0][3:5] == ["release-1", "pending"] and release_rows[0][2].strip("`") == "commit:5d7a1e4"
            check("release_row_pending", pending, "the Release table has one pending row for release-1" if pending else f"Release rows: {release_rows}")
        elif step.id == "release-done":
            first_failed = first_record is not None and first_record.front.get("outcome") == "failed" and "BUG-001" in first_record.front_list("bugs")
            check("release_record_failed", first_failed and second_record is None, "REL-001 is the failed attempt and names BUG-001; there is no second record" if first_failed else "no failed record REL-001")
            row = release_rows[0] if len(release_rows) == 1 else []
            check("release_row_failed", row[3:6] == ["release-1", "failed", "[REL-001](../releases/REL-001.md)"] if row else False, f"Release rows: {release_rows}")
            check("bug_still_verified", bug_is("verified", "release") and any(item[4] == "failed" for item in bug_rows("Release")), f"BUG-001 is {bug.front.get('status') if bug else 'missing'}")
        elif step.id == "release-retry":
            retried = second_record is not None and second_record.front.get("outcome") == "released" and second_record.front.get("retry-of") == "REL-001"
            check("release_record_retry", retried, "REL-002 is released and retries REL-001" if retried else "no record REL-002 that retries REL-001")
            row = release_rows[0] if len(release_rows) == 1 else []
            check("release_row_released", row[3:6] == ["release-2", "released", "[REL-002](../releases/REL-002.md)"] if row else False, f"Release rows: {release_rows}")
            check("bug_released", bug_is("released", "none"), f"BUG-001 is {bug.front.get('status') if bug else 'missing'}")
            check("first_record_unchanged", first_record is not None and first_record.front.get("outcome") == "failed", "REL-001 still records the failed attempt")
        elif step.id == "ingest-incident":
            incident = ws.read_page(workspace, "incidents", ws.INCIDENT_ID)
            recorded = incident is not None and incident.front.get("status") == "open" and "REL-002" in incident.front_list("releases") and "backend" in incident.front_list("apps")
            check("incident_recorded", recorded, "INC-001 is open, names the backend app and REL-002" if recorded else "no open incident INC-001 for REL-002")
            check("incident_cause_unknown", incident is not None and incident.section("Cause").strip().startswith("**Unknown:**"), "the cause starts with Unknown")
            processed = workspace / "knowledge/intake/processed" / ws.PENDING_INPUTS[step.id][0]
            check("intake_moved", (processed / "MANIFEST.md").is_file() and not (workspace / ws.pending_folder(step.id)).exists(), "the pending folder moved to processed with a manifest")
            cells = ws.board_row_cells(workspace, "Operations", "backend")
            check("operations_lists_incident", bool(cells) and cells[-1] == ws.INCIDENT_ID, f"Operations row of backend: {cells}")
            bugs = list((workspace / "knowledge/wiki/bugs").glob("BUG-*.md"))
            check("no_other_page_created", len(bugs) == 1 and bug_is("released", "none"), f"{len(bugs)} bug page(s); BUG-001 is {bug.front.get('status') if bug else 'missing'}")
        elif step.id == "feature-reopen":
            check("evidence_archived", "## Evidence history" in feature.text and "reopen-dev" in page.section("Evidence history"), "the Evidence history names the reopen-dev entry")
            check("evidence_tables_empty", not delivery and not qa_rows and not release_rows, "the delivery, QA and Release tables hold no active row" if not (delivery or qa_rows or release_rows) else "an evidence table still holds rows")
            check("release_records_unchanged", first_record is not None and second_record is not None and second_record.front.get("outcome") == "released", "REL-001 and REL-002 are still in the releases folder")

    # -- teardown -----------------------------------------------------------------------------------

    def teardown(self) -> None:
        """Stop everything this run started, scan, write the report and delete the working folder.

        Each phase is guarded so that a second Ctrl+C, or one phase failing, does not skip the rest.
        """

        notes = self.cleanup_notes

        def phase(label: str, action) -> None:
            try:
                action()
            except BaseException as error:  # noqa: BLE001 - cleanup must reach every phase
                notes.append(f"{label}: {type(error).__name__} during cleanup")

        def stop_browser() -> None:
            if self.browser is not None:
                notes.append(f"browser {self.browser.close()}")

        def stop_board() -> None:
            if self.board is not None:
                notes.append(f"board {self.board.stop()}")

        def kill_leftovers() -> None:
            killed = kill_all_live()
            if killed:
                notes.append(f"killed {killed} leftover process(es)")

        phase("browser", stop_browser)
        phase("board", stop_board)
        phase("processes", kill_leftovers)
        phase("setup log", self.save_setup_log)
        self.run_info["elapsed_s"] = round(time.monotonic() - self.started, 1)
        self.run_info["finished"] = _now()
        # The report is written before the scan so the scan covers it too.
        self.run_info["cleanup"] = "; ".join(notes) + "; working folder pending"
        self.run_info.setdefault("token_scan", "pending")
        phase("report", self.write_report)
        phase("token scan", self.scan_for_tokens)
        phase("working folder", lambda: self.remove_work(notes))
        self.run_info["cleanup"] = "; ".join(notes)

    def scan_for_tokens(self) -> None:
        skip = [self.work / "venv", self.work / "wheelhouse", self.work / "wheel-src"]
        hits = self.tokens.scan_tree(self.out, skip=skip)
        for relative, _labels in hits:
            self.tokens.scrub_file(self.out / relative)
        if hits:
            names = ", ".join(f"{relative} ({', '.join(labels)})" for relative, labels in hits)
            self.run_info["token_scan"] = f"FAILED: a token was found in {names}; the files were redacted in place"
        else:
            self.run_info["token_scan"] = f"clean ({len(self.tokens.labels())} tokens checked in every saved file)"

    def remove_work(self, notes: list[str]) -> None:
        if self.options.keep_work:
            notes.append(f"working folder kept at {self.work}")
        else:
            error = ""
            for _attempt in range(10):
                try:
                    if self.work.exists():
                        shutil.rmtree(self.work)
                    error = ""
                    break
                except OSError as caught:
                    error = str(caught)
                    time.sleep(1.0)
            notes.append("working folder deleted" if not error else f"working folder NOT fully deleted: {error[:160]}")
        self.run_info["cleanup"] = "; ".join(notes)

    # -- report ---------------------------------------------------------------------------------------

    def rescan_report_files(self) -> None:
        for name in ("report.json", "report.md"):
            path = self.out / name
            if self.tokens.labels_in(path.read_bytes()):
                self.tokens.scrub_file(path)

    def write_report(self) -> None:
        report = reports.build_report(self.run_info, self.results, self.seeds, self.options.tier)
        (self.out / "report.json").write_text(reports.render_json(report, self.tokens.redact), encoding="utf-8", newline="\n")
        (self.out / "report.md").write_text(reports.render_markdown(report, self.tokens.redact), encoding="utf-8", newline="\n")


def vars_of(model: config.HostModel) -> dict[str, Any]:
    return {"model": model.model, "effort": model.effort}
