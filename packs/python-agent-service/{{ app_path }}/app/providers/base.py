"""The provider interface: one model call, in terms that belong to no vendor.

An agent turn is a short transcript of messages and a set of tools. A provider turns one call into a reply:
text, tool calls and token usage. The turn logic (`app/agent/turn.py`) never imports a vendor SDK, so a second
real provider is one more class behind this interface.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol


class ProviderError(Exception):
    """The model provider failed. The message is safe to log; the response to the caller is generic."""


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens

    def __add__(self, other: Usage) -> Usage:
        return Usage(self.input_tokens + other.input_tokens, self.output_tokens + other.output_tokens)


@dataclass(frozen=True)
class UserMessage:
    """`content` is an untrusted-data envelope holding the user's question."""

    content: str


@dataclass(frozen=True)
class AssistantMessage:
    """What the model said and asked for. `provider_state` is opaque: the provider that made it replays it as is."""

    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    provider_state: Any = None


@dataclass(frozen=True)
class ToolResultMessage:
    """`content` is an untrusted-data envelope holding the tool's result."""

    call_id: str
    name: str
    content: str
    is_error: bool = False


Message = UserMessage | AssistantMessage | ToolResultMessage


@dataclass(frozen=True)
class ProviderReply:
    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    usage: Usage = Usage()
    provider_state: Any = None


class Provider(Protocol):
    name: str

    async def complete(self, *, system: str, messages: Sequence[Message], tools: Sequence[ToolSpec]) -> ProviderReply:
        """One model call. `system` holds the service's own instructions and nothing a user or a tool supplied."""
        ...
