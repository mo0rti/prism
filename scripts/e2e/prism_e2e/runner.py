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

from . import config, report as reports, workspace as ws
from .browser import BrowserUnavailable
from .browser_client import BrowserClient
from .config import Step
from .hosts import HostRun, run_host
from .procs import clean_env, find_claude, find_codex, kill_all_live, run_captured
from .tokens import TokenRegistry
from .transcripts import collapse_models, first_reported_preview_id, model_matches

PREVIEW_NAMES = ("preview_skill", "preview_transition")


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
        if "po-intake" in options.steps:
            ws.place_pending_brief(self.env.workspace, self.options.fixtures)
        ws.issue_grant(self.env, self.tokens, "human", "Product owner (human)", "human", self.setup_log)
        ws.issue_grant(self.env, self.tokens, "claude", "Claude Code agent", "agent", self.setup_log)
        ws.issue_grant(self.env, self.tokens, "codex", "Codex agent", "agent", self.setup_log)
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
            if step.kind == "agent" and result.first_attempt_success is None:
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
        runs: list[HostRun] = []

        preview = self._launch(host, "preview", load_prompt(step.id, self.options.fixtures), number, step, result, runs)
        transcript = preview.transcript
        preview_calls = transcript.preview_calls
        result.preview_attempts = len(preview_calls)
        result.preview_error_codes = [call.error_code or "error" for call in preview_calls if not call.ok]
        result.other_error_codes = [call.error_code or "error" for call in transcript.calls if not call.ok and call.name not in PREVIEW_NAMES]
        first_ok = bool(preview_calls) and preview_calls[0].ok
        if not preview.exit_ok:
            result.fail("host timed out" if preview.result.timed_out else f"host exit {preview.result.exit_code}")
            return
        if transcript.calls_named("apply"):
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
        self._check_state(step, result, before, operation_id, receipt_token=self.tokens.get("human"))
        result.first_attempt_success = first_ok and all(check.ok for check in result.checks)
        if all(check.ok for check in result.checks):
            result.status = "passed"
        else:
            result.fail("check failed: " + ", ".join(check.name for check in result.checks if not check.ok))

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
        assert self.env is not None and self.board is not None
        if self.browser is None:
            client = BrowserClient(self.board.base_url, self.tokens.get("human"), self.logs / "browser-worker.err")
            client.start()
            self.browser = client
            self.run_info["chromium_version"] = client.version
        before = ws.read_feature(self.env.workspace)
        try:
            outcome = self.browser.perform(step.id, config.FEATURE_ID, self.env.workspace, self.out / "screenshots")
        except Exception:
            self.browser.failure_screenshot(self.out / "screenshots" / f"{number:02d}-{step.id}-failed.png")
            self.browser.recover()
            raise
        result.elapsed_s = outcome["elapsed_s"]
        result.operation_id = outcome["operation_id"]
        record = {
            "step": step.id,
            "operation_id": outcome["operation_id"],
            "preview_text": outcome["preview_text"],
            "applied_text": outcome["applied_text"],
            "writes": outcome["writes"],
            "stages": outcome["stages"],
        }
        (self.transcripts / f"{number:02d}-{step.id}.human.json").write_text(
            self.tokens.redact(json.dumps(record, indent=2, ensure_ascii=False)) + "\n", encoding="utf-8", newline="\n"
        )
        self._check_state(step, result, before, outcome["operation_id"], receipt_token=self.tokens.get("human"))
        if all(check.ok for check in result.checks):
            result.status = "passed"
        else:
            result.fail("check failed: " + ", ".join(check.name for check in result.checks if not check.ok))

    # -- checks after an apply ------------------------------------------------------------------

    def _check_state(self, step: Step, result: reports.StepResult, before: ws.FeatureState | None, operation_id: str, *, receipt_token: str) -> None:
        assert self.env is not None and self.board is not None
        receipt = ws.fetch_receipt(self.board, receipt_token, operation_id)
        state = receipt.get("state")
        result.apply_state = state or receipt.get("error")
        inner = receipt.get("receipt") or {}
        result.applied_paths = list(inner.get("applied_paths") or [])
        result.add_check("receipt_applied", state == "applied", f"receipt state {result.apply_state}")

        feature = ws.read_feature(self.env.workspace)
        found = (feature.status, feature.owner) if feature else None
        result.add_check(
            "stage_and_owner",
            found == (step.status, step.owner),
            f"expected {step.status}/{step.owner}, found {'/'.join(found) if found else 'no feature page'}",
        )
        if feature is not None:
            result.add_check(
                "index_matches_page",
                (feature.index_status, feature.index_owner) == (feature.status, feature.owner),
                f"index row {feature.index_status}/{feature.index_owner}, page {feature.status}/{feature.owner}",
            )
        lint = ws.run_lint(self.env)
        allowed = ws.ALLOWED_LINT_CODES.get(step.id, frozenset())
        result.add_check(
            "lint_no_errors",
            not lint.unexpected(allowed),
            f"{lint.errors} error(s)" + (f" ({', '.join(lint.error_codes)})" if lint.error_codes else "") + (f", {len(allowed)} code(s) expected after this step" if allowed else ""),
        )
        self._step_specific_checks(step, result, before, feature)

    def _step_specific_checks(self, step: Step, result: reports.StepResult, before: ws.FeatureState | None, feature: ws.FeatureState | None) -> None:
        assert self.env is not None
        if feature is None:
            return
        if step.id == "po-intake":
            result.add_check("intake_moved", (self.env.workspace / "knowledge/intake/processed/review-summary").is_dir() and not (self.env.workspace / ws.PENDING_INTAKE).exists(), "the pending folder moved to processed")
            owners = {owner: sum(1 for question in feature.questions if question.owner == owner) for owner in ("po", "designer", "dev")}
            if not owners["designer"] or not owners["dev"]:
                result.notes.append(
                    "the intake routed questions to " + ", ".join(f"{owner} {count}" for owner, count in owners.items())
                    + "; the later design-clarify and dev-clarify steps answer a designer and a developer question"
                )
        elif step.id == "ask":
            grown = before is not None and len(feature.questions) == len(before.questions) + 1
            result.add_check("one_question_added", grown, f"{len(before.questions) if before else '?'} -> {len(feature.questions)} question rows")
            newest = feature.questions[-1] if feature.questions else None
            result.add_check("question_routed_to_po", bool(newest and newest.owner == "po" and newest.is_open), f"newest row owner {newest.owner if newest else 'none'}")
        elif step.id == "po-clarify":
            result.add_check("no_open_po_questions", not feature.open_questions("po"), f"{len(feature.open_questions('po'))} open")
        elif step.id == "design-clarify":
            result.add_check("no_open_designer_questions", not feature.open_questions("designer"), f"{len(feature.open_questions('designer'))} open")
        elif step.id == "dev-clarify":
            result.add_check("no_open_dev_questions", not feature.open_questions("dev"), f"{len(feature.open_questions('dev'))} open")
        elif step.id == "design-handoff":
            if ws.declares_api_work(feature.text):
                contract = ws.read_api_contract(self.env.workspace)
                result.add_check(
                    "api_contract_agreed",
                    bool(contract) and contract.get("feature-id") == config.FEATURE_ID and contract.get("status") == "agreed",
                    f"API contract page {contract.get('status') if contract else 'missing'}",
                )
                requirement = self.env.workspace / ws.REQUIREMENT
                linked = requirement.is_file() and "api-contracts/F-001" in requirement.read_text(encoding="utf-8")
                result.add_check("requirement_links_contract", linked, "the requirement page links the contract" if linked else "the requirement page does not link the contract")
        elif step.id == "dev-done":
            result.add_check("delivery_evidence_recorded", "## Delivery evidence" in feature.text and "3f9c2ab" in feature.text, "the evidence table names the commit")

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
