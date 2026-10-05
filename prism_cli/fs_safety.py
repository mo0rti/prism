"""Shared filesystem classification for Prism's path-confinement checks.

Prism refuses symlinks, junctions, and other reparse points anywhere inside a
workspace so confinement and atomic-replace guarantees hold. Windows cloud-files
placeholders (OneDrive and Dropbox Files On-Demand) carry the same
``FILE_ATTRIBUTE_REPARSE_POINT`` attribute, so they are refused too. This module
only tells the cases apart so the refusal can explain itself; it never changes
which paths are accepted.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Literal

FILE_ATTRIBUTE_REPARSE_POINT = 0x400
# IO_REPARSE_TAG_CLOUD is 0x9000001A; CLOUD_1 through CLOUD_F set the 0xF000 nibble.
CLOUD_REPARSE_TAG = 0x9000001A
CLOUD_TAG_MASK = 0x0000F000

CLOUD_SYNC_MESSAGE = (
    "This workspace is inside a cloud-synced folder (for example OneDrive or Dropbox Files On-Demand). "
    "Prism needs ordinary local files for safe atomic writes. "
    "Move the workspace to a local folder that is not synced, then retry."
)

ReparseKind = Literal["none", "symlink", "cloud", "other"]


class CloudSyncPathError(ValueError):
    """A path is a cloud-files placeholder; the message explains how to recover."""

    def __init__(self) -> None:
        super().__init__(CLOUD_SYNC_MESSAGE)


def reparse_kind(info: os.stat_result) -> ReparseKind:
    """Classify an ``os.lstat`` result.

    ``cloud`` placeholders stay rejected like every other reparse point: the sync
    engine may rewrite or dehydrate a file between Prism's read and write, so an
    atomic replace cannot be guaranteed. Symlinks, junctions, and any other
    reparse tag are ``symlink`` or ``other`` and keep their existing handling.
    Where the platform reports no file attributes (POSIX), only symlinks are
    reparse-like.
    """

    if stat.S_ISLNK(info.st_mode):
        return "symlink"
    attributes = getattr(info, "st_file_attributes", 0)
    if not attributes & FILE_ATTRIBUTE_REPARSE_POINT:
        return "none"
    tag = getattr(info, "st_reparse_tag", 0)
    if tag and (tag & ~CLOUD_TAG_MASK) == CLOUD_REPARSE_TAG:
        return "cloud"
    return "other"


def find_cloud_placeholder(path: Path) -> Path | None:
    """Return the first component of ``path`` (outermost first) that is a cloud placeholder."""

    candidate = Path(path).expanduser().absolute()
    for component in reversed((candidate, *candidate.parents)):
        try:
            info = component.lstat()
        except OSError:
            continue
        if reparse_kind(info) == "cloud":
            return component
    return None
