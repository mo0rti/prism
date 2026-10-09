"""The release record of the wiki: its fields, delivery rows, contract snapshots and the questions the release rules ask of the records.

A release record lives in `knowledge/wiki/releases/REL-XXX.md` and is a dated record: `release-done` writes it once and nothing
rewrites it (CONTRACTS 6.2). Its `## Delivery` table holds one row per (item, app) the record delivers, rolls back or redeploys,
and its `## Contracts` section snapshots, verbatim, the API contract each delivered feature row cites. The service validates
every write; this module reads and checks shape, and answers which record is the current delivery of an (app, target) and which
kind a record is.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from prism_cli.wiki_model import (
    CHECKED_BASES,
    EvidenceProblem,
    MarkdownPage,
    _APP_ID_TOKEN,
    _substantive_evidence_cell,
    artifact_reference_problem,
    clean_cell,
    contract_page_citation,
    parse_evidence_table,
    parse_markdown_text,
    read_markdown_pages,
    release_evidence_problem,
    request_fact,
)

RELEASE_DIRECTORY = "releases"
# `REL-` and the number, written with at least three digits and no other padding: one spelling for each number.
RELEASE_ID_PATTERN = re.compile(r"^REL-(?P<number>[0-9]{3}|[1-9][0-9]{3,})$")
RELEASE_FILE_PATTERN = re.compile(r"^(?P<id>REL-(?:[0-9]{3}|[1-9][0-9]{3,}))\.md$")
_RECORD_LINK = re.compile(r"^\[(?P<id>REL-[0-9]+)\]\((?P<target>[^)\s]+)\)$")
FEATURE_ID_PATTERN = re.compile(r"^F-[0-9]+$")
BUG_ID_PATTERN = re.compile(r"^BUG-[0-9]+$")

RELEASE_REQUIRED_FIELDS = ("id", "title", "date", "operation", "outcome", "features", "bugs")
RELEASE_OPTIONAL_FIELDS = ("retry-of", "rollback-of")
RELEASE_FRONTMATTER_FIELDS = (*RELEASE_REQUIRED_FIELDS, *RELEASE_OPTIONAL_FIELDS)
RELEASE_SECTIONS = ("Summary", "Delivery", "Contracts", "Rollback", "Notes")
# The outcome of a record, and of the delivery rows in it (a row is never `partial`).
RECORD_OUTCOMES = ("released", "failed", "partial", "rolled-back")
ROW_OUTCOMES = ("released", "failed", "rolled-back")
DELIVERY_COLUMNS = ("item", "app", "target", "version", "attempt", "outcome", "evidence", "basis")
# The placeholder a proposal carries in `operation`; the board writes the ID of the producing operation when it applies.
OPERATION_PLACEHOLDER = "pending"

KIND_RELEASE = "release"
KIND_ROLLBACK = "rollback"
KIND_REDEPLOY = "redeploy"


def format_record_id(number: int) -> str:
    return f"REL-{number:03d}"


def record_link(record_id: str) -> str:
    """The `Record` cell of a feature or bug Release row: a link from `features/` or `bugs/` to the record."""

    return f"[{record_id}](../releases/{record_id}.md)"


def record_id_of_cell(cell: str) -> str | None:
    """The record a Release row's `Record` cell links, or ``None`` for `—` and for anything that is not the canonical link."""

    match = _RECORD_LINK.match(cell.strip())
    if match is None or match.group("target") != f"../releases/{match.group('id')}.md" or RELEASE_ID_PATTERN.match(match.group("id")) is None:
        return None
    return match.group("id")


# --- Fence-aware sections ---------------------------------------------------------------------------------------------

_FENCE_OPEN = re.compile(r"^ {0,3}(?P<fence>`{3,}|~{3,})(?P<info>[^`]*)$")
_HEADING_2 = re.compile(r"^##[ \t]+(?P<name>.+?)[ \t]*#*[ \t]*$")
_HEADING_3 = re.compile(r"^###[ \t]+(?P<name>.+?)[ \t]*#*[ \t]*$")


def _split_fenced(lines: Sequence[str], heading: "re.Pattern[str]") -> list[tuple[str, list[str]]]:
    """The (heading, lines) groups of `lines` split at `heading` lines that are outside fenced code; text before the first heading is dropped."""

    groups: list[tuple[str, list[str]]] = []
    fence: tuple[str, int] | None = None
    for line in lines:
        opener = _FENCE_OPEN.match(line)
        if fence is None:
            if opener is not None:
                fence = (opener.group("fence")[0], len(opener.group("fence")))
            else:
                match = heading.match(line)
                if match is not None:
                    groups.append((match.group("name").strip(), []))
                    continue
        else:
            stripped = line.strip()
            if stripped and set(stripped) == {fence[0]} and len(stripped) >= fence[1]:
                fence = None
        if groups:
            groups[-1][1].append(line)
    return groups


def record_sections(body: str) -> dict[str, str]:
    """The `##` sections of a record body, with their text; headings inside fenced code (a contract snapshot) are not headings."""

    sections: dict[str, str] = {}
    for name, lines in _split_fenced(body.splitlines(), _HEADING_2):
        sections.setdefault(name, "\n".join(lines))
    return sections


# --- Delivery rows ----------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RecordRow:
    """One row of a record's `## Delivery`: what a record delivered, rolled back or redeployed for an (item, app)."""

    item: str
    app: str
    target: str
    version: str
    attempt: int | None
    outcome: str
    evidence: str
    basis: str
    cells: tuple[str, ...]

    @property
    def pair(self) -> tuple[str, str]:
        return (self.app, self.target)


def parse_record_rows(body: str) -> tuple[list[RecordRow], list[EvidenceProblem]]:
    """The rows of a record's `## Delivery` and the problems with their shape and cells."""

    section = record_sections(body).get("Delivery", "")
    cell_rows, problems = parse_evidence_table("## Delivery\n" + section, "Delivery", DELIVERY_COLUMNS, "release_record_invalid")
    rows: list[RecordRow] = []
    for cells in cell_rows:
        item, app, target, version, attempt_cell, outcome, evidence, basis = cells
        item, app = item.strip(), app.strip()
        subject = f"{item}/{app}"
        if not (FEATURE_ID_PATTERN.match(item) or BUG_ID_PATTERN.match(item)) or not _APP_ID_TOKEN.match(app):
            problems.append(EvidenceProblem("release_record_invalid", f"A Delivery row names an item (`F-XXX` or `BUG-XXX`) and an app; this one has `{item}` and `{app}`.", subject))
            continue
        attempt_text = clean_cell(attempt_cell)
        attempt_match = re.fullmatch(r"release-([1-9][0-9]*)", attempt_text)
        row = RecordRow(
            item,
            app,
            clean_cell(target),
            clean_cell(version),
            int(attempt_match.group(1)) if attempt_match else None,
            clean_cell(outcome).lower(),
            evidence.strip(),
            clean_cell(basis).lower(),
            cells,
        )
        rows.append(row)

        def bad(message: str, code: str = "release_record_invalid") -> None:
            problems.append(EvidenceProblem(code, message, subject))

        if attempt_match is None and attempt_text not in {"—", "–", "-", ""}:
            bad(f"The attempt of `{subject}` must be `release-<n>`, or `—` in a rollback or redeploy record.")
        if row.outcome not in ROW_OUTCOMES:
            bad(f"The outcome of `{subject}` must be one of {', '.join(ROW_OUTCOMES)}.")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", row.target):
            bad(f"The target of `{subject}` must be a short name such as `production`.")
        reason = artifact_reference_problem(version)
        if reason is not None:
            bad(f"The version of `{subject}` {reason}.", "artifact_reference_invalid")
        if not _substantive_evidence_cell(evidence):
            bad(f"The evidence of `{subject}` is empty or still a placeholder.")
        else:
            evidence_reason = release_evidence_problem(evidence)
            if evidence_reason is not None:
                bad(f"The evidence of `{subject}` {evidence_reason}.")
        if row.basis not in CHECKED_BASES:
            bad(f"The basis of `{subject}` must be `checked` or `attested`.", "basis_invalid")
    return rows, problems


# --- Contract snapshots -----------------------------------------------------------------------------------------------

_SNAPSHOT_HEADING = re.compile(r"^(?P<feature>F-[0-9]+)[ \t]+(?P<app>[A-Za-z0-9][A-Za-z0-9._-]*)$")
_SNAPSHOT_CONTRACT = re.compile(r"^-[ \t]+Contract:[ \t]*`?(?P<citation>[^`\s]+)`?[ \t]*$")


@dataclass(frozen=True)
class ContractSnapshot:
    """The contract a feature's delivery row cites, copied verbatim into a record (CONTRACTS 3.4)."""

    feature: str
    app: str
    citation: str
    text: str

    @property
    def digest_citation(self) -> str | None:
        """The citation the snapshot text itself computes, or ``None`` when the text is not a usable contract page."""

        page = parse_markdown_text(Path("snapshot.md"), self.text)
        if page.parse_errors:
            return None
        return contract_page_citation(page.frontmatter, page.body)


def format_snapshot(feature: str, app: str, citation: str, text: str) -> str:
    """The `###` entry of a `## Contracts` section: the citation and the contract page in a fence longer than any run inside it."""

    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * max(4, longest + 1)
    return f"### {feature} {app}\n\n- Contract: `{citation}`\n\n{fence}markdown\n{text.rstrip(chr(10))}\n{fence}\n"


def parse_snapshots(body: str) -> tuple[list[ContractSnapshot], list[str]]:
    """The snapshots of a record's `## Contracts` section and the problems with their form."""

    section = record_sections(body).get("Contracts", "")
    snapshots: list[ContractSnapshot] = []
    problems: list[str] = []
    for name, lines in _split_fenced(section.splitlines(), _HEADING_3):
        heading = _SNAPSHOT_HEADING.match(name)
        if heading is None:
            problems.append(f"The contract entry `### {name}` is not `### F-XXX <app>`.")
            continue
        citation: str | None = None
        text_lines: list[str] | None = None
        fence: tuple[str, int] | None = None
        for line in lines:
            if text_lines is None:
                match = _SNAPSHOT_CONTRACT.match(line.strip())
                if match is not None and citation is None:
                    citation = match.group("citation")
                    continue
                opener = _FENCE_OPEN.match(line)
                if opener is not None:
                    fence = (opener.group("fence")[0], len(opener.group("fence")))
                    text_lines = []
                continue
            stripped = line.strip()
            if fence is not None and stripped and set(stripped) == {fence[0]} and len(stripped) >= fence[1]:
                break
            text_lines.append(line)
        if citation is None or text_lines is None:
            problems.append(f"The contract entry `### {name}` needs a `- Contract:` line and the contract page in a fenced block.")
            continue
        snapshots.append(ContractSnapshot(heading.group("feature"), heading.group("app"), citation, "\n".join(text_lines)))
    return snapshots, problems


# --- The record ----------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ReleaseRecord:
    """A release record read from the wiki. Missing or malformed fields read as ``None`` or empty; lint reports them."""

    page: MarkdownPage

    def _text(self, key: str) -> str | None:
        value = self.page.frontmatter.get(key)
        return value.strip() if isinstance(value, str) and value.strip() else None

    def _ids(self, key: str) -> list[str]:
        value = self.page.frontmatter.get(key)
        return [item.strip() for item in value if isinstance(item, str) and item.strip()] if isinstance(value, list) else []

    @property
    def record_id(self) -> str:
        value = self._text("id")
        if value is not None:
            return value
        match = RELEASE_FILE_PATTERN.match(self.page.path.name)
        return match.group("id") if match else self.page.path.stem

    @property
    def number(self) -> int | None:
        match = RELEASE_ID_PATTERN.match(self.record_id)
        return int(match.group("number")) if match else None

    @property
    def title(self) -> str:
        return self._text("title") or self.page.path.stem

    @property
    def date(self) -> str | None:
        value = self.page.frontmatter.get("date")
        return value.isoformat() if hasattr(value, "isoformat") else (value.strip() if isinstance(value, str) and value.strip() else None)

    @property
    def operation(self) -> str | None:
        return self._text("operation")

    @property
    def outcome(self) -> str | None:
        return self._text("outcome")

    @property
    def features(self) -> list[str]:
        return self._ids("features")

    @property
    def bugs(self) -> list[str]:
        return self._ids("bugs")

    @property
    def retry_of(self) -> str | None:
        return self._text("retry-of")

    @property
    def rollback_of(self) -> str | None:
        return self._text("rollback-of")

    @cached_property
    def rows(self) -> list[RecordRow]:
        return parse_record_rows(self.page.body)[0]

    @cached_property
    def snapshots(self) -> list[ContractSnapshot]:
        return parse_snapshots(self.page.body)[0]

    def rows_for(self, app: str, target: str) -> list[RecordRow]:
        return [row for row in self.rows if row.app == app and row.target == target]


def read_release_records(wiki_root: Path) -> list[ReleaseRecord]:
    """Every release record of a wiki, in number order (a file that is not named for a number comes last, by name)."""

    def read() -> list[ReleaseRecord]:
        records = [ReleaseRecord(page) for page in read_markdown_pages(wiki_root / RELEASE_DIRECTORY)]
        return sorted(records, key=lambda record: (record.number is None, record.number or 0, record.page.path.name))

    # Inside a read scope (one request) the folder is listed once.
    return list(request_fact(("release-records", str(wiki_root)), read))


def release_listing_digest(wiki_root: Path) -> str:
    """The SHA-256 of the file names in `releases/`: a record written between a preview and its apply changes it."""

    directory = wiki_root / RELEASE_DIRECTORY
    names = sorted(path.name for path in directory.glob("*.md") if not path.name.startswith("_")) if directory.is_dir() else []
    return hashlib.sha256("\n".join(names).encode("utf-8")).hexdigest()


def next_release_number(records: Iterable[ReleaseRecord]) -> int:
    """One more than the highest record number on disk."""

    return max((record.number or 0 for record in records), default=0) + 1


def records_by_id(records: Iterable[ReleaseRecord]) -> dict[str, ReleaseRecord]:
    return {record.record_id: record for record in records}


def record_kinds(records: Iterable[ReleaseRecord]) -> dict[str, str]:
    """The kind of each record, by ID: `rollback` (it has `rollback-of`), `redeploy` (its `retry-of` chain reaches a rollback or a redeploy) or `release`.

    A release that retries a failed release names it in `retry-of` too; that chain ends at a release and stays a release.
    """

    listing = list(records)
    index = records_by_id(listing)
    kinds: dict[str, str] = {}

    def kind(record: ReleaseRecord, seen: frozenset[str]) -> str:
        if record.record_id in kinds:
            return kinds[record.record_id]
        if record.rollback_of is not None:
            result = KIND_ROLLBACK
        elif record.retry_of is not None and record.retry_of not in seen and record.retry_of in index:
            source = kind(index[record.retry_of], seen | {record.record_id})
            result = KIND_REDEPLOY if source in {KIND_ROLLBACK, KIND_REDEPLOY} else KIND_RELEASE
        else:
            result = KIND_RELEASE
        kinds[record.record_id] = result
        return result

    for record in listing:
        kind(record, frozenset())
    return kinds


def record_outcome(rows: Sequence[RecordRow], kind: str) -> str:
    """The outcome of a record from its rows (CONTRACTS 6.2): `rolled-back` for a rollback, otherwise `released` when every row is released, `failed` when none is, else `partial`."""

    if kind == KIND_ROLLBACK:
        return "rolled-back"
    released = sum(1 for row in rows if row.outcome == "released")
    if rows and released == len(rows):
        return "released"
    return "failed" if released == 0 else "partial"


def current_delivery(records: Iterable[ReleaseRecord], app: str, target: str) -> tuple[ReleaseRecord, list[RecordRow]] | None:
    """The current delivery of an (app, target): the highest-numbered record with a `released` row for it, with the rows of the pair (CONTRACTS 5.3).

    A redeploy record counts; a rollback record holds `rolled-back` rows and never does.
    """

    best: tuple[int, ReleaseRecord] | None = None
    for record in records:
        number = record.number
        if number is None or not any(row.outcome == "released" for row in record.rows_for(app, target)):
            continue
        if best is None or number > best[0]:
            best = (number, record)
    if best is None:
        return None
    return best[1], best[1].rows_for(app, target)


def latest_record(records: Iterable[ReleaseRecord], app: str, target: str) -> ReleaseRecord | None:
    """The highest-numbered record with any row for an (app, target)."""

    best: ReleaseRecord | None = None
    for record in records:
        if record.number is None or not record.rows_for(app, target):
            continue
        if best is None or record.number > (best.number or 0):
            best = record
    return best


def release_attempt_of(records: Iterable[ReleaseRecord], kinds: Mapping[str, str], item: str, app: str) -> int:
    """The next release attempt of an (item, app): 1 plus the release-kind records with a delivery row for it (CONTRACTS 5.4)."""

    return 1 + sum(
        1
        for record in records
        if kinds.get(record.record_id, KIND_RELEASE) == KIND_RELEASE and any(row.item == item and row.app == app for row in record.rows)
    )
