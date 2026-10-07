"""The Claude API adapter, through Anthropic's official Python SDK.

The model ID is a setting (`AGENT_CLAUDE_MODEL`) and the key comes from `ANTHROPIC_API_KEY`; neither is in a
file. Tests and CI never reach this class's network path: they use the fake provider, or a stub client.
This adapter is exercised only against a stub until you run it with your own key (`python -m evals.run
--provider claude`).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any, cast

import anthropic

from app.providers.base import (
    AssistantMessage,
    Message,
    ProviderError,
    ProviderReply,
    ToolCall,
    ToolResultMessage,
    ToolSpec,
    Usage,
    UserMessage,
)

logger = logging.getLogger("agent.provider")

REFUSED = "I cannot help with that request."
CUT_OFF = "My answer was cut off before it was complete. Try a narrower question."


class ClaudeProvider:
    name = "claude"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        max_tokens: int,
        client: Any | None = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        self._model = model
        self._max_tokens = max_tokens
        # The SDK retries connection errors, 408, 409, 429 and 5xx twice by default.
        self._client: Any = client or anthropic.AsyncAnthropic(api_key=api_key, timeout=timeout_seconds)

    def __repr__(self) -> str:
        return f"ClaudeProvider(model={self._model!r})"

    async def complete(self, *, system: str, messages: Sequence[Message], tools: Sequence[ToolSpec]) -> ProviderReply:
        request: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "system": system,
            "messages": to_api_messages(messages),
        }
        if tools:
            request["tools"] = [
                {"name": tool.name, "description": tool.description, "input_schema": tool.input_schema}
                for tool in tools
            ]
        try:
            response = await self._client.messages.create(**request)
        except anthropic.APIError as error:
            logger.warning("The Claude API request failed: %s", type(error).__name__)
            raise ProviderError(f"The Claude API request failed ({type(error).__name__})") from error
        return from_api_response(response)


def to_api_messages(messages: Sequence[Message]) -> list[dict[str, Any]]:
    """The transcript in the Messages API's shape. Consecutive tool results share one user message."""

    api: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []

    def flush() -> None:
        if pending:
            api.append({"role": "user", "content": list(pending)})
            pending.clear()

    for message in messages:
        if isinstance(message, ToolResultMessage):
            block: dict[str, Any] = {"type": "tool_result", "tool_use_id": message.call_id, "content": message.content}
            if message.is_error:
                block["is_error"] = True
            pending.append(block)
            continue
        flush()
        if isinstance(message, UserMessage):
            api.append({"role": "user", "content": message.content})
        elif isinstance(message, AssistantMessage):
            if message.provider_state is not None:
                # The blocks exactly as the model produced them, including any thinking blocks a tool turn must echo.
                api.append({"role": "assistant", "content": message.provider_state})
            else:
                blocks: list[dict[str, Any]] = []
                if message.text:
                    blocks.append({"type": "text", "text": message.text})
                blocks.extend(
                    {"type": "tool_use", "id": call.id, "name": call.name, "input": call.arguments}
                    for call in message.tool_calls
                )
                api.append({"role": "assistant", "content": blocks})
    flush()
    return api


def from_api_response(response: Any) -> ProviderReply:
    """Text, tool calls and usage from a Messages API response."""

    text_parts: list[str] = []
    calls: list[ToolCall] = []
    for block in response.content:
        if block.type == "text":
            text_parts.append(block.text)
        elif block.type == "tool_use":
            arguments = block.input if isinstance(block.input, dict) else {}
            calls.append(ToolCall(id=block.id, name=block.name, arguments=cast("dict[str, Any]", arguments)))
    usage = Usage(
        input_tokens=int(getattr(response.usage, "input_tokens", 0) or 0),
        output_tokens=int(getattr(response.usage, "output_tokens", 0) or 0),
    )
    text = "".join(text_parts).strip()
    stop_reason = getattr(response, "stop_reason", None)
    if stop_reason == "refusal":
        return ProviderReply(text=REFUSED, usage=usage)
    if stop_reason == "max_tokens" and not calls:
        text = f"{text}\n\n{CUT_OFF}".strip()
    return ProviderReply(text=text, tool_calls=tuple(calls), usage=usage, provider_state=list(response.content))
