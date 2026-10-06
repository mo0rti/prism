"""Per-app delivery evidence, app retirement and the API-serving app rule."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import yaml

from prism_cli.app_cli import IDENTITY_NOTICE, plan_app_retire
from prism_cli.board_reads import query
from prism_cli.board_service import BoardError, BoardService
from prism_cli.wiki_graph import build_graph, render_mermaid
from prism_cli.wiki_lint import lint_wiki
from prism_cli.wiki_model import DeliveryProblem, parse_delivery_evidence, release_evidence_problem
from prism_cli.wiki_transitions import ACTION_SPECS, build_transition_preflight
from prism_cli.workspace import MANIFEST_FILE, load_workspace
from tests import app_model_baseline
from tests import real_temp  # noqa: F401
from tests import test_feature_scope_apps as scope
from tests.test_app_model_workspace import declare_two_apps, install_workflow
from tests.test_apps_surfaces import run_cli, run_json


URL = "https://example.com/releases/1.4.0"

ACCEPTED_RELEASE_CELLS = {
    "release": f"release: {URL}",
    "release, upper case": f"RELEASE: {URL}",
    "release, no space after the colon": f"Release:{URL}",
    "tag": "tag: https://github.com/acme/app/releases/tag/v1.4.0",
    "deployment url": "deployment: https://deploy.example.com/runs/812",
    "deployment record in the workspace": "deployment: knowledge/evidence/deploy-2026-10-01.md",
    "release with a Markdown link": "release: [v1.4.0](https://example.com/releases/v1.4.0) deployed to production",
    "attestation": "attested by Ada Lovelace: https://example.com/checks/prod-smoke",
    "attestation, mixed case": "Attested By Ada Lovelace: knowledge/evidence/ada-smoke-check.md",
    "attestation that links what was checked": "attested by Ada Lovelace: https://github.com/acme/app/pull/42",
}

REJECTED_RELEASE_CELLS = {
    "short commit SHA": "3f9c2ab",
    "full commit SHA": "3f9c2ab4d5e6f708192a3b4c5d6e7f8091a2b3c4",
    "pull request URL": "https://github.com/acme/app/pull/42",
    "merge request URL": "https://gitlab.com/acme/app/-/merge_requests/42",
    "GitHub merge URL": "https://github.com/acme/app/pull/42/merge",
    "commit URL": "https://github.com/acme/app/commit/3f9c2ab4d5e6f7",
    "merged": "merged",
    "free text": "Version 1.4.0 deployed to production",
    "branch name": "main",
    "n/a": "n/a",
    "template cell": "[release artifact or target]",
    "empty cell": "",
    "prefix without a reference": "release:",
    "release that links a pull request": "release: https://github.com/acme/app/pull/42",
    "release that names a commit": "release: 3f9c2ab",
    "release with free text": "release: shipped",
    "tag name only": "tag: v1.4.0",
    "absolute path": "release: /etc/releases/1.md",
    "parent path": "release: ../releases/1.md",
    "file URL": "release: file:///srv/releases/1.md",
    "attestation without a name": "attested by : https://example.com/checks/prod-smoke",
    "attestation without a reference": "attested by Ada Lovelace",
    "attestation that names a commit": "attested by Ada Lovelace: 3f9c2ab",
}


def evidence_section(rows: dict[str, str], *, implementation: str = "Pull request 42 merged", tests: str = "CI run 1187 passed") -> str:
    lines = ["## Delivery evidence", "| App | Implementation | Tests | Release |", "|---|---|---|---|"]
    lines.extend(f"| {app} | {implementation} | {tests} | {release} |" for app, release in rows.items())
    return "\n".join(lines) + "\n"


def snapshot(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


class ReleaseCellTests(unittest.TestCase):
    def test_each_accepted_form_is_release_evidence_or_an_attestation(self) -> None:
        for name, cell in ACCEPTED_RELEASE_CELLS.items():
            with self.subTest(form=name):
                self.assertIsNone(release_evidence_problem(cell))
                rows, problems = parse_delivery_evidence(evidence_section({"backend": cell}), ["backend"])
                self.assertEqual([], problems)
                self.assertEqual(cell, rows["backend"]["release"])

    def test_each_rejected_form_gets_the_release_code_and_the_shipment_message(self) -> None:
        for name, cell in REJECTED_RELEASE_CELLS.items():
            with self.subTest(form=name):
                self.assertIsNotNone(release_evidence_problem(cell))
                _rows, problems = parse_delivery_evidence(evidence_section({"backend": cell}), ["backend"])
                self.assertEqual(["release-evidence-required"], [problem.code for problem in problems])
                self.assertIsInstance(problems[0], DeliveryProblem)
                self.assertIn("`backend`", problems[0].message)
                self.assertIn("proves which code changed, not that it shipped", problems[0].message)
                self.assertIn("attested by <Name>", problems[0].message)

    def test_the_implementation_and_tests_cells_keep_their_rule(self) -> None:
        _rows, problems = parse_delivery_evidence(evidence_section({"backend": f"release: {URL}"}, implementation="n/a"), ["backend"])
        self.assertEqual([("delivery-evidence", "Delivery evidence `implementation` for `backend` is empty or still a placeholder.")], [(p.code, p.message) for p in problems])
        _rows, problems = parse_delivery_evidence(evidence_section({"backend": f"release: {URL}"}, tests="[test command and result]"), ["backend"])
        self.assertEqual(["delivery-evidence"], [problem.code for problem in problems])
        # A pull request or commit stays a fine Implementation reference.
        _rows, problems = parse_delivery_evidence(evidence_section({"backend": f"release: {URL}"}, implementation="https://github.com/acme/app/pull/42"), ["backend"])
        self.assertEqual([], problems)

    def test_a_row_for_every_app_in_scope_is_still_required(self) -> None:
        _rows, problems = parse_delivery_evidence(evidence_section({"backend": f"release: {URL}"}), ["backend", "web-user-app"])
        self.assertEqual([("delivery-evidence", "Delivery evidence is missing declared app(s): web-user-app.")], [(p.code, p.message) for p in problems])


class ReleaseCellSurfaceTests(scope.WikiWorkspaceCase):
    """The same Release rule in lint, in the dev-done transition check and in the board's validation."""

    def write_done(self, release: str) -> None:
        path = self.write_feature(["customer-android"], status="done", owner="none")
        path.write_text(path.read_text(encoding="utf-8") + "\n" + evidence_section({"customer-android": release}), encoding="utf-8")

    def write_in_dev(self, release: str) -> None:
        path = self.write_feature(["customer-android"], status="in-dev", owner="dev")
        path.write_text(path.read_text(encoding="utf-8") + "\n" + evidence_section({"customer-android": release}), encoding="utf-8")

    def test_lint_applies_the_rule_to_a_done_feature(self) -> None:
        self.write_requirement("customer-android", "done")
        self.write_design()
        for name, cell in ACCEPTED_RELEASE_CELLS.items():
            with self.subTest(accepted=name):
                self.write_done(cell)
                result = self.lint()
                self.assertEqual([], self.with_code(result, "release-evidence-required"))
                self.assertEqual([], self.with_code(result, "done-delivery-evidence"))
        for name, cell in REJECTED_RELEASE_CELLS.items():
            with self.subTest(rejected=name):
                self.write_done(cell)
                found = self.with_code(self.lint(), "release-evidence-required")
                self.assertEqual(1, len(found))
                self.assertEqual("error", found[0].severity)
                self.assertEqual("F-001", found[0].feature_id)
                self.assertIn("not that it shipped", found[0].message)

    def test_lint_leaves_a_feature_before_done_alone(self) -> None:
        self.write_requirement("customer-android")
        self.write_design()
        self.write_in_dev("merged")
        self.assertEqual([], self.with_code(self.lint(), "release-evidence-required"))

    def test_the_dev_done_check_reports_the_code(self) -> None:
        self.write_requirement("customer-android")
        self.write_design()
        for name, cell in ACCEPTED_RELEASE_CELLS.items():
            with self.subTest(accepted=name):
                self.write_in_dev(cell)
                self.assertEqual("pass", self.check("dev-done", "delivery-evidence")["status"])
        for name, cell in REJECTED_RELEASE_CELLS.items():
            with self.subTest(rejected=name):
                self.write_in_dev(cell)
                blocked = self.check("dev-done", "release-evidence-required")
                self.assertEqual("blocked", blocked["status"])
                self.assertIn("proves which code changed, not that it shipped", blocked["message"])
                transition = build_transition_preflight(self.root, "F-001", action="dev-done")["facts"]["transition"]
                self.assertNotEqual("ready", transition["classification"])
                self.assertFalse(any(item["code"] == "delivery-evidence" and item["status"] == "pass" for item in transition["checks"]))

    def test_the_board_rejects_each_rejected_form_and_accepts_each_accepted_one(self) -> None:
        frontmatter = {"apps": ["backend"]}
        for name, cell in REJECTED_RELEASE_CELLS.items():
            with self.subTest(rejected=name), self.assertRaises(BoardError) as caught:
                BoardService._validate_dev_done_evidence("knowledge/wiki/features/F-001.md", f"---\nid: F-001\n---\n\n{evidence_section({'backend': cell})}", frontmatter)
            error = caught.exception
            self.assertEqual(("release_evidence_required", 409), (error.code, error.status))
            self.assertIn("not that it shipped", error.message)
            self.assertEqual(["backend"], error.details["apps"])
            self.assertTrue(error.details["problems"])
        for name, cell in ACCEPTED_RELEASE_CELLS.items():
            with self.subTest(accepted=name):
                BoardService._validate_dev_done_evidence("knowledge/wiki/features/F-001.md", f"---\nid: F-001\n---\n\n{evidence_section({'backend': cell})}", frontmatter)

    def test_a_structural_problem_is_reported_before_the_release_cell(self) -> None:
        with self.assertRaises(BoardError) as caught:
            BoardService._validate_dev_done_evidence(
                "knowledge/wiki/features/F-001.md", f"---\nid: F-001\n---\n\n{evidence_section({'backend': 'merged'}, implementation='n/a')}", {"apps": ["backend"]}
            )
        self.assertEqual("delivery_evidence_invalid", caught.exception.code)
        self.assertIn("(`release:`, `tag:` or `deployment:`", caught.exception.message)


class TwoAppDeliveryTests(scope.WikiWorkspaceCase):
    """Contract section 8, item 3: customer-android in the workspace, partner-android in an external repository."""

    def setUp(self) -> None:
        super().setUp()
        self.write_requirement("customer-android")
        self.write_requirement("partner-android")
        self.write_design()

    def evidence(self, **rows: str) -> None:
        path = self.write_feature(["customer-android", "partner-android"], status="in-dev", owner="dev")
        text = path.read_text(encoding="utf-8")
        path.write_text(text + "\n" + evidence_section({app.replace("_", "-"): release for app, release in rows.items()}), encoding="utf-8")

    def test_dev_done_fails_with_valid_evidence_for_only_one_app(self) -> None:
        self.evidence(customer_android=f"release: {URL}")

        blocked = self.check("dev-done", "delivery-evidence")

        self.assertEqual("blocked", blocked["status"])
        self.assertIn("missing declared app(s): partner-android", blocked["message"])

    def test_dev_done_passes_with_release_evidence_for_one_app_and_an_attestation_for_the_other(self) -> None:
        self.evidence(customer_android=f"release: {URL}", partner_android="attested by Grace Hopper: https://example.com/checks/partner-prod-smoke")

        self.assertEqual("pass", self.check("dev-done", "delivery-evidence")["status"])
        codes = {item["code"] for item in build_transition_preflight(self.root, "F-001", action="dev-done")["facts"]["transition"]["checks"]}
        self.assertNotIn("release-evidence-required", codes)

    def test_dev_done_passes_for_the_external_app_by_url_with_no_local_checkout(self) -> None:
        self.assertFalse((self.root / "prism.local.yml").exists())
        self.evidence(customer_android=f"deployment: {URL}", partner_android="tag: https://git.example.com/acme/mobile-apps/releases/tag/partner-2.0.0")

        self.assertEqual("pass", self.check("dev-done", "delivery-evidence")["status"])
        warnings = [item for item in load_workspace(self.root).diagnostics if item.code == "external-repository-unresolved"]
        self.assertEqual(1, len(warnings), "the unresolved checkout stays one warning and blocks nothing")

    def test_a_pull_request_alone_does_not_ship_the_external_app(self) -> None:
        self.evidence(customer_android=f"release: {URL}", partner_android="https://git.example.com/acme/mobile-apps/pull/7")

        blocked = self.check("dev-done", "release-evidence-required")

        self.assertEqual("blocked", blocked["status"])
        self.assertIn("`partner-android`", blocked["message"])
        self.assertNotIn("`customer-android`", blocked["message"])

    def test_a_done_feature_lints_clean_with_a_valid_row_per_app(self) -> None:
        path = self.write_feature(["customer-android", "partner-android"], status="done", owner="none")
        self.write_requirement("customer-android", "done")
        self.write_requirement("partner-android", "done")
        rows = {"customer-android": f"release: {URL}", "partner-android": "attested by Grace Hopper: https://example.com/checks/partner-prod-smoke"}
        path.write_text(path.read_text(encoding="utf-8") + "\n" + evidence_section(rows), encoding="utf-8")

        result = self.lint()

        self.assertTrue(result.is_clean, [item.to_dict() for item in result.diagnostics if item.severity == "error"])


class ApiServingAppTests(scope.WikiWorkspaceCase):
    API = "GET /summaries returns the payout summary."

    def declare_tool(self, **capabilities: object) -> None:
        self.declare([scope.other_app("tool", **capabilities)])
        self.write_requirement("tool")

    def test_api_work_scoped_only_to_an_app_that_does_not_serve_an_api_fails(self) -> None:
        self.declare_tool(**{"has-ui": False, "serves-api": False})
        self.write_feature(["tool"], api=self.API)

        found = self.with_code(self.lint(), "api-surface-without-api-app")

        self.assertEqual(1, len(found))
        self.assertEqual("error", found[0].severity)
        self.assertIn("`F-001`", found[0].message)
        self.assertIn("`tool` (serves-api: false)", found[0].message)

    def test_an_unknown_capability_counts_as_serving_an_api(self) -> None:
        self.declare_tool(**{"has-ui": False, "serves-api": "unknown"})
        self.write_feature(["tool"], api=self.API)

        self.assertEqual([], self.with_code(self.lint(), "api-surface-without-api-app"))

    def test_adding_an_app_that_serves_an_api_passes(self) -> None:
        self.declare([scope.other_app("tool", **{"has-ui": False, "serves-api": False}), scope.BACKEND])
        self.write_requirement("tool")
        self.write_requirement("backend")
        self.write_feature(["tool", "backend"], api=self.API)

        self.assertEqual([], self.with_code(self.lint(), "api-surface-without-api-app"))

    def test_a_feature_without_api_work_is_unaffected(self) -> None:
        self.declare_tool(**{"has-ui": False, "serves-api": False})
        for api in ("None.", "", "No API changes."):
            with self.subTest(api=api):
                self.write_feature(["tool"], api=api)
                self.assertEqual([], self.with_code(self.lint(), "api-surface-without-api-app"))

    def test_a_done_feature_is_not_flagged(self) -> None:
        self.declare_tool(**{"has-ui": False, "serves-api": False})
        self.write_feature(["tool"], status="done", owner="none", api=self.API)

        self.assertEqual([], self.with_code(self.lint(), "api-surface-without-api-app"))

    def test_a_retired_app_that_serves_an_api_does_not_count(self) -> None:
        self.declare([scope.other_app("tool", **{"has-ui": False, "serves-api": False}), {**scope.BACKEND, "status": "retired"}])
        self.write_feature(["tool", "backend"], api=self.API)

        found = self.with_code(self.lint(), "api-surface-without-api-app")

        self.assertEqual(1, len(found))
        self.assertIn("`backend` (retired)", found[0].message)

    def test_the_design_handoff_dev_start_and_dev_done_checks_block_with_the_code(self) -> None:
        self.declare_tool(**{"has-ui": False, "serves-api": False})
        for action, status, owner in (("design-handoff", "in-design", "designer"), ("dev-start", "ready-for-dev", "dev"), ("dev-done", "in-dev", "dev")):
            with self.subTest(action=action):
                self.write_feature(["tool"], status=status, owner=owner, api=self.API)
                blocked = self.check(action, "api-surface-without-api-app")
                self.assertEqual("blocked", blocked["status"])
                self.assertIn("`tool` (serves-api: false)", blocked["message"])
                self.write_feature(["tool"], status=status, owner=owner, api="None.")
                self.assertEqual("pass", self.check(action, "api-surface-without-api-app")["status"])
        self.declare_tool(**{"has-ui": False, "serves-api": "unknown"})
        self.write_feature(["tool"], status="in-design", owner="designer", api=self.API)
        self.assertEqual("pass", self.check("design-handoff", "api-surface-without-api-app")["status"])

    def test_the_lint_finding_is_not_a_second_unknown_check_on_the_transition(self) -> None:
        self.declare_tool(**{"has-ui": False, "serves-api": False})
        self.write_feature(["tool"], status="in-design", owner="designer", api=self.API)

        transition = build_transition_preflight(self.root, "F-001", action="design-handoff")["facts"]["transition"]

        self.assertEqual("blocked", next(item for item in transition["checks"] if item["code"] == "api-surface-without-api-app")["status"])
        self.assertFalse(any(item["code"].startswith("source-integrity:") for item in transition["checks"]), transition["checks"])


class RetirementWorkspaceCase(scope.WikiWorkspaceCase):
    """customer-android in the workspace, partner-android external, and backend."""

    def retire(self, *extra: str) -> tuple[int, str, str]:
        return run_cli("app", "retire", "partner-android", str(self.root), *extra)

    def flagged(self, result=None) -> list:
        return self.with_code(result or self.lint(), "app-retired-in-scope")

    def write_done_with_history(self) -> None:
        path = self.write_feature(["customer-android", "partner-android"], status="done", owner="none")
        self.write_requirement("customer-android", "done")
        self.write_requirement("partner-android", "done")
        self.write_design()
        rows = {"customer-android": f"release: {URL}", "partner-android": "attested by Grace Hopper: https://example.com/checks/partner-prod-smoke"}
        path.write_text(path.read_text(encoding="utf-8") + "\n" + evidence_section(rows), encoding="utf-8")


class AppRetireCommandTests(RetirementWorkspaceCase):
    def manifest(self) -> dict:
        return yaml.safe_load((self.root / MANIFEST_FILE).read_text(encoding="utf-8"))

    def test_without_apply_it_plans_the_change_and_writes_nothing(self) -> None:
        self.write_feature(["customer-android", "partner-android"], status="in-dev", owner="dev")
        before = snapshot(self.root)

        code, out, err = self.retire()

        self.assertEqual(0, code, err)
        self.assertEqual(before, snapshot(self.root))
        self.assertIn("+  status: retired", out)
        self.assertIn("feature F-001 (in-dev) lists this app and is flagged app-retired-in-scope", out)
        self.assertIn("Retirement never changes a feature's scope by itself.", out)
        self.assertIn(IDENTITY_NOTICE, out)
        self.assertIn("Preview only. Run again with --apply", out)

    def test_the_json_plan_lists_the_change_the_flagged_features_and_the_identity_notice(self) -> None:
        self.write_feature(["customer-android", "partner-android"], status="in-dev", owner="dev")

        plan = run_json("app", "retire", "partner-android", str(self.root), "--json")

        self.assertEqual("app retire", plan["command"])
        self.assertEqual([], plan["conflicts"])
        self.assertEqual({"partner-android"}, {plan["app"]["id"]})
        self.assertEqual("retired", plan["app"]["status"])
        self.assertEqual([{"id": "F-001", "status": "in-dev"}], plan["flagged_features"])
        self.assertTrue(plan["board_identity_changed"])
        self.assertEqual(IDENTITY_NOTICE, plan["notice"])
        self.assertEqual([MANIFEST_FILE], [change["path"] for change in plan["changes"]])

    def test_apply_sets_the_status_and_changes_nothing_else_on_disk(self) -> None:
        self.write_feature(["customer-android", "partner-android"], status="in-dev", owner="dev")
        self.write_requirement("customer-android")
        self.write_requirement("partner-android")
        before = snapshot(self.root)
        manifest_before = self.manifest()

        code, out, err = self.retire("--apply", "--yes")

        self.assertEqual(0, code, err)
        self.assertIn("Retired app `partner-android` in prism.workspace.yml. No code, page, requirement or evidence was deleted.", out)
        self.assertIn(IDENTITY_NOTICE, out)
        after = snapshot(self.root)
        self.assertEqual(set(before), set(after), "no file is created or deleted")
        self.assertEqual([MANIFEST_FILE], [name for name in before if before[name] != after[name]])
        expected = json.loads(json.dumps(manifest_before))
        next(app for app in expected["apps"] if app["id"] == "partner-android")["status"] = "retired"
        self.assertEqual(expected, self.manifest())
        self.assertTrue((self.root / "mobile-android").is_dir(), "the code of an app in this repository stays")

    def test_apply_with_json_returns_a_receipt_with_the_plan(self) -> None:
        receipt = run_json("app", "retire", "partner-android", str(self.root), "--apply", "--yes", "--json")

        self.assertEqual("applied", receipt["status"])
        self.assertEqual("app retire", receipt["command"])
        self.assertEqual("partner-android", receipt["app"]["id"])
        self.assertEqual(IDENTITY_NOTICE, receipt["notice"])
        self.assertEqual([], receipt["plan"]["conflicts"])
        self.assertEqual("retired", next(app for app in self.manifest()["apps"] if app["id"] == "partner-android")["status"])

    def test_an_unknown_app_is_an_error_that_writes_nothing(self) -> None:
        before = snapshot(self.root)

        code, out, err = run_cli("app", "retire", "ghost", str(self.root), "--apply", "--yes")

        self.assertEqual(3, code)
        self.assertIn("`ghost` is not an app of this workspace; the workspace's apps are `customer-android`, `partner-android`, `backend`.", err)
        self.assertNotIn("Retired app", out)
        self.assertNotIn("Preview only", out)
        self.assertEqual(before, snapshot(self.root))
        plan = run_json("app", "retire", "ghost", str(self.root), "--json", allowed=(3,))
        self.assertEqual([], plan["changes"])
        self.assertEqual(1, len(plan["conflicts"]))

    def test_an_already_retired_app_is_an_error_that_writes_nothing(self) -> None:
        self.assertEqual(0, self.retire("--apply", "--yes")[0])
        before = snapshot(self.root)

        code, out, err = self.retire("--apply", "--yes")

        self.assertEqual(3, code)
        self.assertIn("App `partner-android` is already retired.", err)
        self.assertNotIn("Retired app", out)
        self.assertEqual(before, snapshot(self.root))

    def test_apply_without_yes_needs_a_terminal_and_writes_nothing(self) -> None:
        from unittest.mock import patch

        before = snapshot(self.root)
        with patch("sys.stdin.isatty", return_value=False):
            code, _out, err = self.retire("--apply")
        self.assertEqual(2, code)
        self.assertIn("Applying non-interactively requires --apply --yes", err)
        self.assertEqual(before, snapshot(self.root))

    def test_an_interactive_confirmation_applies_or_cancels(self) -> None:
        from unittest.mock import patch

        for answer, expected in (("n", "active"), ("y", "retired")):
            with self.subTest(answer=answer), patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=answer):
                code, out, _err = self.retire("--apply")
            self.assertEqual(0, code)
            self.assertEqual(expected, next(app for app in self.manifest()["apps"] if app["id"] == "partner-android").get("status", "active"))
            if answer == "n":
                self.assertIn("Canceled; no files changed.", out)

    def test_a_manifest_that_changed_after_the_preview_is_not_overwritten(self) -> None:
        from prism_cli.app_cli import apply_app_retire

        plan = plan_app_retire(self.root, "partner-android")
        self.assertEqual([], plan["conflicts"])
        edited = (self.root / MANIFEST_FILE).read_bytes() + b"# edited after preview\n"
        (self.root / MANIFEST_FILE).write_bytes(edited)

        receipt = apply_app_retire(self.root, plan)

        self.assertEqual("conflict", receipt["status"])
        self.assertIn("changed after preview", receipt["conflicts"][0])
        self.assertEqual(edited, (self.root / MANIFEST_FILE).read_bytes())

    def test_a_workspace_without_a_manifest_is_refused(self) -> None:
        (self.root / MANIFEST_FILE).unlink()

        code, _out, err = self.retire("--apply", "--yes")

        self.assertEqual(3, code)
        self.assertIn(f"{MANIFEST_FILE} is missing", err)

    def test_a_retired_app_stays_in_list_status_and_the_graph_marked_retired(self) -> None:
        self.write_feature(["customer-android", "partner-android"], status="done", owner="none")
        self.assertEqual(0, self.retire("--apply", "--yes")[0])

        listed = run_json("app", "list", str(self.root), "--json")
        self.assertEqual({"customer-android": "active", "partner-android": "retired", "backend": "active"}, {app["id"]: app["status"] for app in listed["apps"]})
        _code, table, _err = run_cli("app", "list", str(self.root))
        self.assertRegex(next(line for line in table.splitlines() if "partner-android" in line), r"\bretired\b")
        status = run_json("status", str(self.root), "--json", allowed=(0, 3))
        self.assertEqual("retired", next(app for app in status["workspace"]["apps"] if app["id"] == "partner-android")["status"])
        nodes = {node["id"]: node for node in build_graph(self.root)["facts"]["nodes"]}
        self.assertEqual("retired", nodes["app:partner-android"]["status"])
        self.assertEqual("active", nodes["app:customer-android"]["status"])
        mermaid = render_mermaid(build_graph(self.root), "app", app_id="partner-android")
        self.assertIn("partner-android (retired)", mermaid)

    def test_a_retired_apps_missing_directory_is_not_a_workspace_finding(self) -> None:
        self.declare([{**scope.CUSTOMER, "path": "mobile-gone"}, scope.PARTNER, scope.BACKEND])
        (self.root / "mobile-gone").rmdir()
        (self.root / "mobile-android").rmdir()
        first = run_json("status", str(self.root), "--json", allowed=(0, 3))
        self.assertTrue(any(item["code"] == "manifest-filesystem-drift" for item in first["diagnostics"]))
        retire = run_cli("app", "retire", "customer-android", str(self.root), "--apply", "--yes")
        self.assertEqual(0, retire[0], retire[2])

        second = run_json("status", str(self.root), "--json", allowed=(0, 3))

        self.assertFalse(any(item["code"] == "manifest-filesystem-drift" for item in second["diagnostics"]), second["diagnostics"])


class OptionsBeforeThePathTests(RetirementWorkspaceCase):
    """The workspace path may follow the options on every Python version (argparse before 3.12 needs the intermixed parser)."""

    def test_the_path_may_come_last_after_the_options(self) -> None:
        plan = run_json("app", "retire", "partner-android", "--json", str(self.root))
        self.assertEqual("partner-android", plan["app"]["id"])
        code, _out, err = run_cli("app", "retire", "partner-android", "--apply", "--yes", str(self.root))
        self.assertEqual(0, code, err)
        code, _out, err = run_cli("app", "add", "tablet", "--stack", "android-compose", "--path", "mobile-tablet", "--apply", "--yes", str(self.root))
        self.assertEqual(0, code, err)

    def test_other_commands_with_an_identifier_and_a_path_accept_the_same_order(self) -> None:
        self.write_feature(["customer-android"], status="in-dev", owner="dev")
        code, out, err = run_cli("wiki", "transition-preflight", "F-001", "--action", "dev-done", "--json", str(self.root))
        self.assertIn(code, (0, 3), err)
        self.assertEqual("dev-done", json.loads(out)["facts"]["requested_action"])


class RetirementScopeTests(RetirementWorkspaceCase):
    """Contract section 8, item 4: retiring partner-android flags features in progress and deletes nothing."""

    IN_PROGRESS = (
        ("raw", "po"),
        ("specified", "po"),
        ("ready-for-design", "designer"),
        ("in-design", "designer"),
        ("ready-for-dev", "dev"),
        ("in-dev", "dev"),
    )

    def test_a_feature_in_progress_that_includes_the_retired_app_is_flagged(self) -> None:
        for status, owner in self.IN_PROGRESS:
            self.write_feature(["customer-android", "partner-android"], status=status, owner=owner)
            self.assertEqual([], self.flagged(), f"nothing is flagged before the retirement ({status})")
        self.assertEqual(0, self.retire("--apply", "--yes")[0])

        for status, owner in self.IN_PROGRESS:
            with self.subTest(status=status):
                self.write_feature(["customer-android", "partner-android"], status=status, owner=owner)
                found = self.flagged()
                self.assertEqual(1, len(found))
                self.assertEqual("error", found[0].severity)
                self.assertEqual("F-001", found[0].feature_id)
                self.assertIn("`partner-android`", found[0].message)
                self.assertIn("Retiring an app never changes a feature's scope by itself", found[0].message)
                self.assertFalse(self.lint().is_clean)

    def test_every_lifecycle_action_is_blocked_with_the_code_until_the_scope_is_edited(self) -> None:
        self.assertEqual(0, self.retire("--apply", "--yes")[0])
        actions = [spec for spec in ACTION_SPECS if not spec.action.startswith("reopen-")]
        self.assertGreaterEqual(len(actions), 6)
        for spec in actions:
            with self.subTest(action=spec.action):
                self.write_feature(["customer-android", "partner-android"], status=spec.source_status, owner=spec.source_owner)
                transition = build_transition_preflight(self.root, "F-001", action=spec.action)["facts"]["transition"]
                blocked = next(item for item in transition["checks"] if item["code"] == "app-retired-in-scope")
                self.assertEqual("blocked", blocked["status"])
                self.assertIn("`partner-android`", blocked["message"])
                self.assertIn("never changes a feature's scope by itself", blocked["message"])
                self.assertNotEqual("ready", transition["classification"])

    def test_editing_the_scope_to_drop_the_retired_app_clears_the_flag(self) -> None:
        self.write_feature(["customer-android", "partner-android"], status="in-dev", owner="dev")
        self.assertEqual(0, self.retire("--apply", "--yes")[0])
        self.assertEqual(1, len(self.flagged()))

        self.write_feature(["customer-android"], status="in-dev", owner="dev")

        self.assertEqual([], self.flagged())
        transition = build_transition_preflight(self.root, "F-001", action="dev-done")["facts"]["transition"]
        self.assertFalse(any(item["code"] == "app-retired-in-scope" for item in transition["checks"]))
        self.assertEqual("pass", next(item for item in transition["checks"] if item["code"] == "app-scope")["status"])

    def test_a_done_feature_keeps_the_retired_app_as_history_and_lints_clean(self) -> None:
        self.write_done_with_history()
        self.assertTrue(self.lint().is_clean)

        self.assertEqual(0, self.retire("--apply", "--yes")[0])

        result = self.lint()
        self.assertEqual([], self.flagged(result))
        self.assertTrue(result.is_clean, [item.to_dict() for item in result.diagnostics if item.severity == "error"])
        for action in ("reopen-spec", "reopen-design", "reopen-dev"):
            with self.subTest(action=action):
                scope_check = next(item for item in build_transition_preflight(self.root, "F-001", action=action)["facts"]["transition"]["checks"] if item["code"] == "app-scope")
                self.assertEqual("pass", scope_check["status"])

    def test_retiring_deletes_no_file_whatever_the_features_say(self) -> None:
        self.write_feature(["customer-android", "partner-android"], status="in-dev", owner="dev")
        self.write_requirement("customer-android")
        self.write_requirement("partner-android")
        self.write_design()
        before = snapshot(self.root)

        self.assertEqual(0, self.retire("--apply", "--yes")[0])

        after = snapshot(self.root)
        self.assertEqual(set(before), set(after))
        self.assertEqual([MANIFEST_FILE], [name for name in before if before[name] != after[name]])

    def test_a_retired_app_still_has_a_feature_scope_that_lint_knows(self) -> None:
        self.write_feature(["customer-android", "partner-android"], status="in-dev", owner="dev")
        self.assertEqual(0, self.retire("--apply", "--yes")[0])

        result = self.lint()

        self.assertEqual([], self.with_code(result, "unknown-app-id"), "a retired app is still an app of the workspace")


class AddingAnAppTests(RetirementWorkspaceCase):
    def test_adding_an_app_leaves_every_features_scope_unchanged(self) -> None:
        self.write_feature(["customer-android"], status="in-dev", owner="dev")
        self.write_requirement("customer-android")
        features = {path.name: path.read_bytes() for path in sorted((self.wiki / "features").glob("*.md"))}
        requirements = {path.name: path.read_bytes() for path in sorted((self.wiki / "app-requirements").glob("*.md"))}
        index = (self.wiki / "index.md").read_bytes()

        code, _out, err = run_cli("app", "add", "tablet-android", str(self.root), "--stack", "android-compose", "--path", "mobile-tablet", "--apply", "--yes")

        self.assertEqual(0, code, err)
        self.assertEqual(features, {path.name: path.read_bytes() for path in sorted((self.wiki / "features").glob("*.md"))})
        self.assertEqual(requirements, {path.name: path.read_bytes() for path in sorted((self.wiki / "app-requirements").glob("*.md"))})
        self.assertEqual(index, (self.wiki / "index.md").read_bytes())
        self.assertIn("tablet-android", [app["id"] for app in run_json("app", "list", str(self.root), "--json")["apps"]])
        from prism_cli.wiki_model import read_feature_pages

        self.assertEqual(["customer-android"], read_feature_pages(self.wiki)[0].apps)
        self.assertEqual([], self.with_code(self.lint(), "app-retired-in-scope"))


class RetiredAppBoardTests(unittest.TestCase):
    """The board rejects a retired app on a new feature and on an added scope, and blocks lifecycle proposals on a flagged feature."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "ws"
        self.root.mkdir()
        install_workflow(self.root, platforms=("backend",))
        declare_two_apps(self.root)
        code, _out, err = run_cli("app", "retire", "partner-android", str(self.root), "--apply", "--yes")
        self.assertEqual(0, code, err)
        self.service = BoardService(self.root).start()
        self.addCleanup(self.service.close)

    def page(self, apps: list[str], status: str = "raw", owner: str = "po") -> tuple[str, str]:
        return app_model_baseline._feature("F-001", "Outcome capture", status, owner, apps)

    def test_a_new_feature_that_names_a_retired_app_is_rejected_with_app_retired(self) -> None:
        for skill in ("po-intake", "po-specify"):
            with self.subTest(skill=skill):
                relative, page = self.page(["customer-android", "partner-android"])
                with self.assertRaises(BoardError) as caught:
                    self.service._validate_feature_output(relative, page, skill)
                error = caught.exception
                self.assertEqual(("app_retired", 409), (error.code, error.status))
                self.assertIn("`partner-android`", error.message)
                self.assertIn("Retirement never changes a scope by itself", error.message)
                self.assertEqual({"apps": ["customer-android", "partner-android"], "retired_apps": ["partner-android"], "board_apps": ["backend", "customer-android"]}, error.details)

    def test_an_edit_that_adds_a_retired_app_to_a_scope_is_rejected(self) -> None:
        relative, page = self.page(["customer-android", "partner-android"], "specified")
        with self.assertRaises(BoardError) as caught:
            self.service._validate_feature_output(relative, page, "po-specify", ["customer-android"])
        self.assertEqual("app_retired", caught.exception.code)

    def test_an_edit_that_keeps_a_retired_app_already_in_the_scope_is_not_an_addition(self) -> None:
        relative, page = self.page(["customer-android", "partner-android"], "done", "none")
        self.service._validate_feature_output(relative, page, "feature-reopen", ["customer-android", "partner-android"])

    def test_a_new_feature_with_active_apps_is_accepted(self) -> None:
        relative, page = self.page(["customer-android", "backend"])
        self.service._validate_feature_output(relative, page, "po-intake")

    def test_an_app_the_board_never_had_is_still_an_invalid_scope_not_a_retired_one(self) -> None:
        relative, page = self.page(["customer-android", "ghost"])
        with self.assertRaises(BoardError) as caught:
            self.service._validate_feature_output(relative, page, "po-intake")
        self.assertEqual("invalid_feature_output", caught.exception.code)

    def test_a_lifecycle_proposal_on_a_feature_in_progress_with_a_retired_app_is_blocked(self) -> None:
        for status in ("raw", "specified", "ready-for-design", "in-design", "ready-for-dev", "in-dev"):
            with self.subTest(status=status), self.assertRaises(BoardError) as caught:
                self.service._require_no_retired_app_in_progress("F-001", {"id": "F-001", "status": status, "apps": ["customer-android", "partner-android"]})
            error = caught.exception
            self.assertEqual(("app_retired_in_scope", 409), (error.code, error.status))
            self.assertEqual({"feature_id": "F-001", "apps": ["customer-android", "partner-android"], "retired_apps": ["partner-android"]}, error.details)

    def test_a_done_feature_and_a_clean_scope_take_lifecycle_proposals(self) -> None:
        self.service._require_no_retired_app_in_progress("F-001", {"id": "F-001", "status": "done", "apps": ["customer-android", "partner-android"]})
        self.service._require_no_retired_app_in_progress("F-001", {"id": "F-001", "status": "in-dev", "apps": ["customer-android"]})

    def test_discover_lists_the_retired_app_marked_retired(self) -> None:
        participant = self.service.create_participant("Reader", "human", writable=False)
        board = self.service.discover(self.service.authenticate(participant["token"]))["board"]

        self.assertEqual({"backend": "active", "customer-android": "active", "partner-android": "retired"}, {app["id"]: app["status"] for app in board["apps"]})

    def test_the_app_query_reads_a_retired_app(self) -> None:
        participant = self.service.create_participant("Reader", "human", writable=False)
        actor = self.service.authenticate(participant["token"])

        result = query(self.service, actor, "app", "partner-android")

        self.assertEqual("partner-android", result["facts"]["app"])


class ApiServingAppBoardTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "ws"
        self.root.mkdir()
        install_workflow(self.root, platforms=("backend",))
        declare_two_apps(self.root)
        self.service = BoardService(self.root).start()
        self.addCleanup(self.service.close)

    def feature(self, apps: list[str], api: str) -> dict:
        relative, page = app_model_baseline._feature("F-001", "Outcome capture", "in-design", "designer", apps)
        page = page.replace("## API surface\nNone\n", f"## API surface\n{api}\n", 1)
        return {"path": relative, "id": "F-001", "after": {"apps": apps}, "supplied": {relative: page}}

    def test_design_handoff_for_api_work_needs_an_app_that_serves_an_api(self) -> None:
        item = self.feature(["customer-android"], "GET /outcomes returns the outcome list.")
        with self.assertRaises(BoardError) as caught:
            self.service._require_api_serving_app(item["supplied"], item)
        error = caught.exception
        self.assertEqual(("api_surface_without_api_app", 409), (error.code, error.status))
        self.assertIn("`customer-android` (serves-api: false)", error.message)
        self.assertEqual({"feature_id": "F-001", "apps": ["customer-android"], "board_apps": ["backend", "customer-android", "partner-android"]}, error.details)

    def test_an_app_that_serves_an_api_or_no_api_work_passes(self) -> None:
        for apps, api in ((["customer-android", "backend"], "GET /outcomes returns the outcome list."), (["customer-android"], "None.")):
            with self.subTest(apps=apps, api=api):
                item = self.feature(apps, api)
                self.service._require_api_serving_app(item["supplied"], item)


if __name__ == "__main__":
    unittest.main()
