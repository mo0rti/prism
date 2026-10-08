"""Pure page builders for the QA and bug tests: bug pages, evidence rows and Evidence history entries.

These helpers import nothing from the board tests, so any test module can use them.
"""

from __future__ import annotations

import re
from datetime import date

import yaml


def bug_page(
    bug_id: str = "BUG-001",
    *,
    title: str = "Summary export drops comments",
    status: str = "open",
    owner: str | None = None,
    severity: str = "high",
    blocking: bool = True,
    apps: list[str] | None = None,
    feature: str = "F-001",
    extra: dict[str, object] | None = None,
    fix: str = "",
    verification: str = "",
    release: str = "",
    history: str = "",
) -> str:
    owners = {"open": "dev", "in-fix": "dev", "fixed": "qa", "verified": "release", "released": "none", "closed": "none"}
    frontmatter: dict[str, object] = {
        "id": bug_id,
        "title": title,
        "status": status,
        "owner": owner or owners[status],
        "severity": severity,
        "blocking": blocking,
        "apps": apps or ["worker"],
        "feature": feature,
        "found-in": "build:worker#1",
        "environment": "ci",
        "sources": [],
    }
    frontmatter.update(extra or {})
    return (
        f"---\n{yaml.safe_dump(frontmatter, sort_keys=False).rstrip()}\n---\n\n"
        "## Summary\nThe exported summary drops reviewer comments.\n\n"
        "## Steps to reproduce\n1. Export a summary with comments.\n\n"
        "## Expected\nThe comments are in the export.\n\n"
        "## Actual\nThe comments are missing.\n\n"
        "## Impact\nReviewers lose their comments.\n\n"
        f"## Fix\n{fix}\n\n"
        f"## Verification\n{verification}\n\n"
        f"## Release\n{release}\n\n"
        f"## Evidence history\n{history}\n"
    )


FIX_HEADER = "| App | Artifact | Implementation | Tests | Basis |"
VERIFICATION_HEADER = "| App | Method | Artifact | Environment | Attempt | Result | Evidence | Basis |"


def fix_row(app: str = "worker", artifact: str = "build:worker#2") -> str:
    return f"| {app} | `{artifact}` | [PR 40](https://git.example/pull/40) | `pytest`: 90 passed | checked |"


def verification_row(app: str = "worker", artifact: str = "build:worker#2", *, attempt: int = 1, result: str = "pass", environment: str = "ci") -> str:
    return f"| {app} | manual | `{artifact}` | {environment} | qa-{attempt} | {result} | [notes](https://qa.example/notes) | checked |"


def history_entry(
    action: str,
    *,
    affected: str,
    archived: list[tuple[str, str]],
    reason: str = "The QA run found that the saved summary is not read back.",
    participants: str = "none",
    tracks: str = "none",
    invalidations: str = "No requirement or API page is invalidated.",
    linked: str = "none",
    reaffirmed: str = "none",
    day: str | None = None,
) -> str:
    """An Evidence history entry headed with today's date; `archived` lists (section, active table row) pairs."""

    rows = "\n".join(f"  | {section} | {row.strip().strip('|').strip()} |" for section, row in archived)
    return (
        f"### {day or date.today().isoformat()} - {action}\n"
        f"- Reason: {reason}\n"
        f"- Affected apps: {affected}\n"
        f"- Participants: {participants}\n"
        f"- Affected tracks: {tracks}\n"
        f"- Archived evidence:\n{rows}\n"
        f"- Reaffirmed evidence: {reaffirmed}\n"
        f"- Requirement/API invalidations: {invalidations}\n"
        f"- Linked bugs: {linked}\n"
    )


def requirement_path(app: str) -> str:
    return f"knowledge/wiki/app-requirements/F-001-{app}.md"


def append_history(page: str, entry: str) -> str:
    """The page with one more Evidence history entry after the existing ones, which stay as they are."""

    match = re.search(r"(?ms)(^## Evidence history[ \t]*\r?\n)(.*?)(?=^## |\Z)", page)
    if match is None:
        raise ValueError("The page has no Evidence history section.")
    old = match.group(2)
    base = old if old.endswith("\n\n") else old.rstrip("\n") + "\n\n"
    return page[: match.start(2)] + base + entry.rstrip() + "\n\n" + page[match.end(2) :]
