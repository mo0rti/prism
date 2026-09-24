"""Shared reads discover intake and retain canonical facts without write grants."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from prism_cli.board_reads import list_workspace, query
from prism_cli.board_service import BoardError, BoardService
from prism_cli.workflow_install import apply_install, plan_install
from prism_cli.wiki_query import wiki_show
from tests.test_core_workflow_fixture import _feature_page, _write_index


class BoardReadTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        receipt = apply_install(self.root, plan_install(self.root, name="Document review", platforms=["backend"]))
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


if __name__ == "__main__":
    unittest.main()
