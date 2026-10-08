"""Grant roles, the audit export and `state reset` through the CLI (CONTRACTS 1.1 and 1.7)."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest

from prism_cli.board_service import BoardService
from prism_cli.cli import build_parser
from prism_cli.workflow_install import apply_install, plan_install
from tests.test_board_identity import FEATURE, GatedBoardCase
from tests import real_temp  # noqa: F401


def run_cli(*argv: str) -> tuple[int, str, str]:
    args = build_parser().parse_args(argv)
    stdout, stderr = io.StringIO(), io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = args.func(args)
    return code, stdout.getvalue(), stderr.getvalue()


class GrantRoleCliTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        apply_install(self.root, plan_install(self.root, name="Roles", apps=["backend"]))

    def stored_roles(self, participant_id: str) -> str:
        connection = sqlite3.connect(self.root / ".prism/state/board.sqlite3")
        try:
            return connection.execute("SELECT roles FROM grants WHERE participant_id = ?", (participant_id,)).fetchone()[0]
        finally:
            connection.close()

    def test_a_human_grant_holds_its_roles_and_prints_them_once(self) -> None:
        code, output, _ = run_cli("board", "grant", "Quinn", "--kind", "human", "--write", "--role", "release,qa", "--path", str(self.root))
        self.assertEqual(0, code)
        granted = json.loads(output)
        self.assertEqual(["qa", "release"], granted["participant"]["roles"])
        self.assertEqual("qa,release", self.stored_roles(granted["participant"]["participant_id"]))
        self.assertTrue(granted["token"])

    def test_a_role_flag_may_be_repeated_and_none_means_no_role(self) -> None:
        code, output, _ = run_cli("board", "grant", "Devi", "--kind", "human", "--write", "--role", "dev", "--role", "qa", "--path", str(self.root))
        self.assertEqual((0, ["dev", "qa"]), (code, json.loads(output)["participant"]["roles"]))
        code, output, _ = run_cli("board", "grant", "Reader", "--kind", "human", "--path", str(self.root))
        self.assertEqual((0, []), (code, json.loads(output)["participant"]["roles"]))

    def test_each_refusal_names_its_code_and_stores_nothing(self) -> None:
        cases = [
            (("--kind", "human", "--write", "--role", "chief"), "invalid_role"),
            (("--kind", "human", "--write", "--role", "qa", "--role", "qa"), "invalid_role"),
            (("--kind", "agent", "--write", "--role", "dev"), "agent_role_forbidden"),
            (("--kind", "human", "--role", "dev"), "role_requires_write"),
        ]
        for flags, expected in cases:
            with self.subTest(flags=flags):
                code, output, error = run_cli("board", "grant", "Nobody", *flags, "--path", str(self.root))
                self.assertEqual((3, ""), (code, output))
                self.assertIn(expected, error)
        state = self.root / ".prism/state/board.sqlite3"
        if state.exists():
            connection = sqlite3.connect(state)
            try:
                self.assertEqual(0, connection.execute("SELECT COUNT(*) FROM grants").fetchone()[0])
            finally:
                connection.close()


class AuditAndResetTests(GatedBoardCase):
    def setUp(self) -> None:
        super().setUp()
        self.out_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.out_dir, True)

    def test_the_export_is_readable_and_holds_no_token_hash(self) -> None:
        preview = self.agent_proposal()
        self.approve(self.designer, preview, "approve-1")
        out = self.out_dir / "audit-export.json"
        code, output, error = run_cli("board", "audit", "export", str(self.root), "--out", str(out))
        self.assertEqual((0, ""), (code, error), error)
        self.assertEqual(str(out), json.loads(output)["audit_export"])
        text = out.read_text(encoding="utf-8")
        exported = json.loads(text)
        self.assertNotIn("token_hash", text)
        for token in self.tokens.values():
            self.assertNotIn(token, text)
        self.assertEqual({"schema_version", "exported_at", "grants", "previews", "operations", "events", "provenance"}, set(exported))
        grants = {item["name"]: item for item in exported["grants"]}
        self.assertEqual("designer", grants["Dana"]["roles"])
        self.assertEqual("", grants["Coding agent"]["roles"])
        operation = next(item for item in exported["operations"] if item["operation_id"] == "approve-1")
        self.assertEqual("applied", operation["state"])
        self.assertEqual(self.designer.participant_id, operation["intent"]["approval"]["approver"]["participant_id"])
        self.assertEqual(self.agent.participant_id, operation["intent"]["approval"]["proposer"]["participant_id"])
        self.assertEqual("applied", operation["receipt"]["state"])
        self.assertIn("repair_of", operation)
        self.assertIn("repaired_by", operation)
        preview_row = next(item for item in exported["previews"] if item["preview_id"] == preview["preview_id"])
        self.assertEqual(("design-start", "approve-1"), (preview_row["action"], preview_row["consumed_by"]))
        self.assertNotIn("payload_json", preview_row)
        self.assertTrue(exported["events"])

    def test_the_export_never_overwrites_a_file_or_lands_in_the_state_directory(self) -> None:
        out = self.out_dir / "audit-existing.json"
        out.write_text("keep me", encoding="utf-8")
        code, _, error = run_cli("board", "audit", "export", str(self.root), "--out", str(out))
        self.assertEqual(3, code)
        self.assertIn("already exists", error)
        self.assertEqual("keep me", out.read_text(encoding="utf-8"))
        code, _, error = run_cli("board", "audit", "export", str(self.root), "--out", str(self.root / ".prism/state/export.json"))
        self.assertEqual(3, code)
        self.assertIn("state", error)

    def test_a_reset_is_refused_while_an_operation_is_unresolved(self) -> None:
        preview = self.agent_proposal()
        self.crash_after_first_write(self.designer, preview, "pending-1")
        self.service.close()
        before = (self.root / ".prism/state/board.sqlite3").read_bytes()
        code, output, error = run_cli("board", "state", "reset", str(self.root))
        self.assertEqual((3, ""), (code, output))
        self.assertIn("unresolved_operations", error)
        self.assertIn("pending-1", error)
        self.assertEqual(before, (self.root / ".prism/state/board.sqlite3").read_bytes())
        self.assertFalse((self.root / ".prism/audit").exists(), "no export is written for a refused reset")

    def test_a_reset_after_everything_is_resolved_exports_then_removes_the_state(self) -> None:
        preview = self.agent_proposal()
        self.approve(self.designer, preview, "approve-1")
        self.service.close()
        code, output, error = run_cli("board", "state", "reset", str(self.root))
        self.assertEqual((0, ""), (code, error), error)
        result = json.loads(output)
        self.assertTrue(result["reset"])
        exported = json.loads(Path(result["audit_export"]).read_text(encoding="utf-8"))
        self.assertEqual({"approve-1"}, {item["operation_id"] for item in exported["operations"]})
        self.assertFalse((self.root / ".prism/state").exists())
        self.assertIn("status: in-design", self.read(FEATURE), "the wiki is untouched")
        # A fresh service starts a clean journal.
        with BoardService(self.root) as fresh:
            fresh.create_participant("Again", "human", True, roles="po")

    def test_a_reset_may_name_its_export_and_refuses_a_workspace_in_use(self) -> None:
        out = self.out_dir / "reset-export.json"
        code, _, error = run_cli("board", "state", "reset", str(self.root), "--out", str(out))
        self.assertEqual(3, code, "the running service holds the workspace lock")
        self.assertIn("holds this workspace", error)
        self.assertTrue((self.root / ".prism/state/board.sqlite3").exists())
        self.service.close()
        code, output, _ = run_cli("board", "state", "reset", str(self.root), "--out", str(out))
        self.assertEqual(0, code)
        self.assertEqual(str(out), json.loads(output)["audit_export"])
        self.assertTrue(out.exists())

    def test_a_workspace_without_state_has_nothing_to_reset(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            code, output, _ = run_cli("board", "state", "reset", temporary)
        self.assertEqual((0, False), (code, json.loads(output)["reset"]))

    def test_a_pre_role_database_can_be_exported_and_reset_when_nothing_is_pending(self) -> None:
        self.service.close()
        database = self.root / ".prism/state/board.sqlite3"
        connection = sqlite3.connect(database)
        connection.executescript(
            "DROP TABLE provenance; DROP TABLE events; DROP TABLE operations; DROP TABLE previews; DROP TABLE grants;"
            "CREATE TABLE grants (participant_id TEXT PRIMARY KEY, token_hash TEXT NOT NULL UNIQUE, name TEXT NOT NULL, kind TEXT NOT NULL, "
            "writable INTEGER NOT NULL, active INTEGER NOT NULL, board_id TEXT NOT NULL, workflow_version TEXT NOT NULL, "
            "asset_digest TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, revoked_at TEXT);"
            "CREATE TABLE operations (operation_id TEXT PRIMARY KEY, participant_id TEXT NOT NULL, preview_id TEXT NOT NULL, payload_hash TEXT NOT NULL, "
            "intent_json TEXT NOT NULL, receipt_json TEXT, state TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);"
            "INSERT INTO grants VALUES ('p1', 'hash-1', 'Old', 'human', 1, 1, 'b', '1', '', '2026-01-01T00:00:00+00:00', NULL);"
            "INSERT INTO operations VALUES ('old-pending', 'p1', 'x', 'h', '{}', NULL, 'pending', '2026-01-01', '2026-01-01');"
        )
        connection.commit()
        connection.close()
        code, _, error = run_cli("board", "state", "reset", str(self.root))
        self.assertEqual(3, code)
        self.assertIn("old-pending", error)
        connection = sqlite3.connect(database)
        connection.execute("UPDATE operations SET state = 'abandoned'")
        connection.commit()
        connection.close()
        code, output, error = run_cli("board", "state", "reset", str(self.root))
        self.assertEqual(0, code, error)
        exported = json.loads(Path(json.loads(output)["audit_export"]).read_text(encoding="utf-8"))
        self.assertNotIn("token_hash", json.dumps(exported))
        self.assertEqual(["Old"], [item["name"] for item in exported["grants"]])
        self.assertFalse((self.root / ".prism/state").exists())


if __name__ == "__main__":
    unittest.main()
