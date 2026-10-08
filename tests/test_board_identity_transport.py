"""Approval over the real HTTP and MCP transports: only a browser session approves, and equal credentials get equal results."""

from __future__ import annotations

import json
import unittest

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from starlette.testclient import TestClient

from prism_cli.board_server import create_app
from tests.test_board_identity import FEATURE, GatedBoardCase
from tests.design_tracks import started
from tests.test_board_service import _read_revisions

ORIGIN = "http://127.0.0.1:8765"
API = "/api/board/v1"


class _Transport:
    """The two ways into one started service: a Bearer token and a browser session."""

    def agent_changes(self):
        content = started(self.read(FEATURE))
        changes = [{"path": FEATURE, "content": content}]
        return changes, _read_revisions(self.service, self.agent, "design-start", changes)


class HttpApprovalTests(_Transport, GatedBoardCase):
    def setUp(self) -> None:
        super().setUp()
        self.app = create_app(self.root, port=8765, service=self.service)
        self.client = TestClient(self.app, base_url=ORIGIN)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def propose(self) -> dict:
        changes, revisions = self.agent_changes()
        response = self.client.post(
            f"{API}/previews/skill",
            json={"skill": "design-start", "changes": changes, "read_revisions": revisions},
            headers={"Authorization": "Bearer " + self.tokens["Coding agent"]},
        )
        self.assertEqual(200, response.status_code, response.text)
        return response.json()

    def login(self, name: str) -> dict:
        self.client.cookies.clear()
        response = self.client.post(f"{API}/auth/exchange", json={"token": self.tokens[name]}, headers={"Origin": ORIGIN})
        self.assertEqual(200, response.status_code, response.text)
        return {"Origin": ORIGIN, "X-Prism-CSRF": response.json()["csrf_token"]}

    def bearer_headers(self, name: str) -> dict:
        return {"Authorization": "Bearer " + self.tokens[name]}

    def test_the_agent_is_refused_over_http_and_the_session_actor_is_marked(self) -> None:
        preview = self.propose()
        self.assertEqual("awaiting-approval", preview["approval"]["state"])
        refused = self.client.post(f"{API}/apply", json={"preview_id": preview["preview_id"], "operation_id": "agent-op"}, headers=self.bearer_headers("Coding agent"))
        self.assertEqual((403, "approval_required"), (refused.status_code, refused.json()["error"]["code"]))
        by_token = self.client.get(f"{API}/discover", headers=self.bearer_headers("Dana")).json()["participant"]
        self.assertEqual((["designer"], False), (by_token["roles"], by_token["session"]))
        self.login("Dana")
        by_cookie = self.client.get(f"{API}/discover").json()["participant"]
        self.assertEqual((["designer"], True), (by_cookie["roles"], by_cookie["session"]))
        self.assertEqual((["designer"], True), (self.client.get(f"{API}/auth/session").json()["actor"]["roles"], self.client.get(f"{API}/auth/session").json()["actor"]["session"]))

    def test_the_cookie_route_approves_and_the_same_token_over_bearer_is_refused(self) -> None:
        preview = self.propose()
        # The same human token, as a Bearer token: refused, even with a valid review.
        review = self.service.get_preview(self.designer, preview["preview_id"])["approval"]["review_revision"]
        refused = self.client.post(
            f"{API}/apply",
            json={"preview_id": preview["preview_id"], "operation_id": "bearer-op", "review_revision": review, "semantic_review_acknowledged": True},
            headers=self.bearer_headers("Dana"),
        )
        self.assertEqual((403, "approval_requires_board_session"), (refused.status_code, refused.json()["error"]["code"]))
        headers = self.login("Dana")
        listed = self.client.get(f"{API}/proposals").json()
        self.assertEqual([preview["preview_id"]], [item["preview_id"] for item in listed["proposals"]])
        shown = self.client.get(f"{API}/previews/{preview['preview_id']}").json()
        self.assertEqual("awaiting-approval", shown["approval"]["state"])
        review = shown["approval"]["review_revision"]
        missing = self.client.post(f"{API}/apply", json={"preview_id": preview["preview_id"], "operation_id": "web-op"}, headers=headers)
        self.assertEqual((409, "approval_review_required"), (missing.status_code, missing.json()["error"]["code"]))
        loose = self.client.post(
            f"{API}/apply",
            json={"preview_id": preview["preview_id"], "operation_id": "web-op", "review_revision": review, "semantic_review_acknowledged": "true"},
            headers=headers,
        )
        self.assertEqual((409, "approval_review_required"), (loose.status_code, loose.json()["error"]["code"]))
        applied = self.client.post(
            f"{API}/apply",
            json={"preview_id": preview["preview_id"], "operation_id": "web-op", "review_revision": review, "semantic_review_acknowledged": True},
            headers=headers,
        )
        self.assertEqual(200, applied.status_code, applied.text)
        self.assertEqual(("applied", self.designer.participant_id), (applied.json()["state"], applied.json()["actor"]["participant_id"]))
        self.assertEqual(self.agent.participant_id, applied.json()["proposer"]["participant_id"])
        self.assertIn("status: in-design", self.read(FEATURE))

    def test_the_decline_route_needs_a_session_and_a_reason(self) -> None:
        preview = self.propose()
        refused = self.client.post(f"{API}/proposals/{preview['preview_id']}/decline", json={"reason": "No."}, headers=self.bearer_headers("Dana"))
        self.assertEqual((403, "approval_requires_board_session"), (refused.status_code, refused.json()["error"]["code"]))
        self.client.cookies.clear()
        po_headers = self.login("Pat")
        wrong_role = self.client.post(f"{API}/proposals/{preview['preview_id']}/decline", json={"reason": "No."}, headers=po_headers)
        self.assertEqual((403, "role_required"), (wrong_role.status_code, wrong_role.json()["error"]["code"]))
        headers = self.login("Dana")
        bad = self.client.post(f"{API}/proposals/{preview['preview_id']}/decline", json={"reason": 5}, headers=headers)
        self.assertEqual((400, "invalid_decline"), (bad.status_code, bad.json()["error"]["code"]))
        declined = self.client.post(f"{API}/proposals/{preview['preview_id']}/decline", json={"reason": "Not this sprint."}, headers=headers)
        self.assertEqual(200, declined.status_code, declined.text)
        again = self.client.post(f"{API}/proposals/{preview['preview_id']}/decline", json={"reason": "Again."}, headers=headers)
        self.assertEqual((409, "proposal_declined"), (again.status_code, again.json()["error"]["code"]))
        self.assertEqual([], self.client.get(f"{API}/proposals").json()["proposals"])

    def test_the_preview_route_serves_only_a_reviewer(self) -> None:
        preview = self.propose()
        self.login("Pat")
        hidden = self.client.get(f"{API}/previews/{preview['preview_id']}")
        self.assertEqual((404, "preview_not_found"), (hidden.status_code, hidden.json()["error"]["code"]))
        self.login("Dana")
        self.assertEqual(200, self.client.get(f"{API}/previews/{preview['preview_id']}").status_code)

    def test_a_repair_is_previewed_by_operation_id_over_http(self) -> None:
        headers = self.login("Dana")
        missing = self.client.post(f"{API}/previews/transition", json={"action": "operation-repair", "operation_id": "no-such-operation"}, headers=headers)
        self.assertEqual((404, "operation_not_found"), (missing.status_code, missing.json()["error"]["code"]))
        invalid = self.client.post(f"{API}/previews/transition", json={"action": "design-start"}, headers=headers)
        self.assertEqual((400, "invalid_preview"), (invalid.status_code, invalid.json()["error"]["code"]))


class McpApprovalTests(_Transport, GatedBoardCase, unittest.IsolatedAsyncioTestCase):
    """The same agent token over HTTP and MCP gets equal results; a human token over MCP never approves."""

    def tool(self, result) -> dict:
        self.assertFalse(result.is_error, result)
        return result.structured_content if result.structured_content is not None else json.loads(result.content[0].text)

    def error_text(self, result) -> str:
        self.assertTrue(result.is_error, result)
        return " ".join(part.text for part in result.content if getattr(part, "type", None) == "text")

    async def test_equal_credentials_get_equal_results_and_mcp_never_approves(self) -> None:
        app = create_app(self.root, port=8765, service=self.service)
        async with app.router.lifespan_context(app):
            transport = httpx2.ASGITransport(app=app)
            changes, revisions = self.agent_changes()
            agent_headers = {"Authorization": "Bearer " + self.tokens["Coding agent"]}
            async with httpx2.AsyncClient(transport=transport, base_url=ORIGIN, headers=agent_headers) as http:
                async with streamable_http_client(ORIGIN + "/mcp", http_client=http) as (reader, writer):
                    async with ClientSession(reader, writer) as agent:
                        await agent.initialize()
                        preview = self.tool(await agent.call_tool("preview_skill", {"skill": "design-start", "changes": changes, "read_revisions": revisions}))
                        self.assertEqual("awaiting-approval", preview["approval"]["state"])
                        over_http = (await http.get(f"{API}/proposals")).json()
                        over_mcp = self.tool(await agent.call_tool("list_proposals", {}))
                        self.assertEqual(over_http, over_mcp)
                        self.assertEqual([preview["preview_id"]], [item["preview_id"] for item in over_mcp["proposals"]])
                        refused = await agent.call_tool("apply", {"preview_id": preview["preview_id"], "operation_id": "agent-op"})
                        self.assertIn("approval_required", self.error_text(refused))
                        http_refused = await http.post(f"{API}/apply", json={"preview_id": preview["preview_id"], "operation_id": "agent-op"}, headers={})
                        self.assertEqual("approval_required", http_refused.json()["error"]["code"])
                        declined = await agent.call_tool("decline_proposal", {"preview_id": preview["preview_id"], "reason": "mine"})
                        self.assertIn("approval_required", self.error_text(declined))
            human_headers = {"Authorization": "Bearer " + self.tokens["Dana"]}
            async with httpx2.AsyncClient(transport=transport, base_url=ORIGIN, headers=human_headers) as http:
                async with streamable_http_client(ORIGIN + "/mcp", http_client=http) as (reader, writer):
                    async with ClientSession(reader, writer) as human:
                        await human.initialize()
                        review = self.review(self.designer, preview)
                        arguments = {"preview_id": preview["preview_id"], "operation_id": "human-op", "review_revision": review, "semantic_review_acknowledged": True}
                        over_mcp_error = self.error_text(await human.call_tool("apply", arguments))
                        over_http_error = (await http.post(f"{API}/apply", json={k: v for k, v in arguments.items()})).json()
                        self.assertIn("approval_requires_board_session", over_mcp_error)
                        self.assertEqual("approval_requires_board_session", over_http_error["error"]["code"])
                        self.assertIn("approval_requires_board_session", self.error_text(await human.call_tool("decline_proposal", {"preview_id": preview["preview_id"], "reason": "no"})))
                        discovered = self.tool(await human.call_tool("discover", {}))
                        self.assertEqual((["designer"], False), (discovered["participant"]["roles"], discovered["participant"]["session"]))
                        self.assertEqual(4, discovered["mcp_contract"])
                        self.assertEqual([preview["preview_id"]], [item["preview_id"] for item in discovered["pending_proposals"]])
                        self.assertIn("role_model", discovered["capability"])
        self.assertIn("status: ready-for-design", self.read(FEATURE), "nothing was approved over a token")


if __name__ == "__main__":
    unittest.main()
