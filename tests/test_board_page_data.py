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

from prism_cli.status import build_status
from prism_cli.wiki_lint import lint_wiki
from prism_cli.wiki_graph import action_registry, build_graph
from prism_cli.wiki_model import DESIGN_OWNERS, FEATURE_STATUS_ORDER, status_rank
from prism_cli.wiki_operations import OPERATION_ROW_KEYS, read_board_views
from prism_cli.wiki_transitions import (
    ACTION_SPECS,
    DESIGN_OWNER,
    MINIMUM,
    MODE_AGENT_PROPOSED,
    MODE_HUMAN_DIRECT,
    UNCHANGED,
    build_board_transition_preflight,
)
from tests import real_temp  # noqa: F401
from tests.board_page_fixture import BOTH, TwoAppWorkspace
from tests.browser.harness import EXTRA_FEATURES, build_workspace
from tests.qa_pages import history_entry
from tests.test_lifecycle_model import delivery_row, release_row

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

    def test_a_drop_column_is_set_only_for_a_concrete_target_that_moves_forward(self) -> None:
        metadata = self.by_action()
        for spec in feature_specs():
            entry = metadata[spec.action]
            with self.subTest(action=spec.action):
                if spec.target_status in (MINIMUM, UNCHANGED):
                    # The minimum over the app stages (or no change) depends on the other apps: no column is certain.
                    self.assertIsNone(entry["drop_stage"])
                    self.assertTrue(entry["target_status"], "a recovery view needs the statuses the action may leave the feature in")
                    continue
                forward = status_rank(spec.target_status) > max(status_rank(status) for status in entry["source_status"])
                self.assertEqual(spec.target_status if forward else None, entry["drop_stage"])
        for action in ("dev-done", "qa-verify", "qa-pass", "release-done"):
            with self.subTest(minimum=action):
                self.assertIsNone(metadata[action]["drop_stage"])
        self.assertEqual(["design-start", "dev-start", "po-handoff"], sorted(a for a, e in metadata.items() if e["human_direct"]))
        for action in ("design-start", "dev-start", "po-handoff"):
            with self.subTest(human=action):
                self.assertIsNotNone(metadata[action]["drop_stage"])

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
        self.assertIsNone(metadata["dev-done"]["drop_stage"])
        self.assertEqual(["dev", "qa", "release", "none"], metadata["release-done"]["target_owner"])
        self.assertIsNone(metadata["release-done"]["drop_stage"])
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


class AppStageLayoutTests(unittest.TestCase):
    """An app-stage line never breaks inside an app ID or a stage: the row wraps only between them, and a value wider than the row is cut with an ellipsis."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.html = TEMPLATE.read_text(encoding="utf-8")

    def rule(self, selector: str) -> str:
        found = re.search(rf"(?m)^{re.escape(selector)} \{{([^}}]*)\}}", self.html)
        self.assertIsNotNone(found, f"no rule for {selector}")
        return found.group(1)

    def test_the_row_wraps_between_the_app_and_its_stage_and_never_inside_a_word(self) -> None:
        row = self.rule(".app-stage")
        self.assertIn("flex-wrap: wrap", row)
        self.assertNotIn("overflow-wrap", row, "a break anywhere splits `backend` into `backen` and `d`")
        for selector in (".app-stage .as-name, .app-stage .as-stage",):
            rule = self.rule(selector)
            self.assertIn("white-space: nowrap", rule)
            self.assertIn("text-overflow: ellipsis", rule)
            self.assertIn("max-width: 100%", rule)

    def test_the_card_the_panel_and_the_apps_chip_cut_a_long_value_and_keep_its_full_text_in_a_title(self) -> None:
        start = self.html.index("function appStageHtml(")
        shown = self.html[start : self.html.index("\n}", start)]
        self.assertIn('class="as-name" title="${escapeHtml(row.app)}"', shown)
        self.assertIn('class="as-stage" title="${escapeHtml(row.stage)}"', shown)
        # The card and the panel render the same rows; the Apps view chip carries its own stage label.
        self.assertGreaterEqual(self.html.count("appStageHtml"), 3)
        chip = self.rule(".fchip .req")
        self.assertIn("white-space: nowrap", chip)
        self.assertIn("text-overflow: ellipsis", chip)
        self.assertIn('<span class="req" title="${escapeHtml(stageLabel)}">', self.html)
        # Every label the chip can cut keeps its full text in a title, the requirement status too.
        self.assertIn('title="req: ${escapeHtml(reqStatus)}">req: ${escapeHtml(reqStatus)}</span>', self.html)


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

    def test_a_released_feature_keeps_its_whole_scope_on_every_surface(self) -> None:
        self.seed_released()
        self.retire("worker")
        self.write_status_board()
        both = [{"app": "backend", "stage": "released"}, {"app": "worker", "stage": "released"}]
        graph = build_graph(self.root)
        node = self.feature_node(graph)
        self.assertEqual("released", node["status"])
        self.assertEqual(both, node["app_stages"])
        worker = next(item for item in graph["facts"]["nodes"] if item["id"] == "app:worker")
        self.assertEqual("retired", worker["status"])
        # The status board row, `prism status` and the graph node name the same apps and stages.
        cell = "; ".join(f"{entry['app']}: {entry['stage']}" for entry in node["app_stages"])
        self.assertEqual("backend: released; worker: released", cell)
        board = (self.root / "knowledge" / "wiki" / "status-board.md").read_text(encoding="utf-8")
        row = next(line for line in board.splitlines() if line.startswith("| F-001 "))
        self.assertIn(f"| {cell} |", row)
        self.assertEqual({"F-001": {"backend": "released", "worker": "released"}}, build_status(self.root).feature_app_stages)
        # The retired app's Operations row keeps the release.
        rows = {row["app"]: row for row in graph["facts"]["app_operations"]}
        self.assertEqual("F-001", rows["worker"]["released_features"])
        Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8"))).validate(graph)

    def test_a_feature_before_released_still_excludes_a_retired_app(self) -> None:
        self.seed_in_qa()
        self.retire("worker")
        node = self.feature_node(build_graph(self.root))
        self.assertEqual([{"app": "backend", "stage": "in-qa"}], node["app_stages"])
        self.assertEqual({"F-001": {"backend": "in-qa"}}, build_status(self.root).feature_app_stages)

    def test_an_app_with_only_a_standalone_bug_or_incident_is_in_the_graph_with_its_facts(self) -> None:
        self.add_standalone_bug("backend")
        self.add_open_incident("worker")
        self.write_status_board()
        graph = build_graph(self.root)
        self.assertEqual([], [node for node in graph["facts"]["nodes"] if node["type"] == "feature"])
        self.assertEqual({"app:backend", "app:worker"}, {node["id"] for node in graph["facts"]["nodes"] if node["type"] == "app"})
        self.assertEqual([], [edge for edge in graph["facts"]["edges"] if edge["kind"] == "targets"])
        rows = {row["app"]: row for row in graph["facts"]["app_operations"]}
        self.assertEqual({"backend", "worker"}, set(rows))
        self.assertEqual("BUG-002", rows["backend"]["open_bugs"])
        self.assertEqual("INC-001", rows["worker"]["open_incidents"])
        board = read_board_views((self.root / "knowledge" / "wiki" / "status-board.md").read_text(encoding="utf-8"))
        self.assertEqual(board.operations, rows)
        self.assertEqual(len(graph["facts"]["nodes"]), graph["facts"]["node_count"])
        Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8"))).validate(graph)

    def test_an_app_with_no_feature_and_no_operations_row_stays_out_of_the_graph(self) -> None:
        self.add_standalone_bug("backend")
        graph = build_graph(self.root)
        self.assertEqual({"app:backend"}, {node["id"] for node in graph["facts"]["nodes"] if node["type"] == "app"})
        self.assertEqual(["backend"], [row["app"] for row in graph["facts"]["app_operations"]])

    def test_a_feature_in_qa_offers_its_return_requests(self) -> None:
        self.seed_in_qa()
        node = self.feature_node(build_graph(self.root))
        self.assertEqual("in-qa", node["status"])
        records = {record["action"]: record for record in node["transitions"]}
        for action, target in (("qa-return-spec", "specified"), ("qa-return-design", "in-design")):
            with self.subTest(action=action):
                self.assertIn(action, records)
                record = records[action]
                self.assertEqual((target, "ready", True), (record["target_status"], record["classification"], record["supported"]))
                self.assertEqual({"codex": f"$feature-reopen F-001 {target}", "claude": f"/feature-reopen F-001 {target}"}, record["invocations"])
        # The transition the card shows first does not change.
        self.assertEqual(["qa-verify", "qa-pass", "qa-fail", "qa-return-spec", "qa-return-design"], list(records))

    def test_a_feature_in_development_without_an_app_in_qa_does_not_offer_the_qa_returns(self) -> None:
        self.seed("in-dev", "dev", self.page("in-dev", "dev", BOTH, self.criteria()))
        node = self.feature_node(build_graph(self.root))
        self.assertEqual([{"app": "backend", "stage": "in-dev"}, {"app": "worker", "stage": "in-dev"}], node["app_stages"])
        offered = {record["action"] for record in node["transitions"]}
        self.assertTrue({"dev-return-spec", "dev-return-design"} <= offered)
        self.assertFalse({"qa-return-spec", "qa-return-design"} & offered)


class ReleasedScopeLintTests(TwoAppWorkspace):
    """Lint judges a released feature over the scope the status board, the graph and `prism status` show."""

    def errors(self) -> dict[str, str]:
        """The error codes of F-001, without the requirement pages these fixtures leave out."""

        return {
            item.code: item.message
            for item in lint_wiki(self.root).diagnostics
            if item.severity == "error" and item.feature_id in {None, "F-001"} and item.code != "done-app-requirement"
        }

    def seed_released_without_worker_release(self) -> None:
        """F-001 is `released` and `worker` has delivery and QA evidence but no Release row."""

        page = self.page(
            "released",
            "none",
            BOTH,
            self.criteria(),
            delivery=[delivery_row(app) for app in BOTH],
            qa=self.covering_qa(),
            release=[release_row("backend", "released")],
        )
        self.seed("released", "none", page)

    def test_a_released_feature_with_an_app_retired_after_its_release_stays_clean(self) -> None:
        self.seed_released()
        self.retire("worker")
        self.write_status_board()
        self.assertEqual({}, self.errors())

    def test_a_released_feature_needs_release_evidence_for_an_app_retired_after_the_release(self) -> None:
        self.seed_released_without_worker_release()
        self.retire("worker")
        self.write_status_board()
        errors = self.errors()
        self.assertIn("feature-status-not-minimum", errors)
        self.assertIn("lowest app stage is `in-qa`", errors["feature-status-not-minimum"])
        self.assertIn("worker: in-qa", errors["feature-status-not-minimum"])
        self.assertIn("app-row-missing", errors)
        # `prism status` shows the stages lint judges.
        self.assertEqual({"F-001": {"backend": "released", "worker": "in-qa"}}, build_status(self.root).feature_app_stages)

    def test_an_app_retired_before_any_evidence_leaves_the_released_scope_on_every_surface(self) -> None:
        page = self.page(
            "released",
            "none",
            BOTH,
            self.criteria(),
            delivery=[delivery_row("backend")],
            qa=self.covering_qa()[:1],
            release=[release_row("backend", "released")],
        )
        self.seed("released", "none", page)
        self.retire("worker")
        self.write_status_board()
        self.assertEqual({}, self.errors())
        graph = build_graph(self.root)
        node = next(item for item in graph["facts"]["nodes"] if item["id"] == "F-001")
        self.assertEqual([{"app": "backend", "stage": "released"}], node["app_stages"])
        self.assertEqual({"F-001": {"backend": "released"}}, build_status(self.root).feature_app_stages)
        board = (self.root / "knowledge" / "wiki" / "status-board.md").read_text(encoding="utf-8")
        row = next(line for line in board.splitlines() if line.startswith("| F-001 "))
        self.assertIn("| backend: released |", row)
        self.assertNotIn("worker:", row)

    def test_an_app_retired_after_its_rows_moved_into_the_evidence_history_stays_in_the_scope(self) -> None:
        # No release record names `worker`; the Evidence history that archived its rows is the evidence that it took part.
        archived = [
            ("Delivery evidence", delivery_row("worker")),
            ("QA verification", self.covering_qa()[1]),
            ("Release", release_row("worker", "released")),
        ]
        page = self.page(
            "released",
            "none",
            BOTH,
            self.criteria(),
            delivery=[delivery_row("backend")],
            qa=self.covering_qa()[:1],
            release=[release_row("backend", "released")],
            history=history_entry("dev-return-design", affected="worker", archived=archived),
        )
        self.seed("released", "none", page)
        self.retire("worker")
        self.write_status_board()
        errors = self.errors()
        self.assertIn("feature-status-not-minimum", errors)
        self.assertIn("app-row-missing", errors)
        self.assertEqual({"F-001": {"backend": "released", "worker": "in-dev"}}, build_status(self.root).feature_app_stages)
        node = next(item for item in build_graph(self.root)["facts"]["nodes"] if item["id"] == "F-001")
        self.assertEqual([{"app": "backend", "stage": "released"}, {"app": "worker", "stage": "in-dev"}], node["app_stages"])

    def test_the_same_gap_in_a_released_feature_is_reported_while_the_app_is_active(self) -> None:
        self.seed_released_without_worker_release()
        self.write_status_board()
        self.assertIn("feature-status-not-minimum", self.errors())

    def test_a_feature_that_is_not_released_keeps_the_active_scope_rule(self) -> None:
        # `worker` has no evidence and is retired: the lowest stage over the whole scope would be `in-dev`, over the active apps it is `in-qa`.
        page = self.page("in-qa", "qa", BOTH, self.criteria(), delivery=[delivery_row("backend")], qa=self.covering_qa()[:1])
        self.seed("in-qa", "qa", page)
        self.retire("worker")
        self.write_status_board()
        errors = self.errors()
        self.assertNotIn("feature-status-not-minimum", errors)
        self.assertNotIn("app-row-missing", errors)
        self.assertEqual({"F-001": {"backend": "in-qa"}}, build_status(self.root).feature_app_stages)


class QaReturnPreflightTests(TwoAppWorkspace):
    """`qa-return-spec` and `qa-return-design` are ready only where the board service accepts the route on eligibility."""

    ACTIONS = ("qa-return-spec", "qa-return-design")

    def transition(self, action: str) -> dict:
        return build_board_transition_preflight(self.root, "F-001", action)

    def offered(self) -> dict[str, dict]:
        node = next(item for item in build_graph(self.root)["facts"]["nodes"] if item["id"] == "F-001")
        return {record["action"]: record for record in node["transitions"]}

    def test_a_partial_release_blocks_both_returns_with_the_servers_reason(self) -> None:
        self.seed_released_and_in_qa()
        self.write_status_board()
        offered = self.offered()
        for action in self.ACTIONS:
            with self.subTest(action=action):
                transition = self.transition(action)
                self.assertEqual("blocked", transition["classification"])
                blocked = [check for check in transition["checks"] if check["status"] == "blocked"]
                self.assertEqual(["partial-release-requires-new-feature"], [check["code"] for check in blocked])
                self.assertIn("has released app(s) `backend`", blocked[0]["message"])
                self.assertIn("this feature cannot go back to specification or design", blocked[0]["message"])
                # The card carries the request as blocked, which the page does not open.
                self.assertEqual("blocked", offered[action]["classification"])

    def test_a_feature_with_every_app_in_development_blocks_both_returns(self) -> None:
        self.seed("in-dev", "dev", self.page("in-dev", "dev", BOTH, self.criteria()))
        for action in self.ACTIONS:
            with self.subTest(action=action):
                transition = self.transition(action)
                self.assertEqual("blocked", transition["classification"])
                blocked = [check for check in transition["checks"] if check["status"] == "blocked"]
                self.assertEqual(["app-stage-mismatch"], [check["code"] for check in blocked])
                self.assertIn(f"no app has reached QA, so it returns with dev-return-* rather than {action}", blocked[0]["message"])

    def test_an_app_in_qa_and_none_released_leaves_both_returns_ready(self) -> None:
        self.seed_in_qa()
        self.write_status_board()
        offered = self.offered()
        for action in self.ACTIONS:
            with self.subTest(action=action):
                transition = self.transition(action)
                self.assertEqual(("ready", True), (transition["classification"], transition["supported"]))
                self.assertEqual("ready", offered[action]["classification"])

    def test_a_feature_in_development_with_an_app_in_qa_leaves_both_returns_ready(self) -> None:
        self.seed_in_dev()
        for action in self.ACTIONS:
            with self.subTest(action=action):
                self.assertEqual("ready", self.transition(action)["classification"])


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
