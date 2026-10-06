import json
import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path

from prism_cli.wiki_lint import WIKI_BLOCKER_CODES, lint_wiki
from prism_cli.wiki_graph import build_graph, render_mermaid
from prism_cli.wiki_model import read_wiki_settings
from tests import real_temp  # noqa: F401


FIXTURES = Path(__file__).parent / "fixtures" / "wiki_contract"
CHECK_DATE = date(2026, 9, 8)


class WikiContractLintTests(unittest.TestCase):
    def lint_fixture(self, name: str):
        return lint_wiki(FIXTURES / name, today=CHECK_DATE)

    @staticmethod
    def codes(result) -> set[str]:
        return {diagnostic.code for diagnostic in result.diagnostics}

    @staticmethod
    def diagnostics_for(result, code: str):
        return [diagnostic for diagnostic in result.diagnostics if diagnostic.code == code]

    def test_blocker_vocabulary_is_the_six_canonical_codes(self) -> None:
        self.assertEqual(
            {
                "pending-board-review",
                "missing-design",
                "missing-app-requirements",
                "unresolved-open-questions",
                "api-contract-not-ready",
                "cross-app-dependency",
            },
            WIKI_BLOCKER_CODES,
        )

    def test_healthy_and_fresh_fixtures_are_clean(self) -> None:
        healthy = self.lint_fixture("healthy")
        fresh = self.lint_fixture("fresh")

        self.assertTrue(healthy.is_clean)
        self.assertEqual([], healthy.to_dict()["blocker_facts"])
        self.assertTrue(fresh.is_clean)
        self.assertEqual(0, fresh.feature_count)

    def test_partial_fixture_reports_each_canonical_blocker(self) -> None:
        result = self.lint_fixture("partial")
        blockers = self.codes(result) & WIKI_BLOCKER_CODES

        self.assertEqual(WIKI_BLOCKER_CODES, blockers)

        pending = self.diagnostics_for(result, "pending-board-review")
        self.assertEqual({"F-001", "F-002", "F-005"}, {diagnostic.feature_id for diagnostic in pending})
        self.assertTrue(any("ready-for-design" in diagnostic.message for diagnostic in pending))

        missing_design = self.diagnostics_for(result, "missing-design")
        self.assertEqual({"F-003", "F-006"}, {diagnostic.feature_id for diagnostic in missing_design})
        self.assertFalse(any(diagnostic.feature_id == "F-001" for diagnostic in missing_design))

        missing_requirements = self.diagnostics_for(result, "missing-app-requirements")
        self.assertEqual({"F-006"}, {diagnostic.feature_id for diagnostic in missing_requirements})
        self.assertTrue(any("mobile-ios" in diagnostic.message for diagnostic in missing_requirements))

        unresolved = self.diagnostics_for(result, "unresolved-open-questions")
        self.assertEqual({"F-003"}, {diagnostic.feature_id for diagnostic in unresolved})

        api_contracts = self.diagnostics_for(result, "api-contract-not-ready")
        self.assertEqual({"F-003"}, {diagnostic.feature_id for diagnostic in api_contracts})
        self.assertTrue(all(Path(diagnostic.path).as_posix().endswith("api-contracts/F-003.md") for diagnostic in api_contracts))

        cross_platform = self.diagnostics_for(result, "cross-app-dependency")
        self.assertEqual(2, len(cross_platform))
        self.assertTrue(all(diagnostic.feature_id == "F-003" for diagnostic in cross_platform))

    def test_malformed_fixture_keeps_bad_pages_and_values_visible(self) -> None:
        result = self.lint_fixture("malformed")
        codes = self.codes(result)

        self.assertIn("malformed-frontmatter", codes)
        self.assertIn("malformed-page", codes)
        self.assertIn("invalid-feature-status", codes)
        self.assertIn("invalid-feature-owner", codes)
        self.assertIn("invalid-feature-apps", codes)
        self.assertIn("invalid-api-contract-status", codes)
        self.assertIn("invalid-wiki-stale-after-days", codes)
        self.assertIn("history-date-on-page", codes)
        self.assertIn("broken-wiki-link", codes)
        self.assertTrue(any(diagnostic.feature_id == "F-002" for diagnostic in self.diagnostics_for(result, "broken-wiki-link")))

    def test_invalid_auxiliary_frontmatter_is_visible_and_page_remains_a_graph_node(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            target_wiki = workspace / "knowledge" / "wiki"
            target_wiki.parent.mkdir(parents=True)
            shutil.copytree(FIXTURES / "healthy" / "knowledge" / "wiki", target_wiki)
            shutil.copyfile(FIXTURES / "healthy" / "prism.workspace.yml", target_wiki.parents[1] / "prism.workspace.yml")
            (target_wiki / "api-contracts").mkdir(exist_ok=True)
            (target_wiki / "api-contracts" / "F-007-bad.md").write_text(
                "---\nfeature-id: F-007\nversion: 1\nstatus:\n---\n\n## Endpoints\nGET /broken\n",
                encoding="utf-8",
            )

            result = lint_wiki(workspace, today=CHECK_DATE)
            graph = build_graph(workspace)

        self.assertIn("invalid-api-contract-status", self.codes(result))
        nodes = [node for node in graph["facts"]["nodes"] if node["id"] == "api:F-007-bad"]
        self.assertEqual(1, len(nodes))
        self.assertEqual("error", nodes[0]["health"])

    def test_design_exemption_is_required_and_applies_to_downstream_stages(self) -> None:
        for status, owner in (("ready-for-dev", "dev"), ("in-dev", "dev"), ("done", "none")):
            with self.subTest(status=status):
                with tempfile.TemporaryDirectory() as temp_dir:
                    workspace = Path(temp_dir)
                    target_wiki = workspace / "knowledge" / "wiki"
                    target_wiki.parent.mkdir(parents=True)
                    shutil.copytree(FIXTURES / "healthy" / "knowledge" / "wiki", target_wiki)
                    shutil.copyfile(FIXTURES / "healthy" / "prism.workspace.yml", target_wiki.parents[1] / "prism.workspace.yml")
                    feature = target_wiki / "features" / "F-001-checkout.md"
                    body = feature.read_text(encoding="utf-8")
                    body = body.replace(
                        "status: specified\nowner: po\n",
                        f"status: {status}\nowner: {owner}\n",
                    ).replace(
                        "apps: [backend]\n",
                        "apps: [mobile-ios]\n",
                    ).replace(
                        "advisory-review: not-needed\n",
                        "advisory-review: not-needed\n"
                        "design: not-applicable\n"
                        "design-exemption-reason: Confirmed backend-only workflow with no visual surface.\n",
                    )
                    feature.write_text(body, encoding="utf-8")
                    result = lint_wiki(workspace, today=CHECK_DATE)
                    self.assertFalse(
                        any(
                            diagnostic.code == "missing-design" and diagnostic.feature_id == "F-001"
                            for diagnostic in result.diagnostics
                        )
                    )

        for reason_line in ("", "design-exemption-reason:   "):
            with self.subTest(reason_line=reason_line):
                with tempfile.TemporaryDirectory() as temp_dir:
                    workspace = Path(temp_dir)
                    target_wiki = workspace / "knowledge" / "wiki"
                    target_wiki.parent.mkdir(parents=True)
                    shutil.copytree(FIXTURES / "healthy" / "knowledge" / "wiki", target_wiki)
                    shutil.copyfile(FIXTURES / "healthy" / "prism.workspace.yml", target_wiki.parents[1] / "prism.workspace.yml")
                    feature = target_wiki / "features" / "F-001-checkout.md"
                    body = feature.read_text(encoding="utf-8").replace(
                        "status: specified\nowner: po\n",
                        "status: ready-for-dev\nowner: dev\n",
                    ).replace(
                        "apps: [backend]\n",
                        "apps: [mobile-ios]\n",
                    ).replace(
                        "advisory-review: not-needed\n",
                        "advisory-review: not-needed\n"
                        "design: not-applicable\n"
                        f"{reason_line}\n",
                    )
                    feature.write_text(body, encoding="utf-8")
                    result = lint_wiki(workspace, today=CHECK_DATE)
                    self.assertTrue(
                        any(
                            diagnostic.code == "missing-design" and diagnostic.feature_id == "F-001"
                            for diagnostic in result.diagnostics
                        )
                    )

    def test_done_requires_resolved_advisory_and_open_questions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            target_wiki = workspace / "knowledge" / "wiki"
            target_wiki.parent.mkdir(parents=True)
            shutil.copytree(FIXTURES / "healthy" / "knowledge" / "wiki", target_wiki)
            shutil.copyfile(FIXTURES / "healthy" / "prism.workspace.yml", target_wiki.parents[1] / "prism.workspace.yml")
            feature = target_wiki / "features" / "F-001-checkout.md"
            body = feature.read_text(encoding="utf-8").replace(
                "status: specified\nowner: po\n",
                "status: done\nowner: none\n",
            ).replace(
                "advisory-review: not-needed\n",
                "advisory-review: pending\n",
            ).replace(
                "## Summary\nCustomers can complete a checkout.\n",
                "## Summary\nCustomers can complete a checkout.\n\n"
                "## Open questions\n\n"
                "| # | Question | Owner | Status |\n"
                "|---|----------|-------|--------|\n"
                "| 1 | Which settlement rule applies? | po | open |\n\n"
                "## Delivery evidence\n"
                "| App | Implementation | Tests | Release |\n"
                "|---|---|---|---|\n"
                "| backend | Synthetic implementation evidence | Synthetic test evidence | release: https://example.test/releases/synthetic |\n",
            )
            feature.write_text(body, encoding="utf-8")
            requirement = target_wiki / "app-requirements" / "F-001-backend.md"
            requirement.parent.mkdir(parents=True, exist_ok=True)
            requirement.write_text(
                "---\nfeature-id: F-001\napp: backend\nstatus: done\n---\n",
                encoding="utf-8",
            )

            result = lint_wiki(workspace, today=CHECK_DATE)
            self.assertTrue(
                any(diagnostic.code == "pending-board-review" and diagnostic.feature_id == "F-001" for diagnostic in result.diagnostics)
            )
            self.assertTrue(
                any(diagnostic.code == "unresolved-open-questions" and diagnostic.feature_id == "F-001" for diagnostic in result.diagnostics)
            )

    def test_index_drift_fixture_reports_source_of_truth_differences(self) -> None:
        result = self.lint_fixture("drifted")
        drift = self.diagnostics_for(result, "index-frontmatter-drift")

        self.assertEqual(3, len(drift))
        self.assertTrue(any("status" in diagnostic.message for diagnostic in drift))
        self.assertTrue(any("owner" in diagnostic.message for diagnostic in drift))
        self.assertTrue(any("board review" in diagnostic.message for diagnostic in drift))

    def test_settings_helper_uses_contract_fallback_without_hard_failure(self) -> None:
        source_wiki = FIXTURES / "fresh" / "knowledge" / "wiki"
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            target_wiki = workspace / "knowledge" / "wiki"
            target_wiki.parent.mkdir(parents=True)
            shutil.copytree(source_wiki, target_wiki)
            (target_wiki / "SETTINGS.md").unlink()

            settings = read_wiki_settings(target_wiki)
            result = lint_wiki(workspace, today=CHECK_DATE)

        self.assertEqual(14, settings.stale_after_days)
        self.assertTrue(settings.used_fallback)
        self.assertEqual("missing-wiki-settings", settings.diagnostics[0][0])
        self.assertTrue(result.is_clean)
        self.assertIn("missing-wiki-settings", self.codes(result))

    def test_lint_is_read_only_and_deterministic(self) -> None:
        fixture = FIXTURES / "partial"
        before = {
            path.relative_to(fixture).as_posix(): path.read_bytes()
            for path in fixture.rglob("*")
            if path.is_file()
        }

        first = self.lint_fixture("partial").to_dict()
        second = self.lint_fixture("partial").to_dict()
        after = {
            path.relative_to(fixture).as_posix(): path.read_bytes()
            for path in fixture.rglob("*")
            if path.is_file()
        }

        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))
        self.assertEqual(before, after)

    def test_link_check_decodes_targets_skips_external_sources_and_survives_bad_uri(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            target_wiki = workspace / "knowledge" / "wiki"
            target_wiki.parent.mkdir(parents=True)
            shutil.copytree(FIXTURES / "healthy" / "knowledge" / "wiki", target_wiki)
            shutil.copyfile(FIXTURES / "healthy" / "prism.workspace.yml", target_wiki.parents[1] / "prism.workspace.yml")
            feature_path = target_wiki / "features" / "F-001-checkout.md"
            feature_path.write_text(
                feature_path.read_text(encoding="utf-8")
                + "\n[Encoded missing page](../design/missing%20page.md)\n"
                + "[Processed source](../../intake/processed/brief.md)\n"
                + "[Malformed URI](//[::1.md)\n",
                encoding="utf-8",
            )

            result = lint_wiki(workspace, today=CHECK_DATE)

        broken = self.diagnostics_for(result, "broken-wiki-link")
        self.assertEqual(1, len(broken))
        self.assertIn("missing page.md", broken[0].message)

    def test_invalid_bytes_in_frontmatter_page_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            target_wiki = workspace / "knowledge" / "wiki"
            target_wiki.parent.mkdir(parents=True)
            shutil.copytree(FIXTURES / "healthy" / "knowledge" / "wiki", target_wiki)
            shutil.copyfile(FIXTURES / "healthy" / "prism.workspace.yml", target_wiki.parents[1] / "prism.workspace.yml")
            (target_wiki / "design").mkdir(exist_ok=True)
            (target_wiki / "design" / "F-002-bytes.md").write_bytes(b"\xff\xfe\xfa")

            result = lint_wiki(workspace, today=CHECK_DATE)

        malformed = self.diagnostics_for(result, "malformed-page")
        self.assertEqual(1, len(malformed))
        self.assertIn("F-002-bytes.md", malformed[0].path)

    def test_invalid_yaml_timestamp_is_reported_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            target_wiki = workspace / "knowledge" / "wiki"
            target_wiki.parent.mkdir(parents=True)
            shutil.copytree(FIXTURES / "healthy" / "knowledge" / "wiki", target_wiki)
            shutil.copyfile(FIXTURES / "healthy" / "prism.workspace.yml", target_wiki.parents[1] / "prism.workspace.yml")
            (target_wiki / "design").mkdir(exist_ok=True)
            (target_wiki / "design" / "F-002-invalid-date.md").write_text(
                "---\nfeature-id: F-001\ntitle: Invalid date\ndate: 2026-99-99\nfigma: none\n---\n",
                encoding="utf-8",
            )

            result = lint_wiki(workspace, today=CHECK_DATE)

        malformed = self.diagnostics_for(result, "malformed-page")
        self.assertTrue(any("F-002-invalid-date.md" in diagnostic.path for diagnostic in malformed))

    def test_invalid_index_bytes_are_reported_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            target_wiki = workspace / "knowledge" / "wiki"
            target_wiki.parent.mkdir(parents=True)
            shutil.copytree(FIXTURES / "healthy" / "knowledge" / "wiki", target_wiki)
            shutil.copyfile(FIXTURES / "healthy" / "prism.workspace.yml", target_wiki.parents[1] / "prism.workspace.yml")
            (target_wiki / "index.md").write_bytes(b"\xff\xfe\xfa")

            result = lint_wiki(workspace, today=CHECK_DATE)

        malformed = self.diagnostics_for(result, "malformed-index")
        self.assertEqual(1, len(malformed))

    def test_graph_retains_duplicate_page_ids_with_deterministic_node_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            target_wiki = workspace / "knowledge" / "wiki"
            target_wiki.parent.mkdir(parents=True)
            shutil.copytree(FIXTURES / "healthy" / "knowledge" / "wiki", target_wiki)
            shutil.copyfile(FIXTURES / "healthy" / "prism.workspace.yml", target_wiki.parents[1] / "prism.workspace.yml")
            (target_wiki / "features" / "F-001-second.md").write_text(
                "---\nid: F-001\ntitle: Duplicate checkout\nstatus: specified\nowner: po\n"
                "sources: []\nadvisory-review: not-needed\n---\n\n## Summary\nDuplicate.\n",
                encoding="utf-8",
            )

            graph = build_graph(workspace)

        feature_nodes = [node for node in graph["facts"]["nodes"] if node["type"] == "feature"]
        feature_ids = {node["id"] for node in feature_nodes}
        self.assertIn("F-001", feature_ids)
        self.assertIn("F-001:duplicate:F-001-second", feature_ids)
        duplicate = next(node for node in feature_nodes if node["id"] == "F-001:duplicate:F-001-second")
        self.assertEqual("error", duplicate["health"])
        self.assertIn("duplicate-feature-id", {diagnostic["code"] for diagnostic in graph["diagnostics"]})

    def test_graph_excludes_text_only_project_foundation_page(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            target_wiki = workspace / "knowledge" / "wiki"
            target_wiki.parent.mkdir(parents=True)
            shutil.copytree(FIXTURES / "fresh" / "knowledge" / "wiki", target_wiki)
            shutil.copyfile(FIXTURES / "fresh" / "prism.workspace.yml", target_wiki.parents[1] / "prism.workspace.yml")
            (target_wiki / "advisory").mkdir(exist_ok=True)
            (target_wiki / "advisory" / "PROJECT_FOUNDATION.md").write_text(
                "# Project foundation\n\nSetup interview and rationale.\n",
                encoding="utf-8",
            )

            graph = build_graph(workspace)

        self.assertFalse(any(node["path"] and node["path"].endswith("PROJECT_FOUNDATION.md") for node in graph["facts"]["nodes"]))

    def test_mermaid_keeps_blocker_badge_for_a_blocked_feature(self) -> None:
        graph = build_graph(FIXTURES / "partial")

        mermaid = render_mermaid(graph, "lifecycle")

        self.assertIn("class n_F_001 blocked", mermaid)
        self.assertNotIn("class n_F_001 broken", mermaid)
        self.assertIn("n_F_001 ~~~ n_F_002", mermaid)
        self.assertIn("n_F_002 ~~~ n_F_003", mermaid)

    def test_mermaid_keeps_invalid_status_features_in_explicit_broken_group(self) -> None:
        graph = build_graph(FIXTURES / "malformed")

        mermaid = render_mermaid(graph, "lifecycle")

        self.assertIn('subgraph s_invalid["invalid"]', mermaid)
        self.assertIn("n_F_003", mermaid)
        self.assertIn("class n_F_003 broken", mermaid)


if __name__ == "__main__":
    unittest.main()
