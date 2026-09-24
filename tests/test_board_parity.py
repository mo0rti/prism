"""Canonical write parity through real human HTTP and agent MCP transports."""

from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import Mock, patch

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
import yaml

from prism_cli.board_server import create_app
from prism_cli.board_service import BoardService
from prism_cli.workflow_install import apply_install, plan_install
from tests.core_workflow_fixture import FEATURE_PATH, INTAKE_ITEM, create_core_workflow_fixture
from tests.test_core_workflow_fixture import CHECK_DATE, _feature_page, _requirement_page, _write_index


ORIGIN = "http://127.0.0.1:8765"
ACTIONS = (
    ("po-handoff", "specified", "po", "ready-for-design", "designer"),
    ("design-start", "ready-for-design", "designer", "in-design", "designer"),
    ("dev-start", "ready-for-dev", "dev", "in-dev", "dev"),
)


class BoardTransportParityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        clock = Mock(wraps=date)
        clock.today.return_value = CHECK_DATE
        for module in ("board_service", "wiki_lint", "wiki_transitions"):
            clock_patch = patch(f"prism_cli.{module}.date", clock)
            clock_patch.start()
            self.addCleanup(clock_patch.stop)

    def prepare(self, root: Path, action: tuple[str, ...], *, blocked: bool) -> None:
        create_core_workflow_fixture(root)
        self.assertEqual("applied", apply_install(root, plan_install(root, name="Document review", platforms=["backend"]))["status"])
        pending = root / INTAKE_ITEM.parent
        pending.rename(root / "knowledge/intake/processed/document-review-brief")
        content = _feature_page().replace("status: raw\n", f"status: {action[1]}\n").replace("owner: po\n", f"owner: {action[2]}\n")
        if not blocked:
            content = content.replace("| po | open |", "| po | resolved: Capture key points and requested follow-up. |")
        # Canonical LF fixture bytes avoid conflating transport parity with the
        # separately disclosed formatting normalization of adopted YAML pages.
        (root / FEATURE_PATH).write_bytes(content.encode("utf-8"))
        _write_index(root, action[1], action[2])
        if action[0] == "dev-start":
            (root / "knowledge/wiki/platform-requirements/F-001-backend.md").write_bytes(_requirement_page("pending").encode("utf-8"))

    @staticmethod
    def snapshot(root: Path) -> dict[str, bytes]:
        return {path.relative_to(root).as_posix(): path.read_bytes() for path in (root / "knowledge").rglob("*") if path.is_file()}

    def tool_data(self, result) -> dict:
        self.assertFalse(result.is_error, result)
        if result.structured_content is not None:
            return result.structured_content
        return json.loads(next(part.text for part in result.content if getattr(part, "type", None) == "text"))

    async def exercise(self, root: Path, action: tuple[str, ...], kind: str, *, blocked: bool) -> dict:
        self.prepare(root, action, blocked=blocked)
        before = self.snapshot(root)
        # The agent's proposal is prepared independently from source bytes, not
        # from a human preview or the service's serializer/write-set helper.
        proposal = before[FEATURE_PATH.as_posix()].decode("utf-8")
        proposal = proposal.replace(f"status: {action[1]}\n", f"status: {action[3]}\n", 1)
        proposal = proposal.replace(f"owner: {action[2]}\n", f"owner: {action[4]}\n", 1)
        service = BoardService(root)
        grant = service.create_participant(f"Parity {kind}", kind, writable=True)
        app = create_app(root, port=8765, service=service)
        try:
            async with app.router.lifespan_context(app):
                transport = httpx2.ASGITransport(app=app)
                if kind == "human":
                    async with httpx2.AsyncClient(transport=transport, base_url=ORIGIN) as http:
                        login = await http.post("/api/board/v1/auth/exchange", json={"token": grant["token"]}, headers={"Origin": ORIGIN})
                        self.assertEqual(200, login.status_code, login.text)
                        headers = {"Origin": ORIGIN, "X-Prism-CSRF": login.json()["csrf_token"]}
                        response = await http.post("/api/board/v1/previews/transition", json={"feature_id": "F-001", "action": action[0], "inputs": {"semantic_review_acknowledged": True}}, headers=headers)
                        self.assertEqual(200, response.status_code, response.text)
                        preview = response.json()
                        self.assertEqual(not blocked, preview["applicable"])
                        self.assertEqual("blocked" if blocked else "ready", preview["classification"])
                        self.assertEqual(before, self.snapshot(root))
                        response = await http.post("/api/board/v1/apply", json={"preview_id": preview["preview_id"], "operation_id": "human-parity"}, headers=headers)
                        if blocked:
                            self.assertEqual(409, response.status_code, response.text)
                            self.assertEqual("preview_blocked", response.json()["error"]["code"])
                        else:
                            self.assertEqual(200, response.status_code, response.text)
                            self.assertEqual("applied", response.json()["state"])
                else:
                    async with httpx2.AsyncClient(transport=transport, base_url=ORIGIN, headers={"Authorization": "Bearer " + grant["token"]}) as http:
                        async with streamable_http_client(ORIGIN + "/mcp", http_client=http) as (reader, writer):
                            async with ClientSession(reader, writer) as client:
                                await client.initialize()
                                skill = self.tool_data(await client.call_tool("get_skill", {"name": action[0]}))["skill"]
                                inventory = self.tool_data(await client.call_tool("list_workspace", {}))
                                self.assertIsNone(inventory["next_cursor"])
                                paths = set(skill["required_workspace_reads"])
                                paths.update(item["path"] for item in inventory["files"] if item["read_support"] == "eligible")
                                reads = self.tool_data(await client.call_tool("read_workspace", {"paths": sorted(paths)}))["files"]
                                revisions = {item["path"]: item["digest"] for item in reads}
                                preview = self.tool_data(await client.call_tool("preview_skill", {"skill": action[0], "changes": [{"path": FEATURE_PATH.as_posix(), "content": proposal}], "read_revisions": revisions}))
                                self.assertEqual(not blocked, preview["applicable"])
                                self.assertEqual("blocked" if blocked else "ready", preview["classification"])
                                self.assertEqual(before, self.snapshot(root))
                                result = await client.call_tool("apply", {"preview_id": preview["preview_id"], "operation_id": "agent-parity"})
                                if blocked:
                                    self.assertTrue(result.is_error, result)
                                    self.assertIn("preview_blocked", " ".join(part.text for part in result.content if getattr(part, "type", None) == "text"))
                                else:
                                    self.assertEqual("applied", self.tool_data(result)["state"])
        finally:
            service.close()
        after = self.snapshot(root)
        if blocked:
            self.assertEqual(before, after)
            return {}
        changed = {path: (before.get(path), after.get(path)) for path in before.keys() | after.keys() if before.get(path) != after.get(path)}
        self.assertEqual({FEATURE_PATH.as_posix(), "knowledge/wiki/index.md", "knowledge/wiki/log.md"}, set(changed))
        self.assertEqual(proposal.encode("utf-8"), after[FEATURE_PATH.as_posix()])
        metadata = yaml.safe_load(proposal.split("---", 2)[1])
        self.assertEqual((action[3], action[4]), (metadata["status"], metadata["owner"]))
        return changed

    def normalize_history(self, raw: bytes | None, action: str, kind: str) -> bytes | None:
        if raw is None:
            return None
        text = raw.decode("utf-8")
        def actor(match):
            value = json.loads(match.group(1))
            self.assertEqual({"action", "participant_id", "kind", "name", "preview_id"}, set(value))
            self.assertEqual(action, value["action"])
            self.assertEqual(kind, value["kind"])
            self.assertEqual(f"Parity {kind}", value["name"])
            for key in ("participant_id", "kind", "name", "preview_id"):
                value[key] = "<actor-metadata>"
            return "<!-- prism:board-actor:v1 " + json.dumps(value, sort_keys=True) + " -->"
        text = re.sub(r"<!-- prism:board-actor:v1 (\{[^\n]*\}) -->", actor, text)
        text = re.sub(r"<!-- prism:board-history:v1 preview=[a-f0-9-]+ -->", "<!-- prism:board-history:v1 preview=<preview> -->", text)
        return text.encode("utf-8")

    async def test_human_http_and_agent_mcp_make_equivalent_canonical_changes(self) -> None:
        for action in ACTIONS:
            with self.subTest(action=action[0]), tempfile.TemporaryDirectory() as temporary:
                results = []
                for kind in ("human", "agent"):
                    changes = await self.exercise(Path(temporary) / kind, action, kind, blocked=False)
                    old, new = changes["knowledge/wiki/log.md"]
                    self.assertEqual(1, new.count(b"<!-- prism:board-actor:v1 "))
                    self.assertEqual(1, new.count(b"<!-- prism:board-history:v1 "))
                    changes["knowledge/wiki/log.md"] = (old, self.normalize_history(new, action[0], kind))
                    results.append(changes)
                self.assertEqual(results[0], results[1])

    async def test_both_transports_reject_open_questions_without_canonical_writes(self) -> None:
        for action in ACTIONS:
            with self.subTest(action=action[0]), tempfile.TemporaryDirectory() as temporary:
                for kind in ("human", "agent"):
                    await self.exercise(Path(temporary) / kind, action, kind, blocked=True)
