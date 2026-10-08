import json
import shutil
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

from prism_cli.status import build_status
from prism_cli.wiki_graph import build_graph
from prism_cli.wiki_graph_html import render_html
from prism_cli.wiki_lint import lint_wiki
from prism_cli.wiki_query import wiki_blockers, wiki_owner, wiki_app, wiki_search, wiki_show
from prism_cli.wiki_transitions import build_transition_preflight
from tests.manifest_fixtures import manifest_text
from tests import real_temp  # noqa: F401


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = REPO_ROOT / "prism_cli" / "schemas"
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "wiki_contract" / "healthy"


class JsonContractTests(unittest.TestCase):
    @staticmethod
    def load_schema(name: str) -> dict:
        with (SCHEMA_ROOT / name).open(encoding="utf-8") as stream:
            return json.load(stream)

    def test_packaged_schema_documents_are_valid_json_schema_documents(self) -> None:
        schema_paths = sorted(SCHEMA_ROOT.glob("*.json"))
        self.assertGreaterEqual(len(schema_paths), 5)
        for path in schema_paths:
            with self.subTest(schema=path.name):
                schema = self.load_schema(path.name)
                Draft202012Validator.check_schema(schema)

    def test_read_surface_envelopes_validate_against_versioned_schemas(self) -> None:
        root = FIXTURE_ROOT
        query_schema = self.load_schema("wiki-query-v1.json")
        graph_schema = self.load_schema("wiki-graph-v1.json")
        lint_schema = self.load_schema("wiki-lint-v1.json")
        status_schema = self.load_schema("status-v1.json")
        transition_schema = self.load_schema("wiki-transition-preflight-v1.json")

        queries = {
            "show": wiki_show(root, "F-001"),
            "blockers": wiki_blockers(root),
            "owner": wiki_owner(root, "po"),
            "app": wiki_app(root, "backend"),
            "search": wiki_search(root, "checkout"),
        }
        for name, envelope in queries.items():
            with self.subTest(command=name):
                Draft202012Validator(query_schema).validate(envelope)

        Draft202012Validator(graph_schema).validate(build_graph(root))
        Draft202012Validator(lint_schema).validate(lint_wiki(root).to_dict())
        Draft202012Validator(status_schema).validate(build_status(root).to_dict())
        Draft202012Validator(transition_schema).validate(build_transition_preflight(root, "F-001"))

    def test_common_envelope_schema_rejects_wrong_version(self) -> None:
        envelope = wiki_show(FIXTURE_ROOT, "F-001")
        envelope["schema_version"] = 2

        with self.assertRaises(ValidationError):
            Draft202012Validator(self.load_schema("envelope-v1.json")).validate(envelope)

    def test_transition_schemas_document_support_and_snapshot_observation(self) -> None:
        expected_supported = "true does not mean the feature is ready or approved"
        expected_observed = "unchanged snapshots may reuse this timestamp across reads"
        for name in ("wiki-graph-v1.json", "wiki-transition-preflight-v1.json"):
            with self.subTest(schema=name):
                definitions = self.load_schema(name)["$defs"]
                self.assertIn(expected_supported, definitions["transition"]["properties"]["supported"]["description"])
                self.assertIn(expected_observed, definitions["transition_snapshot"]["properties"]["observed_at"]["description"])

    def test_lifecycle_transition_schema_exposes_v3_actions_and_graph_routes(self) -> None:
        graph = build_graph(FIXTURE_ROOT)
        capability = graph["facts"]["transition_capability"]
        self.assertEqual(3, capability["version"])
        self.assertEqual(
            {
                "po-specify",
                "po-handoff",
                "design-start",
                "design-ui-done",
                "tech-design-done",
                "design-handoff",
                "dev-start",
                "dev-done",
                "dev-return-spec",
                "dev-return-design",
                "qa-verify",
                "qa-pass",
                "qa-fail",
            },
            {surface["action"] for surface in capability["surfaces"]},
        )
        feature = next(node for node in graph["facts"]["nodes"] if node["type"] == "feature")
        self.assertNotIn("transition", feature)
        po_handoff = next(record for record in feature["transitions"] if record["action"] == "po-handoff")
        self.assertEqual("tech-lead", po_handoff["target_owner"])
        Draft202012Validator(self.load_schema("wiki-graph-v1.json")).validate(graph)

    def test_graph_schema_covers_released_and_unmapped_feature_routes(self) -> None:
        graph_schema = self.load_schema("wiki-graph-v1.json")
        partial_root = FIXTURE_ROOT.parent / "partial"
        partial_graph = build_graph(partial_root)
        Draft202012Validator(graph_schema).validate(partial_graph)

        released_node = next(
            node
            for node in partial_graph["facts"]["nodes"]
            if node["type"] == "feature" and node["id"] == "F-005"
        )
        self.assertNotIn("transition", released_node)
        # The reopen routes of a released feature belong to a later work package, so the node offers none.
        self.assertEqual([], released_node["transitions"])

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            wiki_root = workspace / "knowledge" / "wiki"
            wiki_root.parent.mkdir(parents=True)
            shutil.copytree(FIXTURE_ROOT / "knowledge" / "wiki", wiki_root)
            shutil.copyfile(FIXTURE_ROOT / "prism.workspace.yml", wiki_root.parents[1] / "prism.workspace.yml")
            feature_path = wiki_root / "features" / "F-001-checkout.md"
            feature_path.write_text(
                feature_path.read_text(encoding="utf-8")
                .replace("status: specified", "status: future-stage")
                .replace("owner: po", "owner: future-owner"),
                encoding="utf-8",
            )
            unmapped_graph = build_graph(workspace)
            unmapped_preflight = build_transition_preflight(workspace, "F-001")

        Draft202012Validator(graph_schema).validate(unmapped_graph)
        unmapped_node = next(
            node
            for node in unmapped_graph["facts"]["nodes"]
            if node["type"] == "feature" and node["id"] == "F-001"
        )
        self.assertNotIn("transition", unmapped_node)
        self.assertEqual([], unmapped_node["transitions"])
        unmapped_transition = unmapped_preflight["facts"]["transition"]
        self.assertEqual("future-stage", unmapped_transition["source_status"])
        self.assertEqual("future-owner", unmapped_transition["source_owner"])
        self.assertEqual("unknown", unmapped_transition["classification"])
        self.assertIsNone(unmapped_transition["target_status"])
        self.assertIsNone(unmapped_transition["target_owner"])
        self.assertIsNone(unmapped_transition["action"])

    def test_transition_schema_retains_unknown_status_values_for_malformed_pages(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            wiki_root = workspace / "knowledge" / "wiki"
            wiki_root.parent.mkdir(parents=True)
            shutil.copytree(FIXTURE_ROOT / "knowledge" / "wiki", wiki_root)
            shutil.copyfile(FIXTURE_ROOT / "prism.workspace.yml", wiki_root.parents[1] / "prism.workspace.yml")
            feature_path = wiki_root / "features" / "F-001-checkout.md"
            feature_path.write_text(
                feature_path.read_text(encoding="utf-8").replace("status: specified", "status: future-stage"),
                encoding="utf-8",
            )
            envelope = build_transition_preflight(workspace, "F-001")

        Draft202012Validator(self.load_schema("wiki-transition-preflight-v1.json")).validate(envelope)
        self.assertEqual("future-stage", envelope["facts"]["transition"]["source_status"])
        self.assertEqual("unknown", envelope["facts"]["transition"]["classification"])

    def test_transition_schema_retains_an_unsupported_requested_action(self) -> None:
        envelope = build_transition_preflight(FIXTURE_ROOT, "F-001", action="future-action")

        Draft202012Validator(self.load_schema("wiki-transition-preflight-v1.json")).validate(envelope)
        self.assertEqual("future-action", envelope["facts"]["requested_action"])
        self.assertEqual("unknown", envelope["facts"]["transition"]["classification"])

    def test_lint_envelope_includes_workspace_identity_and_matches_common_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            wiki_root = workspace / "knowledge" / "wiki"
            wiki_root.parent.mkdir(parents=True)
            shutil.copytree(FIXTURE_ROOT / "knowledge" / "wiki", wiki_root)
            shutil.copyfile(FIXTURE_ROOT / "prism.workspace.yml", wiki_root.parents[1] / "prism.workspace.yml")
            (workspace / "prism.workspace.yml").write_text(
                manifest_text("Lint workspace", ["backend"]),
                encoding="utf-8",
            )

            envelope = lint_wiki(workspace).to_dict()

        Draft202012Validator(self.load_schema("envelope-v1.json")).validate(envelope)
        self.assertEqual(
            {
                "kind": "generated-project",
                "project_name": "Lint workspace",
                "apps": [
                    {
                        "id": "backend",
                        "name": "Spring Boot Backend",
                        "stack": "spring-backend",
                        "repository": "workspace",
                        "path": "backend",
                        "audience": None,
                        "status": "active",
                        "capabilities": {"has-ui": False, "serves-api": True},
                        "maturity": None,
                    }
                ],
            },
            envelope["workspace"],
        )

    def test_generated_read_surfaces_pin_compatible_cli_and_keep_fallback(self) -> None:
        prompt_paths = [
            *sorted((REPO_ROOT / "template" / ".claude" / "commands").glob("wiki-*.md.jinja")),
            REPO_ROOT / "template" / ".claude" / "commands" / "lint-wiki.md.jinja",
            *sorted(
                path
                for path in (REPO_ROOT / "template" / ".agents" / "skills").glob("*/SKILL.md.jinja")
                if path.parent.name in {
                    "lint-wiki",
                    "wiki-blockers",
                    "wiki-owner",
                    "wiki-app",
                    "wiki-query",
                    "wiki-show",
                    "feature-status",
                    "prep-sprint",
                }
            ),
            REPO_ROOT / "template" / ".claude" / "commands" / "feature-status.md.jinja",
            REPO_ROOT / "template" / ".claude" / "commands" / "prep-sprint.md.jinja",
            REPO_ROOT / "template" / "AGENTS.md.jinja",
        ]
        for path in prompt_paths:
            with self.subTest(prompt=path.as_posix()):
                text = path.read_text(encoding="utf-8")
                self.assertIn("prism-kit>=0.6.0", text)
                self.assertIn("prism --version", text)
                self.assertIn('"schema_version": 1', text)
                self.assertIn("Fallback path", text)
                self.assertIn("read-only", text)

    def test_feature_status_and_prep_sprint_share_cli_status_facts(self) -> None:
        paths = [
            REPO_ROOT / "template" / ".claude" / "commands" / "feature-status.md.jinja",
            REPO_ROOT / "template" / ".claude" / "commands" / "prep-sprint.md.jinja",
            REPO_ROOT / "template" / ".agents" / "skills" / "feature-status" / "SKILL.md.jinja",
            REPO_ROOT / "template" / ".agents" / "skills" / "prep-sprint" / "SKILL.md.jinja",
        ]
        for path in paths:
            with self.subTest(prompt=path.as_posix()):
                text = path.read_text(encoding="utf-8")
                self.assertIn("prism status --json", text)
                self.assertIn("do not recompute", text)
                self.assertIn("returned diagnostics", text)

    def test_graph_and_query_share_the_common_envelope_shape(self) -> None:
        common_schema = self.load_schema("envelope-v1.json")
        for command, envelope in (
            ("query", wiki_show(FIXTURE_ROOT, "F-001")),
            ("graph", build_graph(FIXTURE_ROOT)),
            ("transition", build_transition_preflight(FIXTURE_ROOT, "F-001")),
        ):
            with self.subTest(command=command):
                Draft202012Validator(common_schema).validate(envelope)

    def test_html_data_literal_placeholder_is_not_substituted(self) -> None:
        envelope = wiki_show(FIXTURE_ROOT, "F-001")
        envelope["facts"]["literal"] = "/*__PRISM_CONFIG__*/"

        html = render_html(envelope, generated_at="2026-09-08T00:00:00+02:00")

        self.assertIn('"literal": "/*__PRISM_CONFIG__*/"', html)

    def test_query_envelope_includes_workspace_drift_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            wiki_root = workspace / "knowledge" / "wiki"
            wiki_root.parent.mkdir(parents=True)
            shutil.copytree(FIXTURE_ROOT / "knowledge" / "wiki", wiki_root)
            (workspace / "prism.workspace.yml").write_text(
                manifest_text("Manifest name", ["backend", "mobile-ios"]),
                encoding="utf-8",
            )
            (workspace / ".copier-answers.yml").write_text(
                "_src_path: template\nproject_name: Answers name\nplatforms: [backend]\n",
                encoding="utf-8",
            )
            (workspace / "backend").mkdir()

            envelope = wiki_show(workspace, "F-001")

        codes = {diagnostic["code"] for diagnostic in envelope["diagnostics"]}
        self.assertEqual("Manifest name", envelope["workspace"]["project_name"])
        self.assertEqual(["backend", "mobile-ios"], [app["id"] for app in envelope["workspace"]["apps"]])
        self.assertIn("manifest-answers-drift", codes)
        self.assertIn("manifest-filesystem-drift", codes)
        self.assertEqual("error", envelope["confidence"])

    def test_query_envelope_without_a_manifest_has_no_identity_and_no_apps(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            wiki_root = workspace / "knowledge" / "wiki"
            wiki_root.parent.mkdir(parents=True)
            shutil.copytree(FIXTURE_ROOT / "knowledge" / "wiki", wiki_root)
            (workspace / ".copier-answers.yml").write_text(
                "_src_path: template\nproject_name: Answers name\nplatforms: [mobile-ios]\n",
                encoding="utf-8",
            )
            (workspace / "mobile-ios").mkdir()

            envelope = wiki_show(workspace, "F-001")

        self.assertIsNone(envelope["workspace"]["project_name"])
        self.assertEqual([], envelope["workspace"]["apps"])
        self.assertIn("missing-workspace-manifest", {diagnostic["code"] for diagnostic in envelope["diagnostics"]})


if __name__ == "__main__":
    unittest.main()
