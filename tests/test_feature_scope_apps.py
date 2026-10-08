"""Feature scope names apps of the workspace, and the lifecycle gates read capabilities, never IDs."""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import yaml

from prism_cli import cli
from prism_cli.board_reads import query
from prism_cli.board_service import BoardError, BoardService
from prism_cli.wiki_graph import build_graph
from prism_cli.wiki_lint import lint_wiki
from prism_cli.wiki_transitions import build_transition_preflight
from prism_cli.workflow_assets import list_skills
from prism_cli.workflow_assets import _load as load_workflow_asset
from tests import app_model_baseline
from tests import real_temp  # noqa: F401
from prism_cli.wiki_model import app_stages_text
from tests.wiki_files import evidence_tables, write_index, write_status_board
from tests.test_app_model_workspace import declare_two_apps, install_workflow


REPO_ROOT = Path(__file__).resolve().parents[1]

CUSTOMER = {"id": "customer-android", "name": "Customer app", "stack": "android-compose", "repository": "workspace", "path": "mobile-android"}
PARTNER = {"id": "partner-android", "name": "Partner app", "stack": "android-compose", "repository": "mobile-apps", "path": "apps/partner"}
BACKEND = {"id": "backend", "name": "API", "stack": "spring-backend", "repository": "workspace", "path": "backend"}


def other_app(app_id: str, **capabilities: object) -> dict:
    return {
        "id": app_id,
        "name": f"Tool {app_id}",
        "stack": "other",
        "repository": "workspace",
        "path": f"tools/{app_id}",
        "capabilities": dict(capabilities),
    }


def run_cli(*argv: str) -> tuple[int, str, str]:
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        try:
            code = cli.main(list(argv))
        except SystemExit as exit_request:
            code = exit_request.code if isinstance(exit_request.code, int) else 1
    return code, stdout.getvalue(), stderr.getvalue()


FEATURE_BODY = """## Summary
Prepare a payout summary.

## User story
As an operator, I want a payout summary, so that I can review it.

## Acceptance criteria
- [ ] AC-1 [{criterion_apps}] The summary includes the payout period.

## Open questions

## App scope
{scope}

## API surface
{api}
"""


class WikiWorkspaceCase(unittest.TestCase):
    """A disposable wiki workspace whose manifest declares the apps a test needs."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "ws"
        self.wiki = self.root / "knowledge" / "wiki"
        for directory in ("features", "app-requirements", "advisory", "design", "api-contracts"):
            (self.wiki / directory).mkdir(parents=True)
        (self.root / "knowledge" / "intake" / "pending").mkdir(parents=True)
        (self.root / "knowledge" / "intake" / "quarantined").mkdir(parents=True)
        for name in ("SCHEMA.md", "LIFECYCLE.md"):
            (self.wiki / name).write_text("---\nschema-version: 1\n---\n# Wiki\n", encoding="utf-8")
        (self.wiki / "SETTINGS.md").write_text("---\nwiki-stale-after-days: 36500\n---\n", encoding="utf-8")
        self.declare([CUSTOMER, PARTNER, BACKEND])

    def declare(self, apps: list[dict], repositories: list[dict] | None = None) -> None:
        manifest = {
            "schema_version": 2,
            "project": {"name": "Scope test", "slug": "scope-test"},
            "repositories": repositories
            if repositories is not None
            else [{"id": "workspace"}, {"id": "mobile-apps", "remote": "https://example.com/acme/mobile-apps.git"}],
            "apps": apps,
        }
        (self.root / "prism.workspace.yml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
        for app in apps:
            if app["repository"] == "workspace":
                (self.root / app["path"]).mkdir(parents=True, exist_ok=True)

    def write_feature(self, apps: list[str], *, status: str = "ready-for-dev", owner: str = "dev", extra: str = "", api: str = "None.") -> Path:
        scope = "\n".join(f"- **{app}**: Deliver the summary in {app}." for app in apps)
        text = (
            f"---\nid: F-001\ntitle: Payout summary\nstatus: {status}\nowner: {owner}\n"
            f"apps: [{', '.join(apps)}]\nsources: []\nadvisory-review: not-needed\ncriteria-high-water: 1\n{extra}---\n\n"
            + FEATURE_BODY.format(scope=scope, api=api, criterion_apps=", ".join(apps))
        )
        path = self.wiki / "features" / "F-001-payout-summary.md"
        path.write_text(text, encoding="utf-8")
        write_status_board(self.root, f"| F-001 | Payout summary | {status} | {owner} | not-needed |\n")
        write_index(self.root)
        return path

    def write_requirement(self, app: str, status: str = "pending") -> None:
        (self.wiki / "app-requirements" / f"F-001-{app}.md").write_text(
            f"---\nfeature-id: F-001\napp: {app}\nstatus: {status}\n---\n\n## Acceptance criteria\n- Data is prepared.\n",
            encoding="utf-8",
        )

    def write_design(self) -> None:
        (self.wiki / "design" / "F-001-payout-summary.md").write_text(
            "---\nfeature-id: F-001\ntitle: Payout summary\nfigma: not applicable\n---\n\n## Summary\nThe summary screen.\n",
            encoding="utf-8",
        )

    def lint(self):
        return lint_wiki(self.root)

    @staticmethod
    def with_code(result, code: str) -> list:
        return [item for item in result.diagnostics if item.code == code]

    def check(self, action: str, code: str) -> dict:
        transition = build_transition_preflight(self.root, "F-001", action=action)["facts"]["transition"]
        return next(item for item in transition["checks"] if item["code"] == code)


class TwoAppsOfOneStackTests(WikiWorkspaceCase):
    def test_each_scoped_app_needs_its_own_requirement_page(self) -> None:
        self.write_feature(["customer-android", "partner-android"])

        missing = self.with_code(self.lint(), "missing-app-requirements")
        self.assertEqual(2, len(missing))
        self.assertEqual({"customer-android", "partner-android"}, {app for app in ("customer-android", "partner-android") if any(f"`{app}`" in item.message for item in missing)})

        self.write_requirement("customer-android")
        missing = self.with_code(self.lint(), "missing-app-requirements")
        self.assertEqual(1, len(missing))
        self.assertIn("`partner-android`", missing[0].message)

        self.write_requirement("partner-android")
        self.assertEqual([], self.with_code(self.lint(), "missing-app-requirements"))
        self.assertEqual("pass", self.check("dev-start", "app-requirements")["status"])

    def test_the_dev_start_check_names_the_app_without_a_page(self) -> None:
        self.write_feature(["customer-android", "partner-android"])
        self.write_requirement("customer-android")

        blocked = self.check("dev-start", "app-requirements")

        self.assertEqual("blocked", blocked["status"])
        self.assertIn("partner-android", blocked["message"])
        self.assertNotIn("customer-android", blocked["message"])

    def test_both_apps_fire_the_design_gate_because_of_has_ui(self) -> None:
        self.write_feature(["customer-android", "partner-android"])
        self.write_requirement("customer-android")
        self.write_requirement("partner-android")

        design = self.with_code(self.lint(), "missing-design")

        self.assertEqual(1, len(design))
        self.assertIn("customer-android", design[0].message)
        self.assertIn("partner-android", design[0].message)
        self.write_feature(["customer-android", "partner-android"], status="in-design", owner="designer")
        self.assertEqual("blocked", self.check("design-handoff", "design")["status"])

        self.write_feature(["customer-android", "partner-android"])
        self.write_design()
        self.assertEqual([], self.with_code(self.lint(), "missing-design"))

    def test_the_app_scope_section_lists_every_scoped_app_by_id(self) -> None:
        path = self.write_feature(["customer-android", "partner-android"], status="specified", owner="po")
        self.assertEqual("pass", self.check("po-handoff", "app-section")["status"])
        self.assertEqual("pass", self.check("po-handoff", "app-scope")["status"])

        path.write_text(path.read_text(encoding="utf-8").replace("- **partner-android**: Deliver the summary in partner-android.\n", ""), encoding="utf-8")
        missing = self.check("po-handoff", "app-section")

        self.assertEqual("blocked", missing["status"])
        self.assertIn("partner-android", missing["message"])

    def test_the_graph_has_one_node_per_app_titled_with_its_name(self) -> None:
        self.write_feature(["customer-android", "partner-android"])
        self.write_requirement("customer-android")
        self.write_requirement("partner-android")

        data = build_graph(self.root)

        nodes = {node["id"]: node for node in data["facts"]["nodes"]}
        self.assertEqual("app", nodes["app:customer-android"]["type"])
        self.assertEqual("Customer app", nodes["app:customer-android"]["title"])
        self.assertEqual("Partner app", nodes["app:partner-android"]["title"])
        self.assertNotIn("app:backend", nodes, "an app no feature targets has no node")
        self.assertNotIn("platform", {node["type"] for node in nodes.values()})
        edges = {(edge["source"], edge["target"], edge["kind"]): edge["evidence"] for edge in data["facts"]["edges"]}
        self.assertEqual("frontmatter-apps", edges[("F-001", "app:customer-android", "targets")])
        self.assertEqual("frontmatter-apps", edges[("F-001", "app:partner-android", "targets")])
        self.assertIn("areq:F-001-customer-android", nodes)
        self.assertIn("areq:F-001-partner-android", nodes)

    def test_the_app_view_picks_each_requirement_by_exact_app_id(self) -> None:
        from prism_cli.wiki_graph import render_mermaid

        self.declare([CUSTOMER, PARTNER, {**CUSTOMER, "id": "android", "path": "mobile"}])
        self.write_feature(["android", "customer-android"])
        self.write_requirement("android")
        self.write_requirement("customer-android")

        mermaid = render_mermaid(build_graph(self.root), "app", app_id="android")

        self.assertIn("n_areq_F_001_android", mermaid)
        self.assertNotIn("n_areq_F_001_customer_android", mermaid)


class CapabilityGateTests(WikiWorkspaceCase):
    def test_an_app_without_a_ui_passes_the_design_gate_without_design(self) -> None:
        self.declare([other_app("batch", **{"has-ui": False, "serves-api": False})])
        self.write_feature(["batch"])
        self.write_requirement("batch")

        result = self.lint()

        self.assertEqual([], self.with_code(result, "missing-design"))
        self.write_feature(["batch"], status="in-design", owner="tech-lead")
        self.assertEqual("pass", self.check("design-handoff", "design")["status"])
        self.assertEqual([], self.with_code(result, "app-capability-unknown"))

    def test_an_unknown_ui_capability_counts_as_true_and_is_reported_once(self) -> None:
        self.declare([other_app("batch", **{"has-ui": "unknown", "serves-api": False})])
        self.write_feature(["batch"])
        self.write_requirement("batch")

        result = self.lint()

        self.assertEqual(1, len(self.with_code(result, "missing-design")))
        unknown = self.with_code(result, "app-capability-unknown")
        self.assertEqual(1, len(unknown))
        self.assertEqual("info", unknown[0].severity)
        self.assertIn("`batch`", unknown[0].message)
        self.assertIn("`has-ui`", unknown[0].message)
        self.write_feature(["batch"], status="in-design", owner="designer")
        self.assertEqual("blocked", self.check("design-handoff", "design")["status"])

    def test_one_information_finding_per_app_and_capability(self) -> None:
        self.declare([other_app("one", **{"has-ui": "unknown", "serves-api": "unknown"}), other_app("two", **{"has-ui": "unknown", "serves-api": True})])
        self.write_feature(["one"], status="specified", owner="po")

        findings = self.with_code(self.lint(), "app-capability-unknown")

        self.assertEqual(3, len(findings))
        self.assertEqual({"info"}, {item.severity for item in findings})
        self.assertTrue(self.lint().is_clean, "information findings do not make the wiki unclean")

    def test_an_app_with_an_unknown_ui_needs_a_design_page_and_no_exemption_exists(self) -> None:
        self.declare([other_app("batch", **{"has-ui": "unknown", "serves-api": False})])
        self.write_feature(["batch"], extra="design: not-applicable\ndesign-exemption-reason: The tool has no screens.\n")
        self.write_requirement("batch")

        result = self.lint()

        self.assertEqual(1, len(self.with_code(result, "missing-design")))
        self.assertEqual(2, len(self.with_code(result, "unsupported-feature-field")))
        self.write_feature(["batch"])
        self.write_design()
        self.assertEqual([], self.with_code(self.lint(), "missing-design"))

    def test_the_api_contract_check_follows_the_api_surface_for_every_app(self) -> None:
        """The API-contract check reads the feature's API surface, never an app ID or stack; an app that serves an API needs the contract once the surface declares work."""

        for capabilities in ({"has-ui": False, "serves-api": True}, {"has-ui": False, "serves-api": False}):
            with self.subTest(capabilities=capabilities):
                self.declare([other_app("service", **capabilities)])
                self.write_requirement("service")
                self.write_feature(["service"], api="None.")
                self.assertEqual("pass", self.check("dev-start", "api-contract")["status"])
                self.write_feature(["service"], api="GET /summaries returns the payout summary.")
                self.assertEqual("blocked", self.check("dev-start", "api-contract")["status"])


class UnknownAppTests(WikiWorkspaceCase):
    def test_lint_rejects_an_app_the_workspace_does_not_have(self) -> None:
        self.write_feature(["customer-android", "ghost"])

        findings = self.with_code(self.lint(), "unknown-app-id")

        self.assertEqual(1, len(findings))
        self.assertIn("`ghost`", findings[0].message)
        self.assertIn("customer-android", findings[0].message)
        self.assertEqual("error", findings[0].severity)

    def test_lint_rejects_a_requirement_page_for_an_app_the_workspace_does_not_have(self) -> None:
        self.write_feature(["customer-android"])
        self.write_requirement("ghost")

        self.assertEqual(1, len(self.with_code(self.lint(), "unknown-app-id")))

    def test_the_transition_scope_check_blocks_an_app_the_workspace_does_not_have(self) -> None:
        self.write_feature(["ghost"], status="specified", owner="po")

        scope = self.check("po-handoff", "app-scope")

        self.assertEqual("blocked", scope["status"])
        self.assertIn("ghost", scope["message"])

    def test_the_board_rejects_an_app_the_board_does_not_have(self) -> None:
        root = Path(tempfile.mkdtemp(dir=self.root.parent))
        install_workflow(root, platforms=("backend",))
        declare_two_apps(root)
        service = BoardService(root).start()
        self.addCleanup(service.close)
        relative, page = app_model_baseline._feature("F-001", "Outcome capture", "raw", "po", ["customer-android", "ghost"])

        with self.assertRaises(BoardError) as outside:
            service._validate_feature_output(relative, page, "po-intake")

        self.assertEqual("invalid_feature_output", outside.exception.code)
        self.assertIn("`ghost`", outside.exception.message)
        self.assertEqual({"apps": ["customer-android", "ghost"], "board_apps": ["backend", "customer-android", "partner-android"]}, outside.exception.details)

    def test_the_board_accepts_the_apps_it_has(self) -> None:
        root = Path(tempfile.mkdtemp(dir=self.root.parent))
        install_workflow(root, platforms=("backend",))
        declare_two_apps(root)
        service = BoardService(root).start()
        self.addCleanup(service.close)
        relative, page = app_model_baseline._feature("F-001", "Outcome capture", "raw", "po", ["customer-android", "partner-android"])

        service._validate_feature_output(relative, page, "po-intake")


class RenamedFieldTests(WikiWorkspaceCase):
    def test_platforms_front_matter_is_an_error_that_names_apps(self) -> None:
        path = self.write_feature(["customer-android"])
        path.write_text(path.read_text(encoding="utf-8").replace("apps: [customer-android]", "platforms: [customer-android]"), encoding="utf-8")

        result = self.lint()

        unknown = self.with_code(result, "unsupported-feature-field")
        self.assertEqual(1, len(unknown))
        self.assertIn("`apps:`", unknown[0].message)
        self.assertEqual("error", unknown[0].severity)
        self.assertTrue(any(item.code == "missing-feature-frontmatter" and "`apps`" in item.message for item in result.diagnostics))

    def test_platform_in_a_requirement_page_is_an_error_that_names_app(self) -> None:
        self.write_feature(["customer-android"])
        self.write_requirement("customer-android")
        page = self.wiki / "app-requirements" / "F-001-customer-android.md"
        page.write_text(page.read_text(encoding="utf-8").replace("app: customer-android", "platform: customer-android"), encoding="utf-8")

        unknown = self.with_code(self.lint(), "unknown-requirement-field")

        self.assertEqual(1, len(unknown))
        self.assertIn("`app:`", unknown[0].message)

    def test_the_old_requirements_folder_is_not_read(self) -> None:
        self.write_feature(["customer-android"])
        old = self.wiki / "platform-requirements"
        old.mkdir()
        (old / "F-001-customer-android.md").write_text("---\nfeature-id: F-001\nplatform: customer-android\nstatus: done\n---\n", encoding="utf-8")

        self.assertEqual(1, len(self.with_code(self.lint(), "missing-app-requirements")))

    def test_the_delivery_evidence_table_is_keyed_by_app(self) -> None:
        released = self.write_feature(["customer-android", "partner-android"], status="released", owner="none")
        self.write_requirement("customer-android", "done")
        self.write_requirement("partner-android", "done")
        text = released.read_text(encoding="utf-8")
        both = ["customer-android", "partner-android"]
        self.assertEqual("customer-android: released; partner-android: released", app_stages_text("released", both, text + "\n" + evidence_tables(both), None))

        released.write_text(text + "\n" + evidence_tables(both), encoding="utf-8")
        write_status_board(self.root, "| F-001 | Payout summary | released | none | not-needed |\n")
        self.assertEqual([], self.with_code(self.lint(), "app-row-missing"))

        released.write_text(text + "\n" + evidence_tables(both, skip=("partner-android",)), encoding="utf-8")
        missing = self.with_code(self.lint(), "app-row-missing")
        self.assertEqual(1, len(missing))
        self.assertIn("`partner-android`", missing[0].message)
        self.assertEqual(1, len(self.with_code(self.lint(), "feature-status-not-minimum")))

        wrong_header = evidence_tables(both).replace("| App | Artifact |", "| Platform | Artifact |", 1)
        released.write_text(text + "\n" + wrong_header, encoding="utf-8")
        self.assertTrue(any("must start with the header" in item.message for item in self.with_code(self.lint(), "invalid-evidence-row")))


class QuerySurfaceTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "ws"
        self.root.mkdir()
        install_workflow(self.root, platforms=("backend",))
        declare_two_apps(self.root)
        relative, page = app_model_baseline._feature("F-001", "Outcome capture", "specified", "po", ["customer-android"])
        (self.root / relative).parent.mkdir(parents=True, exist_ok=True)
        (self.root / relative).write_text(page, encoding="utf-8")
        (self.root / "knowledge" / "wiki" / "SETTINGS.md").write_text("---\nwiki-stale-after-days: 36500\n---\n", encoding="utf-8")

    def test_the_cli_command_takes_an_app_id_of_the_workspace(self) -> None:
        code, out, err = run_cli("wiki", "app", "customer-android", str(self.root), "--json")

        self.assertIn(code, (0, 3), err)
        envelope = json.loads(out)
        self.assertEqual("wiki app", envelope["command"])
        self.assertEqual("customer-android", envelope["facts"]["app"])
        self.assertIn("app_requirements", envelope["facts"])
        self.assertNotIn("platform", envelope["facts"])

    def test_the_cli_command_rejects_an_app_the_workspace_does_not_have(self) -> None:
        code, out, err = run_cli("wiki", "app", "ghost", str(self.root), "--json")

        self.assertEqual(3, code)
        self.assertIn("`ghost` is not an app of this workspace", err)
        self.assertEqual("", out)

    def test_the_platform_command_and_option_are_gone(self) -> None:
        code, _out, err = run_cli("wiki", "platform", "backend", str(self.root))
        self.assertNotEqual(0, code)
        self.assertIn("invalid choice", err)
        code, _out, err = run_cli("wiki", "graph", str(self.root), "--mermaid", "--view", "app", "--platform", "backend")
        self.assertNotEqual(0, code)
        self.assertIn("--platform", err)

    def test_the_graph_view_takes_an_app_id(self) -> None:
        code, out, err = run_cli("wiki", "graph", str(self.root), "--mermaid", "--view", "app", "--app", "customer-android")
        self.assertEqual(0, code, err)
        self.assertIn("customer-android", out)
        code, _out, err = run_cli("wiki", "graph", str(self.root), "--mermaid", "--view", "app")
        self.assertEqual(3, code)
        self.assertIn("--view app requires --app", err)

    def test_the_board_app_query_reads_the_boards_apps(self) -> None:
        service = BoardService(self.root).start()
        self.addCleanup(service.close)
        actor = service.authenticate(service.create_participant("Reader", "human", writable=False)["token"])

        result = query(service, actor, "app", "customer-android")

        self.assertEqual("wiki app", result["command"])
        self.assertEqual("customer-android", result["facts"]["app"])
        with self.assertRaises(BoardError) as rejected:
            query(service, actor, "platform", "backend")
        self.assertEqual("invalid_query", rejected.exception.code)
        with self.assertRaises(BoardError) as outside:
            query(service, actor, "app", "ghost")
        self.assertEqual("invalid_query", outside.exception.code)
        self.assertIn("outside this workspace's declared scope", outside.exception.message)


class GeneratedSurfaceTests(unittest.TestCase):
    def test_wiki_app_replaces_wiki_platform_in_both_generated_layers(self) -> None:
        template = REPO_ROOT / "template"
        self.assertTrue((template / ".agents" / "skills" / "wiki-app" / "SKILL.md.jinja").is_file())
        self.assertTrue((template / ".agents" / "skills" / "wiki-app" / "agents" / "openai.yaml").is_file())
        self.assertTrue((template / ".claude" / "commands" / "wiki-app.md.jinja").is_file())
        self.assertFalse((template / ".agents" / "skills" / "wiki-platform").exists())
        self.assertFalse((template / ".claude" / "commands" / "wiki-platform.md.jinja").exists())
        self.assertTrue((template / "knowledge" / "wiki" / "app-requirements" / "_FORMAT.md").is_file())
        self.assertFalse((template / "knowledge" / "wiki" / "platform-requirements").exists())

    def test_the_packaged_skills_list_wiki_app(self) -> None:
        names = {item["name"] for item in list_skills()}
        self.assertIn("wiki-app", names)
        self.assertNotIn("wiki-platform", names)
        paths = {item["path"] for item in load_workflow_asset("1")["files"]}
        self.assertIn(".agents/skills/wiki-app/SKILL.md", paths)
        self.assertIn("knowledge/wiki/app-requirements/_FORMAT.md", paths)
        self.assertFalse(any("platform" in path for path in paths), sorted(path for path in paths if "platform" in path))


if __name__ == "__main__":
    unittest.main()
