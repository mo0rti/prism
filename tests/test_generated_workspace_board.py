"""A workspace from `prism new` has a writable board as soon as a grant is issued, with no `workflow upgrade` first.

`prism new` pins the packaged workflow in the manifest it generates: the version, the board identity and the digest of the
packaged assets. A workspace whose pin is missing or no longer matches the CLI stays read-only.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from uuid import UUID, uuid4

import yaml

from prism_cli.board_service import BoardError, BoardService
from prism_cli.workflow_assets import asset_digest
from tests import real_temp  # noqa: F401
from tests.layered_support import read_yaml, run_cli
from tests.test_board_service import _read_revisions

TOPIC = (
    "---\nkind: topic\ntitle: Payment flows\nstatus: current\nsources:\n- knowledge/intake/processed/2026-10-08-payments/note.md\n---\n\n"
    "## Summary\nPayments settle within one business day.\n\n"
    "## Key points\n- **Observed:** Settlement takes one business day ([note](../../intake/processed/2026-10-08-payments/note.md)).\n\n"
    "## Related pages\nNone yet.\n"
)
FOLDER = "2026-10-08-payments"


class GeneratedBoardTests(unittest.TestCase):
    def generate(self, root: Path) -> Path:
        workspace = root / "workspace"
        code, out, err = run_cli("new", "--preset", "backend-only", "--project-name", "Out Of Box", "--dest", str(workspace), "--yes")
        self.assertEqual(0, code, out + err)
        return workspace

    def test_the_generated_manifest_records_the_pinned_workflow_asset(self) -> None:
        with tempfile.TemporaryDirectory(prefix="prism-board-pin-") as temporary:
            workspace = self.generate(Path(temporary))
            workflow = read_yaml(workspace / "prism.workspace.yml")["workflow"]
            self.assertEqual(("1", "generated", asset_digest("1")), (workflow["version"], workflow["mode"], workflow["asset_digest"]))
            self.assertEqual(workflow["board_id"], str(UUID(workflow["board_id"])))
            ignored = (workspace / ".gitignore").read_text(encoding="utf-8")
            self.assertIn(".prism/state/", ignored)
            attributes = (workspace / ".gitattributes").read_text(encoding="utf-8")
            self.assertIn("* text=auto eol=lf", attributes)
            # Nothing left for an explicit upgrade to pin: its preview changes no file but the runtime lock it holds.
            code, preview, err = run_cli("workflow", "upgrade", "--json", str(workspace))
            self.assertEqual(0, code, err)
            self.assertEqual([], json.loads(preview)["changes"])

    def test_a_grant_from_the_cli_writes_through_the_board_without_a_workflow_upgrade(self) -> None:
        with tempfile.TemporaryDirectory(prefix="prism-board-write-") as temporary:
            workspace = self.generate(Path(temporary))
            code, granted, err = run_cli("board", "grant", "Writer", "--kind", "agent", "--write", "--path", str(workspace))
            self.assertEqual(0, code, err)
            token = json.loads(granted)["token"]

            folder = workspace / "knowledge" / "intake" / "pending" / FOLDER
            folder.mkdir(parents=True)
            (folder / "note.md").write_text("Captured: 2026-10-08\n\nPayments settle within one business day.\n", encoding="utf-8")
            destination = f"knowledge/intake/processed/{FOLDER}"
            changes = [
                {"path": "knowledge/wiki/topics/payment-flows.md", "content": TOPIC},
                {"path": f"{destination}/MANIFEST.md", "content": "# Processed intake\n\n- knowledge/wiki/topics/payment-flows.md\n"},
            ]
            moves = [{"source": f"knowledge/intake/pending/{FOLDER}", "destination": destination}]
            with BoardService(workspace) as service:
                service.start()
                self.assertEqual({"read_only": False, "reason": None}, service.compatibility())
                agent = service.authenticate(token)
                preview = service.preview_skill(agent, "ingest", changes, moves, _read_revisions(service, agent, "ingest", changes, moves))
                self.assertTrue(preview["applicable"], preview["blockers"])
                receipt = service.apply(agent, preview["preview_id"], str(uuid4()))
                self.assertEqual("applied", receipt["state"])
            self.assertEqual(TOPIC, (workspace / "knowledge" / "wiki" / "topics" / "payment-flows.md").read_text(encoding="utf-8"))
            self.assertTrue((workspace / destination / "note.md").is_file())

    def test_a_missing_or_stale_pin_keeps_the_board_read_only(self) -> None:
        with tempfile.TemporaryDirectory(prefix="prism-board-readonly-") as temporary:
            workspace = self.generate(Path(temporary))
            manifest_path = workspace / "prism.workspace.yml"
            original = manifest_path.read_text(encoding="utf-8")
            manifest = yaml.safe_load(original)

            stale = dict(manifest, workflow=dict(manifest["workflow"], asset_digest="0" * 64))
            manifest_path.write_text(yaml.safe_dump(stale, sort_keys=False), encoding="utf-8")
            with BoardService(workspace) as service:
                self.assertTrue(service.compatibility()["read_only"])
                self.assertIn("workflow upgrade", service.compatibility()["reason"])
                with self.assertRaises(BoardError) as caught:
                    service.create_participant("Writer", "agent", True)
                self.assertEqual("workspace_read_only", caught.exception.code)

            unpinned = {key: value for key, value in manifest.items() if key != "workflow"}
            manifest_path.write_text(yaml.safe_dump(unpinned, sort_keys=False), encoding="utf-8")
            with BoardService(workspace) as service:
                self.assertTrue(service.compatibility()["read_only"])
                self.assertIn("upgrade", service.compatibility()["reason"])


if __name__ == "__main__":
    unittest.main()
