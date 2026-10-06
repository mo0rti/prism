"""Real-file regression coverage for lifecycle request preflight semantics.

These tests deliberately build small generated-project-shaped workspaces in a
temporary directory.  The transition evaluator and lint reader must derive
their answers from the files on disk; no lifecycle command is invoked and no
fixture is allowed to mutate the repository checkout.
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from prism_cli.wiki_graph import build_graph
from prism_cli.wiki_lint import lint_wiki
from prism_cli.wiki_transitions import ACTION_SPECS, build_transition_preflight
from tests.manifest_fixtures import manifest_text
from tests import real_temp  # noqa: F401
from tests.wiki_files import write_index, write_status_board


REPO_ROOT = Path(__file__).resolve().parents[1]
CHECK_DATE = date(2026, 9, 8)


class LifecycleRegressionTests(unittest.TestCase):
    """Pin the source-of-truth and evidence rules used by transition requests."""

    def setUp(self) -> None:
        self.clock = Mock(wraps=date)
        self.clock.today.return_value = CHECK_DATE
        for module in ("wiki_lint", "wiki_transitions"):
            date_patch = patch(f"prism_cli.{module}.date", self.clock)
            date_patch.start()
            self.addCleanup(date_patch.stop)
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
        delivery_rows: tuple[tuple[str, str, str, str], ...] = (),
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
        delivery_block = ""
        if delivery_rows:
            rows = "\n".join(
                f"| {platform} | {implementation} | {tests} | {release} |"
                for platform, implementation, tests, release in delivery_rows
            )
            delivery_block = (
                "\n## Delivery evidence\n"
                "| App | Implementation | Tests | Release |\n"
                "|---|---|---|---|\n"
                f"{rows}\n"
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
            f"{frontmatter_extra}"
            "---\n\n"
            "## Summary\n"
            "Customers can prepare a clear payout summary before review.\n\n"
            "## User story\n"
            "As a finance operator, I want a payout summary, so that I can review it before handoff.\n\n"
            "## Acceptance criteria\n"
            "- [ ] The summary includes the selected payout period.\n"
            "- [ ] The summary can be reviewed before it is handed off.\n\n"
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
        path.write_text(body, encoding="utf-8")
        self._upsert_index(feature_id, title, status, owner, advisory)
        return path

    def _upsert_index(self, feature_id: str, title: str, status: str, owner: str, advisory: str) -> None:
        index_path = self.wiki_root / "status-board.md"
        lines = index_path.read_text(encoding="utf-8").splitlines()
        row = f"| {feature_id} | {title} | {status} | {owner} | {advisory} |"
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

    def _write_manifest_platforms(self, platforms: tuple[str, ...]) -> None:
        (self.root / "prism.workspace.yml").write_text(manifest_text("Lifecycle regression", platforms, slug="lifecycle-regression"), encoding="utf-8")
        for platform in platforms:
            path = self.root / {
                "backend": "backend",
                "mobile-android": "mobile-android",
                "mobile-ios": "mobile-ios",
                "web-user-app": "web-user-app",
                "web-admin-portal": "web-admin-portal",
            }[platform]
            path.mkdir(parents=True, exist_ok=True)

    def _write_all_capabilities(self) -> None:
        for spec in ACTION_SPECS:
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
            "designer: regression\n"
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

    def _transition(self, action: str) -> dict:
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
            ("design-start", "ready-for-design", "designer"),
            ("design-handoff", "in-design", "designer"),
            ("dev-start", "ready-for-dev", "dev"),
            ("dev-done", "in-dev", "dev"),
            ("reopen-spec", "done", "none"),
            ("reopen-design", "done", "none"),
            ("reopen-dev", "done", "none"),
        )
        for action, status, owner in cases:
            self._write_feature(
                status=status,
                owner=owner,
                advisory="done",
                delivery_rows=(("backend", "backend/src/payouts.py", "tests/payouts passed", "release: https://example.test/releases/2026-09-08"),),
            )
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

    def test_page_age_does_not_hide_source_integrity_errors(self) -> None:
        self.clock.today.return_value = CHECK_DATE + timedelta(days=365)
        self._write_design()
        original = self.feature_path.read_text(encoding="utf-8")
        cases = (
            ("history-date-on-page", original.replace("apps:", "last-updated: 2026-09-08\napps:", 1)),
            ("broken-wiki-link", original + "\n[Missing design](../design/missing.md)\n"),
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

    def test_shared_api_links_from_feature_or_scoped_requirement_gate_done(self) -> None:
        """Draft shared APIs block; agreed APIs remain requestable with evidence."""

        evidence = (("backend", "backend/src/payouts.py implemented", "tests/payouts passed", "release: https://example.test/releases/2026-09-08"),)
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
                agreed = self._transition("dev-done")
                self.assertEqual("pass", self._check(agreed, "api-contract")["status"])
                self.assertEqual("ready", agreed["classification"])
                self.assertTrue(agreed["supported"])

    def test_out_of_scope_requirement_api_reference_does_not_block_done(self) -> None:
        self._write_manifest_platforms(("backend", "mobile-ios"))
        evidence = (("backend", "backend/src/payouts.py implemented", "tests/payouts passed", "release: https://example.test/releases/2026-09-08"),)
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
            extra_frontmatter=(
                "design: not-applicable\n"
                "design-exemption-reason: This service flow has no visual UI."
            ),
        )
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

    def test_declared_requirement_dependency_still_blocks_selected_action(self) -> None:
        self._write_manifest_platforms(("backend", "mobile-ios"))
        self._write_review(required_action=False, deferred_action=False)
        self._write_feature(
            status="ready-for-dev",
            owner="dev",
            platforms=("mobile-ios",),
            advisory="done",
            extra_frontmatter=(
                "design: not-applicable\n"
                "design-exemption-reason: This service flow has no visual UI."
            ),
        )
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

        self.assertEqual("blocked", transition["classification"])
        dependency_check = self._check(transition, "workflow:cross-app-dependency")
        self.assertEqual("blocked", dependency_check["status"])
        self.assertIn("F-002", dependency_check["message"])

    def test_unknown_requirement_scope_keeps_dependency_gate_fail_closed(self) -> None:
        self._write_manifest_platforms(("backend", "mobile-ios"))
        self._write_review(required_action=False, deferred_action=False)
        self._write_feature(
            status="ready-for-dev",
            owner="dev",
            platforms=("mobile-ios",),
            advisory="done",
            extra_frontmatter=(
                "design: not-applicable\n"
                "design-exemption-reason: This service flow has no visual UI."
            ),
        )
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
                self.assertEqual("blocked", dependency_check["status"])

    def test_malformed_revalidation_is_visible_but_reopen_routes_remain_requestable(self) -> None:
        self._write_review(required_action=False, deferred_action=False)
        self._write_feature(
            status="done",
            owner="none",
            advisory="done",
            extra_frontmatter="revalidation: [unrecognized-domain]",
        )

        for action in ("reopen-spec", "reopen-design", "reopen-dev"):
            with self.subTest(action=action):
                transition = self._transition(action)
                self.assertEqual("ready", transition["classification"])
                impact_review = self._check(transition, "reopen-impact-review")
                self.assertEqual("pass", impact_review["status"])
                self.assertIn("malformed", impact_review["message"].lower())
                self.assertIn("unrecognized-domain", impact_review["message"])

    def test_ui_design_exemption_requires_recorded_reason_and_unblocks_ready_state(self) -> None:
        """A recorded exemption covers every downstream lifecycle stage."""

        self._write_manifest_platforms(("backend", "mobile-ios"))
        self._write_review(required_action=False, deferred_action=False)
        self._write_requirement(platform="mobile-ios", status="done")
        evidence = (
            (
                "mobile-ios",
                "mobile-ios/Summary.swift implemented",
                "tests/SummaryTests passed",
                "release: https://example.test/releases/ios-2026-09-08",
            ),
        )
        exemption = (
            "design: not-applicable\n"
            "design-exemption-reason: This backend-facing flow has no visual UI."
        )
        self.assertFalse((self.wiki_root / "design").exists(), "the exemption scenario must not have a design page")

        for status, owner, action in (
            ("ready-for-dev", "dev", "dev-start"),
            ("in-dev", "dev", "dev-done"),
            ("done", "none", "reopen-dev"),
        ):
            with self.subTest(status=status, action=action):
                self._write_feature(
                    status=status,
                    owner=owner,
                    platforms=("mobile-ios",),
                    advisory="done",
                    extra_frontmatter=exemption,
                    delivery_rows=evidence,
                )
                lint_result = lint_wiki(self.root, today=CHECK_DATE)
                self.assertFalse(
                    any(
                        diagnostic.code == "missing-design" and diagnostic.feature_id == "F-001"
                        for diagnostic in lint_result.diagnostics
                    ),
                    lint_result.diagnostics,
                )
                transition = self._transition(action)
                self.assertEqual("ready", transition["classification"])
                if action == "dev-done":
                    self.assertEqual("pass", self._check(transition, "design")["status"])
                    self.assertEqual("pass", self._check(transition, "app-requirements")["status"])
                    self.assertEqual("pass", self._check(transition, "delivery-evidence")["status"])

        for missing_reason in (True, False):
            with self.subTest(missing_reason=missing_reason):
                invalid_exemption = "design: not-applicable\n"
                if not missing_reason:
                    invalid_exemption += "design-exemption-reason: "
                self._write_feature(
                    status="in-dev",
                    owner="dev",
                    platforms=("mobile-ios",),
                    advisory="done",
                    extra_frontmatter=invalid_exemption,
                    delivery_rows=evidence,
                )
                lint_result = lint_wiki(self.root, today=CHECK_DATE)
                self.assertTrue(
                    any(
                        diagnostic.code == "missing-design" and diagnostic.feature_id == "F-001"
                        for diagnostic in lint_result.diagnostics
                    ),
                    lint_result.diagnostics,
                )
                transition = self._transition("dev-done")
                self.assertEqual("blocked", transition["classification"])
                self.assertEqual("blocked", self._check(transition, "design")["status"])

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
            owner="designer",
            advisory="done",
            questions=(("1", "Which interaction needs review?", "designer", "open"),),
        )

        transition = self._transition("design-start")

        self.assertEqual("pass", self._check(transition, "open-questions")["status"])
        self.assertEqual("ready", transition["classification"])

    def test_done_feature_without_old_evidence_still_exposes_all_reopen_routes(self) -> None:
        self._write_review(required_action=False, deferred_action=False)
        self._write_feature(status="done", owner="none", advisory="done")
        expected = {
            "reopen-spec": "specified",
            "reopen-design": "in-design",
            "reopen-dev": "in-dev",
        }

        for action, target_status in expected.items():
            with self.subTest(action=action):
                transition = self._transition(action)
                self.assertEqual("ready", transition["classification"])
                self.assertTrue(transition["supported"])
                self.assertEqual(target_status, transition["target_status"])
                self.assertEqual("pass", self._check(transition, "reopen-impact-review")["status"])
                self.assertNotIn("done-delivery-evidence", {check["code"] for check in transition["checks"]})

    def test_done_requires_fresh_evidence_for_every_platform_and_earlier_revalidation_blocks(self) -> None:
        self._write_manifest_platforms(("backend", "mobile-ios"))
        self._write_requirement(platform="backend", status="pending")
        self._write_requirement(platform="mobile-ios", status="in-progress")
        self._write_design()
        self._write_review(required_action=False, deferred_action=False)
        backend_evidence = (("backend", "backend/src/payouts.py implemented", "tests/payouts passed", "release: https://example.test/releases/backend-2026-09-08"),)
        self._write_feature(
            status="in-dev",
            owner="dev",
            platforms=("backend", "mobile-ios"),
            advisory="done",
            delivery_rows=backend_evidence,
        )

        missing_platform = self._transition("dev-done")
        self.assertEqual("blocked", self._check(missing_platform, "delivery-evidence")["status"])

        complete_evidence = backend_evidence + (
            ("mobile-ios", "mobile-ios/Summary.swift implemented", "tests/SummaryTests passed", "release: https://example.test/releases/ios-2026-09-08"),
        )
        self._write_feature(
            status="in-dev",
            owner="dev",
            platforms=("backend", "mobile-ios"),
            advisory="done",
            extra_frontmatter="revalidation: [implementation, tests, release]",
            delivery_rows=complete_evidence,
        )
        owned_revalidation = self._transition("dev-done")
        self.assertEqual("pass", self._check(owned_revalidation, "delivery-evidence")["status"])
        self.assertEqual("pass", self._check(owned_revalidation, "revalidation")["status"])
        self.assertEqual("ready", owned_revalidation["classification"])

        self._write_feature(
            status="in-dev",
            owner="dev",
            platforms=("backend", "mobile-ios"),
            advisory="done",
            extra_frontmatter="revalidation: [specification, design]",
            delivery_rows=complete_evidence,
        )
        earlier_revalidation = self._transition("dev-done")
        self.assertEqual("blocked", self._check(earlier_revalidation, "revalidation")["status"])
        self.assertEqual("blocked", earlier_revalidation["classification"])

    def test_pending_requirement_and_agreed_api_can_be_proposed_done_but_lint_requires_completion(self) -> None:
        evidence = (("backend", "backend/src/payouts.py implemented", "tests/payouts passed", "release: https://example.test/releases/2026-09-08"),)
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

        request = self._transition("dev-done")
        self.assertEqual("pass", self._check(request, "app-requirements")["status"])
        self.assertEqual("pass", self._check(request, "api-contract")["status"])
        self.assertEqual("ready", request["classification"])

        self._write_feature(
            status="done",
            owner="none",
            advisory="done",
            api_section="See [shared contract](../api-contracts/SHARED.md).",
            delivery_rows=evidence,
        )
        lint_before_completion = lint_wiki(self.root, today=CHECK_DATE)
        before_codes = {diagnostic.code for diagnostic in lint_before_completion.diagnostics}
        self.assertIn("done-app-requirement", before_codes)
        self.assertIn("done-api-contract", before_codes)

        requirement.write_text(requirement.read_text(encoding="utf-8").replace("status: in-progress", "status: done"), encoding="utf-8")
        api.write_text(api.read_text(encoding="utf-8").replace("status: agreed", "status: implemented"), encoding="utf-8")
        lint_after_completion = lint_wiki(self.root, today=CHECK_DATE)
        after_codes = {diagnostic.code for diagnostic in lint_after_completion.diagnostics}
        self.assertNotIn("done-app-requirement", after_codes)
        self.assertNotIn("done-api-contract", after_codes)

    def test_reopened_parent_invalidates_downstream_done_requirement_even_when_status_is_done(self) -> None:
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

        self._write_feature(status="in-dev", owner="dev", extra_frontmatter="revalidation: []")
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
            ("design-handoff", "in-design", "designer"),
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
                        delivery_rows=(("backend", "backend/src/payouts.py implemented", "tests/payouts passed", "release: https://example.test/releases/2026-09-08"),),
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
