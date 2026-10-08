"""Canonical write parity through real human HTTP and agent MCP transports."""

from __future__ import annotations

from datetime import date
import hashlib
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
from prism_cli.wiki_model import NO_UI_TRACK_REASON, DesignTracks
from prism_cli.workflow_install import apply_install, plan_install
from tests.core_workflow_fixture import FEATURE_PATH, INTAKE_ITEM, create_core_workflow_fixture
from tests.design_tracks import ensure_tracks, technical_design_page, with_tracks
from tests.test_core_workflow_fixture import CHECK_DATE, _feature_page, _requirement_page, _write_index
from tests import real_temp  # noqa: F401


ORIGIN = "http://127.0.0.1:8765"
ACTIONS = (
    ("po-handoff", "specified", "po", "ready-for-design", "tech-lead"),
    ("design-start", "ready-for-design", "tech-lead", "in-design", "tech-lead"),
    ("dev-start", "ready-for-dev", "dev", "in-dev", "dev"),
)
# The role that approves each action: the design owner of a scope with no UI is the tech lead.
ROLE_OF = {"po-handoff": "po", "design-start": "tech-lead", "dev-start": "dev"}


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
        self.assertEqual("applied", apply_install(root, plan_install(root, name="Document review", apps=["backend"]))["status"])
        pending = root / INTAKE_ITEM.parent
        pending.rename(root / "knowledge/intake/processed/2026-10-06-document-review-brief")
        content = _feature_page().replace("status: raw\n", f"status: {action[1]}\n").replace("owner: po\n", f"owner: {action[2]}\n")
        if not blocked:
            content = content.replace("| po | open |", "| po | resolved: Capture key points and requested follow-up. |")
        content = ensure_tracks(content, action[1])
        # Canonical LF fixture bytes avoid conflating transport parity with the
        # separately disclosed formatting normalization of adopted YAML pages.
        (root / FEATURE_PATH).write_bytes(content.encode("utf-8"))
        _write_index(root, action[1], action[2])
        if action[0] == "dev-start":
            (root / "knowledge/wiki/app-requirements/F-001-backend.md").write_bytes(_requirement_page("pending").encode("utf-8"))

    @staticmethod
    def snapshot(root: Path) -> dict[str, bytes]:
        return {path.relative_to(root).as_posix(): path.read_bytes() for path in (root / "knowledge").rglob("*") if path.is_file()}

    @staticmethod
    async def approve_in_a_session(transport, token: str, preview_id: str, operation_id: str):
        """What the board page does: sign in with the human token, read the proposal, then apply its review revision."""

        async with httpx2.AsyncClient(transport=transport, base_url=ORIGIN) as http:
            login = await http.post("/api/board/v1/auth/exchange", json={"token": token}, headers={"Origin": ORIGIN})
            assert login.status_code == 200, login.text
            headers = {"Origin": ORIGIN, "X-Prism-CSRF": login.json()["csrf_token"]}
            reviewed = await http.get(f"/api/board/v1/previews/{preview_id}")
            assert reviewed.status_code == 200, reviewed.text
            body = {
                "preview_id": preview_id,
                "operation_id": operation_id,
                "review_revision": reviewed.json()["approval"]["review_revision"],
                "semantic_review_acknowledged": True,
            }
            return await http.post("/api/board/v1/apply", json=body, headers=headers)

    def tool_data(self, result) -> dict:
        self.assertFalse(result.is_error, result)
        if result.structured_content is not None:
            return result.structured_content
        return json.loads(next(part.text for part in result.content if getattr(part, "type", None) == "text"))

    async def read_every_page(self, client, paths: list[str]) -> list[dict]:
        """Follow read_workspace cursors and return one record per file with its full text."""

        files: dict[str, dict] = {}
        cursor = None
        while True:
            arguments = {"paths": paths} if cursor is None else {"paths": paths, "cursor": cursor}
            page = self.tool_data(await client.call_tool("read_workspace", arguments))
            for record in page["files"]:
                held = files.setdefault(record["path"], {**record, "content": ""})
                self.assertEqual(len(held["content"]), record["offset"])
                held["content"] += record["content"]
            cursor = page["next_cursor"]
            if cursor is None:
                break
        self.assertEqual(sorted(paths), sorted(files))
        for item in files.values():
            self.assertEqual(item["total_chars"], len(item["content"]))
            self.assertEqual("sha256:" + hashlib.sha256(item["content"].encode("utf-8")).hexdigest(), item["digest"])
        return [files[path] for path in paths]

    async def exercise(self, root: Path, action: tuple[str, ...], kind: str, *, blocked: bool) -> dict:
        self.prepare(root, action, blocked=blocked)
        before = self.snapshot(root)
        # The agent's proposal is prepared independently from source bytes, not
        # from a human preview or the service's serializer/write-set helper.
        proposal = before[FEATURE_PATH.as_posix()].decode("utf-8")
        proposal = proposal.replace(f"status: {action[1]}\n", f"status: {action[3]}\n", 1)
        proposal = proposal.replace(f"owner: {action[2]}\n", f"owner: {action[4]}\n", 1)
        # Starting design initializes the tracks, as the human preview does.
        proposal = ensure_tracks(proposal, action[3])
        service = BoardService(root)
        # The action is gated: the human who approves it holds its role and signs in to the board. A human run previews and
        # approves it directly; an agent run proposes it over MCP and the same kind of human approves it (the intended difference).
        approver = service.create_participant("Parity approver", "human", writable=True, roles=ROLE_OF[action[0]])
        grant = approver if kind == "human" else service.create_participant(f"Parity {kind}", kind, writable=True)
        app = create_app(root, port=8765, service=service)
        try:
            async with app.router.lifespan_context(app):
                transport = httpx2.ASGITransport(app=app)

                async def approve_over_http(preview: dict, operation_id: str):
                    async with httpx2.AsyncClient(transport=transport, base_url=ORIGIN) as http:
                        login = await http.post("/api/board/v1/auth/exchange", json={"token": approver["token"]}, headers={"Origin": ORIGIN})
                        self.assertEqual(200, login.status_code, login.text)
                        headers = {"Origin": ORIGIN, "X-Prism-CSRF": login.json()["csrf_token"]}
                        reviewed = await http.get(f"/api/board/v1/previews/{preview['preview_id']}")
                        self.assertEqual(200, reviewed.status_code, reviewed.text)
                        body = {
                            "preview_id": preview["preview_id"],
                            "operation_id": operation_id,
                            "review_revision": reviewed.json()["approval"]["review_revision"],
                            "semantic_review_acknowledged": True,
                        }
                        return await http.post("/api/board/v1/apply", json=body, headers=headers)

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
                        # A gated apply is made against the revision the human read, with the acknowledgement.
                        approval = {"review_revision": preview["approval"]["review_revision"], "semantic_review_acknowledged": True}
                        response = await http.post("/api/board/v1/apply", json={"preview_id": preview["preview_id"], "operation_id": "human-parity", **approval}, headers=headers)
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
                                skill_page = self.tool_data(await client.call_tool("get_skill", {"name": action[0]}))
                                self.assertIsNone(skill_page["next_cursor"])
                                skill = skill_page["skill"]
                                inventory = self.tool_data(await client.call_tool("list_workspace", {}))
                                self.assertIsNone(inventory["next_cursor"])
                                paths = set(skill["required_workspace_reads"])
                                paths.update(item["path"] for item in inventory["files"] if item["read_support"] == "eligible")
                                reads = await self.read_every_page(client, sorted(paths))
                                revisions = {item["path"]: item["digest"] for item in reads}
                                preview = self.tool_data(await client.call_tool("preview_skill", {"skill": action[0], "changes": [{"path": FEATURE_PATH.as_posix(), "content": proposal}], "read_revisions": revisions}))
                                self.assertEqual(not blocked, preview["applicable"])
                                self.assertEqual("blocked" if blocked else "ready", preview["classification"])
                                self.assertEqual(before, self.snapshot(root))
                                # The agent never applies a gated proposal; a human approves it in the board.
                                result = await client.call_tool("apply", {"preview_id": preview["preview_id"], "operation_id": "agent-parity"})
                                self.assertTrue(result.is_error, result)
                                self.assertIn("approval_required", " ".join(part.text for part in result.content if getattr(part, "type", None) == "text"))
                                self.assertEqual(before, self.snapshot(root))
                        response = await approve_over_http(preview, "agent-parity-approved")
                        if blocked:
                            self.assertEqual(409, response.status_code, response.text)
                            self.assertEqual("preview_blocked", response.json()["error"]["code"])
                        else:
                            self.assertEqual(200, response.status_code, response.text)
                            self.assertEqual("applied", response.json()["state"])
        finally:
            service.close()
        after = self.snapshot(root)
        if blocked:
            self.assertEqual(before, after)
            return {}
        changed = {path: (before.get(path), after.get(path)) for path in before.keys() | after.keys() if before.get(path) != after.get(path)}
        self.assertEqual({FEATURE_PATH.as_posix(), "knowledge/wiki/status-board.md", "knowledge/wiki/log.md"}, set(changed))
        self.assertEqual(proposal.encode("utf-8"), after[FEATURE_PATH.as_posix()])
        metadata = yaml.safe_load(proposal.split("---", 2)[1])
        self.assertEqual((action[3], action[4]), (metadata["status"], metadata["owner"]))
        return changed

    def normalize_history(self, raw: bytes | None, action: str, kind: str) -> bytes | None:
        if raw is None:
            return None
        text = raw.decode("utf-8")
        def actor(match):
            # A gated action is always recorded under its approving human, with the proposer's ID beside it.
            value = json.loads(match.group(1))
            self.assertEqual({"action", "participant_id", "kind", "name", "preview_id", "approver_id", "proposer_id", "roles"}, set(value))
            self.assertEqual(action, value["action"])
            self.assertEqual(("human", "Parity approver", [ROLE_OF[action]]), (value["kind"], value["name"], value["roles"]))
            self.assertEqual(value["participant_id"], value["approver_id"])
            for key in ("participant_id", "kind", "name", "preview_id", "approver_id", "proposer_id", "roles"):
                value[key] = "<actor-metadata>"
            return "<!-- prism:board-actor:v1 " + json.dumps(value, sort_keys=True) + " -->"
        def by_line(match):
            # The approver holds the role; an agent's proposal is named after it.
            proposed = " approving Parity agent (agent)" if kind == "agent" else ""
            self.assertEqual(f"Parity approver (human; roles {ROLE_OF[action]}){proposed}", match.group(1))
            return "- by: <actor>"
        text = re.sub(r"<!-- prism:board-actor:v1 (\{[^\n]*\}) -->", actor, text)
        text = re.sub(r"(?m)^- by: (.*)$", by_line, text)
        text = re.sub(r"(?m)^- evidence: board preview [a-f0-9-]+$", "- evidence: board preview <preview>", text)
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

    async def test_dev_clarify_and_dev_done_are_agent_skills_and_the_human_transport_refuses_them(self) -> None:
        """The two skills exist on the agent transport only; the human transport answers with the service's own refusals."""

        from tests.test_board_service import (
            _journey_feature_page,
            _journey_requirement_page,
            _replace_body_section,
            _set_feature_stage,
            _set_requirement_status,
            _write_index_rows,
        )

        feature_relative = FEATURE_PATH.as_posix()
        requirement_relative = "knowledge/wiki/app-requirements/F-001-backend.md"
        question = "| 2 | Is there a limit on the number of comments in one summary? | dev | open |"
        answer = "At most 200 comments are exported; the rest are summarized as a count."
        evidence = (
            "| App | Artifact | Contract | Implementation | Tests | Basis |\n|---|---|---|---|---|---|\n"
            "| backend | `build:backend#42` | none | Pull request 42 merged as 3f9c2ab | CI run 1187: 31 tests passed | checked |"
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "workspace"
            create_core_workflow_fixture(root)
            self.assertEqual("applied", apply_install(root, plan_install(root, name="Document review", apps=["backend"]))["status"])
            (root / INTAKE_ITEM.parent).rename(root / "knowledge/intake/processed/2026-10-06-document-review-brief")
            page = _journey_feature_page("F-001", "Document review", "in-dev", "dev", ["knowledge/intake/processed/2026-10-06-document-review-brief"], [
                    "| 1 | Which points should a review summary highlight? | po | resolved: Key points. |", question,
                ])
            (root / feature_relative).write_bytes(page.encode("utf-8"))
            (root / requirement_relative).write_bytes(_journey_requirement_page("in-progress").encode("utf-8"))
            _write_index_rows(root, [("F-001", "Document review", "in-dev", "dev")])

            service = BoardService(root)
            human = service.create_participant("Parity human", "human", writable=True, roles="dev")
            agent = service.create_participant("Parity agent", "agent", writable=True)
            app = create_app(root, port=8765, service=service)
            try:
                async with app.router.lifespan_context(app):
                    transport = httpx2.ASGITransport(app=app)
                    async with httpx2.AsyncClient(transport=transport, base_url=ORIGIN) as http:
                        login = await http.post("/api/board/v1/auth/exchange", json={"token": human["token"]}, headers={"Origin": ORIGIN})
                        self.assertEqual(200, login.status_code, login.text)
                        headers = {"Origin": ORIGIN, "X-Prism-CSRF": login.json()["csrf_token"]}
                        refused = await http.post("/api/board/v1/previews/transition", json={"feature_id": "F-001", "action": "dev-done", "inputs": {"semantic_review_acknowledged": True}}, headers=headers)
                        self.assertEqual((403, "human_action_unavailable"), (refused.status_code, refused.json()["error"]["code"]))
                        proposal = {"skill": "dev-clarify", "changes": [{"path": feature_relative, "content": page}]}
                        refused = await http.post("/api/board/v1/previews/skill", json=proposal, headers=headers)
                        self.assertEqual((403, "participant_kind_required"), (refused.status_code, refused.json()["error"]["code"]))
                    before = self.snapshot(root)

                    async with httpx2.AsyncClient(transport=transport, base_url=ORIGIN, headers={"Authorization": "Bearer " + agent["token"]}) as http:
                        async with streamable_http_client(ORIGIN + "/mcp", http_client=http) as (reader, writer):
                            async with ClientSession(reader, writer) as client:
                                await client.initialize()
                                listed = {item["name"]: item for item in self.tool_data(await client.call_tool("list_skills", {}))["skills"]}
                                # `dev-clarify` is an ungated write the agent applies itself; `dev-done` is gated, so a human applies it.
                                self.assertEqual((True, ["agent"], {"preview_skill": ["agent"]}), (listed["dev-clarify"]["write_supported"], listed["dev-clarify"]["participant_kinds"], listed["dev-clarify"]["write_tools"]))
                                self.assertEqual(
                                    (True, ["agent", "human"], {"preview_skill": ["agent"], "apply": ["human"]}),
                                    (listed["dev-done"]["write_supported"], listed["dev-done"]["participant_kinds"], listed["dev-done"]["write_tools"]),
                                )
                                transition = await client.call_tool("preview_transition", {"feature_id": "F-001", "action": "dev-done", "inputs": {"semantic_review_acknowledged": True}})
                                self.assertTrue(transition.is_error)
                                self.assertIn("participant_kind_required", " ".join(part.text for part in transition.content if getattr(part, "type", None) == "text"))
                                self.assertEqual(before, self.snapshot(root))

                                async def propose(skill: str, changes: list[dict]):
                                    page_data = self.tool_data(await client.call_tool("get_skill", {"name": skill}))
                                    paths = set(page_data["skill"]["required_workspace_reads"])
                                    inventory = self.tool_data(await client.call_tool("list_workspace", {}))
                                    paths.update(item["path"] for item in inventory["files"] if item["read_support"] == "eligible")
                                    reads = await self.read_every_page(client, sorted(paths))
                                    revisions = {item["path"]: item["digest"] for item in reads}
                                    return await client.call_tool("preview_skill", {"skill": skill, "changes": changes, "read_revisions": revisions})

                                clarified = page.replace(question, f"| 2 | Is there a limit on the number of comments in one summary? | dev | resolved: {answer} |")
                                clarified = _replace_body_section(
                                    service,
                                    clarified,
                                    "Acceptance criteria",
                                    "- [ ] AC-1 [backend] A review summary records the document's key points.\n"
                                    f"- [ ] AC-2 [backend] A reviewer can record the outcome and requested follow-up. {answer}",
                                )
                                requirement = _replace_body_section(service, _journey_requirement_page("in-progress"), "Technical constraints", f"Use the existing workspace storage. {answer}")
                                preview = self.tool_data(await propose("dev-clarify", [{"path": feature_relative, "content": clarified}, {"path": requirement_relative, "content": requirement}]))
                                self.assertEqual(("ready", True), (preview["classification"], preview["applicable"]))
                                applied = await client.call_tool("apply", {"preview_id": preview["preview_id"], "operation_id": "agent-dev-clarify"})
                                self.assertEqual("applied", self.tool_data(applied)["state"])
                                self.assertIn(answer, (root / requirement_relative).read_text(encoding="utf-8"))

                                missing = _set_feature_stage(clarified, "ready-for-qa", "qa", service)
                                requirement_done = _set_requirement_status(requirement, "done")
                                rejected = await propose("dev-done", [{"path": feature_relative, "content": missing}, {"path": requirement_relative, "content": requirement_done}])
                                self.assertTrue(rejected.is_error)
                                text = " ".join(part.text for part in rejected.content if getattr(part, "type", None) == "text")
                                self.assertIn("delivery_evidence_required", text)
                                self.assertIn('"apps":["backend"]', text)

                                complete = _replace_body_section(service, missing, "Delivery evidence", evidence)
                                preview = self.tool_data(await propose("dev-done", [{"path": feature_relative, "content": complete}, {"path": requirement_relative, "content": requirement_done}]))
                                self.assertEqual(("ready", True), (preview["classification"], preview["applicable"]))
                                refused = await client.call_tool("apply", {"preview_id": preview["preview_id"], "operation_id": "agent-dev-done"})
                                self.assertTrue(refused.is_error, refused)
                                self.assertIn("approval_required", " ".join(part.text for part in refused.content if getattr(part, "type", None) == "text"))
                                approved = await self.approve_in_a_session(transport, human["token"], preview["preview_id"], "human-dev-done")
                                self.assertEqual("applied", approved.json()["state"], approved.text)
            finally:
                service.close()
            final = yaml.safe_load((root / feature_relative).read_text(encoding="utf-8").split("---", 2)[1])
            self.assertEqual(("ready-for-qa", "qa"), (final["status"], final["owner"]))
            self.assertIn("Pull request 42 merged as 3f9c2ab", (root / feature_relative).read_text(encoding="utf-8"))

    async def test_design_handoff_creates_the_agreed_api_contract_the_same_way_over_http_and_mcp(self) -> None:
        """An agent's design-handoff with declared API work needs the contract page on both transports, and the human then starts dev over HTTP."""

        from tests.test_board_service import (
            _journey_feature_page,
            _journey_requirement_page,
            _read_revisions,
            _replace_body_section,
            _set_feature_stage,
            _write_index_rows,
        )

        feature_relative = FEATURE_PATH.as_posix()
        requirement_relative = "knowledge/wiki/app-requirements/F-001-backend.md"
        contract_relative = "knowledge/wiki/api-contracts/F-001.md"
        surface = "A new endpoint `POST /api/v1/reviews/{id}/exports` returns the review summary as a PDF export."
        contract = (
            "---\nfeature-id: F-001\nversion: 1\nstatus: agreed\n---\n\n"
            "## Endpoints\n- `POST /api/v1/reviews/{reviewId}/exports` creates a review export. Response body: `ReviewExport` (201). Errors: 401, 404.\n\n"
            "## Data models\n### ReviewExport\n- `url`: string\n\n"
            "## Authentication requirements\nBearer token of the signed-in reviewer.\n\n"
            "## Notes\nThe export is generated when it is requested.\n"
        )
        question = "| 1 | Which points should a review summary highlight? | po | resolved: Key points. |"
        outcomes: list[dict] = []
        for transport in ("http", "mcp"):
            with self.subTest(transport=transport), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary) / "workspace"
                create_core_workflow_fixture(root)
                self.assertEqual("applied", apply_install(root, plan_install(root, name="Document review", apps=["backend"]))["status"])
                (root / INTAKE_ITEM.parent).rename(root / "knowledge/intake/processed/2026-10-06-document-review-brief")
                page = _journey_feature_page("F-001", "Document review", "in-design", "tech-lead", ["knowledge/intake/processed/2026-10-06-document-review-brief"], [question])
                page = _replace_body_section(None, page, "API surface", surface)
                (root / feature_relative).write_bytes(page.encode("utf-8"))
                _write_index_rows(root, [("F-001", "Document review", "in-design", "tech-lead")])

                service = BoardService(root)
                human = service.create_participant("Parity human", "human", writable=True, roles="tech-lead,dev")
                agent = service.create_participant("Parity agent", "agent", writable=True)
                app = create_app(root, port=8765, service=service)
                handoff = with_tracks(_set_feature_stage(page, "ready-for-dev", "dev", service), DesignTracks("not-applicable", "done", NO_UI_TRACK_REASON, None))
                technical = {"path": "knowledge/wiki/technical-design/F-001-document-review.md", "content": technical_design_page("F-001", ("backend",), ("AC-1", "AC-2"))}
                requirement = _replace_body_section(
                    service, _journey_requirement_page("pending"), "API contract reference", "See [the API contract](../api-contracts/F-001.md) for the export endpoint."
                )
                without = [{"path": feature_relative, "content": handoff}, technical, {"path": requirement_relative, "content": requirement.replace("See [the API contract](../api-contracts/F-001.md) for", "No contract exists for")}]
                with_contract = [without[0], technical, {"path": requirement_relative, "content": requirement}, {"path": contract_relative, "content": contract}]
                try:
                    async with app.router.lifespan_context(app):
                        asgi = httpx2.ASGITransport(app=app)
                        if transport == "http":
                            async with httpx2.AsyncClient(transport=asgi, base_url=ORIGIN, headers={"Authorization": "Bearer " + agent["token"]}) as http:
                                async def propose(changes: list[dict]):
                                    revisions = _read_revisions(service, service.authenticate(agent["token"]), "design-handoff", changes)
                                    return await http.post("/api/board/v1/previews/skill", json={"skill": "design-handoff", "changes": changes, "read_revisions": revisions})

                                missing = await propose(without)
                                self.assertEqual(409, missing.status_code, missing.text)
                                error = missing.json()["error"]
                                self.assertEqual("api_contract_required", error["code"])
                                self.assertEqual(contract_relative, error["details"]["path"])
                                self.assertNotIn("knowledge/wiki/api-contracts/F-001.md", self.snapshot(root))
                                response = await propose(with_contract)
                                self.assertEqual(200, response.status_code, response.text)
                                preview = response.json()
                                self.assertEqual(("ready", True), (preview["classification"], preview["applicable"]))
                                refused = await http.post("/api/board/v1/apply", json={"preview_id": preview["preview_id"], "operation_id": "agent-http-handoff"})
                                self.assertEqual((403, "approval_required"), (refused.status_code, refused.json()["error"]["code"]))
                                applied = await self.approve_in_a_session(asgi, human["token"], preview["preview_id"], "human-http-handoff")
                                self.assertEqual("applied", applied.json()["state"], applied.text)
                        else:
                            async with httpx2.AsyncClient(transport=asgi, base_url=ORIGIN, headers={"Authorization": "Bearer " + agent["token"]}) as http:
                                async with streamable_http_client(ORIGIN + "/mcp", http_client=http) as (reader, writer):
                                    async with ClientSession(reader, writer) as client:
                                        await client.initialize()

                                        async def propose(changes: list[dict]):
                                            skill = self.tool_data(await client.call_tool("get_skill", {"name": "design-handoff"}))["skill"]
                                            paths = set(skill["required_workspace_reads"])
                                            inventory = self.tool_data(await client.call_tool("list_workspace", {}))
                                            paths.update(item["path"] for item in inventory["files"] if item["read_support"] == "eligible")
                                            revisions = {item["path"]: item["digest"] for item in await self.read_every_page(client, sorted(paths))}
                                            return await client.call_tool("preview_skill", {"skill": "design-handoff", "changes": changes, "read_revisions": revisions})

                                        missing = await propose(without)
                                        self.assertTrue(missing.is_error)
                                        text = " ".join(part.text for part in missing.content if getattr(part, "type", None) == "text")
                                        self.assertIn("api_contract_required", text)
                                        self.assertIn(contract_relative, text)
                                        self.assertNotIn(contract_relative, self.snapshot(root))
                                        preview = self.tool_data(await propose(with_contract))
                                        self.assertEqual(("ready", True), (preview["classification"], preview["applicable"]))
                                        refused = await client.call_tool("apply", {"preview_id": preview["preview_id"], "operation_id": "agent-mcp-handoff"})
                                        self.assertTrue(refused.is_error, refused)
                                        self.assertIn("approval_required", " ".join(part.text for part in refused.content if getattr(part, "type", None) == "text"))
                                        applied = await self.approve_in_a_session(asgi, human["token"], preview["preview_id"], "human-mcp-handoff")
                                        self.assertEqual("applied", applied.json()["state"], applied.text)

                        async with httpx2.AsyncClient(transport=asgi, base_url=ORIGIN) as http:
                            login = await http.post("/api/board/v1/auth/exchange", json={"token": human["token"]}, headers={"Origin": ORIGIN})
                            self.assertEqual(200, login.status_code, login.text)
                            headers = {"Origin": ORIGIN, "X-Prism-CSRF": login.json()["csrf_token"]}
                            refused = await http.post("/api/board/v1/previews/skill", json={"skill": "design-handoff", "changes": with_contract}, headers=headers)
                            self.assertEqual((403, "participant_kind_required"), (refused.status_code, refused.json()["error"]["code"]))
                            start = await http.post("/api/board/v1/previews/transition", json={"feature_id": "F-001", "action": "dev-start", "inputs": {"semantic_review_acknowledged": True}}, headers=headers)
                            self.assertEqual(200, start.status_code, start.text)
                            self.assertEqual(("ready", True), (start.json()["classification"], start.json()["applicable"]))
                            check = next(item for item in start.json()["checks"] if item["code"] == "api-contract")
                            self.assertEqual("pass", check["status"])
                            approval = {"review_revision": start.json()["approval"]["review_revision"], "semantic_review_acknowledged": True}
                            applied = await http.post("/api/board/v1/apply", json={"preview_id": start.json()["preview_id"], "operation_id": "human-http-dev-start", **approval}, headers=headers)
                            self.assertEqual("applied", applied.json()["state"], applied.text)
                finally:
                    service.close()
                after = self.snapshot(root)
                self.assertEqual(contract.encode("utf-8"), after[contract_relative])
                self.assertEqual(requirement.encode("utf-8"), after[requirement_relative])
                final = yaml.safe_load(after[feature_relative].decode("utf-8").split("---", 2)[1])
                self.assertEqual(("in-dev", "dev"), (final["status"], final["owner"]))
                outcomes.append({path: after[path] for path in (contract_relative, requirement_relative)})
        self.assertEqual(outcomes[0], outcomes[1])
