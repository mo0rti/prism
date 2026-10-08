"""`LIFECYCLE.md` is a required wiki file and a context read of every lifecycle operation; `ACTIONS.md` is a required wiki file and a read of every lifecycle action."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from prism_cli.board_service import BoardError, BoardService, BoardServiceIdentity
from prism_cli.wiki_lint import lint_wiki
from prism_cli.workflow_install import apply_install, plan_install
from tests import real_temp  # noqa: F401
from tests.test_core_workflow_fixture import _feature_page, _write_index

LIFECYCLE = "knowledge/wiki/LIFECYCLE.md"
ACTIONS = "knowledge/wiki/ACTIONS.md"
FEATURE = "knowledge/wiki/features/F-001-document-review.md"


class LifecycleProtocolReadTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        receipt = apply_install(self.root, plan_install(self.root, name="Document review", apps=["backend"]))
        self.assertEqual("applied", receipt["status"])
        (self.root / FEATURE).write_text(_feature_page(), encoding="utf-8")
        _write_index(self.root, "raw", "po")
        self.service = BoardService(self.root).start()
        self.addCleanup(self.service.close)
        grant = self.service.create_participant("Reader", "agent")
        self.actor = self.service.authenticate(grant["token"])
        human = self.service.create_participant("Human", "human", writable=True, roles="po")
        self.human = self.service.authenticate(human["token"], via_session=True)

    def test_the_installer_places_the_lifecycle_file_beside_the_schema(self) -> None:
        self.assertTrue((self.root / LIFECYCLE).is_file())
        self.assertTrue((self.root / "knowledge/wiki/SCHEMA.md").is_file())

    def test_the_lifecycle_file_is_an_approved_readable_wiki_file(self) -> None:
        text = (self.root / LIFECYCLE).read_bytes().decode("utf-8")
        joined = ""
        cursor = None
        while True:
            result = self.service.read_workspace(self.actor, [LIFECYCLE], cursor)
            joined += "".join(item["content"] for item in result["files"])
            cursor = result["next_cursor"]
            if cursor is None:
                break
        self.assertEqual(text, joined)

    def test_other_root_wiki_files_stay_outside_the_approved_paths(self) -> None:
        with self.assertRaises(BoardError) as error:
            self.service.read_workspace(self.actor, ["knowledge/wiki/NOTES.md"])
        self.assertEqual("path_not_approved", error.exception.code)

    def test_feature_context_includes_the_lifecycle_file(self) -> None:
        feature = self.service._resolve_feature("F-001")
        paths = self.service._feature_context_paths(feature["path"], feature["frontmatter"])
        self.assertIn(LIFECYCLE, paths)
        self.assertIn("knowledge/wiki/SCHEMA.md", paths)

    def test_a_transition_preview_records_and_rechecks_the_lifecycle_file(self) -> None:
        preview = self.service.preview_transition(self.human, "F-001", "po-handoff", {"semantic_review_acknowledged": True})
        digest = hashlib.sha256((self.root / LIFECYCLE).read_bytes()).hexdigest()
        self.assertEqual("sha256:" + digest, preview["source_map"][LIFECYCLE])
        # A change to the file after the preview changes the recorded source revision of a fresh preview.
        path = self.root / LIFECYCLE
        path.write_text(path.read_text(encoding="utf-8") + "\nChanged after the preview.\n", encoding="utf-8", newline="\n")
        again = self.service.preview_transition(self.human, "F-001", "po-handoff", {"semantic_review_acknowledged": True})
        self.assertNotEqual(preview["source_revision"], again["source_revision"])

    def test_every_skill_requires_reading_the_lifecycle_file_beside_the_schema(self) -> None:
        for name in ("po-intake", "po-handoff", "dev-done", "wiki-show"):
            with self.subTest(skill=name):
                reads: list[str] = []
                cursor = None
                while True:
                    page = self.service.get_skill(self.actor, name, cursor)
                    reads.extend(page["skill"]["required_workspace_reads"])
                    cursor = page["next_cursor"]
                    if cursor is None:
                        break
                self.assertIn(LIFECYCLE, reads)
                self.assertIn("knowledge/wiki/SCHEMA.md", reads)

    def test_the_installer_places_the_action_registry_beside_the_lifecycle_file(self) -> None:
        self.assertTrue((self.root / ACTIONS).is_file())

    def test_the_action_registry_is_an_approved_readable_wiki_file(self) -> None:
        text = (self.root / ACTIONS).read_bytes().decode("utf-8")
        result = self.service.read_workspace(self.actor, [ACTIONS])
        self.assertIsNone(result["next_cursor"])
        self.assertEqual(text, "".join(item["content"] for item in result["files"]))

    def test_a_skill_reads_the_action_registry_only_when_it_runs_a_registry_action(self) -> None:
        def reads(name: str) -> list[str]:
            collected: list[str] = []
            cursor = None
            while True:
                page = self.service.get_skill(self.actor, name, cursor)
                collected.extend(page["skill"]["required_workspace_reads"])
                cursor = page["next_cursor"]
                if cursor is None:
                    return collected

        for name in ("po-specify", "po-handoff", "design-start", "dev-done", "qa-pass", "feature-scope", "feature-reopen"):
            with self.subTest(skill=name):
                self.assertIn(ACTIONS, reads(name))
                self.assertIn(LIFECYCLE, reads(name))
        for name in ("po-intake", "po-clarify", "board-review", "bug-update", "ingest", "feature-status", "lint-wiki", "wiki-show"):
            with self.subTest(skill=name):
                self.assertNotIn(ACTIONS, reads(name))

    def test_a_transition_preview_records_the_action_registry_and_a_change_to_it_makes_the_preview_stale(self) -> None:
        preview = self.service.preview_transition(self.human, "F-001", "po-handoff", {"semantic_review_acknowledged": True})
        digest = hashlib.sha256((self.root / ACTIONS).read_bytes()).hexdigest()
        self.assertEqual("sha256:" + digest, preview["source_map"][ACTIONS])
        path = self.root / ACTIONS
        path.write_text(path.read_text(encoding="utf-8") + "\nChanged after the preview.\n", encoding="utf-8", newline="\n")
        again = self.service.preview_transition(self.human, "F-001", "po-handoff", {"semantic_review_acknowledged": True})
        self.assertNotEqual(preview["source_revision"], again["source_revision"])

    def test_lint_requires_the_action_registry_and_its_schema_version(self) -> None:
        self.assertEqual([], [item for item in lint_wiki(self.root).diagnostics if "ACTIONS" in item.path])
        original = (self.root / ACTIONS).read_text(encoding="utf-8")
        (self.root / ACTIONS).write_text("# Actions\n", encoding="utf-8", newline="\n")
        unversioned = [item for item in lint_wiki(self.root).diagnostics if item.code == "missing-schema-version"]
        self.assertEqual(["ACTIONS.md"], [Path(item.path).name for item in unversioned])
        (self.root / ACTIONS).write_text(original, encoding="utf-8", newline="\n")
        (self.root / ACTIONS).unlink()
        missing = [item for item in lint_wiki(self.root).diagnostics if item.code == "missing-required-wiki-file"]
        self.assertEqual(["ACTIONS.md"], [Path(item.path).name for item in missing])
        self.assertEqual(["error"], [item.severity for item in missing])

    def test_the_board_does_not_identify_a_workspace_without_the_action_registry(self) -> None:
        self.assertIsNotNone(BoardServiceIdentity(self.root))
        (self.root / ACTIONS).unlink()
        self.assertIsNone(BoardServiceIdentity(self.root))
        with BoardService(self.root) as service:
            self.assertIn("action registry", (service._read_only_reason or "").lower())

    def test_lint_requires_the_lifecycle_file(self) -> None:
        self.assertEqual([], [item for item in lint_wiki(self.root).diagnostics if "LIFECYCLE" in item.path])
        (self.root / LIFECYCLE).unlink()
        missing = [item for item in lint_wiki(self.root).diagnostics if item.code == "missing-required-wiki-file"]
        self.assertEqual(["LIFECYCLE.md"], [Path(item.path).name for item in missing])
        self.assertEqual(["error"], [item.severity for item in missing])

    def test_the_board_does_not_identify_a_workspace_without_the_lifecycle_file(self) -> None:
        self.assertIsNotNone(BoardServiceIdentity(self.root))
        (self.root / LIFECYCLE).unlink()
        self.assertIsNone(BoardServiceIdentity(self.root))
        with BoardService(self.root) as service:
            self.assertIn("lifecycle", (service._read_only_reason or "").lower())


if __name__ == "__main__":
    unittest.main()
