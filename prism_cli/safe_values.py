"""The one rule for user values that reach generated code, configuration or CI.

An app's ID, path, name and audience, and the project's name and description, come from the answers file,
the manifest or a prompt. They end up in shell steps, YAML, Gradle, Xcode, npm and pyproject files, `.env`
files and Markdown that agents read. A value that is not checked there is code in a generated project, so
every entry point (the manifest normalizer, `prism new`, `prism app add` and Copier's own validators in
`copier.yml`) applies the rules of this module, and the templates serialize a value wherever it enters YAML,
JSON, XML or a shell step. The same patterns are repeated in `copier.yml` as validators; a test compares them.

- A path segment is lowercase letters, digits, `.`, `_` and `-`, starts with a letter or a digit and does not
  end with a dot. Such a segment is inert in a shell, a YAML scalar, a glob and a GitHub expression.
- A label (a name or an audience) is one line of letters, digits, spaces and `. , - _ ( ) + / &`.
- A description is a label that may also hold `' : ; ! ?`.
"""

from __future__ import annotations

import re
from typing import Any

PATH_SEGMENT_PATTERN = re.compile(r"[a-z0-9](?:[a-z0-9._-]*[a-z0-9_-])?")
MAX_PATH_LENGTH = 200
MAX_SEGMENT_LENGTH = 64

# Names that Windows treats as devices whatever their extension.
_WINDOWS_DEVICE_NAMES = frozenset({"con", "prn", "aux", "nul", *(f"com{number}" for number in range(1, 10)), *(f"lpt{number}" for number in range(1, 10))})

LABEL_EXTRA = frozenset(" .,-_()+/&")
DESCRIPTION_EXTRA = LABEL_EXTRA | frozenset("':;!?")
MAX_LABEL_LENGTH = 80
MAX_DESCRIPTION_LENGTH = 200

PATH_RULE = "lowercase letters, digits, `.`, `_` and `-` in each segment, starting with a letter or a digit and not ending with a dot"
LABEL_RULE = "one line of letters, digits, spaces and the characters `. , - _ ( ) + / &`"
DESCRIPTION_RULE = "one line of letters, digits, spaces and the characters `. , - _ ( ) + ' : ; ! ? / &`"


def path_segment_problem(segment: str) -> str | None:
    """Why one path segment is not safe, or ``None``."""

    if not PATH_SEGMENT_PATTERN.fullmatch(segment) or len(segment) > MAX_SEGMENT_LENGTH:
        return f"segment `{segment}` is not safe: use {PATH_RULE}, at most {MAX_SEGMENT_LENGTH} characters."
    if segment.split(".", 1)[0] in _WINDOWS_DEVICE_NAMES:
        return f"segment `{segment}` is a reserved Windows device name."
    return None


def path_segments_problem(segments: list[str]) -> str | None:
    """Why a list of path segments is not safe, or ``None``."""

    if sum(len(segment) + 1 for segment in segments) > MAX_PATH_LENGTH:
        return f"is longer than {MAX_PATH_LENGTH} characters."
    for segment in segments:
        problem = path_segment_problem(segment)
        if problem is not None:
            return problem
    return None


def _text_problem(value: Any, extra: frozenset[str], rule: str, max_length: int) -> str | None:
    if not isinstance(value, str):
        return "must be a string."
    if value != value.strip():
        return "must not have leading or trailing whitespace."
    if len(value) > max_length:
        return f"must be at most {max_length} characters."
    for character in value:
        if not (character.isalnum() or character in extra):
            shown = repr(character)[1:-1] if character.isprintable() else f"U+{ord(character):04X}"
            return f"contains `{shown}`, which is not allowed: use {rule}."
    return None


def label_problem(value: Any) -> str | None:
    """Why a name or an audience is not safe to render into generated files, or ``None``. Empty is allowed here; callers that need a value check that."""

    return _text_problem(value, LABEL_EXTRA, LABEL_RULE, MAX_LABEL_LENGTH)


def description_problem(value: Any) -> str | None:
    """Why a project description is not safe to render into generated files, or ``None``."""

    return _text_problem(value, DESCRIPTION_EXTRA, DESCRIPTION_RULE, MAX_DESCRIPTION_LENGTH)
