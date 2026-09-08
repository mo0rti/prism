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
from prism_cli.wiki_query import wiki_blockers, wiki_owner, wiki_platform, wiki_search, wiki_show


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

        queries = {
            "show": wiki_show(root, "F-001"),
            "blockers": wiki_blockers(root),
            "owner": wiki_owner(root, "po"),
            "platform": wiki_platform(root, "backend"),
            "search": wiki_search(root, "checkout"),
        }
        for name, envelope in queries.items():
            with self.subTest(command=name):
                Draft202012Validator(query_schema).validate(envelope)

        Draft202012Validator(graph_schema).validate(build_graph(root))
        Draft202012Validator(lint_schema).validate(lint_wiki(root).to_dict())
        Draft202012Validator(status_schema).validate(build_status(root).to_dict())

    def test_common_envelope_schema_rejects_wrong_version(self) -> None:
        envelope = wiki_show(FIXTURE_ROOT, "F-001")
        envelope["schema_version"] = 2

        with self.assertRaises(ValidationError):
            Draft202012Validator(self.load_schema("envelope-v1.json")).validate(envelope)

    def test_lint_envelope_includes_workspace_identity_and_matches_common_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            wiki_root = workspace / "knowledge" / "wiki"
            wiki_root.parent.mkdir(parents=True)
            shutil.copytree(FIXTURE_ROOT / "knowledge" / "wiki", wiki_root)
            (workspace / "prism.workspace.yml").write_text(
                "schema_version: 1\nproject:\n  name: Lint workspace\n  platforms: [backend]\n",
                encoding="utf-8",
            )

            envelope = lint_wiki(workspace).to_dict()

        Draft202012Validator(self.load_schema("envelope-v1.json")).validate(envelope)
        self.assertEqual(
            {
                "kind": "generated-project",
                "project_name": "Lint workspace",
                "platforms": ["backend"],
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
                    "wiki-platform",
                    "wiki-query",
                    "wiki-show",
                    "feature-status",
                    "prep-sprint",
                }
            ),
            REPO_ROOT / "template" / ".claude" / "commands" / "feature-status.md.jinja",
            REPO_ROOT / "template" / ".claude" / "commands" / "prep-sprint.md.jinja",
            REPO_ROOT / "template" / ".cursor" / "rules" / "wiki.mdc.jinja",
        ]
        for path in prompt_paths:
            with self.subTest(prompt=path.as_posix()):
                text = path.read_text(encoding="utf-8")
                self.assertIn("prism-kit>=0.2.0", text)
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
                "schema_version: 1\nproject:\n  name: Manifest name\n  platforms: [backend, mobile-ios]\n",
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
        self.assertEqual(["backend", "mobile-ios"], envelope["workspace"]["platforms"])
        self.assertIn("manifest-answers-drift", codes)
        self.assertIn("manifest-filesystem-drift", codes)
        self.assertEqual("error", envelope["confidence"])

    def test_query_envelope_uses_answers_and_filesystem_identity_without_manifest(self) -> None:
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

        self.assertEqual("Answers name", envelope["workspace"]["project_name"])
        self.assertEqual(["mobile-ios"], envelope["workspace"]["platforms"])
        self.assertIn("missing-workspace-manifest", {diagnostic["code"] for diagnostic in envelope["diagnostics"]})


if __name__ == "__main__":
    unittest.main()
