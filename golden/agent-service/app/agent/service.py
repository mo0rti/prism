"""The assistant of one request: the budget, then the turn, then the accounting.

Everything per request lives here and in the objects it builds for the request. Nothing a user said or a
tool returned is kept on the service, so one user's data can never enter another user's request.
"""

from __future__ import annotations

import httpx

from app.agent.turn import ToolCallRecord, run_turn
from app.auth.caller import Caller
from app.providers.base import Provider, Usage
from app.safety.audit import AuditLog
from app.safety.budget import BudgetExceededError, UserBudget
from app.tools.base import ToolContext
from app.tools.registry import ToolRegistry


class AssistResult:
    def __init__(self, answer: str, tool_calls: list[ToolCallRecord], usage: Usage) -> None:
        self.answer = answer
        self.tool_calls = tool_calls
        self.usage = usage


class AssistantService:
    def __init__(
        self,
        *,
        provider: Provider,
        tools: ToolRegistry,
        backend: httpx.AsyncClient,
        budget: UserBudget,
        audit: AuditLog,
        max_tool_calls: int,
    ) -> None:
        self._provider = provider
        self._tools = tools
        self._backend = backend
        self._budget = budget
        self._audit = audit
        self._max_tool_calls = max_tool_calls

    async def answer(self, *, caller: Caller, question: str, request_id: str) -> AssistResult:
        """Run one turn for the caller. Raises `BudgetExceededError` before any model call when the budget is used up."""

        try:
            self._budget.reserve(caller.user_id)
        except BudgetExceededError as error:
            self._audit.budget_refused(user_id=caller.user_id, request_id=request_id, reason=error.reason)
            raise
        context = ToolContext(caller=caller, request_id=request_id, backend=self._backend)
        result = await run_turn(
            question=question,
            provider=self._provider,
            tools=self._tools,
            context=context,
            audit=self._audit,
            max_tool_calls=self._max_tool_calls,
        )
        self._budget.record_tokens(caller.user_id, result.usage.total)
        return AssistResult(result.answer, result.tool_calls, result.usage)
