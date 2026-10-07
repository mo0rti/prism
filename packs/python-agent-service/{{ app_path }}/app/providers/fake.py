"""The deterministic provider: no network, no key, the same answer for the same transcript.

It stands in for a model in tests, in the evaluation run of CI and in local runs without a key. It follows the
same rules a model is asked to follow: it reads the question and the tool results as data, calls a tool when
the question needs the user's profile, and answers only from what the tool returned.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.providers.base import (
    AssistantMessage,
    Message,
    ProviderReply,
    ToolCall,
    ToolResultMessage,
    ToolSpec,
    Usage,
    UserMessage,
)
from app.safety.untrusted import unwrap

PROFILE_TOOL = "get_my_profile"
_PROFILE_QUESTION = re.compile(
    r"\b(who am i|who i am|my (profile|account|name|email|details)|signed in as|am i signed in)\b", re.IGNORECASE
)
NOT_UNDERSTOOD = "I can answer questions about the account you are signed in with, for example: who am I signed in as?"
PROFILE_UNAVAILABLE = "I could not read your profile just now, so I cannot answer that."


@dataclass(frozen=True)
class RecordedRequest:
    """What one `complete` call received, kept so tests can assert exactly what a model would have seen."""

    system: str
    messages: tuple[Message, ...]
    tool_names: tuple[str, ...]


def _estimate_tokens(*parts: str) -> int:
    return max(1, sum(len(part) for part in parts) // 4)


class FakeProvider:
    name = "fake"

    def __init__(self) -> None:
        self.requests: list[RecordedRequest] = []

    async def complete(self, *, system: str, messages: Sequence[Message], tools: Sequence[ToolSpec]) -> ProviderReply:
        self.requests.append(RecordedRequest(system, tuple(messages), tuple(tool.name for tool in tools)))
        input_tokens = _estimate_tokens(system, *(_text_of(message) for message in messages))
        text, calls = self._decide(messages, {tool.name for tool in tools})
        usage = Usage(input_tokens=input_tokens, output_tokens=_estimate_tokens(text, *(call.name for call in calls)))
        return ProviderReply(text=text, tool_calls=calls, usage=usage)

    def _decide(self, messages: Sequence[Message], tool_names: set[str]) -> tuple[str, tuple[ToolCall, ...]]:
        question = _question(messages)
        results = [message for message in messages if isinstance(message, ToolResultMessage)]
        if not results:
            if _PROFILE_QUESTION.search(question) and PROFILE_TOOL in tool_names:
                return "", (ToolCall(id="call_1", name=PROFILE_TOOL, arguments={}),)
            return NOT_UNDERSTOOD, ()
        return _answer_from(results[-1]), ()


def _question(messages: Sequence[Message]) -> str:
    for message in messages:
        if isinstance(message, UserMessage):
            _kind, value = unwrap(message.content)
            return value if isinstance(value, str) else ""
    return ""


def _answer_from(result: ToolResultMessage) -> str:
    _kind, payload = unwrap(result.content)
    if not isinstance(payload, dict) or not payload.get("ok") or result.name != PROFILE_TOOL:
        return PROFILE_UNAVAILABLE
    profile: dict[str, Any] = payload.get("result") or {}
    name = profile.get("displayName")
    if not isinstance(name, str):
        return PROFILE_UNAVAILABLE
    email = profile.get("email")
    who = f"{name} ({email})" if isinstance(email, str) else name
    since = profile.get("createdAt")
    suffix = f" Your profile was created {since}." if isinstance(since, str) else ""
    return f"You are signed in as {who}.{suffix}"


def _text_of(message: Message) -> str:
    if isinstance(message, AssistantMessage):
        return message.text
    return message.content
