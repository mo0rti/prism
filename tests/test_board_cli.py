"""CLI compatibility and installation result reporting at the shared-board boundary."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import queue
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

import yaml

from prism_cli.cli import build_parser
from prism_cli.board_store import BoardStore
from prism_cli.workflow_assets import asset_digest
from prism_cli.workflow_install import apply_install, plan_install
from tests.manifest_fixtures import manifest_data
from tests import real_temp  # noqa: F401


class BoardCliTests(unittest.TestCase):
    def run_cli(self, *argv):
        args = build_parser().parse_args(argv)
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = args.func(args)
        return code, stdout.getvalue(), stderr.getvalue()

    def manifest(self, root, digest):
        (root / "knowledge/wiki").mkdir(parents=True, exist_ok=True)
        (root / "knowledge/wiki/SCHEMA.md").write_text("---\nschema-version: 1\n---\n# Schema\n", encoding="utf-8")
        (root / "knowledge/wiki/LIFECYCLE.md").write_text("---\nschema-version: 1\n---\n# Lifecycle\n", encoding="utf-8")
        (root / "knowledge/wiki/index.md").write_text("# Index\n", encoding="utf-8")
        (root / "prism.workspace.yml").write_text(yaml.safe_dump({
            **manifest_data("Editorial", ["backend"]),
            "workflow": {"version": "1", "mode": "workflow",
                         "board_id": "97f352fa-1ac1-4f7d-9ca0-e8246e6293bf",
                         "asset_digest": digest},
            "paths": {"wiki_root": "knowledge/wiki"},
        }), encoding="utf-8")

    def test_status_requires_the_exact_packaged_workflow_pin_and_never_creates_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for digest, expected in ((None, 3), ("0" * 64, 3), (asset_digest(), 0)):
                with self.subTest(digest=digest):
                    self.manifest(root, digest)
                    code, output, _ = self.run_cli("board", "status", str(root))
                    self.assertEqual(expected, code)
                    self.assertEqual(expected == 0, json.loads(output)["compatible"])
                    self.assertFalse((root / ".prism").exists())

    def test_status_does_not_advertise_a_missing_wiki_as_ready(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.manifest(root, asset_digest())
            (root / "knowledge/wiki/SCHEMA.md").unlink()
            code, output, _ = self.run_cli("board", "status", str(root))
            self.assertEqual(3, code)
            self.assertFalse(json.loads(output)["compatible"])
            self.assertFalse((root / ".prism").exists())

    def test_status_does_not_advertise_a_workspace_without_the_lifecycle_protocol_as_ready(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.manifest(root, asset_digest())
            (root / "knowledge/wiki/LIFECYCLE.md").unlink()
            code, output, _ = self.run_cli("board", "status", str(root))
            self.assertEqual(3, code)
            self.assertFalse(json.loads(output)["compatible"])
            self.assertFalse((root / ".prism").exists())

    def test_installer_partial_and_conflict_receipts_are_failures(self):
        for status, expected in (("applied", 0), ("unchanged", 0), ("partial", 3), ("conflict", 3)):
            with self.subTest(status=status), patch("prism_cli.workflow_install.plan_install", return_value={"changes": [], "conflicts": []}), patch("prism_cli.workflow_install.apply_install", return_value={"status": status}) as apply:
                code, output, _ = self.run_cli("workflow", "install", ".", "--apply", "--yes", "--json")
                self.assertEqual(expected, code)
                self.assertEqual(status, json.loads(output)["status"])
                apply.assert_called_once()

    def test_machine_readable_apply_requires_explicit_confirmation(self):
        with patch("prism_cli.workflow_install.plan_install", return_value={"changes": [], "conflicts": []}), patch("prism_cli.workflow_install.apply_install") as apply:
            code, _, error = self.run_cli("workflow", "install", ".", "--apply", "--json")
            self.assertEqual(2, code)
            self.assertIn("--apply --yes", error)
            apply.assert_not_called()

    def test_json_preview_round_trips_unicode_on_a_legacy_windows_output_stream(self):
        plan = {"changes": [{"path": "guidance.md", "before": None, "after": "Follow → review → confirm. فارسی"}], "conflicts": []}
        for json_mode in (True, False):
            with self.subTest(json=json_mode):
                raw = io.BytesIO()
                stream = io.TextIOWrapper(raw, encoding="cp1252")
                argv = ["workflow", "install", "."] + (["--json"] if json_mode else [])
                args = build_parser().parse_args(argv)
                with redirect_stdout(stream), patch("prism_cli.workflow_install.plan_install", return_value=plan):
                    code = args.func(args)
                stream.flush()
                output = raw.getvalue().decode("cp1252")
                self.assertEqual(0, code)
                if json_mode:
                    self.assertEqual(plan, json.loads(output))
                else:
                    self.assertIn(r"\u2192", output)
                stream.close()

    def test_the_text_plan_lists_updated_and_preserved_files(self):
        plan = {
            "changes": [],
            "conflicts": [],
            "updated": ["knowledge/wiki/SCHEMA.md", "AGENTS.md"],
            "preserved": ["knowledge/wiki/index.md"],
        }
        with patch("prism_cli.workflow_install.plan_install", return_value=plan):
            code, output, _ = self.run_cli("workflow", "upgrade", ".")
        self.assertEqual(0, code)
        lines = output.splitlines()
        self.assertIn("Updated: knowledge/wiki/SCHEMA.md", lines)
        self.assertIn("Updated: AGENTS.md", lines)
        self.assertLess(lines.index("Updated: AGENTS.md"), lines.index("Preserved: knowledge/wiki/index.md"))
        with patch("prism_cli.workflow_install.plan_install", return_value={"changes": [], "conflicts": []}):
            _, output, _ = self.run_cli("workflow", "upgrade", ".")
        self.assertNotIn("Updated:", output)

    def test_participant_management_reports_sqlite_contention_without_traceback(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.manifest(root, asset_digest())
            commands = (
                ("board", "grant", "Contention agent", "--path", str(root), "--kind", "agent"),
                ("board", "revoke", "missing-participant", "--path", str(root)),
            )
            for argv in commands:
                with self.subTest(command=argv[1]), patch.object(
                    BoardStore,
                    "transaction",
                    side_effect=sqlite3.OperationalError("database is locked"),
                ):
                    code, output, error = self.run_cli(*argv)
                    self.assertEqual(3, code)
                    self.assertEqual("", output)
                    self.assertIn("Participant management failed: database is locked", error)
                    self.assertNotIn("Traceback", error)


class _FakeUvicornServer:
    """Stands in for uvicorn.Server so serving output is tested without a socket."""

    def __init__(self, config) -> None:
        self.config = config
        self.started = True
        self.should_exit = False

    def run(self) -> None:
        return None


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _stop_process_tree(process: subprocess.Popen) -> None:
    """Stop the server and any interpreter it launched (a Windows venv launcher starts a child)."""

    if process.poll() is None:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, check=False)
        else:
            process.terminate()
    try:
        process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


class BoardServeFirstRunTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.assertEqual(
            "applied",
            apply_install(self.root, plan_install(self.root, name="First run", apps=["backend"]))["status"],
        )

    def run_cli(self, *argv):
        args = build_parser().parse_args(argv)
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = args.func(args)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_serve_prints_the_board_url_mcp_endpoint_and_grant_hint(self):
        port = _free_port()
        with patch("uvicorn.Server", _FakeUvicornServer):
            code, output, error = self.run_cli("board", "serve", str(self.root), "--port", str(port), "--no-open")

        lines = output.splitlines()
        self.assertEqual(0, code, error)
        self.assertEqual(f"Prism board: http://127.0.0.1:{port}/", lines[0])
        self.assertEqual(f"MCP endpoint: http://127.0.0.1:{port}/mcp", lines[1])
        self.assertIn('prism board grant "NAME" --kind human|agent [--write] --path ', lines[2])
        self.assertIn(str(self.root), lines[2])
        self.assertEqual("Local only. Press Ctrl+C to stop.", lines[3])

    def test_serve_hint_uses_a_dot_path_from_the_workspace_folder(self):
        from prism_cli.board_server import serve_board

        port = _free_port()
        previous = Path.cwd()
        os.chdir(self.root)
        try:
            stdout = io.StringIO()
            with patch("uvicorn.Server", _FakeUvicornServer), redirect_stdout(stdout):
                code = serve_board(Path("."), port=port, open_browser=False)
        finally:
            os.chdir(previous)

        self.assertEqual(0, code)
        self.assertTrue(stdout.getvalue().splitlines()[2].endswith("--path ."), stdout.getvalue())

    def test_banner_reaches_a_pipe_while_the_server_is_still_running(self):
        # The subprocess is not unbuffered, so only an explicit flush shows the banner before exit.
        env = {key: value for key, value in os.environ.items() if key != "PYTHONUNBUFFERED"}
        repo_root = Path(__file__).resolve().parent.parent
        port = _free_port()
        process = subprocess.Popen(
            [sys.executable, "-B", "-m", "prism_cli", "board", "serve", str(self.root), "--port", str(port), "--no-open"],
            cwd=repo_root,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        first_line: queue.Queue = queue.Queue()
        reader = threading.Thread(target=lambda: first_line.put(process.stdout.readline()), daemon=True)
        reader.start()
        try:
            try:
                line = first_line.get(timeout=30)
            except queue.Empty:
                self.fail("The board banner did not reach the pipe while the server was running.")
            self.assertEqual(f"Prism board: http://127.0.0.1:{port}/", line.strip())
            self.assertIsNone(process.poll(), "the server must still be running when the banner is read")
        finally:
            _stop_process_tree(process)
            reader.join(timeout=5)
            process.stdout.close()

    def test_busy_port_gives_one_line_error_and_exit_code_4_without_state(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as busy:
            busy.bind(("127.0.0.1", 0))
            busy.listen()
            port = busy.getsockname()[1]
            code, output, error = self.run_cli("board", "serve", str(self.root), "--port", str(port), "--no-open")

        self.assertEqual(4, code)
        self.assertEqual("", output, "the board URL must not be printed when the port is busy")
        self.assertEqual(1, len(error.strip().splitlines()), error)
        self.assertIn(f"Cannot start the Prism board on port {port}", error)
        self.assertIn("already in use", error)
        self.assertFalse((self.root / ".prism").exists(), "a busy port must not create board state")


if __name__ == "__main__":
    unittest.main()
