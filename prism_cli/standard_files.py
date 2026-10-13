"""The standard files at the root of the wiki, listed once.

Every part of Prism that names these files reads its list from `STANDARD_FILES`; none keeps a list of its own. A file
that joins the manifest takes part in each category its entry sets and in no other, so adding one is one entry.

The categories:

- `required`: lint reports `missing-required-wiki-file` when the file is absent, a board refuses to adopt a workspace
  without it, and a lifecycle check reports it when it cannot be read.
- `copied`: the candidate workspace a preview, a repair or a recovery validates carries the file.
- `revision`: the scopes in which a preview records the file's revision, so a change to it makes the preview stale:
  `write` (any skill write), `feature` (a write that changes a feature), `transition` (a lifecycle transition),
  `read` (a skill must have read the file before it writes) and `sources` (the sources a transition snapshot watches).
- `gating`: a lint finding about the file (missing, malformed) gates every lifecycle action.
- `managed`: the board service writes the file itself; a proposal never supplies it.
- `versioned`: the file carries `schema-version` front matter.
- `non_source`: lint never reads the file as a source page, wherever it sits.
- `non_page`: the link helpers never read the file as a page, wherever it sits.
- `unindexed`: the general index never lists the file; `index_line` is the fixed `(label, summary)` it gets there, if it has one.

Every file of the manifest is a recognized root page of the wiki. This module imports nothing from Prism, so any module
can use it.
"""

from __future__ import annotations

from dataclasses import dataclass

WIKI_DIR = "knowledge/wiki"

# The revision scopes of `StandardFile.revision`.
REVISION_SCOPES = ("write", "feature", "transition", "read", "sources")
# The flag categories of `StandardFile`, for `names`.
CATEGORIES = ("required", "copied", "gating", "managed", "versioned", "non_source", "non_page", "unindexed")


@dataclass(frozen=True)
class StandardFile:
    """One standard wiki file and the categories it belongs to."""

    name: str
    required: bool = False
    copied: bool = True
    revision: tuple[str, ...] = ()
    gating: bool = False
    managed: bool = False
    versioned: bool = False
    non_source: bool = False
    non_page: bool = False
    unindexed: bool = False
    index_line: tuple[str, str] | None = None

    def __post_init__(self) -> None:
        unknown = [scope for scope in self.revision if scope not in REVISION_SCOPES]
        if unknown:
            raise ValueError(f"{self.name}: unknown revision scope {unknown[0]!r}")


STANDARD_FILES: tuple[StandardFile, ...] = (
    StandardFile(
        "SCHEMA.md",
        required=True,
        revision=("write", "feature", "transition", "read", "sources"),
        gating=True,
        versioned=True,
        non_source=True,
        non_page=True,
        index_line=("SCHEMA.md", "Wiki conventions and operational rules."),
    ),
    StandardFile(
        "LIFECYCLE.md",
        required=True,
        revision=("write", "feature", "transition", "read", "sources"),
        gating=True,
        versioned=True,
        non_source=True,
        non_page=True,
        index_line=("LIFECYCLE.md", "Feature, board and advisory protocol."),
    ),
    StandardFile(
        "ACTIONS.md",
        required=True,
        revision=("transition", "sources"),
        gating=True,
        versioned=True,
        non_source=True,
        non_page=True,
        index_line=("ACTIONS.md", "Lifecycle action registry, write scopes and action contracts."),
    ),
    StandardFile(
        "SETTINGS.md",
        revision=("feature", "transition", "read"),
        non_source=True,
        non_page=True,
        index_line=("SETTINGS.md", "Project-level settings for wiki read and query behavior."),
    ),
    StandardFile(
        "CONNECTED.md",
        index_line=("CONNECTED.md", "How agents use the connected board and MCP service."),
    ),
    StandardFile(
        "index.md",
        required=True,
        revision=("read", "sources"),
        gating=True,
        managed=True,
        non_page=True,
        unindexed=True,
    ),
    StandardFile(
        "status-board.md",
        required=True,
        revision=("sources",),
        gating=True,
        managed=True,
        non_source=True,
        non_page=True,
        index_line=("Status board", "The status, owner and board review of every feature."),
    ),
    StandardFile(
        "log.md",
        managed=True,
        non_source=True,
        non_page=True,
        unindexed=True,
    ),
)


def names(category: str | None = None) -> tuple[str, ...]:
    """The names of the manifest's files, in manifest order: all of them, or those of a flag category."""

    if category is None:
        return tuple(entry.name for entry in STANDARD_FILES)
    if category not in CATEGORIES:
        raise ValueError(f"unknown standard-file category {category!r}")
    return tuple(entry.name for entry in STANDARD_FILES if getattr(entry, category))


def revision_names(scope: str) -> tuple[str, ...]:
    """The names of the files whose revision a preview records in one scope, in manifest order."""

    if scope not in REVISION_SCOPES:
        raise ValueError(f"unknown revision scope {scope!r}")
    return tuple(entry.name for entry in STANDARD_FILES if scope in entry.revision)


def index_lines() -> dict[str, tuple[str, str]]:
    """The fixed index line, `(label, summary)`, of each standard file that has one."""

    return {entry.name: entry.index_line for entry in STANDARD_FILES if entry.index_line is not None}


def wiki_path(name: str) -> str:
    """The workspace-relative path of a standard file."""

    return f"{WIKI_DIR}/{name}"


def wiki_paths(names_: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    """The workspace-relative paths of standard files, in the order given."""

    return tuple(wiki_path(name) for name in names_)
