"""The bug page of the wiki: its fields, evidence tables, blocking rules and lint (CONTRACTS 2.8, 5.2, 6.2).

A bug page lives in `knowledge/wiki/bugs/BUG-XXX-slug.md` and states the bug's current state. Its status and owner move
through `bug-update`; its `## Fix` and `## Verification` tables hold the evidence of the fix and of its verification, and
an archived row leaves them for `## Evidence history`. The service validates every write; this module reads, checks
shape and answers the questions the QA and release rules ask of a bug (does it block, which artifact verifies it,
is a duplicate link still valid).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from prism_cli.wiki_model import (
    CHECKED_BASES,
    QA_METHODS,
    QA_RESULTS,
    FeatureEvidence,
    HistoryEntry,
    MarkdownPage,
    EvidenceProblem,
    _APP_ID_TOKEN,
    _ENVIRONMENT_TOKEN,
    _substantive_evidence_cell,
    app_stage,
    artifact_reference_problem,
    clean_cell,
    normalize_feature_id,
    parse_evidence_history,
    parse_evidence_table,
    read_feature_evidence,
    read_markdown_pages,
    section_text,
)

BUG_DIRECTORY = "bugs"
BUG_ID_PATTERN = re.compile(r"^BUG-(\d+)$")
BUG_FILE_PATTERN = re.compile(r"^(BUG-\d+)-[a-z0-9]+(?:-[a-z0-9]+)*\.md$")
FEATURE_ID_PATTERN = re.compile(r"^F-\d+$")

BUG_STATUS_ORDER = ("open", "in-fix", "fixed", "verified", "released", "closed")
BUG_OWNER_BY_STATUS = {"open": "dev", "in-fix": "dev", "fixed": "qa", "verified": "release", "released": "none", "closed": "none"}
BUG_SEVERITIES = ("critical", "high", "medium", "low")
# The statuses of a bug that has not reached a terminal state.
ACTIVE_BUG_STATUSES = ("open", "in-fix", "fixed", "verified")
CLOSE_DISPOSITIONS = ("wont-fix", "duplicate", "promoted")
BUG_REQUIRED_FIELDS = ("id", "title", "status", "owner", "severity", "blocking", "apps", "feature", "found-in", "environment", "sources")
# Written only when set (CONTRACTS 6.2).
BUG_OPTIONAL_FIELDS = ("deferred-reason", "close-reason", "duplicate-of", "promoted-to", "regression-of")
BUG_FRONTMATTER_FIELDS = (*BUG_REQUIRED_FIELDS, *BUG_OPTIONAL_FIELDS)
# The fields only `bug-scope` changes (CONTRACTS 2.8).
BUG_SCOPE_FIELDS = ("apps", "feature", "title", "found-in", "environment", "sources")
BUG_SECTIONS = ("Summary", "Steps to reproduce", "Expected", "Actual", "Impact", "Fix", "Verification", "Release", "Evidence history")
BUG_EVIDENCE_SECTIONS = ("Fix", "Verification", "Release", "Evidence history")
FIX_COLUMNS = ("app", "artifact", "implementation", "tests", "basis")
VERIFICATION_COLUMNS = ("app", "method", "artifact", "environment", "attempt", "result", "evidence", "basis")


@dataclass(frozen=True)
class FixRow:
    """One row of a bug's `## Fix`: the artifact that fixes the bug for an app, with the implementation and tests that prove it."""

    app: str
    artifact: str
    implementation: str
    tests: str
    basis: str
    cells: tuple[str, ...]


@dataclass(frozen=True)
class VerificationRow:
    """One row of a bug's `## Verification` (CONTRACTS 5.2)."""

    app: str
    method: str
    artifact: str
    environment: str
    attempt: int | None
    result: str
    evidence: str
    basis: str
    cells: tuple[str, ...]


def parse_fix_rows(body: str) -> tuple[list[FixRow], list[EvidenceProblem]]:
    """The rows of a bug's `## Fix` and the problems with them. The table has no Contract column."""

    cell_rows, problems = parse_evidence_table(body, "Fix", FIX_COLUMNS, "bug_fix_evidence_invalid")
    rows: list[FixRow] = []
    for cells in cell_rows:
        app, artifact, implementation, tests, basis = cells
        subject = app.strip() or None
        if not _APP_ID_TOKEN.match(app.strip()):
            problems.append(EvidenceProblem("bug_fix_evidence_invalid", "Every Fix row must name an app.", subject))
            continue
        row = FixRow(app.strip(), clean_cell(artifact), implementation, tests, clean_cell(basis).lower(), cells)
        rows.append(row)
        reason = artifact_reference_problem(artifact)
        if reason is not None:
            problems.append(EvidenceProblem("artifact_reference_invalid", f"The Fix artifact of `{row.app}` {reason}.", row.app))
        for column, value in (("Implementation", implementation), ("Tests", tests)):
            if not _substantive_evidence_cell(value):
                problems.append(EvidenceProblem("bug_fix_evidence_invalid", f"The {column} cell of the Fix row of `{row.app}` is empty or still a placeholder.", row.app))
        if row.basis not in CHECKED_BASES:
            problems.append(EvidenceProblem("basis_invalid", f"The basis of the Fix row of `{row.app}` must be `checked` or `attested`.", row.app))
    return rows, problems


def parse_verification_rows(body: str) -> tuple[list[VerificationRow], list[EvidenceProblem]]:
    """The rows of a bug's `## Verification` and the problems with them."""

    cell_rows, problems = parse_evidence_table(body, "Verification", VERIFICATION_COLUMNS, "bug_verification_invalid")
    rows: list[VerificationRow] = []
    for cells in cell_rows:
        app, method, artifact, environment, attempt_cell, result, evidence, basis = cells
        subject = app.strip() or None
        if not _APP_ID_TOKEN.match(app.strip()):
            problems.append(EvidenceProblem("bug_verification_invalid", "Every Verification row must name an app.", subject))
            continue
        attempt_match = re.fullmatch(r"qa-([1-9][0-9]*)", clean_cell(attempt_cell))
        row = VerificationRow(
            app.strip(),
            clean_cell(method).lower(),
            clean_cell(artifact),
            clean_cell(environment),
            int(attempt_match.group(1)) if attempt_match else None,
            clean_cell(result).lower(),
            evidence,
            clean_cell(basis).lower(),
            cells,
        )
        rows.append(row)

        def bad(message: str, code: str = "bug_verification_invalid") -> None:
            problems.append(EvidenceProblem(code, message, row.app))

        if row.method not in QA_METHODS:
            bad(f"The method of the Verification row of `{row.app}` must be one of {', '.join(QA_METHODS)}.")
        reason = artifact_reference_problem(artifact)
        if reason is not None:
            bad(f"The Verification artifact of `{row.app}` {reason}.", "artifact_reference_invalid")
        if not _ENVIRONMENT_TOKEN.match(row.environment):
            bad(f"The environment of the Verification row of `{row.app}` must be a short name such as `staging`.")
        if row.attempt is None:
            bad(f"The attempt of the Verification row of `{row.app}` must be `qa-<n>`.")
        if row.result not in QA_RESULTS:
            bad(f"The result of the Verification row of `{row.app}` must be one of {', '.join(QA_RESULTS)}.")
        if not _substantive_evidence_cell(evidence):
            bad(f"The evidence of the Verification row of `{row.app}` is empty or still a placeholder.")
        if row.basis not in CHECKED_BASES:
            problems.append(EvidenceProblem("basis_invalid", f"The basis of the Verification row of `{row.app}` must be `checked` or `attested`.", row.app))
    return rows, problems


@dataclass(frozen=True)
class BugPage:
    """A bug page read from the wiki. Missing or malformed fields read as ``None`` or empty; lint reports them."""

    page: MarkdownPage

    def _text(self, key: str) -> str | None:
        value = self.page.frontmatter.get(key)
        return value.strip() if isinstance(value, str) and value.strip() else None

    @property
    def bug_id(self) -> str:
        value = self._text("id")
        if value is not None:
            return value
        match = re.match(r"^(BUG-\d+)(?:-|$)", self.page.path.stem)
        return match.group(1) if match else self.page.path.stem

    @property
    def title(self) -> str:
        return self._text("title") or self.page.path.stem

    @property
    def status(self) -> str | None:
        return self._text("status")

    @property
    def owner(self) -> str | None:
        return self._text("owner")

    @property
    def severity(self) -> str | None:
        return self._text("severity")

    @property
    def blocking(self) -> bool | None:
        value = self.page.frontmatter.get("blocking")
        return value if isinstance(value, bool) else None

    @property
    def apps(self) -> list[str]:
        value = self.page.frontmatter.get("apps")
        return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []

    @property
    def feature(self) -> str | None:
        """The linked feature's ID, or ``None`` for `none` and for a missing field."""

        value = self._text("feature")
        return None if value is None or value.lower() == "none" else value

    @property
    def deferred(self) -> bool:
        return self._text("deferred-reason") is not None

    @property
    def close_reason(self) -> str | None:
        return self._text("close-reason")

    @property
    def disposition(self) -> str | None:
        """`wont-fix`, `duplicate` or `promoted` for a closed bug, read from the start of `close-reason`."""

        reason = self.close_reason
        return reason.split(":", 1)[0].strip().lower() if reason else None

    @property
    def duplicate_of(self) -> str | None:
        return self._text("duplicate-of")

    @property
    def promoted_to(self) -> str | None:
        return self._text("promoted-to")

    @property
    def fix_rows(self) -> list[FixRow]:
        return parse_fix_rows(self.page.body)[0]

    @property
    def verification_rows(self) -> list[VerificationRow]:
        return parse_verification_rows(self.page.body)[0]

    @property
    def history(self) -> list[HistoryEntry]:
        return parse_evidence_history(self.page.body)


def read_bug_pages(wiki_root: Path) -> list[BugPage]:
    """Every bug page of a wiki, in file order."""

    return [BugPage(page) for page in read_markdown_pages(wiki_root / BUG_DIRECTORY)]


def bug_listing_digest(wiki_root: Path) -> str:
    """The SHA-256 of the file names in `bugs/`: a bug created or removed between a preview and its apply changes it."""

    directory = wiki_root / BUG_DIRECTORY
    names = sorted(path.name for path in directory.glob("*.md") if not path.name.startswith("_")) if directory.is_dir() else []
    return hashlib.sha256("\n".join(names).encode("utf-8")).hexdigest()


def next_bug_number(bugs: Iterable[BugPage]) -> int:
    """One more than the highest bug number on disk."""

    numbers = [int(match.group(1)) for bug in bugs if (match := BUG_ID_PATTERN.match(bug.bug_id))]
    return max(numbers, default=0) + 1


def bugs_by_id(bugs: Iterable[BugPage]) -> dict[str, BugPage]:
    return {bug.bug_id.casefold(): bug for bug in bugs}


# --- Blocking and verification (CONTRACTS 6.2) ----------------------------------------------------------------------


def blocks(bug: BugPage, feature_id: str, app: str) -> bool:
    """Whether the bug blocks `qa-pass` and `release-done` for `app` of the feature.

    Its feature is the feature, its apps include the app, its status is not `verified`, `released` or `closed`, and it is
    not deferred. A blocking bug cannot be deferred.
    """

    if bug.feature is None or normalize_feature_id(bug.feature) != normalize_feature_id(feature_id):
        return False
    return app in bug.apps and bug.status not in {"verified", "released", "closed"} and not bug.deferred


def verification_artifact(bug: BugPage, app: str, evidence: FeatureEvidence | None) -> str | None:
    """The artifact a bug's verification must be recorded on for `app` (CONTRACTS 6.2).

    For a bug linked to a feature app at `ready-for-qa` or later that is not `released` it is that app's Delivery evidence
    artifact. Otherwise it is the app's Fix artifact. ``None`` when the artifact does not exist yet.
    """

    if bug.feature is not None and evidence is not None and app_stage(app, evidence) in {"ready-for-qa", "in-qa", "ready-for-release"}:
        row = evidence.delivery_row(app)
        return clean_cell(row.artifact) if row is not None else None
    fix = next((row for row in bug.fix_rows if row.app == app), None)
    return fix.artifact if fix is not None else None


def duplicate_target_problem(duplicate: BugPage, bugs: Mapping[str, BugPage]) -> str | None:
    """Why the canonical bug a duplicate names is not valid (CONTRACTS 6.2), or ``None`` when it is.

    The canonical bug exists and is not the duplicate itself; it is not `closed` and does not reach the duplicate through
    `duplicate-of`; it has the duplicate's feature (or the duplicate's feature is `none`) and its apps include the
    duplicate's apps; and it is not deferred when the duplicate is `blocking: true`.
    """

    target_id = duplicate.duplicate_of
    if target_id is None:
        return "a duplicate names the canonical bug in `duplicate-of`"
    canonical = bugs.get(target_id.casefold())
    if canonical is None:
        return f"`{target_id}` is not a bug of this wiki"
    if canonical.bug_id.casefold() == duplicate.bug_id.casefold():
        return "a bug cannot be a duplicate of itself"
    if canonical.status == "closed":
        return f"`{canonical.bug_id}` is closed"
    seen = {duplicate.bug_id.casefold()}
    current: BugPage | None = canonical
    while current is not None:
        if current.bug_id.casefold() in seen:
            return f"`{canonical.bug_id}` reaches `{duplicate.bug_id}` through `duplicate-of`, which makes a cycle"
        seen.add(current.bug_id.casefold())
        current = bugs.get(current.duplicate_of.casefold()) if current.duplicate_of else None
    if duplicate.feature is not None and (canonical.feature is None or normalize_feature_id(canonical.feature) != normalize_feature_id(duplicate.feature)):
        return f"`{canonical.bug_id}` belongs to {canonical.feature or 'no feature'}, not to {duplicate.feature}"
    missing = [app for app in duplicate.apps if app not in canonical.apps]
    if missing:
        return f"`{canonical.bug_id}` does not list the app(s) {', '.join(f'`{app}`' for app in missing)}"
    if duplicate.blocking is True and canonical.deferred:
        return f"`{canonical.bug_id}` is deferred, and `{duplicate.bug_id}` is blocking"
    return None


def closed_duplicates(bugs: Iterable[BugPage]) -> list[BugPage]:
    return [bug for bug in bugs if bug.status == "closed" and bug.disposition == "duplicate"]


def duplicate_problems(bugs: Iterable[BugPage], *, feature_id: str | None = None) -> list[tuple[BugPage, str]]:
    """The closed duplicates whose canonical bug no longer satisfies the duplicate rule, with the reason.

    With a `feature_id` only duplicates that belong to the feature, or whose canonical bug does, are checked.
    """

    listing = list(bugs)
    index = bugs_by_id(listing)
    found: list[tuple[BugPage, str]] = []
    for duplicate in closed_duplicates(listing):
        if feature_id is not None:
            canonical = index.get((duplicate.duplicate_of or "").casefold())
            wanted = normalize_feature_id(feature_id)
            if not any(item is not None and item.feature is not None and normalize_feature_id(item.feature) == wanted for item in (duplicate, canonical)):
                continue
        problem = duplicate_target_problem(duplicate, index)
        if problem is not None:
            found.append((duplicate, problem))
    return found


def feature_cites_bug(feature_frontmatter: Mapping[str, Any], feature_body: str, bug_path: str, bug_id: str) -> bool:
    """Whether a feature lists the bug page in `sources` or names the bug under Linked bugs in its latest Evidence history entry."""

    sources = feature_frontmatter.get("sources")
    if isinstance(sources, list) and any(isinstance(item, str) and item.strip() and (item.strip() == bug_path or item.strip().endswith("/" + bug_path.rsplit("/", 1)[-1])) for item in sources):
        return True
    history = parse_evidence_history(feature_body)
    return bool(history) and any(name.casefold() == bug_id.casefold() for name in history[-1].names("Linked bugs"))


# --- Lint ----------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class BugFinding:
    code: str
    severity: str
    path: Path
    message: str
    feature_id: str | None = None


def lint_bug_page(
    bug: BugPage,
    *,
    app_ids: set[str],
    feature_apps: Mapping[str, list[str]],
    bugs: Mapping[str, BugPage],
    features: Mapping[str, tuple[Mapping[str, Any], str, str | None]],
) -> list[BugFinding]:
    """The findings for one bug page.

    `feature_apps` maps a normalized feature ID to its `apps`; `features` maps it to (front matter, body, status) for the
    promotion check.
    """

    path = bug.page.path
    frontmatter = bug.page.frontmatter
    findings: list[BugFinding] = []

    def add(code: str, message: str, severity: str = "error", feature_id: str | None = None) -> None:
        findings.append(BugFinding(code, severity, path, message, feature_id))

    for key in frontmatter:
        if key not in BUG_FRONTMATTER_FIELDS:
            add("bug-page-invalid", f"`{key}` is not a bug field; a bug page carries only {', '.join(f'`{name}`' for name in BUG_FRONTMATTER_FIELDS)}.")
    for key in BUG_REQUIRED_FIELDS:
        if key not in frontmatter:
            add("bug-page-invalid", f"Required frontmatter field `{key}` is missing.")
    bug_id = frontmatter.get("id")
    if "id" in frontmatter:
        if not isinstance(bug_id, str) or not BUG_ID_PATTERN.match(bug_id.strip()):
            add("bug-page-invalid", "`id` must be a bug ID such as `BUG-001`.")
        else:
            file_match = BUG_FILE_PATTERN.match(path.name)
            if file_match is None or file_match.group(1).casefold() != bug_id.strip().casefold():
                add("bug-page-invalid", f"The file name must be `{bug_id.strip()}-<slug>.md` (lowercase words joined by hyphens).")
    if "title" in frontmatter and bug._text("title") is None:
        add("bug-page-invalid", "`title` must be a non-empty string.")
    status = bug.status
    if "status" in frontmatter and status not in BUG_STATUS_ORDER:
        add("bug-page-invalid", f"`status` must be one of {list(BUG_STATUS_ORDER)}.")
    elif status in BUG_OWNER_BY_STATUS and "owner" in frontmatter and bug.owner != BUG_OWNER_BY_STATUS[status]:
        add("invalid-bug-status-owner", f"`status: {status}` must pair with `owner: {BUG_OWNER_BY_STATUS[status]}`.")
    if "severity" in frontmatter and bug.severity not in BUG_SEVERITIES:
        add("bug-page-invalid", f"`severity` must be one of {list(BUG_SEVERITIES)}.")
    if "blocking" in frontmatter and bug.blocking is None:
        add("bug-page-invalid", "`blocking` must be `true` or `false`.")
    apps_value = frontmatter.get("apps")
    if "apps" in frontmatter:
        if not isinstance(apps_value, list) or not apps_value or any(not isinstance(item, str) for item in apps_value) or len(set(apps_value)) != len(apps_value):
            add("bug-page-invalid", "`apps` must be a non-empty list of distinct app IDs.")
        else:
            for app in apps_value:
                if app not in app_ids:
                    add("unknown-app-id", f"`{app}` is not an app of this workspace.")
    feature_value = frontmatter.get("feature")
    if "feature" in frontmatter:
        if not isinstance(feature_value, str) or not (FEATURE_ID_PATTERN.match(feature_value.strip()) or feature_value.strip() == "none"):
            add("bug-page-invalid", "`feature` must be a feature ID such as `F-001`, or `none`.")
        elif bug.feature is not None:
            apps = feature_apps.get(normalize_feature_id(bug.feature))
            if apps is None:
                add("bug-feature-missing", f"`feature: {bug.feature}` names no feature page.")
            else:
                outside = [app for app in bug.apps if app not in apps]
                if outside:
                    add("bug-page-invalid", f"The bug lists app(s) {', '.join(f'`{app}`' for app in outside)} that {bug.feature} does not list.")
    for key in ("found-in", "environment"):
        if key in frontmatter and bug._text(key) is None:
            add("bug-page-invalid", f"`{key}` must be a non-empty string.")
    if "environment" in frontmatter and bug._text("environment") is not None and not _ENVIRONMENT_TOKEN.match(bug._text("environment") or ""):
        add("bug-page-invalid", "`environment` must be a short name such as `staging`.")
    sources = frontmatter.get("sources")
    if "sources" in frontmatter and (not isinstance(sources, list) or any(not isinstance(item, str) for item in sources)):
        add("bug-page-invalid", "`sources` must be a list of strings.")
    for key in ("duplicate-of", "regression-of"):
        if key in frontmatter and (bug._text(key) is None or not BUG_ID_PATTERN.match(bug._text(key) or "")):
            add("bug-page-invalid", f"`{key}` must be a bug ID such as `BUG-001`.")
    if "promoted-to" in frontmatter and (bug._text("promoted-to") is None or not FEATURE_ID_PATTERN.match(bug._text("promoted-to") or "")):
        add("bug-page-invalid", "`promoted-to` must be a feature ID such as `F-001`.")
    if "deferred-reason" in frontmatter:
        if bug._text("deferred-reason") is None:
            add("bug-page-invalid", "`deferred-reason` must be a non-empty string when set.")
        if bug.blocking is True:
            add("bug-page-invalid", "A blocking bug cannot be deferred.")

    if status == "closed":
        disposition = bug.disposition
        reason = bug.close_reason
        if reason is None or disposition not in CLOSE_DISPOSITIONS:
            add("bug-close-reason-required", f"A closed bug records `close-reason`: `wont-fix: <reason>`, `duplicate` or `promoted`; `{reason or ''}` is not one of them.")
        elif disposition == "wont-fix" and not (reason.split(":", 1)[1].strip() if ":" in reason else ""):
            add("bug-close-reason-required", "A `wont-fix` closure needs a reason: `close-reason: wont-fix: <reason>`.")
        elif disposition == "duplicate" and bug.duplicate_of is None:
            add("bug-close-reason-required", "A `duplicate` closure names the canonical bug in `duplicate-of`.")
        elif disposition == "promoted" and bug.promoted_to is None:
            add("bug-close-reason-required", "A `promoted` closure names the feature in `promoted-to`.")
        if disposition == "duplicate":
            problem = duplicate_target_problem(bug, bugs)
            if problem is not None:
                add("duplicate-target-invalid", f"The canonical bug of this duplicate is not valid: {problem}.")
        if disposition == "promoted" and bug.promoted_to is not None:
            target = features.get(normalize_feature_id(bug.promoted_to))
            relative = f"knowledge/wiki/bugs/{path.name}"
            if target is None:
                add("promoted-bug-unreopened", f"`promoted-to: {bug.promoted_to}` names no feature page.")
            elif target[2] == "released":
                add("promoted-bug-unreopened", f"{bug.promoted_to} is released, so it cannot carry the promoted bug.")
            elif not feature_cites_bug(target[0], target[1], relative, bug.bug_id):
                add("promoted-bug-unreopened", f"{bug.promoted_to} does not list this bug in `sources` or under Linked bugs in its latest Evidence history entry.")
    else:
        for key in ("close-reason", "duplicate-of", "promoted-to"):
            if key in frontmatter:
                add("bug-page-invalid", f"`{key}` belongs to a closed bug; this one is `{status}`.")

    body = bug.page.body
    for heading in BUG_SECTIONS:
        if not re.search(rf"(?im)^##\s+{re.escape(heading)}\s*#*\s*$", body):
            add("bug-page-invalid", f"The page needs a `## {heading}` section.")
    if not section_text(body, "Summary").strip():
        add("bug-page-invalid", "The `## Summary` section is empty.")
    fix_rows, fix_problems = parse_fix_rows(body)
    verification_rows, verification_problems = parse_verification_rows(body)
    for problem in (*fix_problems, *verification_problems):
        add("bug-page-invalid", problem.message)
    declared = set(bug.apps)
    for row in fix_rows:
        if row.app not in declared:
            add("bug-page-invalid", f"A Fix row names `{row.app}`, which the bug does not list in `apps`.")
    for row in verification_rows:
        if row.app not in declared:
            add("bug-page-invalid", f"A Verification row names `{row.app}`, which the bug does not list in `apps`.")
    if status in {"open", "in-fix"} and (fix_rows or verification_rows):
        add("bug-page-invalid", f"A `{status}` bug has no active Fix or Verification rows; they are archived in Evidence history.")
    if status in {"fixed", "verified"}:
        missing = [app for app in bug.apps if all(row.app != app for row in fix_rows)]
        if missing:
            add("bug-page-invalid", f"A `{status}` bug needs a Fix row for {', '.join(f'`{app}`' for app in missing)}.")
    if status == "verified":
        missing = [app for app in bug.apps if not any(row.app == app and row.result == "pass" for row in verification_rows)]
        if missing:
            add("bug-page-invalid", f"A `verified` bug needs a passing Verification row for {', '.join(f'`{app}`' for app in missing)}.")
    return findings


def lint_bugs(
    bugs: list[BugPage],
    *,
    app_ids: set[str],
    features: Mapping[str, tuple[Mapping[str, Any], str, str | None, list[str]]],
) -> list[BugFinding]:
    """Findings for every bug page: the page checks, duplicate IDs, and the duplicate constraints."""

    index = bugs_by_id(bugs)
    feature_apps = {key: value[3] for key, value in features.items()}
    feature_facts = {key: (value[0], value[1], value[2]) for key, value in features.items()}
    findings: list[BugFinding] = []
    seen: dict[str, BugPage] = {}
    for bug in bugs:
        findings.extend(lint_bug_page(bug, app_ids=app_ids, feature_apps=feature_apps, bugs=index, features=feature_facts))
        key = bug.bug_id.casefold()
        if key in seen:
            findings.append(BugFinding("bug-page-invalid", "error", bug.page.path, f"Duplicate bug id `{bug.bug_id}`."))
        seen[key] = bug
    return findings
