"""Pure page builders for the release tests: release records, Delivery rows and Release rows.

These helpers import nothing from the board tests, so any test module can use them.
"""

from __future__ import annotations

from datetime import date

RELEASES = "knowledge/wiki/releases"
RELEASE_HEADER = "| App | Target | Version | Attempt | Outcome | Record | Basis |"
DELIVERY_HEADER = "| Item | App | Target | Version | Attempt | Outcome | Evidence | Basis |"
EVIDENCE = "deployment: https://ci.example/deploy/1"


def table(header: str, rows: list[str]) -> str:
    columns = header.split("|")[1:-1]
    return "\n".join([header, "|" + "|".join("---" for _ in columns) + "|", *rows])


def record_path(number: int) -> str:
    return f"{RELEASES}/REL-{number:03d}.md"


def record_id(number: int) -> str:
    return f"REL-{number:03d}"


def release_row(app: str, number: int, *, outcome: str = "released", attempt: int = 1, version: str | None = None, target: str = "production", basis: str = "checked") -> str:
    """The Release row of a feature or a bug that names record `number`."""

    return f"| {app} | {target} | `{version or f'build:{app}#1'}` | release-{attempt} | {outcome} | [{record_id(number)}](../releases/{record_id(number)}.md) | {basis} |"


def delivery(item: str, app: str, *, outcome: str = "released", attempt: int | None = 1, version: str | None = None, target: str = "production", evidence: str = EVIDENCE, basis: str = "checked") -> str:
    """A Delivery row of a release record; `attempt=None` writes `—`."""

    cell = f"release-{attempt}" if attempt is not None else "—"
    return f"| {item} | {app} | {target} | `{version or f'build:{app}#1'}` | {cell} | {outcome} | {evidence} | {basis} |"


def record_outcome_of(rows: list[str]) -> str:
    outcomes = [cells[5].strip() for cells in (row.strip().strip("|").split("|") for row in rows)]
    released = sum(1 for item in outcomes if item == "released")
    return "released" if released == len(outcomes) else "failed" if released == 0 else "partial"


def record_page(
    number: int,
    rows: list[str],
    *,
    features: list[str] | None = None,
    bugs: list[str] | None = None,
    outcome: str | None = None,
    title: str = "Release of F-001",
    day: str | None = None,
    operation: str = "pending",
    retry_of: str | None = None,
    rollback_of: str | None = None,
    summary: str = "F-001 is delivered to production.",
    contracts: str = "None.",
    rollback: str = "None.",
    notes: str = "None.",
    extra: str = "",
) -> str:
    """A release record page; the outcome follows the rows unless given."""

    wanted_outcome = outcome or ("rolled-back" if rollback_of else record_outcome_of(rows))
    lines = [
        "---",
        f"id: {record_id(number)}",
        f"title: {title}",
        f"date: {day or date.today().isoformat()}",
        f"operation: {operation}",
        f"outcome: {wanted_outcome}",
        f"features: [{', '.join(features if features is not None else ['F-001'])}]",
        f"bugs: [{', '.join(bugs or [])}]",
    ]
    if retry_of:
        lines.append(f"retry-of: {retry_of}")
    if rollback_of:
        lines.append(f"rollback-of: {rollback_of}")
    if extra:
        lines.append(extra)
    lines += [
        "---",
        "",
        f"## Summary\n{summary}",
        "",
        f"## Delivery\n{table(DELIVERY_HEADER, rows)}",
        "",
        f"## Contracts\n{contracts}",
        "",
        f"## Rollback\n{rollback}",
        "",
        f"## Notes\n{notes}",
        "",
    ]
    return "\n".join(lines)
