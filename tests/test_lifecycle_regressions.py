"""Real-file regression coverage for lifecycle request preflight semantics.

These tests deliberately build small generated-project-shaped workspaces in a
temporary directory.  The transition evaluator and lint reader must derive
their answers from the files on disk; no lifecycle command is invoked and no
fixture is allowed to mutate the repository checkout.
"""

from __future__ import annotations

import tempfile
import unittest

import yaml
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from prism_cli.wiki_graph import build_graph
from prism_cli.wiki_lint import lint_wiki
from prism_cli.wiki_transitions import ACTION_SPECS, build_board_transition_preflight, build_transition_preflight
from prism_cli.wiki_model import DesignTracks, contract_citation, status_rank
from tests.design_tracks import SETTLED, technical_design_page, with_tracks
from tests.manifest_fixtures import manifest_text
from tests import real_temp  # noqa: F401
from tests.wiki_files import evidence_tables, write_index, write_status_board


REPO_ROOT = Path(__file__).resolve().parents[1]
CHECK_DATE = date(2026, 9, 8)
UI_DONE_TRACKS = "design-tracks:\n  ui: done\n  technical: not-applicable\n  technical-reason: The feature changes no architecture.\ndesign-reaffirm: []"
CRITERION = "The summary includes the selected payout period."


class LifecycleRegressionTests(unittest.TestCase):
    """Pin the source-of-truth and evidence rules used by transition requests."""

    def setUp(self) -> None:
        self.clock = Mock(wraps=date)
        self.clock.today.return_value = CHECK_DATE
        for module in ("wiki_lint", "wiki_transitions"):
            date_patch = patch(f"prism_cli.{module}.date", self.clock)
            date_patch.start()
            self.addCleanup(date_patch.stop)
        # The board evaluation also checks the identity of a connected board; these tests read the lifecycle rules only.
        identity = patch("prism_cli.wiki_transitions._board_workspace_identity_checks", return_value=[])
        identity.start()
        self.addCleanup(identity.stop)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self._create_workspace()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    @property
    def wiki_root(self) -> Path:
        return self.root / "knowledge" / "wiki"

    @property
    def feature_path(self) -> Path:
        return self.wiki_root / "features" / "F-001-payout-summary.md"

    def _create_workspace(self) -> None:
        (self.wiki_root / "features").mkdir(parents=True)
        (self.root / "backend").mkdir()
        (self.root / "knowledge" / "intake" / "pending").mkdir(parents=True)
        (self.root / "knowledge" / "intake" / "quarantined").mkdir(parents=True)
        (self.wiki_root / "SCHEMA.md").write_text("---\nschema-version: 1\n---\n# Wiki schema\n", encoding="utf-8")
        (self.wiki_root / "LIFECYCLE.md").write_text("---\nschema-version: 1\n---\n# Wiki lifecycle\n", encoding="utf-8")
        (self.wiki_root / "ACTIONS.md").write_text("---\nschema-version: 1\n---\n# Wiki actions\n", encoding="utf-8")
        (self.wiki_root / "SETTINGS.md").write_text(
            "---\nwiki-stale-after-days: 14\n---\n",
            encoding="utf-8",
        )
        (self.root / "prism.workspace.yml").write_text(
            manifest_text("Lifecycle regression", ["backend"], slug="lifecycle-regression"),
            encoding="utf-8",
        )
        write_status_board(self.root)
        write_index(self.root)
        self._write_feature()
        self._write_all_capabilities()

    def _write_feature(
        self,
        *,
        feature_id: str = "F-001",
        filename: str | None = None,
        title: str = "Payout summary",
        status: str = "specified",
        owner: str = "po",
        platforms: tuple[str, ...] = ("backend",),
        advisory: str = "not-needed",
        extra_frontmatter: str = "",
        questions: tuple[tuple[str, str, str, str], ...] = (),
        api_section: str = "",
        delivery_rows: tuple[tuple[str, str, str], ...] = (),
        evidence_stage: str | None = None,
        extra_body: str = "",
    ) -> Path:
        if filename is None:
            filename = f"{feature_id}-payout-summary.md"
        path = self.wiki_root / "features" / filename
        question_rows = "\n".join(
            f"| {number} | {question} | {question_owner} | {question_status} |"
            for number, question, question_owner, question_status in questions
        )
        if question_rows:
            question_rows += "\n"
        scope_rows = "\n".join(
            f"- **{platform}**: The {platform} implementation prepares the payout summary."
            for platform in platforms
        )
        api_block = ""
        if api_section:
            api_block = f"\n## API surface\n{api_section.rstrip()}\n"
        if evidence_stage:
            delivery_block = "\n" + evidence_tables(list(platforms), stage=evidence_stage, feature_id=feature_id, criterion=CRITERION)
            delivery_block += "\n## Evidence history\n"
        else:
            rows = "".join(
                f"| {platform} | `build:{platform}#1` | none | {implementation} | {tests} | checked |\n"
                for platform, implementation, tests in delivery_rows
            )
            delivery_block = (
                "\n## Delivery evidence\n"
                "| App | Artifact | Contract | Implementation | Tests | Basis |\n"
                "|---|---|---|---|---|---|\n"
                f"{rows}"
                "\n## QA verification\n"
                "| Row | Criteria | Method | Artifact | Environment | Attempt | Result | Evidence | Basis |\n"
                "|---|---|---|---|---|---|---|---|---|\n"
                "\n## Release\n"
                "| App | Target | Version | Attempt | Outcome | Record | Basis |\n"
                "|---|---|---|---|---|---|---|\n"
                "\n## Evidence history\n"
            )
        frontmatter_extra = f"{extra_frontmatter.rstrip()}\n" if extra_frontmatter.strip() else ""
        body = (
            "---\n"
            f"id: {feature_id}\n"
            f"title: {title}\n"
            f"status: {status}\n"
            f"owner: {owner}\n"
            f"apps: [{', '.join(platforms)}]\n"
            "sources: []\n"
            f"advisory-review: {advisory}\n"
            "criteria-high-water: 1\n"
            f"{frontmatter_extra}"
            "---\n\n"
            "## Summary\n"
            "Customers can prepare a clear payout summary before review.\n\n"
            "## User story\n"
            "As a finance operator, I want a payout summary, so that I can review it before handoff.\n\n"
            "## Acceptance criteria\n"
            f"- [ ] AC-1 [{', '.join(platforms)}] {CRITERION}\n\n"
            "## Open questions\n\n"
            "| # | Question | Owner | Status |\n"
            "|---|----------|-------|--------|\n"
            f"{question_rows}\n"
            "## App scope\n"
            f"{scope_rows}\n"
            f"{api_block}"
            f"{delivery_block}"
            f"{extra_body.rstrip()}\n"
        )
        if "design-tracks" not in extra_frontmatter and status_rank(status) >= status_rank("in-design"):
            # A feature with API work settles the technical track with a technical design page; any other settles it by a reason.
            if api_section.strip():
                tracks = DesignTracks("not-applicable", "done", "No app in scope has a UI.", None)
                technical = self.wiki_root / "technical-design" / f"{feature_id}-payout-summary.md"
                technical.parent.mkdir(parents=True, exist_ok=True)
                technical.write_text(technical_design_page(feature_id, tuple(platforms), ("AC-1",)), encoding="utf-8")
            else:
                tracks = SETTLED
            body = with_tracks(body, tracks)
        path.write_text(body, encoding="utf-8")
        self._upsert_index(feature_id, title, status, owner, advisory)
        return path

    def _upsert_index(self, feature_id: str, title: str, status: str, owner: str, advisory: str) -> None:
        index_path = self.wiki_root / "status-board.md"
        lines = index_path.read_text(encoding="utf-8").splitlines()
        row = f"| {feature_id} | {title} | {status} | {owner} | {advisory} |"
        rows = [line for line in lines if line.startswith("| F-") and not line.startswith(f"| {feature_id} |")]
        replaced = False
        updated: list[str] = []
        for line in lines:
            if line.startswith(f"| {feature_id} |"):
                updated.append(row)
                replaced = True
            else:
                updated.append(line)
        if not replaced:
            updated.append(row)
        index_path.write_text("\n".join(updated) + "\n", encoding="utf-8")
        # The app stages of the row follow the pages on disk.
        write_status_board(self.root, "".join(line + "\n" for line in updated if line.startswith("| F-")))

    def _write_manifest_platforms(self, platforms: tuple[str, ...]) -> None:
        (self.root / "prism.workspace.yml").write_text(manifest_text("Lifecycle regression", platforms, slug="lifecycle-regression"), encoding="utf-8")
        for platform in platforms:
            path = self.root / {
                "backend": "backend",
                "mobile-android": "mobile-android",
                "mobile-ios": "mobile-ios",
                "web": "web",
            }[platform]
            path.mkdir(parents=True, exist_ok=True)

    def _write_all_capabilities(self) -> None:
        for spec in (item for item in ACTION_SPECS if item.enabled and item.subject == "feature"):
            for relative in (
                Path(f".agents/skills/{spec.command}/SKILL.md"),
                Path(f".claude/commands/{spec.command}.md"),
            ):
                source = REPO_ROOT / "template" / f"{relative.as_posix()}.jinja"
                target = self.root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    def _write_requirement(
        self,
        *,
        feature_id: str = "F-001",
        platform: str = "backend",
        status: str = "pending",
        api_link: str = "",
        dependencies: str = "",
    ) -> Path:
        path = self.wiki_root / "app-requirements" / f"{feature_id}-{platform}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        api_block = f"\n## API contract reference\n{api_link.rstrip()}\n" if api_link else ""
        dependency_block = f"\n## Dependencies\n{dependencies.rstrip()}\n" if dependencies else ""
        path.write_text(
            "---\n"
            f"feature-id: {feature_id}\n"
            f"app: {platform}\n"
            f"status: {status}\n"
            "---\n\n"
            "## What to build\n"
            "Prepare the payout summary for this platform.\n\n"
            "## Technical constraints\n"
            "Use the existing platform patterns.\n\n"
            "## Acceptance criteria\n"
            "- The summary is available for review.\n"
            f"{api_block}"
            f"{dependency_block}",
            encoding="utf-8",
        )
        return path

    def _cite_contract(self, filename: str = "SHARED.md") -> None:
        """Make the delivery rows of F-001 cite the contract they depend on, as the board requires of a feature that has one."""

        contract = self.wiki_root / "api-contracts" / filename
        text = contract.read_text(encoding="utf-8")
        frontmatter, body = text.split("---\n", 2)[1], text.split("---\n", 2)[2]
        citation = contract_citation(yaml.safe_load(frontmatter)["feature-id"], 1, body)
        feature = self.wiki_root / "features" / "F-001-payout-summary.md"
        lines = feature.read_text(encoding="utf-8").splitlines(keepends=True)
        feature.write_text("".join(line.replace("` | none |", f"` | {citation} |") if line.startswith("| backend | `build:") else line for line in lines), encoding="utf-8")

    def _write_api(self, *, filename: str = "SHARED.md", feature_id: str = "F-999", status: str = "draft") -> Path:
        path = self.wiki_root / "api-contracts" / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "---\n"
            f"feature-id: {feature_id}\n"
            "version: 1\n"
            f"status: {status}\n"
            "---\n\n"
            "## Endpoints\n"
            "GET /payouts\n\n"
            "## Data models\n"
            "The response includes a payout summary.\n",
            encoding="utf-8",
        )
        return path

    def _write_design(self, feature_id: str = "F-001") -> Path:
        path = self.wiki_root / "design" / f"{feature_id}-payout-summary.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "---\n"
            f"feature-id: {feature_id}\n"
            "title: Payout summary design\n"
            "apps: [mobile-ios]\n"
            "figma: not applicable\n"
            "---\n\n"
            "## Summary\nThe review view covers the payout summary.\n\n"
            "## Key design decisions\nThe review state remains visible.\n\n"
            "## States covered\nEmpty, loading, error, and success.\n\n"
            "## Component references\nNo shared component reference.\n\n"
            "## Open design questions\nNone.\n",
            encoding="utf-8",
        )
        return path

    def _write_review(self, *, required_action: bool, deferred_action: bool = True) -> Path:
        required = "- [ ] Review the payout threshold with the product owner.\n" if required_action else "None.\n"
        deferred = "- [ ] Revisit copy after the local demo.\n" if deferred_action else "No deferred actions are recorded.\n"
        path = self.wiki_root / "advisory" / "F-001-review.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "---\n"
            "feature-id: F-001\n"
            "reviewed: 2026-09-08\n"
            "board-members-consulted: [regression-reviewer]\n"
            "---\n\n"
            "## 1. Conflicts\nNo conflicts identified.\n\n"
            "## 2. Gaps\nThe threshold needs review.\n\n"
            "## 3. Build order\nNo cross-platform ordering constraints.\n\n"
            "## 4. Biggest risk\nAn unclear threshold could confuse operators.\n\n"
            "## Board perspective summaries\nThe regression reviewer recorded the current concern.\n\n"
            "## Actions required before dev starts\n"
            f"{required}\n"
            "## Actions that can be deferred\n"
            f"{deferred}",
            encoding="utf-8",
        )
        return path

    def _transition(self, action: str, named: tuple[str, ...] = ("backend",)) -> dict:
        """The preflight of an action; `dev-done` is evaluated the way the board does, for the apps the proposal delivers."""

        if action == "dev-done":
            return build_board_transition_preflight(self.root, "F-001", action, named_apps=named)
        return build_transition_preflight(self.root, "F-001", action=action)["facts"]["transition"]

    @staticmethod
    def _check(transition: dict, code: str) -> dict:
        matches = [check for check in transition.get("checks", []) if check.get("code") == code]
        if not matches:
            raise AssertionError(f"Missing {code!r} check in {transition.get('checks')!r}")
        return matches[-1]

    def test_page_age_does_not_affect_lifecycle_actions(self) -> None:
        self._write_requirement(status="done")
        self._write_design()
        self._write_review(required_action=False)
        cases = (
            ("po-specify", "raw", "po"),
            ("po-handoff", "specified", "po"),
            ("design-start", "ready-for-design", "tech-lead"),
            ("design-handoff", "in-design", "tech-lead"),
            ("dev-start", "ready-for-dev", "dev"),
        )
        for action, status, owner in cases:
            self._write_feature(status=status, owner=owner, advisory="done")
            before = {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
            for age in (0, 14, 15, 365):
                with self.subTest(action=action, age_days=age):
                    self.clock.today.return_value = CHECK_DATE + timedelta(days=age)
                    preflight = build_transition_preflight(self.root, "F-001", action=action)
                    graph = build_graph(self.root)
                    node = next(node for node in graph["facts"]["nodes"] if node["id"] == "F-001")
                    graph_transition = next(item for item in node["transitions"] if item["action"] == action)
                    for transition in (preflight["facts"]["transition"], graph_transition):
                        self.assertEqual("ready", transition["classification"], transition["checks"])
                        self.assertTrue(transition["supported"])
                        self.assertEqual({"codex", "claude"}, set(transition["invocations"]))
                    for envelope in (preflight, graph):
                        self.assertEqual([], [item for item in envelope["diagnostics"] if item["code"] == "stale-page"])
                    self.assertEqual("ok", node["health"])
            after = {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
            self.assertEqual(before, after)

        # The delivery of an app is judged on the proposal's rows, never on the age of the page.
        self._write_feature(
            status="in-dev",
            owner="dev",
            advisory="done",
            delivery_rows=(("backend", "backend/src/payouts.py implemented", "tests/payouts passed"),),
        )
        for age in (0, 14, 15, 365):
            with self.subTest(action="dev-done", age_days=age):
                self.clock.today.return_value = CHECK_DATE + timedelta(days=age)
                transition = self._transition("dev-done")
                self.assertEqual("ready", transition["classification"], transition["checks"])
                self.assertTrue(transition["supported"])
                self.assertEqual("ready-for-qa", transition["target_status"])

    def test_page_age_does_not_hide_source_integrity_errors(self) -> None:
        self.clock.today.return_value = CHECK_DATE + timedelta(days=365)
        self._write_design()
        original = self.feature_path.read_text(encoding="utf-8")
        cases = (
            ("history-date-on-page", original.replace("apps:", "last-updated: 2026-09-08\napps:", 1)),
            ("broken-link", original + "\n[Missing design](../design/missing.md)\n"),
        )
        for code, body in cases:
            with self.subTest(code=code):
                self.feature_path.write_text(body, encoding="utf-8")
                preflight = build_transition_preflight(self.root, "F-001")
                graph = build_graph(self.root)
                node = next(node for node in graph["facts"]["nodes"] if node["id"] == "F-001")
                graph_transition = next(item for item in node["transitions"] if item["action"] == "po-handoff")
                for transition in (preflight["facts"]["transition"], graph_transition):
                    self.assertEqual("unknown", transition["classification"])
                    self.assertFalse(transition["supported"])
                    self.assertEqual("unknown", self._check(transition, f"source-integrity:{code}")["status"])
                for envelope in (preflight, graph):
                    self.assertIn(code, {item["code"] for item in envelope["diagnostics"]})

    def test_page_age_does_not_hide_workflow_blockers(self) -> None:
        self.clock.today.return_value = CHECK_DATE + timedelta(days=365)
        self._write_feature(advisory="pending")

        transition = self._transition("po-handoff")

        self.assertEqual("blocked", transition["classification"])
        self.assertEqual("review", self._check(transition, "advisory-review")["status"])

    def test_non_api_links_do_not_create_an_api_contract(self) -> None:
        """An external or ordinary link labelled API is not a local contract."""

        self._write_feature(
            status="ready-for-dev",
            owner="dev",
            extra_body="\nSee [API guidance](https://docs.example.test/api-contracts/SHARED.md).\n",
        )
        self._write_requirement()
        self._write_api(status="draft")

        transition = self._transition("dev-start")

        self.assertEqual("pass", self._check(transition, "api-contract")["status"])
        self.assertEqual("ready", transition["classification"])

    def test_shared_api_links_from_feature_or_scoped_requirement_gate_delivery(self) -> None:
        """Draft shared APIs block the delivery; agreed APIs remain requestable with evidence."""

        evidence = (("backend", "backend/src/payouts.py implemented", "tests/payouts passed"),)
        for source in ("feature", "requirement"):
            with self.subTest(source=source):
                link = "See [shared contract](../api-contracts/SHARED.md)."
                self._write_feature(
                    status="in-dev",
                    owner="dev",
                    api_section=link if source == "feature" else "",
                    delivery_rows=evidence,
                )
                self._write_requirement(api_link=link if source == "requirement" else "")
                api = self._write_api(status="draft")

                blocked = self._transition("dev-done")
                self.assertEqual("blocked", self._check(blocked, "api-contract")["status"])

                api.write_text(api.read_text(encoding="utf-8").replace("status: draft", "status: agreed"), encoding="utf-8")
                self._cite_contract()
                agreed = self._transition("dev-done")
                self.assertEqual("pass", self._check(agreed, "api-contract")["status"])
                self.assertEqual("ready", agreed["classification"])
                self.assertTrue(agreed["supported"])

    def test_out_of_scope_requirement_api_reference_does_not_block_delivery(self) -> None:
        self._write_manifest_platforms(("backend", "mobile-ios"))
        evidence = (("backend", "backend/src/payouts.py implemented", "tests/payouts passed"),)
        self._write_feature(status="in-dev", owner="dev", delivery_rows=evidence)
        self._write_requirement(platform="backend", status="pending")
        self._write_requirement(
            platform="mobile-ios",
            status="pending",
            api_link="See [shared contract](../api-contracts/SHARED.md).",
        )
        self._write_api(status="draft")

        transition = self._transition("dev-done")

        self.assertEqual("pass", self._check(transition, "app-requirements")["status"])
        self.assertEqual("pass", self._check(transition, "api-contract")["status"])
        self.assertEqual("ready", transition["classification"])

    def test_out_of_scope_requirement_dependency_stays_global_but_not_action_gate(self) -> None:
        """A global dependency fact is filtered only after scope is proven."""

        self._write_manifest_platforms(("backend", "mobile-ios"))
        self._write_review(required_action=False, deferred_action=False)
        self._write_feature(
            status="ready-for-dev",
            owner="dev",
            platforms=("mobile-ios",),
            advisory="done",
        )
        self._write_design()
        self._write_requirement(platform="mobile-ios", status="pending")
        self._write_requirement(platform="backend", status="pending", dependencies="F-002")
        self._write_feature(
            feature_id="F-002",
            filename="F-002-other-summary.md",
            title="Other summary",
            status="specified",
            owner="po",
            platforms=("backend",),
        )

        lint_result = lint_wiki(self.root, today=CHECK_DATE)
        global_dependency = [
            diagnostic
            for diagnostic in lint_result.diagnostics
            if diagnostic.code == "cross-app-dependency"
            and diagnostic.path.endswith("F-001-backend.md")
        ]
        self.assertTrue(global_dependency, lint_result.diagnostics)
        self.assertEqual("F-001", global_dependency[0].feature_id)

        envelope = build_transition_preflight(self.root, "F-001", action="dev-start")
        transition = envelope["facts"]["transition"]
        self.assertEqual("ready", transition["classification"])
        self.assertNotIn(
            "workflow:cross-app-dependency",
            {check["code"] for check in transition["checks"]},
        )
        self.assertTrue(
            any(
                diagnostic["code"] == "cross-app-dependency"
                and diagnostic.get("feature_id") == "F-001"
                for diagnostic in envelope["diagnostics"]
            )
        )
        self.assertTrue(
            any(
                diagnostic["code"] == "cross-app-dependency"
                and diagnostic.get("feature_id") == "F-001"
                for diagnostic in envelope["blocker_facts"]
            )
        )

    def test_declared_requirement_dependency_warns_on_the_selected_action(self) -> None:
        self._write_manifest_platforms(("backend", "mobile-ios"))
        self._write_review(required_action=False, deferred_action=False)
        self._write_feature(
            status="ready-for-dev",
            owner="dev",
            platforms=("mobile-ios",),
            advisory="done",
        )
        self._write_design()
        self._write_requirement(platform="mobile-ios", status="pending", dependencies="F-002")
        self._write_feature(
            feature_id="F-002",
            filename="F-002-other-summary.md",
            title="Other summary",
            status="specified",
            owner="po",
            platforms=("backend",),
        )

        transition = self._transition("dev-start")

        # An unreleased dependency warns and never blocks the start (CONTRACTS 8.1).
        self.assertEqual("ready", transition["classification"], transition["checks"])
        dependency_check = self._check(transition, "workflow:cross-app-dependency")
        self.assertEqual("warning", dependency_check["status"])
        self.assertIn("F-002", dependency_check["message"])

    def test_unknown_requirement_scope_keeps_the_dependency_warning(self) -> None:
        self._write_manifest_platforms(("backend", "mobile-ios"))
        self._write_review(required_action=False, deferred_action=False)
        self._write_feature(
            status="ready-for-dev",
            owner="dev",
            platforms=("mobile-ios",),
            advisory="done",
        )
        self._write_design()
        self._write_requirement(platform="mobile-ios", status="pending")
        requirement = self._write_requirement(platform="backend", status="pending", dependencies="F-002")
        valid_requirement = requirement.read_text(encoding="utf-8")
        self._write_feature(
            feature_id="F-002",
            filename="F-002-other-summary.md",
            title="Other summary",
            status="specified",
            owner="po",
            platforms=("backend",),
        )

        for malformed_platform in ("", "unsupported-platform"):
            with self.subTest(platform=malformed_platform or "missing"):
                replacement = "app:" if not malformed_platform else f"app: {malformed_platform}"
                requirement.write_text(
                    valid_requirement.replace("app: backend", replacement),
                    encoding="utf-8",
                )
                transition = self._transition("dev-start")

                self.assertNotEqual("ready", transition["classification"])
                dependency_check = self._check(transition, "workflow:cross-app-dependency")
                self.assertEqual("warning", dependency_check["status"])

    def test_a_malformed_revalidation_value_is_a_lint_error_and_blocks_the_gate(self) -> None:
        self._write_review(required_action=False, deferred_action=False)
        self._write_requirement(status="pending")
        self._write_feature(
            status="ready-for-dev",
            owner="dev",
            advisory="done",
            extra_frontmatter="revalidation: [unrecognized-domain]",
        )
        codes = {item.code for item in lint_wiki(self.root, today=CHECK_DATE).diagnostics if item.feature_id == "F-001"}
        self.assertIn("invalid-revalidation", codes)
        transition = self._transition("dev-start")
        self.assertNotEqual("ready", transition["classification"])
        self.assertIn("unrecognized-domain", self._check(transition, "revalidation")["message"])

    def test_a_scope_without_a_ui_app_needs_no_design_page_and_a_ui_app_needs_one(self) -> None:
        """The design owner follows the scope: a settled UI track covers every app with a UI (or an unknown one) by a design page."""

        self._write_manifest_platforms(("backend", "mobile-ios"))
        self._write_review(required_action=False, deferred_action=False)
        self._write_requirement(platform="backend", status="done")
        self._write_requirement(platform="mobile-ios", status="done")
        evidence = (("backend", "backend/src/payouts.py implemented", "tests/payouts passed"),)
        self.assertFalse((self.wiki_root / "design").exists())

        for status, owner, action in (("ready-for-dev", "dev", "dev-start"), ("in-dev", "dev", "dev-done")):
            with self.subTest(scope="backend", action=action):
                self._write_feature(status=status, owner=owner, platforms=("backend",), advisory="done", delivery_rows=evidence if action == "dev-done" else ())
                lint_result = lint_wiki(self.root, today=CHECK_DATE)
                self.assertFalse(any(item.code == "design-coverage-incomplete" and item.feature_id == "F-001" for item in lint_result.diagnostics), lint_result.diagnostics)
                transition = self._transition(action)
                self.assertEqual("ready", transition["classification"], transition["checks"])

        for status, owner, action in (("ready-for-dev", "dev", "dev-start"), ("in-dev", "dev", "dev-done")):
            with self.subTest(scope="mobile-ios", action=action):
                self._write_feature(
                    status=status,
                    owner=owner,
                    platforms=("mobile-ios",),
                    advisory="done",
                    delivery_rows=(("mobile-ios", "mobile-ios/Summary.swift implemented", "tests/SummaryTests passed"),) if action == "dev-done" else (),
                    extra_frontmatter=UI_DONE_TRACKS,
                )
                lint_result = lint_wiki(self.root, today=CHECK_DATE)
                self.assertTrue(any(item.code == "design-coverage-incomplete" and item.feature_id == "F-001" for item in lint_result.diagnostics), lint_result.diagnostics)
                transition = self._transition(action, ("mobile-ios",) if action == "dev-done" else None)
                self.assertNotEqual("ready", transition["classification"])
                self.assertEqual("unknown", self._check(transition, "source-integrity:design-coverage-incomplete")["status"])
        # A recorded design page that lists the app clears it.
        self._write_design()
        self._write_feature(
            status="in-dev",
            owner="dev",
            platforms=("mobile-ios",),
            advisory="done",
            delivery_rows=(("mobile-ios", "mobile-ios/Summary.swift implemented", "tests/SummaryTests passed"),),
            extra_frontmatter=UI_DONE_TRACKS,
        )
        self.assertFalse(any(item.code == "design-coverage-incomplete" for item in lint_wiki(self.root, today=CHECK_DATE).diagnostics))
        recorded = self._transition("dev-done", ("mobile-ios",))
        self.assertEqual("ready", recorded["classification"], recorded["checks"])
        self.assertNotIn("source-integrity:design-coverage-incomplete", {check["code"] for check in recorded["checks"]})

    def test_the_design_exemption_fields_are_no_longer_feature_fields(self) -> None:
        self._write_feature(
            status="ready-for-dev",
            owner="dev",
            advisory="done",
            extra_frontmatter="design: not-applicable\ndesign-exemption-reason: This service flow has no visual UI.",
        )
        codes = [item.code for item in lint_wiki(self.root, today=CHECK_DATE).diagnostics if item.feature_id == "F-001" or item.feature_id is None]
        self.assertIn("unsupported-feature-field", codes)

    def test_open_question_checks_name_question_numbers_and_count_them_separately(self) -> None:
        cases = (
            ("dev-start", "ready-for-dev", "dev", "dev", (("3", "Which limit applies?", "dev", "open"),), "1 open action-relevant question remains: question 3."),
            (
                "dev-start",
                "ready-for-dev",
                "dev",
                "dev",
                (("3", "Which limit applies?", "dev", "open"), ("5", "Which store is used?", "dev", "open"), ("6", "Already answered", "dev", "resolved: Yes.")),
                "2 open action-relevant questions remain: questions 3, 5.",
            ),
            ("po-handoff", "specified", "po", "po", (("1", "Which points?", "po", "open"),), "1 open PO-owned question remains: question 1."),
            (
                "po-handoff",
                "specified",
                "po",
                "po",
                (("2", "Which points?", "po", "open"), ("4", "Which format?", "po", "open")),
                "2 open PO-owned questions remain: questions 2, 4.",
            ),
        )
        for action, status, owner, _question_owner, questions, expected in cases:
            with self.subTest(action=action, expected=expected):
                self._write_feature(status=status, owner=owner, advisory="done", questions=questions)
                check = self._check(self._transition(action), "open-questions")
                self.assertEqual("blocked", check["status"])
                self.assertEqual(expected, check["message"])
                self.assertNotIn("(", check["message"])

    def test_a_requirement_linking_its_own_feature_does_not_depend_on_it(self) -> None:
        self._write_feature(status="in-dev", owner="dev", advisory="done")
        own_link = "Context: [F-001](../features/F-001-payout-summary.md) and its feature page F-001-payout-summary.md."
        self._write_requirement(status="pending", dependencies=own_link)
        diagnostics = [item for item in lint_wiki(self.root, today=CHECK_DATE).diagnostics if item.code == "cross-app-dependency"]
        self.assertEqual([], diagnostics, diagnostics)

        plain = "This follows F-001 and [the requirement itself](F-001-backend.md)."
        self._write_requirement(status="pending", dependencies=plain)
        self.assertEqual([], [item for item in lint_wiki(self.root, today=CHECK_DATE).diagnostics if item.code == "cross-app-dependency"])

        # Another unfinished feature is still a dependency.
        self._write_feature(feature_id="F-002", filename="F-002-other-summary.md", title="Other summary", status="specified", owner="po")
        self._write_requirement(status="pending", dependencies=own_link + " It also waits for [F-002](../features/F-002-other-summary.md).")
        found = [item for item in lint_wiki(self.root, today=CHECK_DATE).diagnostics if item.code == "cross-app-dependency"]
        self.assertEqual(1, len(found), found)
        self.assertIn("unfinished feature `F-002`", found[0].message)
        self.assertNotIn("`F-001`", found[0].message)

    def test_design_start_allows_designer_owned_questions(self) -> None:
        self._write_feature(
            status="ready-for-design",
            owner="tech-lead",
            advisory="done",
            questions=(("1", "Which interaction needs review?", "designer", "open"),),
        )

        transition = self._transition("design-start")

        self.assertEqual("pass", self._check(transition, "open-questions")["status"])
        self.assertEqual("ready", transition["classification"])

    def test_the_reopen_routes_of_a_released_feature_are_registered_and_unavailable(self) -> None:
        self._write_review(required_action=False, deferred_action=False)
        self._write_requirement(status="done")
        self._write_feature(status="released", owner="none", advisory="done", evidence_stage="released")
        self.assertEqual([], [item.code for item in lint_wiki(self.root, today=CHECK_DATE).diagnostics if item.severity == "error" and item.feature_id == "F-001"])
        for action in ("reopen-spec", "reopen-design", "reopen-dev"):
            with self.subTest(action=action):
                transition = build_board_transition_preflight(self.root, "F-001", action)
                self.assertEqual("unknown", transition["classification"])
                self.assertFalse(transition["supported"])
                self.assertEqual("unknown", self._check(transition, "action-unavailable")["status"])
                copy_only = self._transition(action)
                self.assertEqual("unknown", copy_only["classification"])
                self.assertFalse(copy_only["supported"])

    def test_delivery_needs_evidence_for_every_named_app_and_earlier_revalidation_blocks(self) -> None:
        self._write_manifest_platforms(("backend", "mobile-ios"))
        self._write_requirement(platform="backend", status="pending")
        self._write_requirement(platform="mobile-ios", status="in-progress")
        self._write_design()
        self._write_review(required_action=False, deferred_action=False)
        backend_evidence = (("backend", "backend/src/payouts.py implemented", "tests/payouts passed"),)
        self._write_feature(
            status="in-dev",
            owner="dev",
            platforms=("backend", "mobile-ios"),
            advisory="done",
            delivery_rows=backend_evidence,
        )

        missing_platform = self._transition("dev-done", ("backend", "mobile-ios"))
        self.assertEqual("blocked", self._check(missing_platform, "delivery-evidence")["status"])

        complete_evidence = backend_evidence + (
            ("mobile-ios", "mobile-ios/Summary.swift implemented", "tests/SummaryTests passed"),
        )
        self._write_feature(
            status="in-dev",
            owner="dev",
            platforms=("backend", "mobile-ios"),
            advisory="done",
            extra_frontmatter="app-revalidation:\n  backend: [implementation, tests]\n  mobile-ios: [implementation, tests]",
            delivery_rows=complete_evidence,
        )
        owned_revalidation = self._transition("dev-done", ("backend", "mobile-ios"))
        self.assertEqual("pass", self._check(owned_revalidation, "delivery-evidence")["status"])
        self.assertEqual("pass", self._check(owned_revalidation, "app-revalidation")["status"])
        self.assertEqual("ready", owned_revalidation["classification"])

        self._write_feature(
            status="in-dev",
            owner="dev",
            platforms=("backend", "mobile-ios"),
            advisory="done",
            extra_frontmatter="revalidation: [specification, design]",
            delivery_rows=complete_evidence,
        )
        earlier_revalidation = self._transition("dev-done", ("backend", "mobile-ios"))
        self.assertEqual("blocked", self._check(earlier_revalidation, "revalidation")["status"])
        self.assertEqual("blocked", earlier_revalidation["classification"])

    def test_pending_requirement_and_agreed_api_can_be_proposed_for_delivery_but_lint_requires_completion(self) -> None:
        evidence = (("backend", "backend/src/payouts.py implemented", "tests/payouts passed"),)
        self._write_feature(
            status="in-dev",
            owner="dev",
            advisory="done",
            api_section="See [shared contract](../api-contracts/SHARED.md).",
            delivery_rows=evidence,
        )
        self._write_review(required_action=False, deferred_action=False)
        requirement = self._write_requirement(status="in-progress")
        api = self._write_api(status="agreed")
        self._cite_contract()

        request = self._transition("dev-done")
        self.assertEqual("pass", self._check(request, "app-requirements")["status"])
        self.assertEqual("pass", self._check(request, "api-contract")["status"])
        self.assertEqual("ready", request["classification"])

        self._write_feature(
            status="ready-for-qa",
            owner="qa",
            advisory="done",
            api_section="See [shared contract](../api-contracts/SHARED.md).",
            delivery_rows=evidence,
        )
        lint_before_completion = lint_wiki(self.root, today=CHECK_DATE)
        before_codes = {diagnostic.code for diagnostic in lint_before_completion.diagnostics}
        self.assertIn("done-app-requirement", before_codes)
        self.assertIn("delivered-api-contract", before_codes)

        requirement.write_text(requirement.read_text(encoding="utf-8").replace("status: in-progress", "status: done"), encoding="utf-8")
        api.write_text(api.read_text(encoding="utf-8").replace("status: agreed", "status: implemented"), encoding="utf-8")
        lint_after_completion = lint_wiki(self.root, today=CHECK_DATE)
        after_codes = {diagnostic.code for diagnostic in lint_after_completion.diagnostics}
        self.assertNotIn("done-app-requirement", after_codes)
        self.assertNotIn("delivered-api-contract", after_codes)

    def test_a_dependency_is_satisfied_only_by_a_released_parent_without_a_revalidation_domain(self) -> None:
        self._write_feature(
            status="in-dev",
            owner="dev",
            extra_frontmatter="revalidation: [specification]",
        )
        self._write_requirement(status="done")
        self._write_feature(
            feature_id="F-002",
            filename="F-002-dependent-summary.md",
            title="Dependent summary",
            status="ready-for-dev",
            owner="dev",
        )
        self._write_requirement(
            feature_id="F-002",
            status="done",
            dependencies="- [Payout requirement](F-001-backend.md)",
        )

        invalidated = lint_wiki(self.root, today=CHECK_DATE)
        dependency_diagnostics = [
            diagnostic
            for diagnostic in invalidated.diagnostics
            if diagnostic.code == "cross-app-dependency" and diagnostic.feature_id == "F-002"
        ]
        self.assertTrue(dependency_diagnostics)
        self.assertTrue(any("F-001-backend" in diagnostic.message for diagnostic in dependency_diagnostics))

        # A dependency is satisfied only when the app of the parent is released.
        self._write_feature(status="in-dev", owner="dev", extra_frontmatter="revalidation: []")
        still_unreleased = lint_wiki(self.root, today=CHECK_DATE)
        self.assertTrue(
            any(diagnostic.code == "cross-app-dependency" and diagnostic.feature_id == "F-002" for diagnostic in still_unreleased.diagnostics)
        )
        self._write_feature(status="released", owner="none", evidence_stage="released")
        restored = lint_wiki(self.root, today=CHECK_DATE)
        self.assertFalse(
            any(
                diagnostic.code == "cross-app-dependency" and diagnostic.feature_id == "F-002"
                for diagnostic in restored.diagnostics
            )
        )

    def test_required_advisory_actions_block_active_handoffs_but_deferred_actions_do_not(self) -> None:
        self._write_review(required_action=True)
        for action, status, owner in (
            ("design-handoff", "in-design", "tech-lead"),
            ("dev-start", "ready-for-dev", "dev"),
            ("dev-done", "in-dev", "dev"),
        ):
            with self.subTest(action=action):
                self._write_feature(status=status, owner=owner, advisory="done")
                if action in {"dev-start", "dev-done"}:
                    self._write_requirement(status="pending")
                if action == "dev-done":
                    self._write_feature(
                        status=status,
                        owner=owner,
                        advisory="done",
                        delivery_rows=(("backend", "backend/src/payouts.py implemented", "tests/payouts passed"),),
                    )
                transition = self._transition(action)
                advisory_action_checks = [check for check in transition["checks"] if check.get("code") == "advisory-actions"]
                self.assertTrue(advisory_action_checks, transition["checks"])
                self.assertIn(advisory_action_checks[0]["status"], {"blocked", "review"})
                self.assertEqual("blocked", transition["classification"])

        self._write_review(required_action=False, deferred_action=True)
        self._write_feature(status="ready-for-dev", owner="dev", advisory="done")
        self._write_requirement(status="pending")
        deferred_only = self._transition("dev-start")
        self.assertEqual("ready", deferred_only["classification"])
        self.assertEqual("pass", self._check(deferred_only, "advisory-review")["status"])


if __name__ == "__main__":
    unittest.main()
