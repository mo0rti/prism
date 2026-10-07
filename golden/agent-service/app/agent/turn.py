"""One agent turn: the question goes to the provider, the provider may call tools, and the answer comes back.

This is where the safety rules of a turn are enforced:
- the question and every tool result are passed as data, in envelopes, never into the system prompt;
- only registered tools run, with validated arguments, and a turn makes at most `max_tool_calls` calls;
- every tool call is logged with the user and request IDs, and never with a token or a value;
- a tool's failure is a result the model reads as data, not an exception that ends the turn;
- before each model call the turn reserves the most that call can cost from the user's token budget, and the
  usage of each completed call is recorded at once, so a turn that fails later still pays for what it used.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from app.agent.prompts import SYSTEM_PROMPT
from app.providers.base import (
    AssistantMessage,
    Message,
    Provider,
    ProviderReply,
    ToolCall,
    ToolResultMessage,
    ToolSpec,
    Usage,
    UserMessage,
)
from app.safety.audit import AuditLog
from app.safety.budget import TurnBudget
from app.safety.untrusted import as_data
from app.tools.base import ToolContext, ToolError
from app.tools.registry import ToolRegistry

logger = logging.getLogger("agent.turn")

MAX_RESULT_CHARS = 8000
OUT_OF_STEPS = "I could not finish that within the number of steps I am allowed. Try a narrower question."


@dataclass(frozen=True)
class ToolCallRecord:
    name: str
    ok: bool


@dataclass
class TurnResult:
    answer: str
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    usage: Usage = Usage()


def call_cost_bound(system: str, messages: Sequence[Message], tools: Sequence[ToolSpec], output_token_cap: int) -> int:
    """The most one model call can cost in tokens: its output cap plus an upper bound of its input.

    A token is at least one byte of text, so the bytes of everything sent bound the input tokens from above. The
    bound is generous on purpose: a reservation is replaced by the real usage when the call completes.
    """

    size = len(system.encode("utf-8")) + sum(len(repr(tool).encode("utf-8")) for tool in tools)
    size += sum(len(repr(message).encode("utf-8")) for message in messages)
    return size + output_token_cap


async def run_turn(
    *,
    question: str,
    provider: Provider,
    tools: ToolRegistry,
    context: ToolContext,
    audit: AuditLog,
    max_tool_calls: int,
    budget: TurnBudget,
    output_token_cap: int,
) -> TurnResult:
    messages: list[Message] = [UserMessage(as_data("user_question", question))]
    result = TurnResult(answer="")
    while True:
        specs = list(tools.specs())
        reservation = budget.reserve_call(call_cost_bound(SYSTEM_PROMPT, messages, specs, output_token_cap))
        try:
            reply: ProviderReply = await provider.complete(system=SYSTEM_PROMPT, messages=messages, tools=specs)
        except BaseException:
            # The call returned no usage: release what it held and charge nothing.
            reservation.cancel()
            raise
        reservation.settle(reply.usage.total)
        result.usage = result.usage + reply.usage
        if not reply.tool_calls:
            result.answer = reply.text.strip()
            return result
        if len(result.tool_calls) + len(reply.tool_calls) > max_tool_calls:
            result.answer = OUT_OF_STEPS
            return result
        messages.append(
            AssistantMessage(text=reply.text, tool_calls=reply.tool_calls, provider_state=reply.provider_state)
        )
        for call in reply.tool_calls:
            messages.append(await _run_tool(call, tools, context, audit, result))


async def _run_tool(
    call: ToolCall, tools: ToolRegistry, context: ToolContext, audit: AuditLog, turn: TurnResult
) -> ToolResultMessage:
    started = time.monotonic()
    outcome = "ok"
    payload: dict[str, Any]
    tool = tools.get(call.name)
    if tool is None:
        outcome = "unknown_tool"
        payload = {"tool": call.name, "ok": False, "error": "There is no such tool"}
    else:
        try:
            arguments = tool.Arguments.model_validate(call.arguments)
            payload = {"tool": call.name, "ok": True, "result": await tool.run(arguments, context)}
        except ValidationError as error:
            outcome = "invalid_arguments"
            fields = sorted({".".join(str(part) for part in item["loc"]) or "arguments" for item in error.errors()})
            payload = {"tool": call.name, "ok": False, "error": f"The arguments are not valid: {', '.join(fields)}"}
        except ToolError as error:
            outcome = "error"
            payload = {"tool": call.name, "ok": False, "error": str(error)}
        except Exception as error:
            # A tool's bug is not the model's concern, and its message may hold data. Log the type only.
            logger.error("Tool %s failed with %s", call.name, type(error).__name__)
            outcome = "error"
            payload = {"tool": call.name, "ok": False, "error": "The tool failed"}
    envelope = as_data("tool_result", payload)
    if len(envelope) > MAX_RESULT_CHARS:
        outcome = "error"
        payload = {"tool": call.name, "ok": False, "error": "The result is too large to use"}
        envelope = as_data("tool_result", payload)
    audit.tool_call(
        user_id=context.caller.user_id,
        request_id=context.request_id,
        tool=call.name,
        argument_names=list(call.arguments),
        outcome=outcome,
        duration_ms=int((time.monotonic() - started) * 1000),
    )
    turn.tool_calls.append(ToolCallRecord(name=call.name, ok=bool(payload["ok"])))
    return ToolResultMessage(call_id=call.id, name=call.name, content=envelope, is_error=not payload["ok"])
