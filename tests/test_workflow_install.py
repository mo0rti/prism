"""Preview and recovery contracts for non-application workflow adoption."""

from pathlib import Path
import tempfile
import unittest
from argparse import Namespace
import contextlib
import io
from unittest.mock import patch
from uuid import UUID

import yaml

from prism_cli.workflow_assets import asset_digest, bootstrap_files, guidance_pointer
from prism_cli.board_cli import cmd_workflow
from prism_cli.board_service import BoardService
from prism_cli.workflow_install import apply_install, plan_install
import prism_cli.workflow_install as workflow_installer


class WorkflowInstallTests(unittest.TestCase):
    def test_empty_workspace_preview_apply_and_repeat_are_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = plan_install(root, name="Editorial", platforms=["web-user-app", "backend"])

            self.assertEqual([], plan["conflicts"])
            self.assertEqual("workflow", plan["mode"])
            self.assertTrue(any(item["path"] == "prism.workspace.yml" for item in plan["changes"]))
            self.assertFalse(plan["runtime_lock"]["required"])
            self.assertFalse((root / "prism.workspace.yml").exists(), "planning must not mutate the workspace")
            self.assertEqual("applied", apply_install(root, plan)["status"])
            self.assertFalse((root / ".prism").exists(), "first-time adoption must not create runtime state")

            manifest = yaml.safe_load((root / "prism.workspace.yml").read_text(encoding="utf-8"))
            self.assertEqual(1, manifest["schema_version"])
            self.assertEqual("Editorial", manifest["project"]["name"])
            self.assertEqual(["backend", "web-user-app"], manifest["project"]["platforms"])
            self.assertEqual("workflow", manifest["workflow"]["mode"])
            self.assertEqual(asset_digest(), manifest["workflow"]["asset_digest"])
            UUID(manifest["workflow"]["board_id"])

            for source in bootstrap_files():
                self.assertEqual(source["content"], (root / source["path"]).read_text(encoding="utf-8"))
            self.assertEqual(guidance_pointer("AGENTS.md"), (root / "AGENTS.md").read_text(encoding="utf-8"))
            self.assertIn(".prism/state/", (root / ".gitignore").read_text(encoding="utf-8"))

            repeat = plan_install(root)
            self.assertEqual([], repeat["conflicts"])
            self.assertEqual([], repeat["changes"])
            self.assertEqual(manifest["workflow"]["board_id"], repeat["board_id"])
            self.assertEqual("unchanged", apply_install(root, repeat)["status"])
            self.assertFalse((root / ".prism").exists(), "an unchanged repeat must not create runtime state")

    def test_existing_project_data_and_custom_guidance_are_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "knowledge/wiki").mkdir(parents=True)
            custom_wiki = b"# User-owned feature index\r\nkeep exact bytes\r\n"
            (root / "knowledge/wiki/index.md").write_bytes(custom_wiki)
            custom_agents = b"# My project rules\r\nKeep these rules.\r\n"
            (root / "AGENTS.md").write_bytes(custom_agents)
            (root / ".gitignore").write_text("*.scratch\n", encoding="utf-8")
            manifest_data = {
                "schema_version": 1,
                "project": {"name": "Existing", "platforms": ["backend"], "custom_owner": "team"},
                "paths": {"wiki_root": "knowledge/wiki", "custom_catalog": "docs/catalog.md"},
                "expected_surfaces": {"team": ["README.md"]},
                "local_extension": {"keep": True},
            }
            (root / "prism.workspace.yml").write_text(yaml.safe_dump(manifest_data, sort_keys=False), encoding="utf-8")

            plan = plan_install(root)
            self.assertEqual([], plan["conflicts"])
            self.assertIn("AGENTS.md", " ".join(plan["optional_steps"]))
            self.assertIn("knowledge/wiki/index.md", plan["preserved"])
            self.assertEqual("applied", apply_install(root, plan)["status"])

            updated = yaml.safe_load((root / "prism.workspace.yml").read_text(encoding="utf-8"))
            self.assertEqual("team", updated["project"]["custom_owner"])
            self.assertEqual("docs/catalog.md", updated["paths"]["custom_catalog"])
            self.assertEqual({"team": ["README.md"]}, updated["expected_surfaces"])
            self.assertEqual({"keep": True}, updated["local_extension"])
            self.assertEqual(custom_wiki, (root / "knowledge/wiki/index.md").read_bytes())
            self.assertEqual(custom_agents, (root / "AGENTS.md").read_bytes())
            self.assertTrue((root / "knowledge/wiki/CONNECTED.md").is_file())

    def test_custom_connected_binding_blocks_every_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binding = root / "knowledge/wiki/CONNECTED.md"
            binding.parent.mkdir(parents=True)
            binding.write_bytes(b"# User-owned connected rules\n")
            before = binding.read_bytes()

            plan = plan_install(root, name="Editorial", platforms=["backend"])
            self.assertTrue(any("CONNECTED.md" in item for item in plan["conflicts"]))
            receipt = apply_install(root, plan)
            self.assertEqual("conflict", receipt["status"])
            self.assertEqual(before, binding.read_bytes())
            self.assertFalse((root / "prism.workspace.yml").exists())
            self.assertFalse((root / "knowledge/wiki/SCHEMA.md").exists())

    def test_apply_rechecks_all_before_states_before_writing_anything(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".gitignore").write_text("# initial\n", encoding="utf-8")
            plan = plan_install(root, name="Editorial", platforms=["backend"])
            (root / ".gitignore").write_text("# external edit\n", encoding="utf-8")

            receipt = apply_install(root, plan)
            self.assertEqual("conflict", receipt["status"])
            self.assertIn(".gitignore changed after preview", receipt["conflicts"][0])
            self.assertEqual("# external edit\n", (root / ".gitignore").read_text(encoding="utf-8"))
            self.assertFalse((root / "prism.workspace.yml").exists())
            self.assertFalse((root / "knowledge/wiki/SCHEMA.md").exists())

    def test_random_tempfiles_never_replace_fixed_prism_temp_sentinel(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sentinel = root / "prism.workspace.yml.prism-tmp"
            sentinel.write_bytes(b"user data stays here")
            plan = plan_install(root, name="Editorial", platforms=["backend"])

            self.assertEqual("applied", apply_install(root, plan)["status"])
            self.assertEqual(b"user data stays here", sentinel.read_bytes())

    def test_manifest_changed_at_write_time_is_preserved_as_recoverable_partial(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = plan_install(root, name="Editorial", platforms=["backend"])
            external_manifest = b"user-created manifest after preview\n"
            original_write = workflow_installer._atomic_write

            def concurrent_manifest_write(workspace, relative, target, content, expected_before):
                if relative == "prism.workspace.yml":
                    target.write_bytes(external_manifest)
                return original_write(workspace, relative, target, content, expected_before)

            with patch("prism_cli.workflow_install._atomic_write", side_effect=concurrent_manifest_write):
                receipt = apply_install(root, plan)

            self.assertEqual("partial", receipt["status"])
            self.assertIn("prism.workspace.yml", receipt["remaining"])
            self.assertEqual(external_manifest, (root / "prism.workspace.yml").read_bytes())
            self.assertIn("prism.workspace.yml changed immediately before replacement", receipt["conflicts"][0])

    def test_noncanonical_manifest_paths_and_malformed_surfaces_block(self):
        cases = (
            ({"paths": {"wiki_root": "other/wiki"}}, "paths.wiki_root"),
            ({"expected_surfaces": {"ai": ".agents/skills"}}, "expected_surfaces"),
            ({"expected_surfaces": []}, "expected_surfaces"),
        )
        for extension, expected in cases:
            with self.subTest(extension=extension), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                manifest = {
                    "schema_version": 1,
                    "project": {"name": "Existing", "platforms": ["backend"]},
                    **extension,
                }
                (root / "prism.workspace.yml").write_text(yaml.safe_dump(manifest), encoding="utf-8")

                plan = plan_install(root)
                self.assertTrue(any(expected in item for item in plan["conflicts"]))
                self.assertEqual("conflict", apply_install(root, plan)["status"])
                self.assertFalse((root / "knowledge/wiki/CONNECTED.md").exists())

    def test_boolean_or_float_manifest_schema_version_is_rejected(self):
        for schema_version in (True, 1.0):
            with self.subTest(schema_version=schema_version), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / "prism.workspace.yml").write_text(
                    yaml.safe_dump({
                        "schema_version": schema_version,
                        "project": {"name": "Existing", "platforms": ["backend"]},
                    }),
                    encoding="utf-8",
                )
                plan = plan_install(root)
                self.assertTrue(any("schema_version 1" in item for item in plan["conflicts"]))
                self.assertEqual("conflict", apply_install(root, plan)["status"])

    def test_existing_stale_workflow_requires_explicit_upgrade_and_keeps_board_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            board_id = "97f352fa-1ac1-4f7d-9ca0-e8246e6293bf"
            (root / "prism.workspace.yml").write_text(yaml.safe_dump({
                "schema_version": 1,
                "project": {"name": "Existing", "platforms": ["backend"]},
                "workflow": {"version": "1", "mode": "workflow", "board_id": board_id, "asset_digest": "0" * 64},
            }), encoding="utf-8")

            blocked = plan_install(root)
            self.assertTrue(blocked["conflicts"])
            self.assertEqual("conflict", apply_install(root, blocked)["status"])
            self.assertEqual(board_id, yaml.safe_load((root / "prism.workspace.yml").read_text(encoding="utf-8"))["workflow"]["board_id"])

            upgraded = plan_install(root, upgrade=True)
            self.assertEqual([], upgraded["conflicts"])
            self.assertEqual(board_id, upgraded["board_id"])
            self.assertEqual("applied", apply_install(root, upgraded)["status"])
            after = yaml.safe_load((root / "prism.workspace.yml").read_text(encoding="utf-8"))
            self.assertEqual(asset_digest(), after["workflow"]["asset_digest"])
            self.assertEqual(board_id, after["workflow"]["board_id"])

    def test_upgrade_preview_and_apply_create_only_lock_for_pinned_workspace_without_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _adopt_empty_workspace(root)
            self.assertFalse((root / ".prism").exists())
            _make_workflow_stale(root)

            plan = plan_install(root, upgrade=True)
            self.assertEqual([], plan["conflicts"])
            self.assertEqual({"path": ".prism/state/board.lock", "required": True, "creates": True}, plan["runtime_lock"])

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                preview_result = cmd_workflow(Namespace(
                    path=str(root), workflow_command="upgrade", name=None, platform=None,
                    apply=False, yes=False, json=False,
                ))
            self.assertEqual(0, preview_result)
            self.assertIn("Create and hold runtime lock: .prism/state/board.lock", stdout.getvalue())
            self.assertFalse((root / ".prism").exists(), "preview must remain read-only")

            receipt = apply_install(root, plan)
            self.assertEqual("applied", receipt["status"])
            self.assertTrue((root / ".prism/state/board.lock").is_file())
            self.assertFalse((root / ".prism/state/board.sqlite3").exists(), "locking must not initialize SQLite or grants")

    def test_upgrade_fails_without_touching_files_while_board_service_is_running(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _adopt_empty_workspace(root)
            service = BoardService(root).start()
            try:
                _make_workflow_stale(root)
                plan = plan_install(root, upgrade=True)
                before = _snapshot_tree(root)

                receipt = apply_install(root, plan)

                self.assertEqual("conflict", receipt["status"])
                self.assertIn("already holds this workspace lock", receipt["conflicts"][0])
                self.assertEqual(before, _snapshot_tree(root))
            finally:
                service.close()

    def test_upgrade_refuses_pending_and_conflict_journal_rows_without_changes(self):
        for state in ("pending", "conflict"):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                _adopt_empty_workspace(root)
                service = BoardService(root).start()
                participant = service.create_participant("operation owner", "agent", writable=True)
                participant_id = participant["participant"]["participant_id"]
                operation_id = f"operation-{state}"
                with service.store.transaction() as connection:
                    connection.execute(
                        "INSERT INTO operations(operation_id, participant_id, preview_id, payload_hash, intent_json, receipt_json, state, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (operation_id, participant_id, "preview", "f" * 64, "{}", None, state,
                         "2026-09-22T00:00:00Z", "2026-09-22T00:00:00Z"),
                    )
                service.close()
                _make_workflow_stale(root)
                plan = plan_install(root, upgrade=True)
                before = _snapshot_tree(root)

                receipt = apply_install(root, plan)

                self.assertEqual("conflict", receipt["status"])
                self.assertIn(f"{operation_id} ({state})", receipt["conflicts"][0])
                self.assertEqual(before, _snapshot_tree(root))

    def test_upgrade_allows_empty_or_fully_applied_journal(self):
        for operation_state in (None, "applied"):
            with self.subTest(operation_state=operation_state), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                _adopt_empty_workspace(root)
                service = BoardService(root).start()
                if operation_state:
                    participant = service.create_participant("completed owner", "agent", writable=True)
                    participant_id = participant["participant"]["participant_id"]
                    with service.store.transaction() as connection:
                        connection.execute(
                            "INSERT INTO operations(operation_id, participant_id, preview_id, payload_hash, intent_json, receipt_json, state, created_at, updated_at) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            ("operation-applied", participant_id, "preview", "e" * 64, "{}", "{}", operation_state,
                             "2026-09-22T00:00:00Z", "2026-09-22T00:00:00Z"),
                        )
                service.close()
                _make_workflow_stale(root)
                plan = plan_install(root, upgrade=True)

                receipt = apply_install(root, plan)

                self.assertEqual("applied", receipt["status"])
                self.assertEqual(asset_digest(), yaml.safe_load((root / "prism.workspace.yml").read_text(encoding="utf-8"))["workflow"]["asset_digest"])

    def test_symlink_root_is_rejected_before_resolution(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            target = base / "workspace"
            target.mkdir()
            link = base / "workspace-link"
            try:
                link.symlink_to(target, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"directory symlink creation is unavailable: {exc}")
            with self.assertRaisesRegex(ValueError, "symlink, junction, or reparse"):
                plan_install(link, name="Editorial", platforms=["backend"])

    def test_symlink_inside_bootstrap_path_is_reported_without_writing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wiki = root / "knowledge/wiki"
            wiki.mkdir(parents=True)
            link = wiki / "SCHEMA.md"
            try:
                link.symlink_to(root / "missing-target.md")
            except OSError as exc:
                self.skipTest(f"file symlink creation is unavailable: {exc}")

            plan = plan_install(root, name="Editorial", platforms=["backend"])
            self.assertTrue(any("SCHEMA.md" in item and "symlink" in item for item in plan["conflicts"]))
            self.assertEqual("conflict", apply_install(root, plan)["status"])
            self.assertTrue(link.is_symlink())
            self.assertFalse((root / "prism.workspace.yml").exists())


def _adopt_empty_workspace(root: Path) -> None:
    plan = plan_install(root, name="Editorial", platforms=["backend"])
    if plan["conflicts"]:
        raise AssertionError(plan["conflicts"])
    receipt = apply_install(root, plan)
    if receipt["status"] != "applied":
        raise AssertionError(receipt)


def _make_workflow_stale(root: Path) -> None:
    manifest_path = root / "prism.workspace.yml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["workflow"]["asset_digest"] = "0" * 64
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")


def _snapshot_tree(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.relative_to(root).as_posix() != ".prism/state/board.lock"
    }


if __name__ == "__main__":
    unittest.main()
