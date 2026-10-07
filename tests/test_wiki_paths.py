"""The shared wiki path resolver: hostile paths are refused lexically, before any filesystem call."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from prism_cli.wiki_paths import OUTSIDE, REPARSE, UNSAFE, decoded_link_path, resolve_confined
from tests import real_temp  # noqa: F401

HOSTILE_UNSAFE = {
    "encoded UNC with slashes": "%2F%2Fattacker.invalid%2Fshare%2Fprobe.md",
    "encoded UNC with backslashes": "%5C%5Cattacker.invalid%5Cshare%5Cprobe.md",
    "literal UNC with backslashes": "\\\\attacker.invalid\\share\\probe.md",
    "drive letter, encoded colon": "C%3A%2FWindows%2Fprobe.md",
    "drive letter, encoded colon, no slash": "C%3Aprobe.md",
    "drive letter, literal": "C:probe.md",
    "backslash": "..\\outside.md",
    "encoded backslash": "..%5Coutside.md",
    "rooted": "/etc/passwd",
    "encoded rooted": "%2Fetc%2Fpasswd",
    "double-encoded UNC": "%252F%252Fattacker.invalid%252Fshare%252Fprobe.md",
    "double-encoded backslash": "%255C%255Cattacker.invalid%255Cshare",
    "triple-encoded UNC": "%25252F%25252Fattacker.invalid",
    "a stream name": "page.md%3Astream",
    "a NUL": "page%00.md",
    "a control character": "page%0A.md",
}


class DecodedLinkPathTests(unittest.TestCase):
    def test_every_hostile_form_is_refused_without_a_filesystem_call(self) -> None:
        with patch.object(Path, "resolve", side_effect=AssertionError("resolve")), patch.object(
            Path, "exists", side_effect=AssertionError("exists")
        ), patch.object(Path, "lstat", side_effect=AssertionError("lstat")), patch.object(os, "stat", side_effect=AssertionError("stat")):
            for label, raw in HOSTILE_UNSAFE.items():
                with self.subTest(label):
                    path, problem = decoded_link_path(raw)
                    self.assertIsNone(path)
                    self.assertTrue(problem)

    def test_a_plain_relative_path_is_decoded(self) -> None:
        self.assertEqual(("../design/My page.md", None), decoded_link_path("../design/My%20page.md"))
        self.assertEqual(("a/b.md", None), decoded_link_path("a/b.md", percent_encoded=False))

    def test_a_decoded_target_is_checked_for_a_further_decoding(self) -> None:
        # A step that already decoded the link hands on `%2F%2Fhost`: decoding again would make it a UNC path.
        path, problem = decoded_link_path("%2F%2Fhost%2Fshare%2Fx.md", percent_encoded=False)
        self.assertIsNone(path)
        self.assertIn("encoded twice", problem)


class ResolveConfinedTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        (self.root / "knowledge" / "wiki" / "features").mkdir(parents=True)
        (self.root / "knowledge" / "wiki" / "design").mkdir(parents=True)
        (self.root / "knowledge" / "wiki" / "design" / "F-001-x.md").write_text("# x\n", encoding="utf-8")
        self.base = self.root / "knowledge" / "wiki" / "features"

    def test_a_link_to_an_existing_page_resolves_below_the_boundary(self) -> None:
        resolution = resolve_confined(self.root, self.base, "../design/F-001-x.md")
        self.assertTrue(resolution.ok)
        self.assertTrue(resolution.exists)
        self.assertEqual(self.root / "knowledge" / "wiki" / "design" / "F-001-x.md", resolution.path)

    def test_a_missing_target_resolves_but_does_not_exist(self) -> None:
        resolution = resolve_confined(self.root, self.base, "../design/missing.md")
        self.assertTrue(resolution.ok)
        self.assertFalse(resolution.exists)

    def test_unsafe_paths_make_no_filesystem_call(self) -> None:
        with patch.object(Path, "resolve", side_effect=AssertionError("resolve")), patch.object(
            Path, "exists", side_effect=AssertionError("exists")
        ), patch.object(Path, "lstat", side_effect=AssertionError("lstat")), patch.object(os, "stat", side_effect=AssertionError("stat")), patch.object(
            os, "lstat", side_effect=AssertionError("lstat")
        ):
            for label, raw in HOSTILE_UNSAFE.items():
                with self.subTest(label):
                    resolution = resolve_confined(self.root, self.base, raw)
                    self.assertEqual(UNSAFE, resolution.kind)
                    self.assertIsNone(resolution.path)

    def test_a_parent_escape_is_refused_lexically(self) -> None:
        with patch.object(Path, "resolve", side_effect=AssertionError("resolve")), patch.object(
            Path, "lstat", side_effect=AssertionError("lstat")
        ), patch.object(os, "stat", side_effect=AssertionError("stat")):
            for raw in ("../../../../outside.md", "..%2F..%2F..%2F..%2Foutside.md", "../../../../../etc/passwd", "a/../../../../../outside.md"):
                with self.subTest(raw):
                    resolution = resolve_confined(self.root, self.base, raw)
                    self.assertEqual(OUTSIDE, resolution.kind)

    def test_a_symlink_component_is_refused_after_the_lexical_checks(self) -> None:
        outside = Path(tempfile.mkdtemp(dir=self.root.parent))
        self.addCleanup(lambda: outside.rmdir() if outside.exists() else None)
        link = self.root / "knowledge" / "wiki" / "design" / "link"
        try:
            os.symlink(outside, link, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks need privileges on this machine")
        self.addCleanup(lambda: os.unlink(link) if link.is_symlink() else None)
        resolution = resolve_confined(self.root, self.base, "../design/link/page.md")
        self.assertEqual(REPARSE, resolution.kind)


if __name__ == "__main__":
    unittest.main()
