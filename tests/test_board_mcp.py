"""Real MCP SDK protocol tests for the Prism Board tool adapter."""

from __future__ import annotations

import asyncio
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import MCPError

from prism_cli.board_server import create_app


class _BoardError(Exception):
    def __init__(self, code: str, message: str, status: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


class _Actor:
    participant_id = "agent-1"
    name = "Test Agent"
    kind = "agent"
    writable = True
    board_id = "board-1"
    workflow_version = "1"
    scopes = ["read", "write"]


class _Service:
    def __init__(self) -> None:
        self.auth_calls = 0
        self.fail_on_auth_call: int | None = None
        self.revoked = False
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.auth_token = "mcp-agent-secret"

    def validate_graph_inputs(self) -> None:
        return None

    def authenticate(self, token: str) -> _Actor:
        self.auth_calls += 1
        if token != self.auth_token or self.revoked or self.auth_calls == self.fail_on_auth_call:
            raise _BoardError("invalid_token", f"invalid credential {token}", 401)
        return _Actor()

    def _result(self, name: str, actor: _Actor, *args: Any) -> dict[str, Any]:
        if actor.participant_id != "agent-1":
            raise AssertionError("transport constructed an unexpected actor")
        self.calls.append((name, args))
        return {"schema_version": 1, "operation": name, "args": list(args)}

    def discover(self, actor: _Actor) -> dict[str, Any]:
        return self._result("discover", actor)

    def read_workspace(self, actor: _Actor, paths: list[str]) -> dict[str, Any]:
        return self._result("read_workspace", actor, paths)

    def list_workspace(self, actor: _Actor, prefix: str = "knowledge", cursor: str | None = None) -> dict[str, Any]:
        return self._result("list_workspace", actor, prefix, cursor)

    def query(self, actor: _Actor, kind: str, value: str | None = None, action: str | None = None) -> dict[str, Any]:
        return self._result("query", actor, kind, value, action)

    def list_skills(self, actor: _Actor) -> dict[str, Any]:
        return self._result("list_skills", actor)

    def get_skill(self, actor: _Actor, name: str) -> dict[str, Any]:
        if name == "leak-error":
            raise _BoardError("skill_unavailable", f"bad token was {self.auth_token}", 409)
        return self._result("get_skill", actor, name)

    def preview_transition(self, actor: _Actor, feature_id: str, action: str, inputs: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._result("preview_transition", actor, feature_id, action, inputs)

    def preview_skill(self, actor: _Actor, skill: str, changes: list[dict[str, Any]], moves: list[dict[str, Any]] | None = None, read_revisions: dict[str, str] | None = None) -> dict[str, Any]:
        return self._result("preview_skill", actor, skill, changes, moves, read_revisions)

    def apply(self, actor: _Actor, preview_id: str, operation_id: str) -> dict[str, Any]:
        return self._result("apply", actor, preview_id, operation_id)

    def operation(self, actor: _Actor, operation_id: str) -> dict[str, Any]:
        return self._result("operation", actor, operation_id)

    def recover(self, actor: _Actor, operation_id: str, review_revision: str | None = None, semantic_review_acknowledged: bool = False) -> dict[str, Any]:
        return self._result("recover", actor, operation_id, review_revision, semantic_review_acknowledged)

    def changes(self, actor: _Actor, cursor: str | None = None) -> dict[str, Any]:
        return self._result("changes", actor, cursor)


class BoardMCPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.service = _Service()
        self.app = create_app(self.root, port=8765, service=self.service)
        self.transport = httpx2.ASGITransport(app=self.app)

    async def asyncTearDown(self) -> None:
        self.temp.cleanup()

    async def _connect(self) -> tuple[Any, Any, Any]:
        http = httpx2.AsyncClient(
            transport=self.transport,
            base_url="http://127.0.0.1:8765",
            headers={"Authorization": f"Bearer {self.service.auth_token}"},
        )
        await http.__aenter__()
        streams = streamable_http_client("http://127.0.0.1:8765/mcp", http_client=http)
        reader, writer = await streams.__aenter__()
        session = ClientSession(reader, writer)
        await session.__aenter__()
        return http, streams, session

    async def _disconnect(self, http: Any, streams: Any, session: Any) -> None:
        await session.__aexit__(None, None, None)
        await streams.__aexit__(None, None, None)
        await http.__aexit__(None, None, None)

    async def test_real_sdk_legacy_handshake_and_tool_call(self) -> None:
        async with self.app.router.lifespan_context(self.app):
            http, streams, session = await self._connect()
            try:
                init = await session.initialize()
                self.assertEqual(init.protocol_version, "2025-11-25")
                self.assertEqual(session.protocol_version, "2025-11-25")
                listed = await session.list_tools()
                names = {tool.name for tool in listed.tools}
                self.assertEqual(
                    names,
                    {
                        "discover",
                        "read_workspace",
                        "list_workspace",
                        "query",
                        "list_skills",
                        "get_skill",
                        "preview_transition",
                        "preview_skill",
                        "apply",
                        "operation",
                        "recover",
                        "changes",
                    },
                )
                self.assertTrue(all("participant" not in name for name in names))
                by_name = {tool.name: tool for tool in listed.tools}
                self.assertEqual(
                    set(by_name["query"].input_schema["properties"]["kind"]["enum"]),
                    {"show", "blockers", "owner", "platform", "search", "transition-preflight", "lint"},
                )
                for name in {"discover", "read_workspace", "list_workspace", "query", "list_skills", "get_skill", "operation", "changes"}:
                    self.assertTrue(by_name[name].annotations.read_only_hint, name)
                    self.assertFalse(by_name[name].annotations.open_world_hint, name)
                for name in {"preview_transition", "preview_skill", "apply", "recover"}:
                    self.assertFalse(by_name[name].annotations.read_only_hint, name)
                result = await session.call_tool("read_workspace", {"paths": ["knowledge/wiki/BOARD.md"]})
                self.assertFalse(result.is_error)
                self.assertEqual(result.structured_content["operation"], "read_workspace")
                self.assertEqual(self.service.calls[-1][1], (["knowledge/wiki/BOARD.md"],))
                listed = await session.call_tool(
                    "list_workspace",
                    {"prefix": "knowledge/intake", "cursor": "C-1"},
                )
                self.assertFalse(listed.is_error)
                self.assertEqual(listed.structured_content["operation"], "list_workspace")
                self.assertEqual(self.service.calls[-1][1], ("knowledge/intake", "C-1"))
                queried = await session.call_tool(
                    "query",
                    {"kind": "transition-preflight", "value": "F-1", "action": "design-start"},
                )
                self.assertFalse(queried.is_error)
                self.assertEqual(queried.structured_content["operation"], "query")
                self.assertEqual(self.service.calls[-1][1], ("transition-preflight", "F-1", "design-start"))
                self.assertGreaterEqual(self.service.auth_calls, 4)
            finally:
                await self._disconnect(http, streams, session)

    async def test_real_sdk_modern_discovery_protocol(self) -> None:
        async with self.app.router.lifespan_context(self.app):
            http, streams, session = await self._connect()
            try:
                discovery = await session.discover()
                self.assertIn("2026-07-28", discovery.supported_versions)
                self.assertEqual(session.protocol_version, "2026-07-28")
                tools = await session.list_tools()
                self.assertIn("apply", {tool.name for tool in tools.tools})
                result = await session.call_tool("discover", {})
                self.assertFalse(result.is_error)
                self.assertEqual(result.structured_content["operation"], "discover")
            finally:
                await self._disconnect(http, streams, session)

    async def test_preview_skill_schema_validates_nested_proposals_before_service_call(self) -> None:
        async with self.app.router.lifespan_context(self.app):
            http, streams, session = await self._connect()
            try:
                await session.initialize()
                tools = await session.list_tools()
                by_name = {tool.name: tool for tool in tools.tools}
                skill_schema = by_name["preview_skill"].input_schema
                change_schema = skill_schema["$defs"]["PreviewSkillChange"]
                move_schema = skill_schema["$defs"]["PreviewSkillMove"]
                self.assertEqual(change_schema["required"], ["path", "content"])
                self.assertEqual(change_schema["additionalProperties"], False)
                self.assertEqual(change_schema["properties"]["path"]["type"], "string")
                self.assertEqual(change_schema["properties"]["content"]["type"], "string")
                self.assertEqual(move_schema["required"], ["source", "destination"])
                self.assertEqual(move_schema["additionalProperties"], False)
                self.assertEqual(move_schema["properties"]["source"]["type"], "string")
                self.assertEqual(move_schema["properties"]["destination"]["type"], "string")

                transition_inputs = by_name["preview_transition"].input_schema["$defs"]["PreviewTransitionInputs"]
                self.assertEqual(
                    set(transition_inputs["properties"]),
                    {"semantic_review_acknowledged", "skip_advisory_review", "advisory_skip_reason", "verified_revalidation"},
                )
                self.assertEqual(transition_inputs["additionalProperties"], False)
                for name in ("semantic_review_acknowledged", "skip_advisory_review"):
                    self.assertIn(
                        {"type": "boolean"},
                    transition_inputs["properties"][name]["anyOf"],
                )

                recover_schema = by_name["recover"].input_schema
                self.assertEqual(recover_schema["required"], ["operation_id"])
                self.assertIn({"type": "string"}, recover_schema["properties"]["review_revision"]["anyOf"])
                self.assertEqual(recover_schema["properties"]["semantic_review_acknowledged"]["type"], "boolean")

                change = {"path": "knowledge/intake/pending/F-1/feature.md", "content": "id: F-1\n"}
                move = {"source": "knowledge/intake/pending/F-1", "destination": "knowledge/intake/processed/F-1"}
                revisions = {"knowledge/wiki/SCHEMA.md": "sha256-schema"}
                accepted = await session.call_tool(
                    "preview_skill",
                    {"skill": "po-intake", "changes": [change], "moves": [move], "read_revisions": revisions},
                )
                self.assertFalse(accepted.is_error)
                self.assertEqual(
                    self.service.calls[-1][1],
                    ("po-intake", [change], [move], revisions),
                    "Pydantic transport models must be converted to plain service dictionaries",
                )

                inputs = {
                    "semantic_review_acknowledged": False,
                    "skip_advisory_review": True,
                    "advisory_skip_reason": "Reviewed by the PO.",
                    "verified_revalidation": ["specification"],
                }
                transitioned = await session.call_tool(
                    "preview_transition",
                    {"feature_id": "F-1", "action": "po-handoff", "inputs": inputs},
                )
                self.assertFalse(transitioned.is_error)
                self.assertEqual(self.service.calls[-1][1], ("F-1", "po-handoff", inputs))

                recovered = await session.call_tool(
                    "recover",
                    {"operation_id": "O-review", "review_revision": "revision-1", "semantic_review_acknowledged": True},
                )
                self.assertFalse(recovered.is_error)
                self.assertEqual(self.service.calls[-1][1], ("O-review", "revision-1", True))

                before = len(self.service.calls)
                invalid_proposals = [
                    {"skill": "po-intake", "changes": [{**change, "unexpected": "value"}]},
                    {"skill": "po-intake", "changes": [{"path": change["path"]}]},
                    {"skill": "po-intake", "changes": [{"path": change["path"], "content": 7}]},
                    {"skill": "po-intake", "changes": [change], "moves": [{**move, "unexpected": "value"}]},
                    {"skill": "po-intake", "changes": [change], "moves": [{"from": move["source"], "to": move["destination"]}]},
                ]
                for proposal in invalid_proposals:
                    result = await session.call_tool("preview_skill", proposal)
                    self.assertTrue(result.is_error, proposal)
                bad_inputs = await session.call_tool(
                    "preview_transition",
                    {"feature_id": "F-1", "action": "po-handoff", "inputs": {"unrecognized": True}},
                )
                self.assertTrue(bad_inputs.is_error)
                for invalid_ack in ("true", 1):
                    invalid_inputs = await session.call_tool(
                        "preview_transition",
                        {
                            "feature_id": "F-1",
                            "action": "po-handoff",
                            "inputs": {"semantic_review_acknowledged": invalid_ack},
                        },
                    )
                    self.assertTrue(invalid_inputs.is_error, invalid_ack)
                for invalid_recovery in (
                    {"operation_id": "O-review", "review_revision": 1, "semantic_review_acknowledged": True},
                    {"operation_id": "O-review", "review_revision": "revision-1", "semantic_review_acknowledged": "true"},
                ):
                    result = await session.call_tool("recover", invalid_recovery)
                    self.assertTrue(result.is_error, invalid_recovery)
                self.assertEqual(len(self.service.calls), before, "invalid nested fields reached BoardService")
            finally:
                await self._disconnect(http, streams, session)

    async def test_each_tool_reauthenticates_and_redacts_service_error(self) -> None:
        async with self.app.router.lifespan_context(self.app):
            http, streams, session = await self._connect()
            try:
                await session.initialize()
                current_count = self.service.auth_calls
                rejected = await session.call_tool("discover", {})
                # The SDK verifies the Bearer at its HTTP boundary. Prism then
                # authenticates it again inside the tool before resolving the
                # server-owned Actor for that individual tool call.
                self.assertFalse(rejected.is_error)
                self.assertGreaterEqual(self.service.auth_calls - current_count, 2)

                leaked = await session.call_tool("get_skill", {"name": "leak-error"})
                self.assertTrue(leaked.is_error)
                content = " ".join(block.text for block in leaked.content if hasattr(block, "text"))
                self.assertNotIn(self.service.auth_token, content)
                self.assertIn("[redacted]", content)
            finally:
                await self._disconnect(http, streams, session)

    async def test_revoked_bearer_is_rejected_for_the_next_tool_call(self) -> None:
        async with self.app.router.lifespan_context(self.app):
            http, streams, session = await self._connect()
            try:
                await session.initialize()
                self.service.revoked = True
                auth_calls_before = self.service.auth_calls
                before = len(self.service.calls)
                with self.assertRaises(MCPError):
                    await session.call_tool("discover", {})
                self.assertGreater(self.service.auth_calls, auth_calls_before)
                self.assertEqual(len(self.service.calls), before)
            finally:
                self.service.revoked = False
                await self._disconnect(http, streams, session)

    async def test_mcp_route_rejects_missing_and_invalid_bearer(self) -> None:
        async with self.app.router.lifespan_context(self.app):
            async with httpx2.AsyncClient(transport=self.transport, base_url="http://127.0.0.1:8765") as http:
                response = await http.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
                self.assertEqual(response.status_code, 401)
                invalid = await http.post(
                    "/mcp",
                    json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                    headers={"Authorization": "Bearer raw-invalid-token"},
                )
                self.assertEqual(invalid.status_code, 401)
                self.assertNotIn("raw-invalid-token", invalid.text)


if __name__ == "__main__":
    unittest.main()
