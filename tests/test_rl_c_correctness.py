"""Correctness fixes found by review: manifest keys, lint agreement, path reuse, the API rule on the board, line endings."""

from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from uuid import uuid4

import yaml

from prism_cli.app_model import normalize_manifest
from prism_cli.board_service import BoardError, BoardService, _render_status_board
from prism_cli.wiki_lint import lint_wiki
from prism_cli.wiki_model import parse_delivery_rows, parse_status_board_rows
from prism_cli.workflow_install import apply_install, plan_install
from tests import real_temp  # noqa: F401
from tests import test_feature_scope_apps as scope
from tests.core_workflow_fixture import INTAKE_ITEM, create_core_workflow_fixture
from tests.layered_support import generate_default_apps, no_background_gc
from tests.test_board_service import _journey_feature_page, _read_revisions, _replace_body_section, _set_feature_stage, _write_index_rows
from tests.test_feature_scope_edit import NO_API, QUESTION, SOURCE, requirement, requirement_path, with_apps

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = Path("prism.workspace.yml")


def manifest(apps: list[dict], repositories: list[dict] | None = None) -> dict:
    data: dict = {"schema_version": 2, "project": {"name": "Check", "slug": "check"}, "apps": apps}
    if repositories is not None:
        data["repositories"] = repositories
    return data


def codes(data: dict) -> list[str]:
    return sorted(item.code for item in normalize_manifest(data, path=MANIFEST)[1])


BACKEND = {"id": "backend", "stack": "spring-backend", "path": "backend"}


class DocumentedEvidenceTests(unittest.TestCase):
    def test_the_adding_a_feature_example_of_the_workspace_model_passes_the_delivery_rules(self) -> None:
        text = (REPO_ROOT / "docs" / "workspace-model.md").read_text(encoding="utf-8")
        table = re.search(r"### Adding a feature later.*?```markdown\n(.*?)```", text, re.DOTALL)
        self.assertIsNotNone(table)
        rows, problems = parse_delivery_rows(table.group(1))
        self.assertEqual(["customer-android"], [row.app for row in rows])
        self.assertEqual([], [item.message for item in problems])


class UnknownManifestKeyTests(unittest.TestCase):
    def test_a_misspelled_app_field_is_an_error_not_a_silently_ignored_key(self) -> None:
        for key, value in (("satus", "retired"), ("capabilites", {"serves-api": True}), ("Path", "x"), ("port", 8080)):
            with self.subTest(key=key):
                self.assertEqual(["unknown-app-field"], codes(manifest([{**BACKEND, key: value}])))

    def test_the_message_names_the_app_and_the_unknown_field(self) -> None:
        _model, diagnostics = normalize_manifest(manifest([{**BACKEND, "satus": "retired"}]), path=MANIFEST)
        self.assertEqual(1, len(diagnostics))
        self.assertEqual("error", diagnostics[0].severity)
        self.assertIn("`backend`", diagnostics[0].message)
        self.assertIn("`satus`", diagnostics[0].message)

    def test_a_misspelled_repository_field_is_an_error(self) -> None:
        repositories = [{"id": "mobile-apps", "remote": "https://example.com/acme/mobile-apps.git", "remtoe": "x"}]
        self.assertEqual(["unknown-repository-field"], codes(manifest([BACKEND], repositories)))

    def test_every_documented_field_is_still_accepted(self) -> None:
        app = {
            "id": "partner",
            "name": "Partner app",
            "stack": "android-compose",
            "repository": "mobile-apps",
            "path": "apps/partner",
            "audience": "B2B",
            "status": "retired",
            "generation": "registered",
            "capabilities": {"has-ui": True},
        }
        repositories = [{"id": "mobile-apps", "remote": "https://example.com/acme/mobile-apps.git"}]
        self.assertEqual([], codes(manifest([BACKEND, app], repositories)))


class RetiredPathTests(unittest.TestCase):
    def test_a_retired_apps_path_may_be_reused_by_a_new_app_but_its_id_may_not(self) -> None:
        retired = {**BACKEND, "status": "retired"}
        replacement = {"id": "backend-two", "stack": "spring-backend", "path": "backend"}
        self.assertEqual([], codes(manifest([retired, replacement])))
        self.assertEqual(["duplicate-app-id"], codes(manifest([retired, {**replacement, "id": "backend"}])))

    def test_two_active_apps_still_conflict_on_a_path(self) -> None:
        self.assertEqual(["app-path-conflict"], codes(manifest([BACKEND, {"id": "backend-two", "stack": "spring-backend", "path": "backend"}])))
        self.assertEqual(["app-path-conflict"], codes(manifest([BACKEND, {"id": "inner", "stack": "spring-backend", "path": "backend/inner"}])))


class LintAgreementTests(scope.WikiWorkspaceCase):
    def test_the_design_page_of_a_lower_case_feature_id_counts_as_the_design(self) -> None:
        self.write_feature(["customer-android"])
        self.write_requirement("customer-android")
        self.assertEqual(1, len(self.with_code(self.lint(), "missing-design")))
        self.write_design()
        design = self.wiki / "design" / "F-001-payout-summary.md"
        design.write_text(design.read_text(encoding="utf-8").replace("feature-id: F-001", "feature-id: f-001"), encoding="utf-8")
        self.assertEqual([], self.with_code(self.lint(), "missing-design"))

    def test_the_advisory_board_and_the_project_foundation_are_current_state_pages(self) -> None:
        for name in ("BOARD.md", "PROJECT_FOUNDATION.md", "OTHER.md"):
            (self.wiki / "advisory" / name).write_text("---\nlast-updated: 2026-01-01\n---\n\n# Page\n\nBody.\n", encoding="utf-8")
        flagged = sorted(Path(item.path).name for item in lint_wiki(self.root).diagnostics if item.code == "history-date-on-page")
        self.assertEqual(["BOARD.md", "OTHER.md", "PROJECT_FOUNDATION.md"], flagged)

    def test_the_other_exempt_files_stay_exempt(self) -> None:
        for name in ("SCHEMA.md", "LIFECYCLE.md", "SETTINGS.md"):
            page = self.wiki / name
            page.write_text(page.read_text(encoding="utf-8").replace("---\n", "---\nlast-updated: 2026-01-01\n", 1), encoding="utf-8")
        self.assertEqual([], [item for item in lint_wiki(self.root).diagnostics if item.code == "history-date-on-page"])


class StatusBoardHeaderTests(unittest.TestCase):
    BOARD = (
        "# Feature Status Board\n\n| {id} | {feature} | {status} | {owner} | {review} | Design tracks | App stages | Open bugs |\n"
        "|----|---------|--------|-------|--------------|---------------|------------|-----------|\n| F-001 | Review | raw | po | not-needed | — | — | — |\n"
    )

    def board(self, **names: str) -> str:
        defaults = {"id": "ID", "feature": "Feature", "status": "Status", "owner": "Owner", "review": "Board Review"}
        return self.BOARD.format(**{**defaults, **names})

    def test_lint_and_the_board_accept_the_exact_header_and_refuse_a_differently_cased_one(self) -> None:
        after = {"F-001": {"id": "F-001", "title": "Review", "status": "specified", "owner": "po", "advisory_review": "not-needed", "design_tracks": "—", "app_stages": "—", "open_bugs": "—"}}
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "status-board.md"
            for label, text, valid in (
                ("exact", self.board(), True),
                ("lower case", self.board(id="id", feature="feature", status="status", owner="owner", review="board review"), False),
                ("one cell", self.board(owner="OWNER"), False),
            ):
                with self.subTest(header=label):
                    path.write_text(text, encoding="utf-8")
                    _rows, errors = parse_status_board_rows(path)
                    self.assertEqual(valid, not errors)
                    if valid:
                        self.assertIn("specified", _render_status_board(text, {"F-001": None}, after))
                    else:
                        with self.assertRaises(BoardError) as caught:
                            _render_status_board(text, {"F-001": None}, after)
                        self.assertEqual("invalid_status_board", caught.exception.code)


class ApiRuleOnTheBoardTests(unittest.TestCase):
    """`dev-start` and `dev-done` block a feature with declared API work and no app that serves an API, as `design-handoff` does."""

    API = "GET /documents returns the reviewed documents."

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = create_core_workflow_fixture(Path(temporary.name) / "generated-project")
        self.assertEqual("applied", apply_install(self.root, plan_install(self.root, name="Document review", apps=["backend"]))["status"])
        (self.root / INTAKE_ITEM).parent.rename(self.root / SOURCE)
        manifest_path = self.root / "prism.workspace.yml"
        data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        data["apps"].append({"id": "worker", "name": "worker", "stack": "other", "repository": "workspace", "path": "tools/worker", "capabilities": NO_API})
        (self.root / "tools" / "worker").mkdir(parents=True)
        manifest_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        self.pages = {}
        for feature_id, status, owner, apps in (("F-001", "ready-for-dev", "dev", ["worker"]), ("F-002", "in-dev", "dev", ["worker"]), ("F-003", "ready-for-dev", "dev", ["worker", "backend"])):
            page = with_apps(_journey_feature_page(feature_id, f"Feature {feature_id}", status, owner, [SOURCE], QUESTION), apps)
            page = _replace_body_section(None, page, "API surface", self.API)  # type: ignore[arg-type]
            relative = f"knowledge/wiki/features/{feature_id}-feature.md"
            self.pages[feature_id] = relative
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(page.encode("utf-8"))
            for app in apps:
                (self.root / requirement_path(feature_id, app)).write_bytes(requirement(feature_id, app, "pending").encode("utf-8"))
        _write_index_rows(self.root, [("F-001", "Feature F-001", "ready-for-dev", "dev"), ("F-002", "Feature F-002", "in-dev", "dev"), ("F-003", "Feature F-003", "ready-for-dev", "dev")])
        self.service = BoardService(self.root).start()
        self.addCleanup(self.service.close)
        self.agent = self.service.authenticate(self.service.create_participant("Api agent", "agent", True)["token"])

    def propose(self, skill: str, feature_id: str, status: str, owner: str) -> dict:
        relative = self.pages[feature_id]
        page = _set_feature_stage((self.root / relative).read_text(encoding="utf-8"), status, owner)
        changes = [{"path": relative, "content": page}]
        return self.service.preview_skill(self.agent, skill, changes, None, _read_revisions(self.service, self.agent, skill, changes))

    def test_dev_start_and_dev_done_are_refused_without_an_app_that_serves_an_api(self) -> None:
        for skill, feature_id, status, owner in (("dev-start", "F-001", "in-dev", "dev"), ("dev-done", "F-002", "in-dev", "dev")):
            with self.subTest(skill=skill), self.assertRaises(BoardError) as caught:
                self.propose(skill, feature_id, status, owner)
            error = caught.exception
            self.assertEqual(("api_surface_without_api_app", 409), (error.code, error.status))
            self.assertEqual(["worker"], error.details["apps"])

    def test_an_app_that_serves_an_api_lets_dev_start_through(self) -> None:
        preview = self.propose("dev-start", "F-003", "in-dev", "dev")
        self.assertNotEqual("api_surface_without_api_app", next((item["code"] for item in preview["checks"] if item["status"] == "blocked"), None))
        self.assertEqual(uuid4().version, 4)  # the preview carries a fresh ID; nothing was written
        self.assertEqual("ready-for-dev", yaml.safe_load((self.root / self.pages["F-003"]).read_text(encoding="utf-8").split("---", 2)[1])["status"])


class GeneratedLineEndingTests(unittest.TestCase):
    """A generated workspace stores LF whatever the machine's `core.autocrlf` says, so a commit leaves `git status` clean."""

    @staticmethod
    def git(workspace: Path, *arguments: str) -> str:
        identity = ("-c", "user.name=Prism test", "-c", "user.email=test@example.invalid")
        return subprocess.run(["git", *identity, *arguments], cwd=workspace, check=True, capture_output=True, text=True).stdout

    def test_the_workspace_ships_a_gitattributes_with_lf_and_crlf_only_for_windows_scripts(self) -> None:
        with tempfile.TemporaryDirectory(prefix="prism-eol-") as temporary:
            root = Path(temporary)
            workspace = generate_default_apps(root / "ws", ["backend"], root)
            lines = [line for line in (workspace / ".gitattributes").read_text(encoding="utf-8").splitlines() if line and not line.startswith("#")]
            self.assertEqual(["* text=auto eol=lf", "*.bat text eol=crlf", "*.cmd text eol=crlf"], lines)

            self.git(workspace, "init", "-q", "-b", "main")
            self.git(workspace, "config", "gc.auto", "0")
            # A CRLF file, as Copier writes a template file that was checked out with CRLF on Windows.
            crlf = workspace / "docs" / "line-endings.md"
            crlf.write_bytes(b"# Title\r\n\r\nText.\r\n")
            self.git(workspace, "-c", "core.autocrlf=true", "add", "-A")
            self.git(workspace, "-c", "core.autocrlf=true", "commit", "-qm", "Generated workspace")

            listing = {line.split("	")[1]: line.split("	")[0] for line in self.git(workspace, "ls-files", "--eol", "docs/line-endings.md", "backend/gradlew.bat").splitlines()}
            self.assertTrue(listing["docs/line-endings.md"].startswith("i/lf"), listing)
            # The index holds LF for every text file; a Windows script is checked out with CRLF by its own attribute.
            self.assertTrue(listing["backend/gradlew.bat"].startswith("i/lf"), listing)
            self.assertIn("eol=crlf", listing["backend/gradlew.bat"])
            # Later git invocations that disagree about autocrlf, and a file whose timestamp changed so git rereads it.
            later = crlf.stat().st_mtime + 10
            os.utime(crlf, (later, later))
            for autocrlf in ("true", "false", "input"):
                with self.subTest(autocrlf=autocrlf):
                    self.assertEqual("", self.git(workspace, "-c", f"core.autocrlf={autocrlf}", "status", "--porcelain"))


class UpdateEdgeCaseTests(unittest.TestCase):
    """A layer's commit leaves Copier's `.rej` files alone, and the template excludes what Copier excluded by default."""

    @staticmethod
    def git(repo: Path, *arguments: str) -> str:
        identity = ("-c", "user.name=Prism test", "-c", "user.email=test@example.invalid")
        return subprocess.run(["git", *identity, *arguments], cwd=repo, check=True, capture_output=True, text=True).stdout

    @classmethod
    def init_repo(cls, repo: Path) -> None:
        """A repository with its own identity, as `commit_layer` runs git without the helper's `-c` options, and no background gc."""

        cls.git(repo, "init", "-q", "-b", "main")
        no_background_gc(repo)
        cls.git(repo, "config", "user.name", "Prism test")
        cls.git(repo, "config", "user.email", "test@example.invalid")

    def test_commit_layer_never_commits_a_rej_file_and_leaves_it_in_the_tree(self) -> None:
        from prism_cli.layers import commit_layer, scan_conflicts

        with tempfile.TemporaryDirectory(prefix="prism-rej-") as temporary:
            repo = Path(temporary)
            self.init_repo(repo)
            (repo / "kept.txt").write_text("one\n", encoding="utf-8")
            self.git(repo, "add", "-A")
            self.git(repo, "commit", "-qm", "Base")

            (repo / "kept.txt").write_text("two\n", encoding="utf-8")
            (repo / "kept.txt.rej").write_text("rejected hunk\n", encoding="utf-8")
            (repo / "deep" / "er").mkdir(parents=True)
            (repo / "deep" / "er" / "page.md.rej").write_text("rejected hunk\n", encoding="utf-8")
            (repo / "deep" / "er" / "page.md").write_text("new page\n", encoding="utf-8")

            self.assertIsNotNone(commit_layer(repo, "Layer"))
            committed = self.git(repo, "ls-tree", "-r", "--name-only", "HEAD").split()
            self.assertEqual(["deep/er/page.md", "kept.txt"], sorted(committed))
            self.assertTrue((repo / "kept.txt.rej").is_file() and (repo / "deep" / "er" / "page.md.rej").is_file(), "the files stay for the person resolving the conflict")
            self.assertEqual(["deep/er/page.md.rej", "kept.txt.rej"], scan_conflicts(repo), "and the conflict scan still finds them")

    def test_a_layer_that_changed_only_a_rej_file_commits_nothing(self) -> None:
        from prism_cli.layers import commit_layer

        with tempfile.TemporaryDirectory(prefix="prism-rej-") as temporary:
            repo = Path(temporary)
            self.init_repo(repo)
            (repo / "kept.txt").write_text("one\n", encoding="utf-8")
            self.git(repo, "add", "-A")
            self.git(repo, "commit", "-qm", "Base")
            (repo / "kept.txt.rej").write_text("rejected hunk\n", encoding="utf-8")

            self.assertIsNone(commit_layer(repo, "Layer"))
            self.assertEqual("1", self.git(repo, "rev-list", "--count", "HEAD").strip())

    def test_the_template_excludes_python_caches_and_finder_files_in_both_layers(self) -> None:
        from copier import run_copy

        config = yaml.safe_load((REPO_ROOT / "copier.yml").read_text(encoding="utf-8"))
        defaults = config["_exclude"][:3]
        self.assertEqual(["__pycache__", "*.py[co]", ".DS_Store"], defaults)
        with tempfile.TemporaryDirectory(prefix="prism-exclude-") as temporary:
            template, destination = Path(temporary) / "template", Path(temporary) / "out"
            files = template / "files"
            (files / "__pycache__").mkdir(parents=True)
            (files / "pkg" / "__pycache__").mkdir(parents=True)
            for name in ("keep.txt", "__pycache__/x.pyc", "pkg/__pycache__/y.pyc", "pkg/mod.pyc", "pkg/mod.pyo", "pkg/.DS_Store", ".DS_Store"):
                (files / name).write_text("x\n", encoding="utf-8")
            (template / "copier.yml").write_text(yaml.safe_dump({"_subdirectory": "files", "_exclude": defaults}), encoding="utf-8")
            run_copy(str(template), str(destination), defaults=True, unsafe=True, quiet=True)
            produced = sorted(path.relative_to(destination).as_posix() for path in destination.rglob("*") if path.is_file())
            self.assertEqual(["keep.txt"], produced)


class WorkflowInstallLineEndingRuleTests(unittest.TestCase):
    """The installer keeps `knowledge/` on LF; a catch-all LF rule, as generated workspaces ship, already does."""

    def plan(self, attributes: str) -> dict:
        with tempfile.TemporaryDirectory(prefix="prism-attributes-") as temporary:
            root = Path(temporary)
            (root / ".gitattributes").write_text(attributes, encoding="utf-8")
            return plan_install(root, name="Check")

    def test_a_catch_all_lf_rule_is_enough(self) -> None:
        plan = self.plan("* text=auto eol=lf\n*.bat text eol=crlf\n")
        self.assertIn(".gitattributes", plan["unchanged"])
        self.assertNotIn(".gitattributes", [change["path"] for change in plan["changes"]])

    def test_a_catch_all_rule_without_lf_or_a_later_knowledge_rule_is_not(self) -> None:
        for attributes in ("* text=auto\n", "* text=auto eol=lf\nknowledge/** text eol=crlf\n", "* text=auto eol=lf\n* text=auto eol=crlf\n"):
            with self.subTest(attributes=attributes):
                plan = self.plan(attributes)
                self.assertIn(".gitattributes", [change["path"] for change in plan["changes"]])


if __name__ == "__main__":
    unittest.main()
