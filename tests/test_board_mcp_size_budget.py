"""No MCP tool result exceeds 32,000 characters, and paged content stays complete.

The tests use the real BoardService, ``create_app`` and the MCP SDK client over
the ASGI transport against a disposable workspace with 500 feature pages. Each
result is measured as the compact JSON of the JSON-RPC ``result`` object read
from the transport, the same way the size measurement script does.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
from pathlib import Path
import re
import shutil
import tempfile
from datetime import date
from typing import Any
import unittest
from unittest.mock import patch

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
import yaml

from prism_cli.board_server import create_app
from prism_cli.board_service import BoardError, BoardService
from prism_cli.app_model import apps_from_platforms
from prism_cli.workflow_install import apply_install, plan_install
from tests.core_workflow_fixture import create_core_workflow_fixture
from tests.test_board_service import _read_revisions
from tests import real_temp  # noqa: F401
from tests.wiki_files import write_index, write_status_board


REPO_ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "http://127.0.0.1:8765"
RESULT_BUDGET = 32000
SUMMARY_LIMIT = 500
FEATURE_COUNT = 500
TODAY = date.today().isoformat()
PROCESSED_SOURCE = "knowledge/intake/processed/2026-10-06-document-review-brief/brief.md"


class _TeeStream(httpx2.AsyncByteStream):
    def __init__(self, inner: Any, sink: list[bytes]) -> None:
        self._inner = inner
        self._sink = sink

    async def __aiter__(self):
        async for chunk in self._inner:
            self._sink.append(bytes(chunk))
            yield chunk

    async def aclose(self) -> None:
        close = getattr(self._inner, "aclose", None)
        if close is not None:
            await close()


class _CapturingTransport(httpx2.AsyncBaseTransport):
    """Wrap the ASGI transport and keep every response body it returns."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self._sinks: list[list[bytes]] = []

    async def handle_async_request(self, request: Any) -> Any:
        response = await self._inner.handle_async_request(request)
        sink: list[bytes] = []
        self._sinks.append(sink)
        response.stream = _TeeStream(response.stream, sink)
        return response

    def clear(self) -> None:
        self._sinks = []

    def tool_results(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for sink in self._sinks:
            text = b"".join(sink).decode("utf-8", errors="replace")
            candidates = [text.strip()] if text.strip().startswith("{") else []
            if not candidates:
                for event in re.split(r"\r?\n\r?\n", text):
                    data = "\n".join(line[5:].lstrip(" ") for line in event.splitlines() if line.startswith("data:"))
                    if data:
                        candidates.append(data)
            for candidate in candidates:
                try:
                    message = json.loads(candidate)
                except ValueError:
                    continue
                result = message.get("result") if isinstance(message, dict) else None
                if isinstance(result, dict) and "content" in result:
                    results.append(result)
        return results


def _compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _feature_page(number: int) -> str:
    return f"""---
id: F-{number:03d}
title: Document review {number:03d}
status: raw
owner: po
apps:
- backend
sources:
- {PROCESSED_SOURCE}
advisory-review: not-needed
---

## Summary
Review a document, summarize its key points, and record the review outcome.

## User story
As a reviewer, I want to record a document review, so that the outcome and follow-up are clear.

## Acceptance criteria
- [ ] A review summary records the document's key points.
- [ ] A reviewer can record the outcome and requested follow-up.

## Open questions
| # | Question | Owner | Status |
|---|----------|-------|--------|
| 1 | Which points should a review summary highlight? | po | open |

## App scope
- **backend**: Store the review summary and recorded outcome.

## API surface
None
"""


def build_workspace(root: Path, feature_count: int) -> None:
    create_core_workflow_fixture(root)
    receipt = apply_install(root, plan_install(root, name="Document review", apps=["backend"]))
    if receipt["status"] != "applied":
        raise RuntimeError(f"installer did not apply: {receipt}")
    (root / "knowledge/intake/pending/2026-10-06-document-review-brief").rename(root / "knowledge/intake/processed/2026-10-06-document-review-brief")
    # A generated project ships the real wiki schema; the fixture has a placeholder.
    shutil.copyfile(REPO_ROOT / "template/knowledge/wiki/SCHEMA.md", root / "knowledge/wiki/SCHEMA.md")
    shutil.copyfile(REPO_ROOT / "template/knowledge/wiki/LIFECYCLE.md", root / "knowledge/wiki/LIFECYCLE.md")
    features = root / "knowledge/wiki/features"
    rows = []
    for number in range(1, feature_count + 1):
        (features / f"F-{number:03d}-document-review.md").write_text(_feature_page(number), encoding="utf-8", newline="\n")
        # The title links the page, as an agent-written index does; the index then spans more than one result page.
        rows.append(f"| F-{number:03d} | [Document review {number:03d}](features/F-{number:03d}-document-review.md) | raw | po | not-needed |\n")
    write_status_board(root, "".join(rows))
    write_index(root)


class _Client:
    """One MCP session whose every tool result is checked against the budget."""

    def __init__(self, case: unittest.TestCase, session: Any, capture: _CapturingTransport, service: BoardService, actor: Any, roots: list[str]) -> None:
        self.case = case
        self.session = session
        self.capture = capture
        self.service = service
        self.actor = actor
        self.roots = roots

    async def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call a tool, check its wire size and text summary, and return its structured content."""

        self.capture.clear()
        result = await self.session.call_tool(tool, arguments)
        self.case.assertFalse(result.is_error, (tool, arguments, result.content))
        wire = self.capture.tool_results()
        self.case.assertEqual(1, len(wire), (tool, "tool results seen on the wire"))
        size = len(_compact(wire[0]))
        shown = {key: value for key, value in arguments.items() if key != "paths"}
        self.case.assertLessEqual(size, RESULT_BUDGET, (tool, shown))
        structured = wire[0]["structuredContent"]
        assert_workspace_relative(self.case, tool, structured, self.roots)
        texts = [block["text"] for block in wire[0]["content"] if block.get("type") == "text"]
        self.case.assertEqual(1, len(texts), tool)
        self.case.assertLessEqual(len(texts[0]), SUMMARY_LIMIT, tool)
        self.case.assertTrue(texts[0].startswith(tool), texts[0])
        try:
            parsed = json.loads(texts[0])
        except ValueError:
            parsed = None
        self.case.assertNotEqual(structured, parsed, f"{tool} text block repeats the structured content")
        self.case.assertEqual(structured, result.structured_content)
        return structured

    async def paged(self, tool: str, arguments: dict[str, Any]) -> list[dict[str, Any]]:
        pages: list[dict[str, Any]] = []
        cursor = None
        while True:
            page = await self.call(tool, arguments if cursor is None else {**arguments, "cursor": cursor})
            pages.append(page)
            cursor = page["next_cursor"]
            if cursor is None:
                return pages
            self.case.assertLess(len(pages), 200, f"{tool} did not finish paging")


@contextlib.asynccontextmanager
async def connected(case: unittest.TestCase, root: Path, *, kind: str = "agent", writable: bool = False):
    """Serve `root` over the real MCP transport and yield a checked client.

    Every result the client returns is also checked for workspace and
    temporary-directory paths.
    """

    service = BoardService(root)
    try:
        grant = service.create_participant("Size budget", kind, writable=writable)
        roots = sorted({str(root), str(root.resolve()), tempfile.gettempdir(), str(Path(tempfile.gettempdir()).resolve())})
        app = create_app(root, port=8765, service=service)
        capture = _CapturingTransport(httpx2.ASGITransport(app=app))
        async with app.router.lifespan_context(app):
            async with httpx2.AsyncClient(transport=capture, base_url=ORIGIN, headers={"Authorization": "Bearer " + grant["token"]}) as http:
                async with streamable_http_client(ORIGIN + "/mcp", http_client=http) as (reader, writer):
                    async with ClientSession(reader, writer) as session:
                        await session.initialize()
                        yield _Client(case, session, capture, service, service.authenticate(grant["token"]), roots)
    finally:
        service.close()


class McpResultSizeBudgetTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls._temporary.cleanup)
        cls.small_root = Path(cls._temporary.name) / "small"
        cls.root = Path(cls._temporary.name) / "board"
        build_workspace(cls.small_root, 0)
        build_workspace(cls.root, FEATURE_COUNT)

    def setUp(self) -> None:
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, logging.NOTSET)

    async def test_discover_and_list_skills_stay_within_budget_and_report_contract_3(self) -> None:
        async with connected(self, self.root) as client:
            discovered = await client.call("discover", {})
            listed = await client.call("list_skills", {})
            self.assertEqual(3, discovered["mcp_contract"])
            self.assertEqual(3, listed["mcp_contract"])
            self.assertEqual(26, len(listed["skills"]))
            self.assertEqual(listed["read_support"], discovered["capability"]["read_support"])
            for item in discovered["skills"]:
                self.assertEqual({"name", "description"}, set(item))
            for item in listed["skills"]:
                self.assertNotIn("read_support", item)
            self.assertEqual(1, _compact(discovered).count('"max_paths_per_request"'))
            self.assertEqual(1, _compact(listed).count('"max_paths_per_request"'))

    async def test_every_skill_and_reference_chunk_stays_within_budget_and_reassembles_to_its_digest(self) -> None:
        async with connected(self, self.small_root) as client:
            names = [item["name"] for item in (await client.call("list_skills", {}))["skills"]]
            self.assertEqual(26, len(names))
            for name in names:
                with self.subTest(skill=name):
                    pages = await client.paged("get_skill", {"name": name})
                    skill = pages[0]["skill"]
                    instructions = "".join(page["skill"]["instructions"] for page in pages)
                    self.assertEqual(skill["instructions_chunk"]["digest"], _digest(instructions))
                    self.assertEqual(skill["instructions_chunk"]["total_chars"], len(instructions))
                    reads = [path for page in pages for path in page["skill"]["required_workspace_reads"]]
                    self.assertEqual(skill["required_workspace_reads_chunk"]["total"], len(reads))
                    self.assertEqual(sorted(set(reads)), reads)
                    self.assertTrue(skill["references"])
                    for reference in skill["references"]:
                        self.assertEqual({"path", "title", "size_chars", "digest"}, set(reference))
                        self.assertNotIn("content", reference)
                        chunks = await client.paged("get_skill_reference", {"name": name, "path": reference["path"]})
                        text = "".join(chunk["content"] for chunk in chunks)
                        self.assertEqual(reference["size_chars"], len(text), reference["path"])
                        self.assertEqual(reference["digest"], _digest(text), reference["path"])
                        self.assertEqual({reference["digest"]}, {chunk["digest"] for chunk in chunks})
                        self.assertEqual([0] + [sum(len(c["content"]) for c in chunks[:i + 1]) for i in range(len(chunks) - 1)], [c["offset"] for c in chunks])

    async def test_get_skill_stays_within_budget_for_every_skill_on_a_500_feature_workspace(self) -> None:
        async with connected(self, self.root) as client:
            names = [item["name"] for item in (await client.call("list_skills", {}))["skills"]]
            for name in names:
                with self.subTest(skill=name):
                    pages = await client.paged("get_skill", {"name": name})
                    skill = pages[0]["skill"]
                    reads = [path for page in pages for path in page["skill"]["required_workspace_reads"]]
                    self.assertEqual(skill["required_workspace_reads_chunk"]["total"], len(reads))
                    self.assertEqual(len(reads), len(set(reads)))
                    instructions = "".join(page["skill"]["instructions"] for page in pages)
                    self.assertEqual(skill["instructions_chunk"]["digest"], _digest(instructions))
                    if name == "po-intake":
                        self.assertGreater(len(pages), 1)
                        self.assertGreaterEqual(len(reads), FEATURE_COUNT)

    async def test_owner_and_search_pages_stay_within_budget_and_cover_every_match_once(self) -> None:
        async with connected(self, self.root) as client:
            owner = await client.paged("query", {"kind": "owner", "value": "po"})
            self.assertGreater(len(owner), 1)
            features = [item["id"] for page in owner for item in page["facts"]["features"]]
            questions = [(item["feature_id"], item["number"]) for page in owner for item in page["facts"]["open_questions"]]
            expected = [f"F-{number:03d}" for number in range(1, FEATURE_COUNT + 1)]
            self.assertEqual(expected, features)
            self.assertEqual([(feature_id, "1") for feature_id in expected], questions)
            self.assertEqual({2 * FEATURE_COUNT}, {page["total"] for page in owner})
            self.assertEqual({FEATURE_COUNT}, {page["facts"]["feature_count"] for page in owner})

            search = await client.paged("query", {"kind": "search", "value": "review"})
            self.assertGreater(len(search), 1)
            paths = [item["path"] for page in search for item in page["facts"]["results"]]
            self.assertEqual(len(paths), len(set(paths)))
            self.assertEqual({len(paths)}, {page["total"] for page in search})
            features_found = {path for path in paths if path.startswith("knowledge/wiki/features/F-")}
            self.assertEqual(FEATURE_COUNT, len(features_found))

            platform = await client.call("query", {"kind": "app", "value": "backend"})
            self.assertIsNone(platform["next_cursor"])
            self.assertEqual(0, platform["total"])

    async def test_read_workspace_pages_and_chunks_stay_within_budget_and_match_their_digests(self) -> None:
        async with connected(self, self.root) as client:
            feature_paths = [f"knowledge/wiki/features/F-{number:03d}-document-review.md" for number in range(1, 65)]
            schema_paths = ["knowledge/wiki/SCHEMA.md", "knowledge/wiki/LIFECYCLE.md"]
            for paths in (feature_paths, ["knowledge/wiki/SCHEMA.md"], ["knowledge/wiki/LIFECYCLE.md"], schema_paths, ["knowledge/wiki/index.md"], ["knowledge/wiki/SCHEMA.md", *feature_paths[:10]]):
                with self.subTest(paths=len(paths), first=paths[0]):
                    pages = await client.paged("read_workspace", {"paths": paths})
                    records = [record for page in pages for record in page["files"]]
                    self.assertEqual(paths, list(dict.fromkeys(record["path"] for record in records)))
                    joined: dict[str, str] = {}
                    for record in records:
                        self.assertEqual(len(joined.get(record["path"], "")), record["offset"])
                        joined[record["path"]] = joined.get(record["path"], "") + record["content"]
                    for path in paths:
                        on_disk = (self.root / path).read_bytes().decode("utf-8")
                        self.assertEqual(on_disk, joined[path])
                        self.assertEqual({_digest(on_disk)}, {record["digest"] for record in records if record["path"] == path})
                        self.assertEqual({len(on_disk)}, {record["total_chars"] for record in records if record["path"] == path})
            schema_pages = await client.paged("read_workspace", {"paths": schema_paths})
            self.assertGreater(len(schema_pages), 1)
            index_pages = await client.paged("read_workspace", {"paths": ["knowledge/wiki/index.md"]})
            self.assertGreaterEqual(len(index_pages), 1)
            board_pages = await client.paged("read_workspace", {"paths": ["knowledge/wiki/status-board.md"]})
            self.assertGreater(len(board_pages), 1)
            batch_pages = await client.paged("read_workspace", {"paths": feature_paths})
            self.assertGreater(len(batch_pages), 1)
            self.assertTrue(all(record["offset"] == 0 for page in batch_pages for record in page["files"]))

    async def test_list_workspace_pages_stay_within_budget(self) -> None:
        async with connected(self, self.root) as client:
            pages = await client.paged("list_workspace", {"prefix": "knowledge"})
            self.assertGreater(len(pages), 1)
            self.assertEqual(pages[0]["total"], sum(len(page["files"]) for page in pages))

    async def test_a_reference_outside_the_skill_is_rejected_with_a_typed_error(self) -> None:
        async with connected(self, self.small_root) as client:
            result = await client.session.call_tool("get_skill_reference", {"name": "wiki-show", "path": "knowledge/wiki/log.md"})
            self.assertTrue(result.is_error)
            self.assertIn("reference_not_found", " ".join(block.text for block in result.content if hasattr(block, "text")))
            invalid = await client.session.call_tool("query", {"kind": "owner", "value": "po", "cursor": "not-a-cursor"})
            self.assertTrue(invalid.is_error)
            self.assertIn("invalid_cursor", " ".join(block.text for block in invalid.content if hasattr(block, "text")))


PLATFORMS = ["backend", "mobile-android", "mobile-ios", "web"]
BULK = ("Long detail sentence about the review workflow. " * 12).strip()
BODY_KEYS = {"before", "after", "content"}
DRIVE_PATH = re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/]")
FEATURE_FILE = "knowledge/wiki/features/F-001-document-review.md"
DESIGN_FILE = "knowledge/wiki/design/F-001-document-review.md"


def assert_workspace_relative(case: unittest.TestCase, label: str, value: Any, roots: list[str]) -> None:
    """Fail when a result carries the workspace, the temp directory or any absolute Windows path.

    Page text (`before`, `after`, `content`) is project data, not a path field, and is skipped.
    """

    if isinstance(value, dict):
        for key, entry in value.items():
            if key not in BODY_KEYS:
                assert_workspace_relative(case, f"{label}.{key}", entry, roots)
    elif isinstance(value, list):
        for index, entry in enumerate(value):
            assert_workspace_relative(case, f"{label}[{index}]", entry, roots)
    elif isinstance(value, str):
        lowered = value.lower().replace("\\", "/")
        case.assertNotIn("prism-board-preview", lowered, label)
        for root in roots:
            case.assertNotIn(root.lower().replace("\\", "/"), lowered, label)
        case.assertIsNone(DRIVE_PATH.search(value), f"{label}: absolute path in {value[:120]!r}")
        case.assertFalse(value.startswith("\\\\"), f"{label}: UNC path in {value[:120]!r}")


def _dev_feature_page(status: str, owner: str, platforms: list[str], evidence_rows: str, bulk: str) -> str:
    frontmatter = {
        "id": "F-001",
        "title": "Document review",
        "status": status,
        "owner": owner,
        "apps": platforms,
        "sources": [PROCESSED_SOURCE.rsplit("/", 1)[0]],
        "advisory-review": "not-needed",
        "revalidation": [],
    }
    scope = "\n".join(f"- **{platform}**: Store and show the review summary on {platform}. {bulk}" for platform in platforms)
    criteria = "\n".join(f"- [ ] Criterion {number}: {bulk}" for number in range(12))
    body = f"""## Summary
Review a document, summarize its key points, and record the review outcome. {bulk}

## User story
As a reviewer, I want to record a document review, so that the outcome and follow-up are clear.

## Acceptance criteria
{criteria}

## Open questions
| # | Question | Owner | Status |
|---|----------|-------|--------|
| 1 | Which points should a review summary highlight? | po | resolved: The key points and the outcome. |

## App scope
{scope}

## API surface
None

## Design
The design is recorded in [F-001 design](../design/F-001-document-review.md).

## Related features
No related feature is required for this workflow.

## Board review summary
The existing acceptance checks cover the scoped review workflow.

## Delivery evidence
| App | Implementation | Tests | Release |
|---|---|---|---|
{evidence_rows}

## Reopen history

## Post-ship notes
The fixture has no post-ship deviations.
"""
    return f"---\n{yaml.safe_dump(frontmatter, sort_keys=False).rstrip()}\n---\n\n{body}"


def _dev_requirement_page(platform: str, status: str, bulk: str) -> str:
    return (
        f"---\nfeature-id: F-001\napp: {platform}\nstatus: {status}\n---\n\n"
        f"## What to build\nStore a document review summary and outcome on {platform}. {bulk}\n\n"
        f"## Technical constraints\nUse the existing storage. {bulk}\n\n"
        "## Design reference\nNone yet.\n\n"
        "## API contract reference\nNo separate API contract is needed.\n\n"
        f"## Acceptance criteria\n- The saved summary and outcome can be read back. {bulk}\n\n"
        "## Dependencies\nThe document review record is available to the assigned reviewer.\n"
    )


def _dev_design_page() -> str:
    return (
        f"---\nfeature-id: F-001\ntitle: Document review\ndesigner: Reviewer\nfigma: reviewed-document-flow\n---\n\n"
        "## Summary\nThe reviewer sees the document title and review status.\n\n"
        "## Key design decisions\nKeep the review outcome beside the source document.\n\n"
        "## States covered\nThe page shows pending and completed reviews.\n\n"
        "## Component references\nUse the existing document summary panel.\n\n"
        "## Open design questions\nThe reviewer can scan the summary before saving.\n"
    )


def build_dev_done_workspace(root: Path, platforms: list[str], bulk: str, large_platform: str | None = None) -> list[dict[str, str]]:
    """Make F-001 in-dev on `platforms` and return the `dev-done` proposal that completes it.

    Every platform has a requirement page and a long evidence row. The page of
    `large_platform` is several times larger than one result, so one write must
    be returned in chunks.
    """

    create_core_workflow_fixture(root)
    manifest = root / "prism.workspace.yml"
    data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    data["apps"] = apps_from_platforms(list(platforms))
    manifest.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    for platform in platforms:
        (root / platform).mkdir(exist_ok=True)
        (root / platform / ".gitkeep").write_text("", encoding="utf-8")
    receipt = apply_install(root, plan_install(root, name="Document review", apps=platforms))
    if receipt["status"] != "applied":
        raise RuntimeError(f"installer did not apply: {receipt}")
    (root / "knowledge/intake/pending/2026-10-06-document-review-brief").rename(root / "knowledge/intake/processed/2026-10-06-document-review-brief")
    wiki = root / "knowledge/wiki"

    def write(relative: str, content: str) -> None:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")

    def requirement_bulk(platform: str) -> str:
        return bulk * 120 if platform == large_platform else bulk

    write(FEATURE_FILE, _dev_feature_page("in-dev", "dev", platforms, "", bulk))
    write(DESIGN_FILE, _dev_design_page())
    for platform in platforms:
        write(f"knowledge/wiki/app-requirements/F-001-{platform}.md", _dev_requirement_page(platform, "in-progress", requirement_bulk(platform)))
    write_status_board(root, "| F-001 | Document review | in-dev | dev | not-needed |\n")
    write_index(root)
    evidence = "\n".join(
        f"| {platform} | Pull request for {platform} merged as commit abc123. {bulk} | CI run on {platform}: 120 tests passed. {bulk} | release: https://example.test/releases/{platform}-1.4.0 {bulk} |"
        for platform in platforms
    )
    return [
        {"path": FEATURE_FILE, "content": _dev_feature_page("done", "none", platforms, evidence, bulk)},
        *(
            {"path": f"knowledge/wiki/app-requirements/F-001-{platform}.md", "content": _dev_requirement_page(platform, "done", requirement_bulk(platform))}
            for platform in platforms
        ),
    ]


class McpPreviewBudgetTests(unittest.IsolatedAsyncioTestCase):
    """Previews, operation records and change feeds stay within the result budget."""

    def setUp(self) -> None:
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, logging.NOTSET)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.temporary = Path(temporary.name)

    def dev_done(self, name: str, platforms: list[str], bulk: str, large_platform: str | None) -> tuple[Path, list[dict[str, str]]]:
        root = self.temporary / name
        return root, build_dev_done_workspace(root, platforms, bulk, large_platform)

    async def read_preview(self, client: _Client, first: dict[str, Any]) -> list[dict[str, Any]]:
        pages = [first]
        while pages[-1]["next_cursor"] is not None:
            pages.append(await client.call("get_preview", {"preview_id": first["preview_id"], "cursor": pages[-1]["next_cursor"]}))
            self.assertLess(len(pages), 200)
        return pages

    def reassemble(self, pages: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
        """Join the chunks of every record's before/after text, checking each chunk's offset."""

        joined: dict[str, dict[str, Any]] = {}
        for page in pages:
            for entry in page[key]:
                record = joined.setdefault(entry["path"], {"meta": {k: v for k, v in entry.items() if k not in {"before", "after"} and not k.endswith("_chunk")}, "before": None, "after": None})
                for side in ("before", "after"):
                    if isinstance(entry.get(side), str):
                        chunk = entry.get(f"{side}_chunk")
                        offset = chunk["offset"] if chunk else 0
                        held = record[side] or ""
                        self.assertEqual(len(held), offset, (entry["path"], side))
                        record[side] = held + entry[side]
                        if chunk:
                            self.assertEqual(entry[f"{side}_chars"], chunk["total_chars"])
        return joined

    async def test_dev_done_preview_on_every_default_platform_pages_within_budget_and_reassembles_exactly(self) -> None:
        root, changes = self.dev_done("every", PLATFORMS, BULK, "web")
        async with connected(self, root, writable=True) as client:
            revisions = _read_revisions(client.service, client.actor, "dev-done", changes)
            first = await client.call("preview_skill", {"skill": "dev-done", "changes": changes, "read_revisions": revisions})
            self.assertTrue(first["applicable"], first["checks"])
            pages = await self.read_preview(client, first)
            self.assertGreater(len(pages), 2)
            truth = client.service.get_preview(client.actor, first["preview_id"])
            self.assertGreater(len(json.dumps(truth)), 100000)
            for page in pages:
                for omitted in ("source_map", "proposed_changes", "read_revisions"):
                    self.assertNotIn(omitted, page)
                self.assertEqual([], page["moves"])
                self.assertEqual(len(truth["writes"]), page["writes_chunk"]["total"])
                for key in ("preview_id", "classification", "applicable", "checks", "blockers", "source", "target", "source_revision"):
                    self.assertEqual(first[key], page[key], key)
            self.assertEqual(len(revisions), first["read_revisions_count"])
            joined = self.reassemble(pages, "writes")
            self.assertEqual([item["path"] for item in truth["writes"]], list(joined))
            self.assertEqual({"canonical", "status-board", "log"}, {item["meta"]["role"] for item in joined.values()})
            for write in truth["writes"]:
                record = joined[write["path"]]
                self.assertEqual(write["before"], record["before"], write["path"])
                self.assertEqual(write["after"], record["after"], write["path"])
                self.assertEqual(write["after_digest"], _digest(record["after"]), write["path"])
                self.assertEqual(write["before_digest"], _digest(record["before"]) if record["before"] is not None else None)
            expected = {item["path"]: item["content"] for item in changes}
            for path, content in expected.items():
                self.assertEqual(content, joined[path]["after"])
            chunked = [entry for page in pages for entry in page["writes"] if "after_chunk" in entry or "before_chunk" in entry]
            self.assertTrue(chunked, "one write is larger than a page and must arrive in chunks")

            receipt = await client.call("apply", {"preview_id": first["preview_id"], "operation_id": "dev-done-every"})
            self.assertEqual("applied", receipt["state"])
            self.assertEqual(sorted([*expected, "knowledge/wiki/status-board.md", "knowledge/wiki/log.md"]), sorted(receipt["applied_paths"]))
            again = await client.call("operation", {"operation_id": "dev-done-every"})
            self.assertEqual(receipt, again["receipt"])
            feed = await client.call("changes", {})
            self.assertEqual("operation-applied", feed["changes"][-1]["event"]["type"])
        for path, content in expected.items():
            self.assertEqual(content, (root / path).read_text(encoding="utf-8"))

    async def test_dev_clarify_preview_on_every_default_platform_pages_within_budget_and_reassembles_exactly(self) -> None:
        root, _completion = self.dev_done("clarify", PLATFORMS, BULK, "web")
        answer = "At most 200 comments are exported; the rest are counted."
        resolved = "| 1 | Which points should a review summary highlight? | po | resolved: The key points and the outcome. |"
        feature_path = root / FEATURE_FILE
        asked = feature_path.read_text(encoding="utf-8").replace(
            resolved, resolved + "\n| 2 | Is there a limit on the number of comments? | dev | open |"
        )
        feature_path.write_bytes(asked.encode("utf-8"))
        answered = asked.replace("| dev | open |", f"| dev | resolved: {answer} |").replace(
            "- **backend**: Store and show the review summary on backend.", f"- **backend**: Store and show the review summary on backend. {answer}", 1
        )
        changes = [{"path": FEATURE_FILE, "content": answered}]
        for platform in PLATFORMS:
            relative = f"knowledge/wiki/app-requirements/F-001-{platform}.md"
            page = (root / relative).read_text(encoding="utf-8").replace(
                "## Technical constraints\nUse the existing storage.", f"## Technical constraints\nUse the existing storage. {answer}", 1
            )
            changes.append({"path": relative, "content": page})
        async with connected(self, root, writable=True) as client:
            revisions = _read_revisions(client.service, client.actor, "dev-clarify", changes)
            first = await client.call("preview_skill", {"skill": "dev-clarify", "changes": changes, "read_revisions": revisions})
            self.assertTrue(first["applicable"], first["checks"])
            pages = await self.read_preview(client, first)
            self.assertGreater(len(pages), 2)
            truth = client.service.get_preview(client.actor, first["preview_id"])
            joined = self.reassemble(pages, "writes")
            self.assertEqual([item["path"] for item in truth["writes"]], list(joined))
            for write in truth["writes"]:
                self.assertEqual(write["after"], joined[write["path"]]["after"], write["path"])
                self.assertEqual(write["after_digest"], _digest(joined[write["path"]]["after"]), write["path"])
            self.assertTrue([entry for page in pages for entry in page["writes"] if "after_chunk" in entry or "before_chunk" in entry])
            receipt = await client.call("apply", {"preview_id": first["preview_id"], "operation_id": "dev-clarify-every"})
            self.assertEqual("applied", receipt["state"])
        for item in changes:
            self.assertEqual(item["content"], (root / item["path"]).read_text(encoding="utf-8"))

    async def test_a_small_preview_arrives_in_one_page_with_inline_text_and_a_null_cursor(self) -> None:
        root, changes = self.dev_done("small", ["backend"], "", None)
        async with connected(self, root, writable=True) as client:
            revisions = _read_revisions(client.service, client.actor, "dev-done", changes)
            preview = await client.call("preview_skill", {"skill": "dev-done", "changes": changes, "read_revisions": revisions})
            self.assertTrue(preview["applicable"], preview["checks"])
            self.assertIsNone(preview["next_cursor"])
            self.assertEqual(preview["writes_chunk"], {"offset": 0, "count": len(preview["writes"]), "total": len(preview["writes"])})
            for entry in preview["writes"]:
                self.assertIsInstance(entry["after"], str)
                self.assertEqual(len(entry["after"]), entry["after_chars"])
                self.assertNotIn("after_chunk", entry)
                self.assertNotIn("before_chunk", entry)
            again = await client.call("get_preview", {"preview_id": preview["preview_id"]})
            self.assertEqual(preview, again)

    async def test_previews_are_private_to_their_participant_and_cursors_are_bound(self) -> None:
        root, changes = self.dev_done("bound", PLATFORMS, BULK, "backend")
        async with connected(self, root, writable=True) as client:
            revisions = _read_revisions(client.service, client.actor, "dev-done", changes)
            first = await client.call("preview_skill", {"skill": "dev-done", "changes": changes, "read_revisions": revisions})
            second = await client.call("preview_skill", {"skill": "dev-done", "changes": changes, "read_revisions": revisions})
            self.assertIsNotNone(first["next_cursor"])
            for arguments, code in (
                ({"preview_id": "no-such-preview"}, "preview_not_found"),
                ({"preview_id": first["preview_id"], "cursor": "not-a-cursor"}, "invalid_cursor"),
                ({"preview_id": second["preview_id"], "cursor": first["next_cursor"]}, "invalid_cursor"),
                ({"preview_id": "bad id!"}, "invalid_identifier"),
            ):
                with self.subTest(arguments=arguments):
                    result = await client.session.call_tool("get_preview", arguments)
                    self.assertTrue(result.is_error)
                    self.assertIn(code, " ".join(block.text for block in result.content if hasattr(block, "text")))
            other = client.service.authenticate(client.service.create_participant("Other agent", "agent", True)["token"])
            with self.assertRaises(BoardError) as error:
                client.service.get_preview(other, first["preview_id"])
            self.assertEqual("preview_not_found", error.exception.code)

    async def test_preview_transition_checks_use_workspace_relative_paths(self) -> None:
        root, _changes = self.dev_done("transition", ["backend"], "", None)
        async with connected(self, root, kind="human", writable=True) as client:
            preview = await client.call("preview_transition", {"feature_id": "F-001", "action": "dev-start", "inputs": {"semantic_review_acknowledged": True}})
            paths = [check["path"] for check in preview["checks"] if "path" in check]
            self.assertTrue(paths)
            self.assertTrue(all(path.startswith("knowledge/") or path == "prism.workspace.yml" for path in paths), paths)
            self.assertIn("writes_chunk", preview)

    async def test_skill_preview_checks_never_show_the_scratch_directory(self) -> None:
        root, changes = self.dev_done("scratch", ["backend"], "", None)
        async with connected(self, root) as client:
            service = client.service
            agent = service.authenticate(service.create_participant("Writer", "agent", True)["token"])
            revisions = _read_revisions(service, agent, "dev-done", changes)
            envelope = service.preview_skill(agent, "dev-done", changes, None, revisions)
            self.assertTrue(envelope["checks"])
            with_paths = [check["path"] for check in envelope["checks"] if "path" in check]
            self.assertTrue(with_paths)
            self.assertTrue(all(path.startswith("knowledge/") or path == "prism.workspace.yml" for path in with_paths), with_paths)
            assert_workspace_relative(self, "preview_skill", envelope, client.roots)

    async def test_an_interrupted_operation_pages_its_remaining_changes_and_recovers_within_budget(self) -> None:
        root, changes = self.dev_done("interrupted", PLATFORMS, BULK, "web")
        async with connected(self, root, writable=True) as client:
            revisions = _read_revisions(client.service, client.actor, "dev-done", changes)
            first = await client.call("preview_skill", {"skill": "dev-done", "changes": changes, "read_revisions": revisions})
            truth = client.service.get_preview(client.actor, first["preview_id"])
            original = client.service._apply_write

            def interrupted(write: dict[str, Any], **kwargs: Any) -> str:
                if write["role"] == "status-board":
                    raise OSError("synthetic write failure")
                return original(write, **kwargs)

            with patch.object(client.service, "_apply_write", side_effect=interrupted):
                receipt = await client.call("apply", {"preview_id": first["preview_id"], "operation_id": "interrupted-every"})
            self.assertEqual("conflict", receipt["state"])
            pages = await client.paged("operation", {"operation_id": "interrupted-every"})
            self.assertGreater(len(pages), 1)
            self.assertEqual({"conflict"}, {page["state"] for page in pages})
            for page in pages:
                self.assertEqual(len(truth["writes"]), page["remaining_changes_chunk"]["total"])
                self.assertEqual(client.service.operation(client.actor, "interrupted-every")["recovery_review_revision"], page["recovery_review_revision"])
                self.assertNotIn("source_files", json.dumps(page["moves"]))
            joined = self.reassemble(pages, "remaining_changes")
            self.assertEqual([item["path"] for item in truth["writes"]], list(joined))
            for write in truth["writes"]:
                self.assertEqual(write["before"], joined[write["path"]]["before"], write["path"])
                self.assertEqual(write["after"], joined[write["path"]]["after"], write["path"])
            self.assertEqual({"applied", "pending"}, {record["meta"]["state"] for record in joined.values()})
            invalid = await client.session.call_tool("operation", {"operation_id": "interrupted-every", "cursor": pages[0]["next_cursor"][:-4] + "AAAA"})
            self.assertTrue(invalid.is_error)
            self.assertIn("invalid_cursor", " ".join(block.text for block in invalid.content if hasattr(block, "text")))
            recovered = await client.call("recover", {"operation_id": "interrupted-every"})
            self.assertEqual("applied", recovered["state"])
            done = await client.call("operation", {"operation_id": "interrupted-every"})
            self.assertEqual("applied", done["state"])
            self.assertIsNone(done["next_cursor"] if "next_cursor" in done else None)

    async def test_changes_pages_many_large_events_without_losing_or_repeating_any(self) -> None:
        root = self.temporary / "events"
        build_workspace(root, 0)
        async with connected(self, root) as client:
            count = 520
            paths = [f"knowledge/wiki/features/F-{number:03d}-document-review-with-a-long-name.md" for number in range(60)]
            with client.service.store.transaction() as db:
                for number in range(count):
                    event = {"type": "operation-applied", "receipt": {"operation_id": f"op-{number}", "state": "applied", "applied_paths": paths}}
                    db.execute(
                        "INSERT INTO events(operation_id, participant_id, event_json, created_at) VALUES (?, ?, ?, ?)",
                        (f"op-{number}", "participant", json.dumps(event), "2026-01-01T00:00:00Z"),
                    )
            seen: list[str] = []
            calls = 0
            cursor = None
            while True:
                page = await client.call("changes", {} if cursor is None else {"cursor": cursor})
                calls += 1
                seen.extend(item["operation_id"] for item in page["changes"])
                self.assertEqual(page["cursor"], page["changes"][-1]["cursor"])
                cursor = page["cursor"]
                if not page["has_more"]:
                    break
                self.assertLess(calls, 100)
            self.assertGreater(calls, 3)
            self.assertEqual([f"op-{number}" for number in range(count)], seen)
            self.assertEqual(str(count), page["head_cursor"])
            empty = await client.call("changes", {"cursor": cursor})
            self.assertEqual([], empty["changes"])
            self.assertFalse(empty["has_more"])

    async def test_changes_returns_an_event_larger_than_one_result_in_chunks(self) -> None:
        root = self.temporary / "oversize-event"
        build_workspace(root, 0)
        async with connected(self, root) as client:
            paths = [f"knowledge/intake/processed/batch/file-{number:04d}-" + "x" * 60 + ".md" for number in range(450)]
            events = [
                {"type": "operation-applied", "receipt": {"operation_id": "op-1", "applied_paths": ["a.md"]}},
                {"type": "operation-conflict", "operation_id": "op-2", "paths": paths},
                {"type": "operation-applied", "receipt": {"operation_id": "op-3", "applied_paths": ["b.md"]}},
            ]
            with client.service.store.transaction() as db:
                for number, event in enumerate(events, start=1):
                    db.execute(
                        "INSERT INTO events(operation_id, participant_id, event_json, created_at) VALUES (?, ?, ?, ?)",
                        (f"op-{number}", "participant", json.dumps(event), "2026-01-01T00:00:00Z"),
                    )
            seen: list[str] = []
            text = ""
            cursor = None
            for _ in range(20):
                page = await client.call("changes", {} if cursor is None else {"cursor": cursor})
                for record in page["changes"]:
                    chunk = record.get("event_chunk")
                    if chunk is None:
                        seen.append(record["operation_id"])
                        continue
                    self.assertEqual(len(text), chunk["offset"])
                    text += chunk["text"]
                    if len(text) == chunk["total_chars"]:
                        seen.append(record["operation_id"])
                if not page["has_more"]:
                    break
                cursor = page["cursor"]
            else:
                self.fail("the changes cursor never reached the head")
            self.assertEqual(["op-1", "op-2", "op-3"], seen)
            self.assertEqual(events[1], json.loads(text))
            self.assertEqual("3", page["cursor"])
            invalid = await client.session.call_tool("changes", {"cursor": "2~999999"})
            self.assertTrue(invalid.is_error)
            self.assertIn("invalid_cursor", " ".join(block.text for block in invalid.content if hasattr(block, "text")))

    async def test_list_skills_reports_which_participant_kinds_may_write(self) -> None:
        root = self.temporary / "skills"
        build_workspace(root, 0)
        async with connected(self, root) as client:
            skills = {item["name"]: item for item in (await client.call("list_skills", {}))["skills"]}
            for name in ("po-handoff", "design-start", "dev-start"):
                with self.subTest(skill=name):
                    skill = skills[name]
                    self.assertTrue(skill["write_supported"])
                    self.assertEqual(["agent", "human"], skill["participant_kinds"])
                    self.assertEqual({"preview_skill": ["agent"], "preview_transition": ["human"]}, skill["write_tools"])
                    line = next(text for text in skill["limitations"] if text.startswith("Direct human action"))
                    self.assertIn("participant_kind_required", line)
            for name in ("po-intake", "dev-done", "dev-clarify", "feature-reopen", "ask"):
                with self.subTest(skill=name):
                    self.assertEqual(["agent"], skills[name]["participant_kinds"])
                    self.assertEqual({"preview_skill": ["agent"]}, skills[name]["write_tools"])
                    self.assertFalse(any(text.startswith("Direct human action") for text in skills[name]["limitations"]))
            for name, skill in skills.items():
                if not skill["write_supported"]:
                    self.assertEqual([], skill["participant_kinds"], name)
                    self.assertEqual({}, skill["write_tools"], name)
            page = await client.paged("get_skill", {"name": "dev-start"})
            self.assertEqual(["agent", "human"], page[0]["skill"]["participant_kinds"])


if __name__ == "__main__":
    unittest.main()
