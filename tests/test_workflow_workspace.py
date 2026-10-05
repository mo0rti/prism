"""Workflow adoption removes application coupling, not wiki integrity checks."""

from pathlib import Path
import tempfile
import unittest

import yaml

from prism_cli.workspace import detect_workspace_kind, inspect_workspace
from tests.manifest_fixtures import manifest_data
from tests import real_temp  # noqa: F401


class WorkflowWorkspaceTests(unittest.TestCase):
    def inspect(self, root, *, mode="workflow", version="1"):
        (root / "prism.workspace.yml").write_text(yaml.safe_dump({
            **manifest_data("Editorial", ["backend"]),
            "workflow": {"version": version, "mode": mode,
                         "board_id": "97f352fa-1ac1-4f7d-9ca0-e8246e6293bf"},
            "paths": {"wiki_root": "knowledge/wiki"},
        }), encoding="utf-8")
        return inspect_workspace(root)

    def test_workflow_requires_no_copier_or_application_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "knowledge/wiki").mkdir(parents=True)
            result = self.inspect(root)
            self.assertEqual("workflow-project", detect_workspace_kind(root))
            self.assertEqual(["backend"], result.platforms)
            self.assertEqual([], result.contract_diagnostics)

    def test_generated_mode_still_reports_missing_application(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.inspect(Path(tmp), mode="generated")
            codes = {item.code for item in result.contract_diagnostics}
            self.assertIn("manifest-filesystem-drift", codes)
            self.assertIn("missing-copier-answers", codes)

    def test_workflow_paths_and_future_version_are_still_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.inspect(Path(tmp), version="99")
            codes = {item.code for item in result.contract_diagnostics}
            self.assertIn("missing-manifest-path", codes)
            self.assertIn("unsupported-workflow-version", codes)

    def test_template_repo_cannot_be_reclassified_by_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "template").mkdir()
            (root / "copier.yml").write_text("", encoding="utf-8")
            self.inspect(root)
            self.assertEqual("template", detect_workspace_kind(root))


if __name__ == "__main__":
    unittest.main()
