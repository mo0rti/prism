"""Real MCP SDK protocol tests for the Prism Board tool adapter."""

from __future__ import annotations

import asyncio
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import MCPError

from prism_cli.board_mcp import SERVER_INSTRUCTIONS, _safe_error
from prism_cli.board_service import BoardError
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

    def read_workspace(self, actor: _Actor, paths: list[str], cursor: str | None = None) -> dict[str, Any]:
        return self._result("read_workspace", actor, paths, cursor)

    def list_workspace(self, actor: _Actor, prefix: str = "knowledge", cursor: str | None = None) -> dict[str, Any]:
        return self._result("list_workspace", actor, prefix, cursor)

    def query(self, actor: _Actor, kind: str, value: str | None = None, action: str | None = None, cursor: str | None = None) -> dict[str, Any]:
        return self._result("query", actor, kind, value, action, cursor)

    def list_skills(self, actor: _Actor) -> dict[str, Any]:
        return self._result("list_skills", actor)

    def get_skill(self, actor: _Actor, name: str, cursor: str | None = None) -> dict[str, Any]:
        if name == "leak-error":
            raise _BoardError("skill_unavailable", f"bad token was {self.auth_token}", 409)
        return self._result("get_skill", actor, name, cursor)

    def get_skill_reference(self, actor: _Actor, name: str, path: str, cursor: str | None = None) -> dict[str, Any]:
        return self._result("get_skill_reference", actor, name, path, cursor)

    def preview_transition(self, actor: _Actor, feature_id: str, action: str, inputs: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._result("preview_transition", actor, feature_id, action, inputs)

    def preview_skill(self, actor: _Actor, skill: str, changes: list[dict[str, Any]], moves: list[dict[str, Any]] | None = None, read_revisions: dict[str, str] | None = None) -> dict[str, Any]:
        if skill == "rejected-details":
            raise BoardError(
                "clarify_answer_unlinked",
                f"Updated `Summary` must include an answer; the credential was {self.auth_token}.",
                409,
                {"section": "Summary", "resolved_questions": ["2"], "resolved_answers": {"2": f"Answer starts with {self.auth_token}"}},
            )
        return self._result("preview_skill", actor, skill, changes, moves, read_revisions)

    def get_preview(self, actor: _Actor, preview_id: str) -> dict[str, Any]:
        return self._result("get_preview", actor, preview_id)

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
                        "get_skill_reference",
                        "preview_transition",
                        "preview_skill",
                        "get_preview",
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
                for name in {"discover", "read_workspace", "list_workspace", "query", "list_skills", "get_skill", "get_skill_reference", "get_preview", "operation", "changes"}:
                    self.assertTrue(by_name[name].annotations.read_only_hint, name)
                    self.assertFalse(by_name[name].annotations.open_world_hint, name)
                for name in {"preview_transition", "preview_skill", "apply", "recover"}:
                    self.assertFalse(by_name[name].annotations.read_only_hint, name)
                result = await session.call_tool("read_workspace", {"paths": ["knowledge/wiki/BOARD.md"]})
                self.assertFalse(result.is_error)
                self.assertEqual(result.structured_content["operation"], "read_workspace")
                self.assertEqual(self.service.calls[-1][1], (["knowledge/wiki/BOARD.md"], None))
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
                self.assertEqual(self.service.calls[-1][1], ("transition-preflight", "F-1", "design-start", None))
                self.assertGreaterEqual(self.service.auth_calls, 4)
            finally:
                await self._disconnect(http, streams, session)

    async def test_results_carry_structured_content_once_with_a_short_text_summary(self) -> None:
        async with self.app.router.lifespan_context(self.app):
            http, streams, session = await self._connect()
            try:
                await session.initialize()
                tools = {tool.name: tool for tool in (await session.list_tools()).tools}
                calls = (
                    ("discover", {}, ()),
                    ("list_skills", {}, ()),
                    ("get_skill", {"name": "po-intake", "cursor": "C-2"}, ("po-intake", "C-2")),
                    (
                        "get_skill_reference",
                        {"name": "po-intake", "path": "knowledge/wiki/SCHEMA.md", "cursor": "C-3"},
                        ("po-intake", "knowledge/wiki/SCHEMA.md", "C-3"),
                    ),
                    ("read_workspace", {"paths": ["knowledge/wiki/index.md"], "cursor": "C-4"}, (["knowledge/wiki/index.md"], "C-4")),
                    ("query", {"kind": "owner", "value": "po", "cursor": "C-5"}, ("owner", "po", None, "C-5")),
                    ("changes", {}, (None,)),
                )
                for tool, arguments, expected in calls:
                    with self.subTest(tool=tool):
                        self.assertIsNotNone(tools[tool].output_schema)
                        result = await session.call_tool(tool, arguments)
                        self.assertFalse(result.is_error)
                        self.assertEqual(tool, result.structured_content["operation"])
                        self.assertEqual(list(expected), result.structured_content["args"])
                        texts = [block.text for block in result.content if block.type == "text"]
                        self.assertEqual(1, len(texts))
                        self.assertLessEqual(len(texts[0]), 500)
                        self.assertTrue(texts[0].startswith(tool))
                        with self.assertRaises(ValueError):
                            json.loads(texts[0])
                        self.assertNotIn("schema_version", texts[0])
            finally:
                await self._disconnect(http, streams, session)

    async def test_summary_for_a_large_structured_result_stays_short(self) -> None:
        async with self.app.router.lifespan_context(self.app):
            http, streams, session = await self._connect()
            try:
                await session.initialize()
                original = self.service.get_skill
                big = {"schema_version": 1, "skill": {"name": "po-intake", "references": [{"path": f"r{index}"} for index in range(2000)]}, "next_cursor": "C-9"}
                self.service.get_skill = lambda actor, name, cursor=None: big
                try:
                    result = await session.call_tool("get_skill", {"name": "po-intake"})
                finally:
                    self.service.get_skill = original
                self.assertFalse(result.is_error)
                self.assertEqual(2000, len(result.structured_content["skill"]["references"]))
                texts = [block.text for block in result.content if block.type == "text"]
                self.assertEqual(1, len(texts))
                self.assertLessEqual(len(texts[0]), 500)
                self.assertIn("next_cursor", texts[0])
            finally:
                await self._disconnect(http, streams, session)

    async def test_initialize_publishes_title_description_and_orientation_instructions(self) -> None:
        async with self.app.router.lifespan_context(self.app):
            http, streams, session = await self._connect()
            try:
                init = await session.initialize()
                self.assertEqual("Prism Board", init.server_info.title)
                self.assertTrue(init.server_info.description)
                self.assertNotIn("\n", init.server_info.description)
                instructions = init.instructions
                self.assertIsInstance(instructions, str)
                self.assertLessEqual(len(instructions), 2000)
                self.assertEqual(SERVER_INSTRUCTIONS, instructions)
                for term in ("discover", "get_skill_reference", "next_cursor", "preview_skill", "apply", "operation"):
                    self.assertIn(term, instructions)
                self.assertIn("untrusted", instructions)
                self.assertIn("never approves", instructions)
                # A rejected proposal may be corrected as the error names, at most 2 more times, without widening it.
                retry = instructions[instructions.index("If the board rejects a proposal"):]
                for term in ("exactly what the error names", "at most 2 more times", "without widening the change", "then stop and report"):
                    self.assertIn(term, retry)
                # The steps appear in the order an agent should use them.
                order = ("discover", "list_skills", "get_skill_reference", "next_cursor", "read_workspace", "preview_skill", "apply", "operation", "recover", "updates with changes")
                positions = [instructions.index(term) for term in order]
                self.assertEqual(sorted(positions), positions)
            finally:
                await self._disconnect(http, streams, session)

    async def test_tool_descriptions_are_distinctive_and_the_contract_is_unchanged(self) -> None:
        # name -> (all argument names, required argument names)
        expected = {
            "discover": (set(), set()),
            "read_workspace": ({"paths", "cursor"}, {"paths"}),
            "list_workspace": ({"prefix", "cursor"}, set()),
            "query": ({"kind", "value", "action", "cursor"}, {"kind"}),
            "list_skills": (set(), set()),
            "get_skill": ({"name", "cursor"}, {"name"}),
            "get_skill_reference": ({"name", "path", "cursor"}, {"name", "path"}),
            "preview_transition": ({"feature_id", "action", "inputs"}, {"feature_id", "action"}),
            "preview_skill": ({"skill", "changes", "moves", "read_revisions"}, {"skill", "changes"}),
            "get_preview": ({"preview_id", "cursor"}, {"preview_id"}),
            "apply": ({"preview_id", "operation_id"}, {"preview_id", "operation_id"}),
            "operation": ({"operation_id", "cursor"}, {"operation_id"}),
            "recover": ({"operation_id", "review_revision", "semantic_review_acknowledged"}, {"operation_id"}),
            "changes": ({"cursor"}, set()),
        }
        async with self.app.router.lifespan_context(self.app):
            http, streams, session = await self._connect()
            try:
                await session.initialize()
                tools = {tool.name: tool for tool in (await session.list_tools()).tools}
                self.assertEqual(set(expected), set(tools))
                for name, (arguments, required) in expected.items():
                    with self.subTest(tool=name):
                        tool = tools[name]
                        self.assertTrue(tool.description.startswith("Prism board:"), tool.description)
                        self.assertEqual(arguments, set(tool.input_schema.get("properties", {})))
                        self.assertEqual(required, set(tool.input_schema.get("required", [])))
                for name in ("read_workspace", "query", "get_skill_reference"):
                    self.assertIn("next_cursor", tools[name].description, name)
                self.assertIn("digest", tools["get_skill_reference"].description)
                self.assertIn("get_skill_reference", tools["get_skill"].description)
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

    async def test_rejection_details_reach_the_tool_error_text_and_stay_redacted(self) -> None:
        async with self.app.router.lifespan_context(self.app):
            http, streams, session = await self._connect()
            try:
                await session.initialize()
                result = await session.call_tool(
                    "preview_skill",
                    {"skill": "rejected-details", "changes": [{"path": "knowledge/wiki/features/F-001.md", "content": "x"}]},
                )
                self.assertTrue(result.is_error)
                text = " ".join(block.text for block in result.content if hasattr(block, "text"))
                self.assertIn("clarify_answer_unlinked: Updated `Summary`", text)
                self.assertNotIn(self.service.auth_token, text)
                self.assertIn("[redacted]", text)
                details = json.loads(text[text.index(' {"'):])
                self.assertEqual(
                    {"section": "Summary", "resolved_questions": ["2"], "resolved_answers": {"2": "Answer starts with [redacted]"}},
                    details,
                )
            finally:
                await self._disconnect(http, streams, session)

    def test_safe_error_appends_compact_details_and_stays_under_the_limit(self) -> None:
        error = BoardError("invalid_change", "`changes[1]` is missing `content`.", 400, {"index": 1, "missing": ["content"]})
        self.assertEqual(
            'invalid_change: `changes[1]` is missing `content`. {"index":1,"missing":["content"]}',
            _safe_error(error),
        )
        self.assertEqual("invalid_change: `changes[1]` is missing `content`.", _safe_error(BoardError("invalid_change", "`changes[1]` is missing `content`.")))
        # Details that do not fit are dropped; the message always survives within the cap.
        crowded = BoardError("invalid_change", "m" * 900, 400, {"fields": ["f" * 50] * 20})
        crowded.message = "m" * 1990
        text = _safe_error(crowded)
        self.assertLessEqual(len(text), 2000)
        self.assertNotIn("fields", text)

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
