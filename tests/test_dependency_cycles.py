"""`dependency-cycle`: apps and features cannot wait for each other (CONTRACTS 8.1)."""

from __future__ import annotations

import unittest

from prism_cli.wiki_lint import lint_wiki
from tests.release_support import REQUIREMENT_TWO, ReleaseTwoFeatures

REQUIREMENT_ONE = "knowledge/wiki/app-requirements/F-001-backend.md"
REQUIREMENT_WORKER = "knowledge/wiki/app-requirements/F-001-worker.md"
PLACEHOLDER = "The document review record is available to the assigned reviewer."


class DependencyCycleTests(ReleaseTwoFeatures):
    def depend(self, path: str, text: str) -> None:
        page = self.read(path)
        self.assertIn(PLACEHOLDER, page, path)
        self.put(path, page.replace(PLACEHOLDER, text, 1))

    def findings(self, code: str = "dependency-cycle") -> list:
        return [item for item in lint_wiki(self.root).diagnostics if item.code == code]

    def test_two_features_that_wait_for_each_other_are_a_cycle(self) -> None:
        self.depend(REQUIREMENT_ONE, "This app needs F-002 to be delivered first.")
        self.depend(REQUIREMENT_TWO, "This app needs F-001 to be delivered first.")
        found = self.findings()
        self.assertEqual(1, len(found))
        self.assertEqual("error", found[0].severity)
        self.assertIn("F-001-backend", found[0].message)
        self.assertIn("F-002-backend", found[0].message)

    def test_two_apps_of_one_feature_that_wait_for_each_other_are_a_cycle(self) -> None:
        self.depend(REQUIREMENT_ONE, "Needs [the worker](F-001-worker.md) first.")
        self.depend(REQUIREMENT_WORKER, "Needs [the backend](F-001-backend.md) first.")
        self.assertEqual(1, len(self.findings()))

    def test_a_chain_without_a_loop_is_not_a_cycle(self) -> None:
        self.depend(REQUIREMENT_ONE, "This app needs F-002 to be delivered first.")
        self.depend(REQUIREMENT_WORKER, "Needs [the backend](F-001-backend.md) first.")
        self.assertEqual([], self.findings())

    def test_the_link_to_the_own_feature_is_context_and_not_a_dependency(self) -> None:
        self.depend(REQUIREMENT_ONE, "Part of F-001, built after F-002.")
        self.depend(REQUIREMENT_TWO, "Part of F-002.")
        self.assertEqual([], self.findings())

    def test_a_longer_cycle_is_reported_once(self) -> None:
        self.depend(REQUIREMENT_ONE, "Needs [the worker](F-001-worker.md) first.")
        self.depend(REQUIREMENT_WORKER, "This app needs F-002 to be delivered first.")
        self.depend(REQUIREMENT_TWO, "Needs [the backend](F-001-backend.md) first.")
        found = self.findings()
        self.assertEqual(1, len(found))
        for label in ("F-001-backend", "F-001-worker", "F-002-backend"):
            self.assertIn(label, found[0].message)

    def test_the_unreleased_dependency_still_warns_beside_the_cycle(self) -> None:
        self.depend(REQUIREMENT_ONE, "This app needs F-002 to be delivered first.")
        self.assertEqual(1, len(self.findings("cross-app-dependency")))
        self.assertEqual([], self.findings())


if __name__ == "__main__":
    unittest.main()
