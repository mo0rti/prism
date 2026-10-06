"""Parsed wiki pages are shared inside one request and read-only for every consumer."""

import copy
import json
import os
import pickle
import shutil
import tempfile
import time
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import yaml

from prism_cli import wiki_model
from prism_cli.wiki_graph import build_graph
from prism_cli.wiki_lint import lint_wiki
from prism_cli.wiki_model import (
    FrozenDict,
    FrozenList,
    MarkdownPage,
    WikiPageScope,
    freeze,
    load_markdown_page,
    parse_markdown_text,
    read_feature_pages,
    read_markdown_page,
    wiki_read_scope,
    within_wiki_read_scope,
)
from prism_cli.wiki_query import wiki_blockers, wiki_owner, wiki_search, wiki_show
from prism_cli.wiki_transitions import build_board_transition_preflight, build_transition_preflight
from tests import real_temp  # noqa: F401


FIXTURES = Path(__file__).parent / "fixtures" / "wiki_contract"
PAGE = "---\nid: F-001\ntitle: Payout summary\nstatus: specified\napps:\n- backend\nnested:\n  items:\n  - a\n  - b\n---\n\n## Summary\nBody\n"
HOUR_NS = 3_600_000_000_000


def age(path: Path, nanoseconds: int = HOUR_NS) -> None:
    """Make ``path`` look old, so the scope may reuse its page without rereading the file."""

    stamp = time.time_ns() - nanoseconds
    os.utime(path, ns=(stamp, stamp))


class ParseCounter:
    """Count real parses of page text."""

    def __init__(self) -> None:
        self.calls = 0
        self._original = wiki_model.parse_markdown_text
        self._patch = patch.object(wiki_model, "parse_markdown_text", self._count)

    def _count(self, path: Path, text: str) -> MarkdownPage:
        self.calls += 1
        return self._original(path, text)

    def __enter__(self) -> "ParseCounter":
        self._patch.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._patch.stop()


class ReadOnlyPageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.page = parse_markdown_text(Path("page.md"), PAGE)

    def test_frontmatter_and_parse_errors_refuse_in_place_changes(self) -> None:
        frontmatter = self.page.frontmatter
        for change in (
            lambda: frontmatter.__setitem__("status", "done"),
            lambda: frontmatter.__delitem__("title"),
            lambda: frontmatter.update(status="done"),
            lambda: frontmatter.pop("title"),
            lambda: frontmatter.popitem(),
            lambda: frontmatter.setdefault("extra", 1),
            lambda: frontmatter.clear(),
            lambda: frontmatter["apps"].append("ios"),
            lambda: frontmatter["apps"].__setitem__(0, "ios"),
            lambda: frontmatter["apps"].sort(),
            lambda: frontmatter["nested"]["items"].extend(["c"]),
            lambda: frontmatter["nested"].__setitem__("x", 1),
            lambda: self.page.parse_errors.append("x"),
        ):
            with self.assertRaises(TypeError):
                change()
        self.assertEqual("specified", frontmatter["status"])
        self.assertEqual(["backend"], frontmatter["apps"])
        self.assertEqual({"items": ["a", "b"]}, frontmatter["nested"])

    def test_frozen_containers_behave_like_plain_ones_for_readers(self) -> None:
        frontmatter = self.page.frontmatter
        self.assertIsInstance(frontmatter, dict)
        self.assertIsInstance(frontmatter["apps"], list)
        self.assertEqual(
            {"id": "F-001", "title": "Payout summary", "status": "specified", "apps": ["backend"], "nested": {"items": ["a", "b"]}},
            frontmatter,
        )
        self.assertEqual(json.dumps(dict(frontmatter), sort_keys=True), json.dumps(frontmatter, sort_keys=True))
        self.assertEqual(["id", "title", "status", "apps", "nested"], list(frontmatter))

    def test_copies_are_ordinary_and_changing_them_does_not_leak(self) -> None:
        frontmatter = self.page.frontmatter
        shallow = dict(frontmatter)
        shallow["status"] = "done"
        deep = copy.deepcopy(frontmatter)
        deep["apps"].append("ios")
        deep["nested"]["items"].append("c")
        listed = list(frontmatter["apps"])
        listed.append("ios")
        merged = {**frontmatter, "status": "done"}

        self.assertIs(type(deep), dict)
        self.assertIs(type(deep["apps"]), list)
        self.assertIs(type(copy.copy(frontmatter)), dict)
        self.assertIs(type(frontmatter.copy()), dict)
        self.assertIs(type(pickle.loads(pickle.dumps(frontmatter))), dict)
        self.assertEqual("done", merged["status"])
        self.assertEqual("specified", frontmatter["status"])
        self.assertEqual(["backend"], frontmatter["apps"])
        self.assertEqual(["a", "b"], frontmatter["nested"]["items"])

    def test_a_page_built_with_plain_containers_is_frozen_without_touching_the_input(self) -> None:
        source = {"apps": ["backend"]}
        errors = ["oops"]
        page = MarkdownPage(path=Path("x.md"), frontmatter=source, body="", parse_errors=errors)

        self.assertIsInstance(page.frontmatter, FrozenDict)
        self.assertIsInstance(page.parse_errors, FrozenList)
        source["apps"].append("ios")
        errors.append("more")
        self.assertEqual(["backend"], page.frontmatter["apps"])
        self.assertEqual(["oops"], page.parse_errors)
        self.assertIs(page.frontmatter, freeze(page.frontmatter))

    def test_yaml_that_refers_to_itself_is_frozen_without_looping(self) -> None:
        loaded = yaml.safe_load("&a {self: *a, items: &b [*b]}")
        frozen = freeze(loaded)

        self.assertIsInstance(frozen, FrozenDict)
        self.assertIs(frozen, frozen["self"])
        self.assertIs(frozen["items"], frozen["items"][0])
        with self.assertRaises(TypeError):
            frozen["x"] = 1


class PageScopeTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="prism-page-scope-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / "F-001-payout.md"
        self.path.write_text(PAGE, encoding="utf-8", newline="\n")
        age(self.path)

    def test_without_a_scope_every_read_parses_the_file(self) -> None:
        with ParseCounter() as counter:
            first = load_markdown_page(self.path)
            second = load_markdown_page(self.path)

        self.assertEqual(2, counter.calls)
        self.assertEqual(first, second)
        self.assertIsNone(wiki_model._PAGE_SCOPE.get())

    def test_inside_a_scope_a_page_is_parsed_once_and_not_reopened(self) -> None:
        opened: list[Path] = []
        original = Path.read_text

        def counting_read_text(path: Path, *args: object, **kwargs: object) -> str:
            opened.append(path)
            return original(path, *args, **kwargs)

        with ParseCounter() as counter, patch.object(Path, "read_text", counting_read_text):
            with wiki_read_scope():
                first = load_markdown_page(self.path)
                second = load_markdown_page(self.path)
                third = load_markdown_page(self.path)

        self.assertEqual(1, counter.calls)
        self.assertEqual([self.path], opened)
        self.assertIs(first, second)
        self.assertIs(first, third)

    def test_a_scope_ends_with_its_request_and_nothing_survives_it(self) -> None:
        with ParseCounter() as counter:
            with wiki_read_scope() as first_scope:
                load_markdown_page(self.path)
            self.assertIsNone(wiki_model._PAGE_SCOPE.get())
            with wiki_read_scope() as second_scope:
                load_markdown_page(self.path)

        self.assertIsNot(first_scope, second_scope)
        self.assertEqual(2, counter.calls)

    def test_a_scope_ends_when_the_request_fails(self) -> None:
        with self.assertRaises(RuntimeError):
            with wiki_read_scope():
                raise RuntimeError("stop")
        self.assertIsNone(wiki_model._PAGE_SCOPE.get())

        @within_wiki_read_scope
        def fail() -> None:
            raise RuntimeError("stop")

        with self.assertRaises(RuntimeError):
            fail()
        self.assertIsNone(wiki_model._PAGE_SCOPE.get())

    def test_a_nested_scope_joins_the_outer_one(self) -> None:
        @within_wiki_read_scope
        def inner() -> WikiPageScope:
            return wiki_model._PAGE_SCOPE.get()

        with wiki_read_scope() as outer:
            self.assertIs(outer, inner())
            with wiki_read_scope() as nested:
                self.assertIs(outer, nested)
        self.assertIsNone(wiki_model._PAGE_SCOPE.get())

    def test_a_changed_file_is_never_served_stale(self) -> None:
        with wiki_read_scope():
            before = load_markdown_page(self.path)
            self.path.write_text(PAGE.replace("Payout summary", "Payout overview"), encoding="utf-8", newline="\n")
            after = load_markdown_page(self.path)
            self.path.write_text(PAGE.replace("Payout summary", "Payout summary!"), encoding="utf-8", newline="\n")
            last = load_markdown_page(self.path)

        self.assertEqual("Payout summary", before.frontmatter["title"])
        self.assertEqual("Payout overview", after.frontmatter["title"])
        self.assertEqual("Payout summary!", last.frontmatter["title"])

    def test_a_recent_file_is_confirmed_by_content_every_time(self) -> None:
        recent = self.root / "recent.md"
        recent.write_text(PAGE, encoding="utf-8", newline="\n")
        stamp = time.time_ns()
        os.utime(recent, ns=(stamp, stamp))
        scope = WikiPageScope(wall_clock_ns=lambda: stamp + 1_000_000)
        opened: list[Path] = []
        original = Path.read_text

        def counting_read_text(path: Path, *args: object, **kwargs: object) -> str:
            opened.append(path)
            return original(path, *args, **kwargs)

        with ParseCounter() as counter, patch.object(Path, "read_text", counting_read_text):
            first = scope.load(recent)
            second = scope.load(recent)
            # Same size, same modification time: only the content tells them apart.
            recent.write_text(PAGE.replace("Payout summary", "Payout summarz"), encoding="utf-8", newline="\n")
            os.utime(recent, ns=(stamp, stamp))
            third = scope.load(recent)

        self.assertEqual([recent, recent, recent], opened)
        self.assertEqual(2, counter.calls)
        self.assertIs(first, second)
        self.assertEqual("Payout summarz", third.frontmatter["title"])

    def test_an_old_file_is_trusted_without_reading_it_again(self) -> None:
        scope = WikiPageScope()
        opened: list[Path] = []
        original = Path.read_text

        def counting_read_text(path: Path, *args: object, **kwargs: object) -> str:
            opened.append(path)
            return original(path, *args, **kwargs)

        with patch.object(Path, "read_text", counting_read_text):
            first = scope.load(self.path)
            second = scope.load(self.path)

        self.assertEqual([self.path], opened)
        self.assertIs(first, second)

    def test_a_file_that_disappears_or_cannot_be_read_gives_the_unreadable_page(self) -> None:
        with wiki_read_scope():
            load_markdown_page(self.path)
            self.path.unlink()
            page = load_markdown_page(self.path)

        self.assertEqual({}, page.frontmatter)
        self.assertEqual(read_markdown_page(self.path), page)
        self.assertTrue(page.parse_errors[0].startswith("Unable to read file"))

    def test_scoped_pages_equal_unscoped_pages_for_good_and_bad_files(self) -> None:
        samples = {
            "good.md": PAGE,
            "no-frontmatter.md": "just text\n",
            "bad-yaml.md": "---\nid: [unclosed\n---\nbody\n",
            "not-a-mapping.md": "---\n- a\n- b\n---\nbody\n",
            "bom-and-crlf.md": "﻿---\r\nid: F-002\r\n---\r\nbody\r\n",
            "empty-frontmatter.md": "---\n\n---\nbody\n",
        }
        paths = []
        for name, text in samples.items():
            path = self.root / name
            path.write_bytes(text.encode("utf-8"))
            age(path)
            paths.append(path)
        paths.append(self.root / "missing.md")

        with wiki_read_scope():
            scoped = [load_markdown_page(path) for path in paths]
            again = [load_markdown_page(path) for path in paths]

        self.assertEqual([read_markdown_page(path) for path in paths], scoped)
        self.assertEqual(scoped, again)


class ConsumerTests(unittest.TestCase):
    """Sharing pages changes no output and no consumer changes a shared page."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="prism-page-consumers-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)

    def workspace(self, name: str) -> Path:
        destination = self.base / name
        shutil.copytree(FIXTURES / name, destination)
        for path in destination.rglob("*.md"):
            age(path)
        return destination

    @staticmethod
    def outputs(root: Path) -> dict[str, object]:
        graph = build_graph(root)

        def strip(value: object) -> object:
            if isinstance(value, dict):
                return {key: strip(item) for key, item in value.items() if key != "observed_at"}
            if isinstance(value, list):
                return [strip(item) for item in value]
            return value

        results: dict[str, object] = {
            "lint": lint_wiki(root, today=date(2026, 9, 8)).to_dict(),
            "graph": strip(graph),
            "blockers": wiki_blockers(root),
            "search": wiki_search(root, "payout"),
            "owner": wiki_owner(root, "po"),
            "show": wiki_show(root, "F-001"),
            "preflight": strip(build_transition_preflight(root, "F-001")),
        }
        for action in ("po-handoff", "design-start", "dev-start"):
            results[f"board {action}"] = build_board_transition_preflight(root, "F-001", action)
        return json.loads(json.dumps(results, sort_keys=True, default=str))

    def test_sharing_pages_does_not_change_any_output(self) -> None:
        for name in ("healthy", "partial"):
            with self.subTest(fixture=name):
                root = self.workspace(name)
                shared = self.outputs(root)
                with patch.object(WikiPageScope, "load", lambda scope, path: read_markdown_page(path)):
                    unshared = self.outputs(root)
                self.assertEqual(unshared, shared)

    def test_no_consumer_changes_the_pages_it_shares(self) -> None:
        root = self.workspace("partial")
        wiki = root / "knowledge" / "wiki"
        overrides = {"status": "done", "apps": ["web-user-app"], "revalidation": ["design"]}
        with wiki_read_scope():
            snapshot = [(feature.page.path, copy.deepcopy(feature.page.frontmatter), feature.page.body) for feature in read_feature_pages(wiki)]
            self.assertTrue(snapshot)
            for action in ("po-handoff", "design-start", "dev-start"):
                build_board_transition_preflight(root, "F-001", action, frontmatter_overrides=overrides, advisory_override=("skipped", "reason"))
            lint_wiki(root)
            build_graph(root)
            wiki_show(root, "F-001")
            after = [(feature.page.path, copy.deepcopy(feature.page.frontmatter), feature.page.body) for feature in read_feature_pages(wiki)]

        self.assertEqual(snapshot, after)

    def test_an_override_for_a_preflight_does_not_reach_the_next_reader(self) -> None:
        root = self.workspace("partial")
        wiki = root / "knowledge" / "wiki"
        with wiki_read_scope():
            original = [feature.status for feature in read_feature_pages(wiki)]
            build_board_transition_preflight(root, "F-001", "po-handoff", frontmatter_overrides={"status": "done"})
            self.assertEqual(original, [feature.status for feature in read_feature_pages(wiki)])


if __name__ == "__main__":
    unittest.main()
