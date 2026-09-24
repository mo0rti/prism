"""Provider-neutral MCP tools backed by the local :class:`BoardService`.

This module contains no workflow validation.  Every tool authenticates the
Bearer token again at call time and delegates directly to the shared service.
The MCP SDK is imported lazily so read-only Prism commands do not require the
optional transport dependencies.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, Literal


_SAFE_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def _authorization(headers: Any) -> str | None:
    if not headers:
        return None
    value = headers.get("authorization")
    if not isinstance(value, str):
        return None
    scheme, separator, token = value.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token or token.strip() != token or " " in token:
        return None
    return token


def _safe_error(exc: Exception, token: str | None = None) -> str:
    code = getattr(exc, "code", "board_error")
    if not isinstance(code, str) or not _SAFE_CODE.fullmatch(code):
        code = "board_error"
    message = getattr(exc, "message", "The board request could not be completed.")
    if not isinstance(message, str):
        message = "The board request could not be completed."
    if token:
        message = message.replace(token, "[redacted]")
    return f"{code}: {message}"


def create_mcp_server(service: Any) -> Any:
    """Create an MCPServer exposing only the approved BoardService operations.

    `service` is an existing BoardService instance owned by the HTTP app.  The
    returned server is mounted by ``board_server`` and shares its lifecycle.
    """

    try:
        from mcp.server import MCPServer
        from mcp.server.auth.provider import AccessToken, TokenVerifier
        from mcp.server.auth.settings import AuthSettings
        from mcp.server.mcpserver.context import Context
        from mcp.server.mcpserver.exceptions import ToolError
        from mcp.types import ToolAnnotations
        from pydantic import BaseModel, ConfigDict, StrictBool, StrictStr
    except ImportError as exc:  # pragma: no cover - depends on install profile
        raise RuntimeError("The optional MCP transport requires mcp==2.2.0.") from exc

    # MCPServer resolves postponed annotations against the callable's module
    # globals.  Publish the optional SDK type there only after it is imported.
    globals()["Context"] = Context
    globals()["StrictBool"] = StrictBool
    globals()["StrictStr"] = StrictStr

    class PreviewSkillChange(BaseModel):
        model_config = ConfigDict(extra="forbid")
        path: StrictStr
        content: StrictStr

    class PreviewSkillMove(BaseModel):
        model_config = ConfigDict(extra="forbid")
        source: StrictStr
        destination: StrictStr

    class PreviewTransitionInputs(BaseModel):
        model_config = ConfigDict(extra="forbid")
        semantic_review_acknowledged: StrictBool | None = None
        skip_advisory_review: StrictBool | None = None
        advisory_skip_reason: StrictStr | None = None
        verified_revalidation: list[StrictStr] | None = None

    # MCPServer calls get_type_hints() in this module namespace after the
    # optional SDK has been loaded; dynamic models keep core imports lazy.
    globals()["PreviewSkillChange"] = PreviewSkillChange
    globals()["PreviewSkillMove"] = PreviewSkillMove
    globals()["PreviewTransitionInputs"] = PreviewTransitionInputs

    class _BoardTokenVerifier(TokenVerifier):
        async def verify_token(self, token: str) -> Any:
            try:
                actor = await asyncio.to_thread(service.authenticate, token)
            except Exception:
                return None
            scopes = getattr(actor, "scopes", ("read",))
            if not isinstance(scopes, (tuple, list, set, frozenset)):
                scopes = ("read",)
            return AccessToken(
                token=token,
                client_id="prism-board",
                scopes=[scope for scope in scopes if isinstance(scope, str)],
                subject=getattr(actor, "participant_id", None),
            )

    server = MCPServer(
        name="Prism Board",
        version="1",
        token_verifier=_BoardTokenVerifier(),
        auth=AuthSettings(
            issuer_url="http://127.0.0.1/",
            resource_server_url=None,
            required_scopes=[],
        ),
    )
    read_annotations = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
    preview_annotations = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
    operation_annotations = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)

    async def actor_for(context: Any) -> tuple[Any, str]:
        token = _authorization(getattr(context, "headers", None))
        if token is None:
            raise ToolError("unauthorized: A valid Prism Bearer token is required.")
        try:
            actor = await asyncio.to_thread(service.authenticate, token)
        except Exception as exc:
            raise ToolError(_safe_error(exc, token)) from None
        return actor, token

    async def call(context: Any, method_name: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        actor, token = await actor_for(context)
        try:
            method = getattr(service, method_name)
            result = await asyncio.to_thread(method, actor, *args, **kwargs)
        except ToolError:
            raise
        except Exception as exc:
            if hasattr(exc, "code") and hasattr(exc, "message"):
                raise ToolError(_safe_error(exc, token)) from None
            # Keep unexpected service details, paths, and possible credentials
            # out of MCP content and SDK logs.
            raise ToolError("internal_error: The board request could not be completed.") from None
        if not isinstance(result, dict):
            raise ToolError("internal_error: The board returned an invalid response.")
        return result

    @server.tool(name="discover", description="Read the current Prism board capabilities and pending operations.", annotations=read_annotations, structured_output=True)
    async def discover(ctx: Context) -> dict[str, Any]:
        return await call(ctx, "discover")

    @server.tool(name="read_workspace", description="Read bounded, approved wiki and intake context by relative path.", annotations=read_annotations, structured_output=True)
    async def read_workspace(paths: list[str], ctx: Context) -> dict[str, Any]:
        return await call(ctx, "read_workspace", paths)

    @server.tool(name="list_workspace", description="List a paginated, approved workspace tree by relative prefix.", annotations=read_annotations, structured_output=True)
    async def list_workspace(ctx: Context, prefix: str = "knowledge", cursor: str | None = None) -> dict[str, Any]:
        return await call(ctx, "list_workspace", prefix, cursor)

    @server.tool(name="query", description="Run one bounded Prism workspace query or source-backed transition preflight.", annotations=read_annotations, structured_output=True)
    async def query(
        ctx: Context,
        kind: Literal["show", "blockers", "owner", "platform", "search", "transition-preflight", "lint"],
        value: str | None = None,
        action: str | None = None,
    ) -> dict[str, Any]:
        return await call(ctx, "query", kind, value, action)

    @server.tool(name="list_skills", description="List the canonical workflow skills pinned to this workspace.", annotations=read_annotations, structured_output=True)
    async def list_skills(ctx: Context) -> dict[str, Any]:
        return await call(ctx, "list_skills")

    @server.tool(name="get_skill", description="Read one canonical workflow skill and its referenced guidance.", annotations=read_annotations, structured_output=True)
    async def get_skill(name: str, ctx: Context) -> dict[str, Any]:
        return await call(ctx, "get_skill", name)

    @server.tool(name="preview_transition", description="Calculate an exact preview for a supported human lifecycle action.", annotations=preview_annotations, structured_output=True)
    async def preview_transition(
        ctx: Context,
        feature_id: str,
        action: str,
        inputs: PreviewTransitionInputs | None = None,
    ) -> dict[str, Any]:
        input_values = inputs.model_dump(exclude_unset=True) if inputs is not None else None
        return await call(ctx, "preview_transition", feature_id, action, input_values)

    @server.tool(name="preview_skill", description="Preview a bounded operation supported by a canonical workflow skill.", annotations=preview_annotations, structured_output=True)
    async def preview_skill(
        ctx: Context,
        skill: str,
        changes: list[PreviewSkillChange],
        moves: list[PreviewSkillMove] | None = None,
        read_revisions: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        change_values = [item.model_dump() for item in changes]
        move_values = [item.model_dump() for item in moves] if moves is not None else None
        return await call(ctx, "preview_skill", skill, change_values, move_values, read_revisions)

    @server.tool(name="apply", description="Apply a previously returned, applicable preview using an idempotent operation ID.", annotations=operation_annotations, structured_output=True)
    async def apply(preview_id: str, operation_id: str, ctx: Context) -> dict[str, Any]:
        return await call(ctx, "apply", preview_id, operation_id)

    @server.tool(name="operation", description="Read the receipt for a previously submitted board operation.", annotations=read_annotations, structured_output=True)
    async def operation(operation_id: str, ctx: Context) -> dict[str, Any]:
        return await call(ctx, "operation", operation_id)

    @server.tool(name="recover", description="Reconcile a pending board operation while preserving conflicting external edits.", annotations=operation_annotations, structured_output=True)
    async def recover(
        ctx: Context,
        operation_id: str,
        review_revision: StrictStr | None = None,
        semantic_review_acknowledged: StrictBool = False,
    ) -> dict[str, Any]:
        return await call(ctx, "recover", operation_id, review_revision, semantic_review_acknowledged)

    @server.tool(name="changes", description="Read durable board changes after an optional cursor.", annotations=read_annotations, structured_output=True)
    async def changes(ctx: Context, cursor: str | None = None) -> dict[str, Any]:
        return await call(ctx, "changes", cursor)

    return server
