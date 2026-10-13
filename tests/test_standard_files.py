"""The standard wiki files: the one manifest they are listed in, and every part of Prism that reads it.

`PinnedBehaviourTests` states, as literal lists, which standard file each part of the product treats as required,
recorded as a revision or gating. It never reads the manifest, so it keeps the lists that existed before the
manifest from drifting. `ManifestBehaviourTests` runs the same checks against the manifest's categories, so each
consumer's list equals the manifest's. `ExtraEntryTests` adds an entry to the manifest and nothing else, and every
consumer follows it.
"""

from __future__ import annotations

import ast
import hashlib
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from prism_cli import standard_files
from prism_cli.board_service import BoardError, BoardService, BoardServiceIdentity
from prism_cli.wiki_index import index_label, index_summary, is_page_path
from prism_cli.wiki_lint import _is_non_source_page, lint_wiki
from prism_cli.wiki_links import NON_PAGE_FILENAMES
from prism_cli.wiki_model import read_feature_pages
from prism_cli.wiki_transitions import ACTION_SPECS, _relevant_integrity_checks, _transition_sources, evaluate_transition_summaries, workspace_fingerprint
from prism_cli.workflow_install import apply_install, plan_install
from prism_cli.workspace import inspect_workspace
from tests import real_temp  # noqa: F401
from tests.test_core_workflow_fixture import _feature_page, _write_index
from tests.wiki_files import write_index

REPOSITORY = Path(__file__).resolve().parents[1]
WIKI = "knowledge/wiki"
FEATURE = f"{WIKI}/features/F-001-document-review.md"
EXTRA = "EXTRA.md"

# Every standard file at the root of the wiki, in the order the product lists them.
ALL = ("SCHEMA.md", "LIFECYCLE.md", "ACTIONS.md", "SETTINGS.md", "CONNECTED.md", "index.md", "status-board.md", "log.md")


def installed_workspace(test: unittest.TestCase) -> Path:
    """A workflow workspace with every standard file, one feature page and a lint-clean index and status board."""

    temporary = tempfile.TemporaryDirectory()
    test.addCleanup(temporary.cleanup)
    root = Path(temporary.name)
    receipt = apply_install(root, plan_install(root, name="Document review", apps=["backend"]))
    test.assertEqual("applied", receipt["status"])
    (root / FEATURE).write_text(_feature_page(), encoding="utf-8")
    _write_index(root, "raw", "po")
    return root


def standard(paths, names=ALL) -> set[str]:
    """The names of the standard files among workspace-relative or absolute `paths`."""

    return {Path(path).name for path in paths if Path(path).parent.name == "wiki"} & set(names)


def read_revisions(root: Path, paths) -> dict[str, str]:
    return {path: "sha256:" + hashlib.sha256((root / path).read_bytes()).hexdigest() for path in paths}


class StandardFileBehaviour:
    """The checks of how each part of Prism treats the standard files, against the expectations a subclass sets."""

    ALL: tuple[str, ...]
    REQUIRED: tuple[str, ...]
    VERSIONED: tuple[str, ...]
    MANAGED: tuple[str, ...]
    UNINDEXED: tuple[str, ...]
    TRANSITION_REVISIONS: set[str]
    FEATURE_REVISIONS: set[str]
    READ_REVISIONS: set[str]
    SOURCES: tuple[str, ...]
    NON_SOURCE: set[str]
    NON_PAGE: set[str]
    FIXED_LINES: dict[str, tuple[str, str]]

    def setUp(self) -> None:
        self.root = installed_workspace(self)
        self.wiki = self.root / WIKI
        self.service = BoardService(self.root).start()
        self.addCleanup(self.service.close)
        agent = self.service.create_participant("Writer", "agent", writable=True)
        self.agent = self.service.authenticate(agent["token"])

    def test_the_installed_workspace_has_every_standard_file(self) -> None:
        self.assertEqual(sorted(self.ALL), sorted(name for name in self.ALL if (self.wiki / name).is_file()))

    def test_lint_reports_exactly_the_required_files_as_missing(self) -> None:
        for name in self.ALL:
            (self.wiki / name).unlink()
        missing = [Path(item.path).name for item in lint_wiki(self.root).diagnostics if item.code == "missing-required-wiki-file"]
        self.assertEqual(sorted(self.REQUIRED), sorted(missing))

    def test_lint_requires_a_schema_version_of_exactly_the_versioned_files(self) -> None:
        for name in self.ALL:
            (self.wiki / name).write_text("# Unversioned\n", encoding="utf-8", newline="\n")
        unversioned = [Path(item.path).name for item in lint_wiki(self.root).diagnostics if item.code == "missing-schema-version"]
        self.assertEqual(sorted(self.VERSIONED), sorted(unversioned))

    def test_lint_never_reads_these_files_as_source_pages_wherever_they_sit(self) -> None:
        for name in self.ALL:
            with self.subTest(name=name):
                self.assertEqual(name in self.NON_SOURCE, _is_non_source_page(self.wiki / "features" / name, self.wiki))

    def test_the_link_helpers_skip_exactly_these_non_page_files(self) -> None:
        self.assertEqual(self.NON_PAGE, set(NON_PAGE_FILENAMES))

    def test_the_index_lists_every_standard_file_but_the_unindexed_ones(self) -> None:
        for name in self.ALL:
            with self.subTest(name=name):
                self.assertEqual(name not in self.UNINDEXED, is_page_path(name))
        self.assertFalse(is_page_path("WIKI_REPORT.md"))

    def test_the_index_gives_these_files_a_fixed_line(self) -> None:
        for name in self.ALL:
            with self.subTest(name=name):
                line = (index_label(name, {}), index_summary(name, {}, ""))
                if name in self.FIXED_LINES:
                    self.assertEqual(self.FIXED_LINES[name], line)
                else:
                    self.assertNotIn(line, self.FIXED_LINES.values())

    def test_the_board_recognizes_exactly_these_wiki_root_files(self) -> None:
        for name in self.ALL:
            with self.subTest(name=name):
                relative, _path = self.service._approved_source_path(f"{WIKI}/{name}")
                self.assertEqual(f"{WIKI}/{name}", relative)
        with self.assertRaises(BoardError) as unknown:
            self.service._approved_source_path(f"{WIKI}/NOTES.md")
        self.assertEqual("path_not_approved", unknown.exception.code)

    def test_a_proposal_cannot_supply_the_files_the_board_writes_itself(self) -> None:
        for name in self.ALL:
            with self.subTest(name=name):
                with self.assertRaises(BoardError) as refused:
                    self.service.preview_skill(self.agent, "ask", [{"path": f"{WIKI}/{name}", "content": "x"}])
                self.assertEqual(name in self.MANAGED, refused.exception.code == "managed_file", refused.exception.code)

    def test_a_board_adopts_a_workspace_only_with_every_required_file(self) -> None:
        self.assertIsNotNone(BoardServiceIdentity(self.root))
        for name in self.ALL:
            with self.subTest(name=name):
                path = self.wiki / name
                content = path.read_bytes()
                path.unlink()
                try:
                    self.assertEqual(name not in self.REQUIRED, BoardServiceIdentity(self.root) is not None)
                finally:
                    path.write_bytes(content)

    def test_a_candidate_workspace_carries_every_standard_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.service._build_candidate_root(Path(directory), {}, [])
            self.assertEqual(sorted(self.ALL), sorted(name for name in self.ALL if (Path(directory) / WIKI / name).is_file()))

    def test_a_feature_records_these_revisions(self) -> None:
        feature = self.service._resolve_feature("F-001")
        paths = self.service._feature_context_paths(feature["path"], feature["frontmatter"])
        self.assertEqual(self.FEATURE_REVISIONS, standard(paths))

    def test_a_transition_records_these_revisions(self) -> None:
        feature = self.service._resolve_feature("F-001")
        paths = self.service._transition_context_paths(feature["path"], feature["frontmatter"])
        self.assertEqual(self.TRANSITION_REVISIONS, standard(paths))

    def test_a_skill_must_have_read_these_files_before_it_writes(self) -> None:
        self.service._asset_get = lambda name: {"references": []}  # type: ignore[method-assign]
        self.assertEqual({f"{WIKI}/{name}" for name in self.READ_REVISIONS}, set(self.service._required_skill_revision_paths("wiki-show", {}, {}, [])))

    def test_a_skill_preview_records_the_revisions_of_the_files_it_reads(self) -> None:
        self.service._asset_get = lambda name: {"references": []}  # type: ignore[method-assign]
        text = (self.root / FEATURE).read_bytes().decode("utf-8")
        question = "| 1 | Which points should a review summary highlight? | po | open |"
        changes = [{"path": FEATURE, "content": text.replace(question, question + "\n| 2 | How should the review be organized? | designer | open |")}]
        required = self.service._required_skill_revision_paths("ask", {FEATURE: changes[0]["content"]}, {FEATURE: text}, [])
        preview = self.service.preview_skill(self.agent, "ask", changes, read_revisions=read_revisions(self.root, required))
        self.assertEqual(self.FEATURE_REVISIONS, standard(self.root / path for path in preview["source_map"]))

    def test_the_board_history_revisions_include_every_wiki_page(self) -> None:
        self.assertTrue({f"{WIKI}/{name}" for name in self.ALL} <= self.service._all_board_revision_paths())

    def test_the_preflight_of_a_transition_watches_these_files(self) -> None:
        features = read_feature_pages(self.wiki)
        evaluation = evaluate_transition_summaries(
            self.root,
            features=features,
            lint_result=lint_wiki(self.root),
            inspection=inspect_workspace(self.root),
            initial_fingerprint=workspace_fingerprint(self.root),
        )
        sources = evaluation.transitions_by_path[str(features[0].page.path)]["sources"]
        self.assertEqual(list(self.SOURCES), [Path(source).name for source in sources if Path(source).name in self.ALL])
        spec = next(item for item in ACTION_SPECS if item.action == "po-handoff")
        listed = _transition_sources(self.root, features[0], spec, [], [])
        self.assertEqual(list(self.SOURCES), [Path(source).name for source in listed if Path(source).name in self.ALL])

    def test_a_transition_is_gated_by_exactly_the_required_files(self) -> None:
        feature = read_feature_pages(self.wiki)[0]
        for name in self.ALL:
            with self.subTest(name=name):
                path = self.wiki / name
                content = path.read_bytes()
                path.unlink()
                try:
                    checks = _relevant_integrity_checks(feature, lint_wiki(self.root))
                finally:
                    path.write_bytes(content)
                gated = {Path(check["path"]).name for check in checks if check["code"] == "source-integrity:missing-required-wiki-file"}
                self.assertEqual({name} if name in self.REQUIRED else set(), gated)

    def test_an_unreadable_required_file_is_reported_by_a_transition_check(self) -> None:
        feature = read_feature_pages(self.wiki)[0]
        for name in self.ALL:
            with self.subTest(name=name):
                path = self.wiki / name
                content = path.read_bytes()
                path.write_bytes(b"\xff\xfe\xfa invalid utf-8 \xc3\x28")
                try:
                    checks = _relevant_integrity_checks(feature, lint_wiki(self.root))
                finally:
                    path.write_bytes(content)
                unreadable = {Path(check["path"]).name for check in checks if check["code"] == "source-integrity:unreadable-required-wiki-file"}
                self.assertEqual({name} if name in self.REQUIRED else set(), unreadable)


class PinnedBehaviourTests(StandardFileBehaviour, unittest.TestCase):
    """The lists as they were before the manifest."""

    ALL = ALL
    # Lint reports each as missing; a board refuses to adopt a workspace without them; they gate lifecycle actions.
    REQUIRED = ("SCHEMA.md", "LIFECYCLE.md", "ACTIONS.md", "index.md", "status-board.md")
    # The protocol documents that carry `schema-version: 1`.
    VERSIONED = ("SCHEMA.md", "LIFECYCLE.md", "ACTIONS.md")
    # The files the board service writes itself.
    MANAGED = ("index.md", "status-board.md", "log.md")
    # The files the general index never lists.
    UNINDEXED = ("index.md", "log.md")
    # The revisions a lifecycle transition records, a feature write records, and a skill must have read.
    TRANSITION_REVISIONS = {"SCHEMA.md", "LIFECYCLE.md", "SETTINGS.md", "ACTIONS.md"}
    FEATURE_REVISIONS = {"SCHEMA.md", "LIFECYCLE.md", "SETTINGS.md"}
    READ_REVISIONS = {"SCHEMA.md", "LIFECYCLE.md", "SETTINGS.md", "index.md"}
    # The files a transition snapshot watches.
    SOURCES = ("SCHEMA.md", "LIFECYCLE.md", "ACTIONS.md", "index.md", "status-board.md")
    NON_SOURCE = {"SCHEMA.md", "LIFECYCLE.md", "ACTIONS.md", "SETTINGS.md", "status-board.md", "log.md"}
    NON_PAGE = {"_FORMAT.md", "BOARD.md", "PROJECT_FOUNDATION.md", "SCHEMA.md", "LIFECYCLE.md", "ACTIONS.md", "SETTINGS.md", "index.md", "status-board.md", "log.md", "WIKI_REPORT.md"}
    FIXED_LINES = {
        "SCHEMA.md": ("SCHEMA.md", "Wiki conventions and operational rules."),
        "LIFECYCLE.md": ("LIFECYCLE.md", "Feature, board and advisory protocol."),
        "ACTIONS.md": ("ACTIONS.md", "Lifecycle action registry, write scopes and action contracts."),
        "CONNECTED.md": ("CONNECTED.md", "How agents use the connected board and MCP service."),
        "SETTINGS.md": ("SETTINGS.md", "Project-level settings for wiki read and query behavior."),
        "status-board.md": ("Status board", "The status, owner and board review of every feature."),
    }


class ManifestBehaviourTests(StandardFileBehaviour, unittest.TestCase):
    """The same checks, with each expectation read from the manifest's category."""

    ALL = standard_files.names()
    REQUIRED = standard_files.names("required")
    VERSIONED = standard_files.names("versioned")
    MANAGED = standard_files.names("managed")
    UNINDEXED = standard_files.names("unindexed")
    TRANSITION_REVISIONS = set(standard_files.revision_names("transition"))
    FEATURE_REVISIONS = set(standard_files.revision_names("feature"))
    READ_REVISIONS = set(standard_files.revision_names("read"))
    SOURCES = standard_files.revision_names("sources")
    NON_SOURCE = set(standard_files.names("non_source"))
    NON_PAGE = {"_FORMAT.md", "BOARD.md", "PROJECT_FOUNDATION.md", "WIKI_REPORT.md", *standard_files.names("non_page")}
    FIXED_LINES = standard_files.index_lines()

    def test_the_refusal_to_supply_a_managed_file_names_every_managed_file(self) -> None:
        managed = standard_files.names("managed")
        with self.assertRaises(BoardError) as refused:
            self.service.preview_skill(self.agent, "ask", [{"path": f"{WIKI}/{managed[0]}", "content": "x"}])
        self.assertEqual("managed_file", refused.exception.code)
        self.assertEqual(f"{', '.join(managed[:-1])} and {managed[-1]} are generated and merged by BoardService.", str(refused.exception))
        for name in managed:
            self.assertIn(name, str(refused.exception))

    def test_the_refusal_to_adopt_a_workspace_names_every_required_file(self) -> None:
        (self.wiki / "status-board.md").unlink()
        reason = BoardService(self.root)._read_only_reason
        self.assertIsNotNone(reason)
        for name in standard_files.names("required"):
            self.assertIn(name, reason)


class ManifestTests(unittest.TestCase):
    def test_each_standard_file_is_listed_once_and_the_order_is_the_products(self) -> None:
        self.assertEqual(ALL, standard_files.names())
        self.assertEqual(len(ALL), len(set(standard_files.names())))

    def test_the_categories_of_each_file(self) -> None:
        table = {
            "required": ("SCHEMA.md", "LIFECYCLE.md", "ACTIONS.md", "index.md", "status-board.md"),
            "gating": ("SCHEMA.md", "LIFECYCLE.md", "ACTIONS.md", "index.md", "status-board.md"),
            "managed": ("index.md", "status-board.md", "log.md"),
            "versioned": ("SCHEMA.md", "LIFECYCLE.md", "ACTIONS.md"),
            "non_source": ("SCHEMA.md", "LIFECYCLE.md", "ACTIONS.md", "SETTINGS.md", "status-board.md", "log.md"),
            "non_page": ("SCHEMA.md", "LIFECYCLE.md", "ACTIONS.md", "SETTINGS.md", "index.md", "status-board.md", "log.md"),
            "unindexed": ("index.md", "log.md"),
        }
        self.assertEqual(set(table), set(standard_files.CATEGORIES))
        for category, expected in table.items():
            with self.subTest(category=category):
                self.assertEqual(expected, standard_files.names(category))

    def test_the_revision_scopes_of_each_file(self) -> None:
        table = {
            "write": ("SCHEMA.md", "LIFECYCLE.md"),
            "feature": ("SCHEMA.md", "LIFECYCLE.md", "SETTINGS.md"),
            "transition": ("SCHEMA.md", "LIFECYCLE.md", "ACTIONS.md", "SETTINGS.md"),
            "read": ("SCHEMA.md", "LIFECYCLE.md", "SETTINGS.md", "index.md"),
            "sources": ("SCHEMA.md", "LIFECYCLE.md", "ACTIONS.md", "index.md", "status-board.md"),
        }
        self.assertEqual(set(table), set(standard_files.REVISION_SCOPES))
        for scope, expected in table.items():
            with self.subTest(scope=scope):
                self.assertEqual(expected, standard_files.revision_names(scope))

    def test_a_category_or_scope_the_manifest_does_not_have_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            standard_files.names("requird")
        with self.assertRaises(ValueError):
            standard_files.revision_names("feture")
        with self.assertRaises(ValueError):
            standard_files.StandardFile("X.md", revision=("feture",))

    def test_every_file_is_shipped_by_the_template(self) -> None:
        shipped = {path.name.removesuffix(".jinja") for path in (REPOSITORY / "template" / "knowledge" / "wiki").iterdir() if path.is_file()}
        self.assertEqual(set(), set(standard_files.names()) - shipped)

    def test_the_schema_lists_the_standard_files(self) -> None:
        schema = (REPOSITORY / "template" / "knowledge" / "wiki" / "SCHEMA.md").read_text(encoding="utf-8")
        # The directory tree shows the files of the wiki root at this indent.
        listed = set(re.findall(r"^    [├└]── (\S+\.md)\s", schema, re.MULTILINE))
        # The tree also shows the single pages and the generated report, which are not standard files.
        self.assertEqual(set(standard_files.names()) - {"CONNECTED.md"}, listed - {"direction.md", "roadmap.md", "WIKI_REPORT.md"})
        # CONNECTED.md is described with the connected workflow, by its path.
        self.assertIn(standard_files.wiki_path("CONNECTED.md"), schema)

    def test_no_module_of_prism_keeps_its_own_list_of_the_standard_files(self) -> None:
        names = {*standard_files.names(), *(standard_files.wiki_path(name) for name in standard_files.names())}
        offenders: list[str] = []
        for path in sorted((REPOSITORY / "prism_cli").glob("*.py")):
            if path.name == "standard_files.py":
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                elements = node.elts if isinstance(node, (ast.Tuple, ast.List, ast.Set)) else node.keys if isinstance(node, ast.Dict) else []
                found = {item.value for item in elements if isinstance(item, ast.Constant) and item.value in names}
                if len(found) > 1:
                    offenders.append(f"{path.name}:{node.lineno}: {sorted(found)}")
        self.assertEqual([], offenders)


class ExtraEntryTests(unittest.TestCase):
    """A file added to the manifest, with every category, takes part in each consumer without another edit."""

    def setUp(self) -> None:
        self.root = installed_workspace(self)
        self.wiki = self.root / WIKI
        self.extra = f"{WIKI}/{EXTRA}"
        (self.wiki / EXTRA).write_text("---\nschema-version: 1\n---\n# Extra\n", encoding="utf-8", newline="\n")
        entry = standard_files.StandardFile(EXTRA, required=True, revision=standard_files.REVISION_SCOPES, gating=True, versioned=True)
        patcher = patch.object(standard_files, "STANDARD_FILES", (*standard_files.STANDARD_FILES, entry))
        patcher.start()
        self.addCleanup(patcher.stop)
        write_index(self.root)
        self.service = BoardService(self.root).start()
        self.addCleanup(self.service.close)
        agent = self.service.create_participant("Writer", "agent", writable=True)
        self.agent = self.service.authenticate(agent["token"])
        human = self.service.create_participant("Human", "human", writable=True, roles="po")
        self.human = self.service.authenticate(human["token"], via_session=True)

    def test_lint_requires_the_file_and_its_schema_version(self) -> None:
        def codes(code: str) -> list[str]:
            return [Path(item.path).name for item in lint_wiki(self.root).diagnostics if item.code == code]

        self.assertNotIn(EXTRA, codes("missing-required-wiki-file"))
        self.assertNotIn(EXTRA, codes("missing-schema-version"))
        (self.wiki / EXTRA).write_text("# Extra\n", encoding="utf-8", newline="\n")
        self.assertIn(EXTRA, codes("missing-schema-version"))
        (self.wiki / EXTRA).unlink()
        self.assertIn(EXTRA, codes("missing-required-wiki-file"))

    def test_a_board_adopts_a_workspace_only_with_the_file(self) -> None:
        self.assertIsNotNone(BoardServiceIdentity(self.root))
        (self.wiki / EXTRA).unlink()
        self.assertIsNone(BoardServiceIdentity(self.root))

    def test_the_board_recognizes_the_file_as_a_wiki_root_page(self) -> None:
        relative, _path = self.service._approved_source_path(self.extra)
        self.assertEqual(self.extra, relative)

    def test_a_candidate_workspace_carries_the_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.service._build_candidate_root(Path(directory), {}, [])
            self.assertTrue((Path(directory) / self.extra).is_file())

    def test_the_managed_file_message_follows_a_managed_entry(self) -> None:
        generated = standard_files.StandardFile("GENERATED.md", managed=True)
        with patch.object(standard_files, "STANDARD_FILES", (*standard_files.STANDARD_FILES, generated)):
            with self.assertRaises(BoardError) as refused:
                self.service.preview_skill(self.agent, "ask", [{"path": f"{WIKI}/GENERATED.md", "content": "x"}])
        self.assertEqual("managed_file", refused.exception.code)
        self.assertEqual("index.md, status-board.md, log.md and GENERATED.md are generated and merged by BoardService.", str(refused.exception))

    def test_the_refusal_to_adopt_a_workspace_names_the_file(self) -> None:
        (self.wiki / EXTRA).unlink()
        reason = BoardService(self.root)._read_only_reason
        self.assertIsNotNone(reason)
        self.assertIn(EXTRA, reason)

    def test_every_revision_scope_records_the_file(self) -> None:
        self.service._asset_get = lambda name: {"references": []}  # type: ignore[method-assign]
        feature = self.service._resolve_feature("F-001")
        self.assertIn(self.extra, self.service._feature_context_paths(feature["path"], feature["frontmatter"]))
        self.assertIn(self.extra, self.service._transition_context_paths(feature["path"], feature["frontmatter"]))
        self.assertIn(self.extra, self.service._required_skill_revision_paths("wiki-show", {}, {}, []))

    def test_a_skill_preview_records_the_file_and_a_change_to_it_makes_the_preview_stale(self) -> None:
        self.service._asset_get = lambda name: {"references": []}  # type: ignore[method-assign]
        text = (self.root / FEATURE).read_bytes().decode("utf-8")
        question = "| 1 | Which points should a review summary highlight? | po | open |"
        changes = [{"path": FEATURE, "content": text.replace(question, question + "\n| 2 | How should the review be organized? | designer | open |")}]
        required = self.service._required_skill_revision_paths("ask", {FEATURE: changes[0]["content"]}, {FEATURE: text}, [])
        revisions = read_revisions(self.root, required)
        preview = self.service.preview_skill(self.agent, "ask", changes, read_revisions=revisions)
        self.assertIn(self.extra, preview["source_map"])
        (self.wiki / EXTRA).write_text("---\nschema-version: 1\n---\n# Extra, changed\n", encoding="utf-8", newline="\n")
        with self.assertRaises(BoardError) as stale:
            self.service.preview_skill(self.agent, "ask", changes, read_revisions=revisions)
        self.assertEqual(409, stale.exception.status)
        self.assertIn(self.extra, stale.exception.message)

    def test_a_transition_preview_records_the_file_and_a_change_to_it_changes_the_revision(self) -> None:
        inputs = {"semantic_review_acknowledged": True}
        preview = self.service.preview_transition(self.human, "F-001", "po-handoff", inputs)
        digest = hashlib.sha256((self.wiki / EXTRA).read_bytes()).hexdigest()
        self.assertEqual("sha256:" + digest, preview["source_map"][self.extra])
        (self.wiki / EXTRA).write_text("---\nschema-version: 1\n---\n# Extra, changed\n", encoding="utf-8", newline="\n")
        again = self.service.preview_transition(self.human, "F-001", "po-handoff", inputs)
        self.assertNotEqual(preview["source_revision"], again["source_revision"])

    def test_a_transition_snapshot_watches_the_file(self) -> None:
        feature = read_feature_pages(self.wiki)[0]
        spec = next(item for item in ACTION_SPECS if item.action == "po-handoff")
        self.assertIn(str(self.wiki / EXTRA), _transition_sources(self.root, feature, spec, [], []))

    def test_a_transition_is_gated_by_the_file(self) -> None:
        feature = read_feature_pages(self.wiki)[0]

        def checks_about_the_file(code: str) -> list[dict]:
            return [check for check in _relevant_integrity_checks(feature, lint_wiki(self.root)) if check["code"] == code and Path(check["path"]).name == EXTRA]

        self.assertEqual([], checks_about_the_file("source-integrity:missing-required-wiki-file"))
        (self.wiki / EXTRA).write_bytes(b"\xff\xfe\xfa invalid utf-8 \xc3\x28")
        self.assertEqual(1, len(checks_about_the_file("source-integrity:unreadable-required-wiki-file")))
        (self.wiki / EXTRA).unlink()
        self.assertEqual(1, len(checks_about_the_file("source-integrity:missing-required-wiki-file")))


if __name__ == "__main__":
    unittest.main()
