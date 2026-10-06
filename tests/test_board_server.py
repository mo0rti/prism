"""Focused HTTP transport and browser-session regressions for Prism Board."""

from __future__ import annotations

import asyncio
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import Mock, patch

from starlette.testclient import TestClient

from prism_cli.board_server import MAX_REQUEST_BYTES, _LiveGraph, _SnapshotRefreshingService, create_app, quiet_connection_reset_handler
from prism_cli.board_service import BoardError, BoardService
from prism_cli.wiki_transitions import FingerprintCache
from prism_cli.workflow_install import apply_install, plan_install
from tests.test_core_workflow_fixture import _feature_page, _write_index
from tests.wiki_files import write_index, write_status_board
from tests import real_temp  # noqa: F401


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

    def read_workspace(self, actor: _Actor, paths: list[str], cursor: str | None = None) -> dict[str, Any]:
        return self._result("read_workspace", actor, paths, cursor)

    def list_workspace(self, actor: _Actor, prefix: str = "knowledge", cursor: str | None = None) -> dict[str, Any]:
        return self._result("list_workspace", actor, prefix, cursor)

    def query(self, actor: _Actor, kind: str, value: str | None = None, action: str | None = None, cursor: str | None = None) -> dict[str, Any]:
        return self._result("query", actor, kind, value, action, cursor)

    def list_skills(self, actor: _Actor) -> dict[str, Any]:
        return self._result("list_skills", actor)

    def get_skill(self, actor: _Actor, name: str) -> dict[str, Any]:
        return self._result("get_skill", actor, name)

    def preview_transition(self, actor: _Actor, feature_id: str, action: str, inputs: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._result("preview_transition", actor, feature_id, action, inputs)

    def preview_skill(self, actor: _Actor, skill: str, changes: list[dict[str, Any]], moves: list[dict[str, Any]] | None = None, read_revisions: dict[str, str] | None = None) -> dict[str, Any]:
        if skill == "rejected-details":
            raise BoardError(
                "clarify_answer_unlinked",
                "Updated `Summary` must include an answer; the credential was secret-token.",
                409,
                {"section": "Summary", "resolved_questions": ["2"], "resolved_answers": {"2": "Answer starts with secret-token"}},
            )
        return self._result("preview_skill", actor, skill, changes, moves, read_revisions)

    def apply(self, actor: _Actor, preview_id: str, operation_id: str) -> dict[str, Any]:
        return self._result("apply", actor, preview_id, operation_id)

    def operation(self, actor: _Actor, operation_id: str) -> dict[str, Any]:
        return self._result("operation", actor, operation_id)

    def recover(self, actor: _Actor, operation_id: str, review_revision: str | None = None, semantic_review_acknowledged: bool = False, abandon: bool = False) -> dict[str, Any]:
        return self._result("recover", actor, operation_id, review_revision, semantic_review_acknowledged, **({"abandon": True} if abandon else {}))

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

    def test_token_exchange_removes_expired_sessions_and_keeps_live_ones(self) -> None:
        sessions = self.app.state.board_sessions
        self.login()
        self.client.cookies.clear()
        self.login()
        self.client.cookies.clear()
        expired_id, live_id = list(sessions)
        sessions[expired_id].expires_at = 0.0

        result, _cookie = self.login()

        self.assertNotIn(expired_id, sessions)
        self.assertIn(live_id, sessions)
        self.assertEqual(2, len(sessions))
        new_id = next(session_id for session_id in sessions if session_id != live_id)
        self.assertEqual(result["csrf_token"], sessions[new_id].csrf)
        self.assertEqual(200, self.client.get("/api/board/v1/discover").status_code)

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
        self.assertEqual({}, self.service.calls[-1][3])

        abandoned = self.client.post(
            "/api/board/v1/operations/O-1/recover",
            json={"review_revision": "review-1", "semantic_review_acknowledged": True, "abandon": True},
            headers=headers,
        )
        self.assertEqual(200, abandoned.status_code, abandoned.text)
        self.assertEqual(("O-1", "review-1", True), self.service.calls[-1][2])
        self.assertEqual({"abandon": True}, self.service.calls[-1][3])

        before = len(self.service.calls)
        for payload in (
            {"review_revision": 7, "semantic_review_acknowledged": True},
            {"review_revision": "review-1", "semantic_review_acknowledged": 1},
            {"review_revision": "review-1", "semantic_review_acknowledged": True, "abandon": "true"},
            {"review_revision": "review-1", "semantic_review_acknowledged": True, "abandon": 1},
            {"review_revision": "review-1", "unexpected": "value"},
        ):
            invalid = self.client.post("/api/board/v1/operations/O-1/recover", json=payload, headers=headers)
            self.assertEqual(400, invalid.status_code, invalid.text)
        self.assertEqual(before, len(self.service.calls), "invalid recovery fields reached BoardService")

    def test_list_and_query_routes_integrate_with_real_board_service(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt = apply_install(root, plan_install(root, name="Document review", apps=["backend"]))
            self.assertEqual("applied", receipt["status"])
            pending = root / "knowledge/intake/pending/2026-10-06-document-review-brief"
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
                self.assertIn("knowledge/intake/pending/2026-10-06-document-review-brief/brief.md", [item["path"] for item in listed.json()["files"]])

                queried = client.post(
                    "/api/board/v1/query",
                    json={"kind": "transition-preflight", "value": "F-001", "action": "po-specify"},
                    headers=headers,
                )
                self.assertEqual(200, queried.status_code, queried.text)
                self.assertEqual("po-specify", queried.json()["facts"]["transition"]["action"])
                self.assertEqual("read-only", queried.json()["capability"]["mode"])
                self.assertEqual(original_feature, feature.read_text(encoding="utf-8"))

    def test_read_and_query_routes_forward_a_cursor_and_validate_its_type(self) -> None:
        headers = {"Authorization": "Bearer secret-token"}
        read = self.client.post("/api/board/v1/workspace/read", json={"paths": ["knowledge/wiki/BOARD.md"], "cursor": "C-2"}, headers=headers)
        self.assertEqual(200, read.status_code, read.text)
        self.assertEqual((["knowledge/wiki/BOARD.md"], "C-2"), self.service.calls[-1][2])
        first = self.client.post("/api/board/v1/workspace/read", json={"paths": ["knowledge/wiki/BOARD.md"]}, headers=headers)
        self.assertEqual(200, first.status_code, first.text)
        self.assertEqual((["knowledge/wiki/BOARD.md"], None), self.service.calls[-1][2])
        query = self.client.post("/api/board/v1/query", json={"kind": "owner", "value": "po", "cursor": "C-3"}, headers=headers)
        self.assertEqual(200, query.status_code, query.text)
        self.assertEqual(("owner", "po", None, "C-3"), self.service.calls[-1][2])
        before = len(self.service.calls)
        for path, body in (
            ("/api/board/v1/workspace/read", {"paths": ["knowledge/wiki/BOARD.md"], "cursor": 7}),
            ("/api/board/v1/query", {"kind": "owner", "value": "po", "cursor": ["C-3"]}),
            ("/api/board/v1/query", {"kind": "owner", "value": "po", "unexpected": "x"}),
        ):
            rejected = self.client.post(path, json=body, headers=headers)
            self.assertEqual(400, rejected.status_code, rejected.text)
        self.assertEqual(before, len(self.service.calls), "invalid cursor fields reached BoardService")

    def test_bearer_clients_can_page_workspace_reads_and_queries_over_http(self) -> None:
        from prism_cli import board_reads

        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertEqual("applied", apply_install(root, plan_install(root, name="Document review", apps=["backend"]))["status"])
            ids = [f"F-{number:03d}" for number in range(1, 15)]
            for feature_id in ids:
                page = _feature_page().replace("F-001", feature_id).replace("Document review", f"Document review {feature_id}")
                (root / f"knowledge/wiki/features/{feature_id}-document-review.md").write_text(page, encoding="utf-8", newline="\n")
            write_status_board(root, "".join(f"| {feature_id} | Document review {feature_id} | raw | po | not-needed |\n" for feature_id in ids))
            write_index(root)
            large = root / "knowledge/wiki/features/F-001-document-review.md"
            large.write_text(large.read_text(encoding="utf-8") + "\nA long paragraph of review notes. " * 1200 + "\n", encoding="utf-8", newline="\n")
            expected = large.read_text(encoding="utf-8")
            service = BoardService(root)
            self.addCleanup(service.close)
            headers = {"Authorization": f"Bearer {service.create_participant('Paging client', 'agent')['token']}"}
            app = create_app(root, port=8767, service=service)
            with TestClient(app, base_url="http://127.0.0.1:8767") as client, patch.object(board_reads, "STRUCTURED_BUDGET_CHARS", 8000):
                path = "knowledge/wiki/features/F-001-document-review.md"
                body: dict[str, Any] = {"paths": [path]}
                text, pages = "", 0
                while True:
                    response = client.post("/api/board/v1/workspace/read", json=body, headers=headers)
                    self.assertEqual(200, response.status_code, response.text)
                    page = response.json()
                    pages += 1
                    text += page["files"][0]["content"]
                    self.assertEqual(len(text) - len(page["files"][0]["content"]), page["files"][0]["offset"])
                    if page["next_cursor"] is None:
                        break
                    body = {"paths": [path], "cursor": page["next_cursor"]}
                    self.assertLess(pages, 20)
                self.assertGreater(pages, 2)
                self.assertEqual(expected, text)
                wrong = client.post("/api/board/v1/workspace/read", json={"paths": [path.replace("F-001", "F-002")], "cursor": page.get("next_cursor") or body["cursor"]}, headers=headers)
                self.assertEqual(400, wrong.status_code, wrong.text)
                self.assertEqual("invalid_cursor", wrong.json()["error"]["code"])

                found, query_body, queries = [], {"kind": "owner", "value": "po"}, 0
                budget = patch.object(board_reads, "STRUCTURED_BUDGET_CHARS", 4000)
                budget.start()
                self.addCleanup(budget.stop)
                while True:
                    response = client.post("/api/board/v1/query", json=query_body, headers=headers)
                    self.assertEqual(200, response.status_code, response.text)
                    page = response.json()
                    queries += 1
                    found.extend(item["id"] for item in page["facts"]["features"])
                    if page["next_cursor"] is None:
                        break
                    query_body = {"kind": "owner", "value": "po", "cursor": page["next_cursor"]}
                    self.assertLess(queries, 20)
                self.assertGreater(queries, 1)
                self.assertEqual(ids, found)
                other = client.post("/api/board/v1/query", json={"kind": "owner", "value": "dev", "cursor": query_body["cursor"]}, headers=headers)
                self.assertEqual(("invalid_cursor", 400), (other.json()["error"]["code"], other.status_code))

    def test_apply_refreshes_the_graph_snapshot_before_the_response_returns(self) -> None:
        # A one-hour poll interval keeps the background poller out of the way,
        # so only the write path can make the snapshot current.
        with TemporaryDirectory() as temporary, patch("prism_cli.board_server.GRAPH_POLL_SECONDS", 3600.0):
            root = Path(temporary)
            apply_install(root, plan_install(root, name="Document review", apps=["backend"]))
            source = root / "knowledge/intake/processed/2026-10-06-document-review-brief/brief.md"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"# Document review\nRecord a summary and outcome.\n")
            feature = root / "knowledge/wiki/features/F-001-document-review.md"
            feature.write_bytes(
                _feature_page()
                .replace("status: raw", "status: ready-for-design")
                .replace("owner: po", "owner: designer")
                .replace("| po | open |", "| po | resolved: Summarize key points. |")
                .encode("utf-8")
            )
            _write_index(root, "ready-for-design", "designer")

            service = BoardService(root)
            self.addCleanup(service.close)
            grant = service.create_participant("Refresh test human", "human", True)
            app = create_app(root, port=8767, service=service)
            with TestClient(app, base_url="http://127.0.0.1:8767") as client:
                headers = {"Authorization": f"Bearer {grant['token']}"}

                def stage() -> tuple[int, str]:
                    response = client.get("/data.json", headers=headers)
                    self.assertEqual(200, response.status_code, response.text)
                    payload = response.json()
                    node = next(item for item in payload["envelope"]["facts"]["nodes"] if item["id"] == "F-001")
                    return payload["version"], node["status"]

                version_before, status_before = stage()
                self.assertEqual("ready-for-design", status_before)
                preview = client.post(
                    "/api/board/v1/previews/transition",
                    json={"feature_id": "F-001", "action": "design-start", "inputs": {"semantic_review_acknowledged": True}},
                    headers=headers,
                )
                self.assertEqual(200, preview.status_code, preview.text)
                self.assertTrue(preview.json()["applicable"], preview.text)
                self.assertEqual((version_before, status_before), stage(), "Previewing must not change the snapshot.")

                applied = client.post(
                    "/api/board/v1/apply",
                    json={"preview_id": preview.json()["preview_id"], "operation_id": "refresh-operation"},
                    headers=headers,
                )
                self.assertEqual(200, applied.status_code, applied.text)
                self.assertEqual("applied", applied.json()["state"])
                # No sleep: the very next read already reflects the applied write.
                version_after, status_after = stage()
                self.assertEqual("in-design", status_after)
                self.assertGreater(version_after, version_before)
                self.assertEqual((version_after, status_after), stage(), "A read after the refresh must not rebuild the snapshot again.")

    def test_only_the_graph_poller_reuses_file_hashes(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            apply_install(root, plan_install(root, name="Document review", apps=["backend"]))
            source = root / "knowledge/intake/processed/2026-10-06-document-review-brief/brief.md"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"# Document review\nRecord a summary and outcome.\n")
            feature = root / "knowledge/wiki/features/F-001-document-review.md"
            feature.write_bytes(
                _feature_page()
                .replace("status: raw", "status: ready-for-design")
                .replace("owner: po", "owner: designer")
                .replace("| po | open |", "| po | resolved: Summarize key points. |")
                .encode("utf-8")
            )
            _write_index(root, "ready-for-design", "designer")

            service = BoardService(root).start()
            try:
                self.assert_poller_alone_reuses_file_hashes(root, service)
            finally:
                service.close()

    def assert_poller_alone_reuses_file_hashes(self, root: Path, service: BoardService) -> None:
        grant = service.create_participant("Cache test human", "human", True)
        actor = service.authenticate(grant["token"])
        scans: list[FingerprintCache] = []
        real_scan = FingerprintCache.scan

        request_thread = threading.get_ident()

        def recording_scan(cache: FingerprintCache) -> Any:
            # The live graph's own poller thread may scan at any time on a slow
            # machine; only scans made by this (request) thread are counted.
            if threading.get_ident() == request_thread:
                scans.append(cache)
            return real_scan(cache)

        with patch.object(FingerprintCache, "scan", recording_scan):
            graph = _LiveGraph(root, service.validate_graph_inputs)
            self.assertEqual(1, len(scans), "The poller's own fingerprint goes through its cache.")
            scans.clear()

            preview = service.preview_transition(actor, feature_id="F-001", action="design-start", inputs={"semantic_review_acknowledged": True})
            self.assertTrue(preview["applicable"], preview)
            service.query(actor, "blockers")
            receipt = service.apply(actor, preview["preview_id"], "cache-operation")
            self.assertEqual("applied", receipt["state"])
            self.assertEqual([], scans, "Preview, query and apply hash every file themselves.")

            graph.refresh_now()
            self.assertEqual(1, len(scans))
            graph.refresh_now()
            self.assertEqual(2, len(scans))
            self.assertIs(scans[0], scans[1], "The poller keeps one cache.")

    def test_snapshot_refresh_wrapper_covers_writes_and_leaves_reads_alone(self) -> None:
        class Graph:
            refreshes = 0

            def refresh_now(self) -> None:
                self.refreshes += 1

        class Service:
            def apply(self, actor: Any, preview_id: str, operation_id: str) -> dict[str, Any]:
                if preview_id == "bad":
                    raise _BoardError("preview_blocked", "blocked", 409)
                return {"state": "applied"}

            def recover(self, actor: Any, operation_id: str) -> dict[str, Any]:
                return {"state": "applied"}

            def discover(self, actor: Any) -> dict[str, Any]:
                return {}

        graph = Graph()
        wrapped = _SnapshotRefreshingService(Service(), graph)  # type: ignore[arg-type]
        wrapped.discover(None)
        self.assertEqual(0, graph.refreshes)
        self.assertEqual({"state": "applied"}, wrapped.apply(None, "good", "op-1"))
        self.assertEqual(1, graph.refreshes)
        self.assertEqual({"state": "applied"}, wrapped.recover(None, "op-1"))
        self.assertEqual(2, graph.refreshes)
        with self.assertRaises(_BoardError):
            wrapped.apply(None, "bad", "op-2")
        self.assertEqual(3, graph.refreshes, "A failed write may still have touched files, so it refreshes too.")

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

    def test_rejection_details_reach_the_http_error_body_and_stay_redacted(self) -> None:
        response = self.client.post(
            "/api/board/v1/previews/skill",
            json={"skill": "rejected-details", "changes": []},
            headers={"Authorization": "Bearer secret-token"},
        )
        self.assertEqual(409, response.status_code, response.text)
        error = response.json()["error"]
        self.assertEqual("clarify_answer_unlinked", error["code"])
        self.assertIn("`Summary`", error["message"])
        self.assertEqual(
            {"section": "Summary", "resolved_questions": ["2"], "resolved_answers": {"2": "Answer starts with [redacted]"}},
            error["details"],
        )
        self.assertNotIn("secret-token", response.text)

        # Errors without structured details keep the original two-field body.
        plain = self.client.get("/api/board/v1/discover", headers={"Authorization": "Bearer unknown-token"})
        self.assertEqual(401, plain.status_code)
        self.assertEqual({"code", "message"}, set(plain.json()["error"]))

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

    def test_event_stream_ends_when_the_server_is_stopping(self) -> None:
        stopping = threading.Event()
        app = create_app(self.root, port=8765, service=self.service, should_stop=stopping.is_set)
        with TestClient(app, base_url=self.origin) as client:
            exchange = client.post("/api/board/v1/auth/exchange", json={"token": "human-token"}, headers={"Origin": self.origin})
            self.assertEqual(200, exchange.status_code, exchange.text)
            responses: list[Any] = []
            reader = threading.Thread(target=lambda: responses.append(client.get("/events")), daemon=True)
            reader.start()
            # Without a stop signal the stream never ends, so the reader stays blocked until it is set.
            reader.join(timeout=1.5)
            self.assertTrue(reader.is_alive(), "The event stream ended before the server was stopping.")
            stopping.set()
            reader.join(timeout=20)
            self.assertFalse(reader.is_alive(), "An open event stream held the server after it began stopping.")
        self.assertEqual(200, responses[0].status_code)
        self.assertTrue(responses[0].text.startswith("id: "), responses[0].text)


def _free_port() -> int:
    import socket

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class ConnectionResetHandlerTests(unittest.TestCase):
    """A client that drops its connection costs one quiet line, not a traceback."""

    def test_a_reset_connection_is_reported_once_and_never_as_a_traceback(self) -> None:
        handler = quiet_connection_reset_handler()
        loop = Mock()
        context = {"message": "Exception in callback _call_connection_lost", "exception": ConnectionResetError(10054, "reset by peer")}
        with redirect_stderr(io.StringIO()) as stderr:
            for _ in range(3):
                handler(loop, context)
        loop.default_exception_handler.assert_not_called()
        lines = stderr.getvalue().splitlines()
        self.assertEqual(1, len(lines), lines)
        self.assertIn("connection reset", lines[0])
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_every_other_exception_keeps_the_default_reporting(self) -> None:
        handler = quiet_connection_reset_handler()
        loop = Mock()
        for exception in (ValueError("boom"), ConnectionAbortedError("aborted"), BrokenPipeError("pipe"), None):
            context = {"message": "unexpected", "exception": exception}
            with redirect_stderr(io.StringIO()) as stderr:
                handler(loop, context)
            loop.default_exception_handler.assert_called_with(context)
            self.assertEqual("", stderr.getvalue())
        self.assertEqual(4, loop.default_exception_handler.call_count)

    def test_serve_board_runs_its_event_loop_with_the_handler(self) -> None:
        import uvicorn

        from prism_cli.board_server import serve_board

        installed: list[Any] = []

        async def fake_serve(self: Any, sockets: Any = None) -> None:
            installed.append(asyncio.get_running_loop().get_exception_handler())

        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            apply_install(root, plan_install(root, name="Document review", apps=["backend"]))
            with patch.object(uvicorn.Server, "serve", fake_serve), redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
                serve_board(root, port=_free_port(), open_browser=False)
        self.assertEqual(1, len(installed))
        self.assertIn("quiet_connection_reset_handler", installed[0].__qualname__)

    def test_the_handler_works_as_a_real_event_loop_exception_handler(self) -> None:
        async def run() -> None:
            asyncio.get_running_loop().set_exception_handler(quiet_connection_reset_handler())

            def reset() -> None:
                raise ConnectionResetError(10054, "reset by peer")

            asyncio.get_running_loop().call_soon(reset)
            await asyncio.sleep(0.05)

        with redirect_stderr(io.StringIO()) as stderr, self.assertNoLogs("asyncio", level="ERROR"):
            asyncio.run(run())
        self.assertEqual(1, len(stderr.getvalue().splitlines()))


if __name__ == "__main__":
    unittest.main()
