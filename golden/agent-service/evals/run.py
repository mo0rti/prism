"""The evaluation harness: fixed cases, run through the agent turn, reported per run.

    python -m evals.run                      # every case with the fake provider (what CI runs)
    python -m evals.run --case profile-question
    python -m evals.run --provider claude    # on demand: calls the live API with your ANTHROPIC_API_KEY and costs money

Each case in `evals/cases/*.toml` names a question, what a mocked backend answers and what the answer must and
must not contain. The backend is always mocked, so a run never reads real data. The report lists the model
tokens used per case and in total, and the cost when you pass `--input-price` and `--output-price`
(USD per million tokens). The exit code is 0 only when every case passes.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from app.agent.turn import run_turn
from app.auth.caller import Caller
from app.config import ConfigurationError, Settings
from app.providers.base import Provider, Usage
from app.providers.factory import build_provider
from app.safety.audit import AuditLog
from app.tools.backend_profile import GetMyProfile
from app.tools.base import ToolContext
from app.tools.registry import ToolRegistry

CASES_DIR = Path(__file__).parent / "cases"
BACKEND_URL = "http://backend.invalid"
CASE_KEYS = {"id", "description", "question", "user", "backend", "expect"}
EXPECT_KEYS = {"tool_calls", "answer_contains", "answer_excludes"}


class CaseError(ValueError):
    """A case file that does not follow the format."""


@dataclass(frozen=True)
class Expectation:
    tool_calls: list[str] = field(default_factory=list)
    answer_contains: list[str] = field(default_factory=list)
    answer_excludes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class EvalCase:
    id: str
    description: str
    question: str
    subject: str
    token: str
    backend_status: int
    backend_body: dict[str, Any]
    expect: Expectation


@dataclass
class CaseResult:
    case_id: str
    failures: list[str]
    usage: Usage
    tool_calls: list[str]

    @property
    def passed(self) -> bool:
        return not self.failures


def _strings(value: Any, name: str, case_id: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise CaseError(f"{case_id}: `{name}` must be a list of strings")
    return list(value)


def parse_case(data: dict[str, Any], source: str = "case") -> EvalCase:
    unknown = set(data) - CASE_KEYS
    if unknown:
        raise CaseError(f"{source}: unknown keys {sorted(unknown)}")
    case_id = data.get("id")
    if not isinstance(case_id, str) or not case_id:
        raise CaseError(f"{source}: `id` is required")
    question = data.get("question")
    if not isinstance(question, str) or not question.strip():
        raise CaseError(f"{case_id}: `question` is required")
    user = data.get("user") or {}
    backend = data.get("backend") or {}
    expect = data.get("expect") or {}
    unknown = set(expect) - EXPECT_KEYS
    if unknown:
        raise CaseError(f"{case_id}: unknown `expect` keys {sorted(unknown)}")
    if not expect:
        raise CaseError(f"{case_id}: `expect` must state at least one expectation")
    return EvalCase(
        id=case_id,
        description=str(data.get("description", "")),
        question=question,
        subject=str(user.get("subject", "dev:eval@example.test")),
        token=str(user.get("token", "eval-token")),
        backend_status=int(backend.get("status", 200)),
        backend_body=dict(backend.get("body", {})),
        expect=Expectation(
            tool_calls=_strings(expect.get("tool_calls", []), "expect.tool_calls", case_id),
            answer_contains=_strings(expect.get("answer_contains", []), "expect.answer_contains", case_id),
            answer_excludes=_strings(expect.get("answer_excludes", []), "expect.answer_excludes", case_id),
        ),
    )


def load_cases(directory: Path = CASES_DIR) -> list[EvalCase]:
    cases = [
        parse_case(tomllib.loads(path.read_text(encoding="utf-8")), path.name)
        for path in sorted(directory.glob("*.toml"))
    ]
    ids = [case.id for case in cases]
    if len(ids) != len(set(ids)):
        raise CaseError("Two cases share an id")
    return cases


def mock_backend(case: EvalCase) -> httpx.AsyncClient:
    """The backend of a case: it answers GET /api/me with the case's body, and only for the case's token."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/me" and request.headers.get("Authorization") == f"Bearer {case.token}":
            return httpx.Response(case.backend_status, json=case.backend_body)
        return httpx.Response(401, json={"code": "UNAUTHORIZED", "message": "Authentication required"})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=BACKEND_URL)


async def run_case(case: EvalCase, provider: Provider) -> CaseResult:
    caller = Caller(subject=case.subject, issuer="eval", token=case.token)
    async with mock_backend(case) as backend:
        result = await run_turn(
            question=case.question,
            provider=provider,
            tools=ToolRegistry([GetMyProfile()]),
            context=ToolContext(caller=caller, request_id=f"eval-{case.id}", backend=backend),
            audit=AuditLog(lambda _record: None),
            max_tool_calls=4,
        )
    called = [call.name for call in result.tool_calls]
    answer = result.answer.lower()
    failures: list[str] = []
    if called != case.expect.tool_calls:
        failures.append(f"tool calls were {called}, expected {case.expect.tool_calls}")
    failures.extend(f"the answer lacks {text!r}" for text in case.expect.answer_contains if text.lower() not in answer)
    failures.extend(f"the answer contains {text!r}" for text in case.expect.answer_excludes if text.lower() in answer)
    return CaseResult(case.id, failures, result.usage, called)


async def run_all(cases: Sequence[EvalCase], provider: Provider) -> list[CaseResult]:
    return [await run_case(case, provider) for case in cases]


def report(
    results: Sequence[CaseResult], provider_name: str, input_price: float | None, output_price: float | None
) -> str:
    lines = [f"Evaluation run with the {provider_name} provider: {len(results)} case(s)"]
    for result in results:
        lines.append(
            f"  {'PASS' if result.passed else 'FAIL'}  {result.case_id}  tokens in/out {result.usage.input_tokens}/{result.usage.output_tokens}"
        )
        lines.extend(f"        - {failure}" for failure in result.failures)
    total = sum((result.usage for result in results), Usage())
    passed = sum(1 for result in results if result.passed)
    lines.append(f"{passed}/{len(results)} passed; tokens in/out {total.input_tokens}/{total.output_tokens}")
    if input_price is not None and output_price is not None:
        cost = (total.input_tokens * input_price + total.output_tokens * output_price) / 1_000_000
        lines.append(f"cost of this run: ${cost:.4f} at ${input_price}/${output_price} per million input/output tokens")
    elif provider_name != "fake":
        lines.append("pass --input-price and --output-price (USD per million tokens) to record the cost of this run")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the evaluation cases through the agent turn.")
    parser.add_argument("--provider", choices=["fake", "claude"], default="fake")
    parser.add_argument("--case", help="Run one case by id")
    parser.add_argument("--input-price", type=float, help="USD per million input tokens")
    parser.add_argument("--output-price", type=float, help="USD per million output tokens")
    args = parser.parse_args(argv)

    cases = load_cases()
    if args.case:
        cases = [case for case in cases if case.id == args.case]
        if not cases:
            print(f"No case has the id {args.case!r}.", file=sys.stderr)
            return 2
    if not cases:
        print("No evaluation cases found in evals/cases/.", file=sys.stderr)
        return 2
    try:
        provider = build_provider(Settings(provider=args.provider))
    except ConfigurationError as error:
        print(error, file=sys.stderr)
        return 2
    if args.provider != "fake":
        print("This run calls the live model API and costs money.", file=sys.stderr)
    results = asyncio.run(run_all(cases, provider))
    print(report(results, provider.name, args.input_price, args.output_price))
    return 0 if all(result.passed for result in results) else 1


if __name__ == "__main__":
    sys.exit(main())
