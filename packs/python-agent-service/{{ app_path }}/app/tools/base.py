"""What a tool is, and what it is given.

A tool is a read. It receives validated arguments and the context of one request: the caller, whose own
token it must use for any data call, and the request ID. It never sees another user's context, because a
context exists for one request only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

import httpx
from pydantic import BaseModel

from app.auth.caller import Caller


class ToolError(Exception):
    """A failure the model may be told about, in words that are safe to show it and the user."""


@dataclass(frozen=True)
class ToolContext:
    caller: Caller
    request_id: str
    # The client for the backend API: a fixed base URL, no redirects. The model never chooses a URL.
    backend: httpx.AsyncClient

    def backend_headers(self) -> dict[str, str]:
        """The headers of a backend call: the caller's own bearer token and the request ID."""

        return {"Authorization": f"Bearer {self.caller.token}", "X-Request-ID": self.request_id}


class Tool:
    """Subclass it, set the class attributes and implement `run`. See the `add-tool` skill."""

    name: ClassVar[str]
    description: ClassVar[str]
    # The model fills these in; they are validated before `run` is called.
    Arguments: ClassVar[type[BaseModel]]
    # A tool never changes anything by itself. A tool that proposes a change returns a preview of it, and the
    # user confirms in the application. The registry refuses a tool that sets this to True.
    mutates: ClassVar[bool] = False

    async def run(self, arguments: Any, context: ToolContext) -> dict[str, Any]:
        raise NotImplementedError
