"""Mechanical link lint: relative links, anchors, `sources` entries and `repo:` links into external repositories.

A relative link or a `sources` entry that does not resolve is `broken-link` (error). An anchor with no heading is
`broken-anchor` (warning). A `repo:<repository-id>/<path>` link resolves through `prism.local.yml`; an unresolved
repository is one `external-repository-unresolved` warning and its links are skipped. Lint only checks that a path
exists in an external checkout and never writes there.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

import yaml

from prism_cli.wiki_lint import lint_wiki
from tests import real_temp  # noqa: F401
from tests.manifest_fixtures import manifest_data
from tests.wiki_files import copy_template_knowledge, write_index

REMOTE = "https://example.com/acme/mobile-apps.git"
TOPIC_HEAD = "---\nkind: topic\ntitle: {title}\nstatus: current\nsources: {sources}\n---\n\n"
TOPIC_BODY = "## Summary\nThe page states a fact.\n\n## Key points\n{points}\n\n## Related pages\nNone yet.\n"


def topic(title: str = "Payments", sources: str = "[]", points: str = "- **Assumed:** Nothing is confirmed.") -> str:
    return TOPIC_HEAD.format(title=title, sources=sources) + TOPIC_BODY.format(points=points)


class LinkCase(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "workspace"
        self.root.mkdir()
        copy_template_knowledge(self.root / "knowledge")
        (self.root / "backend").mkdir()
        self.write_manifest()
        self.wiki = self.root / "knowledge" / "wiki"

    def write_manifest(self, *, external: bool = False) -> None:
        data = manifest_data("Links", ["backend"], slug="links")
        if external:
            data["repositories"] = [{"id": "mobile-apps", "remote": REMOTE}]
            data["apps"].append({"id": "partner-android", "name": "Partner", "stack": "android-compose", "repository": "mobile-apps", "path": "apps/partner"})
        (self.root / "prism.workspace.yml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    def write(self, relative: str, text: str) -> Path:
        path = self.wiki / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        return path

    def lint(self):
        write_index(self.root)
        return lint_wiki(self.root)

    def found(self, code: str) -> list:
        return [item for item in self.lint().diagnostics if item.code == code]

    def checkout(self, *files: str) -> Path:
        checkout = self.base / "mobile-apps"
        for relative in files:
            target = checkout / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("content\n", encoding="utf-8")
        checkout.mkdir(exist_ok=True)
        (self.root / "prism.local.yml").write_text(yaml.safe_dump({"repositories": {"mobile-apps": str(checkout)}}), encoding="utf-8")
        return checkout


class RelativeLinkTests(LinkCase):
    def test_a_link_that_resolves_to_a_file_or_a_folder_is_clean_and_a_broken_one_is_an_error_with_its_line(self) -> None:
        (self.root / "backend" / "notes.txt").write_text("a note\n", encoding="utf-8")
        page = self.write(
            "topics/payments.md",
            topic(points="- **Assumed:** Fine.\n- See [a folder](../../../backend) and [a file](../../../backend/notes.txt).\n- See [missing](../research/nowhere.md).\n"),
        )

        broken = self.found("broken-link")

        self.assertEqual(1, len(broken))
        self.assertEqual("error", broken[0].severity)
        self.assertEqual(str(page), broken[0].path)
        self.assertIn("`../research/nowhere.md`", broken[0].message)
        lines = page.read_text(encoding="utf-8").splitlines()
        number = next(index for index, line in enumerate(lines, start=1) if "nowhere.md" in line)
        self.assertIn(f"(line {number})", broken[0].message)

    def test_every_line_of_a_repeated_broken_link_is_reported_once(self) -> None:
        self.write("topics/payments.md", topic(points="- **Assumed:** [gone](../research/gone.md)\n- **Assumed:** [gone again](../research/gone.md)"))
        broken = self.found("broken-link")
        self.assertEqual(1, len(broken))
        self.assertRegex(broken[0].message, r"\(lines \d+, \d+\)")

    def test_links_in_code_urls_images_and_absolute_paths_are_not_checked(self) -> None:
        self.write(
            "topics/payments.md",
            topic(
                points=(
                    "- **Assumed:** Use `[inline](../research/inline.md)`.\n"
                    "- **Assumed:** [web](https://example.com/nowhere.md) and [mail](mailto:a@example.com) and [abs](/nowhere.md).\n"
                    "- ![image](../research/image.png)\n"
                    "\n```text\n[fenced](../research/fenced.md)\n```"
                )
            ),
        )
        self.assertEqual([], self.found("broken-link"))

    def test_a_link_that_leaves_the_workspace_is_broken(self) -> None:
        (self.base / "outside.md").write_text("outside\n", encoding="utf-8")
        self.write("topics/payments.md", topic(points="- **Assumed:** [out](../../../../outside.md)"))
        broken = self.found("broken-link")
        self.assertEqual(1, len(broken))
        self.assertIn("leaves the workspace", broken[0].message)
        self.assertIn("repo:<repository-id>/<path>", broken[0].message)

    def test_the_format_and_schema_files_are_not_checked_for_links(self) -> None:
        # SCHEMA.md and every _FORMAT.md show example links that do not resolve.
        self.assertIn("(../../../wiki/features/F-001-slug.md)", (self.wiki / "SCHEMA.md").read_text(encoding="utf-8"))
        self.assertIn("(../../intake/processed/YYYY-MM-DD-slug/notes.md)", (self.wiki / "personas" / "_FORMAT.md").read_text(encoding="utf-8"))
        self.assertEqual([], self.found("broken-link"))

    def test_a_link_to_a_wiki_page_that_exists_is_clean(self) -> None:
        self.write("topics/other.md", topic("Other"))
        self.write("topics/payments.md", topic(points="- **Assumed:** See [other](other.md) and [again](../topics/other.md)."))
        self.assertEqual([], self.found("broken-link"))

    def test_the_old_code_name_is_gone(self) -> None:
        self.write("topics/payments.md", topic(points="- **Assumed:** [gone](gone.md)"))
        self.assertEqual([], self.found("broken-wiki-link"))


class AnchorTests(LinkCase):
    def test_an_anchor_is_checked_against_the_headings_of_its_target(self) -> None:
        self.write("topics/other.md", topic("Other"))
        self.write(
            "topics/payments.md",
            topic(
                points=(
                    "- **Assumed:** [ok](other.md#related-pages) and [ok too](other.md#Key-Points) and [here](#key-points).\n"
                    "- **Assumed:** [bad](other.md#no-such-heading) and [bad here](#nothing-here)."
                )
            ),
        )

        anchors = self.found("broken-anchor")

        self.assertEqual(2, len(anchors))
        self.assertEqual({"warning"}, {item.severity for item in anchors})
        messages = " ".join(item.message for item in anchors)
        self.assertIn("#no-such-heading", messages)
        self.assertIn("#nothing-here", messages)
        self.assertEqual([], self.found("broken-link"))

    def test_a_repeated_heading_and_an_explicit_html_anchor_are_anchors(self) -> None:
        self.write("topics/other.md", topic("Other", points='- **Assumed:** Fine.\n\n## Notes\nOne.\n\n## Notes\nTwo.\n\n<a id="custom-anchor"></a>'))
        self.write("topics/payments.md", topic(points="- **Assumed:** [a](other.md#notes), [b](other.md#notes-1), [c](other.md#custom-anchor)."))
        self.assertEqual([], self.found("broken-anchor"))

    def test_an_anchor_on_a_missing_page_is_one_broken_link_and_no_anchor_finding(self) -> None:
        self.write("topics/payments.md", topic(points="- **Assumed:** [gone](gone.md#heading)"))
        self.assertEqual(1, len(self.found("broken-link")))
        self.assertEqual([], self.found("broken-anchor"))


class SourcesTests(LinkCase):
    def test_a_feature_source_that_does_not_exist_is_a_broken_link_naming_the_entry(self) -> None:
        from tests.test_board_service import _journey_feature_page
        from tests.wiki_files import write_status_board

        (self.root / "knowledge/intake/processed/2026-10-06-brief").mkdir(parents=True)
        (self.root / "knowledge/intake/processed/2026-10-06-brief/brief.md").write_text("brief\n", encoding="utf-8")
        page = _journey_feature_page(
            "F-001",
            "Payments",
            "raw",
            "po",
            ["knowledge/intake/processed/2026-10-06-brief/brief.md", "knowledge/intake/processed/2026-10-06-brief", "knowledge/intake/processed/2026-10-06-gone/brief.md", "https://example.com/doc"],
            ["| 1 | Which details? | po | open |"],
        )
        path = self.write("features/F-001-payments.md", page)
        write_status_board(self.root, "| F-001 | Payments | raw | po | not-needed |\n")

        broken = self.found("broken-link")

        self.assertEqual(1, len(broken))
        self.assertEqual(str(path), broken[0].path)
        self.assertEqual("F-001", broken[0].feature_id)
        self.assertIn("`sources` entry `knowledge/intake/processed/2026-10-06-gone/brief.md`", broken[0].message)
        number = next(index for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1) if "2026-10-06-gone" in line)
        self.assertIn(f"(line {number})", broken[0].message)

    def test_a_broken_source_never_gates_a_transition_but_a_broken_link_to_a_wiki_page_still_does(self) -> None:
        from prism_cli.wiki_transitions import build_transition_preflight
        from tests.test_board_service import _journey_feature_page
        from tests.wiki_files import write_status_board

        page = _journey_feature_page("F-001", "Payments", "specified", "po", ["knowledge/intake/processed/2026-10-06-gone/brief.md"], ["| 1 | Which details? | po | resolved: These. |"])
        path = self.write("features/F-001-payments.md", page)
        write_status_board(self.root, "| F-001 | Payments | specified | po | not-needed |\n")

        def integrity_checks() -> list[str]:
            write_index(self.root)
            checks = build_transition_preflight(self.root, "F-001")["facts"]["transition"]["checks"]
            return [item["code"] for item in checks if item["code"].startswith("source-integrity:")]

        self.assertEqual(1, len(self.found("broken-link")), "the missing source is reported")
        self.assertEqual([], integrity_checks(), "a missing source is not a gate")

        path.write_text(path.read_text(encoding="utf-8") + "\nSee [the design](../design/missing.md).\n", encoding="utf-8", newline="\n")
        self.assertEqual(["source-integrity:broken-link"], integrity_checks(), "a broken link to a page of the wiki is still a gate")

    def test_a_pending_source_names_the_processed_path_to_list(self) -> None:
        self.write("topics/payments.md", topic(sources="[knowledge/intake/pending/2026-10-06-brief]"))
        broken = self.found("broken-link")
        self.assertEqual(1, len(broken))
        self.assertIn("knowledge/intake/processed/2026-10-06-brief", broken[0].message)

    def test_free_text_and_urls_in_a_loose_source_field_are_not_checked_but_a_knowledge_path_is(self) -> None:
        persona = (
            "---\nid: P-001\nname: Reviewer\nsources:\n- the client call last week\n- https://example.com/survey\n- knowledge/intake/processed/2026-10-06-gone/notes.md\n---\n\n"
            "## Who they are\nA person assigned to review a document.\n\n## Goals\nRecord key points.\n\n## Pain points\nNotes get lost.\n\n"
            "## Features that serve this persona\nNone yet.\n"
        )
        rule = (
            "---\nid: BR-001\ntitle: Keep outcomes\nsource: the board meeting\n---\n\n## Rule\nA review keeps its outcome.\n\n"
            "## Rationale\nReviewers need to find it.\n\n## Affected features\nNone yet.\n\n## Exceptions\nNone.\n"
        )
        self.write("personas/reviewer.md", persona)
        self.write("business-rules/BR-001-keep-outcomes.md", rule)
        rule_gone = rule.replace("source: the board meeting", "source: knowledge/intake/processed/2026-10-06-gone/notes.md").replace("BR-001", "BR-002")
        self.write("business-rules/BR-002-gone.md", rule_gone)

        broken = self.found("broken-link")

        self.assertEqual({"reviewer.md", "BR-002-gone.md"}, {Path(item.path).name for item in broken})
        self.assertIn("`source` entry", next(item.message for item in broken if item.path.endswith("BR-002-gone.md")))

    def test_every_general_page_kind_checks_its_sources(self) -> None:
        pages = {
            "topics/a.md": topic("A", "[knowledge/gone-a.md]"),
            "research/b.md": "---\nkind: research\ntitle: B\nstatus: open\nsources: [knowledge/gone-b.md]\n---\n\n## Question\nWhy?\n\n## Summary\nBecause.\n\n## Findings\n- **Unknown:** Nothing.\n\n## Gaps\n- **Unknown:** All.\n",
            "plans/c.md": "---\nkind: plan\ntitle: C\nstatus: active\nsources: [knowledge/gone-c.md]\n---\n\n## Summary\nA plan.\n\n## Goal\nShip.\n\n## Current status\nStarted.\n\n## Next steps\n- **Proposed:** Go.\n\n## Blockers\nNo blockers.\n",
            "direction.md": "---\nkind: direction\nsources: [knowledge/gone-d.md]\n---\n\n## Summary\nThe direction.\n\n## Direction\n- **Proposed:** Forward.\n\n## Principles\n- Keep records.\n",
            "roadmap.md": "---\nkind: roadmap\nsources: [knowledge/gone-e.md]\n---\n\n## Summary\nWhat comes next.\n\n## Next\n- A step.\n\n## Later\n- Another.\n",
        }
        for relative, text in pages.items():
            self.write(relative, text)
        self.assertEqual({"a.md", "b.md", "c.md", "direction.md", "roadmap.md"}, {Path(item.path).name for item in self.found("broken-link")})


class ExternalRepositoryTests(LinkCase):
    LINK = "- **Assumed:** See [login](repo:mobile-apps/apps/partner/Login.kt)."

    def setUp(self) -> None:
        super().setUp()
        self.write_manifest(external=True)

    def test_an_unresolved_repository_is_one_warning_and_its_links_are_skipped(self) -> None:
        self.write("topics/a.md", topic("A", points=self.LINK + "\n- **Assumed:** [two](repo:mobile-apps/docs/two.md)"))
        self.write("topics/b.md", topic("B", sources="[repo:mobile-apps/docs/spec.md]", points=self.LINK))

        result = self.lint()

        unresolved = [item for item in result.diagnostics if item.code == "external-repository-unresolved"]
        self.assertEqual(1, len(unresolved))
        self.assertEqual("warning", unresolved[0].severity)
        self.assertIn("`mobile-apps`", unresolved[0].message)
        self.assertIn("prism.local.yml", unresolved[0].message)
        self.assertEqual([], [item for item in result.diagnostics if item.code == "broken-link"])
        self.assertTrue(result.is_clean)

    def test_a_workspace_with_no_link_into_the_repository_gets_no_finding_from_lint(self) -> None:
        self.write("topics/a.md", topic("A"))
        self.assertEqual([], self.found("external-repository-unresolved"))

    def test_a_resolved_repository_with_the_target_present_is_clean(self) -> None:
        self.checkout("apps/partner/Login.kt", "docs/spec.md")
        self.write("topics/a.md", topic("A", sources="[repo:mobile-apps/docs/spec.md]", points=self.LINK + "\n- **Assumed:** [folder](repo:mobile-apps/apps/partner)"))

        result = self.lint()

        self.assertEqual([], [item for item in result.diagnostics if item.code in {"broken-link", "external-repository-unresolved"}])

    def test_a_resolved_repository_with_the_target_missing_is_a_broken_link(self) -> None:
        self.checkout("apps/partner/Other.kt")
        page = self.write("topics/a.md", topic("A", sources="[repo:mobile-apps/docs/spec.md]", points=self.LINK))

        broken = self.found("broken-link")

        self.assertEqual(2, len(broken))
        self.assertEqual({str(page)}, {item.path for item in broken})
        self.assertTrue(all("`mobile-apps`" in item.message and "does not exist in the checkout" in item.message for item in broken))
        self.assertEqual([], self.found("external-repository-unresolved"))

    def test_an_undeclared_repository_and_a_malformed_link_are_broken_links(self) -> None:
        self.write(
            "topics/a.md",
            topic(
                "A",
                points=(
                    "- **Assumed:** [unknown](repo:other/file.md)\n"
                    "- **Assumed:** [no path](repo:mobile-apps)\n"
                    "- **Assumed:** [up](repo:mobile-apps/../x.md)\n"
                    "- **Assumed:** [no id](repo:/file.md)"
                ),
            ),
        )

        messages = [item.message for item in self.found("broken-link")]

        self.assertEqual(4, len(messages))
        self.assertTrue(any("does not declare" in message and "`other`" in message for message in messages))
        self.assertEqual(3, sum("is not a repository link" in message for message in messages))

    def test_the_workspace_repository_id_means_this_repository(self) -> None:
        (self.root / "backend" / "notes.txt").write_text("a note\n", encoding="utf-8")
        self.write("topics/a.md", topic("A", points="- **Assumed:** [yes](repo:workspace/backend/notes.txt) and [no](repo:workspace/backend/gone.txt)"))
        broken = self.found("broken-link")
        self.assertEqual(1, len(broken))
        self.assertIn("backend/gone.txt", broken[0].message)

    def test_lint_leaves_the_checkout_and_the_workspace_as_they_are(self) -> None:
        checkout = self.checkout("apps/partner/Login.kt")
        self.write("topics/a.md", topic("A", points=self.LINK + "\n- **Assumed:** [gone](repo:mobile-apps/gone.kt)"))
        write_index(self.root)

        def snapshot(base: Path) -> dict[str, tuple[bytes, int]]:
            return {path.relative_to(base).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns) for path in sorted(base.rglob("*")) if path.is_file()}

        before_checkout, before_workspace = snapshot(checkout), snapshot(self.root)
        lint_wiki(self.root)
        lint_wiki(self.root)
        self.assertEqual(before_checkout, snapshot(checkout))
        self.assertEqual(before_workspace, snapshot(self.root))

    def test_a_link_through_a_symlink_in_the_checkout_is_not_followed(self) -> None:
        checkout = self.checkout("real/file.md")
        try:
            os.symlink(checkout / "real", checkout / "alias", target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symbolic links are not available")
        self.write("topics/a.md", topic("A", points="- **Assumed:** [via alias](repo:mobile-apps/alias/file.md)"))
        broken = self.found("broken-link")
        self.assertEqual(1, len(broken))
        self.assertIn("symlink or reparse point", broken[0].message)



MARKER = "attacker.invalid"


class FilesystemSpy:
    """Fails the test when a filesystem call names a path that carries the marker of a hostile link.

    A rejected link must be refused as text: no `stat`, `lstat`, `realpath` (what `Path.resolve` calls),
    `exists` or directory scan may be made for it, because on Windows such a call on a UNC or a
    drive-qualified path reaches a network share or another volume.
    """

    NAMES = ("os.stat", "os.lstat", "os.scandir", "os.listdir", "os.path.realpath", "os.path.exists", "os.path.isfile", "os.path.isdir", "os.path.islink")

    def __init__(self, case: unittest.TestCase) -> None:
        self.case = case
        self.calls: list[str] = []

    def __enter__(self) -> "FilesystemSpy":
        from unittest.mock import patch

        self.patches = []
        for name in self.NAMES:
            module_name, attribute = name.rsplit(".", 1)
            module = os if module_name == "os" else os.path
            original = getattr(module, attribute)
            patcher = patch.object(module, attribute, side_effect=self._wrap(name, original))
            patcher.start()
            self.patches.append(patcher)
        return self

    def __exit__(self, *_exc: object) -> None:
        for patcher in self.patches:
            patcher.stop()

    def _wrap(self, name: str, original):
        def spy(*args, **kwargs):
            if any(MARKER in os.fsdecode(argument) for argument in args if isinstance(argument, (str, bytes, os.PathLike))):
                self.calls.append(f"{name}{args!r}")
                raise AssertionError(f"filesystem call for a hostile path: {name}{args!r}")
            return original(*args, **kwargs)

        return spy


HOSTILE_LINKS = {
    "encoded UNC with slashes": f"%2F%2F{MARKER}%2Fshare%2Fprobe.md",
    "encoded UNC with backslashes": f"%5C%5C{MARKER}%5Cshare%5Cprobe.md",
    "literal UNC with backslashes": f"\\\\{MARKER}\\share\\probe.md",
    "drive letter": f"C%3A%2F{MARKER}%2Fprobe.md",
    "drive letter without a slash": f"C%3A{MARKER}.md",
    "backslash": f"..%5C{MARKER}%5Cprobe.md",
    "double encoding": f"%252F%252F{MARKER}%252Fshare%252Fprobe.md",
    "parent escape": f"../../../../../../{MARKER}/probe.md",
    "encoded parent escape": f"..%2F..%2F..%2F..%2F..%2F..%2F{MARKER}%2Fprobe.md",
}


class HostileLinkTests(LinkCase):
    """A link on a proposed page is untrusted text: it is refused before it can reach the filesystem."""

    def lint_without_touching(self):
        write_index(self.root)
        with FilesystemSpy(self) as spy:
            result = lint_wiki(self.root)
        self.assertEqual([], spy.calls)
        return result

    def test_a_hostile_markdown_link_is_a_broken_link_and_causes_no_filesystem_call(self) -> None:
        for label, target in HOSTILE_LINKS.items():
            with self.subTest(label):
                self.write("topics/hostile.md", topic("Hostile", points=f"- **Assumed:** See [reference]({target})."))
                result = self.lint_without_touching()
                broken = [item for item in result.diagnostics if item.code == "broken-link"]
                self.assertEqual(1, len(broken), [item.message for item in result.diagnostics])
                self.assertEqual("error", broken[0].severity)
                self.assertTrue("safe relative path" in broken[0].message or "leaves the workspace" in broken[0].message, broken[0].message)

    def test_a_hostile_sources_entry_is_a_broken_link_and_causes_no_filesystem_call(self) -> None:
        from tests.test_board_service import _journey_feature_page
        from tests.wiki_files import write_status_board

        entries = {
            "UNC with backslashes": f"\\\\{MARKER}\\share\\probe.md",
            "backslash path": f"knowledge\\{MARKER}\\probe.md",
            "colon in a segment": f"knowledge/{MARKER}:probe.md",
            "drive-qualified segment": f"knowledge/C:{MARKER}/probe.md",
        }
        for label, entry in entries.items():
            with self.subTest(label):
                page = _journey_feature_page("F-001", "Payments", "raw", "po", [entry], ["| 1 | Which details? | po | open |"])
                self.write("features/F-001-payments.md", page)
                write_status_board(self.root, "| F-001 | Payments | raw | po | not-needed |\n")
                result = self.lint_without_touching()
                broken = [item for item in result.diagnostics if item.code == "broken-link"]
                self.assertEqual(1, len(broken), [item.message for item in result.diagnostics])
                self.assertIn("safe workspace path", broken[0].message)

    def test_a_hostile_repository_link_is_refused_and_causes_no_filesystem_call(self) -> None:
        for label, target in {
            "drive letter": f"repo:workspace/C%3A{MARKER}",
            "backslash": f"repo:workspace/..%5C{MARKER}",
            "encoded UNC": f"repo:workspace/%2F%2F{MARKER}%2Fshare",
        }.items():
            with self.subTest(label):
                self.write("topics/hostile.md", topic("Hostile", points=f"- **Assumed:** See [reference]({target})."))
                result = self.lint_without_touching()
                broken = [item for item in result.diagnostics if item.code == "broken-link"]
                self.assertEqual(1, len(broken), [item.message for item in result.diagnostics])
                self.assertIn("not a repository link", broken[0].message)

    def test_an_api_contract_reference_with_a_hostile_path_is_ignored_without_a_filesystem_call(self) -> None:
        from prism_cli.wiki_transitions import api_contract_link_targets

        body = "\n".join(f"[contract]({target})" for target in HOSTILE_LINKS.values()) + f"\nSee ../api-contracts/..%5C{MARKER}.md and wiki/api-contracts/%2F%2F{MARKER}/x.md.\n"
        source = self.write("features/F-001-x.md", "---\nid: F-001\n---\n" + body)
        with FilesystemSpy(self) as spy:
            targets = api_contract_link_targets(body, source, self.wiki)
        self.assertEqual([], targets)
        self.assertEqual([], spy.calls)

    def test_a_valid_relative_link_still_resolves(self) -> None:
        self.write("research/a.md", "---\nkind: research\ntitle: A\nstatus: current\nsources: []\n---\n\n## Question\nq\n\n## Findings\nf\n")
        self.write("topics/a.md", topic("A", points="- **Assumed:** See [the research](../research/a.md) and [more](../research/My%20page.md)."))
        broken = self.found("broken-link")
        self.assertEqual(1, len(broken))
        self.assertIn("My%20page.md", broken[0].message, "an encoded space is decoded, and the missing page is reported")


if __name__ == "__main__":
    unittest.main()
