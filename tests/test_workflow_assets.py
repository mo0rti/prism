"""The packaged workflow catalog is complete, self-contained, and reproducible."""

import hashlib
from pathlib import Path
import subprocess
import sys
import unittest

from prism_cli.workflow_assets import asset_digest, bootstrap_files, get_skill, list_skills


REPO_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SKILLS = {
    "ask", "audit-feature", "board-review", "design-clarify", "design-handoff",
    "design-intake", "design-start", "dev-done", "dev-start", "feature-reopen",
    "feature-status", "lint-wiki", "po-clarify", "po-handoff", "po-intake",
    "po-specify", "prep-sprint", "setup-project", "wiki-blockers", "wiki-owner",
    "wiki-platform", "wiki-query", "wiki-show",
}


class WorkflowAssetsTests(unittest.TestCase):
    def test_skill_catalog_and_feature_reopen_actions_are_distinct(self):
        skills = list_skills()
        by_name = {item["name"]: item for item in skills}
        self.assertEqual(EXPECTED_SKILLS, set(by_name))
        self.assertEqual(["reopen-spec", "reopen-design", "reopen-dev"], by_name["feature-reopen"]["actions"])
        self.assertEqual("1", by_name["po-intake"]["version"])
        self.assertEqual(64, len(asset_digest()))

    def test_skill_instructions_and_references_are_complete_content_with_digests(self):
        skill = get_skill("po-intake")
        self.assertIn("##", skill["instructions"])
        self.assertIn("knowledge/wiki/CONNECTED.md", {item["path"] for item in skill["references"]})
        self.assertIn("knowledge/intake/README.md", {item["path"] for item in skill["references"]})
        self.assertNotIn("knowledge/wiki/index.md", {item["path"] for item in skill["references"]})
        for item in skill["references"]:
            self.assertEqual(hashlib.sha256(item["content"].encode("utf-8")).hexdigest(), item["digest"])

    def test_skill_references_never_substitute_template_workspace_state(self):
        workspace_state = {
            "knowledge/wiki/SETTINGS.md",
            "knowledge/wiki/WIKI_REPORT.md",
            "knowledge/wiki/index.md",
            "knowledge/wiki/log.md",
            "knowledge/wiki/advisory/BOARD.md",
            "knowledge/wiki/advisory/PROJECT_FOUNDATION.md",
        }
        for listed in list_skills():
            with self.subTest(skill=listed["name"]):
                references = {item["path"] for item in get_skill(listed["name"])["references"]}
                self.assertFalse(workspace_state.intersection(references))

    def test_bootstrap_contains_only_non_application_knowledge_sources(self):
        files = bootstrap_files()
        paths = {item["path"] for item in files}
        self.assertIn("knowledge/wiki/SCHEMA.md", paths)
        self.assertIn("knowledge/wiki/CONNECTED.md", paths)
        self.assertIn("knowledge/wiki/index.md", paths)
        self.assertIn("knowledge/intake/README.md", paths)
        self.assertTrue(all(path.startswith("knowledge/") for path in paths))
        self.assertGreaterEqual(len(files), 20)

    def test_checked_in_asset_matches_maintained_template_sources(self):
        result = subprocess.run(
            [sys.executable, "scripts/build-workflow-assets.py", "--check"],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, result.returncode, result.stderr or result.stdout)
        self.assertIn("matches maintained template skill and knowledge sources", result.stdout)


if __name__ == "__main__":
    unittest.main()
