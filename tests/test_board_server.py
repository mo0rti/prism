"""Focused HTTP transport and browser-session regressions for Prism Board."""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from starlette.testclient import TestClient

from prism_cli.board_server import MAX_REQUEST_BYTES, create_app
from prism_cli.board_service import BoardService
from prism_cli.workflow_install import apply_install, plan_install
from tests.test_core_workflow_fixture import _feature_page, _write_index


class _BoardError(Exception):
    def __init__(self, code: str, message: str, status: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


class _Actor:
    def __init__(self, kind: str = "human", *, participant_id: str = "participant-1") -> None:
        self.participant_id = participant_id
        self.name = "Local Human" if kind == "human" else "Local Agent"
        self.kind = kind
        self.writable = True
        self.board_id = "board-1"
        self.workflow_version = "1"
        self.scopes = ["read", "write"]
        self._server_proof = "must-not-leave-service"


class _Service:
    def __init__(self) -> None:
        self.started = False
        self.closed = False
        self.revoked: set[str] = set()
        self.calls: list[tuple[str, str, tuple[Any, ...], dict[str, Any]]] = []
        self.version = "1"
        self.graph_checks = 0

    def start(self) -> None:
        self.started = True

    def close(self) -> None:
        self.closed = True

    def validate_graph_inputs(self) -> None:
        self.graph_checks += 1

    def authenticate(self, token: str) -> _Actor:
        if token in self.revoked or token not in {"human-token", "agent-token", "secret-token"}:
            raise _BoardError("invalid_token", f"invalid token {token}", 401)
        actor = _Actor("agent" if token == "agent-token" else "human")
        actor.workflow_version = self.version
        return actor

    def _result(self, method: str, actor: _Actor, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append((method, actor.participant_id, args, kwargs))
        return {"schema_version": 1, "method": method, "args": list(args), "kwargs": kwargs}

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


class BoardServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.service = _Service()
        self.app = create_app(self.root, port=8765, service=self.service)
        self.client = TestClient(self.app, base_url="http://127.0.0.1:8765")
        self.client_context = self.client.__enter__()
        self.origin = "http://127.0.0.1:8765"

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def login(self, token: str = "human-token") -> tuple[dict[str, Any], str]:
        response = self.client.post(
            "/api/board/v1/auth/exchange",
            json={"token": token},
            headers={"Origin": self.origin},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json(), response.headers["set-cookie"]

    def test_public_login_shell_and_protected_graph(self) -> None:
        marker = "private-wiki-context-never-on-login-page"
        (self.root / "private-note.txt").write_text(marker, encoding="utf-8")
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Connect to your Prism board", page.text)
        self.assertNotIn(marker, page.text)
        self.assertIn("nonce-", page.headers["content-security-policy"])
        self.assertEqual(page.headers["x-frame-options"], "DENY")
        self.assertEqual(page.headers["cache-control"], "no-store")
        self.assertGreaterEqual(self.service.graph_checks, 1)
        self.assertEqual(self.client.get("/data.json").status_code, 401)

        self.login()
        data = self.client.get("/data.json")
        self.assertEqual(data.status_code, 200)
        self.assertEqual(set(data.json()), {"epoch", "version", "envelope"})
        live_page = self.client.get("/")
        self.assertEqual(live_page.status_code, 200)
        self.assertIn("frame-ancestors 'none'", live_page.headers["content-security-policy"])
        self.assertRegex(live_page.text, r'<script nonce="[^"]+">')

    def test_browser_token_exchange_csrf_and_session_revalidation(self) -> None:
        result, cookie_header = self.login()
        csrf = result["csrf_token"]
        self.assertEqual(result["actor"]["kind"], "human")
        self.assertNotIn("_server_proof", json.dumps(result))
        self.assertNotIn("human-token", cookie_header)
        self.assertIn("HttpOnly", cookie_header)
        self.assertIn("SameSite=strict", cookie_header)
        self.assertIn("Path=/", cookie_header)
        self.assertNotIn("Domain=", cookie_header)
        expected_tag = hashlib.sha256(str(self.root.resolve()).encode("utf-8")).hexdigest()[:16]
        self.assertIn(f"prism_board_{expected_tag}_session=", cookie_header)

        session = self.client.get("/api/board/v1/auth/session")
        self.assertEqual(session.status_code, 200)
        self.assertEqual(session.json()["csrf_token"], csrf)
        self.assertNotIn("token", session.json())

        payload = {"preview_id": "preview-1", "operation_id": "op-1"}
        no_csrf = self.client.post("/api/board/v1/apply", json=payload, headers={"Origin": self.origin})
        self.assertEqual(no_csrf.status_code, 403)
        self.assertFalse(any(call[0] == "apply" for call in self.service.calls))

        applied = self.client.post(
            "/api/board/v1/apply",
            json=payload,
            headers={"Origin": self.origin, "X-Prism-CSRF": csrf},
        )
        self.assertEqual(applied.status_code, 200, applied.text)
        self.assertEqual(applied.json()["method"], "apply")
        self.assertEqual(self.service.calls[-1][1], "participant-1")

        listed_without_csrf = self.client.post(
            "/api/board/v1/workspace/list",
            json={"prefix": "knowledge/intake"},
            headers={"Origin": self.origin},
        )
        self.assertEqual(listed_without_csrf.status_code, 403)
        listed = self.client.post(
            "/api/board/v1/workspace/list",
            json={"prefix": "knowledge/intake", "cursor": "C-1"},
            headers={"Origin": self.origin, "X-Prism-CSRF": csrf},
        )
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(self.service.calls[-1][0], "list_workspace")

        self.service.revoked.add("human-token")
        revoked = self.client.get("/api/board/v1/discover")
        self.assertEqual(revoked.status_code, 401)
        self.assertEqual(revoked.json()["error"]["code"], "unauthorized")
        self.assertIn("Max-Age=0", revoked.headers["set-cookie"])
        revoked_write = self.client.post(
            "/api/board/v1/apply",
            json=payload,
            headers={"Origin": self.origin, "X-Prism-CSRF": csrf},
        )
        self.assertEqual(revoked_write.status_code, 401)
        self.assertFalse(any(call[0] == "apply" and call[1] == "participant-1" for call in self.service.calls[2:]))

    def test_changed_contract_invalidates_browser_session(self) -> None:
        self.login()
        self.service.version = "2"
        response = self.client.get("/api/board/v1/discover")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "session_invalidated")

    def test_http_routes_delegate_the_approved_service_contract(self) -> None:
        token = "secret-token"
        headers = {"Authorization": f"Bearer {token}"}
        cases = [
            ("GET", "/api/board/v1/discover", None, "discover"),
            ("POST", "/api/board/v1/workspace/read", {"paths": ["knowledge/wiki/BOARD.md"]}, "read_workspace"),
            ("POST", "/api/board/v1/workspace/list", {"prefix": "knowledge/intake", "cursor": "C-1"}, "list_workspace"),
            ("POST", "/api/board/v1/query", {"kind": "transition-preflight", "value": "F-1", "action": "design-start"}, "query"),
            ("GET", "/api/board/v1/skills", None, "list_skills"),
            ("GET", "/api/board/v1/skills/setup-project", None, "get_skill"),
            ("POST", "/api/board/v1/previews/transition", {"feature_id": "F-1", "action": "design-start"}, "preview_transition"),
            ("POST", "/api/board/v1/previews/skill", {"skill": "dev-start", "changes": []}, "preview_skill"),
            ("POST", "/api/board/v1/apply", {"preview_id": "P-1", "operation_id": "O-1"}, "apply"),
            ("GET", "/api/board/v1/operations/O-1", None, "operation"),
            ("POST", "/api/board/v1/operations/O-1/recover", {}, "recover"),
            ("GET", "/api/board/v1/changes?cursor=C-1", None, "changes"),
        ]
        for method, path, body, service_method in cases:
            request_headers = dict(headers)
            if method == "POST" and service_method not in {"apply", "recover"}:
                request_headers["Origin"] = self.origin
                # Preview and read calls from browsers use CSRF; bearer calls
                # remain accepted for local CLI/MCP clients without Origin.
                request_headers.pop("Origin")
            response = self.client.request(method, path, json=body, headers=request_headers)
            self.assertEqual(response.status_code, 200, f"{method} {path}: {response.text}")
            self.assertEqual(response.json()["method"], service_method)
        self.assertNotIn("create_participant", [call[0] for call in self.service.calls])
        self.assertNotIn("revoke_participant", [call[0] for call in self.service.calls])

    def test_recover_forwards_review_revision_and_strict_acknowledgement(self) -> None:
        bearer_headers = {"Authorization": "Bearer human-token"}
        legacy = self.client.post("/api/board/v1/operations/O-1/recover", headers=bearer_headers)
        self.assertEqual(200, legacy.status_code, legacy.text)
        self.assertEqual(("O-1", None, False), self.service.calls[-1][2])

        session, _ = self.login()
        headers = {"Origin": self.origin, "X-Prism-CSRF": session["csrf_token"]}
        response = self.client.post(
            "/api/board/v1/operations/O-1/recover",
            json={"review_revision": "review-1", "semantic_review_acknowledged": True},
            headers=headers,
        )
        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual(("O-1", "review-1", True), self.service.calls[-1][2])

        before = len(self.service.calls)
        for payload in (
            {"review_revision": 7, "semantic_review_acknowledged": True},
            {"review_revision": "review-1", "semantic_review_acknowledged": 1},
            {"review_revision": "review-1", "unexpected": "value"},
        ):
            invalid = self.client.post("/api/board/v1/operations/O-1/recover", json=payload, headers=headers)
            self.assertEqual(400, invalid.status_code, invalid.text)
        self.assertEqual(before, len(self.service.calls), "invalid recovery fields reached BoardService")

    def test_list_and_query_routes_integrate_with_real_board_service(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt = apply_install(root, plan_install(root, name="Document review", platforms=["backend"]))
            self.assertEqual("applied", receipt["status"])
            pending = root / "knowledge/intake/pending/document-review-brief"
            pending.mkdir(parents=True)
            (pending / "brief.md").write_text("# Document review\n", encoding="utf-8")
            feature = root / "knowledge/wiki/features/F-001-document-review.md"
            feature.write_text(_feature_page(), encoding="utf-8")
            _write_index(root, "raw", "po")
            original_feature = feature.read_text(encoding="utf-8")

            service = BoardService(root)
            self.addCleanup(service.close)
            grant = service.create_participant("Read-only test client", "agent")
            app = create_app(root, port=8766, service=service)
            with TestClient(app, base_url="http://127.0.0.1:8766") as client:
                headers = {"Authorization": f"Bearer {grant['token']}"}
                listed = client.post(
                    "/api/board/v1/workspace/list",
                    json={"prefix": "knowledge/intake/pending"},
                    headers=headers,
                )
                self.assertEqual(200, listed.status_code, listed.text)
                self.assertIn("knowledge/intake/pending/document-review-brief/brief.md", [item["path"] for item in listed.json()["files"]])

                queried = client.post(
                    "/api/board/v1/query",
                    json={"kind": "transition-preflight", "value": "F-001", "action": "po-specify"},
                    headers=headers,
                )
                self.assertEqual(200, queried.status_code, queried.text)
                self.assertEqual("po-specify", queried.json()["facts"]["transition"]["action"])
                self.assertEqual("read-only", queried.json()["capability"]["mode"])
                self.assertEqual(original_feature, feature.read_text(encoding="utf-8"))

    def test_host_origin_mixed_credential_and_body_size_guards(self) -> None:
        wrong_host = self.client.get("/api/board/v1/discover", headers={"Host": "attacker.example"})
        self.assertEqual(wrong_host.status_code, 400)
        self.assertEqual(wrong_host.headers["x-frame-options"], "DENY")
        self.assertIn("frame-ancestors 'none'", wrong_host.headers["content-security-policy"])
        same_site = self.client.get("/api/board/v1/discover", headers={"Sec-Fetch-Site": "same-site"})
        self.assertEqual(same_site.status_code, 400)
        cross_origin = self.client.post(
            "/api/board/v1/auth/exchange",
            json={"token": "human-token"},
            headers={"Origin": "http://evil.example:8765"},
        )
        self.assertEqual(cross_origin.status_code, 400)
        unsupported_content = self.client.post(
            "/api/board/v1/auth/exchange",
            content="token=human-token",
            headers={"Origin": self.origin, "Content-Type": "application/x-www-form-urlencoded"},
        )
        self.assertEqual(unsupported_content.status_code, 415)

        self.login()
        csrf = self.client.get("/api/board/v1/auth/session").json()["csrf_token"]
        cross_origin_write = self.client.post(
            "/api/board/v1/apply",
            json={"preview_id": "preview-1", "operation_id": "op-cross-origin"},
            headers={"Origin": "http://evil.example:8765", "X-Prism-CSRF": csrf},
        )
        self.assertEqual(cross_origin_write.status_code, 400)
        self.assertFalse(any(call[0] == "apply" for call in self.service.calls))
        mixed = self.client.get("/api/board/v1/discover", headers={"Authorization": "Bearer human-token"})
        self.assertEqual(mixed.status_code, 400)
        oversized = self.client.post(
            "/api/board/v1/auth/exchange",
            content=b"x" * (MAX_REQUEST_BYTES + 1),
            headers={"Origin": self.origin, "Content-Type": "application/json"},
        )
        self.assertEqual(oversized.status_code, 413)

    def test_browser_exchange_rejects_agent_grants_and_redacts_credentials(self) -> None:
        agent = self.client.post(
            "/api/board/v1/auth/exchange",
            json={"token": "agent-token"},
            headers={"Origin": self.origin},
        )
        self.assertEqual(agent.status_code, 403)
        self.assertEqual(agent.json()["error"]["code"], "human_grant_required")
        raw = "this-is-a-bad-secret-token"
        invalid = self.client.post(
            "/api/board/v1/auth/exchange",
            json={"token": raw},
            headers={"Origin": self.origin},
        )
        self.assertEqual(invalid.status_code, 401)
        self.assertNotIn(raw, invalid.text)


if __name__ == "__main__":
    unittest.main()
