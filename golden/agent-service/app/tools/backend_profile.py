"""The example tool: the signed-in user's profile, read from the backend's `GET /api/me` with the user's own token.

It proves the data-access rule of the service: the agent can see exactly what its user can see, because every
backend call carries the caller's token and the backend decides what that token may read.
"""

from __future__ import annotations

from typing import Any, ClassVar

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from app.tools.base import Tool, ToolContext, ToolError

ME_PATH = "/api/me"


class NoArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BackendUserProfile(BaseModel):
    """The fields of `UserProfile` in `shared/api-contracts/openapi.yml`. Anything else the backend adds is dropped."""

    model_config = ConfigDict(extra="ignore")

    id: str
    displayName: str
    email: str | None = None
    createdAt: str


class GetMyProfile(Tool):
    name: ClassVar[str] = "get_my_profile"
    description: ClassVar[str] = (
        "Read the profile of the signed-in user: display name, email and when the profile was created. "
        "Takes no arguments."
    )
    Arguments: ClassVar[type[BaseModel]] = NoArguments

    async def run(self, arguments: Any, context: ToolContext) -> dict[str, Any]:
        try:
            response = await context.backend.get(ME_PATH, headers=context.backend_headers())
        except httpx.HTTPError as error:
            raise ToolError("The backend could not be reached") from error
        if response.status_code in {401, 403}:
            raise ToolError("The backend did not accept the user's token")
        if response.status_code != 200:
            raise ToolError(f"The backend answered with status {response.status_code}")
        try:
            profile = BackendUserProfile.model_validate(response.json())
        except (ValueError, ValidationError) as error:
            raise ToolError("The backend answered with a profile in an unexpected shape") from error
        return profile.model_dump(exclude_none=True)
