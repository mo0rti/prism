"""Design tracks for the feature fixtures of the tests (CONTRACTS 3.1).

A fixture that sits in design or later carries `design-tracks` and `design-reaffirm`. These helpers give a page the tracks its
status needs: initial ones in design, settled ones from `ready-for-dev` on, none before design.
"""

from __future__ import annotations

import re
from typing import Any, MutableMapping

import yaml

from prism_cli.wiki_model import DesignTracks, NO_UI_TRACK_REASON, status_rank

NO_TECHNICAL_REASON = "The feature changes no architecture and declares no API work."

SETTLED = DesignTracks("not-applicable", "not-applicable", NO_UI_TRACK_REASON, NO_TECHNICAL_REASON)
# The tracks of a feature with no UI that design has just started.
STARTED = DesignTracks("not-applicable", "pending", NO_UI_TRACK_REASON, None)
# The tracks of a feature with a UI that design has just started.
STARTED_WITH_UI = DesignTracks("pending", "pending")
# Both tracks settled for a scope with a UI: the UI track by an exemption, the technical track by a reason.
SETTLED_WITH_UI = DesignTracks("not-applicable", "not-applicable", "The screens are unchanged.", NO_TECHNICAL_REASON)

_FRONTMATTER = re.compile(r"\A(﻿?)---\r?\n(.*?)\r?\n---\r?\n?(.*)\Z", re.DOTALL)


def tracks_for_status(status: str, current: DesignTracks | None = None) -> DesignTracks | None:
    """The tracks a fixture at `status` carries: none before design, `current` while it is valid there, otherwise a default."""

    rank = status_rank(status)
    if rank < status_rank("in-design"):
        return None
    if rank >= status_rank("ready-for-dev"):
        return current if current is not None and not current.unresolved and not current.reaffirm else SETTLED
    return current if current is not None else STARTED


def apply_tracks(frontmatter: MutableMapping[str, Any], status: str, current: DesignTracks | None = None) -> None:
    """Set `design-tracks` and `design-reaffirm` of a front matter mapping to what a fixture at `status` carries."""

    tracks = tracks_for_status(status, current)
    for key in ("design-tracks", "design-reaffirm"):
        frontmatter.pop(key, None)
    if tracks is not None:
        frontmatter.update(tracks.frontmatter())


def with_tracks(content: str, tracks: DesignTracks | None, **updates: Any) -> str:
    """The page `content` with `design-tracks` and `design-reaffirm` set to `tracks` (removed when ``None``) and other front matter `updates`."""

    match = _FRONTMATTER.match(content)
    if match is None:
        raise ValueError("A feature page starts with front matter.")
    frontmatter = yaml.safe_load(match.group(2)) or {}
    for key in ("design-tracks", "design-reaffirm"):
        frontmatter.pop(key, None)
    if tracks is not None:
        frontmatter.update(tracks.frontmatter())
    frontmatter.update(updates)
    return f"{match.group(1)}---\n{yaml.safe_dump(frontmatter, sort_keys=False).rstrip()}\n---\n{match.group(3)}"


def started(content: str, tracks: DesignTracks = STARTED_WITH_UI) -> str:
    """The page of a feature that starts design (`ready-for-design` to `in-design`) with the initial `tracks` of its scope."""

    return with_tracks(content, tracks, status="in-design")


def ensure_tracks(content: str, status: str) -> str:
    """The page `content` with the tracks its `status` needs, added when it has none (a page that has tracks is left alone)."""

    match = _FRONTMATTER.match(content)
    if match is None or "design-tracks" in match.group(2):
        return content
    tracks = tracks_for_status(status)
    if tracks is None:
        return content
    # The tracks are appended to the front matter as it is, so the rest of the page keeps its exact text.
    block = yaml.safe_dump(tracks.frontmatter(), sort_keys=False).rstrip()
    return f"{match.group(1)}---\n{match.group(2)}\n{block}\n---\n{match.group(3)}"


def technical_design_page(feature_id: str = "F-001", apps: tuple[str, ...] = ("backend",), criteria: tuple[str, ...] = ("AC-1", "AC-2")) -> str:
    """A complete technical design page (CONTRACTS 6.2): every section has content, every app has an Architecture impact row and every criterion a Test strategy row."""

    impact = "\n".join(f"| {app} | core | A small change behind the existing module of {app} |" for app in apps)
    strategy = "\n".join(f"| {criterion} | {', '.join(apps)} | automated | integration | |" for criterion in criteria)
    return (
        f"---\nfeature-id: {feature_id}\ntitle: Technical design of {feature_id}\napps: [{', '.join(apps)}]\ndecisions: []\n---\n\n"
        "## Summary\nThe feature reuses the existing modules and adds one small change per app.\n\n"
        f"## Architecture impact\n| App | Modules | Change |\n|---|---|---|\n{impact}\n\n"
        "## Data model and migrations\nNo migration is needed.\n\n"
        "## Security and privacy\nThe existing authorization applies unchanged.\n\n"
        "## Non-functional requirements\nThe change adds no measurable latency.\n\n"
        "## Risks\nNo risk beyond the existing modules is known.\n\n"
        "## Decisions\nNo new decision is needed.\n\n"
        "## API contract\nThe feature declares no API work beyond the existing contract.\n\n"
        f"## Test strategy\n| Criterion | Applies to | Method | Level | Notes |\n|---|---|---|---|---|\n{strategy}\n"
    )
