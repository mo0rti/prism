"""The evaluation harness: the example case passes with the fake provider, and a failing case is reported as failing."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from app.providers.base import Provider
from app.providers.fake import FakeProvider
from evals.run import CASES_DIR, CaseError, Expectation, load_cases, main, parse_case, report, run_all, run_case


@pytest.mark.anyio
async def test_every_case_passes_with_the_fake_provider() -> None:
    cases = load_cases()
    assert [case.id for case in cases] == ["profile-question"]

    results = await run_all(cases, FakeProvider())

    assert [(result.case_id, result.failures) for result in results] == [("profile-question", [])]
    assert results[0].tool_calls == ["get_my_profile"]
    assert results[0].usage.total > 0


@pytest.mark.anyio
async def test_a_case_whose_expectations_are_not_met_fails_and_says_why() -> None:
    (case,) = load_cases()
    strict = replace(
        case,
        expect=Expectation(tool_calls=[], answer_contains=["a fact the answer lacks"], answer_excludes=["Ada Example"]),
    )

    result = await run_case(strict, FakeProvider())

    assert not result.passed
    assert any("tool calls were ['get_my_profile'], expected []" in failure for failure in result.failures)
    assert any("lacks 'a fact the answer lacks'" in failure for failure in result.failures)
    assert any("contains 'Ada Example'" in failure for failure in result.failures)


@pytest.mark.anyio
async def test_a_wrong_token_makes_the_mocked_backend_refuse_and_the_case_fails() -> None:
    (case,) = load_cases()

    class WrongToken(FakeProvider):
        pass

    result = await run_case(replace(case, token="the-case-token", subject="dev:x"), FakeProvider())
    assert result.passed, "the tool sends the caller's token, which is the case's token"
    backend_refusal = await run_case(replace(case, backend_status=401), FakeProvider())
    assert not backend_refusal.passed


def test_the_command_line_runs_the_cases_and_reports_tokens(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["--provider", "fake"])
    out = capsys.readouterr().out

    assert code == 0
    assert "PASS  profile-question" in out and "1/1 passed" in out and "tokens in/out" in out


def test_the_claude_run_is_on_demand_and_needs_a_key(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--provider", "claude"]) == 2
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err
    assert main(["--case", "no-such-case"]) == 2


def test_the_report_records_the_cost_of_a_run_when_prices_are_given() -> None:
    from app.providers.base import Usage
    from evals.run import CaseResult

    results = [CaseResult("a", [], Usage(1000, 500), []), CaseResult("b", ["broken"], Usage(1000, 500), [])]
    text = report(results, "claude", 2.0, 10.0)

    assert "FAIL  b" in text and "- broken" in text and "1/2 passed" in text
    assert "cost of this run: $0.0140" in text
    assert "pass --input-price" in report(results, "claude", None, None)


def test_a_case_file_must_follow_the_format(tmp_path: Path) -> None:
    good = {"id": "x", "question": "q?", "expect": {"tool_calls": []}}
    assert parse_case(good).id == "x"
    for bad in (
        {**good, "unknown": 1},
        {"question": "q", "expect": {"tool_calls": []}},
        {"id": "x", "expect": {"tool_calls": []}},
        {"id": "x", "question": "q"},
        {**good, "expect": {"answer_contains": "not a list"}},
        {**good, "expect": {"nonsense": []}},
    ):
        with pytest.raises(CaseError):
            parse_case(bad)
    (tmp_path / "a.toml").write_text('id = "dup"\nquestion = "q"\n[expect]\ntool_calls = []\n', encoding="utf-8")
    (tmp_path / "b.toml").write_text('id = "dup"\nquestion = "q"\n[expect]\ntool_calls = []\n', encoding="utf-8")
    with pytest.raises(CaseError, match="share an id"):
        load_cases(tmp_path)
    assert CASES_DIR.is_dir()


def test_the_fake_provider_satisfies_the_provider_interface() -> None:
    provider: Provider = FakeProvider()
    assert provider.name == "fake"
