"""Classification of symlinks, reparse points, and cloud-files placeholders."""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import stat
from types import SimpleNamespace
from typing import Iterator
import unittest
from unittest.mock import patch

from prism_cli.fs_safety import CLOUD_SYNC_MESSAGE, find_cloud_placeholder, reparse_kind

REPARSE_ATTRIBUTE = 0x400
JUNCTION_TAG = 0xA0000003
CLOUD_TAG = 0x9000001A

_REAL_LSTAT = Path.lstat


@contextmanager
def fake_reparse(target: Path, tag: int | None) -> Iterator[None]:
    """Report ``target`` as a reparse point with ``tag`` (omitted when None) from Path.lstat."""

    def lstat(self: Path, *args: object, **kwargs: object):
        info = _REAL_LSTAT(self, *args, **kwargs)
        if self == target:
            fields = {"st_mode": info.st_mode, "st_size": info.st_size, "st_file_attributes": REPARSE_ATTRIBUTE}
            if tag is not None:
                fields["st_reparse_tag"] = tag
            return SimpleNamespace(**fields)
        return info

    with patch.object(Path, "lstat", lstat):
        yield


def _info(*, mode: int = stat.S_IFREG, attributes: int | None = None, tag: int | None = None) -> SimpleNamespace:
    fields: dict[str, int] = {"st_mode": mode}
    if attributes is not None:
        fields["st_file_attributes"] = attributes
    if tag is not None:
        fields["st_reparse_tag"] = tag
    return SimpleNamespace(**fields)


class ReparseKindTests(unittest.TestCase):
    def test_regular_entry_is_none(self) -> None:
        self.assertEqual("none", reparse_kind(_info(attributes=0x20)))

    def test_missing_attributes_are_none(self) -> None:
        self.assertEqual("none", reparse_kind(_info()))

    def test_symlink_mode_is_symlink(self) -> None:
        self.assertEqual("symlink", reparse_kind(_info(mode=stat.S_IFLNK)))
        self.assertEqual("symlink", reparse_kind(_info(mode=stat.S_IFLNK, attributes=REPARSE_ATTRIBUTE, tag=0xA000000C)))

    def test_junction_tag_is_other(self) -> None:
        self.assertEqual("other", reparse_kind(_info(mode=stat.S_IFDIR, attributes=REPARSE_ATTRIBUTE, tag=JUNCTION_TAG)))

    def test_cloud_tags_are_cloud(self) -> None:
        self.assertEqual("cloud", reparse_kind(_info(attributes=REPARSE_ATTRIBUTE, tag=CLOUD_TAG)))
        self.assertEqual("cloud", reparse_kind(_info(attributes=REPARSE_ATTRIBUTE, tag=0x9000701A)))
        self.assertEqual("cloud", reparse_kind(_info(attributes=REPARSE_ATTRIBUTE, tag=0x9000F01A)))

    def test_unrelated_tag_is_other(self) -> None:
        self.assertEqual("other", reparse_kind(_info(attributes=REPARSE_ATTRIBUTE, tag=0x80000021)))

    def test_reparse_attribute_without_a_tag_is_other(self) -> None:
        self.assertEqual("other", reparse_kind(_info(attributes=REPARSE_ATTRIBUTE)))

    def test_cloud_tag_without_the_reparse_attribute_is_none(self) -> None:
        self.assertEqual("none", reparse_kind(_info(attributes=0x20, tag=CLOUD_TAG)))

    def test_real_files_are_classified_without_error(self) -> None:
        self.assertEqual("none", reparse_kind(os.lstat(Path(__file__))))


class FindCloudPlaceholderTests(unittest.TestCase):
    def test_returns_the_outermost_cloud_component(self) -> None:
        here = Path(__file__).resolve().parent
        with fake_reparse(here.parent, CLOUD_TAG):
            self.assertEqual(here.parent, find_cloud_placeholder(here))

    def test_other_reparse_points_are_not_cloud(self) -> None:
        here = Path(__file__).resolve().parent
        with fake_reparse(here.parent, JUNCTION_TAG):
            self.assertIsNone(find_cloud_placeholder(here))

    def test_ordinary_path_is_none(self) -> None:
        self.assertIsNone(find_cloud_placeholder(Path(__file__).resolve().parent))

    def test_guidance_names_the_recovery(self) -> None:
        self.assertIn("cloud-synced folder", CLOUD_SYNC_MESSAGE)
        self.assertIn("Move the workspace to a local folder that is not synced", CLOUD_SYNC_MESSAGE)


if __name__ == "__main__":
    unittest.main()
