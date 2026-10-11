"""The lint rules of the release record and of the Release rows that name it (CONTRACTS 6.2).

`lint_release_records` checks every record on its own and against the records it names; `lint_release_row_cells` checks that a
feature or bug Release row agrees with the record it links. Both return findings that `wiki_lint` turns into diagnostics.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from prism_cli.qa_rules import Problem
from prism_cli.release_rules import (
    RELEASE_ROW_OUTCOMES,
    check_record_page,
    record_front_matter_problems,
    record_row_problems,
    row_record_mismatch,
)
from prism_cli.wiki_releases import (
    KIND_REDEPLOY,
    KIND_RELEASE,
    KIND_ROLLBACK,
    ReleaseRecord,
    parse_record_rows,
    parse_snapshots,
    record_id_of_cell,
    record_kinds,
)


@dataclass(frozen=True)
class ReleaseFinding:
    code: str
    severity: str
    path: Path
    message: str
    feature_id: str | None = None


def lint_release_records(records: Sequence[ReleaseRecord], *, items: Mapping[str, list[str]]) -> list[ReleaseFinding]:
    """The findings for every release record: its page, its rows, the records it names and the contract snapshots it carries.

    `items` maps a feature or bug ID (upper case) to its `apps`; an item the wiki does not have is not a key.
    """

    findings: list[ReleaseFinding] = []
    by_id: dict[str, ReleaseRecord] = {}
    kinds = record_kinds(records)
    for record in records:
        path = record.page.path
        page = record.page

        def add(problem: Problem | str) -> None:
            message = problem.message if isinstance(problem, Problem) else problem
            findings.append(ReleaseFinding("release-record-invalid", "error", path, message))

        for problem in check_record_page(str(path), page.frontmatter, page.body, parse_errors=page.parse_errors):
            add(problem)
        if page.parse_errors:
            continue
        if record.record_id in by_id:
            add(f"Duplicate release record `{record.record_id}`.")
        by_id[record.record_id] = record
        kind = kinds.get(record.record_id, KIND_RELEASE)
        rows, row_problems = parse_record_rows(page.body)
        for problem in record_row_problems(rows, kind, row_problems):
            add(problem)
        for problem in record_front_matter_problems(str(path), page.frontmatter, rows, kind):
            add(problem)
        for row in rows:
            apps = items.get(row.item.upper())
            if apps is None:
                add(f"A Delivery row names `{row.item}`, which is not a feature or bug of this wiki.")
            elif row.app not in apps:
                add(f"A Delivery row names `{row.app}` for {row.item}, which does not list that app.")
        snapshots, snapshot_messages = parse_snapshots(page.body)
        for message in snapshot_messages:
            add(message)
        for snapshot in snapshots:
            if snapshot.digest_citation != snapshot.citation:
                add(f"The contract snapshot of {snapshot.feature} for `{snapshot.app}` states `{snapshot.citation}`, but its text digests to `{snapshot.digest_citation}`.")
        named = record.rollback_of or record.retry_of
        if named is None:
            continue
        label = "rollback-of" if record.rollback_of else "retry-of"
        target = next((item for item in records if item.record_id == named), None)
        if target is None or target.number is None or record.number is None or target.number >= record.number:
            add(f"`{label}: {named}` must name an earlier release record.")
        elif record.rollback_of is not None:
            delivered = {(row.item, row.app, row.target, row.version) for row in target.rows if row.outcome == "released"}
            for row in rows:
                if (row.item, row.app, row.target, row.version) not in delivered:
                    add(f"A rollback row for {row.item} and `{row.app}` is not a delivery of {named}.")
        elif kind == KIND_RELEASE and not any(row.outcome == "failed" for row in target.rows):
            add(f"`retry-of: {named}` names a record with no failed delivery.")
        elif kind == KIND_REDEPLOY and {row.pair for row in rows} - {row.pair for row in target.rows}:
            add(f"A redeploy retries {named} for the (app, target) pairs it has rows for.")
    return findings


def validate_release_records(records: Sequence[ReleaseRecord]) -> tuple[list[ReleaseRecord], dict[Path, list[str]]]:
    """The records that may carry authority, and why each other record may not.

    A record carries authority (the current delivery of an app, the next number, a rollback or retry target) only when its
    page, rows, metadata, snapshots and earlier-record references are valid and no other file claims its ID.
    The second result maps each invalid record's path to its problems. Cross-page delivery bindings are also checked
    when a record is written and by lint.
    """

    problems: dict[Path, list[str]] = {}

    def add(record: ReleaseRecord, message: str) -> None:
        problems.setdefault(record.page.path, []).append(message)

    counts: dict[str, int] = {}
    for record in records:
        counts[record.record_id] = counts.get(record.record_id, 0) + 1
    kinds = record_kinds(records)
    for record in records:
        page = record.page
        for problem in check_record_page(str(page.path), page.frontmatter, page.body, parse_errors=page.parse_errors):
            add(record, problem.message)
        if not page.parse_errors:
            rows, row_problems = parse_record_rows(page.body)
            kind = kinds.get(record.record_id, KIND_RELEASE)
            for problem in record_row_problems(rows, kind, row_problems):
                add(record, problem.message)
            for problem in record_front_matter_problems(str(page.path), page.frontmatter, rows, kind):
                add(record, problem.message)
            snapshots, messages = parse_snapshots(page.body)
            for message in messages:
                add(record, message)
            seen: set[tuple[str, str]] = set()
            for snapshot in snapshots:
                key = (snapshot.feature, snapshot.app)
                if key in seen:
                    add(record, f"Two contract snapshots name {snapshot.feature} and `{snapshot.app}`.")
                seen.add(key)
                if snapshot.digest_citation != snapshot.citation or not snapshot.citation.startswith(snapshot.feature + "@v") or snapshot.app not in {row.app for row in rows}:
                    add(record, f"The contract snapshot of {snapshot.feature} for `{snapshot.app}` has a broken binding or names an app not delivered by the record.")
        if counts[record.record_id] > 1:
            add(record, f"More than one file claims the release record ID `{record.record_id}`.")
    by_id = {record.record_id: record for record in records}
    for record in records:
        named = record.rollback_of or record.retry_of
        target = by_id.get(named or "")
        if target is None:
            continue  # the dependency check below reports missing or invalid targets
        kind = kinds.get(record.record_id, KIND_RELEASE)
        source_kind = kinds.get(target.record_id, KIND_RELEASE)
        for row in record.rows:
            source_rows = target.rows_for(*row.pair)
            if record.rollback_of:
                expected = sorted((item.item, item.version) for item in source_rows if item.outcome == "released")
                actual = sorted((item.item, item.version) for item in record.rows_for(*row.pair))
                if source_kind == KIND_ROLLBACK or not expected or actual != expected:
                    add(record, f"`rollback-of: {named}` must name a delivery of the same items, app, target and version.")
            elif kind == KIND_RELEASE:
                if source_kind != KIND_RELEASE or not any(item.outcome == "failed" for item in source_rows):
                    add(record, f"`retry-of: {named}` must name a failed release for `{row.app}` at `{row.target}`.")
            else:
                expected = sorted((item.item, item.version) for item in source_rows)
                actual = sorted((item.item, item.version) for item in record.rows_for(*row.pair))
                if source_kind not in {KIND_ROLLBACK, KIND_REDEPLOY} or not source_rows or actual != expected or (source_kind == KIND_REDEPLOY and any(item.outcome != "failed" for item in source_rows)):
                    add(record, f"`retry-of: {named}` must name a rollback or failed redeploy of the same items, app, target and version.")
    changed = True
    while changed:
        changed = False
        for record in records:
            named = record.rollback_of or record.retry_of
            if named is None or record.page.path in problems:
                continue
            label = "rollback-of" if record.rollback_of else "retry-of"
            target = by_id.get(named)
            if target is None or target.page.path in problems or target.number is None or record.number is None or target.number >= record.number:
                add(record, f"`{label}: {named}` must name an earlier valid release record.")
                changed = True
    return [record for record in records if record.page.path not in problems], problems


def lint_release_row_cells(
    *,
    item: str,
    path: Path,
    rows: Sequence[Any],
    records: Mapping[str, ReleaseRecord],
    linked_bugs: Sequence[str] = (),
    feature_id: str | None = None,
) -> list[ReleaseFinding]:
    """A feature or bug Release row that links a record of the wiki agrees with that record's Delivery row on target, version and outcome (`release-row-record-mismatch`).

    A Record cell that is not the link to a record (`[REL-001](../releases/REL-001.md)`) names no record to compare with; the board
    writes the link, and a file that does not exist is a broken link.
    """

    findings: list[ReleaseFinding] = []
    for row in rows:
        if not row.authoritative or row.outcome not in RELEASE_ROW_OUTCOMES:
            continue
        record_id = record_id_of_cell(row.record)
        if record_id is None:
            continue
        record = records.get(record_id)
        if record is None:
            findings.append(
                ReleaseFinding("release-row-record-mismatch", "error", path, f"The Release row of `{row.app}` in {item} names {record_id}, which is not a release record of this wiki.", feature_id)
            )
            continue
        problem = row_record_mismatch(
            item=item,
            app=row.app,
            row_target=row.target,
            row_version=row.version,
            row_outcome=row.outcome,
            record=record,
            linked_bugs=linked_bugs,
        )
        if problem is not None:
            findings.append(ReleaseFinding("release-row-record-mismatch", "error", path, f"The Release row of `{row.app}` in {item} disagrees with {record_id}: {problem}.", feature_id))
    return findings
