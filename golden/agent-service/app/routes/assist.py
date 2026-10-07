"""`POST /api/assist`: one question, one agent turn, one answer. The caller needs a valid bearer token."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

from app.agent.service import AssistantService
from app.auth.caller import Caller
from app.auth.dependencies import require_caller
from app.errors import ApiError
from app.models import AssistRequest, AssistResponse, ToolCallInfo, UsageInfo
from app.providers.base import ProviderError
from app.safety.budget import BudgetExceededError
from app.safety.notice import NOTICE

router = APIRouter()

PROTECTED_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"description": "The request is not valid"},
    401: {"description": "Authentication required or invalid token"},
    403: {"description": "The local development identity answers callers on this machine only"},
    429: {"description": "The caller's budget is used up"},
    502: {"description": "The model provider failed"},
    503: {"description": "The identity keys are unavailable"},
}


@router.post(
    "/api/assist",
    operation_id="createAssist",
    tags=["assistant"],
    response_model=AssistResponse,
    responses=PROTECTED_RESPONSES,
)
async def assist(
    body: AssistRequest, request: Request, caller: Annotated[Caller, Depends(require_caller)]
) -> AssistResponse:
    service: AssistantService = request.app.state.assistant
    request_id: str = request.state.request_id
    try:
        result = await service.answer(caller=caller, question=body.question, request_id=request_id)
    except BudgetExceededError as error:
        raise ApiError(
            429,
            "BUDGET_EXCEEDED",
            f"You have used your {error.reason} budget for now. Try again later.",
            headers={"Retry-After": str(error.retry_after_seconds)},
        ) from error
    except ProviderError as error:
        raise ApiError(
            502, "PROVIDER_ERROR", "The assistant could not get an answer from its model. Try again later."
        ) from error
    return AssistResponse(
        answer=result.answer,
        tool_calls=[ToolCallInfo(name=call.name, ok=call.ok) for call in result.tool_calls],
        usage=UsageInfo(input_tokens=result.usage.input_tokens, output_tokens=result.usage.output_tokens),
        notice=NOTICE,
        request_id=request_id,
    )
