"""A real MCP SDK client for the browser scenarios, with a synchronous surface.

The agent in a scenario signs in the way a connected agent does: the MCP
Python SDK over streamable HTTP to the served board's ``/mcp`` endpoint, with
the agent's participant token as a Bearer credential. The SDK is asynchronous
and Playwright's sync API owns the test thread, so the client runs its own
event loop on a worker thread and exposes blocking calls. The token is passed
in memory only; it is never written, logged or returned.
"""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
import hashlib
import json
import threading
from typing import Any

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

CALL_TIMEOUT_SECONDS = 60
READ_BATCH = 32


class AgentToolError(Exception):
    """An MCP tool call returned an error result; ``text`` is the service's message."""

    def __init__(self, tool: str, text: str) -> None:
        super().__init__(f"{tool}: {text}")
        self.tool = tool
        self.text = text


class AgentClient:
    def __init__(self, base_url: str, token: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._loop = asyncio.new_event_loop()
        self._loop.set_exception_handler(self._ignore_closed_connection)
        self._thread = threading.Thread(target=self._loop.run_forever, name="prism-browser-e2e-agent", daemon=True)
        self._thread.start()
        self._stack = AsyncExitStack()
        self._session: ClientSession | None = None

    # -- plumbing -----------------------------------------------------------------

    @staticmethod
    def _ignore_closed_connection(loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
        """A server that resets a connection while the client closes it is not worth a traceback."""

        if isinstance(context.get("exception"), ConnectionResetError):
            return
        loop.default_exception_handler(context)

    def _run(self, coroutine: Any) -> Any:
        return asyncio.run_coroutine_threadsafe(coroutine, self._loop).result(timeout=CALL_TIMEOUT_SECONDS)

    async def _open(self) -> None:
        http = await self._stack.enter_async_context(httpx2.AsyncClient(headers={"Authorization": "Bearer " + self._token}))
        reader, writer = await self._stack.enter_async_context(streamable_http_client(self._base_url + "/mcp", http_client=http))
        self._session = await self._stack.enter_async_context(ClientSession(reader, writer))
        await self._session.initialize()

    def __enter__(self) -> "AgentClient":
        self._run(self._open())
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()

    def close(self) -> None:
        try:
            if self._session is not None:
                self._run(self._stack.aclose())
        except Exception:
            pass
        self._session = None
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=10)

    async def _call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        assert self._session is not None
        result = await self._session.call_tool(tool, arguments)
        text = " ".join(part.text for part in result.content if getattr(part, "type", None) == "text")
        if result.is_error:
            raise AgentToolError(tool, text)
        if result.structured_content is not None:
            return result.structured_content
        return json.loads(text)

    def call(self, tool: str, **arguments: Any) -> dict[str, Any]:
        return self._run(self._call(tool, arguments))

    # -- workflow helpers ---------------------------------------------------------

    def read_every_page(self, paths: list[str]) -> dict[str, str]:
        """Full text of each path, following ``read_workspace`` cursors."""

        files: dict[str, str] = {}
        for start in range(0, len(paths), READ_BATCH):
            batch = paths[start:start + READ_BATCH]
            cursor = None
            while True:
                arguments: dict[str, Any] = {"paths": batch}
                if cursor is not None:
                    arguments["cursor"] = cursor
                page = self.call("read_workspace", **arguments)
                for record in page["files"]:
                    files[record["path"]] = files.get(record["path"], "") + record["content"]
                cursor = page["next_cursor"]
                if cursor is None:
                    break
        return files

    def revisions_for(self, skill: str) -> dict[str, str]:
        """The digests of every file the skill and the board require the agent to have read."""

        description = self.call("get_skill", name=skill)["skill"]
        inventory = self.call("list_workspace")
        paths = set(description["required_workspace_reads"])
        paths.update(item["path"] for item in inventory["files"] if item["read_support"] == "eligible")
        texts = self.read_every_page(sorted(paths))
        return {path: "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest() for path, text in texts.items()}

    def preview(self, skill: str, changes: list[dict[str, str]]) -> dict[str, Any]:
        return self.call("preview_skill", skill=skill, changes=changes, read_revisions=self.revisions_for(skill))

    def apply(self, preview_id: str, operation_id: str) -> dict[str, Any]:
        return self.call("apply", preview_id=preview_id, operation_id=operation_id)

    def propose(self, skill: str, feature_path: str, transform: Any) -> dict[str, Any]:
        """Read the feature page, apply ``transform(text) -> text`` and preview the result."""

        current = self.read_every_page([feature_path])[feature_path]
        return self.preview(skill, [{"path": feature_path, "content": transform(current)}])
