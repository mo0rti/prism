from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
import yaml
from collections import Counter, OrderedDict
from contextlib import redirect_stdout
from datetime import date, datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

from prism_cli.wiki_model import app_stages_text, parse_advisory_required_actions, parse_delivery_rows, read_feature_pages
from prism_cli.workspace import inspect_workspace
from prism_cli.wiki_graph import build_graph
from prism_cli.cli import build_parser
from prism_cli import wiki_lint
from prism_cli.wiki_lint import lint_wiki
from prism_cli.wiki_transitions import (
    ACTION_SPECS,
    CAPABILITY_FILES,
    FingerprintCache,
    _OBSERVED_AT_CACHE_LIMIT,
    build_board_transition_preflight,
    build_transition_preflight,
    evaluate_transition_summaries,
    fingerprint_digest,
    workspace_fingerprint,
)
from prism_cli.wiki_model import DesignTracks, contract_citation
from tests.design_tracks import SETTLED, ensure_tracks, technical_design_page, with_tracks
from tests.manifest_fixtures import manifest_text
from tests import real_temp  # noqa: F401
from tests.wiki_files import write_index, write_status_board


REPO_ROOT = Path(__file__).resolve().parents[1]
CHECK_DATE = date(2026, 9, 8)
FEATURE_TEMPLATE = """---
id: {feature_id}
title: {title}
status: {status}
owner: {owner}
apps: [{platforms}]
sources: []
advisory-review: {advisory}
{advisory_reason}criteria-high-water: 2
---

## Summary
Customers can prepare a clear payout summary before review.

## User story
As a finance operator, I want a payout summary, so that I can review it before handoff.

## Acceptance criteria
- [ ] AC-1 [{platforms}] The summary includes the selected payout period.
- [ ] AC-2 [{platforms}] The summary can be reviewed before it is handed off.

## Open questions

| # | Question | Owner | Status |
|---|----------|-------|--------|

## App scope
- **backend**: The backend prepares the summary data.

"""


class WikiTransitionTests(unittest.TestCase):
    def test_optional_surfaces_do_not_disable_available_lifecycle_capabilities(self) -> None:
        manifest_path = self.root / "prism.workspace.yml"
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        manifest.update({
            "min_prism_cli_version": "0.2.0",
            "expected_surfaces": {
                "ai": ["AGENTS.md", "CLAUDE.md", ".agents/skills", ".claude/commands", ".cursor/rules"],
                "docs": ["README.md", "AGENTS.md", "docs/"],
                "workflows": [".github/workflows/backend.yml"],
            },
        })
        manifest_path.write_text(yaml.safe_dump(manifest), encoding="utf-8")
        (self.root / CAPABILITY_FILES["claude"]).unlink()
        result = build_transition_preflight(self.root, "F-001", action="po-handoff")
        self.assertEqual("ready", result["facts"]["transition"]["classification"])
        self.assertTrue(result["facts"]["transition"]["supported"])
        # Real platform and minimum-version incompatibilities remain blocking.
        (self.root / "backend").rmdir()
        result = build_transition_preflight(self.root, "F-001", action="po-handoff")
        self.assertFalse(result["facts"]["transition"]["supported"])
        (self.root / "backend").mkdir()
        manifest["min_prism_cli_version"] = "99.0.0"
        manifest_path.write_text(yaml.safe_dump(manifest), encoding="utf-8")
        result = build_transition_preflight(self.root, "F-001", action="po-handoff")
        self.assertFalse(result["facts"]["transition"]["supported"])

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
        (self.wiki_root / "ACTIONS.md").write_text("---\nschema-version: 1\n---\n# Wiki actions\n", encoding="utf-8")
        (self.wiki_root / "SETTINGS.md").write_text(
            "---\nwiki-stale-after-days: 14\n---\n",
            encoding="utf-8",
        )
        write_status_board(self.root, "| F-001 | Payout summary | specified | po | not-needed |\n")
        write_index(self.root)
        (self.root / "prism.workspace.yml").write_text(
            manifest_text("Transition test", ["backend"], slug="transition-test"),
            encoding="utf-8",
        )
        self._write_feature()
        self._write_capabilities()

    def _write_feature(
        self,
        *,
        feature_id: str = "F-001",
        filename: str = "F-001-payout-summary.md",
        status: str = "specified",
        owner: str = "po",
        platforms: str = "backend",
        advisory: str = "not-needed",
        advisory_reason: str = "",
        body: str | None = None,
    ) -> Path:
        path = self.wiki_root / "features" / filename
        if body is None:
            body = FEATURE_TEMPLATE.format(
                feature_id=feature_id,
                title="Payout summary",
                status=status,
                owner=owner,
                platforms=platforms,
                advisory=advisory,
                advisory_reason=advisory_reason,
            )
        path.write_text(ensure_tracks(body, status), encoding="utf-8")
        index_path = self.wiki_root / "status-board.md"
        lines = index_path.read_text(encoding="utf-8").splitlines()
        stages = app_stages_text(status, [platforms], path.read_text(encoding="utf-8"), inspect_workspace(self.root).model)
        lines = [
            (
                f"| F-001 | Payout summary | {status} | {owner} | {advisory} | — | {stages} | — |"
                if line.startswith("| F-001 |")
                else line
            )
            for line in lines
        ]
        index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def _write_capabilities(self) -> None:
        for role, relative in CAPABILITY_FILES.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            invocation = "$po-handoff F-XXX" if role == "codex" else "/po-handoff F-XXX"
            path.write_text(
                f"<!-- prism:po-handoff-contract:v2 -->\n"
                f"Use {invocation}.\n",
                encoding="utf-8",
            )

    def _write_all_capabilities(self) -> None:
        """Render every lifecycle instruction surface from repository templates."""

        for spec in ACTION_SPECS:
            if not (spec.enabled and spec.copy):
                continue
            for role, relative in {
                "codex": Path(f".agents/skills/{spec.command}/SKILL.md"),
                "claude": Path(f".claude/commands/{spec.command}.md"),
            }.items():
                template_path = REPO_ROOT / "template" / Path(f"{relative.as_posix()}.jinja")
                generated_path = self.root / relative
                generated_path.parent.mkdir(parents=True, exist_ok=True)
                generated_path.write_text(template_path.read_text(encoding="utf-8"), encoding="utf-8")

    def _write_completed_advisory_review(self) -> None:
        review = self.wiki_root / "advisory" / "F-001-review.md"
        review.parent.mkdir(parents=True, exist_ok=True)
        review.write_text(
            "---\nfeature-id: F-001\nreviewed: 2026-09-08\n"
            "board-members-consulted: [Reviewer]\n---\n\n"
            "## Actions required before dev starts\n"
            "None required.\n",
            encoding="utf-8",
        )

    def test_action_registry_supports_raw_and_concrete_reopen_invocations(self) -> None:
        self._write_all_capabilities()
        self._write_feature(status="raw", owner="po")

        raw = build_transition_preflight(self.root, "F-001", action="po-specify")
        raw_transition = raw["facts"]["transition"]
        self.assertEqual("po-specify", raw_transition["action"])
        self.assertEqual("specified", raw_transition["target_status"])
        self.assertEqual("po", raw_transition["target_owner"])
        self.assertEqual("ready", raw_transition["classification"])

        self._write_feature(status="released", owner="none")
        reopen = build_transition_preflight(self.root, "F-001", action="reopen-design")
        transition = reopen["facts"]["transition"]
        self.assertEqual("reopen-design", transition["action"])
        self.assertEqual("in-design", transition["target_status"])
        self.assertEqual("tech-lead", transition["target_owner"])  # the design owner follows the scope: a backend-only scope has no UI app
        self.assertEqual("ready", transition["classification"])
        self.assertEqual("$feature-reopen F-001 in-design", transition["invocations"]["codex"])
        self.assertEqual("/feature-reopen F-001 in-design", transition["invocations"]["claude"])
        self.assertNotIn("specified|in-design|in-dev", json.dumps(transition))

        graph = build_graph(self.root)
        node = next(node for node in graph["facts"]["nodes"] if node["type"] == "feature")
        self.assertNotIn("transition", node)
        self.assertEqual(
            {"reopen-spec", "reopen-design", "reopen-dev"},
            {record["action"] for record in node["transitions"]},
        )

    def test_design_start_allows_design_work_and_designer_questions(self) -> None:
        self._write_all_capabilities()
        body = FEATURE_TEMPLATE.format(
            feature_id="F-001",
            title="Payout summary",
            status="ready-for-design",
            owner="tech-lead",
            platforms="backend",
            advisory="not-needed",
            advisory_reason="",
        ).replace(
            "|---|----------|-------|--------|\n\n## App scope",
            "|---|----------|-------|--------|\n| 1 | Which interaction needs review? | designer | open |\n\n## App scope",
        )
        self._write_feature(status="ready-for-design", owner="tech-lead", body=body)

        transition = build_transition_preflight(self.root, "F-001", action="design-start")["facts"]["transition"]

        self.assertEqual("design-start", transition["action"])
        self.assertEqual("ready", transition["classification"])
        self.assertTrue(transition["supported"])
        self.assertNotIn("design", {check["code"] for check in transition["checks"]})

    def test_a_ui_app_needs_a_design_page_and_there_is_no_exemption(self) -> None:
        self._write_all_capabilities()
        (self.root / "mobile-ios").mkdir()
        manifest = self.root / "prism.workspace.yml"
        manifest.write_text(
            manifest_text("Transition test", ["backend", "mobile-ios"], slug="transition-test"),
            encoding="utf-8",
        )
        body = FEATURE_TEMPLATE.format(
            feature_id="F-001",
            title="Payout summary",
            status="ready-for-dev",
            owner="dev",
            platforms="mobile-ios",
            advisory="not-needed",
            advisory_reason="",
        ).replace(
            "advisory-review: not-needed\n",
            "advisory-review: not-needed\n"
            "design: not-applicable\n"
            "design-exemption-reason: Confirmed backend-only workflow with no visual surface.\n",
        )
        self._write_feature(status="ready-for-dev", owner="dev", platforms="mobile-ios", body=body)
        requirements = self.wiki_root / "app-requirements" / "F-001-mobile-ios.md"
        requirements.parent.mkdir(parents=True, exist_ok=True)
        requirements.write_text(
            "---\nfeature-id: F-001\napp: mobile-ios\nstatus: pending\n---\n\n"
            "## Acceptance criteria\n- The flow is inspectable.\n",
            encoding="utf-8",
        )

        codes = {diagnostic.code for diagnostic in lint_wiki(self.root).diagnostics}
        self.assertIn("unsupported-feature-field", codes)

        # The old exemption fields exempt nothing. A settled UI track needs design pages that cover the app with a UI, or an exemption in the track.
        body = body.replace("design: not-applicable\ndesign-exemption-reason: Confirmed backend-only workflow with no visual surface.\n", "")
        done = with_tracks(body, DesignTracks("done", "not-applicable", None, "The feature changes no architecture."))
        self._write_feature(status="ready-for-dev", owner="dev", platforms="mobile-ios", body=done)
        self.assertIn("design-coverage-incomplete", {diagnostic.code for diagnostic in lint_wiki(self.root).diagnostics})
        design = self.wiki_root / "design" / "F-001-payout.md"
        design.parent.mkdir(parents=True, exist_ok=True)
        design.write_text(
            "---\nfeature-id: F-001\ntitle: Payout design\napps: [mobile-ios]\nfigma: not applicable\n---\n\n"
            "## Summary\nThe summary screen.\n",
            encoding="utf-8",
        )
        self.assertFalse(any(diagnostic.code == "design-coverage-incomplete" for diagnostic in lint_wiki(self.root).diagnostics))
        exempt = with_tracks(body, DesignTracks("not-applicable", "not-applicable", "The screens are unchanged.", "The feature changes no architecture."))
        self._write_feature(status="ready-for-dev", owner="dev", platforms="mobile-ios", body=exempt)
        design.unlink()
        self.assertFalse(any(diagnostic.code == "design-coverage-incomplete" for diagnostic in lint_wiki(self.root).diagnostics))
        self._write_feature(status="ready-for-dev", owner="dev", platforms="mobile-ios", body=done)
        design.write_text(
            "---\nfeature-id: F-001\ntitle: Payout design\napps: [mobile-ios]\nfigma: not applicable\n---\n\n"
            "## Summary\nThe summary screen.\n",
            encoding="utf-8",
        )
        transition = build_transition_preflight(self.root, "F-001", action="dev-start")["facts"]["transition"]
        self.assertEqual("pass", next(check for check in transition["checks"] if check["code"] == "app-scope")["status"])
        self.assertEqual("ready", transition["classification"])

    def test_dev_done_checks_the_delivery_rows_of_the_named_apps(self) -> None:
        self._write_all_capabilities()
        self._write_completed_advisory_review()
        body = FEATURE_TEMPLATE.format(
            feature_id="F-001",
            title="Payout summary",
            status="in-dev",
            owner="dev",
            platforms="backend",
            advisory="done",
            advisory_reason="",
        ) + (
            "## API surface\n"
            "- The payout summary endpoint is implemented by the backend.\n\n"
            "## Delivery evidence\n"
            "| App | Artifact | Contract | Implementation | Tests | Basis |\n"
            "|---|---|---|---|---|---|\n"
            "| backend | `build:backend#12` | CONTRACT | `backend/src/payouts.kt` implemented | `tests/payouts` passed | checked |\n"
        )
        contract_text = "---\nfeature-id: F-001\nversion: 1\nstatus: implemented\n---\n\n## Endpoints\nGET /payouts\n"
        body = body.replace("CONTRACT", contract_citation("F-001", 1, contract_text.split("---\n", 2)[2]))
        body = with_tracks(body, DesignTracks("not-applicable", "done", "No app in scope has a UI.", None))
        technical = self.wiki_root / "technical-design" / "F-001-payout-summary.md"
        technical.parent.mkdir(parents=True, exist_ok=True)
        technical.write_text(technical_design_page(), encoding="utf-8")
        self._write_feature(status="in-dev", owner="dev", advisory="done", body=body)
        requirements = self.wiki_root / "app-requirements" / "F-001-backend.md"
        requirements.parent.mkdir(parents=True, exist_ok=True)
        requirements.write_text(
            "---\nfeature-id: F-001\napp: backend\nstatus: done\n---\n\n## Acceptance criteria\n- Data is prepared.\n",
            encoding="utf-8",
        )
        api = self.wiki_root / "api-contracts" / "F-001.md"
        api.parent.mkdir(parents=True, exist_ok=True)
        api.write_text(contract_text, encoding="utf-8")

        # The copy-only preflight has no proposal: the delivery evidence is reported as not yet supplied.
        copy_only = build_transition_preflight(self.root, "F-001", action="dev-done")["facts"]["transition"]
        self.assertEqual("blocked", copy_only["classification"])
        self.assertEqual("blocked", next(check for check in copy_only["checks"] if check["code"] == "delivery-evidence")["status"])
        # The board evaluation names the apps the proposal delivers and checks their rows.
        identity = patch("prism_cli.wiki_transitions._board_workspace_identity_checks", return_value=[])
        identity.start()
        self.addCleanup(identity.stop)
        ready = build_board_transition_preflight(self.root, "F-001", "dev-done", named_apps=["backend"])
        self.assertEqual("ready", ready["classification"], ready["reason"])
        self.assertTrue(ready["supported"])
        self.assertEqual("ready-for-qa", ready["target_status"])
        self.assertEqual("qa", ready["target_owner"])

        current = self.feature_path.read_text(encoding="utf-8")
        self.feature_path.write_text(current.replace("advisory-review: done", "advisory-review: done\napp-revalidation:\n  backend: [tests]"), encoding="utf-8")
        reopened_work = build_board_transition_preflight(self.root, "F-001", "dev-done", named_apps=["backend"])
        self.assertEqual("ready", reopened_work["classification"], reopened_work["reason"])
        self.assertEqual("pass", next(check for check in reopened_work["checks"] if check["code"] == "app-revalidation")["status"])
        # A feature domain blocks the delivery.
        self.feature_path.write_text(current.replace("advisory-review: done", "advisory-review: done\nrevalidation: [design]"), encoding="utf-8")
        blocked = build_board_transition_preflight(self.root, "F-001", "dev-done", named_apps=["backend"])
        self.assertEqual("blocked", blocked["classification"])
        self.assertEqual("blocked", next(check for check in blocked["checks"] if check["code"] == "revalidation")["status"])

    def test_an_unreleased_dependency_warns_and_never_blocks_dev_start(self) -> None:
        self._write_all_capabilities()
        self._write_completed_advisory_review()
        body = FEATURE_TEMPLATE.format(
            feature_id="F-001",
            title="Payout summary",
            status="ready-for-dev",
            owner="dev",
            platforms="backend",
            advisory="done",
            advisory_reason="",
        )
        self._write_feature(status="ready-for-dev", owner="dev", advisory="done", body=body)
        other = FEATURE_TEMPLATE.format(
            feature_id="F-002", title="Other", status="in-dev", owner="dev", platforms="backend", advisory="not-needed", advisory_reason=""
        )
        (self.wiki_root / "features" / "F-002-other.md").write_text(other, encoding="utf-8")
        write_status_board(
            self.root,
            "| F-001 | Payout summary | ready-for-dev | dev | done |\n| F-002 | Other | in-dev | dev | not-needed |\n",
        )
        requirements = self.wiki_root / "app-requirements"
        requirements.mkdir(parents=True, exist_ok=True)
        (requirements / "F-001-backend.md").write_text(
            "---\nfeature-id: F-001\napp: backend\nstatus: pending\n---\n\n## What to build\nThe summary data.\n\n"
            "## Dependencies\n- [F-002](../features/F-002-other.md)\n",
            encoding="utf-8",
        )
        (requirements / "F-002-backend.md").write_text(
            "---\nfeature-id: F-002\napp: backend\nstatus: pending\n---\n\n## What to build\nSomething.\n",
            encoding="utf-8",
        )
        write_index(self.root)

        transition = build_transition_preflight(self.root, "F-001", action="dev-start")["facts"]["transition"]

        warning = next(check for check in transition["checks"] if check["code"] == "workflow:cross-app-dependency")
        self.assertEqual("warning", warning["status"])
        self.assertEqual("ready", transition["classification"], transition["reason"])
        self.assertIn("Warnings:", transition["reason"])

    def test_api_gate_uses_feature_scope_and_explicit_links_only(self) -> None:
        # The requirement page of an app outside the feature's scope still names an app of the workspace.
        (self.root / "prism.workspace.yml").write_text(
            manifest_text("Transition test", ["backend", "mobile-ios"], slug="transition-test"),
            encoding="utf-8",
        )
        (self.root / "mobile-ios").mkdir()
        self._write_all_capabilities()
        self._write_completed_advisory_review()
        body = FEATURE_TEMPLATE.format(
            feature_id="F-001",
            title="Payout summary",
            status="ready-for-dev",
            owner="dev",
            platforms="backend",
            advisory="done",
            advisory_reason="",
        ) + "\nSee [the persona](../personas/operator.md) for context.\n"
        self._write_feature(status="ready-for-dev", owner="dev", advisory="done", body=body)
        requirements_dir = self.wiki_root / "app-requirements"
        requirements_dir.mkdir(parents=True, exist_ok=True)
        (requirements_dir / "F-001-backend.md").write_text(
            "---\nfeature-id: F-001\napp: backend\nstatus: pending\n---\n\n## Acceptance criteria\n- Data is prepared.\n",
            encoding="utf-8",
        )
        (requirements_dir / "F-001-mobile-ios.md").write_text(
            "---\nfeature-id: F-001\napp: mobile-ios\nstatus: pending\n---\n\n## API surface\nSee [shared](../api-contracts/SHARED.md).\n",
            encoding="utf-8",
        )
        api = self.wiki_root / "api-contracts" / "SHARED.md"
        api.parent.mkdir(parents=True, exist_ok=True)
        api.write_text(
            "---\nfeature-id: F-999\nversion: 1\nstatus: draft\n---\n\n## Endpoints\nGET /shared\n",
            encoding="utf-8",
        )
        (self.wiki_root / "personas").mkdir(parents=True, exist_ok=True)
        (self.wiki_root / "personas" / "operator.md").write_text(
            "---\nid: P-001\nname: Operator\nsources: []\n---\n",
            encoding="utf-8",
        )

        no_api = build_transition_preflight(self.root, "F-001", action="dev-start")["facts"]["transition"]
        self.assertEqual("ready", no_api["classification"])
        self.assertEqual("pass", next(check for check in no_api["checks"] if check["code"] == "api-contract")["status"])

        feature_with_api = body.replace(
            "See [the persona](../personas/operator.md) for context.",
            "## API surface\nSee [shared](../api-contracts/SHARED.md) for the endpoint.\n\nSee [the persona](../personas/operator.md) for context.",
        )
        technical = self.wiki_root / "technical-design" / "F-001-payout-summary.md"
        technical.parent.mkdir(parents=True, exist_ok=True)
        technical.write_text(technical_design_page(), encoding="utf-8")
        feature_with_api = with_tracks(feature_with_api, DesignTracks("not-applicable", "done", "No app in scope has a UI.", None))
        self._write_feature(status="ready-for-dev", owner="dev", advisory="done", body=feature_with_api)
        linked = build_transition_preflight(self.root, "F-001", action="dev-start")["facts"]["transition"]
        self.assertEqual("blocked", linked["classification"])
        self.assertEqual("blocked", next(check for check in linked["checks"] if check["code"] == "api-contract")["status"])

    def test_advisory_required_actions_block_development_but_deferred_actions_do_not(self) -> None:
        self._write_all_capabilities()
        body = FEATURE_TEMPLATE.format(
            feature_id="F-001",
            title="Payout summary",
            status="in-design",
            owner="tech-lead",
            platforms="backend",
            advisory="done",
            advisory_reason="",
        )
        body = with_tracks(body, SETTLED)
        self._write_feature(status="in-design", owner="tech-lead", advisory="done", body=body)
        advisory = self.wiki_root / "advisory" / "F-001-review.md"
        advisory.parent.mkdir(parents=True, exist_ok=True)
        advisory.write_text(
            "---\nfeature-id: F-001\nreviewed: 2026-09-08\nboard-members-consulted: [Reviewer]\n---\n\n"
            "## Actions required before dev starts\n"
            "- [ ] Confirm the settlement threshold with PO.\n\n"
            "## Actions that can be deferred\n"
            "- Add metrics after launch.\n",
            encoding="utf-8",
        )
        blocked = build_transition_preflight(self.root, "F-001", action="design-handoff")["facts"]["transition"]
        self.assertEqual("blocked", blocked["classification"])
        self.assertEqual("blocked", next(check for check in blocked["checks"] if check["code"] == "advisory-actions")["status"])

        advisory.write_text(
            advisory.read_text(encoding="utf-8").replace("- [ ] Confirm", "- [x] Confirm"),
            encoding="utf-8",
        )
        ready = build_transition_preflight(self.root, "F-001", action="design-handoff")["facts"]["transition"]
        self.assertEqual("ready", ready["classification"])
        self.assertEqual("pass", next(check for check in ready["checks"] if check["code"] == "advisory-actions")["status"])

    def test_design_handoff_is_blocked_by_open_design_stage_questions_but_not_by_a_dev_question(self) -> None:
        self._write_all_capabilities()

        def preflight_with_question(owner: str) -> dict:
            body = FEATURE_TEMPLATE.format(
                feature_id="F-001",
                title="Payout summary",
                status="in-design",
                owner="tech-lead",
                platforms="backend",
                advisory="not-needed",
                advisory_reason="",
            ).replace(
                "|---|----------|-------|--------|\n",
                "|---|----------|-------|--------|\n"
                f"| 1 | Which settlement threshold applies? | {owner} | open |\n",
            )
            body = with_tracks(body, SETTLED)
            self._write_feature(status="in-design", owner="tech-lead", body=body)
            return build_transition_preflight(self.root, "F-001", action="design-handoff")["facts"]["transition"]

        for owner in ("po", "designer", "tech-lead"):
            with self.subTest(owner=owner):
                blocked = preflight_with_question(owner)
                self.assertEqual("blocked", blocked["classification"])
                self.assertEqual("blocked", next(check for check in blocked["checks"] if check["code"] == "open-questions")["status"])
        ready = preflight_with_question("dev")
        self.assertEqual("ready", ready["classification"])
        self.assertEqual("pass", next(check for check in ready["checks"] if check["code"] == "open-questions")["status"])

        # The guidance says the same: only po and designer questions block the handoff.
        for relative in (".agents/skills/design-handoff/SKILL.md", ".claude/commands/design-handoff.md"):
            with self.subTest(guidance=relative):
                text = " ".join((self.root / relative).read_text(encoding="utf-8").split())
                self.assertIn("owned by `dev` does not block", text)
                self.assertIn("`po`, `designer` or `tech-lead`", text)
                self.assertNotIn("route the question with", text)

    def test_advisory_examples_in_comments_or_fences_cannot_satisfy_required_actions(self) -> None:
        examples = [
            """## Actions required before dev starts
<!--
- [x] Example action from a review template.
-->""",
            """## Actions required before dev starts
```markdown
- [x] Example action from a review template.
```""",
        ]
        for body in examples:
            with self.subTest(body=body):
                pending, errors = parse_advisory_required_actions(body)
                self.assertEqual([], pending)
                self.assertTrue(errors)

        pending, errors = parse_advisory_required_actions(
            """## Actions required before dev starts
- [x] Confirm the visible action.
<!--
- [ ] Ignore this commented example.
-->"""
        )
        self.assertEqual([], pending)
        self.assertEqual([], errors)

    def test_delivery_evidence_ignores_examples_and_rejects_ambiguous_tables(self) -> None:
        header = "| App | Artifact | Contract | Implementation | Tests | Basis |"
        divider = "|---|---|---|---|---|---|"
        row = "| backend | `build:backend#1` | none | src | passed | checked |"
        cases = [
            f"## Delivery evidence\n```markdown\n{header}\n{divider}\n{row}\n```",
            f"## Delivery evidence\n<!--\n{header}\n{divider}\n{row}\n-->",
        ]
        for body in cases:
            with self.subTest(body=body):
                rows, errors = parse_delivery_rows(body)
                self.assertEqual(([], []), (rows, errors))
        bad = [
            f"## Delivery evidence\n{header}\n{divider}\n{row} extra |",
            f"## Delivery evidence\n| App | Artifact | Contract | Implementation | Tests |\n|---|---|---|---|---|\n| backend | `build:b#1` | none | src | passed |",
            f"## Delivery evidence\n{header}\n{divider}\n| backend | main | none | src | passed | checked |",
            f"## Delivery evidence\n{header}\n{divider}\n| backend | `build:b#1` | none | src | passed | maybe |",
        ]
        for body in bad:
            with self.subTest(body=body):
                _rows, errors = parse_delivery_rows(body)
                self.assertTrue(errors)

    def test_ready_preflight_is_copy_only_and_uses_canonical_id(self) -> None:
        before = {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()}

        envelope = build_transition_preflight(self.root, "F-001")

        transition = envelope["facts"]["transition"]
        self.assertEqual("po-handoff", envelope["facts"]["requested_action"])
        self.assertEqual("ready", transition["classification"])
        self.assertTrue(transition["supported"])
        self.assertEqual("ready-for-design", transition["target_status"])
        self.assertEqual("$po-handoff F-001", transition["invocations"]["codex"])
        self.assertEqual("/po-handoff F-001", transition["invocations"]["claude"])
        self.assertEqual(["po-handoff"], envelope["facts"]["transition_capability"]["supported_actions"])
        after = {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        self.assertEqual(before, after)

    def test_repository_capability_templates_are_detected_on_both_surfaces(self) -> None:
        for relative in CAPABILITY_FILES.values():
            template_path = REPO_ROOT / "template" / Path(f"{relative.as_posix()}.jinja")
            generated_path = self.root / relative
            generated_path.write_text(template_path.read_text(encoding="utf-8"), encoding="utf-8")

        envelope = build_transition_preflight(self.root, "F-001")
        capability = envelope["facts"]["transition_capability"]
        surfaces = {surface["role"]: surface for surface in capability["surfaces"] if surface["action"] == "po-handoff"}

        self.assertTrue(surfaces["codex"]["available"])
        self.assertTrue(surfaces["claude"]["available"])
        self.assertEqual({"codex", "claude"}, set(envelope["facts"]["transition"]["invocations"]))

    def test_missing_optional_capability_surface_does_not_block_available_surface(self) -> None:
        (self.root / CAPABILITY_FILES["claude"]).unlink()

        envelope = build_transition_preflight(self.root, "F-001")

        transition = envelope["facts"]["transition"]
        self.assertEqual("ready", transition["classification"])
        self.assertTrue(transition["supported"])
        self.assertEqual({"codex"}, set(transition["invocations"]))
        surfaces = {
            surface["role"]: surface
            for surface in envelope["facts"]["transition_capability"]["surfaces"]
            if surface["action"] == "po-handoff"
        }
        self.assertTrue(surfaces["codex"]["available"])
        self.assertFalse(surfaces["claude"]["available"])

    def test_pending_advisory_and_open_po_question_block_without_losing_action_mapping(self) -> None:
        body = FEATURE_TEMPLATE.format(
            feature_id="F-001",
            title="Payout summary",
            status="specified",
            owner="po",
            platforms="backend",
            advisory="pending",
            advisory_reason="",
        ).replace(
            "|---|----------|-------|--------|\n\n## App scope",
            "|---|----------|-------|--------|\n| 1 | Which period is authoritative? | po | open |\n\n## App scope",
        )
        self._write_feature(body=body, advisory="pending")

        transition = build_transition_preflight(self.root, "F-001")["facts"]["transition"]

        self.assertEqual("blocked", transition["classification"])
        self.assertTrue(transition["supported"])
        self.assertEqual("po-handoff", transition["action"])
        statuses = {check["code"]: check["status"] for check in transition["checks"]}
        self.assertEqual("blocked", statuses["open-questions"])
        self.assertEqual("review", statuses["advisory-review"])

    def test_empty_acceptance_and_mismatched_platform_scope_are_blocked(self) -> None:
        body = FEATURE_TEMPLATE.format(
            feature_id="F-001",
            title="Payout summary",
            status="specified",
            owner="po",
            platforms="backend",
            advisory="not-needed",
            advisory_reason="",
        ).replace(
            "- [ ] AC-1 [backend] The summary includes the selected payout period.\n- [ ] AC-2 [backend] The summary can be reviewed before it is handed off.",
            "",
        ).replace(
            "- **backend**: The backend prepares the summary data.",
            "- **mobile-ios**: The iOS app prepares the summary.",
        )
        self._write_feature(body=body)

        transition = build_transition_preflight(self.root, "F-001")["facts"]["transition"]

        self.assertEqual("blocked", transition["classification"])
        statuses = {check["code"]: check["status"] for check in transition["checks"]}
        self.assertEqual("blocked", statuses["acceptance-criteria"])
        self.assertEqual("blocked", statuses["app-section"])

    def test_invalid_frontmatter_values_are_unknown_and_feature_is_retained(self) -> None:
        body = FEATURE_TEMPLATE.format(
            feature_id="F-001",
            title="Payout summary",
            status="null",
            owner="[]",
            platforms="backend",
            advisory="not-needed",
            advisory_reason="",
        ).replace("status: null", "status: null").replace("owner: []", "owner: []")
        self._write_feature(body=body, status="null", owner="[]")

        envelope = build_transition_preflight(self.root, "F-001")
        transition = envelope["facts"]["transition"]

        self.assertEqual("unknown", transition["classification"])
        self.assertFalse(transition["supported"])
        self.assertIsNone(transition["action"])
        self.assertIsNotNone(envelope["facts"]["feature"])

    def test_unsupported_stage_has_explicit_gap_without_fabricated_completeness_checks(self) -> None:
        self._write_feature(status="ready-for-design", owner="tech-lead")

        transition = build_transition_preflight(self.root, "F-001")["facts"]["transition"]

        self.assertEqual("unknown", transition["classification"])
        self.assertFalse(transition["supported"])
        self.assertIsNone(transition["action"])
        self.assertEqual(
            {"feature-id", "unsupported-source-stage", "source-owner", "workspace-identity"},
            {check["code"] for check in transition["checks"]},
        )

    def test_feature_scope_is_subset_of_workspace_scope(self) -> None:
        (self.root / "mobile-ios").mkdir()
        manifest = self.root / "prism.workspace.yml"
        manifest.write_text(
            manifest_text("Transition test", ["backend", "mobile-ios"], slug="transition-test"),
            encoding="utf-8",
        )
        self._write_feature(platforms="backend")
        ready = build_transition_preflight(self.root, "F-001")["facts"]["transition"]
        self.assertEqual("ready", ready["classification"])

        self._write_feature(platforms="web-user-app")
        blocked = build_transition_preflight(self.root, "F-001")["facts"]["transition"]
        self.assertEqual("blocked", blocked["classification"])
        self.assertTrue(any(check["code"] == "app-scope" and check["status"] == "blocked" for check in blocked["checks"]))

    def test_duplicate_canonical_ids_are_unknown(self) -> None:
        self._write_feature(filename="F-001-another.md")

        envelope = build_transition_preflight(self.root, "F-001")

        self.assertEqual("unknown", envelope["facts"]["transition"]["classification"])
        self.assertIn("duplicate-feature-id", {diagnostic["code"] for diagnostic in envelope["diagnostics"]})

    def test_mixed_case_duplicate_id_blocks_graph_and_preflight(self) -> None:
        self._write_feature(feature_id="f-001", filename="F-001-alias.md")

        preflight = build_transition_preflight(self.root, "F-001")
        self.assertEqual("unknown", preflight["facts"]["transition"]["classification"])

        graph = build_graph(self.root)
        canonical_node = next(
            node
            for node in graph["facts"]["nodes"]
            if node["type"] == "feature" and node["transitions"] and node["transitions"][0]["feature_id"] == "F-001"
        )
        self.assertEqual("unknown", canonical_node["transitions"][0]["classification"])
        self.assertFalse(canonical_node["transitions"][0]["supported"])

    def test_codex_capability_requires_real_dollar_invocation(self) -> None:
        codex_path = self.root / CAPABILITY_FILES["codex"]
        codex_path.write_text(
            "<!-- prism:po-handoff-contract:v2 -->\n"
            "The argument shape is F-XXX, but no command invocation is provided.\n",
            encoding="utf-8",
        )

        envelope = build_transition_preflight(self.root, "F-001")
        transition = envelope["facts"]["transition"]
        surfaces = {
            surface["role"]: surface
            for surface in envelope["facts"]["transition_capability"]["surfaces"]
            if surface["action"] == "po-handoff"
        }

        self.assertFalse(surfaces["codex"]["available"])
        self.assertEqual("unknown", next(check for check in transition["checks"] if check["code"] == "capability-codex")["status"])
        self.assertNotIn("codex", transition.get("invocations", {}))
        self.assertEqual({"claude"}, set(transition["invocations"]))

    def test_observed_at_cache_is_stable_and_bounded(self) -> None:
        from prism_cli import wiki_transitions

        replacement: OrderedDict[str, str] = OrderedDict()
        entries = (("snapshot", "stable"),)
        key = fingerprint_digest(entries)
        with patch.object(wiki_transitions, "_OBSERVED_AT_BY_FINGERPRINT", replacement):
            with patch.object(wiki_transitions, "datetime") as mocked_datetime:
                mocked_datetime.now.side_effect = [
                    datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc),
                    datetime(2026, 9, 8, 12, 1, tzinfo=timezone.utc),
                ]
                first = wiki_transitions._observed_at(entries)
                second = wiki_transitions._observed_at(entries)
                mocked_datetime.now.assert_called_once_with()
            self.assertEqual(first, second)
            self.assertEqual(1, len(replacement))

            for index in range(_OBSERVED_AT_CACHE_LIMIT + 1):
                wiki_transitions._observed_at((("eviction", str(index)),))

            self.assertLessEqual(len(replacement), _OBSERVED_AT_CACHE_LIMIT)
            self.assertNotIn(key, replacement)

    def test_missing_schema_or_index_is_relevant_to_the_selected_feature(self) -> None:
        (self.wiki_root / "SCHEMA.md").unlink()

        transition = build_transition_preflight(self.root, "F-001")["facts"]["transition"]

        self.assertEqual("unknown", transition["classification"])
        self.assertTrue(any(check["code"] == "source-integrity" or check["code"].startswith("source-integrity:") for check in transition["checks"]))

    def test_source_change_during_outer_read_marks_snapshot_inconsistent(self) -> None:
        original_reader = read_feature_pages
        changed = False

        def reader(path: Path):
            nonlocal changed
            pages = original_reader(path)
            if not changed:
                changed = True
                self.feature_path.write_text(
                    self.feature_path.read_text(encoding="utf-8").replace("payout summary", "changed payout summary"),
                    encoding="utf-8",
                )
            return pages

        with patch("prism_cli.wiki_transitions.read_feature_pages", side_effect=reader):
            envelope = build_transition_preflight(self.root, "F-001")

        self.assertFalse(envelope["facts"]["transition_capability"]["snapshot"]["consistent"])
        self.assertEqual("unknown", envelope["facts"]["transition"]["classification"])
        self.assertIn("transition-source-changed", {diagnostic["code"] for diagnostic in envelope["diagnostics"]})

    def test_source_change_during_envelope_assembly_invalidates_preflight(self) -> None:
        from prism_cli import wiki_transitions

        original_builder = wiki_transitions.build_envelope
        changed = False

        def builder(*args, **kwargs):
            nonlocal changed
            envelope = original_builder(*args, **kwargs)
            if not changed:
                changed = True
                self.feature_path.write_text(
                    self.feature_path.read_text(encoding="utf-8").replace("payout summary", "late payout summary"),
                    encoding="utf-8",
                )
            return envelope

        with patch("prism_cli.wiki_transitions.build_envelope", side_effect=builder):
            envelope = build_transition_preflight(self.root, "F-001")

        self.assertFalse(envelope["facts"]["transition_capability"]["snapshot"]["consistent"])
        self.assertEqual("unknown", envelope["facts"]["transition"]["classification"])
        self.assertIn("transition-source-changed", {diagnostic["code"] for diagnostic in envelope["diagnostics"]})

    def test_source_change_during_graph_edge_read_invalidates_graph_transition(self) -> None:
        from prism_cli import wiki_graph

        original_collector = wiki_graph._collect_edges
        changed = False

        def collector(*args, **kwargs):
            nonlocal changed
            result = original_collector(*args, **kwargs)
            if not changed:
                changed = True
                self.feature_path.write_text(
                    self.feature_path.read_text(encoding="utf-8").replace("payout summary", "late payout summary"),
                    encoding="utf-8",
                )
            return result

        with patch("prism_cli.wiki_graph._collect_edges", side_effect=collector):
            envelope = build_graph(self.root)

        feature_nodes = [node for node in envelope["facts"]["nodes"] if node["type"] == "feature"]
        self.assertEqual(1, len(feature_nodes))
        self.assertEqual("unknown", feature_nodes[0]["transitions"][0]["classification"])
        self.assertFalse(envelope["facts"]["transition_capability"]["snapshot"]["consistent"])

    def _add_features(self, count: int) -> None:
        for number in range(2, count + 2):
            self._write_feature(feature_id=f"F-{number:03d}", filename=f"F-{number:03d}-payout-summary.md")

    def test_lint_resolves_each_path_once_per_call(self) -> None:
        self._add_features(5)
        real_resolve = Path.resolve
        resolved: Counter[str] = Counter()

        def counting_resolve(path: Path, *args: object, **kwargs: object) -> Path:
            resolved[str(path)] += 1
            return real_resolve(path, *args, **kwargs)

        with patch.object(Path, "resolve", counting_resolve):
            result = lint_wiki(self.root)

        self.assertEqual({}, {path: count for path, count in resolved.items() if count > 1})
        self.assertEqual(result.to_dict()["diagnostics"], lint_wiki(self.root).to_dict()["diagnostics"])

    def test_lint_resolve_memo_is_local_to_one_call(self) -> None:
        lint_wiki(self.root)
        self.assertIsNone(wiki_lint._RESOLVE_MEMO.get())
        with patch("prism_cli.wiki_lint.read_wiki_pages", side_effect=RuntimeError("stop")):
            with self.assertRaises(RuntimeError):
                lint_wiki(self.root)
        self.assertIsNone(wiki_lint._RESOLVE_MEMO.get())

    def _count_required_file_reads(self) -> tuple[Counter[str], int]:
        real_read_text = Path.read_text
        reads: Counter[str] = Counter()

        def counting_read_text(path: Path, *args: object, **kwargs: object) -> str:
            if path.name in {"SCHEMA.md", "LIFECYCLE.md", "ACTIONS.md", "index.md", "status-board.md"} and kwargs.get("encoding") == "utf-8-sig":
                reads[path.name] += 1
            return real_read_text(path, *args, **kwargs)

        with patch.object(Path, "read_text", counting_read_text):
            evaluation = evaluate_transition_summaries(self.root)
        return reads, len(evaluation.transitions_by_path)

    def test_required_wiki_files_are_read_a_fixed_number_of_times_per_evaluation(self) -> None:
        one_feature, count_one = self._count_required_file_reads()
        self._add_features(5)
        six_features, count_six = self._count_required_file_reads()

        self.assertEqual((1, 6), (count_one, count_six))
        self.assertEqual(one_feature, six_features, "Reads of SCHEMA.md, LIFECYCLE.md, ACTIONS.md, index.md and status-board.md must not grow with the feature count.")

    def test_unreadable_required_wiki_file_still_blocks_every_feature(self) -> None:
        self._add_features(2)
        (self.wiki_root / "SCHEMA.md").write_bytes(bytes([0xFF, 0xFE, 0x00]) + b" not utf-8")

        evaluation = evaluate_transition_summaries(self.root)

        self.assertEqual(3, len(evaluation.transitions_by_path))
        for transition in evaluation.transitions_by_path.values():
            codes = {check["code"] for check in transition["checks"]}
            self.assertIn("source-integrity:unreadable-required-wiki-file", codes)

    def test_fingerprint_includes_capability_files(self) -> None:
        before = workspace_fingerprint(self.root)
        path = self.root / CAPABILITY_FILES["codex"]
        path.write_text(path.read_text(encoding="utf-8") + "revision\n", encoding="utf-8")

        self.assertNotEqual(before, workspace_fingerprint(self.root))

    def test_fingerprint_changes_when_calendar_day_rolls_over(self) -> None:
        before = workspace_fingerprint(self.root)

        self.clock.today.return_value = CHECK_DATE + timedelta(days=1)

        self.assertNotEqual(before, workspace_fingerprint(self.root))

    def test_cli_exposes_read_only_transition_preflight_json(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["wiki", "transition-preflight", "F-001", str(self.root), "--json"])
        output = StringIO()
        with redirect_stdout(output):
            exit_code = args.func(args)

        self.assertEqual(0, exit_code)
        payload = json.loads(output.getvalue())
        self.assertEqual("wiki transition-preflight", payload["command"])
        self.assertEqual("F-001", payload["facts"]["transition"]["feature_id"])


class FingerprintCacheTests(unittest.TestCase):
    """The poller's stat-gated fingerprint must never hide an edit for longer than its documented bounds."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.features = self.root / "knowledge" / "wiki" / "features"
        self.features.mkdir(parents=True)
        self.now_ns = time.time_ns()
        self.monotonic = 1000.0
        self.cache = FingerprintCache(wall_clock_ns=lambda: self.now_ns, monotonic=lambda: self.monotonic)
        self.pages = [self.features / f"F-00{number}-page.md" for number in range(1, 4)]
        for page in self.pages:
            self.write(page, f"alpha {page.name}\n")
        self.write(self.root / "knowledge" / "wiki" / "index.md", "# Index\n")
        self.write(self.root / "prism.workspace.yml", "schema_version: 2\n")
        self.hashed: list[str] = []
        from prism_cli import wiki_transitions

        real = wiki_transitions._file_fingerprint

        def recording(path: Path) -> str:
            self.hashed.append(path.name)
            return real(path)

        patcher = patch("prism_cli.wiki_transitions._file_fingerprint", recording)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, path: Path, text: str, *, age_seconds: float = 3600.0) -> None:
        path.write_text(text, encoding="utf-8", newline="\n")
        self.set_mtime(path, age_seconds)

    def set_mtime(self, path: Path, age_seconds: float) -> None:
        modified = self.now_ns - int(age_seconds * 1_000_000_000)
        os.utime(path, ns=(modified, modified))

    def scan(self) -> tuple[tuple[str, str], ...]:
        self.hashed.clear()
        return workspace_fingerprint(self.root, cache=self.cache)

    def test_cached_fingerprint_equals_the_full_fingerprint_and_skips_unchanged_files(self) -> None:
        full = workspace_fingerprint(self.root)
        self.assertEqual(5, len(self.hashed))
        first = self.scan()
        hashed_first = len(self.hashed)
        second = self.scan()

        self.assertEqual(full, first)
        self.assertEqual(full, second)
        self.assertEqual(5, hashed_first)
        self.assertEqual([], self.hashed)

    def test_edit_that_changes_content_and_size_is_detected_on_the_next_scan(self) -> None:
        before = self.scan()
        self.write(self.pages[0], "alpha with a longer body\n")

        after = self.scan()
        hashed = list(self.hashed)

        self.assertNotEqual(before, after)
        self.assertEqual(workspace_fingerprint(self.root), after)
        self.assertEqual([self.pages[0].name], hashed)

    def test_edit_that_keeps_the_size_but_changes_the_modification_time_is_detected(self) -> None:
        before = self.scan()
        original = self.pages[1].read_text(encoding="utf-8")
        self.write(self.pages[1], original.replace("alpha", "bravo"), age_seconds=1800.0)
        self.assertEqual(len(original), len(self.pages[1].read_text(encoding="utf-8")))

        after = self.scan()

        self.assertNotEqual(before, after)
        self.assertEqual(workspace_fingerprint(self.root), after)

    def test_edit_that_keeps_size_and_modification_time_is_caught_by_the_backstop(self) -> None:
        before = self.scan()
        original = self.pages[2].read_text(encoding="utf-8")
        self.write(self.pages[2], original.replace("alpha", "bravo"))  # same size, same timestamp as before
        self.assertEqual(len(original), len(self.pages[2].read_text(encoding="utf-8")))

        self.monotonic += FingerprintCache.FULL_REHASH_SECONDS - 1
        self.assertEqual(before, self.scan(), "Inside the backstop interval the stat gate trusts the unchanged signature.")
        self.assertEqual([], self.hashed)

        self.monotonic += 1
        after = self.scan()
        hashed = list(self.hashed)
        self.assertNotEqual(before, after)
        self.assertEqual(workspace_fingerprint(self.root), after)
        self.assertEqual(5, len(hashed), "The backstop rehashes every file.")

        self.assertEqual(after, self.scan())
        self.assertEqual([], self.hashed, "The next scan is gated again.")

    def test_files_inside_the_racy_window_are_rehashed_until_they_age_out(self) -> None:
        racy = self.features / "F-009-racy.md"
        self.write(racy, "alpha racy\n", age_seconds=0.5)
        first = self.scan()
        self.assertIn("F-009-racy.md", self.hashed)

        # Same size, same timestamp tick as the first hash: only the racy rule can see it.
        self.write(racy, "bravo racy\n", age_seconds=0.5)
        second = self.scan()
        self.assertNotEqual(first, second)
        self.assertIn("F-009-racy.md", self.hashed)

        self.now_ns += 10 * 1_000_000_000
        self.scan()
        self.assertIn("F-009-racy.md", self.hashed, "The first hash taken after the window is stored.")
        self.scan()
        self.assertNotIn("F-009-racy.md", self.hashed, "Once it was hashed outside the window it is gated.")

    def test_deleted_and_new_files_are_reflected(self) -> None:
        before = self.scan()
        self.pages[0].unlink()
        extra = self.features / "F-010-new.md"
        self.write(extra, "alpha new\n")

        after = self.scan()
        hashed = list(self.hashed)

        self.assertNotEqual(before, after)
        self.assertEqual(workspace_fingerprint(self.root), after)
        self.assertEqual(["F-010-new.md"], hashed)

    def test_calendar_day_rollover_still_invalidates_a_cached_scan(self) -> None:
        before = self.scan()
        with patch("prism_cli.wiki_transitions.date") as clock:
            clock.today.return_value = date(2999, 1, 1)
            after = self.scan()

        self.assertNotEqual(before, after)
        self.assertEqual("2999-01-01", dict(after)["today"])

    def test_unreadable_files_are_not_cached(self) -> None:
        self.scan()
        with patch("prism_cli.wiki_transitions._file_fingerprint", return_value="unreadable"):
            self.monotonic += FingerprintCache.FULL_REHASH_SECONDS
            self.scan()
        self.hashed.clear()
        self.scan()
        self.assertEqual(5, len(self.hashed))

    def test_default_fingerprint_never_consults_a_cache(self) -> None:
        with patch.object(FingerprintCache, "file_fingerprint", side_effect=AssertionError("cache used")):
            first = workspace_fingerprint(self.root)
            second = workspace_fingerprint(self.root)

        self.assertEqual(first, second)
        self.assertEqual(10, len(self.hashed), "Without a cache every call hashes every file.")


if __name__ == "__main__":
    unittest.main()
