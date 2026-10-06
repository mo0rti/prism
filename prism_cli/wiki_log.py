"""The wiki log: how `log.md` entries are read, and how a verification entry is written.

`knowledge/wiki/log.md` is the only home for history. Each entry is

    ## YYYY-MM-DD <operation> | <subject>
    - paths: <paths, comma-separated, relative to the repository root>
    - evidence: <links, or none>
    - by: <actor>

Wiki lint checks the form, freshness reads `verify` entries from it, and `prism wiki verify` and
the connected board's `verify` skill append them.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Iterable

from prism_cli.wiki_model import parse_iso_date


VERIFY_OPERATION = "verify"

# `## YYYY-MM-DD <operation> | <subject>`, then `paths`, `evidence` and `by` lines.
LOG_HEADING_PATTERN = re.compile(r"^## (\d{4}-\d{2}-\d{2}) ([a-z][a-z0-9-]*) \| (\S.*)$")
LOG_FIELD_PATTERN = re.compile(r"^- (paths|evidence|by): (\S.*)$")
LOG_FIELDS = ("paths", "evidence", "by")
_SUBJECT_LIMIT = 120


def split_log_entries(text: str) -> list[tuple[int, str, list[str]]]:
    """Split `log.md` into `(line number, heading line, body lines)` entries.

    A heading is any line that starts with `## ` outside a fenced block. Body lines are stripped, and
    blank lines and HTML comment lines (the board's markers) are left out.
    """

    entries: list[tuple[int, str, list[str]]] = []
    in_fence = False
    for number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.rstrip()
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if line.startswith("## "):
            entries.append((number, line, []))
            continue
        stripped = line.strip()
        if not entries or not stripped or (stripped.startswith("<!--") and stripped.endswith("-->")):
            continue
        entries[-1][2].append(stripped)
    return entries


def split_log_paths(value: str) -> list[str]:
    """The paths of a `paths` line: comma-separated, trimmed, `none` and empty items dropped."""

    return [item for item in (part.strip() for part in value.split(",")) if item and item.casefold() != "none"]


def last_verifications(text: str) -> dict[str, date]:
    """The latest verification date of each path, from the `verify` entries of `log.md`.

    A verification is an entry whose operation is `verify`; every path on its `paths` line was
    verified on the entry's date. An entry that is not in the log format is ignored here: lint
    reports it as `malformed-log-entry`.
    """

    verified: dict[str, date] = {}
    for _number, heading, body in split_log_entries(text):
        match = LOG_HEADING_PATTERN.match(heading)
        if match is None or match.group(2) != VERIFY_OPERATION:
            continue
        day = parse_iso_date(match.group(1))
        if day is None:
            continue
        for line in body:
            field = LOG_FIELD_PATTERN.match(line)
            if field is None or field.group(1) != "paths":
                continue
            for path in split_log_paths(field.group(2)):
                if path not in verified or verified[path] < day:
                    verified[path] = day
            break
    return verified


def format_verification_entry(
    *,
    day: date,
    pages: Iterable[str],
    evidence: str | None = None,
    by: str,
    operation: str = VERIFY_OPERATION,
) -> str:
    """One `verify` entry in the log format, without a trailing newline.

    ``pages`` are repository-root-relative paths. The subject names the pages' files, clipped to a
    heading that stays on one line.
    """

    paths = list(dict.fromkeys(pages))
    names = [path.rsplit("/", 1)[-1] for path in paths]
    subject = ", ".join(names)
    if len(subject) > _SUBJECT_LIMIT:
        shown: list[str] = []
        for name in names:
            if len(", ".join([*shown, name])) > _SUBJECT_LIMIT - 20:
                break
            shown.append(name)
        subject = ", ".join(shown) + f" and {len(names) - len(shown)} more"
    return (
        f"## {day.isoformat()} {operation} | {_one_line(subject) or 'pages'}\n"
        f"- paths: {', '.join(paths)}\n"
        f"- evidence: {_one_line(evidence or '') or 'none'}\n"
        f"- by: {_one_line(by) or 'unknown'}"
    )


def append_log_entry(existing: str, entry: str) -> str:
    """`log.md` text with `entry` appended after a blank line. Existing entries are never touched."""

    prefix = existing
    if prefix and not prefix.endswith("\n"):
        prefix += "\n"
    if prefix and not prefix.endswith("\n\n"):
        prefix += "\n"
    return prefix + entry.rstrip() + "\n"


def _one_line(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()
