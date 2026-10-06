"""Knowledge-root workspaces: a workflow-only workspace for apps that live in other repositories."""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator
import yaml

from prism_cli import cli
from prism_cli.app_model import PURPOSE_KNOWLEDGE_ROOT, normalize_manifest
from prism_cli.board_reads import query
from prism_cli.board_service import BoardError, BoardService
from prism_cli.presets import PRESETS, WORKFLOW_PRESETS
from prism_cli.status import build_status
from prism_cli.wiki_graph import build_graph
from prism_cli.wiki_graph_html import render_html
from prism_cli.wiki_lint import lint_wiki
from prism_cli.workflow_assets import guidance_pointer
from prism_cli.workflow_install import apply_install, plan_install
from prism_cli.workspace import MANIFEST_FILE, load_workspace
from tests import app_model_baseline
from tests import real_temp  # noqa: F401
from tests.wiki_files import write_index, write_status_board
from tests.test_workflow_assets import _load_build_script


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = REPO_ROOT / "prism_cli" / "schemas"
MOBILE_REMOTE = "https://example.com/acme/mobile-apps.git"
BILLING_REMOTE = "https://example.com/acme/billing-service.git"


def run_cli(*argv: str) -> tuple[int, str, str]:
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        try:
            code = cli.main(list(argv))
        except SystemExit as exit_request:
            code = exit_request.code if isinstance(exit_request.code, int) else 1
    return code, stdout.getvalue(), stderr.getvalue()


def run_json(*argv: str, allowed: tuple[int, ...] = (0,)) -> dict:
    code, stdout, stderr = run_cli(*argv)
    if code not in allowed:
        raise AssertionError(f"prism {' '.join(argv)} exited {code}: {stderr}")
    return json.loads(stdout)


def schema(name: str) -> dict:
    return json.loads((SCHEMA_ROOT / name).read_text(encoding="utf-8"))


def manifest_data(root: Path) -> dict:
    return yaml.safe_load((root / MANIFEST_FILE).read_text(encoding="utf-8"))


class KnowledgeRootCase(unittest.TestCase):
    """A disposable knowledge root started through the CLI."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "knowledge"
        self.root.mkdir()
        code, _out, err = run_cli("workflow", "install", str(self.root), "--name", "Acme knowledge", "--knowledge-root", "--apply", "--yes")
        self.assertEqual(0, code, err)

    def add_external_apps(self) -> None:
        for argv in (
            ("customer-android", "--stack", "android-compose", "--name", "Customer app", "--audience", "B2C",
             "--repository", "mobile-apps", "--remote", MOBILE_REMOTE, "--path", "apps/customer"),
            ("billing-api", "--stack", "spring-backend", "--name", "Billing API",
             "--repository", "billing-service", "--remote", BILLING_REMOTE, "--path", "."),
        ):
            code, _out, err = run_cli("app", "add", *argv, str(self.root), "--apply", "--yes")
            self.assertEqual(0, code, err)

    def map_mobile_checkout(self) -> Path:
        checkout = self.base / "checkouts" / "mobile-apps"
        (checkout / "apps" / "customer").mkdir(parents=True)
        (self.root / "prism.local.yml").write_text(yaml.safe_dump({"repositories": {"mobile-apps": str(checkout)}}), encoding="utf-8")
        return checkout


class StartKnowledgeRootTests(unittest.TestCase):
    def new_root(self) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name) / "ws"
        root.mkdir()
        return root

    def test_the_preview_writes_nothing_and_the_apply_records_the_purpose(self) -> None:
        root = self.new_root()

        plan = plan_install(root, name="Acme knowledge", knowledge_root=True)

        self.assertEqual([], plan["conflicts"])
        self.assertEqual("workflow", plan["mode"])
        self.assertEqual(PURPOSE_KNOWLEDGE_ROOT, plan["purpose"])
        self.assertEqual([], plan["apps"])
        self.assertEqual([], list(root.iterdir()), "planning must not write")
        self.assertEqual("applied", apply_install(root, plan)["status"])

        manifest = manifest_data(root)
        self.assertEqual(2, manifest["schema_version"])
        self.assertEqual([], manifest["apps"])
        self.assertEqual("workflow", manifest["workflow"]["mode"])
        self.assertEqual("knowledge-root", manifest["workflow"]["purpose"])
        self.assertEqual("Acme knowledge", manifest["project"]["name"])
        self.assertIn("prism.local.yml", (root / ".gitignore").read_text(encoding="utf-8"))

    def test_the_cli_previews_applies_and_reports_the_purpose_in_json(self) -> None:
        root = self.new_root()

        code, out, err = run_cli("workflow", "install", str(root), "--name", "Acme", "--knowledge-root", "--json")
        self.assertEqual(0, code, err)
        plan = json.loads(out)
        self.assertEqual("knowledge-root", plan["purpose"])
        self.assertFalse((root / MANIFEST_FILE).exists())

        code, out, err = run_cli("workflow", "install", str(root), "--name", "Acme", "--knowledge-root", "--apply", "--yes", "--json")
        self.assertEqual(0, code, err)
        receipt = json.loads(out)
        self.assertEqual("applied", receipt["status"])
        self.assertEqual("knowledge-root", receipt["purpose"])
        self.assertEqual("knowledge-root", receipt["plan"]["purpose"])
        self.assertEqual("knowledge-root", manifest_data(root)["workflow"]["purpose"])

    def test_it_cannot_be_combined_with_app(self) -> None:
        root = self.new_root()

        code, _out, err = run_cli("workflow", "install", str(root), "--name", "Acme", "--knowledge-root", "--app", "backend", "--apply", "--yes")

        self.assertEqual(3, code)
        self.assertIn("`--knowledge-root` cannot be combined with `--app`", err)
        self.assertEqual([], list(root.iterdir()))
        with self.assertRaises(ValueError):
            plan_install(root, name="Acme", apps=["backend"], knowledge_root=True)

    def test_only_install_takes_the_option(self) -> None:
        root = self.new_root()

        code, _out, err = run_cli("workflow", "upgrade", str(root), "--knowledge-root")

        self.assertEqual(2, code)
        self.assertIn("--knowledge-root", err)

    def test_the_guidance_says_what_a_knowledge_root_is(self) -> None:
        root = self.new_root()
        apply_install(root, plan_install(root, name="Acme", knowledge_root=True))

        text = (root / "AGENTS.md").read_text(encoding="utf-8")
        self.assertEqual(guidance_pointer("AGENTS.md", purpose="knowledge-root"), text)
        flat = " ".join(text.split())
        for term in (
            "This workspace is a knowledge root",
            "applications that live in other repositories",
            "generates no application code",
            "feature scope, delivery evidence and shared knowledge",
            "Each application repository keeps its own instructions",
            "neither set of rules overrides the other",
            "`prism.local.yml` (untracked, per machine) maps each external repository to its local checkout",
            "The feature lifecycle is optional",
        ):
            self.assertIn(term, flat)
        self.assertTrue(text.startswith(guidance_pointer("AGENTS.md")), "the knowledge-root text extends the standard pointer")
        # CLAUDE.md only imports AGENTS.md, so the knowledge-root text lives once.
        self.assertEqual("@AGENTS.md\n", (root / "CLAUDE.md").read_text(encoding="utf-8"))
        self.assertEqual(guidance_pointer("CLAUDE.md"), guidance_pointer("CLAUDE.md", purpose="knowledge-root"))

    def test_a_plain_workflow_workspace_has_no_purpose_and_no_knowledge_root_guidance(self) -> None:
        root = self.new_root()
        plan = plan_install(root, name="Plain")
        apply_install(root, plan)

        self.assertIsNone(plan["purpose"])
        self.assertNotIn("purpose", manifest_data(root)["workflow"])
        self.assertNotIn("purpose", run_json("status", str(root), "--json")["workspace"], "only a knowledge root reports a purpose")
        self.assertNotIn("purpose", run_json("wiki", "lint", str(root), "--json")["workspace"])
        service = BoardService(root)
        self.addCleanup(service.close)
        actor = service.authenticate(service.create_participant("Reader", "human", writable=False)["token"])
        self.assertNotIn("purpose", service.discover(actor)["board"])
        self.assertEqual(guidance_pointer("AGENTS.md"), (root / "AGENTS.md").read_text(encoding="utf-8"))
        self.assertNotIn("knowledge root", (root / "AGENTS.md").read_text(encoding="utf-8"))

    def test_repeating_the_install_or_upgrading_changes_nothing_and_keeps_the_purpose(self) -> None:
        root = self.new_root()
        apply_install(root, plan_install(root, name="Acme", knowledge_root=True))

        for kwargs in ({"knowledge_root": True}, {}, {"upgrade": True}):
            with self.subTest(kwargs=kwargs):
                plan = plan_install(root, **kwargs)
                self.assertEqual([], plan["conflicts"])
                self.assertEqual([], plan["changes"])
                self.assertEqual(PURPOSE_KNOWLEDGE_ROOT, plan["purpose"])
        self.assertEqual("knowledge-root", manifest_data(root)["workflow"]["purpose"])

    def test_it_starts_a_workspace_and_never_converts_an_existing_one(self) -> None:
        plain = self.new_root()
        apply_install(plain, plan_install(plain, name="Plain", apps=["backend"]))
        manifest = (plain / MANIFEST_FILE).read_bytes()

        plan = plan_install(plain, knowledge_root=True)

        self.assertTrue(any("starts a new workspace" in item for item in plan["conflicts"]), plan["conflicts"])
        self.assertEqual("conflict", apply_install(plain, plan)["status"])
        self.assertEqual(manifest, (plain / MANIFEST_FILE).read_bytes())

        generated = self.new_root()
        (generated / MANIFEST_FILE).write_text(yaml.safe_dump({"schema_version": 2, "project": {"name": "Generated"}, "generated_by": {"tool": "prism-cli"}}), encoding="utf-8")
        refused = plan_install(generated, name="Generated", knowledge_root=True)
        self.assertTrue(any("generated workspace" in item for item in refused["conflicts"]), refused["conflicts"])


class PurposeValidationTests(unittest.TestCase):
    def manifest(self, **workflow: object) -> dict:
        return {
            "schema_version": 2,
            "project": {"name": "Purpose"},
            "apps": [],
            "workflow": {"version": "1", "mode": "workflow", "board_id": "44f8c341-9a4a-4dc5-970a-c4656f3d5140", **workflow},
        }

    def test_a_valid_purpose_and_an_absent_one_are_accepted(self) -> None:
        for workflow, expected in (({"purpose": "knowledge-root"}, "knowledge-root"), ({}, None)):
            with self.subTest(workflow=workflow):
                model, diagnostics = normalize_manifest(self.manifest(**workflow), path=Path(MANIFEST_FILE))
                self.assertEqual([], diagnostics)
                self.assertEqual(expected, model.purpose)
        model, _ = normalize_manifest(self.manifest(purpose="knowledge-root"), path=Path(MANIFEST_FILE))
        self.assertTrue(model.knowledge_root)

    def test_any_other_value_is_an_error_with_a_stable_code(self) -> None:
        for value in ("wiki", "Knowledge-Root", "", 3, True, ["knowledge-root"], {"name": "knowledge-root"}, None):
            with self.subTest(value=value):
                model, diagnostics = normalize_manifest(self.manifest(purpose=value), path=Path(MANIFEST_FILE))
                self.assertEqual(["invalid-workflow-purpose"], [item.code for item in diagnostics])
                self.assertEqual("error", diagnostics[0].severity)
                self.assertIsNone(model.purpose)

    def test_a_purpose_needs_a_workflow_only_workspace(self) -> None:
        model, diagnostics = normalize_manifest(self.manifest(mode="generated", purpose="knowledge-root"), path=Path(MANIFEST_FILE))

        self.assertEqual(["invalid-workflow-purpose"], [item.code for item in diagnostics])
        self.assertIn("`workflow.mode` must be `workflow`", diagnostics[0].message)
        self.assertFalse(model.knowledge_root)

    def test_the_error_reaches_status_the_board_and_the_installer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "ws"
            root.mkdir()
            apply_install(root, plan_install(root, name="Bad purpose"))
            data = manifest_data(root)
            data["workflow"]["purpose"] = "wiki"
            (root / MANIFEST_FILE).write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

            self.assertIn("invalid-workflow-purpose", [item.code for item in load_workspace(root).diagnostics])
            envelope = run_json("status", str(root), "--json", allowed=(0,))
            self.assertEqual("error", envelope["confidence"])
            self.assertIn("invalid-workflow-purpose", [item["code"] for item in envelope["manifest"]["diagnostics"]])
            self.assertNotIn("purpose", envelope["workspace"])
            service = BoardService(root)
            self.addCleanup(service.close)
            compatibility = service.compatibility()
            self.assertTrue(compatibility["read_only"])
            self.assertIn("invalid-workflow-purpose", compatibility["reason"])
            plan = plan_install(root, upgrade=True)
            self.assertTrue(any("invalid-workflow-purpose" in item for item in plan["conflicts"]), plan["conflicts"])


class LifecycleOptionalTests(KnowledgeRootCase):
    """A knowledge root with no apps and no feature pages passes every workspace check."""

    def check_everything_passes(self, expected_apps: int) -> dict:
        root = str(self.root)
        self.assertEqual(0, run_cli("wiki", "lint", root)[0])
        lint = run_json("wiki", "lint", root, "--json")
        self.assertEqual(0, lint["facts"]["feature_count"])
        self.assertEqual("knowledge-root", lint["workspace"]["purpose"])
        Draft202012Validator(schema("wiki-lint-v1.json")).validate(lint)
        self.assertEqual(0, run_cli("validate", root)[0])
        envelope = run_json("status", root, "--json")
        Draft202012Validator(schema("status-v1.json")).validate(envelope)
        self.assertEqual("knowledge-root", envelope["workspace"]["purpose"])
        self.assertEqual(expected_apps, len(envelope["workspace"]["apps"]))
        self.assertEqual(0, envelope["facts"]["wiki"]["feature_count"])
        self.assertEqual(0, envelope["facts"]["wiki"]["error_count"])
        self.assertEqual(0, envelope["facts"]["wiki"]["blocker_count"])
        self.assertEqual([], envelope["blocker_facts"])
        self.assertEqual([], [item for item in envelope["diagnostics"] if item["severity"] == "error"])
        code, out, _err = run_cli("doctor", "--workspace", root)
        self.assertEqual(0, code, out)
        self.assertIn("Purpose: knowledge root", out)
        self.assertIn("Prism workflow checks passed.", out)
        self.assertEqual(0, run_cli("board", "status", root)[0])
        service = BoardService(self.root).start()
        self.addCleanup(service.close)
        self.assertEqual({"read_only": False, "reason": None}, service.compatibility())
        actor = service.authenticate(service.create_participant("Writer", "human", writable=True)["token"])
        self.assertTrue(actor.writable)
        board = service.discover(actor)["board"]
        self.assertEqual("knowledge-root", board["purpose"])
        self.assertEqual(expected_apps, len(board["apps"]))
        return envelope

    def test_no_apps_and_no_features(self) -> None:
        envelope = self.check_everything_passes(0)

        self.assertEqual("high", envelope["confidence"])
        self.assertEqual([], envelope["diagnostics"])

    def test_status_and_the_graph_say_there_are_no_features_yet_without_a_problem(self) -> None:
        code, out, _err = run_cli("status", str(self.root))

        self.assertEqual(0, code)
        self.assertIn("Purpose: knowledge root", out)
        self.assertIn("No features yet.", out)
        self.assertIn("the feature lifecycle is optional", out)
        self.assertIn("Wiki errors: 0", out)
        self.assertIn("Workspace status is clean.", out)
        graph = build_graph(self.root)
        Draft202012Validator(schema("wiki-graph-v1.json")).validate(graph)
        self.assertEqual("knowledge-root", graph["workspace"]["purpose"])
        self.assertEqual("high", graph["confidence"])

    def test_registered_external_apps_keep_every_check_passing(self) -> None:
        self.add_external_apps()
        self.map_mobile_checkout()

        envelope = self.check_everything_passes(2)

        repositories = {item["id"]: item for item in envelope["workspace"]["repositories"]}
        self.assertEqual("resolved", repositories["mobile-apps"]["checkout"])
        self.assertEqual("unresolved", repositories["billing-service"]["checkout"])
        warnings = [item for item in envelope["diagnostics"] if item["severity"] == "warning"]
        self.assertEqual(["external-repository-unresolved"], [item["code"] for item in warnings], "the unresolved checkout is one warning")
        self.assertIn("`billing-service`", warnings[0]["message"])
        self.assertEqual("degraded", envelope["confidence"])
        self.assertNotIn(str(self.base / "checkouts"), json.dumps(envelope), "status never prints a local path")

    def test_a_resolved_checkout_is_never_written(self) -> None:
        self.add_external_apps()
        checkout = self.map_mobile_checkout()
        before = sorted(path.relative_to(checkout).as_posix() for path in checkout.rglob("*"))

        run_cli("status", str(self.root))
        run_cli("wiki", "lint", str(self.root))
        run_cli("doctor", "--workspace", str(self.root))
        build_graph(self.root)

        self.assertEqual(before, sorted(path.relative_to(checkout).as_posix() for path in checkout.rglob("*")))

    def test_the_board_page_describes_the_workspace_as_a_knowledge_root(self) -> None:
        envelope = build_graph(self.root)

        html = render_html(envelope, mode="live")

        self.assertIn('"purpose": "knowledge-root"', html.replace('"purpose":"knowledge-root"', '"purpose": "knowledge-root"'))
        self.assertIn("renderKnowledgeRootGuide", html)
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node.js is required for the dashboard runtime check")
        with tempfile.TemporaryDirectory() as temporary:
            page = Path(temporary) / "board.html"
            page.write_text(html, encoding="utf-8")
            result = subprocess.run(
                [node, str(REPO_ROOT / "scripts" / "dashboard-boot-check.js"), str(page)],
                cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30,
            )
        self.assertEqual(0, result.returncode, result.stderr or result.stdout)
        self.assertIn("BOOT OK", result.stdout)
        self.assertIn("FIRSTRUN OK — knowledge root guide rendered", result.stdout)


FEATURE_BODY = """## Summary
Show the invoice history.

## User story
As a customer, I want to see my invoices, so that I can check what I paid.

## Acceptance criteria
- [ ] The history lists every invoice.

## Open questions

## App scope
{scope}

## API surface
None.

## Delivery evidence
| App | Implementation | Tests | Release |
|---|---|---|---|
{rows}
"""


class FeatureLaterTests(KnowledgeRootCase):
    """Adding a feature later works as in any workflow workspace, scoped to the registered apps."""

    def setUp(self) -> None:
        super().setUp()
        self.board = None
        self.add_external_apps()
        self.map_mobile_checkout()
        self.wiki = self.root / "knowledge" / "wiki"
        (self.wiki / "SETTINGS.md").write_text("---\nwiki-stale-after-days: 36500\n---\n", encoding="utf-8")

    def write_in_dev_feature(self, apps: list[str]) -> None:
        scope = "\n".join(f"- **{app}**: Deliver the history in {app}." for app in apps)
        rows = "\n".join(
            f"| {app} | https://example.com/acme/{app}/pull/42 | https://example.com/acme/{app}/actions/runs/1187 | release: https://example.com/acme/{app}/releases/tag/v1.4.0 |"
            for app in apps
        )
        (self.wiki / "features" / "F-001-invoice-history.md").write_text(
            "---\nid: F-001\ntitle: Invoice history\nstatus: in-dev\nowner: dev\n"
            f"apps: [{', '.join(apps)}]\nsources: []\nadvisory-review: not-needed\ndesign: not-applicable\n"
            "design-exemption-reason: The history reuses the existing list screen.\n---\n\n"
            + FEATURE_BODY.format(scope=scope, rows=rows),
            encoding="utf-8",
        )
        for app in apps:
            (self.wiki / "app-requirements" / f"F-001-{app}.md").write_text(
                f"---\nfeature-id: F-001\napp: {app}\nstatus: done\n---\n\n## Acceptance criteria\n- The history is shown.\n",
                encoding="utf-8",
            )
        write_status_board(self.root, "| F-001 | Invoice history | in-dev | dev | not-needed |\n")
        write_index(self.root)

    def dev_done_checks(self) -> dict[str, dict]:
        """The dev-done checks as the connected board evaluates them for a human writer."""

        if self.board is None:
            self.board = BoardService(self.root).start()
            self.addCleanup(self.board.close)
            self.writer = self.board.authenticate(self.board.create_participant("Writer", "human", writable=True)["token"])
        transition = query(self.board, self.writer, "transition-preflight", "F-001", "dev-done")["facts"]["transition"]
        return {check["code"]: check for check in transition["checks"]}

    def test_delivery_evidence_by_url_passes_dev_done_for_a_resolved_and_an_unresolved_app(self) -> None:
        for apps in (["customer-android"], ["billing-api"], ["customer-android", "billing-api"]):
            with self.subTest(apps=apps):
                self.write_in_dev_feature(apps)

                checks = self.dev_done_checks()

                self.assertEqual("pass", checks["delivery-evidence"]["status"], checks["delivery-evidence"])
                self.assertEqual([], [code for code, check in checks.items() if check["status"] in {"blocked", "unknown"}], checks)
                result = lint_wiki(self.root)
                self.assertEqual(0, result.error_count, [item.to_dict() for item in result.diagnostics])
                status = build_status(self.root)
                self.assertEqual(1, status.wiki_lint.feature_count)
                self.assertEqual(["external-repository-unresolved"], [item.code for item in status.manifest_diagnostics])

    def test_the_unresolved_checkout_does_not_block_the_evidence_of_a_missing_app(self) -> None:
        self.write_in_dev_feature(["customer-android", "billing-api"])
        page = self.wiki / "features" / "F-001-invoice-history.md"
        page.write_text(page.read_text(encoding="utf-8").replace("| billing-api | https://example.com/acme/billing-api/pull/42 | https://example.com/acme/billing-api/actions/runs/1187 | release: https://example.com/acme/billing-api/releases/tag/v1.4.0 |\n", ""), encoding="utf-8")

        blocked = self.dev_done_checks()["delivery-evidence"]

        self.assertEqual("blocked", blocked["status"])
        self.assertIn("billing-api", blocked["message"])
        self.assertNotIn("checkout", blocked["message"])

    def test_the_board_scopes_a_feature_to_the_registered_apps_only(self) -> None:
        service = BoardService(self.root).start()
        self.addCleanup(service.close)
        accepted_relative, accepted = app_model_baseline._feature("F-001", "Invoice history", "raw", "po", ["customer-android", "billing-api"])
        service._validate_feature_output(accepted_relative, accepted, "po-intake")

        relative, page = app_model_baseline._feature("F-002", "Ghost", "raw", "po", ["customer-android", "ghost"])
        with self.assertRaises(BoardError) as outside:
            service._validate_feature_output(relative, page, "po-intake")

        self.assertEqual("invalid_feature_output", outside.exception.code)
        self.assertIn("`ghost`", outside.exception.message)
        self.assertEqual(["billing-api", "customer-android"], outside.exception.details["board_apps"])


class PresetsTests(unittest.TestCase):
    def test_the_text_lists_the_knowledge_root_after_the_generation_presets(self) -> None:
        code, out, _err = run_cli("presets")

        self.assertEqual(0, code)
        for preset in PRESETS:
            self.assertIn(preset.slug, out)
        self.assertIn("Workflow presets (no application is generated)", out)
        self.assertIn("knowledge-root", out)
        self.assertIn("prism workflow install <path> --name <name> --knowledge-root", out)
        self.assertLess(out.index("backend-web"), out.index("Workflow presets"))
        self.assertLess(out.index("Workflow presets"), out.index("knowledge-root"))
        self.assertNotIn("knowledge-root", out[: out.index("Workflow presets")], "a workflow preset is not listed with the generation paths")

    def test_the_json_keeps_generation_and_workflow_presets_apart(self) -> None:
        data = run_json("presets", "--json")

        self.assertEqual({"schema_version", "command", "generation_presets", "workflow_presets"}, set(data))
        self.assertEqual("presets", data["command"])
        self.assertEqual([preset.slug for preset in PRESETS], [item["slug"] for item in data["generation_presets"]])
        for item in data["generation_presets"]:
            self.assertEqual({"slug", "label", "maturity", "summary", "notes"}, set(item))
        self.assertEqual(["knowledge-root"], [item["slug"] for item in data["workflow_presets"]])
        knowledge_root = data["workflow_presets"][0]
        self.assertEqual({"slug", "label", "summary", "command", "notes"}, set(knowledge_root))
        self.assertEqual(WORKFLOW_PRESETS[0].command, knowledge_root["command"])
        self.assertNotIn("maturity", knowledge_root)

    def test_a_workflow_preset_is_not_a_generation_preset(self) -> None:
        self.assertNotIn("knowledge-root", {preset.slug for preset in PRESETS})
        code, _out, err = run_cli("doctor", "--preset", "knowledge-root")
        self.assertEqual(2, code)
        self.assertIn("knowledge-root", err)


class PackagedGuidanceTests(unittest.TestCase):
    def test_both_forms_come_from_the_one_connected_section(self) -> None:
        build = _load_build_script()
        agents = (REPO_ROOT / "template" / "AGENTS.md.jinja").read_text(encoding="utf-8")
        claude = (REPO_ROOT / "template" / "CLAUDE.md.jinja").read_text(encoding="utf-8")

        plain, knowledge_root = build._connected_pointers(agents, claude)

        self.assertEqual(
            plain["AGENTS.md"].rstrip("\n") + "\n\n" + knowledge_root["AGENTS.md"][len(plain["AGENTS.md"]) + 1:],
            knowledge_root["AGENTS.md"],
        )
        self.assertNotIn("knowledge root", plain["AGENTS.md"])
        self.assertEqual(plain["AGENTS.md"], guidance_pointer("AGENTS.md"))
        self.assertEqual(knowledge_root["AGENTS.md"], guidance_pointer("AGENTS.md", purpose="knowledge-root"))
        # CLAUDE.md is the import of AGENTS.md in both forms and carries no section of its own.
        self.assertEqual("@AGENTS.md\n", plain["CLAUDE.md"])
        self.assertEqual(plain["CLAUDE.md"], knowledge_root["CLAUDE.md"])
        self.assertEqual(plain["CLAUDE.md"], guidance_pointer("CLAUDE.md"))
        self.assertEqual("@AGENTS.md\n", claude)
        self.assertEqual(1, agents.count("This workspace is a knowledge root"))
        self.assertEqual(0, claude.count("This workspace is a knowledge root"))

    def test_a_generated_project_never_gets_the_knowledge_root_paragraph(self) -> None:
        import jinja2

        source = (REPO_ROOT / "template" / "AGENTS.md.jinja").read_text(encoding="utf-8")
        section = source[source.index("## Connected board workflow"):source.index("## Product knowledge wiki")]
        environment = jinja2.Environment(undefined=jinja2.StrictUndefined, keep_trailing_newline=True)
        without = environment.from_string(section).render()
        with_condition = environment.from_string(section).render(knowledge_root=True)
        self.assertNotIn("knowledge root", without)
        self.assertIn("This workspace is a knowledge root", with_condition)
        self.assertEqual(without.rstrip(), with_condition[: len(without.rstrip())])


if __name__ == "__main__":
    unittest.main()
