from __future__ import annotations

import http.client
import io
import json
import socket
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch

from prism_cli.cli import build_parser
from prism_cli.graph_server import _GraphState, _make_handler, _workspace_fingerprint
from prism_cli.wiki_transitions import CAPABILITY_FILES
from tests import real_temp  # noqa: F401


def _create_workspace(root: Path) -> None:
    wiki = root / "knowledge" / "wiki"
    (wiki / "features").mkdir(parents=True)
    for directory in ("platform-requirements", "advisory", "personas", "business-rules", "design", "api-contracts", "decisions"):
        (wiki / directory).mkdir()
    (root / "knowledge" / "intake" / "pending").mkdir(parents=True)
    (root / "knowledge" / "intake" / "quarantined").mkdir(parents=True)
    (wiki / "SCHEMA.md").write_text("# Schema\n", encoding="utf-8")
    (wiki / "LIFECYCLE.md").write_text("# Lifecycle\n", encoding="utf-8")
    (wiki / "SETTINGS.md").write_text("---\nwiki-stale-after-days: 14\n---\n", encoding="utf-8")
    (wiki / "index.md").write_text(
        "# Feature Status Board\n\n"
        "| ID | Feature | Status | Owner | Board Review | Introduced |\n"
        "|----|---------|--------|-------|--------------|------------|\n\n"
        "## Other wiki pages\n",
        encoding="utf-8",
    )
    (root / "prism.workspace.yml").write_text(
        "schema_version: 1\n"
        "project:\n"
        "  name: Test\n"
        "  slug: test\n"
        "  platforms:\n"
        "    - backend\n",
        encoding="utf-8",
    )


class GraphFingerprintTests(unittest.TestCase):
    def test_fingerprint_tracks_same_length_content_and_identity_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _create_workspace(root)
            first = _workspace_fingerprint(root)
            self.assertIn(("today", date.today().isoformat()), first)

            page = root / "knowledge" / "wiki" / "SETTINGS.md"
            page.write_text("---\nwiki-stale-after-days: 15\n---\n", encoding="utf-8")
            second = _workspace_fingerprint(root)
            self.assertNotEqual(first, second)

            (root / "knowledge" / "intake" / "pending" / "brief.txt").write_text("idea", encoding="utf-8")
            third = _workspace_fingerprint(root)
            self.assertNotEqual(second, third)

            (root / "prism.workspace.yml").write_text(
                "schema_version: 1\nproject:\n  name: Demo\n  slug: test\n  platforms:\n    - backend\n",
                encoding="utf-8",
            )
            fourth = _workspace_fingerprint(root)
            self.assertNotEqual(third, fourth)

            (root / ".copier-answers.yml").write_text("_src_path: test\nproject_name: Demo\n", encoding="utf-8")
            fifth = _workspace_fingerprint(root)
            self.assertNotEqual(fourth, fifth)

            capability_path = root / CAPABILITY_FILES["codex"]
            capability_path.parent.mkdir(parents=True)
            capability_path.write_text("<!-- prism:po-handoff-contract:v1 -->\n", encoding="utf-8")
            sixth = _workspace_fingerprint(root)
            self.assertNotEqual(fifth, sixth)


class GraphServerEndpointTests(unittest.TestCase):
    def test_five_event_streams_share_published_state_without_individual_scans(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _create_workspace(root)
            state = _GraphState(root)
            server = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(state))
            server.daemon_threads = True
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            connections = []
            try:
                with patch("prism_cli.graph_server._workspace_fingerprint", side_effect=AssertionError("viewer initiated a scan")):
                    for _ in range(5):
                        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
                        connections.append(connection)
                        connection.request("GET", "/events")
                        response = connection.getresponse()
                        self.assertEqual(200, response.status)
                        self.assertEqual(f"id: {state.epoch}:1\n".encode(), response.readline())
                        self.assertEqual(b"data: 1\n", response.readline())
                        self.assertEqual(b"\n", response.readline())
                        response.close()
            finally:
                state.close()
                for connection in connections:
                    connection.close()
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)
                if getattr(self, "_graph_state", None) is not None:
                    self._graph_state.close()

    def _server(self, root: Path) -> tuple[ThreadingHTTPServer, threading.Thread]:
        state = _GraphState(root)
        server = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(state))
        state.start_watching()
        self.addCleanup(state.close)
        # Stopped again in each test's finally block, before the temporary
        # workspace is deleted, so the watcher never holds a file open then.
        self._graph_state = state
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, thread

    def test_failed_refresh_keeps_old_fingerprint_for_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _create_workspace(root)
            state = _GraphState(root)
            original_fingerprint = state.fingerprint
            (root / "knowledge" / "intake" / "pending" / "first-brief.md").write_text("idea", encoding="utf-8")

            with patch("prism_cli.graph_server.build_graph", side_effect=OSError("temporary read failure")):
                with self.assertRaises(OSError):
                    state.refresh_if_changed()
            self.assertEqual(1, state.version)
            self.assertEqual(original_fingerprint, state.fingerprint)
            self.assertTrue(state.refresh_if_changed())
            self.assertEqual(2, state.version)

    def test_data_endpoint_refreshes_after_manifest_edit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _create_workspace(root)
            server, thread = self._server(root)
            try:
                connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
                connection.request("GET", "/data.json")
                response = connection.getresponse()
                self.assertEqual(200, response.status)
                self.assertEqual("DENY", response.getheader("X-Frame-Options"))
                self.assertEqual("frame-ancestors 'none'", response.getheader("Content-Security-Policy"))
                initial = json.loads(response.read())
                self.assertEqual(1, initial["version"])
                self.assertEqual("Test", initial["envelope"]["workspace"]["project_name"])

                (root / "prism.workspace.yml").write_text(
                    "schema_version: 1\nproject:\n  name: Demo\n  slug: test\n  platforms:\n    - backend\n",
                    encoding="utf-8",
                )
                connection.request("GET", "/data.json")
                response = connection.getresponse()
                updated = json.loads(response.read())
                self.assertEqual(2, updated["version"])
                self.assertEqual("Demo", updated["envelope"]["workspace"]["project_name"])

                (root / ".copier-answers.yml").write_text("_src_path: test\nproject_name: Demo\n", encoding="utf-8")
                connection.request("GET", "/data.json")
                response = connection.getresponse()
                answers_refresh = json.loads(response.read())
                self.assertEqual(3, answers_refresh["version"])
            finally:
                connection.close()
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)
                if getattr(self, "_graph_state", None) is not None:
                    self._graph_state.close()

    def test_events_report_a_new_graph_version_after_queue_item_arrives(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _create_workspace(root)
            server, thread = self._server(root)
            try:
                with patch("prism_cli.graph_server.POLL_SECONDS", 0.01):
                    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
                    connection.request("GET", "/events")
                    response = connection.getresponse()
                    self.assertEqual(200, response.status)
                    epoch_line = response.readline()
                    self.assertTrue(epoch_line.startswith(b"id: "))
                    self.assertEqual(b"data: 1\n", response.readline())
                    self.assertEqual(b"\n", response.readline())

                    (root / "knowledge" / "intake" / "pending" / "first-brief.md").write_text("idea", encoding="utf-8")
                    deadline = time.monotonic() + 3
                    lines: list[bytes] = []
                    while time.monotonic() < deadline:
                        line = response.readline()
                        lines.append(line)
                        if line == b"data: 2\n":
                            break
                    self.assertIn(b"data: 2\n", lines)
                    self.assertIn(epoch_line.replace(b":1\n", b":2\n"), lines)
                    connection.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)
                if getattr(self, "_graph_state", None) is not None:
                    self._graph_state.close()

    def test_post_is_refused_by_read_only_server(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _create_workspace(root)
            server, thread = self._server(root)
            try:
                connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
                connection.request("POST", "/data.json")
                response = connection.getresponse()
                self.assertEqual(501, response.status)
                response.read()
                connection.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)
                if getattr(self, "_graph_state", None) is not None:
                    self._graph_state.close()

    def test_get_routes_reject_foreign_or_ambiguous_authorities(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _create_workspace(root)
            server, thread = self._server(root)
            try:
                port = server.server_port
                for route in ("/", "/index.html", "/data.json", "/events"):
                    for headers in (
                        [("Host", f"evil.example:{port}")],
                        [("Host", f"localhost.evil.example:{port}")],
                        [("Host", f"127.0.0.1:{port}"), ("Origin", "null")],
                        [("Host", f"127.0.0.1:{port}"), ("Origin", "https://evil.example")],
                        [("Host", f"127.0.0.1:{port}"), ("Sec-Fetch-Site", "cross-site")],
                        [("Host", f"127.0.0.1:{port}"), ("Sec-Fetch-Site", "same-site")],
                        [],
                    ):
                        with self.subTest(route=route, headers=headers):
                            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
                            connection.putrequest("GET", route, skip_host=True)
                            for name, value in headers:
                                connection.putheader(name, value)
                            connection.endheaders()
                            response = connection.getresponse()
                            self.assertEqual(403, response.status)
                            response.read()
                            connection.close()
                for host in (f"localhost:{port}", f"127.0.0.1:{port}"):
                    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
                    connection.request("GET", "/data.json", headers={"Host": host, "Origin": f"http://{host}"})
                    response = connection.getresponse()
                    self.assertEqual(200, response.status)
                    self.assertTrue(json.loads(response.read())["epoch"])
                    connection.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)
                if getattr(self, "_graph_state", None) is not None:
                    self._graph_state.close()

    def test_raw_duplicate_authority_headers_are_rejected(self) -> None:
        # Exercise the HTTP parser directly; intermediaries may normalize
        # duplicate headers before a network request reaches this server.
        for headers in (
            "Host: localhost:8321\r\nHost: 127.0.0.1:8321\r\n",
            "Host: localhost:8321\r\nOrigin: http://localhost:8321\r\nOrigin: null\r\n",
        ):
            with self.subTest(headers=headers):
                request = Mock()
                request.makefile.return_value = io.BytesIO(f"GET /data.json HTTP/1.1\r\n{headers}\r\n".encode())
                output = io.BytesIO()
                request.sendall.side_effect = output.write
                _make_handler(Mock())(request, ("127.0.0.1", 12345), Mock(server_port=8321))
                self.assertIn(b" 403 ", output.getvalue().split(b"\r\n", 1)[0])


class GraphServerBusyPortTests(unittest.TestCase):
    def test_busy_port_gives_one_line_error_and_exit_code_4(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, socket.socket(socket.AF_INET, socket.SOCK_STREAM) as busy:
            busy.bind(("127.0.0.1", 0))
            busy.listen()
            port = busy.getsockname()[1]
            stdout, stderr = io.StringIO(), io.StringIO()
            args = build_parser().parse_args(["wiki", "graph", temporary, "--serve", "--port", str(port)])
            with patch("webbrowser.open") as opened, redirect_stdout(stdout), redirect_stderr(stderr):
                code = args.func(args)

        self.assertEqual(4, code)
        self.assertEqual("", stdout.getvalue())
        self.assertEqual(1, len(stderr.getvalue().strip().splitlines()), stderr.getvalue())
        self.assertIn(f"Cannot start the dashboard on port {port}", stderr.getvalue())
        self.assertIn("Choose another --port", stderr.getvalue())
        opened.assert_not_called()


if __name__ == "__main__":
    unittest.main()
