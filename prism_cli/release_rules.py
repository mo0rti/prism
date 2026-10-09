"""The release rules shared by the board service, the read-only evaluator and lint (CONTRACTS 2.4, 5.3, 6.2, 7).

Each function takes parsed pages and returns the refusals as `Problem` values (the board error code, the message that names
the way out and small details), in the order the contract lists them. The board service raises the first one; the transition
evaluator turns the list into checks; lint turns the findings of a record into diagnostics. Nothing here reads the file system
or writes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from prism_cli.qa_rules import Problem, environments_of
from prism_cli.wiki_bugs import BugPage, blocks
from prism_cli.wiki_model import (
    EvidenceProblem,
    FeatureEvidence,
    clean_cell,
    normalize_feature_id,
)
from prism_cli.wiki_releases import (
    KIND_REDEPLOY,
    KIND_RELEASE,
    KIND_ROLLBACK,
    OPERATION_PLACEHOLDER,
    RECORD_OUTCOMES,
    RELEASE_FILE_PATTERN,
    RELEASE_FRONTMATTER_FIELDS,
    RELEASE_ID_PATTERN,
    RELEASE_OPTIONAL_FIELDS,
    RELEASE_REQUIRED_FIELDS,
    RELEASE_SECTIONS,
    ContractSnapshot,
    ReleaseRecord,
    RecordRow,
    current_delivery,
    latest_record,
    record_id_of_cell,
    record_outcome,
    record_sections,
)

# A feature's Release row is written in one of two outcomes; `pending` is what `qa-pass` writes.
RELEASE_ROW_OUTCOMES = ("released", "failed")
# The domains that must be cleared before an app is released (CONTRACTS 2.4 `release-done`).
BLOCKING_APP_DOMAINS = ("implementation", "tests", "qa")


def _quoted(values: Iterable[str]) -> str:
    return ", ".join(f"`{value}`" for value in values)


def _cells(row: Any) -> tuple[str, ...]:
    return tuple(cell.strip() for cell in row.cells)


# --- The record page (CONTRACTS 6.2) -------------------------------------------------------------------------------------


def check_record_page(
    path: str,
    frontmatter: Mapping[str, Any],
    body: str,
    *,
    today: date | None = None,
    proposal: bool = False,
    parse_errors: Sequence[str] = (),
) -> list[Problem]:
    """The shape of a release record: its fields, name, date, sections and delivery table.

    With `proposal` the page is being written: its `operation` is the placeholder the board replaces when it applies, and its
    `date` is `today`, the preview day (`record_date_invalid`). Without it the page is on disk, where `operation` names the
    producing operation and `date` is any valid day.
    """

    problems: list[Problem] = []
    name = Path(path).name

    def bad(message: str, code: str = "release_record_invalid", **details: Any) -> None:
        problems.append(Problem(code, f"`{path}`: {message}", {"path": path, **details}))

    for error in parse_errors:
        bad(error)
    for key in frontmatter:
        if key not in RELEASE_FRONTMATTER_FIELDS:
            bad(f"`{key}` is not a release record field; a record carries only {_quoted(RELEASE_FRONTMATTER_FIELDS)}.")
    for key in RELEASE_REQUIRED_FIELDS:
        if key not in frontmatter:
            bad(f"the front matter field `{key}` is missing.")
    record_id = frontmatter.get("id")
    file_match = RELEASE_FILE_PATTERN.match(name)
    if "id" in frontmatter:
        if not isinstance(record_id, str) or RELEASE_ID_PATTERN.match(record_id.strip()) is None:
            bad("`id` must be `REL-` and the number with at least three digits and no other padding, such as `REL-001` or `REL-1042`.")
        elif file_match is None or file_match.group("id") != record_id.strip():
            bad(f"the file name must be `{record_id.strip()}.md`.")
    elif file_match is None:
        bad("the file name must be `REL-<n>.md`.")
    title = frontmatter.get("title")
    if "title" in frontmatter and (not isinstance(title, str) or not title.strip()):
        bad("`title` must be a non-empty string.")
    day = frontmatter.get("date")
    day_text = day.isoformat() if hasattr(day, "isoformat") else (day.strip() if isinstance(day, str) else None)
    if "date" in frontmatter:
        valid = False
        if isinstance(day_text, str) and len(day_text) == 10:
            try:
                date.fromisoformat(day_text)
                valid = True
            except ValueError:
                valid = False
        if not valid:
            bad("`date` must be a day, `YYYY-MM-DD`.", "record_date_invalid")
        elif proposal and today is not None and day_text != today.isoformat():
            bad(f"`date` is the preview day, {today.isoformat()}; the record says {day_text}.", "record_date_invalid", expected=today.isoformat())
    operation = frontmatter.get("operation")
    if "operation" in frontmatter:
        if not isinstance(operation, str) or not operation.strip():
            bad("`operation` must name the producing operation.")
        elif proposal and operation.strip() != OPERATION_PLACEHOLDER:
            bad(f"`operation` is `{OPERATION_PLACEHOLDER}` in a proposal; the board writes the ID of the operation that applies it.")
    if "outcome" in frontmatter and frontmatter.get("outcome") not in RECORD_OUTCOMES:
        bad(f"`outcome` must be one of {_quoted(RECORD_OUTCOMES)}.")
    for key, pattern_name in (("features", "F-XXX"), ("bugs", "BUG-XXX")):
        value = frontmatter.get(key)
        if key in frontmatter and (not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value) or len(set(value)) != len(value)):
            bad(f"`{key}` must be a list of distinct {pattern_name} IDs (an empty list when there are none).")
    for key in RELEASE_OPTIONAL_FIELDS:
        if key in frontmatter and (not isinstance(frontmatter[key], str) or RELEASE_ID_PATTERN.match(frontmatter[key].strip()) is None):
            bad(f"`{key}` must name a release record, such as `REL-001`.")
    if "retry-of" in frontmatter and "rollback-of" in frontmatter:
        bad("a record is a rollback (`rollback-of`) or a retry (`retry-of`), not both.")
    sections = record_sections(body)
    absent = [heading for heading in RELEASE_SECTIONS if heading not in sections]
    if absent:
        bad(f"the page needs the section(s) {_quoted(f'## {heading}' for heading in absent)}.", sections=absent)
    if "Summary" in sections and not sections["Summary"].strip():
        bad("the `## Summary` section is empty.")
    return problems


def record_row_problems(rows: Sequence[RecordRow], kind: str, parse_problems: Sequence[EvidenceProblem] = ()) -> list[Problem]:
    """The rows of a record: their cells, their attempts by the kind of the record and one outcome and version for each (app, target) (CONTRACTS 6.2)."""

    problems: list[Problem] = [Problem(item.code, item.message, {"row": item.subject}) for item in parse_problems]
    if not rows:
        problems.append(Problem("release_record_invalid", "The `## Delivery` table of a release record has at least one row.", {}))
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (row.item, row.app)
        if key in seen:
            problems.append(Problem("release_record_invalid", f"The `## Delivery` table has two rows for `{row.item}` and `{row.app}`; one row delivers an item for an app.", {"item": row.item, "app": row.app}))
        seen.add(key)
        if kind == KIND_RELEASE:
            if row.attempt is None:
                problems.append(Problem("release_record_invalid", f"The attempt of `{row.item}`/`{row.app}` is `release-<n>` in a release record.", {"item": row.item, "app": row.app}))
            if row.outcome == "rolled-back":
                problems.append(Problem("release_record_invalid", f"`{row.item}`/`{row.app}` is `rolled-back`; only a rollback record has such a row.", {"item": row.item, "app": row.app}))
        else:
            if row.attempt is not None:
                problems.append(
                    Problem("release_record_invalid", f"The attempt of `{row.item}`/`{row.app}` is `—` in a {kind} record; its attempts are not counted.", {"item": row.item, "app": row.app})
                )
            if kind == KIND_ROLLBACK and row.outcome != "rolled-back":
                problems.append(Problem("release_record_invalid", f"A rollback record's rows are `rolled-back`; `{row.item}`/`{row.app}` is `{row.outcome}`.", {"item": row.item, "app": row.app}))
            if kind == KIND_REDEPLOY and row.outcome == "rolled-back":
                problems.append(Problem("release_record_invalid", f"`{row.item}`/`{row.app}` is `rolled-back`; a redeploy record delivers or fails.", {"item": row.item, "app": row.app}))
    problems.extend(group_conflicts(rows))
    return problems


def group_conflicts(rows: Sequence[RecordRow]) -> list[Problem]:
    """Every row for one (app, target) in a record shares its Version and Outcome (`release_artifact_conflict`)."""

    problems: list[Problem] = []
    groups: dict[tuple[str, str], list[RecordRow]] = {}
    for row in rows:
        groups.setdefault(row.pair, []).append(row)
    for (app, target), items in groups.items():
        versions = sorted({row.version for row in items})
        outcomes = sorted({row.outcome for row in items})
        if len(versions) > 1 or len(outcomes) > 1:
            problems.append(
                Problem(
                    "release_artifact_conflict",
                    f"The rows for `{app}` at `{target}` do not agree: versions {_quoted(versions)}, outcomes {_quoted(outcomes)}. "
                    "One deployment of an app delivers one version with one outcome; release the items that share it together, or separately.",
                    {"app": app, "target": target, "versions": versions, "outcomes": outcomes},
                )
            )
    return problems


def record_front_matter_problems(path: str, frontmatter: Mapping[str, Any], rows: Sequence[RecordRow], kind: str) -> list[Problem]:
    """The `features`, `bugs` and `outcome` of a record follow its rows."""

    problems: list[Problem] = []
    listed_features = sorted(item.strip() for item in frontmatter.get("features", []) if isinstance(item, str)) if isinstance(frontmatter.get("features"), list) else None
    listed_bugs = sorted(item.strip() for item in frontmatter.get("bugs", []) if isinstance(item, str)) if isinstance(frontmatter.get("bugs"), list) else None
    row_features = sorted({row.item for row in rows if row.item.startswith("F-")})
    row_bugs = sorted({row.item for row in rows if row.item.startswith("BUG-")})
    if listed_features is not None and listed_features != row_features:
        problems.append(
            Problem("release_record_invalid", f"`{path}`: `features` lists {_quoted(listed_features) or 'none'}, but the Delivery rows name {_quoted(row_features) or 'none'}.", {"path": path})
        )
    if listed_bugs is not None and listed_bugs != row_bugs:
        problems.append(Problem("release_record_invalid", f"`{path}`: `bugs` lists {_quoted(listed_bugs) or 'none'}, but the Delivery rows name {_quoted(row_bugs) or 'none'}.", {"path": path}))
    outcome = frontmatter.get("outcome")
    if outcome in RECORD_OUTCOMES and rows:
        expected = record_outcome(rows, kind)
        if outcome != expected:
            problems.append(Problem("release_record_invalid", f"`{path}`: `outcome` is `{outcome}`, but its rows make the record `{expected}`.", {"path": path, "expected": expected}))
    return problems


# --- Rollback and redeploy (F21, F22) ------------------------------------------------------------------------------------


def _pairs(rows: Sequence[RecordRow]) -> list[tuple[str, str]]:
    return list(dict.fromkeys(row.pair for row in rows))


def rollback_problems(
    *,
    rollback_of: str,
    rows: Sequence[RecordRow],
    records: Sequence[ReleaseRecord],
    kinds: Mapping[str, str],
) -> list[Problem]:
    """A rollback names the current delivery of every (app, target) it rolls back and lists the items that delivery carried (`rollback_target_invalid`)."""

    index = {record.record_id: record for record in records}
    target = index.get(rollback_of)
    if target is None:
        return [Problem("rollback_target_invalid", f"`rollback-of: {rollback_of}` names no release record.", {"rollback_of": rollback_of})]
    if kinds.get(rollback_of) == KIND_ROLLBACK:
        return [Problem("rollback_target_invalid", f"{rollback_of} is itself a rollback; a rollback rolls back a delivery.", {"rollback_of": rollback_of})]
    problems: list[Problem] = []
    for app, target_name in _pairs(rows):
        current = current_delivery(records, app, target_name)
        if current is None or current[0].record_id != rollback_of:
            held = current[0].record_id if current is not None else None
            problems.append(
                Problem(
                    "rollback_target_invalid",
                    f"{rollback_of} is not the current delivery of `{app}` at `{target_name}`"
                    + (f"; {held} is, and a rollback binds to it." if held else "; nothing has been delivered there.")
                    + " Roll back the current delivery.",
                    {"app": app, "target": target_name, "current": held},
                )
            )
            continue
        latest = latest_record(records, app, target_name)
        if latest is not None and latest.record_id != rollback_of and kinds.get(latest.record_id) == KIND_ROLLBACK and latest.rollback_of == rollback_of:
            problems.append(
                Problem(
                    "rollback_target_invalid",
                    f"{rollback_of} is already rolled back for `{app}` at `{target_name}` by {latest.record_id}. Redeploy it with `--redeploy {latest.record_id}`, or release again.",
                    {"app": app, "target": target_name, "rollback": latest.record_id},
                )
            )
            continue
        delivered = sorted((row.item, row.version) for row in target.rows_for(app, target_name) if row.outcome == "released")
        listed = sorted((row.item, row.version) for row in rows if row.pair == (app, target_name))
        if delivered != listed:
            problems.append(
                Problem(
                    "rollback_target_invalid",
                    f"The rollback of `{app}` at `{target_name}` lists the items {rollback_of} delivered there ("
                    + (", ".join(f"`{item}`" for item, _version in delivered) or "none")
                    + ") at the version they were delivered; it lists "
                    + (", ".join(f"`{item}`" for item, _version in listed) or "none")
                    + ".",
                    {"app": app, "target": target_name},
                )
            )
    return problems


def redeploy_problems(
    *,
    retry_of: str,
    rows: Sequence[RecordRow],
    records: Sequence[ReleaseRecord],
    kinds: Mapping[str, str],
) -> list[Problem]:
    """A redeploy retries the latest record of every (app, target) it redeploys: a rollback of the current delivery, or a failed redeploy of it."""

    index = {record.record_id: record for record in records}
    problems: list[Problem] = []
    for app, target_name in _pairs(rows):
        current = current_delivery(records, app, target_name)
        latest = latest_record(records, app, target_name)
        if current is None:
            problems.append(Problem("app_stage_mismatch", f"Nothing has been delivered to `{app}` at `{target_name}`, so there is nothing to redeploy.", {"app": app, "target": target_name}))
            continue
        if latest is None or latest.record_id != retry_of:
            problems.append(
                Problem(
                    "app_stage_mismatch",
                    f"`retry-of: {retry_of}` is not the latest record for `{app}` at `{target_name}`"
                    + (f" ({latest.record_id} is)." if latest is not None else ".")
                    + " A redeploy follows the latest record.",
                    {"app": app, "target": target_name, "latest": latest.record_id if latest is not None else None},
                )
            )
            continue
        source = latest
        kind = kinds.get(source.record_id)
        if kind == KIND_REDEPLOY and any(row.outcome != "failed" for row in source.rows_for(app, target_name)):
            problems.append(
                Problem(
                    "app_stage_mismatch",
                    f"{source.record_id} redeployed `{app}` at `{target_name}` successfully; a redeploy retries a rollback or a failed redeploy.",
                    {"app": app, "target": target_name},
                )
            )
            continue
        root = source
        seen = {root.record_id}
        while kinds.get(root.record_id) == KIND_REDEPLOY and root.retry_of in index and root.retry_of not in seen:
            root = index[root.retry_of]
            seen.add(root.record_id)
        if kinds.get(root.record_id) != KIND_ROLLBACK or root.rollback_of != current[0].record_id:
            problems.append(
                Problem(
                    "app_stage_mismatch",
                    f"{retry_of} is not a rollback of the current delivery of `{app}` at `{target_name}` ({current[0].record_id}), nor a failed redeploy of it.",
                    {"app": app, "target": target_name, "current": current[0].record_id},
                )
            )
            continue
        delivered = sorted({row.version for row in current[1] if row.outcome == "released"})
        listed = sorted({row.version for row in rows if row.pair == (app, target_name)})
        if listed != delivered:
            problems.append(
                Problem(
                    "redeploy_version_mismatch",
                    f"A redeploy of `{app}` at `{target_name}` delivers the version of the current delivery, {_quoted(delivered)}; the record says {_quoted(listed)}.",
                    {"app": app, "target": target_name, "expected": delivered},
                )
            )
            continue
        items = sorted(row.item for row in current[1] if row.outcome == "released")
        listed_items = sorted(row.item for row in rows if row.pair == (app, target_name))
        if items != listed_items:
            problems.append(
                Problem(
                    "redeploy_version_mismatch",
                    f"A redeploy of `{app}` at `{target_name}` lists the items of the current delivery ({_quoted(items)}); the record lists {_quoted(listed_items)}.",
                    {"app": app, "target": target_name, "expected": items},
                )
            )
    return problems


# --- The Release rows a feature or bug carries (F18, F19, B14) ------------------------------------------------------------


def target_of(policy: Mapping[str, Any] | None, app: str) -> str | None:
    """The delivery target an app resolves to in the policy (`SETTINGS.md` and the stack defaults), or ``None``."""

    entry = ((policy or {}).get("delivery_targets") or {}).get(app) or {}
    target = entry.get("target")
    return target if isinstance(target, str) and target else None


def release_row_cells(app: str, target: str, version: str, attempt: int, outcome: str, record_id: str, basis: str) -> list[str]:
    from prism_cli.wiki_releases import record_link

    return [app, target, f"`{version}`", f"release-{attempt}", outcome, record_link(record_id), basis]


@dataclass(frozen=True)
class ReleasedApp:
    """One app a feature release delivers: the row it ends with."""

    app: str
    target: str
    version: str
    attempt: int
    outcome: str
    basis: str


def check_feature_release_rows(
    *,
    feature_id: str,
    old: FeatureEvidence,
    new: FeatureEvidence,
    stages: Mapping[str, str],
    active: Sequence[str],
    policy: Mapping[str, Any] | None,
    attempt_of: Any,
    record_id: str,
    fix_apps: Iterable[str] = (),
) -> tuple[list[ReleasedApp], list[Problem]]:
    """The apps a `release-done` delivers (those whose `pending` or `failed` authoritative Release row becomes `released` or `failed`) and the refusals for the rows (CONTRACTS 2.4, 5.3).

    `attempt_of(app)` is the release attempt the row must carry; `record_id` the record the proposal writes. A `released` row is
    never rewritten here: a bug fix updates it, and the rows of the `fix_apps` it reaches are judged by `check_bug_fix_row`.
    Staging rows (attempt `—`) are informational.
    """

    problems: list[Problem] = []
    skipped = set(fix_apps)
    delivered = {row.app: clean_cell(row.artifact) for row in old.delivery}
    old_cells = {_cells(row) for row in old.release}
    new_cells = {_cells(row) for row in new.release}
    seen = {(item.code, item.message) for item in old.problems}
    for item in new.problems:
        if item.code in {"release_row_invalid", "artifact_reference_invalid", "basis_invalid"} and item.subject is not None and (item.code, item.message) not in seen:
            if item.subject not in skipped and any(row.app == item.subject and _cells(row) not in old_cells for row in new.release):
                problems.append(Problem(item.code, item.message, {"app": item.subject}))
    named: list[ReleasedApp] = []
    for row in old.release:
        if _cells(row) in new_cells or row.app in skipped:
            continue
        if row.authoritative and row.outcome in {"pending", "failed"} and row.app in active:
            continue  # the row the release replaces
        if row.authoritative:
            problems.append(
                Problem(
                    "release_row_invalid",
                    f"`release-done` never removes the authoritative Release row of `{row.app}` ({row.outcome}); a return or a reopen archives it.",
                    {"app": row.app},
                )
            )
    authoritative_apps: dict[str, int] = {}
    for row in new.release:
        if _cells(row) in old_cells or row.app in skipped:
            continue
        if row.app not in active:
            problems.append(Problem("undeclared_app_row", f"The Release row of `{row.app}` names an app that is not active in the feature's scope.", {"app": row.app}))
            continue
        if not row.authoritative:
            if row.target not in environments_of(policy, row.app):
                problems.append(
                    Problem(
                        "environment_unknown",
                        f"The staging Release row of `{row.app}` names the environment `{row.target}`, which its delivery target does not declare.",
                        {"app": row.app, "environment": row.target},
                    )
                )
            continue
        authoritative_apps[row.app] = authoritative_apps.get(row.app, 0) + 1
        previous = old.authoritative_release(row.app)
        if authoritative_apps[row.app] > 1:
            problems.append(Problem("duplicate_app_row", f"`{row.app}` has more than one authoritative Release row.", {"app": row.app}))
            continue
        if stages.get(row.app) != "ready-for-release" or previous is None or previous.outcome not in {"pending", "failed"}:
            problems.append(
                Problem(
                    "app_stage_mismatch",
                    f"`release-done` names apps at `ready-for-release` with a `pending` or `failed` Release row, but `{row.app}` is {stages.get(row.app, 'unknown')}.",
                    {"app": row.app, "stage": stages.get(row.app)},
                )
            )
            continue
        expected = attempt_of(row.app)
        if row.attempt != expected:
            problems.append(
                Problem(
                    "release_attempt_mismatch",
                    f"The Release row of `{row.app}` is attempt release-{row.attempt}, but the attempt this release makes is release-{expected} "
                    "(one more than the release records that delivered it for this feature).",
                    {"app": row.app, "expected": f"release-{expected}"},
                )
            )
            continue
        if row.outcome not in RELEASE_ROW_OUTCOMES:
            problems.append(Problem("release_row_invalid", f"`release-done` writes the Release row of `{row.app}` as `released` or `failed`, not `{row.outcome}`.", {"app": row.app}))
            continue
        target = target_of(policy, row.app)
        if target is None:
            problems.append(
                Problem(
                    "delivery_target_missing",
                    f"`{row.app}` has no delivery target: declare one under `delivery-targets` in SETTINGS.md (an app of the `other` stack must).",
                    {"app": row.app},
                )
            )
            continue
        if row.target != target:
            problems.append(
                Problem(
                    "release_target_mismatch",
                    f"The Release row of `{row.app}` names the target `{row.target}`; its delivery target in SETTINGS.md is `{target}`. `release-done` fills the target from the current settings.",
                    {"app": row.app, "expected": target},
                )
            )
            continue
        if row.version != delivered.get(row.app):
            problems.append(
                Problem(
                    "release_version_not_verified",
                    f"The Release row of `{row.app}` names `{row.version}`, but the artifact QA verified is `{delivered.get(row.app)}`. A release delivers the verified artifact.",
                    {"app": row.app, "delivered": delivered.get(row.app)},
                )
            )
            continue
        if record_id_of_cell(row.record) != record_id:
            problems.append(
                Problem(
                    "release_row_invalid",
                    f"The Record cell of `{row.app}` is `{row.record}`; it links the record of this release, `[{record_id}](../releases/{record_id}.md)`.",
                    {"app": row.app, "record": record_id},
                )
            )
            continue
        named.append(ReleasedApp(row.app, row.target, row.version, row.attempt or 0, row.outcome, row.basis))
    return named, problems


def check_bug_fix_row(
    *,
    feature_id: str,
    app: str,
    old: FeatureEvidence,
    new: FeatureEvidence,
    version: str,
    record_id: str,
) -> list[Problem]:
    """The Release row of a feature app that is already released and receives a bug fix: it keeps its target, attempt and outcome, and names the new record and the bug's verification artifact (CONTRACTS 5.3)."""

    before = old.authoritative_release(app)
    after = new.authoritative_release(app)
    if before is None or before.outcome != "released":
        return [Problem("release_row_invalid", f"{feature_id} has no released Release row for `{app}` that a bug fix could update.", {"app": app})]
    if after is None:
        return [Problem("release_row_invalid", f"The proposal removes the Release row of `{app}` in {feature_id}; a bug fix updates it to name the new record.", {"app": app})]
    problems: list[Problem] = []
    if (after.target, after.attempt, after.outcome) != (before.target, before.attempt, before.outcome):
        problems.append(
            Problem(
                "release_row_invalid",
                f"A bug fix keeps the target, attempt and outcome of the Release row of `{app}` in {feature_id} ({before.target}, release-{before.attempt}, {before.outcome}); it changes the Version and the Record.",
                {"app": app},
            )
        )
    if after.version != version:
        problems.append(
            Problem(
                "release_version_not_verified",
                f"The Release row of `{app}` in {feature_id} names `{after.version}`; the bug fix delivers `{version}`.",
                {"app": app, "expected": version},
            )
        )
    if record_id_of_cell(after.record) != record_id:
        problems.append(
            Problem(
                "release_row_invalid",
                f"The Record cell of `{app}` in {feature_id} is `{after.record}`; it links the record of this release, `[{record_id}](../releases/{record_id}.md)`.",
                {"app": app, "record": record_id},
            )
        )
    if after.basis not in {"checked", "attested"}:
        problems.append(Problem("basis_invalid", f"The basis of the Release row of `{app}` in {feature_id} must be `checked` or `attested`.", {"app": app}))
    return problems


def bug_release_inclusion_problems(
    bugs: Sequence[BugPage],
    *,
    feature_id: str,
    named: Sequence[str],
    included: Mapping[str, set[str]],
) -> list[Problem]:
    """Every `verified` bug linked to the feature and a released app is included in the release for that app (`verified_bug_not_included`)."""

    problems: list[Problem] = []
    for app in named:
        for bug in bugs:
            if bug.status != "verified" or bug.feature is None or normalize_feature_id(bug.feature) != normalize_feature_id(feature_id) or app not in bug.apps:
                continue
            if app not in included.get(bug.bug_id, set()):
                problems.append(
                    Problem(
                        "verified_bug_not_included",
                        f"`{bug.bug_id}` is verified for `{app}` of {feature_id}, so it ships with the release of `{app}`: add it to the release, with its own Release row for `{app}`.",
                        {"bug": bug.bug_id, "app": app},
                    )
                )
    return problems


def release_bug_blocking(bugs: Sequence[BugPage], *, feature_id: str, named: Sequence[str]) -> list[Problem]:
    """A bug that blocks the app now blocks the release (`open_bug_blocks_release`)."""

    problems: list[Problem] = []
    for app in named:
        blocking = [bug for bug in bugs if blocks(bug, feature_id, app)]
        if blocking:
            problems.append(
                Problem(
                    "open_bug_blocks_release",
                    f"{', '.join(f'`{bug.bug_id}` ({bug.status})' for bug in blocking)} block `{app}`. Verify or close the bug (a non-blocking bug can be deferred by the product owner), "
                    "or return the app with qa-fail citing it.",
                    {"app": app, "bugs": [bug.bug_id for bug in blocking]},
                )
            )
    return problems


# --- Contract snapshots (CONTRACTS 3.4) ----------------------------------------------------------------------------------


def snapshot_problems(
    snapshots: Sequence[ContractSnapshot],
    snapshot_parse_problems: Sequence[str],
    *,
    expected: Mapping[tuple[str, str], tuple[str, str | None]],
    path: str,
) -> list[Problem]:
    """The `## Contracts` section of a record snapshots, verbatim, the contract each listed feature row cites.

    `expected` maps (feature, app) to the citation the feature's delivery row cites and the current text of the contract page
    (``None`` when the page is not available, as in lint of an old record).
    """

    problems: list[Problem] = [Problem("release_contract_snapshot_invalid", f"`{path}`: {message}", {"path": path}) for message in snapshot_parse_problems]
    by_key = {(item.feature, item.app): item for item in snapshots}
    if len(by_key) != len(snapshots):
        problems.append(Problem("release_contract_snapshot_invalid", f"`{path}`: the `## Contracts` section has two entries for one feature and app.", {"path": path}))
    for key in sorted(set(by_key) - set(expected)):
        problems.append(
            Problem("release_contract_snapshot_invalid", f"`{path}`: `## Contracts` snapshots a contract for {key[0]} and `{key[1]}`, which no row of this record cites.", {"path": path, "feature": key[0], "app": key[1]})
        )
    for key, (citation, current_text) in sorted(expected.items()):
        feature, app = key
        entry = by_key.get(key)
        if entry is None:
            problems.append(
                Problem(
                    "release_contract_snapshot_invalid",
                    f"`{path}`: {feature} delivered `{app}` against the contract `{citation}`; the record's `## Contracts` section snapshots it under `### {feature} {app}`.",
                    {"path": path, "feature": feature, "app": app},
                )
            )
            continue
        computed = entry.digest_citation
        if entry.citation != citation or computed != citation:
            problems.append(
                Problem(
                    "release_contract_snapshot_invalid",
                    f"`{path}`: the snapshot of {feature} for `{app}` states `{entry.citation}` and its text digests to `{computed}`; the delivery row cites `{citation}`.",
                    {"path": path, "feature": feature, "app": app},
                )
            )
        elif current_text is not None and _normalized(entry.text) != _normalized(current_text):
            problems.append(
                Problem(
                    "release_contract_snapshot_invalid",
                    f"`{path}`: the snapshot of {feature} for `{app}` is not the contract page verbatim.",
                    {"path": path, "feature": feature, "app": app},
                )
            )
    return problems


def _normalized(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").strip().split("\n"))


def contract_cited_by(delivery_cells: Sequence[str]) -> str | None:
    """The citation of a Delivery evidence row's Contract cell, or ``None`` for `none`."""

    cell = clean_cell(delivery_cells[2]) if len(delivery_cells) > 2 else "none"
    return None if cell.lower() == "none" else cell


# --- Record against the pages that name it (lint) -------------------------------------------------------------------------


def row_record_mismatch(
    *,
    item: str,
    app: str,
    row_target: str,
    row_version: str,
    row_outcome: str,
    record: ReleaseRecord,
    linked_bugs: Sequence[str] = (),
) -> str | None:
    """Why a feature or bug Release row disagrees with its record, or ``None`` (`release-row-record-mismatch`).

    The record's row is the one for the same (item, app); a feature row whose app was released by a bug fix is matched by the
    record's row for a bug linked to the feature.
    """

    candidates = [row for row in record.rows if row.app == app and row.item == item]
    if not candidates:
        candidates = [row for row in record.rows if row.app == app and row.item in linked_bugs]
    if not candidates:
        return f"{record.record_id} has no Delivery row for `{app}` of {item}"
    if not any((row.target, row.version, row.outcome) == (row_target, row_version, row_outcome) for row in candidates):
        wanted = candidates[0]
        return (
            f"the row says {row_target}, {row_version}, {row_outcome}; {record.record_id} says {wanted.target}, {wanted.version}, {wanted.outcome} for `{app}`"
        )
    return None
