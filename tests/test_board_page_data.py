"""The data the board page renders: per-app stages, design tracks, the Operations facts and the action rules.

The page reads its action rules from `facts.action_registry`, which the server generates from the transition registry, and
its Operations facts from `facts.app_operations`, which come from the code that writes and lints the status board.
"""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from prism_cli.wiki_graph import action_registry, build_graph
from prism_cli.wiki_model import DESIGN_OWNERS, FEATURE_STATUS_ORDER, status_rank
from prism_cli.wiki_operations import OPERATION_ROW_KEYS, read_board_views
from prism_cli.wiki_transitions import ACTION_SPECS, DESIGN_OWNER, MINIMUM, MODE_AGENT_PROPOSED, MODE_HUMAN_DIRECT, UNCHANGED
from tests import real_temp  # noqa: F401
from tests.board_page_fixture import TwoAppWorkspace
from tests.browser.harness import EXTRA_FEATURES, build_workspace

REPOSITORY = Path(__file__).resolve().parents[1]
TEMPLATE = REPOSITORY / "prism_cli" / "assets" / "graph_template.html"
SCHEMA = REPOSITORY / "prism_cli" / "schemas" / "wiki-graph-v1.json"
# The tables the page used to keep by hand; the registry is the only source of action rules now.
REMOVED_TABLES = (
    "ACTION_CONTRACTS",
    "ACTION_DROP_STAGE",
    "CONNECTED_HUMAN_ACTIONS",
    "CONNECTED_AGENT_ACTIONS",
    "CONNECTED_AGENT_SKILLS",
    "CONNECTED_ACTION_BY_STAGE",
    "ACTION_COMMANDS",
    "ACTION_ARGUMENTS",
)
RETURN_ACTIONS = ("dev-return-spec", "dev-return-design", "qa-return-spec", "qa-return-design")


def feature_specs() -> list:
    return [spec for spec in ACTION_SPECS if spec.subject == "feature" and spec.available]


class ActionRegistryTests(unittest.TestCase):
    def by_action(self) -> dict[str, dict]:
        return {entry["action"]: entry for entry in action_registry()}

    def test_the_metadata_equals_the_registry_for_every_feature_action(self) -> None:
        metadata = self.by_action()
        self.assertEqual([spec.action for spec in feature_specs()], [entry["action"] for entry in action_registry()])
        for spec in feature_specs():
            entry = metadata[spec.action]
            with self.subTest(action=spec.action):
                self.assertEqual(spec.command, entry["skill"])
                self.assertEqual(spec.arguments, entry["arguments"])
                self.assertEqual(MODE_HUMAN_DIRECT in spec.modes, entry["human_direct"])
                self.assertEqual(MODE_AGENT_PROPOSED in spec.modes, entry["agent_proposal"])
                sources = {pair for owner in DESIGN_OWNERS for pair in spec.resolved_sources(owner)}
                self.assertEqual({status for status, _owner in sources}, set(entry["source_status"]))
                self.assertEqual({owner for _status, owner in sources}, set(entry["source_owner"]))
                if spec.target_status not in (MINIMUM, UNCHANGED):
                    self.assertEqual([spec.target_status], entry["target_status"])
                    owners = list(DESIGN_OWNERS) if spec.target_owner == DESIGN_OWNER else [spec.target_owner]
                    self.assertEqual(owners, entry["target_owner"])
                for status in entry["source_status"] + entry["target_status"]:
                    self.assertIn(status, FEATURE_STATUS_ORDER)
                drop = entry["drop_stage"]
                if drop is not None:
                    self.assertGreater(status_rank(drop), max(status_rank(status) for status in entry["source_status"]))

    def test_known_actions_carry_the_values_the_registry_declares(self) -> None:
        metadata = self.by_action()
        self.assertEqual(
            {
                "action": "dev-return-spec",
                "skill": "feature-reopen",
                "arguments": "specified",
                "human_direct": False,
                "agent_proposal": True,
                "source_status": ["ready-for-dev", "in-dev"],
                "source_owner": ["dev"],
                "target_status": ["specified"],
                "target_owner": ["po"],
                "drop_stage": None,
            },
            metadata["dev-return-spec"],
        )
        self.assertEqual(["in-dev", "ready-for-qa"], metadata["dev-done"]["target_status"])
        self.assertEqual("ready-for-qa", metadata["dev-done"]["drop_stage"])
        self.assertEqual(["dev", "qa", "release", "none"], metadata["release-done"]["target_owner"])
        self.assertEqual("released", metadata["release-done"]["drop_stage"])
        self.assertEqual(["designer", "tech-lead"], metadata["po-handoff"]["target_owner"])
        self.assertEqual("ready-for-design", metadata["po-handoff"]["drop_stage"])
        self.assertEqual("release-done", metadata["release-return-dev"]["skill"])
        self.assertEqual("--return in-dev", metadata["release-return-dev"]["arguments"])
        human = sorted(action for action, entry in metadata.items() if entry["human_direct"])
        self.assertEqual(["design-start", "dev-start", "po-handoff"], human)

    def test_the_return_actions_are_in_the_metadata_as_agent_proposals(self) -> None:
        metadata = self.by_action()
        for action in RETURN_ACTIONS:
            with self.subTest(action=action):
                self.assertIn(action, metadata)
                self.assertTrue(metadata[action]["agent_proposal"])
                self.assertFalse(metadata[action]["human_direct"])
                self.assertEqual("feature-reopen", metadata[action]["skill"])

    def test_the_template_keeps_no_hand_written_action_table(self) -> None:
        text = TEMPLATE.read_text(encoding="utf-8")
        for name in REMOVED_TABLES:
            with self.subTest(name=name):
                self.assertIsNone(re.search(rf"\b{name}\b", text), f"{name} is still in the page; the page reads facts.action_registry")
        self.assertIn("facts.action_registry", text)


class BoardPageEnvelopeTests(TwoAppWorkspace):
    def feature_node(self, graph: dict, feature_id: str = "F-001") -> dict:
        return next(node for node in graph["facts"]["nodes"] if node["id"] == feature_id)

    def test_the_envelope_carries_the_action_registry_and_validates(self) -> None:
        self.seed_released_and_in_qa()
        graph = build_graph(self.root)
        self.assertEqual(json.loads(json.dumps(action_registry())), graph["facts"]["action_registry"])
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        Draft202012Validator(schema).validate(graph)

    def test_a_feature_with_one_app_released_and_one_in_qa_shows_both_stages(self) -> None:
        self.seed_released_and_in_qa()
        node = self.feature_node(build_graph(self.root))
        self.assertEqual("in-qa", node["status"])
        self.assertEqual([{"app": "backend", "stage": "released"}, {"app": "worker", "stage": "in-qa"}], node["app_stages"])

    def test_an_app_that_is_retired_is_not_given_a_stage(self) -> None:
        self.seed_released_and_in_qa()
        import yaml

        manifest_path = self.root / "prism.workspace.yml"
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        for app in manifest["apps"]:
            if app["id"] == "worker":
                app["status"] = "retired"
        manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
        graph = build_graph(self.root)
        self.assertEqual([{"app": "backend", "stage": "released"}], self.feature_node(graph)["app_stages"])
        worker = next(node for node in graph["facts"]["nodes"] if node["id"] == "app:worker")
        self.assertEqual("retired", worker["status"])
        self.assertIn({"source": "F-001", "target": "app:worker", "kind": "targets", "evidence": "frontmatter-apps"}, graph["facts"]["edges"])

    def test_the_operations_facts_equal_the_status_board_rows(self) -> None:
        self.seed_released_and_in_qa()
        self.add_open_bug()
        self.write_status_board()
        graph = build_graph(self.root)
        rows = {row["app"]: row for row in graph["facts"]["app_operations"]}
        board = read_board_views((self.root / "knowledge" / "wiki" / "status-board.md").read_text(encoding="utf-8"))
        self.assertEqual({"backend", "worker"}, set(rows))
        self.assertEqual(board.operations, rows)
        for row in rows.values():
            self.assertEqual(set(OPERATION_ROW_KEYS), set(row))
        self.assertEqual("F-001", rows["backend"]["released_features"])
        self.assertEqual("BUG-001", rows["worker"]["open_bugs"])
        self.assertEqual("—", rows["worker"]["released_features"])

    def test_an_app_with_nothing_to_show_has_no_operations_row(self) -> None:
        self.seed_in_dev()
        self.write_status_board()
        graph = build_graph(self.root)
        self.assertEqual([], graph["facts"]["app_operations"])
        board = read_board_views((self.root / "knowledge" / "wiki" / "status-board.md").read_text(encoding="utf-8"))
        self.assertEqual({}, board.operations)

    def test_a_feature_in_development_offers_the_return_actions_the_registry_lists(self) -> None:
        self.seed_in_dev()
        graph = build_graph(self.root)
        node = self.feature_node(graph)
        self.assertEqual("in-dev", node["status"])
        self.assertEqual([{"app": "backend", "stage": "ready-for-qa"}, {"app": "worker", "stage": "in-dev"}], node["app_stages"])
        offered = {record["action"] for record in node["transitions"]}
        registry = {entry["action"] for entry in graph["facts"]["action_registry"]}
        self.assertTrue({"dev-return-spec", "dev-return-design"} <= offered)
        self.assertTrue(offered <= registry, offered - registry)


class DesignTracksEnvelopeTests(unittest.TestCase):
    def test_a_feature_in_design_carries_its_tracks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = build_workspace(Path(temporary) / "document-review", (EXTRA_FEATURES["in-design"],))
            graph = build_graph(root)
        nodes = {node["id"]: node for node in graph["facts"]["nodes"]}
        self.assertEqual({"ui": "not-applicable", "technical": "done"}, nodes["F-007"]["design_tracks"])
        # A feature before design has no tracks, and a feature with app stages starts at in-dev.
        self.assertNotIn("design_tracks", nodes["F-001"])
        self.assertNotIn("app_stages", nodes["F-007"])
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        Draft202012Validator(schema).validate(graph)


if __name__ == "__main__":
    unittest.main()
