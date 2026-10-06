"""Shared reads discover intake and retain canonical facts without write grants."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from prism_cli import board_reads
from prism_cli.board_reads import chunk_text, compact_size, list_workspace, query
from prism_cli.board_service import BoardError, BoardService
from prism_cli.workflow_install import apply_install, plan_install
from prism_cli.wiki_query import wiki_show
from tests.test_core_workflow_fixture import _feature_page, _write_index
from tests import real_temp  # noqa: F401
from tests.wiki_files import write_index, write_status_board


class BoardReadTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        receipt = apply_install(self.root, plan_install(self.root, name="Document review", apps=["backend"]))
        self.assertEqual("applied", receipt["status"])
        path = self.root / "knowledge/wiki/features/F-001-document-review.md"
        path.write_text(_feature_page(), encoding="utf-8")
        _write_index(self.root, "raw", "po")
        self.service = BoardService(self.root)
        self.addCleanup(self.service.close)
        grant = self.service.create_participant("Read client", "agent")
        self.actor = self.service.authenticate(grant["token"])

    def test_read_only_participant_can_find_sources_and_read_canonical_facts(self):
        pending = self.root / "knowledge/intake/pending/new-brief"
        pending.mkdir()
        (pending / "brief.md").write_text("# Document review\n", encoding="utf-8")
        listing = list_workspace(self.service, self.actor, "knowledge/intake/pending")
        self.assertIn("knowledge/intake/pending/new-brief/brief.md", [item["path"] for item in listing["files"]])
        result = query(self.service, self.actor, "show", "F-001")
        canonical = wiki_show(self.root, "F-001")
        self.assertEqual(canonical["facts"]["feature"]["status"], result["facts"]["feature"]["status"])
        self.assertEqual(canonical["facts"]["feature"]["open_questions"], result["facts"]["feature"]["open_questions"])
        self.assertTrue(result["snapshot"]["consistent"])
        sources = self.service.read_workspace(self.actor, ["knowledge/wiki/features/F-001-document-review.md"])
        self.assertEqual((self.root / sources["files"][0]["path"]).read_bytes().decode("utf-8"), sources["files"][0]["content"])
        self.assertFalse(self.actor.writable)
        self.assertFalse((self.root / ".agents").exists())
        self.assertFalse((self.root / ".claude").exists())

    def test_inventory_pagination_does_not_skip_and_rejects_changed_inventory(self):
        pending = self.root / "knowledge/intake/pending/paged-brief"
        pending.mkdir()
        for index in range(103):
            (pending / f"note-{index:03}.md").write_text(f"Note {index}", encoding="utf-8")
        first = list_workspace(self.service, self.actor, "knowledge/intake/pending/paged-brief")
        self.assertEqual(100, len(first["files"]))
        second = list_workspace(self.service, self.actor, "knowledge/intake/pending/paged-brief", first["next_cursor"])
        self.assertEqual(3, len(second["files"]))
        self.assertIsNone(second["next_cursor"])
        self.assertEqual(103, len({item["path"] for item in first["files"] + second["files"]}))
        (pending / "note-new.md").write_text("New note", encoding="utf-8")
        with self.assertRaises(BoardError) as error:
            list_workspace(self.service, self.actor, "knowledge/intake/pending/paged-brief", first["next_cursor"])
        self.assertEqual("stale_source_cursor", error.exception.code)

    def test_inventory_exposes_unsupported_and_oversized_intake_files_as_metadata_only(self):
        pending = self.root / "knowledge/intake/pending/attachment-brief"
        pending.mkdir()
        (pending / "scan.pdf").write_bytes(b"%PDF synthetic attachment")
        (pending / "photo.png").write_bytes(b"\x89PNG synthetic attachment")
        (pending / "large.md").write_bytes(b"x" * (512 * 1024 + 1))

        unreadable = {pending / "scan.pdf", pending / "photo.png", pending / "large.md"}
        open_file = Path.open

        def reject_unbounded_content(path, *args, **kwargs):
            if path in unreadable:
                raise AssertionError(f"inventory/read attempted to open unsupported source {path.name}")
            return open_file(path, *args, **kwargs)

        with patch.object(Path, "open", reject_unbounded_content):
            result = list_workspace(self.service, self.actor, "knowledge/intake/pending/attachment-brief")
            with self.assertRaises(BoardError) as attachment:
                self.service.read_workspace(self.actor, ["knowledge/intake/pending/attachment-brief/scan.pdf"])
            self.assertEqual("path_not_approved", attachment.exception.code)
            with self.assertRaises(BoardError) as oversized:
                self.service.read_workspace(self.actor, ["knowledge/intake/pending/attachment-brief/large.md"])
            self.assertEqual("text_file_limit", oversized.exception.code)

        files = {item["path"].rsplit("/", 1)[-1]: item for item in result["files"]}
        self.assertEqual("unsupported_extension", files["scan.pdf"]["read_support"])
        self.assertEqual("unsupported_extension", files["photo.png"]["read_support"])
        self.assertEqual("file_too_large", files["large.md"]["read_support"])
        self.assertEqual(512 * 1024 + 1, files["large.md"]["bytes"])
        self.assertTrue(all("content" not in item and "digest" not in item for item in files.values()))

    def test_skill_read_contract_lists_installed_baseline_copies(self):
        result = self.service.get_skill(self.actor, "po-intake")["skill"]
        discover_support = self.service.discover(self.actor)["capability"]["read_support"]
        self.assertEqual(result["read_support"], discover_support)
        design_intake = self.service.get_skill(self.actor, "design-intake")["skill"]
        self.assertEqual(result["read_support"], design_intake["read_support"])
        self.assertTrue(any("text-only" in item and "cannot be omitted" in item for item in design_intake["limitations"]))
        self.assertEqual(
            {
                "encoding": "UTF-8",
                "extensions": [".md", ".txt", ".yaml", ".yml"],
                "max_file_bytes": 512 * 1024,
                "max_response_bytes": 2 * 1024 * 1024,
                "max_paths_per_request": 64,
                "inventory_content": "metadata-only; read_workspace returns eligible file content and digests",
            },
            result["read_support"],
        )
        self.assertEqual(
            {
                "knowledge/intake/README.md",
                "knowledge/intake/pending/DESIGN_HANDOFF_TEMPLATE.md",
                "knowledge/intake/pending/PO_BRIEF_TEMPLATE.md",
                "knowledge/wiki/CONNECTED.md",
                "knowledge/wiki/LIFECYCLE.md",
                "knowledge/wiki/SCHEMA.md",
                "knowledge/wiki/SETTINGS.md",
                "knowledge/wiki/advisory/_FORMAT.md",
                "knowledge/wiki/business-rules/_FORMAT.md",
                "knowledge/wiki/features/_FORMAT.md",
                "knowledge/wiki/features/F-001-document-review.md",
                "knowledge/wiki/index.md",
                "knowledge/wiki/personas/_FORMAT.md",
            },
            set(result["required_workspace_reads"]),
        )
        self.assertTrue(any("text-only" in item and "cannot be omitted" in item for item in result["limitations"]))

    def test_source_discovery_cannot_reveal_private_state_or_application_files(self):
        (self.root / ".env").write_text("TEST_SECRET=synthetic", encoding="utf-8")
        for prefix in (".", "..", ".prism/state", "backend", "knowledge/../../.env"):
            with self.subTest(prefix=prefix), self.assertRaises(BoardError):
                list_workspace(self.service, self.actor, prefix)
        paths = [item["path"] for item in list_workspace(self.service, self.actor)["files"]]
        self.assertNotIn(".env", paths)
        self.assertFalse(any(".prism" in path for path in paths))

    def test_connected_preflight_is_read_only_without_vendor_instruction_folders(self):
        result = query(self.service, self.actor, "transition-preflight", "F-001", "po-specify")
        self.assertEqual("po-specify", result["facts"]["transition"]["action"])
        self.assertTrue(result["facts"]["transition"]["supported"])
        self.assertEqual("read-only", result["capability"]["mode"])
        self.assertEqual("raw", wiki_show(self.root, "F-001")["facts"]["feature"]["status"])

    def test_revocation_applies_to_inventory_and_query(self):
        self.service.revoke_participant(self.actor.participant_id)
        for call in (lambda: list_workspace(self.service, self.actor), lambda: query(self.service, self.actor, "lint")):
            with self.assertRaises(BoardError) as error:
                call()
            self.assertEqual("unauthorized", error.exception.code)

    def test_query_reuses_owner_blocker_and_search_facts(self):
        owner = query(self.service, self.actor, "owner", "po")
        self.assertEqual(1, owner["facts"]["feature_count"])
        self.assertGreater(owner["facts"]["open_question_count"], 0)
        search = query(self.service, self.actor, "search", "Document review")
        self.assertGreater(search["facts"]["result_count"], 0)
        missing = query(self.service, self.actor, "search", "absent-unique-prose")
        self.assertEqual(0, missing["facts"]["result_count"])


class PagedReadTests(unittest.TestCase):
    """Cursor paging keeps every tool result within the structured budget."""

    BUDGET = 4000

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        receipt = apply_install(self.root, plan_install(self.root, name="Document review", apps=["backend"]))
        self.assertEqual("applied", receipt["status"])
        self.ids = [f"F-{number:03d}" for number in range(1, 15)]
        for feature_id in self.ids:
            page = _feature_page().replace("F-001", feature_id).replace("Document review", f"Document review {feature_id}")
            (self.root / f"knowledge/wiki/features/{feature_id}-document-review.md").write_text(page, encoding="utf-8", newline="\n")
        write_status_board(self.root, "".join(f"| {feature_id} | Document review {feature_id} | raw | po | not-needed |\n" for feature_id in self.ids))
        write_index(self.root)
        self.service = BoardService(self.root)
        self.addCleanup(self.service.close)
        grant = self.service.create_participant("Paging client", "agent")
        self.actor = self.service.authenticate(grant["token"])
        budget = patch.object(board_reads, "STRUCTURED_BUDGET_CHARS", self.BUDGET)
        budget.start()
        self.addCleanup(budget.stop)

    def pages(self, call):
        pages, cursor = [], None
        while True:
            page = call(cursor)
            self.assertLessEqual(compact_size(page), board_reads.STRUCTURED_BUDGET_CHARS)
            pages.append(page)
            cursor = page["next_cursor"]
            if cursor is None:
                return pages

    def test_owner_pages_return_every_feature_and_question_exactly_once(self):
        pages = self.pages(lambda cursor: query(self.service, self.actor, "owner", "po", None, cursor))
        self.assertGreater(len(pages), 2)
        self.assertEqual({28}, {page["total"] for page in pages})
        features = [item["id"] for page in pages for item in page["facts"]["features"]]
        questions = [(item["feature_id"], item["number"]) for page in pages for item in page["facts"]["open_questions"]]
        self.assertEqual(self.ids, features)
        self.assertEqual([(feature_id, "1") for feature_id in self.ids], questions)
        for page in pages:
            self.assertEqual(14, page["facts"]["feature_count"])
            self.assertEqual(14, page["facts"]["open_question_count"])
            self.assertTrue(page["snapshot"]["consistent"])
            listed = {item["path"] for item in page["facts"]["features"]} | {item["path"] for item in page["facts"]["open_questions"]}
            feature_sources = {source for source in page["sources"] if source.startswith("knowledge/wiki/features/")}
            self.assertEqual(listed, feature_sources)

    def test_search_and_platform_pages_return_every_match_exactly_once(self):
        search = self.pages(lambda cursor: query(self.service, self.actor, "search", "Document review", None, cursor))
        self.assertGreater(len(search), 1)
        paths = [item["path"] for page in search for item in page["facts"]["results"]]
        self.assertEqual(len(paths), len(set(paths)))
        self.assertEqual({len(paths)}, {page["total"] for page in search})
        self.assertTrue({f"knowledge/wiki/features/{feature_id}-document-review.md" for feature_id in self.ids} <= set(paths))
        for page in search:
            self.assertEqual(len(paths), page["facts"]["result_count"])
        # Features become platform-active once they leave raw.
        for feature_id in self.ids:
            path = self.root / f"knowledge/wiki/features/{feature_id}-document-review.md"
            path.write_text(path.read_text(encoding="utf-8").replace("status: raw", "status: ready-for-design"), encoding="utf-8", newline="\n")
        # Their missing requirement pages add diagnostics that repeat on every page.
        with patch.object(board_reads, "STRUCTURED_BUDGET_CHARS", 8000):
            platform = self.pages(lambda cursor: query(self.service, self.actor, "app", "backend", None, cursor))
        self.assertGreater(len(platform), 1)
        self.assertEqual(self.ids, [item["id"] for page in platform for item in page["facts"]["features"]])

    def test_an_oversize_query_item_is_replaced_by_a_placeholder_that_names_it(self):
        # One open question larger than a whole result must not drop out of the paging silently.
        path = self.root / "knowledge/wiki/features/F-007-document-review.md"
        page = path.read_text(encoding="utf-8").replace(
            "| 1 | Which points should a review summary highlight? | po | open |",
            "| 1 | " + "Which points should a review summary highlight? " * 150 + " | po | open |",
        )
        path.write_text(page, encoding="utf-8", newline="\n")
        pages = self.pages(lambda cursor: query(self.service, self.actor, "owner", "po", None, cursor))
        questions = [item for page in pages for item in page["facts"]["open_questions"]]
        self.assertEqual(self.ids, [item["feature_id"] for item in questions])
        placeholders = [item for item in questions if item.get("oversize")]
        self.assertEqual(["F-007"], [item["feature_id"] for item in placeholders])
        placeholder = placeholders[0]
        self.assertEqual("knowledge/wiki/features/F-007-document-review.md", placeholder["path"])
        self.assertGreater(placeholder["size_chars"], board_reads.STRUCTURED_BUDGET_CHARS)
        self.assertNotIn("question", placeholder)
        self.assertIn("read_workspace", placeholder["note"])
        self.assertEqual([item["id"] for item in pages[0]["facts"]["features"]][:1], ["F-001"])
        self.assertEqual(self.ids, [item["id"] for page in pages for item in page["facts"]["features"]])
        # The same page again is identical: the replacement depends only on the item and its position.
        again = self.pages(lambda cursor: query(self.service, self.actor, "owner", "po", None, cursor))
        self.assertEqual([page["next_cursor"] for page in pages], [page["next_cursor"] for page in again])

    def test_small_results_keep_their_shape_and_add_a_null_cursor(self):
        with patch.object(board_reads, "STRUCTURED_BUDGET_CHARS", board_reads.RESULT_BUDGET_CHARS - 2000):
            owner = query(self.service, self.actor, "owner", "po")
            self.assertIsNone(owner["next_cursor"])
            self.assertEqual(28, owner["total"])
            self.assertEqual(14, len(owner["facts"]["features"]))
            self.assertEqual(14, len(owner["facts"]["open_questions"]))
            missing = query(self.service, self.actor, "search", "absent-unique-prose")
            self.assertEqual((0, [], None), (missing["total"], missing["facts"]["results"], missing["next_cursor"]))
            for kind, value in (("show", "F-001"), ("lint", None), ("blockers", None)):
                result = query(self.service, self.actor, kind, value)
                self.assertIsNone(result["next_cursor"], kind)
                self.assertNotIn("total", result)

    def test_query_cursors_are_validated(self):
        first = query(self.service, self.actor, "owner", "po")
        cursor = first["next_cursor"]
        self.assertIsNotNone(cursor)
        for bad in ("", "not-base64!", "e30=", cursor[:-3], "x" * 5000):
            with self.subTest(cursor=bad[:12]), self.assertRaises(BoardError) as error:
                query(self.service, self.actor, "owner", "po", None, bad)
            self.assertEqual(("invalid_cursor", 400), (error.exception.code, error.exception.status))
        with self.assertRaises(BoardError) as other_value:
            query(self.service, self.actor, "owner", "designer", None, cursor)
        self.assertEqual("invalid_cursor", other_value.exception.code)
        with self.assertRaises(BoardError) as other_kind:
            query(self.service, self.actor, "search", "po", None, cursor)
        self.assertEqual("invalid_cursor", other_kind.exception.code)
        with self.assertRaises(BoardError) as unpaged:
            query(self.service, self.actor, "show", "F-001", None, cursor)
        self.assertEqual(("invalid_query", 400), (unpaged.exception.code, unpaged.exception.status))
        path = self.root / "knowledge/wiki/features/F-001-document-review.md"
        path.write_text(path.read_text(encoding="utf-8") + "\nAdded after the first page.\n", encoding="utf-8", newline="\n")
        with self.assertRaises(BoardError) as stale:
            query(self.service, self.actor, "owner", "po", None, cursor)
        self.assertEqual(("stale_cursor", 409), (stale.exception.code, stale.exception.status))

    def test_skill_index_lists_references_without_bodies_and_chunks_reassemble(self):
        with patch.object(board_reads, "STRUCTURED_BUDGET_CHARS", board_reads.RESULT_BUDGET_CHARS - 2000):
            page = self.service.get_skill(self.actor, "po-intake")
        skill = page["skill"]
        self.assertIsNone(page["next_cursor"])
        self.assertEqual({"path", "title", "size_chars", "digest"}, {key for item in skill["references"] for key in item})
        by_path = {item["path"]: item for item in skill["references"]}
        catalog = {item["path"]: item for item in self.service._asset_get("po-intake")["references"]}
        self.assertEqual(set(catalog), set(by_path))
        self.assertTrue(by_path["knowledge/wiki/SCHEMA.md"]["title"].startswith("Wiki schema"))
        for path, entry in by_path.items():
            chunks = self.pages(lambda cursor, path=path: self.service.get_skill_reference(self.actor, "po-intake", path, cursor))
            text = "".join(chunk["content"] for chunk in chunks)
            self.assertEqual(catalog[path]["content"], text)
            self.assertEqual(entry["size_chars"], len(text), path)
            self.assertEqual(entry["digest"], "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest(), path)
            self.assertEqual({entry["digest"]}, {chunk["digest"] for chunk in chunks})
            self.assertEqual({len(text)}, {chunk["total_chars"] for chunk in chunks})
            starts = [0]
            for chunk in chunks[:-1]:
                starts.append(starts[-1] + len(chunk["content"]))
            self.assertEqual(starts, [chunk["offset"] for chunk in chunks])
        lifecycle_chunks = self.pages(lambda cursor: self.service.get_skill_reference(self.actor, "po-intake", "knowledge/wiki/LIFECYCLE.md", cursor))
        self.assertGreater(len(lifecycle_chunks), 5)

    def test_reference_cursors_are_bound_to_one_skill_and_reference(self):
        first = self.service.get_skill_reference(self.actor, "po-intake", "knowledge/wiki/SCHEMA.md")
        cursor = first["next_cursor"]
        self.assertIsNotNone(cursor)
        for call in (
            lambda: self.service.get_skill_reference(self.actor, "po-intake", "knowledge/wiki/CONNECTED.md", cursor),
            lambda: self.service.get_skill_reference(self.actor, "design-intake", "knowledge/wiki/SCHEMA.md", cursor),
            lambda: self.service.get_skill_reference(self.actor, "po-intake", "knowledge/wiki/SCHEMA.md", "garbage"),
            lambda: self.service.get_skill(self.actor, "po-intake", cursor),
        ):
            with self.assertRaises(BoardError) as error:
                call()
            self.assertEqual(("invalid_cursor", 400), (error.exception.code, error.exception.status))

    def test_instructions_and_required_reads_continue_with_a_cursor(self):
        with patch.object(board_reads, "STRUCTURED_BUDGET_CHARS", board_reads.RESULT_BUDGET_CHARS - 2000):
            whole = self.service.get_skill(self.actor, "po-handoff")["skill"]
        with patch.object(board_reads, "STRUCTURED_BUDGET_CHARS", 5000):
            pages = self.pages(lambda cursor: self.service.get_skill(self.actor, "po-handoff", cursor))
        self.assertGreater(len(pages), 1)
        text = "".join(page["skill"]["instructions"] for page in pages)
        self.assertEqual(whole["instructions"], text)
        self.assertEqual({whole["instructions_chunk"]["digest"]}, {page["skill"]["instructions_chunk"]["digest"] for page in pages})
        self.assertEqual("sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest(), whole["instructions_chunk"]["digest"])
        self.assertEqual(whole["required_workspace_reads"], [item for page in pages for item in page["skill"]["required_workspace_reads"]])
        self.assertEqual(whole["references"], pages[-1]["skill"]["references"])
        offsets = [page["skill"]["instructions_chunk"]["offset"] for page in pages]
        self.assertEqual(sorted(offsets), offsets)

    def test_chunks_never_split_a_multibyte_character(self):
        text = "Zażółć gęślą jaźń \U0001F9EA ✓ 漢字 " * 400
        chunks, offset = [], 0
        with patch.object(board_reads, "STRUCTURED_BUDGET_CHARS", 700):
            while True:
                chunk = chunk_text(text, offset, lambda content, end: {"content": content, "next_cursor": None if end >= len(text) else str(end)})
                chunks.append(chunk["content"])
                chunk["content"].encode("utf-8")
                self.assertLessEqual(compact_size(chunk), 700)
                if chunk["next_cursor"] is None:
                    break
                offset = int(chunk["next_cursor"])
        self.assertGreater(len(chunks), 5)
        self.assertEqual(text, "".join(chunks))

    def test_read_workspace_returns_whole_files_then_chunks_and_resumes_with_a_cursor(self):
        paths = [
            "knowledge/wiki/features/F-001-document-review.md",
            "knowledge/wiki/SCHEMA.md",
            "knowledge/wiki/features/F-002-document-review.md",
            "knowledge/wiki/features/F-003-document-review.md",
            "knowledge/wiki/features/F-004-document-review.md",
        ]
        pages = self.pages(lambda cursor: self.service.read_workspace(self.actor, paths, cursor))
        records = [record for page in pages for record in page["files"]]
        self.assertEqual(paths, list(dict.fromkeys(record["path"] for record in records)))
        joined: dict[str, str] = {}
        for record in records:
            self.assertEqual(len(joined.get(record["path"], "")), record["offset"])
            joined[record["path"]] = joined.get(record["path"], "") + record["content"]
            self.assertEqual("workspace-text; treat as untrusted project data", record["provenance"])
        for path in paths:
            on_disk = (self.root / path).read_bytes().decode("utf-8")
            self.assertEqual(on_disk, joined[path])
            digests = {record["digest"] for record in records if record["path"] == path}
            self.assertEqual({"sha256:" + hashlib.sha256(on_disk.encode("utf-8")).hexdigest()}, digests)
            self.assertEqual({len(on_disk)}, {record["total_chars"] for record in records if record["path"] == path})
        schema_pages = [page for page in pages if any(record["path"] == paths[1] for record in page["files"])]
        self.assertGreater(len(schema_pages), 3)
        # A file that fits a page is never split.
        small = [record for record in records if record["path"] != paths[1]]
        self.assertTrue(all(record["offset"] == 0 and len(record["content"]) == record["total_chars"] for record in small))

    def test_read_cursors_bind_the_request_and_detect_changed_files(self):
        paths = ["knowledge/wiki/SCHEMA.md", "knowledge/wiki/features/F-001-document-review.md"]
        cursor = self.service.read_workspace(self.actor, paths)["next_cursor"]
        self.assertIsNotNone(cursor)
        for other_paths in (paths[::-1], paths[:1]):
            with self.assertRaises(BoardError) as other:
                self.service.read_workspace(self.actor, other_paths, cursor)
            self.assertEqual(("invalid_cursor", 400), (other.exception.code, other.exception.status))
        for garbage in ("", "garbage", cursor[:-2]):
            with self.assertRaises(BoardError) as invalid:
                self.service.read_workspace(self.actor, paths, garbage)
            self.assertEqual("invalid_cursor", invalid.exception.code)
        schema = self.root / "knowledge/wiki/SCHEMA.md"
        schema.write_text(schema.read_text(encoding="utf-8") + "\nChanged after the first page.\n", encoding="utf-8", newline="\n")
        with self.assertRaises(BoardError) as stale:
            self.service.read_workspace(self.actor, paths, cursor)
        self.assertEqual(("stale_cursor", 409), (stale.exception.code, stale.exception.status))

    def test_read_limits_and_approved_paths_are_unchanged_by_paging(self):
        with self.assertRaises(BoardError) as outside:
            self.service.read_workspace(self.actor, ["prism.workspace.yml"])
        self.assertEqual("path_not_approved", outside.exception.code)
        with self.assertRaises(BoardError) as too_many:
            self.service.read_workspace(self.actor, [f"knowledge/wiki/features/F-{number:03d}.md" for number in range(65)])
        self.assertEqual("invalid_paths", too_many.exception.code)
        with self.assertRaises(BoardError) as duplicate:
            self.service.read_workspace(self.actor, ["knowledge/wiki/index.md", "knowledge/wiki/index.md"])
        self.assertEqual("duplicate_path", duplicate.exception.code)


class ResultShapingTests(unittest.TestCase):
    """Pure helpers that keep MCP results within the budget and free of absolute paths."""

    def test_relativize_paths_removes_every_root_spelling_and_keeps_other_text(self):
        roots = [r"C:\Users\Example\AppData\Local\Temp\prism-board-preview-ab12", "C:/work/board"]
        data = {
            "root": r"C:\Users\Example\AppData\Local\Temp\prism-board-preview-ab12",
            "path": r"c:\users\example\appdata\local\temp\prism-board-preview-ab12\knowledge\wiki\features\F-001.md",
            "also": "C:/work/board/knowledge/wiki/index.md",
            "message": r"Missing C:\work\board\knowledge\wiki\log.md, then retry.",
            "sibling": "C:/work/board2/knowledge/x.md",
            "nested": [{"p": "C:/work/board/prism.workspace.yml"}, 3, None, True],
        }
        result = board_reads.relativize_paths(data, roots)
        self.assertEqual(".", result["root"])
        self.assertEqual("knowledge/wiki/features/F-001.md", result["path"])
        self.assertEqual("knowledge/wiki/index.md", result["also"])
        self.assertEqual("Missing knowledge/wiki/log.md, then retry.", result["message"])
        self.assertEqual("C:/work/board2/knowledge/x.md", result["sibling"])
        self.assertEqual([{"p": "prism.workspace.yml"}, 3, None, True], result["nested"])
        self.assertEqual({"a": "b"}, board_reads.relativize_paths({"a": "b"}, []))

    def test_shrink_to_budget_leaves_a_fitting_result_alone_and_names_every_cut(self):
        small = {"state": "applied", "applied_paths": ["a", "b"]}
        self.assertIs(small, board_reads.shrink_to_budget(small))
        receipt = {"state": "applied", "applied_paths": [f"knowledge/wiki/features/F-{number:04d}-long-feature-name.md" for number in range(2000)], "conflicts": [{"path": "x", "reason": "y"}]}
        result = board_reads.shrink_to_budget(receipt)
        self.assertLessEqual(compact_size(result), board_reads.STRUCTURED_BUDGET_CHARS)
        self.assertEqual(receipt["applied_paths"][: len(result["applied_paths"])], result["applied_paths"])
        self.assertEqual(2000 - len(result["applied_paths"]), result["truncated"]["applied_paths"])
        self.assertEqual([{"path": "x", "reason": "y"}], result["conflicts"])
        self.assertIn("truncated", result["truncated_note"])
        self.assertEqual(2000, len(receipt["applied_paths"]), "the input is not modified")
        text = board_reads.shrink_to_budget({"message": "x" * 100000})
        self.assertLessEqual(compact_size(text), board_reads.STRUCTURED_BUDGET_CHARS)
        self.assertIn("message#chars", text["truncated"])

    def _items(self):
        return [
            {"path": "a.md", "role": "canonical", "before": None, "after": "new file\n"},
            {"path": "b.md", "role": "canonical", "before": "old " * 9000, "after": "new " * 9000},
            {"path": "c.md", "role": "index", "before": "", "after": "row\n"},
            {"path": "d.md", "role": "log", "before": None, "after": None},
        ]

    def _walk(self, items, **extra):
        pages, cursor = [], None
        while True:
            page = board_reads.page_bodies({"id": "x", "state": "pending"}, "writes", items, cursor, tag="preview", ident="p-1", digest="d1", **extra)
            pages.append(page)
            cursor = page["next_cursor"]
            if cursor is None:
                return pages
            self.assertLess(len(pages), 50)

    def test_page_bodies_returns_whole_items_then_chunks_and_every_side_reassembles(self):
        items = self._items()
        pages = self._walk(items)
        self.assertGreater(len(pages), 2)
        joined = {}
        for page in pages:
            self.assertLessEqual(compact_size(page), board_reads.STRUCTURED_BUDGET_CHARS)
            self.assertEqual({"id": "x", "state": "pending"}, {key: page[key] for key in ("id", "state")})
            for entry in page["writes"]:
                held = joined.setdefault(entry["path"], {"before": None, "after": None})
                for side in ("before", "after"):
                    if isinstance(entry.get(side), str):
                        chunk = entry.get(f"{side}_chunk")
                        self.assertEqual(len(held[side] or ""), chunk["offset"] if chunk else 0)
                        held[side] = (held[side] or "") + entry[side]
        for item in items:
            self.assertEqual(item["before"], joined[item["path"]]["before"], item["path"])
            self.assertEqual(item["after"], joined[item["path"]]["after"], item["path"])
        self.assertEqual(["a.md", "b.md", "c.md", "d.md"], list(joined))
        first_entry = pages[0]["writes"][0]
        self.assertEqual((None, "new file\n", 9, None), (first_entry["before"], first_entry["after"], first_entry["after_chars"], first_entry["before_chars"]))

    def test_page_bodies_without_items_is_one_empty_page(self):
        page = board_reads.page_bodies({"id": "x"}, "writes", [], None, tag="preview", ident="p-1", digest="d1")
        self.assertEqual([], page["writes"])
        self.assertIsNone(page["next_cursor"])
        self.assertEqual({"offset": 0, "count": 0, "total": 0}, page["writes_chunk"])

    def test_page_bodies_cursors_are_bound_to_the_record_and_its_digest(self):
        items = self._items()
        cursor = self._walk(items)[0]["next_cursor"]
        self.assertIsNotNone(cursor)
        with self.assertRaises(BoardError) as other:
            board_reads.page_bodies({}, "writes", items, cursor, tag="preview", ident="p-2", digest="d1")
        self.assertEqual(("invalid_cursor", 400), (other.exception.code, other.exception.status))
        with self.assertRaises(BoardError) as changed:
            board_reads.page_bodies({}, "writes", items, cursor, tag="preview", ident="p-1", digest="d2")
        self.assertEqual(("stale_cursor", 409), (changed.exception.code, changed.exception.status))
        with self.assertRaises(BoardError) as tag:
            board_reads.page_bodies({}, "writes", items, cursor, tag="operation", ident="p-1", digest="d1")
        self.assertEqual("invalid_cursor", tag.exception.code)
        for garbage in ("", "garbage", cursor[:-3]):
            with self.assertRaises(BoardError) as invalid:
                board_reads.page_bodies({}, "writes", items, garbage, tag="preview", ident="p-1", digest="d1")
            self.assertEqual("invalid_cursor", invalid.exception.code)
        beyond = board_reads.encode_cursor({"t": "preview", "i": "p-1", "d": "d1", "g": 99, "o": 0})
        with self.assertRaises(BoardError) as past:
            board_reads.page_bodies({}, "writes", items, beyond, tag="preview", ident="p-1", digest="d1")
        self.assertEqual("invalid_cursor", past.exception.code)

    def test_page_bodies_chunks_never_split_a_multibyte_character(self):
        text = "naive caf\u00e9 \u2603 " * 7000
        pages = self._walk([{"path": "u.md", "role": "canonical", "before": None, "after": text}])
        joined = "".join(entry["after"] for page in pages for entry in page["writes"])
        self.assertEqual(text, joined)
        self.assertGreater(len(pages), 1)

    def test_preview_page_drops_internal_copies_and_keeps_moves_compact(self):
        envelope = {
            "schema_version": 1,
            "preview_id": "p-9",
            "checks": [{"code": "x", "status": "pass", "message": "ok"}],
            "writes": [{"path": "a.md", "role": "canonical", "before": None, "before_digest": None, "after": "x", "after_digest": "sha256:1", "merge": None}],
            "proposed_changes": [{"path": "a.md", "content": "x"}],
            "source_map": {"a.md": "sha256:1", "b.md": None},
            "read_revisions": {"a.md": "sha256:1"},
            "moves": [{"source": "s", "destination": "d", "source_digest": "sha256:2", "source_files": {"f": "sha256:3", "g": "sha256:4"}, "source_directories": ["."]}],
        }
        page = board_reads.preview_page(envelope)
        for omitted in ("proposed_changes", "source_map", "read_revisions"):
            self.assertNotIn(omitted, page)
        self.assertEqual((2, 1), (page["source_count"], page["read_revisions_count"]))
        self.assertEqual([{"source": "s", "destination": "d", "source_digest": "sha256:2", "source_file_count": 2}], page["moves"])
        self.assertIsNone(page["next_cursor"])
        self.assertEqual("x", page["writes"][0]["after"])
        # Anything that is not a preview envelope is returned as it is.
        other = {"operation": "get_preview", "args": ["p-1"]}
        self.assertIs(other, board_reads.preview_page(other, "ignored"))

    def test_changes_page_keeps_the_cursor_of_the_last_event_it_returns(self):
        events = [{"cursor": str(number), "operation_id": f"op-{number}", "event": {"paths": ["p" * 200] * 40}, "created_at": "t"} for number in range(1, 31)]
        result = {"schema_version": 1, "cursor": "30", "head_cursor": "30", "board_revision": "r", "changes": events}
        page = board_reads.changes_page(result)
        kept = len(page["changes"])
        self.assertTrue(0 < kept < 30)
        self.assertEqual(str(kept), page["cursor"])
        self.assertTrue(page["has_more"])
        self.assertLessEqual(compact_size(page), board_reads.STRUCTURED_BUDGET_CHARS)
        whole = board_reads.changes_page({**result, "changes": events[:2], "cursor": "2", "head_cursor": "2"})
        self.assertEqual((2, "2", False), (len(whole["changes"]), whole["cursor"], whole["has_more"]))
        empty = board_reads.changes_page({**result, "changes": [], "cursor": "30"})
        self.assertEqual(("30", False), (empty["cursor"], empty["has_more"]))

    def test_an_event_larger_than_one_result_is_returned_in_chunks_and_never_skipped(self):
        big = {"cursor": "5", "operation_id": "op-5", "event": {"type": "operation-conflict", "paths": [f"knowledge/intake/processed/batch/file-{index:04d}-" + "x" * 60 + ".md" for index in range(450)]}, "created_at": "t"}
        before = [{"cursor": str(number), "operation_id": f"op-{number}", "event": {"type": "operation-applied"}, "created_at": "t"} for number in range(1, 5)]
        after = [{"cursor": "6", "operation_id": "op-6", "event": {"type": "operation-applied"}, "created_at": "t"}]
        events = [*before, big, *after]
        head = "6"

        def serve(cursor):
            # What the service returns for a cursor: the events after it, in a result of their own.
            service_cursor, resume = board_reads.parse_changes_cursor(cursor)
            after_cursor = int(service_cursor or "0")
            listed = [event for event in events if int(event["cursor"]) > after_cursor]
            result = {"schema_version": 1, "cursor": listed[-1]["cursor"] if listed else str(after_cursor), "head_cursor": head, "board_revision": "r", "changes": listed}
            return board_reads.changes_page(result, resume)

        seen, text, cursor, calls = [], [], None, 0
        while True:
            page = serve(cursor)
            calls += 1
            self.assertLessEqual(compact_size(page), board_reads.STRUCTURED_BUDGET_CHARS)
            for record in page["changes"]:
                chunk = record.get("event_chunk")
                if chunk is None:
                    seen.append(record["operation_id"])
                    continue
                self.assertEqual({"type": "operation-conflict", "chunked": True}, record["event"])
                self.assertEqual(len("".join(text)), chunk["offset"])
                text.append(chunk["text"])
                if chunk["offset"] + len(chunk["text"]) == chunk["total_chars"]:
                    seen.append(record["operation_id"])
            self.assertEqual(page["has_more"], page["cursor"] != head)
            if not page["has_more"]:
                break
            cursor = page["cursor"]
            self.assertLess(calls, 50)
        self.assertEqual([f"op-{number}" for number in range(1, 7)], seen)
        self.assertEqual(big["event"], json.loads("".join(text)))
        self.assertGreater(calls, 3)

    def test_changes_chunk_cursors_are_validated(self):
        self.assertEqual(("4", (5, 100)), board_reads.parse_changes_cursor("5~100"))
        self.assertEqual(("7", None), board_reads.parse_changes_cursor("7"))
        self.assertEqual((None, None), board_reads.parse_changes_cursor(None))
        for bad in ("0~5", "5~0"):
            with self.subTest(cursor=bad), self.assertRaises(BoardError) as error:
                board_reads.parse_changes_cursor(bad)
            self.assertEqual(("invalid_cursor", 400), (error.exception.code, error.exception.status))
        event = {"cursor": "5", "operation_id": "op-5", "event": {"type": "operation-applied"}, "created_at": "t"}
        result = {"schema_version": 1, "cursor": "5", "head_cursor": "5", "board_revision": "r", "changes": [event]}
        for resume in ((6, 1), (5, 10_000)):
            with self.subTest(resume=resume), self.assertRaises(BoardError) as error:
                board_reads.changes_page(result, resume)
            self.assertEqual("invalid_cursor", error.exception.code)
        with self.assertRaises(BoardError):
            board_reads.changes_page({**result, "changes": []}, (5, 1))


if __name__ == "__main__":
    unittest.main()
