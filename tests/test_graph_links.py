"""The wiki graph: links to records are not dangling, and the card offers `qa-fail` for an app that is ready for release (F14)."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from prism_cli.wiki_graph import GraphNode, _offered_transitions, build_graph
from tests import real_temp  # noqa: F401
from tests.lumen_checks import FIXTURE_ROOT
from tests.lumen_library import create_lumen_workspace


class RecordLinkTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="prism-graph-")
        self.addCleanup(temporary.cleanup)
        self.root = create_lumen_workspace(Path(temporary.name))
        self.wiki = self.root / "knowledge" / "wiki"
        # The end state of the Lumen case: the feature, its release record, the bug and the incident, linked as the formats say.
        shutil.copytree(FIXTURE_ROOT, self.wiki, dirs_exist_ok=True)

    def dangling(self) -> list[dict[str, str]]:
        return build_graph(self.root)["facts"]["dangling_references"]

    def test_links_to_release_records_bugs_incidents_and_technical_design_are_not_dangling(self) -> None:
        text = "\n".join(path.read_text(encoding="utf-8") for path in (self.wiki / "features").glob("*.md"))
        for folder in ("releases", "bugs", "incidents", "technical-design"):
            self.assertTrue(any((self.wiki / folder).glob("*.md")), folder)
        self.assertIn("](../releases/REL-", text)
        records = [item for item in self.dangling() if any(f"/{folder}/" in item["reference"] for folder in ("releases", "bugs", "incidents", "technical-design"))]
        self.assertEqual([], records)
        self.assertEqual([], self.dangling())

    def test_a_link_to_a_record_that_does_not_exist_is_still_dangling(self) -> None:
        feature = next((self.wiki / "features").glob("*.md"))
        feature.write_text(feature.read_text(encoding="utf-8") + "\nSee [the missing record](../releases/REL-099.md).\n", encoding="utf-8")
        self.assertEqual(["../releases/REL-099.md"], [item["reference"] for item in self.dangling()])


class OfferedTransitionTests(unittest.TestCase):
    ACTIONS = ("dev-done", "qa-fail", "qa-verify", "release-done", "release-return-dev")

    def offered(self, stages: dict[str, str], status: str = "in-dev") -> list[str]:
        node = GraphNode("F-001", "feature", "Feature", "knowledge/wiki/features/F-001.md", status=status, app_stages=tuple(stages.items()))
        return [record["action"] for record in _offered_transitions(node, [{"action": action} for action in self.ACTIONS])]

    def test_an_app_at_ready_for_release_can_still_fail_qa(self) -> None:
        offered = self.offered({"backend": "ready-for-release", "worker": "in-dev"})
        self.assertEqual(list(self.ACTIONS), offered)

    def test_a_feature_in_development_waits_for_an_app_to_reach_qa(self) -> None:
        self.assertEqual(["dev-done"], self.offered({"backend": "in-dev", "worker": "in-dev"}))
        self.assertIn("qa-fail", self.offered({"backend": "ready-for-qa", "worker": "in-dev"}))
        self.assertNotIn("release-done", self.offered({"backend": "ready-for-qa", "worker": "in-dev"}))


if __name__ == "__main__":
    unittest.main()
