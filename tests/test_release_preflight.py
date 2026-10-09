"""The read-only side of the release actions: the evaluator, the preflight, the graph and the discovery of the skill (CONTRACTS 2.3, 7; cases 10.2 and 10.3)."""

from __future__ import annotations

import unittest

from prism_cli.board_service import BoardError
from prism_cli.wiki_graph import build_graph
from prism_cli.wiki_transitions import ACTION_BY_ID, build_board_transition_preflight, build_transition_preflight
from prism_cli.workflow_assets import get_skill, list_skills
from tests.release_support import BUGS, FEATURE, SETTINGS, ReleaseTests, bug_page


def check(transition: dict, code: str) -> dict:
    matches = [item for item in transition["checks"] if item["code"] == code]
    assert matches, (code, [item["code"] for item in transition["checks"]])
    return matches[0]


class ReleasePreflightTests(ReleaseTests):
    def preflight(self, action: str = "release-done", named: list[str] | None = None) -> dict:
        return build_board_transition_preflight(self.root, "F-001", action, named_apps=named)

    def test_a_feature_ready_for_release_is_ready_for_release_done(self) -> None:
        transition = self.preflight()
        self.assertEqual("ready", transition["classification"], transition["checks"])
        self.assertEqual(("released", "none"), (transition["target_status"], transition["target_owner"]))
        self.assertEqual("pass", check(transition, "release-apps")["status"])
        self.assertEqual("pass", check(transition, "release-target")["status"])
        self.assertIn("`backend` to `production`", check(transition, "release-target")["message"])
        self.assertEqual("pass", check(transition, "qa-coverage")["status"])
        self.assertEqual("pass", check(transition, "open-bugs")["status"])

    def test_the_named_apps_decide_the_target_status(self) -> None:
        transition = self.preflight(named=["backend"])
        self.assertEqual("ready", transition["classification"])
        self.assertEqual(("ready-for-release", "release"), (transition["target_status"], transition["target_owner"]))

    def test_an_app_without_a_delivery_target_blocks(self) -> None:
        self.put(SETTINGS, "---\nwiki-stale-after-days: 365\ndelivery-targets:\n  backend: {kind: deployment, target: production}\n---\n")
        transition = self.preflight()
        self.assertEqual("blocked", transition["classification"])
        self.assertEqual("blocked", check(transition, "release-target")["status"])
        self.assertIn("worker", check(transition, "release-target")["message"])
        self.assertEqual("ready", self.preflight(named=["backend"])["classification"])

    def test_an_open_blocking_bug_blocks_its_app_only(self) -> None:
        self.put(f"{BUGS}/BUG-001-open.md", bug_page("BUG-001", status="open", apps=["backend"]))
        transition = self.preflight()
        self.assertEqual("blocked", transition["classification"])
        self.assertEqual("blocked", check(transition, "open-bugs")["status"])
        self.assertEqual("ready", self.preflight(named=["worker"])["classification"])

    def test_pending_revalidation_blocks(self) -> None:
        self.put(FEATURE, self.frontmatter_with(self.read(FEATURE), **{"app-revalidation": {"backend": ["qa"]}}))
        transition = self.preflight()
        self.assertEqual("blocked", transition["classification"])
        self.assertEqual("blocked", check(transition, "revalidation")["status"])

    def test_stale_qa_evidence_blocks(self) -> None:
        self.put(FEATURE, self.read(FEATURE).replace("A reviewer can record the outcome of a backend review.", "A reviewer can record the outcome of a backend review quickly."))
        transition = self.preflight()
        self.assertNotEqual("ready", transition["classification"])
        self.assertEqual("blocked", check(transition, "qa-coverage")["status"])

    def test_the_return_to_development_is_ready_at_ready_for_release(self) -> None:
        transition = self.preflight("release-return-dev", named=["backend"])
        self.assertEqual("ready", transition["classification"], transition["checks"])
        self.assertEqual(("in-dev", "dev"), (transition["target_status"], transition["target_owner"]))
        self.assertEqual("release-done --return in-dev", f"{ACTION_BY_ID['release-return-dev'].command} {ACTION_BY_ID['release-return-dev'].arguments}")

    def test_an_action_of_another_stage_is_not_ready(self) -> None:
        for action in ("reopen-dev", "reopen-spec", "reopen-design"):
            with self.subTest(action=action):
                transition = self.preflight(action)
                self.assertNotEqual("ready", transition["classification"])
                self.assertNotEqual("pass", check(transition, "unsupported-source-stage")["status"])

    def test_the_copy_only_preflight_of_a_variant_that_has_no_copy_surface_is_unsupported(self) -> None:
        for action in ("release-rollback", "release-redeploy"):
            with self.subTest(action=action):
                transition = build_transition_preflight(self.root, "F-001", action=action)["facts"]["transition"]
                self.assertFalse(transition["supported"])
                self.assertEqual("unknown", transition["classification"])

    def test_the_copy_only_preflight_of_the_release_names_the_skill(self) -> None:
        transition = build_transition_preflight(self.root, "F-001", action="release-done")["facts"]["transition"]
        self.assertTrue(transition["supported"])
        self.assertEqual("$release-done F-001", transition["invocations"]["codex"].replace("  ", " "))
        self.assertEqual("/release-done F-001", transition["invocations"]["claude"].replace("  ", " "))

    def test_the_service_answers_the_preflight_and_the_discovery(self) -> None:
        answer = self.service.query(self.agent, "transition-preflight", "F-001", "release-done")
        self.assertEqual("ready", answer["facts"]["transition"]["classification"])
        discovery = self.service.discover(self.agent)
        self.assertIn("release-done", {item["name"] for item in discovery["skills"]})
        for action in ("release-done", "release-return-dev", "release-rollback", "release-redeploy", "reopen-spec", "reopen-design", "reopen-dev"):
            self.assertTrue(ACTION_BY_ID[action].available, action)

    def test_an_unknown_action_is_still_unknown(self) -> None:
        with self.assertRaises(BoardError):
            self.service.query(self.agent, "transition-preflight", "F-001", "release-everything")


class ReleaseGraphTests(ReleaseTests):
    def node(self) -> dict:
        return next(item for item in build_graph(self.root)["facts"]["nodes"] if item["type"] == "feature")

    def offered(self) -> set[str]:
        return {item["action"] for item in self.node()["transitions"]}

    def test_a_feature_ready_for_release_offers_the_release_actions(self) -> None:
        self.assertEqual({"release-done", "release-return-dev"}, {action for action in self.offered() if action.startswith("release")})

    def test_a_released_feature_offers_the_three_reopen_routes_only(self) -> None:
        self.release()
        self.assertEqual({"reopen-spec", "reopen-design", "reopen-dev"}, self.offered())

    def test_a_feature_before_release_offers_no_release_action(self) -> None:
        page = self.with_status("in-dev", "dev", self.release_table([]))
        self.put(FEATURE, page)
        self.assertEqual(set(), {action for action in self.offered() if action.startswith(("release", "reopen"))})


class ReleaseSkillTests(unittest.TestCase):
    def test_the_skill_is_listed_and_reads_the_record_format(self) -> None:
        self.assertIn("release-done", {item["name"] for item in list_skills()})
        skill = get_skill("release-done")
        paths = [item["path"] for item in skill["references"]]
        for expected in ("knowledge/wiki/ACTIONS.md", "knowledge/wiki/releases/_FORMAT.md", "knowledge/wiki/features/_FORMAT.md", "knowledge/wiki/bugs/_FORMAT.md"):
            self.assertIn(expected, paths)
        self.assertIn("release_sequence_invalid", skill["instructions"])
        self.assertEqual(["release-done", "release-return-dev", "release-rollback", "release-redeploy"], skill["actions"])

    def test_the_reopen_skill_names_the_three_routes_from_released(self) -> None:
        skill = get_skill("feature-reopen")
        for route in ("reopen-spec", "reopen-design", "reopen-dev"):
            self.assertIn(route, skill["actions"])
            self.assertIn(route, skill["instructions"])

    def test_the_status_skills_use_the_released_status(self) -> None:
        for name in ("feature-status", "prep-sprint", "wiki-app", "audit-feature"):
            with self.subTest(skill=name):
                text = get_skill(name)["instructions"]
                self.assertIn("released", text)
                self.assertNotIn("status `done`", text)
                self.assertNotIn("`done` feature", text)


if __name__ == "__main__":
    unittest.main()
