"""The lint rules of the release record and of the Release rows that name it (CONTRACTS 6.2).

`lint_release_records` checks every record on its own and against the records it names; `lint_release_row_cells` checks that a
feature or bug Release row agrees with the record it links. Both return findings that `wiki_lint` turns into diagnostics.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from prism_cli.release_rules import RELEASE_ROW_OUTCOMES, row_record_mismatch, validate_release_sequence
from prism_cli.wiki_releases import ReleaseRecord, record_id_of_cell


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

    sequence = validate_release_sequence(records)
    findings = [
        ReleaseFinding("release-record-invalid", "error", path, problem.message)
        for path, problems in sequence.problems.items()
        for problem in problems
    ]
    for record in records:
        for row in record.rows:
            apps = items.get(row.item.upper())
            if apps is None:
                message = f"A Delivery row names `{row.item}`, which is not a feature or bug of this wiki."
            elif row.app not in apps:
                message = f"A Delivery row names `{row.app}` for {row.item}, which does not list that app."
            else:
                continue
            findings.append(ReleaseFinding("release-record-invalid", "error", record.page.path, message))
    return findings


def validate_release_records(records: Sequence[ReleaseRecord]) -> tuple[list[ReleaseRecord], dict[Path, list[str]]]:
    """The chronological authority decision shared by readers, lint and write previews.

    Cross-page delivery bindings are also checked when a record is written and by lint.
    """

    sequence = validate_release_sequence(records)
    return sequence.records, {path: [problem.message for problem in problems] for path, problems in sequence.problems.items()}


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
