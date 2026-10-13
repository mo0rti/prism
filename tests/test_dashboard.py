from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from prism_cli.wiki_graph import action_registry
from prism_cli.wiki_graph_html import render_html
from tests import real_temp  # noqa: F401
from tests.records_views_fixture import records_envelope


def _fresh_envelope(root: Path) -> dict:
    return {
        "schema_version": 1,
        "experimental": True,
        "command": "wiki graph",
        "root": str(root),
        "generated_at": "2026-09-08T12:00:00+02:00",
        "confidence": "high",
        "workspace": {"kind": "generated-project", "project_name": "Dashboard test", "apps": [{"id": "backend"}]},
        "facts": {
            "node_count": 0,
            "edge_count": 0,
            "nodes": [],
            "edges": [],
            "dangling_references": [],
            "setup_state": "initialized",
            "intake": {"pending": ["first-brief.md"], "quarantined": []},
            "action_registry": action_registry(),
        },
        "blocker_facts": [],
        "required_obligations": [],
        "sources": [],
        "diagnostics": [],
    }


class DashboardBootRegressionTests(unittest.TestCase):
    def test_guide_transition_and_malformed_ids_are_safe(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node.js is required for dashboard runtime checks")

        repo_root = Path(__file__).resolve().parents[1]
        harness = repo_root / "scripts" / "dashboard-boot-check.js"
        with tempfile.TemporaryDirectory() as temp_dir:
            html_path = Path(temp_dir) / "dashboard.html"
            html_path.write_text(render_html(_fresh_envelope(Path(temp_dir)), mode="live"), encoding="utf-8")
            result = subprocess.run(
                [
                    node,
                    str(harness),
                    str(html_path),
                    "--check-guide-transition",
                    "--check-escaping",
                    "--check-health-labels",
                    "--check-view-accessibility",
                    "--check-unknown-stage",
                    "--check-transitions",
                    "--check-connected-board",
                    "--check-board-defects",
                ],
                cwd=repo_root,
                capture_output=True,
                text=True,
                timeout=20,
            )

        self.assertEqual(0, result.returncode, result.stderr or result.stdout)
        self.assertIn("GUIDE TRANSITION OK", result.stdout)
        self.assertIn("ESCAPING OK", result.stdout)
        self.assertIn("HEALTH LABELS OK", result.stdout)
        self.assertIn("VIEW ACCESSIBILITY OK", result.stdout)
        self.assertIn("UNKNOWN STAGE OK", result.stdout)
        self.assertIn("LIVE RECOVERY OK", result.stdout)
        self.assertIn("TRANSITIONS OK", result.stdout)
        self.assertIn("CONNECTED BOARD OK", result.stdout)
        self.assertIn("BOARD DEFECTS OK", result.stdout)


class DashboardRecordsViewsTests(unittest.TestCase):
    """The Bugs, Releases and Incidents views render the records of a synthetic envelope that follows the data shape."""

    def run_check(self, mode: str) -> subprocess.CompletedProcess:
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node.js is required for dashboard runtime checks")
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            html_path = Path(temp_dir) / "dashboard.html"
            html_path.write_text(render_html(records_envelope(Path(temp_dir)), mode=mode), encoding="utf-8")
            html = html_path.read_text(encoding="utf-8")
            for view in ("bugs", "releases", "incidents"):
                self.assertIn(f'<button data-view="{view}">', html)
                self.assertIn(f'<section class="view" id="{view}-view" inert aria-hidden="true"></section>', html)
            return subprocess.run(
                [node, str(repo_root / "scripts" / "dashboard-boot-check.js"), str(html_path), "--check-records-views"],
                cwd=repo_root,
                capture_output=True,
                text=True,
                timeout=30,
            )

    def test_the_live_page_renders_every_record_view(self) -> None:
        result = self.run_check("live")
        self.assertEqual(0, result.returncode, result.stderr or result.stdout)
        self.assertIn("RECORDS VIEWS OK", result.stdout)

    def test_the_static_export_renders_every_record_view(self) -> None:
        result = self.run_check("snapshot")
        self.assertEqual(0, result.returncode, result.stderr or result.stdout)
        self.assertIn("RECORDS VIEWS OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
