from __future__ import annotations

import http.client
import json
import tempfile
import threading
import time
import unittest
from datetime import date
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from prism_cli.graph_server import _GraphState, _make_handler, _workspace_fingerprint


def _create_workspace(root: Path) -> None:
    wiki = root / "knowledge" / "wiki"
    (wiki / "features").mkdir(parents=True)
    for directory in ("platform-requirements", "advisory", "personas", "business-rules", "design", "api-contracts", "decisions"):
        (wiki / directory).mkdir()
    (root / "knowledge" / "intake" / "pending").mkdir(parents=True)
    (root / "knowledge" / "intake" / "quarantined").mkdir(parents=True)
    (wiki / "SCHEMA.md").write_text("# Schema\n", encoding="utf-8")
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


class GraphServerEndpointTests(unittest.TestCase):
    def _server(self, root: Path) -> tuple[ThreadingHTTPServer, threading.Thread]:
        server = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(_GraphState(root)))
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
                    connection.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
