"""The QA, `qa-fail`, return and bug rules shared by the board service and the read-only evaluator.

Each function takes parsed pages and returns the refusals as `Problem` values, in the order the contract lists them. The
board service raises the first one as a board error with the code; the transition evaluator turns the list into checks.
Nothing here reads the file system except `release_attempt_for`, and nothing writes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from prism_cli.wiki_bugs import (
    BugPage,
    blocks,
    duplicate_problems,
    verification_artifact,
)
from prism_cli.wiki_model import (
    APP_REVALIDATION_DOMAINS,
    Criterion,
    EvidenceProblem,
    FeatureEvidence,
    HistoryEntry,
    QaRow,
    active_scope,
    app_stages,
    clean_cell,
    merge_revalidation,
    parse_evidence_table,
    qa_attempt,
    qa_coverage,
    read_markdown_pages,
    release_attempt,
)

# The stages in which QA rows can be written for an app, and in which it can pass or fail QA.
QA_STAGES = ("ready-for-qa", "in-qa")
QA_FAIL_STAGES = ("ready-for-qa", "in-qa", "ready-for-release")
# The environments every app can name besides the ones its delivery target declares (CONTRACTS 7).
GENERIC_ENVIRONMENTS = ("local", "ci")
QA_PROBLEM_CODES = frozenset({"qa_row_invalid", "artifact_reference_invalid", "basis_invalid"})
RELEASE_PROBLEM_CODES = frozenset({"release_row_invalid", "artifact_reference_invalid", "basis_invalid"})


@dataclass(frozen=True)
class Problem:
    """One refusal: the board error code, the message that names the way out, and small structured details."""

    code: str
    message: str
    details: Mapping[str, Any] = field(default_factory=dict)


def _cells(row: Any) -> tuple[str, ...]:
    return tuple(cell.strip() for cell in row.cells)


def _quoted(values: Iterable[str]) -> str:
    return ", ".join(f"`{value}`" for value in values)


# --- QA rows (F12, F13, F14) ----------------------------------------------------------------------------------------


def qa_row_changes(old: Sequence[QaRow], new: Sequence[QaRow]) -> tuple[list[QaRow], list[QaRow]]:
    """The rows a write adds or changes, and the rows it removes, compared by their cells."""

    old_cells = {_cells(row) for row in old}
    new_cells = {_cells(row) for row in new}
    return [row for row in new if _cells(row) not in old_cells], [row for row in old if _cells(row) not in new_cells]


def expected_qa_attempt(row: QaRow, history: Sequence[HistoryEntry]) -> int:
    """The attempt a row must carry: the app's current attempt, or for an integration row the highest among its participants."""

    return max(qa_attempt(app, history) for app in row.apps)


def environments_of(policy: Mapping[str, Any] | None, app: str) -> set[str]:
    """The environments an app's QA rows may name: `local`, `ci` and the environments of its delivery target."""

    targets = (policy or {}).get("delivery_targets") or {}
    entry = targets.get(app) or {}
    return {*GENERIC_ENVIRONMENTS, *(entry.get("environments") or [])}


def check_qa_rows(
    *,
    old: FeatureEvidence,
    new: FeatureEvidence,
    criteria: Sequence[Criterion],
    history: Sequence[HistoryEntry],
    scope: Sequence[str],
    active: Sequence[str],
    policy: Mapping[str, Any] | None,
) -> list[Problem]:
    """The refusals for the QA rows a proposal adds, changes or removes (CONTRACTS 2.4 `qa-verify`, 5.2).

    `scope` is the feature's `apps`, `active` its active apps. Stages are those of the page before the write, so the rows
    a clean `qa-pass` adds are judged against the apps as they stand. A row is replaced when the proposal removes it and
    writes a row with the same key for each criterion it cited; any other removed row is not archived by this write.
    """

    problems: list[Problem] = []
    added, removed = qa_row_changes(old.qa, new.qa)
    seen_problems = {(item.code, item.message) for item in old.problems}
    for item in new.problems:
        if item.code in QA_PROBLEM_CODES and (item.code, item.message) not in seen_problems and _is_qa_problem(item):
            problems.append(Problem(item.code, item.message, {"row": item.subject}))
    stages = app_stages(active, old)
    by_number = {criterion.number: criterion for criterion in criteria if criterion.number is not None}
    delivered = {row.app: clean_cell(row.artifact) for row in old.delivery}
    for row in added:
        outside = [app for app in row.apps if app not in scope or app not in active]
        if outside:
            problems.append(
                Problem(
                    "undeclared_app_row",
                    f"The QA row `{row.key}` names {_quoted(outside)}, which {'is' if len(outside) == 1 else 'are'} not in the active scope of the feature ({_quoted(active) or 'none'}).",
                    {"row": row.key, "apps": outside},
                )
            )
            continue
        if row.integration:
            in_qa = [app for app in row.apps if stages.get(app) in QA_STAGES]
            undelivered = [app for app in row.apps if stages.get(app) == "in-dev"]
            if not in_qa or undelivered:
                problems.append(
                    Problem(
                        "app_stage_mismatch",
                        f"The integration row `{row.key}` needs every participant delivered and at least one at `ready-for-qa` or `in-qa`; "
                        + ", ".join(f"`{app}` is {stages.get(app, 'unknown')}" for app in row.apps)
                        + ".",
                        {"row": row.key, "stages": {app: stages.get(app) for app in row.apps}},
                    )
                )
                continue
        elif stages.get(row.apps[0]) not in QA_STAGES:
            problems.append(
                Problem(
                    "app_stage_mismatch",
                    f"QA rows are written for apps at `ready-for-qa` or `in-qa`, but `{row.apps[0]}` is {stages.get(row.apps[0], 'unknown')}.",
                    {"row": row.key, "app": row.apps[0], "stage": stages.get(row.apps[0])},
                )
            )
            continue
        for app in row.apps:
            if row.artifacts.get(app) != delivered.get(app):
                problems.append(
                    Problem(
                        "qa_artifact_mismatch",
                        f"The QA row `{row.key}` verified `{row.artifacts.get(app)}` for `{app}`, but its delivered artifact is `{delivered.get(app)}`. "
                        "Verify and cite the delivered artifact.",
                        {"row": row.key, "app": app, "delivered": delivered.get(app)},
                    )
                )
        for ref in row.criteria:
            criterion = by_number.get(ref.number)
            applies = (
                criterion is not None
                and criterion.revision is not None
                and criterion.integration == row.integration
                and (set(row.apps) == set(criterion.applies_to) if row.integration else row.apps[0] in criterion.applies_to)
            )
            if not applies:
                problems.append(
                    Problem(
                        "criterion_not_applicable",
                        f"`AC-{ref.number}` does not apply to the QA row `{row.key}`: "
                        + (
                            "the feature has no such criterion."
                            if criterion is None
                            else "an integration criterion is verified by an integration row of exactly its participants, and a per-app criterion by the row of an app it lists."
                        ),
                        {"row": row.key, "criterion": f"AC-{ref.number}"},
                    )
                )
            elif criterion is not None and criterion.revision != ref.revision:
                problems.append(
                    Problem(
                        "criterion_revision_stale",
                        f"The QA row `{row.key}` cites `AC-{ref.number}` at a revision that has changed; cite `AC-{ref.number}@{criterion.revision}`.",
                        {"row": row.key, "criterion": f"AC-{ref.number}", "current": criterion.revision},
                    )
                )
        expected = expected_qa_attempt(row, history)
        if row.attempt != expected:
            problems.append(
                Problem(
                    "qa_attempt_mismatch",
                    f"The QA row `{row.key}` is in attempt qa-{row.attempt}, but the current attempt is qa-{expected}.",
                    {"row": row.key, "expected": f"qa-{expected}"},
                )
            )
        known = set().union(*(environments_of(policy, app) for app in row.apps))
        if row.environment not in known:
            problems.append(
                Problem(
                    "environment_unknown",
                    f"The environment `{row.environment}` of the QA row `{row.key}` is not `local`, `ci` or an environment of "
                    f"{_quoted(row.apps)} in the delivery targets of SETTINGS.md ({_quoted(sorted(known))}).",
                    {"row": row.key, "environment": row.environment},
                )
            )
    new_by_key: dict[str, set[int]] = {}
    for row in new.qa:
        for ref in row.criteria:
            numbers = new_by_key.setdefault(row.key, set())
            if ref.number in numbers:
                problems.append(
                    Problem("qa_row_invalid", f"The QA verification table has two rows `{row.key}` for `AC-{ref.number}`; a row is replaced, not repeated.", {"row": row.key})
                )
            numbers.add(ref.number)
    for row in removed:
        remaining = new_by_key.get(row.key, set())
        lost = [ref.number for ref in row.criteria if ref.number not in remaining and ref.number in by_number]
        if lost:
            problems.append(
                Problem(
                    "evidence_not_archived",
                    f"The QA row `{row.key}` leaves the table without being replaced for {', '.join(f'`AC-{number}`' for number in lost)}. "
                    "A QA row is replaced by a row with the same key and criterion in the current attempt; a row that leaves for any other "
                    "reason is archived by `qa-fail` or a return route.",
                    {"row": row.key},
                )
            )
    return problems


def _is_qa_problem(item: EvidenceProblem) -> bool:
    """Whether an evidence problem belongs to a QA row. A basis or artifact problem names the row key, an app the Delivery table."""

    return item.code == "qa_row_invalid" or item.subject is not None


# --- Release rows of a qa-pass --------------------------------------------------------------------------------------


def release_attempt_for(wiki_root: Path, item_id: str, app: str) -> int:
    """The next release attempt of an (item, app): 1 plus the release records with a delivery row for it (CONTRACTS 5.4).

    A rollback or redeploy record does not count. A wiki with no `releases/` folder has no records.
    """

    records: list[dict[str, Any]] = []
    for page in read_markdown_pages(wiki_root / "releases"):
        rows, _problems = parse_evidence_table(
            page.body, "Delivery", ("item", "app", "target", "version", "attempt", "outcome", "evidence", "basis"), "release_record_invalid"
        )
        kind = "rollback" if page.frontmatter.get("rollback-of") else "redeploy" if page.frontmatter.get("redeploy-of") else "release"
        records.append({"kind": kind, "delivery": [(cells[0].strip(), cells[1].strip()) for cells in rows]})
    return release_attempt(records, item_id, app)


def check_qa_pass_release_rows(
    *,
    old: FeatureEvidence,
    new: FeatureEvidence,
    stages: Mapping[str, str],
    active: Sequence[str],
    policy: Mapping[str, Any] | None,
    attempt_of: Any,
) -> tuple[tuple[str, ...], list[Problem]]:
    """The apps a `qa-pass` names (those that gain a `pending` authoritative Release row) and the refusals for its Release rows.

    `attempt_of(app)` is the release attempt a new pending row must carry. Staging rows (attempt `—`) are informational: they
    may be added or replaced, naming an environment of the app and its delivered artifact.
    """

    problems: list[Problem] = []
    old_cells = {_cells(row) for row in old.release}
    new_cells = {_cells(row) for row in new.release}
    seen = {(item.code, item.message) for item in old.problems}
    for item in new.problems:
        if item.code in RELEASE_PROBLEM_CODES and item.subject is not None and (item.code, item.message) not in seen and any(row.app == item.subject for row in new.release):
            problems.append(Problem(item.code, item.message, {"app": item.subject}))
    for row in old.release:
        if row.authoritative and _cells(row) not in new_cells:
            problems.append(
                Problem(
                    "release_row_invalid",
                    f"`qa-pass` never changes the authoritative Release row of `{row.app}` ({row.attempt and f'release-{row.attempt}'}); a return archives it.",
                    {"app": row.app},
                )
            )
    delivered = {row.app: clean_cell(row.artifact) for row in old.delivery}
    named: list[str] = []
    for row in new.release:
        if _cells(row) in old_cells:
            continue
        if row.app not in active:
            problems.append(Problem("undeclared_app_row", f"The Release row of `{row.app}` names an app that is not active in the feature's scope.", {"app": row.app}))
            continue
        if row.version != delivered.get(row.app):
            problems.append(
                Problem(
                    "qa_artifact_mismatch",
                    f"The Release row of `{row.app}` names `{row.version}`, but its delivered artifact is `{delivered.get(row.app)}`.",
                    {"app": row.app, "delivered": delivered.get(row.app)},
                )
            )
        if row.authoritative:
            if stages.get(row.app) not in QA_STAGES:
                problems.append(
                    Problem(
                        "app_stage_mismatch",
                        f"`qa-pass` names apps at `ready-for-qa` or `in-qa`, but `{row.app}` is {stages.get(row.app, 'unknown')}.",
                        {"app": row.app, "stage": stages.get(row.app)},
                    )
                )
                continue
            if old.authoritative_release(row.app) is not None or row.app in named:
                problems.append(Problem("duplicate_app_row", f"`{row.app}` has more than one authoritative Release row.", {"app": row.app}))
                continue
            expected = attempt_of(row.app)
            if row.attempt != expected or row.outcome != "pending":
                problems.append(
                    Problem(
                        "release_attempt_mismatch",
                        f"`qa-pass` writes the `pending` Release row of `{row.app}` in attempt release-{expected}; the row has "
                        f"`{'release-' + str(row.attempt) if row.attempt else '—'}` and outcome `{row.outcome}`.",
                        {"app": row.app, "expected": f"release-{expected}"},
                    )
                )
                continue
            named.append(row.app)
        else:
            if row.target not in environments_of(policy, row.app):
                problems.append(
                    Problem(
                        "environment_unknown",
                        f"The staging Release row of `{row.app}` names the environment `{row.target}`, which its delivery target does not declare.",
                        {"app": row.app, "environment": row.target},
                    )
                )
    return tuple(named), problems


# --- The bug rules of qa-pass (CONTRACTS 6.2) -----------------------------------------------------------------------


def bug_gate_problems(
    bugs: Sequence[BugPage],
    *,
    feature_id: str,
    named: Sequence[str],
    evidence: FeatureEvidence,
    code_blocks: str = "open_bug_blocks_qa",
) -> list[Problem]:
    """The bug refusals of `qa-pass` (and, with `open_bug_blocks_release`, of `release-done`).

    An open, in-fix or fixed bug of the feature and app that is not deferred blocks (`code_blocks`). A verified bug whose
    Verification row is on another artifact than the current verification artifact is `bug_verified_on_other_artifact`. A
    closed duplicate whose canonical bug no longer satisfies the duplicate rule is `duplicate_target_invalid`.
    """

    problems: list[Problem] = []
    for app in named:
        blocking = [bug for bug in bugs if blocks(bug, feature_id, app)]
        if blocking:
            listed = ", ".join(f"`{bug.bug_id}` ({bug.status})" for bug in blocking)
            problems.append(
                Problem(
                    code_blocks,
                    f"{listed} block `{app}`. Verify or close the bug (a non-blocking bug can be deferred by the product owner), "
                    "or return the app with qa-fail citing it.",
                    {"app": app, "bugs": [bug.bug_id for bug in blocking]},
                )
            )
    for app in named:
        for bug in bugs:
            if bug.status != "verified" or bug.feature is None or bug.feature.casefold() != feature_id.casefold() or app not in bug.apps:
                continue
            wanted = verification_artifact(bug, app, evidence)
            row = next((item for item in bug.verification_rows if item.app == app and item.result == "pass"), None)
            if row is None or wanted is None or row.artifact != wanted:
                problems.append(
                    Problem(
                        "bug_verified_on_other_artifact",
                        f"`{bug.bug_id}` was verified on `{row.artifact if row else None}`, but the current verification artifact of `{app}` is `{wanted}`. "
                        f"Run bug-update {bug.bug_id} reverify on the current artifact, or reject it.",
                        {"bug": bug.bug_id, "app": app},
                    )
                )
    for duplicate, reason in duplicate_problems(bugs, feature_id=feature_id):
        problems.append(
            Problem(
                "duplicate_target_invalid",
                f"`{duplicate.bug_id}` is closed as a duplicate of `{duplicate.duplicate_of}`, which no longer qualifies: {reason}. "
                "Resolve the canonical bug, or have the product owner close it with an explicit disposition.",
                {"bug": duplicate.bug_id},
            )
        )
    return problems


def coverage_problems(app: str, criteria: Sequence[Criterion], evidence: FeatureEvidence, history: Sequence[HistoryEntry]) -> list[Problem]:
    """The QA coverage gaps of an app (CONTRACTS 4.4) as refusals: `criterion_not_covered`, `integration_not_covered`, `qa_result_failed`."""

    gaps = qa_coverage(app, criteria, evidence, history)
    # A failed or blocked row is the more useful refusal: it explains why a criterion has no passing row.
    ordered = [gap for gap in gaps if gap.code == "qa_result_failed"] + [gap for gap in gaps if gap.code != "qa_result_failed"]
    return [Problem(gap.code, f"`{app}`: {gap.message}", {"app": app, "criterion": gap.criterion}) for gap in ordered]


# --- qa-fail and the return routes (F15, F16, F17) ------------------------------------------------------------------


def qa_fail_archive(
    evidence: FeatureEvidence,
    named: Sequence[str],
    stages: Mapping[str, str],
) -> tuple[list[tuple[str, tuple[str, ...]]], list[str]]:
    """The rows `qa-fail` archives and the participants that lose a Release row (CONTRACTS 2.7).

    The named apps lose their Delivery evidence row, every QA row that names them (an app row or an integration row) and
    their Release rows. Each other app that takes part in an archived integration row and is not `released` loses its
    `pending` or `failed` authoritative Release row; its Delivery evidence and its app rows stay.
    """

    archive: list[tuple[str, tuple[str, ...]]] = []
    wanted = set(named)
    archive.extend(("Delivery evidence", row.cells) for row in evidence.delivery if row.app in wanted)
    archived_qa = [row for row in evidence.qa if wanted & set(row.apps)]
    archive.extend(("QA verification", row.cells) for row in archived_qa)
    archive.extend(("Release", row.cells) for row in evidence.release if row.app in wanted)
    participants: list[str] = []
    for row in archived_qa:
        if not row.integration:
            continue
        for app in row.apps:
            if app in wanted or app in participants or stages.get(app) == "released":
                continue
            release = evidence.authoritative_release(app)
            if release is not None and release.outcome in {"pending", "failed"}:
                participants.append(app)
                archive.append(("Release", release.cells))
    return archive, sorted(participants)


def qa_fail_support(
    *,
    named: Sequence[str],
    evidence: FeatureEvidence,
    history: Sequence[HistoryEntry],
    bugs: Sequence[BugPage],
    linked: Sequence[str],
    feature_id: str,
) -> list[Problem]:
    """`qa_failure_unsupported`: each named app needs a `fail` or `blocked` row in its current attempt, or a linked, non-deferred bug.

    A linked bug is one the history entry lists under Linked bugs; it belongs to the feature, lists the app and is
    `open`, `in-fix` or `fixed`.
    """

    problems: list[Problem] = []
    by_id = {bug.bug_id.casefold(): bug for bug in bugs}
    cited = [by_id[name.casefold()] for name in linked if name.casefold() in by_id]
    for app in named:
        failing = [
            row
            for row in evidence.qa_rows_naming(app)
            if row.result in {"fail", "blocked"} and row.attempt == expected_qa_attempt(row, history)
        ]
        supporting = [
            bug
            for bug in cited
            if bug.feature is not None
            and bug.feature.casefold() == feature_id.casefold()
            and app in bug.apps
            and bug.status in {"open", "in-fix", "fixed"}
            and not bug.deferred
        ]
        if not failing and not supporting:
            problems.append(
                Problem(
                    "qa_failure_unsupported",
                    f"`{app}` has no `fail` or `blocked` QA row in its current attempt and no linked, non-deferred bug in `open`, `in-fix` or `fixed`. "
                    "Record the failure with qa-verify first, or open a bug and list it under `- Linked bugs:`.",
                    {"app": app},
                )
            )
    return problems


def merged_app_revalidation(
    current: Mapping[str, list[str]],
    additions: Mapping[str, Sequence[str]],
    *,
    drop: Iterable[str] = (),
) -> dict[str, list[str]]:
    """The `app-revalidation` mapping after adding domains per app (canonical order) and dropping apps."""

    dropped = set(drop)
    result = {app: list(domains) for app, domains in current.items() if app not in dropped}
    for app, added in additions.items():
        result[app] = merge_revalidation(result.get(app, []), added, APP_REVALIDATION_DOMAINS)
    return result


def every_row(evidence: FeatureEvidence) -> list[tuple[str, tuple[str, ...]]]:
    """Every active evidence row of a page, section by section: what a route to `specified` or `in-design` archives."""

    return [
        *(("Delivery evidence", row.cells) for row in evidence.delivery),
        *(("QA verification", row.cells) for row in evidence.qa),
        *(("Release", row.cells) for row in evidence.release),
    ]


def released_apps(scope: Sequence[str], evidence: FeatureEvidence, model: Any) -> list[str]:
    """The active apps of the scope that are `released`."""

    stages = app_stages(active_scope(scope, model), evidence)
    return [app for app, stage in stages.items() if stage == "released"]
