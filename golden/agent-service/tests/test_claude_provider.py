"""The Claude adapter, against a stub client: tests and CI never call the live API.

The stub records the request the adapter would send and returns objects shaped like the SDK's response, so these
tests pin the translation (messages, tools, tool results, usage, errors) and the configuration (model ID, key).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import anthropic
import httpx
import pytest

from app.config import DEFAULT_CLAUDE_MODEL, Settings
from app.providers.base import AssistantMessage, ProviderError, ToolCall, ToolResultMessage, ToolSpec, UserMessage
from app.providers.claude import REFUSED, ClaudeProvider, to_api_messages
from app.providers.factory import build_provider
from app.safety.untrusted import as_data


def text_block(text: str) -> Any:
    return SimpleNamespace(type="text", text=text)


def tool_block(call_id: str, name: str, arguments: dict[str, Any]) -> Any:
    return SimpleNamespace(type="tool_use", id=call_id, name=name, input=arguments)


def response(*blocks: Any, stop_reason: str = "end_turn", input_tokens: int = 11, output_tokens: int = 7) -> Any:
    return SimpleNamespace(
        content=list(blocks),
        stop_reason=stop_reason,
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )


class StubClient:
    def __init__(self, reply: Any = None, error: Exception | None = None) -> None:
        self.requests: list[dict[str, Any]] = []
        self.reply = reply
        self.error = error
        self.messages = self

    async def create(self, **request: Any) -> Any:
        self.requests.append(request)
        if self.error:
            raise self.error
        return self.reply


SPEC = ToolSpec(
    name="get_my_profile", description="Read the profile.", input_schema={"type": "object", "properties": {}}
)


def provider(client: StubClient, **overrides: Any) -> ClaudeProvider:
    return ClaudeProvider(
        api_key="sk-ant-test", model=overrides.get("model", DEFAULT_CLAUDE_MODEL), max_tokens=512, client=client
    )


@pytest.mark.anyio
async def test_the_request_carries_the_configured_model_the_system_prompt_the_data_envelopes_and_the_tools() -> None:
    client = StubClient(response(text_block("You are Ada.")))
    reply = await provider(client).complete(
        system="SYSTEM", messages=[UserMessage(as_data("user_question", "Who am I?"))], tools=[SPEC]
    )

    (request,) = client.requests
    assert request["model"] == "claude-sonnet-5-5"
    assert request["max_tokens"] == 512
    assert request["system"] == "SYSTEM"
    assert request["messages"] == [{"role": "user", "content": as_data("user_question", "Who am I?")}]
    assert request["tools"] == [
        {"name": "get_my_profile", "description": "Read the profile.", "input_schema": SPEC.input_schema}
    ]
    assert "temperature" not in request and "tool_choice" not in request, "no sampling parameter and no forced tool use"
    assert (reply.text, reply.tool_calls) == ("You are Ada.", ())
    assert (reply.usage.input_tokens, reply.usage.output_tokens) == (11, 7)


@pytest.mark.anyio
async def test_the_model_id_is_configurable() -> None:
    client = StubClient(response(text_block("ok")))
    await provider(client, model="claude-another-model").complete(system="S", messages=[UserMessage("q")], tools=[])

    assert client.requests[0]["model"] == "claude-another-model"
    assert "tools" not in client.requests[0], "no tools, no tools parameter"


@pytest.mark.anyio
async def test_a_tool_use_reply_becomes_tool_calls_and_keeps_the_provider_blocks_for_replay() -> None:
    blocks = [text_block("Let me check."), tool_block("toolu_1", "get_my_profile", {})]
    reply = await provider(StubClient(response(*blocks, stop_reason="tool_use"))).complete(
        system="S", messages=[UserMessage("q")], tools=[SPEC]
    )

    assert reply.tool_calls == (ToolCall(id="toolu_1", name="get_my_profile", arguments={}),)
    assert reply.text == "Let me check."
    assert reply.provider_state == blocks


def test_the_transcript_replays_the_models_own_blocks_and_batches_tool_results_in_one_user_message() -> None:
    blocks = [tool_block("t1", "a", {}), tool_block("t2", "b", {})]
    api = to_api_messages(
        [
            UserMessage("question"),
            AssistantMessage(
                text="", tool_calls=(ToolCall("t1", "a", {}), ToolCall("t2", "b", {})), provider_state=blocks
            ),
            ToolResultMessage(call_id="t1", name="a", content="r1"),
            ToolResultMessage(call_id="t2", name="b", content="r2", is_error=True),
        ]
    )

    assert api[0] == {"role": "user", "content": "question"}
    assert api[1] == {"role": "assistant", "content": blocks}
    assert api[2] == {
        "role": "user",
        "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "r1"},
            {"type": "tool_result", "tool_use_id": "t2", "content": "r2", "is_error": True},
        ],
    }
    assert len(api) == 3


def test_an_assistant_turn_without_provider_state_is_rebuilt_from_its_calls() -> None:
    api = to_api_messages([AssistantMessage(text="Checking.", tool_calls=(ToolCall("t1", "a", {"x": 1}),))])

    assert api == [
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Checking."},
                {"type": "tool_use", "id": "t1", "name": "a", "input": {"x": 1}},
            ],
        }
    ]


@pytest.mark.anyio
async def test_a_refusal_and_a_cut_off_answer_are_reported_in_plain_words() -> None:
    refused = await provider(StubClient(response(stop_reason="refusal"))).complete(
        system="S", messages=[UserMessage("q")], tools=[]
    )
    cut = await provider(StubClient(response(text_block("Partial"), stop_reason="max_tokens"))).complete(
        system="S", messages=[UserMessage("q")], tools=[]
    )

    assert refused.text == REFUSED
    assert cut.text.startswith("Partial") and "cut off" in cut.text


@pytest.mark.anyio
async def test_an_api_failure_is_a_provider_error_that_does_not_carry_the_providers_text() -> None:
    # The SDK builds on its own HTTP library; the exception only keeps the request it is given.
    request: Any = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    failure = anthropic.APIConnectionError(request=request)
    with pytest.raises(ProviderError) as raised:
        await provider(StubClient(error=failure)).complete(system="S", messages=[UserMessage("q")], tools=[])

    assert "APIConnectionError" in str(raised.value)
    assert "sk-ant" not in str(raised.value)


def test_the_default_model_is_sonnet_5_5_and_the_provider_never_shows_its_key() -> None:
    assert DEFAULT_CLAUDE_MODEL == "claude-sonnet-5-5"
    assert Settings().claude_model == "claude-sonnet-5-5"
    built = provider(StubClient())
    assert "sk-ant-test" not in repr(built) and "sk-ant-test" not in str(vars(built))


def test_the_factory_builds_the_claude_adapter_from_the_environment_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-from-env")
    monkeypatch.setenv("AGENT_CLAUDE_MODEL", "claude-custom")
    built = build_provider(Settings(provider="claude"))

    assert built.name == "claude"
    assert "claude-custom" in repr(built)
    assert "sk-ant-from-env" not in repr(built)
