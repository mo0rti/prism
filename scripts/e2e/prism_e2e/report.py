"""Per-step results, totals and the report files. Pure data handling, no host or network access."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from typing import Any, Callable

USAGE_KEYS = ("input_tokens", "cached_input_tokens", "cache_creation_tokens", "output_tokens", "reasoning_tokens")


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class StepResult:
    step: str
    kind: str  # "agent" or "human"
    host: str  # "claude", "codex" or "browser"
    status: str = "pending"  # passed, failed or skipped
    reason: str | None = None  # why the step failed or was skipped
    expected_model: str | None = None
    expected_effort: str | None = None
    models: list[str] = field(default_factory=list)  # as recorded by the host
    efforts: list[str] = field(default_factory=list)  # as recorded by the host
    preview_attempts: int = 0
    preview_error_codes: list[str] = field(default_factory=list)
    other_error_codes: list[str] = field(default_factory=list)  # errors of every other tool
    first_attempt_success: bool | None = None
    preview_id: str | None = None
    operation_id: str | None = None
    apply_state: str | None = None  # receipt state
    applied_paths: list[str] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)
    elapsed_s: float = 0.0
    usage: dict[str, int] | None = None
    cost_usd: float | None = None
    notes: list[str] = field(default_factory=list)
    not_applicable: bool = False  # passed without launching a host: there was nothing for the step to do

    def fail(self, reason: str) -> None:
        self.status = "failed"
        self.reason = self.reason or reason

    def add_check(self, name: str, ok: bool, detail: str = "") -> bool:
        self.checks.append(Check(name, ok, detail))
        return ok

    def add_usage(self, usage: dict[str, int] | None, cost: float | None) -> None:
        if usage is not None:
            self.usage = {key: (self.usage or {}).get(key, 0) + usage.get(key, 0) for key in USAGE_KEYS}
        if cost is not None:
            self.cost_usd = (self.cost_usd or 0.0) + cost


def compute_totals(results: list[StepResult], tier: str) -> list[dict[str, Any]]:
    """One row per host for this tier: steps, outcomes, previews, time, tokens and cost where reported."""

    totals: dict[str, dict[str, Any]] = {}
    for result in results:
        row = totals.setdefault(
            result.host,
            {"tier": tier, "host": result.host, "steps": 0, "passed": 0, "failed": 0, "skipped": 0, "preview_attempts": 0,
             "first_attempt_successes": 0, "elapsed_s": 0.0, "usage": None, "cost_usd": None, "cost_reported": False},
        )
        row["steps"] += 1
        row[result.status if result.status in ("passed", "failed", "skipped") else "failed"] += 1
        row["preview_attempts"] += result.preview_attempts
        row["first_attempt_successes"] += 1 if result.first_attempt_success else 0
        row["elapsed_s"] = round(row["elapsed_s"] + result.elapsed_s, 1)
        if result.usage is not None:
            row["usage"] = {key: (row["usage"] or {}).get(key, 0) + result.usage.get(key, 0) for key in USAGE_KEYS}
        if result.cost_usd is not None:
            row["cost_usd"] = round((row["cost_usd"] or 0.0) + result.cost_usd, 4)
            row["cost_reported"] = True
    return [totals[host] for host in sorted(totals)]


def build_report(run: dict[str, Any], results: list[StepResult], seeds: list[dict[str, Any]], tier: str) -> dict[str, Any]:
    return {
        "run": run,
        "seeds": seeds,
        "steps": [asdict(result) for result in results],
        "totals": compute_totals(results, tier),
    }


def _cell(value: Any) -> str:
    text = "-" if value in (None, "", []) else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def _tokens(usage: dict[str, int] | None) -> str:
    if not usage:
        return "-"
    return f"{usage['input_tokens']:,} in / {usage['cached_input_tokens']:,} cached / {usage['output_tokens']:,} out"


def _cost(value: float | None, reported: bool = True) -> str:
    return f"${value:.4f}" if value is not None else "not reported"


def render_markdown(report: dict[str, Any], redact: Callable[[str], str] = lambda text: text) -> str:
    run = report["run"]
    lines = [
        f"# Journey report: {run['tier']} tier",
        "",
        f"- Verdict: **{run['verdict']}**" + (f" ({run['verdict_reason']})" if run.get("verdict_reason") else ""),
        f"- Steps selected: {', '.join(run['steps_selected'])}",
        f"- Fixtures: {run.get('fixtures', 'default')}",
        f"- Hosts: {', '.join(run['hosts'])}; timeout per host run: {run['timeout_s']} s",
        f"- Started {run['started']}, took {run['elapsed_s']} s",
        f"- Product: prism-kit {run.get('prism_version', '?')}; wheel `{run.get('wheel', '?')}` (SHA-256 `{run.get('wheel_sha256', '?')}`)",
        f"- Claude Code {run.get('claude_version') or 'not used'}" + (f" (`{run['claude_executable']}`)" if run.get("claude_executable") else "")
        + f"; Codex {run.get('codex_version') or 'not used'}" + (f" (`{run['codex_executable']}`)" if run.get("codex_executable") else "")
        + f"; Chromium {run.get('chromium_version') or 'not used'}",
        f"- Token scan of saved files: {run.get('token_scan', 'not run')}",
        f"- Cleanup: {run.get('cleanup', 'not run')}",
        "",
        "## Steps",
        "",
        "| # | Step | Host | Model (recorded) | Effort (recorded) | Result | Previews | First attempt | Preview errors | Apply | Elapsed s | Tokens | Cost |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for index, step in enumerate(report["steps"], start=1):
        skipped = step["status"] == "skipped"
        agent = step["kind"] == "agent"
        first = {True: "yes", False: "no", None: "-"}[step["first_attempt_success"]]
        effort = ", ".join(step["efforts"]) or ("none set" if agent and not skipped and not step["expected_effort"] else None)
        lines.append(
            "| " + " | ".join(
                _cell(value)
                for value in (
                    index,
                    step["step"],
                    step["host"],
                    ", ".join(step["models"]) or None,
                    effort,
                    step["status"] + (f" ({step['reason']})" if step["reason"] else ""),
                    "n/a" if not agent else (None if skipped else step["preview_attempts"]),
                    "n/a" if not agent else (None if skipped else first),
                    ", ".join(step["preview_error_codes"]) or None,
                    step["apply_state"],
                    None if skipped else step["elapsed_s"],
                    _tokens(step["usage"]),
                    "n/a" if not agent else (None if skipped else _cost(step["cost_usd"])),
                )
            ) + " |"
        )
    failed = [step for step in report["steps"] if step["status"] != "passed"]
    if failed:
        lines += ["", "## Failed and skipped steps", ""]
        for step in failed:
            lines.append(f"- **{step['step']}** ({step['status']}): {step['reason'] or 'no reason recorded'}")
            for check in step["checks"]:
                if not check["ok"]:
                    lines.append(f"  - check `{check['name']}` failed: {check['detail']}")
            for note in step["notes"]:
                lines.append(f"  - {note}")
    notes = [(step["step"], note) for step in report["steps"] if step["status"] == "passed" for note in step["notes"]]
    if notes:
        lines += ["", "## Notes", ""]
        lines += [f"- {name}: {note}" for name, note in notes]
    if report["seeds"]:
        lines += ["", "## Seeded state", ""]
        for seed in report["seeds"]:
            through = seed["through"] or "baseline"
            lines.append(f"- State after `{through}` from the recorded fixtures: {len(seed['files'])} file(s); lint errors {seed['lint_errors']}.")
    lines += [
        "",
        "## Totals",
        "",
        "| Tier | Host | Steps | Passed | Failed | Skipped | Previews | First-attempt successes | Elapsed s | Tokens | Cost |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in report["totals"]:
        cost = _cost(row["cost_usd"]) if row["host"] != "browser" else "n/a"
        lines.append(
            "| " + " | ".join(
                _cell(value)
                for value in (row["tier"], row["host"], row["steps"], row["passed"], row["failed"], row["skipped"], row["preview_attempts"],
                              row["first_attempt_successes"], row["elapsed_s"], _tokens(row["usage"]), cost)
            ) + " |"
        )
    lines += [
        "",
        "Tokens are the host's own report: Claude Code's `result` event (cache reads and writes are separate counts) and Codex's `turn.completed` usage "
        "(its input count includes the cached input). Claude Code reports a cost; Codex does not, so its cost is not reported.",
        "",
    ]
    return redact("\n".join(lines))


def render_json(report: dict[str, Any], redact: Callable[[str], str] = lambda text: text) -> str:
    return redact(json.dumps(report, indent=2, ensure_ascii=False)) + "\n"
