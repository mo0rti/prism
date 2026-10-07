"""The request and response bodies. Field names are camelCase on the wire, like the backend's."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

MAX_QUESTION_CHARS = 2000


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class HealthResponse(ApiModel):
    status: str


class AssistRequest(ApiModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)

    @field_validator("question")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("The question must not be blank")
        return value.strip()


class ToolCallInfo(ApiModel):
    name: str
    ok: bool


class UsageInfo(ApiModel):
    input_tokens: int
    output_tokens: int


class AssistResponse(ApiModel):
    answer: str
    tool_calls: list[ToolCallInfo]
    usage: UsageInfo
    notice: str
    request_id: str
