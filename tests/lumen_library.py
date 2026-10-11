"""The "Lumen Library" case of CONTRACTS 10.1: a neutral two-app workspace, its people and the pages of feature F-001.

`catalog-api` (`spring-backend`, repository `workspace`) and `reader-app` (`android-compose`, external repository `reader-repo`
with no checkout) deliver "Reserve a book". The workspace holds seven grants: Pat (`po`), Dana (`designer`), Theo
(`tech-lead`), Devi (`dev`, `qa`), Quinn (`qa`), Remy (`release`) and an Agent grant that holds no role. The Agent proposes each
step and the named human approves it in a board session; a few steps are ungated writes that the Agent applies itself.

The module has no tests. `tests/test_lumen_case.py` walks the nineteen steps of the contract through the board service, and its
direct-file test writes the same pages with no board and checks them with lint alone.
"""

from __future__ import annotations

import re
import tempfile
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from prism_cli.wiki_model import (
    DesignTracks,
    contract_citation,
    criterion_revision,
)
from prism_cli.workflow_install import apply_install, plan_install

# -- identity ------------------------------------------------------------------------------------------------------------

DAY = date(2026, 10, 9)
TODAY = DAY.isoformat()

WORKSPACE_NAME = "Lumen Library"
CATALOG = "catalog-api"
READER = "reader-app"
APPS = [CATALOG, READER]
READER_REMOTE = "https://git.example/lumen/reader-repo.git"

FEATURE_ID = "F-001"
FEATURE_PATH = "knowledge/wiki/features/F-001-reserve-a-book.md"
DESIGN_PATH = "knowledge/wiki/design/F-001-reserve-a-book.md"
TECH_PATH = "knowledge/wiki/technical-design/F-001-reserve-a-book.md"
CONTRACT_PATH = "knowledge/wiki/api-contracts/F-001.md"
REQUIREMENT_PATHS = {CATALOG: f"knowledge/wiki/app-requirements/F-001-{CATALOG}.md", READER: f"knowledge/wiki/app-requirements/F-001-{READER}.md"}
SETTINGS_PATH = "knowledge/wiki/SETTINGS.md"
BOARD_PATH = "knowledge/wiki/status-board.md"
INDEX_PATH = "knowledge/wiki/index.md"
LOG_PATH = "knowledge/wiki/log.md"
BUG_DIR = "knowledge/wiki/bugs"
RELEASE_DIR = "knowledge/wiki/releases"
INCIDENT_DIR = "knowledge/wiki/incidents"

# The people: name, the roles of the grant. The Agent holds none.
PEOPLE: Mapping[str, str] = {"Pat": "po", "Dana": "designer", "Theo": "tech-lead", "Devi": "dev,qa", "Quinn": "qa", "Remy": "release"}

SETTINGS_TEXT = (
    "---\n"
    "wiki-stale-after-days: 365\n"
    "qa-separate-from-dev: true\n"
    "delivery-targets:\n"
    f"  {CATALOG}: {{ kind: deployment, target: production, environments: [staging] }}\n"
    f"  {READER}: {{ kind: store, target: play-store, environments: [internal-test] }}\n"
    "---\n"
    "\n# Wiki Settings\n\nThe Lumen Library keeps the separation of developers and testers on and declares where each app is delivered.\n"
)

# -- the feature ---------------------------------------------------------------------------------------------------------

TITLE = "Reserve a book"
BRIEF = "2026-10-01-reserve-a-book-brief"
SOURCE = f"knowledge/intake/processed/{BRIEF}"
SUMMARY = "A reader reserves an available copy of a book in the reader app, and the catalog records the reservation."
STORY = "As a reader, I want to reserve an available copy of a book, so that it waits for me at the library."
SURFACE = "A new endpoint `POST /api/v1/reservations` reserves an available copy for the signed-in reader and returns the reservation."

TEXT_1 = "A reservation request for an available copy returns the reservation."
TEXT_2 = "A reader can reserve an available copy from the book page."
TEXT_3 = "A reservation made in the reader appears in the catalog within one minute."
TEXT_1_EDITED = "A reservation request for an available copy returns the reservation with its pickup date."
CRITERIA = [
    f"AC-1 [{CATALOG}] {TEXT_1}",
    f"AC-2 [{READER}] {TEXT_2}",
    f"AC-3 [integration: {CATALOG}, {READER}] {TEXT_3}",
]


def ref(number: int, text: str, apps: Sequence[str], *, integration: bool = False) -> str:
    """The citation `AC-n@v1:<hash>` of a criterion of F-001 (CONTRACTS 4.1)."""

    return f"AC-{number}@{criterion_revision(FEATURE_ID, number, apps, integration, '', text)}"


def ref_1(text: str = TEXT_1) -> str:
    return ref(1, text, [CATALOG])


def ref_2() -> str:
    return ref(2, TEXT_2, [READER])


def ref_3() -> str:
    return ref(3, TEXT_3, APPS, integration=True)


def criteria_lines(first: str = TEXT_1) -> list[str]:
    return [f"AC-1 [{CATALOG}] {first}", *CRITERIA[1:]]


DESIGNER_QUESTION = "| 2 | What does the book page show after a reservation? | designer | open |"
DESIGNER_ANSWER = "The book page shows the pickup date, and a copy is held for three days."
QUESTIONS = [
    "| 1 | How many copies can a reader reserve at once? | po | resolved: One copy at a time. |",
    DESIGNER_QUESTION,
]

# -- artifacts -----------------------------------------------------------------------------------------------------------

CATALOG_BUILD = "build:catalog-api#412"
READER_BUILD = "build:reader-app#90"
READER_FIX_BUILD = "build:reader-app#91"
CATALOG_FIX_BUILD = "build:catalog-api#413"

HEADERS = {
    "delivery": "| App | Artifact | Contract | Implementation | Tests | Basis |",
    "qa": "| Row | Criteria | Method | Artifact | Environment | Attempt | Result | Evidence | Basis |",
    "release": "| App | Target | Version | Attempt | Outcome | Record | Basis |",
    "fix": "| App | Artifact | Implementation | Tests | Basis |",
    "verification": "| App | Method | Artifact | Environment | Attempt | Result | Evidence | Basis |",
    "record": "| Item | App | Target | Version | Attempt | Outcome | Evidence | Basis |",
}


def table(kind: str, rows: Sequence[str]) -> str:
    header = HEADERS[kind]
    columns = header.split("|")[1:-1]
    return "\n".join([header, "|" + "|".join("---" for _ in columns) + "|", *rows])


def delivery_row(app: str, artifact: str, contract: str = "none", *, pull: int = 31) -> str:
    return (
        f"| {app} | `{artifact}` | {contract} | [PR {pull}](https://git.example/lumen/pull/{pull}) "
        f"| `./run-tests`: 214 passed ([run](https://ci.example/{artifact.rsplit('#', 1)[1]})) | checked |"
    )


# The environment a QA row names: the app's own environment from SETTINGS.md, or `ci` for an integration row.
ENVIRONMENTS = {CATALOG: "staging", READER: "internal-test"}


def qa_row(key: str, refs: Sequence[str], artifacts: str, *, attempt: int, result: str = "pass", environment: str | None = None, method: str = "manual", basis: str = "attested") -> str:
    environment = environment or ENVIRONMENTS.get(key, "ci")
    return f"| {key} | {', '.join(refs)} | {method} | {artifacts} | {environment} | qa-{attempt} | {result} | [notes](https://qa.example/s/{attempt}{key[:2]}) | {basis} |"


def pending_release_row(app: str, artifact: str, attempt: int = 1) -> str:
    return f"| {app} | — | `{artifact}` | release-{attempt} | pending | — | — |"


def release_row(app: str, artifact: str, number: int, *, target: str, outcome: str = "released", attempt: int = 1, basis: str = "checked") -> str:
    return f"| {app} | {target} | `{artifact}` | release-{attempt} | {outcome} | [REL-{number:03d}](../releases/REL-{number:03d}.md) | {basis} |"


def fix_row(app: str, artifact: str, *, pull: int = 40) -> str:
    return f"| {app} | `{artifact}` | [PR {pull}](https://git.example/lumen/pull/{pull}) | `./run-tests`: 220 passed ([run](https://ci.example/{artifact.rsplit('#', 1)[1]})) | checked |"


def verification_row(app: str, artifact: str, *, attempt: int = 1, environment: str | None = None) -> str:
    environment = environment or ENVIRONMENTS[app]
    return f"| {app} | manual | `{artifact}` | {environment} | qa-{attempt} | pass | [notes](https://qa.example/bug/{attempt}) | attested |"


def record_row(item: str, app: str, artifact: str, *, target: str, outcome: str = "released", attempt: int | None = 1, evidence: str | None = None) -> str:
    cell = f"release-{attempt}" if attempt is not None else "—"
    proof = evidence or ("store: https://play.example/lumen/reader" if outcome == "released" and app == READER else "deployment: https://ci.example/deploy/" + artifact.rsplit("#", 1)[1])
    return f"| {item} | {app} | {target} | `{artifact}` | {cell} | {outcome} | {proof} | checked |"


# -- front matter and sections -------------------------------------------------------------------------------------------

_FRONTMATTER = re.compile(r"\A(﻿?)---\r?\n(.*?)\r?\n---\r?\n?(.*)\Z", re.DOTALL)


def split_page(text: str) -> tuple[dict[str, Any], str]:
    match = _FRONTMATTER.match(text)
    if match is None:
        raise ValueError("A wiki page starts with front matter.")
    return (yaml.safe_load(match.group(2)) or {}), match.group(3)


def join_page(frontmatter: Mapping[str, Any], body: str) -> str:
    return f"---\n{yaml.safe_dump(dict(frontmatter), sort_keys=False, allow_unicode=True).rstrip()}\n---\n{body}"


def set_frontmatter(text: str, updates: Mapping[str, Any] | None = None, remove: Sequence[str] = ()) -> str:
    """The page with front matter keys set or removed; every other key and the body stay as they are."""

    frontmatter, body = split_page(text)
    frontmatter.update(updates or {})
    for key in remove:
        frontmatter.pop(key, None)
    return join_page(frontmatter, body)


def set_section(text: str, heading: str, replacement: str) -> str:
    """The page with the body of `## heading` replaced."""

    pattern = re.compile(rf"(?ms)(^## {re.escape(heading)}[ \t]*\r?\n).*?(?=^## |\Z)")
    match = pattern.search(text)
    if match is None:
        raise ValueError(f"Required section {heading!r} is missing")
    return text[: match.start()] + match.group(1) + replacement.rstrip() + "\n\n" + text[match.end() :]


def section(text: str, heading: str) -> str:
    match = re.search(rf"(?ms)^## {re.escape(heading)}[ \t]*\r?\n(.*?)(?=^## |\Z)", text)
    if match is None:
        raise ValueError(f"Required section {heading!r} is missing")
    return match.group(1)


def table_rows(text: str, heading: str) -> list[str]:
    """The data rows (lines after the header and separator) of the table in `## heading`."""

    lines = [line for line in section(text, heading).splitlines() if line.strip().startswith("|")]
    return lines[2:]


def with_rows(text: str, heading: str, kind: str, rows: Sequence[str]) -> str:
    return set_section(text, heading, table(kind, rows))


def history_entry(
    action: str,
    *,
    reason: str,
    affected: str,
    archived: Sequence[tuple[str, str]],
    participants: str = "none",
    tracks: str = "none",
    reaffirmed: str = "none",
    invalidations: str = "No requirement or API page is invalidated.",
    linked: str = "none",
    day: str = TODAY,
) -> str:
    """An Evidence history entry (CONTRACTS 2.7); `archived` lists (section, active row) pairs."""

    rows = "\n".join(f"  | {name} | {row.strip().strip('|').strip()} |" for name, row in archived)
    return (
        f"### {day} - {action}\n"
        f"- Reason: {reason}\n"
        f"- Affected apps: {affected}\n"
        f"- Participants: {participants}\n"
        f"- Affected tracks: {tracks}\n"
        f"- Archived evidence:\n{rows}\n"
        f"- Reaffirmed evidence: {reaffirmed}\n"
        f"- Requirement/API invalidations: {invalidations}\n"
        f"- Linked bugs: {linked}\n"
    )


def append_history(text: str, entry: str) -> str:
    """The page with one more Evidence history entry after the existing ones, which stay as they are."""

    body = section(text, "Evidence history")
    base = body if body.endswith("\n\n") else body.rstrip("\n") + ("\n\n" if body.strip() else "")
    return set_section(text, "Evidence history", base + entry.rstrip())


# -- the feature page ----------------------------------------------------------------------------------------------------


def raw_feature_page() -> str:
    """F-001 as intake leaves it: `raw`, owned by the PO, with criteria that carry IDs and an empty evidence section."""

    frontmatter = {
        "id": FEATURE_ID,
        "title": TITLE,
        "status": "raw",
        "owner": "po",
        "apps": list(APPS),
        "sources": [f"{SOURCE}/brief.md"],
        "advisory-review": "not-needed",
        "criteria-high-water": 3,
        "revalidation": [],
    }
    body = (
        f"\n## Summary\n{SUMMARY}\n\n"
        f"## User story\n{STORY}\n\n"
        "## Acceptance criteria\n" + "\n".join(f"- [ ] {line}" for line in CRITERIA) + "\n\n"
        "## Open questions\n| # | Question | Owner | Status |\n|---|----------|-------|--------|\n" + "\n".join(QUESTIONS) + "\n\n"
        f"## App scope\n- **{CATALOG}**: Reserve a copy and record the reservation.\n- **{READER}**: Offer the reservation on the book page.\n\n"
        "## Design\nNo design has been recorded yet.\n\n"
        "## Related features\nNo related feature is required for this workflow.\n\n"
        f"## API surface\n{SURFACE}\n\n"
        "## Board review summary\nThe acceptance checks cover the scoped reservation workflow.\n\n"
        f"## Delivery evidence\n{table('delivery', [])}\n\n"
        f"## QA verification\n{table('qa', [])}\n\n"
        f"## Release\n{table('release', [])}\n\n"
        "## Evidence history\n"
    )
    return join_page(frontmatter, body)


def requirement_page(app: str, status: str = "pending") -> str:
    ui = app == READER
    return (
        f"---\nfeature-id: {FEATURE_ID}\napp: {app}\nstatus: {status}\n---\n\n"
        f"## What to build\n{'Offer the reservation on the book page and show its pickup date.' if ui else 'Reserve an available copy and return the reservation.'}\n\n"
        f"## Technical constraints\n{'Use the shared reader network client.' if ui else 'Use the existing catalog storage and the authenticated write path.'}\n\n"
        f"## Design reference\n{'[Reservation design](../design/F-001-reserve-a-book.md) shows the book page.' if ui else 'Not applicable for this app: it has no UI.'}\n\n"
        "## API contract reference\n[API contract](../api-contracts/F-001.md)\n\n"
        f"## Acceptance criteria\n- {TEXT_2 if ui else TEXT_1}\n\n"
        f"## Dependencies\n{'The catalog-api reservation endpoint is available.' if ui else 'No unfinished dependency.'}\n"
    )


def design_page() -> str:
    return (
        f"---\nfeature-id: {FEATURE_ID}\ntitle: {TITLE}\napps: [{READER}]\nfigma: reserve-a-book-flow\n---\n\n"
        "## Summary\nThe book page offers a reserve button for an available copy and shows the pickup date after it.\n\n"
        "## Key design decisions\nThe reserve button sits beside the availability line so a reader sees the copy status first.\n\n"
        "## States covered\nThe page shows available, reserved and unavailable copies, and the failure of a reservation.\n\n"
        "## Component references\nUse the existing button and status chip of the reader app.\n\n"
        "## Open design questions\nNo design question is open.\n"
    )


def technical_page(*, hold: str = "two", note: str = "The reservation endpoint is added to the existing catalog module.") -> str:
    return (
        f"---\nfeature-id: {FEATURE_ID}\ntitle: {TITLE} technical design\napps: [{CATALOG}, {READER}]\ndecisions: []\n---\n\n"
        "## Summary\nThe catalog stores a reservation for an available copy and the reader app calls the new endpoint.\n\n"
        "## Architecture impact\n| App | Modules | Change |\n|---|---|---|\n"
        f"| {CATALOG} | catalog | {note} |\n"
        f"| {READER} | book page | A reserve action that calls the reservation endpoint. |\n\n"
        "## Data model and migrations\nA reservations table links a reader to a copy; the migration is additive.\n\n"
        "## Security and privacy\nOnly the signed-in reader can reserve a copy for themself.\n\n"
        "## Non-functional requirements\nA reservation is visible in the catalog within one minute.\n\n"
        "## Risks\nTwo readers may reserve the last copy at once; the catalog accepts the first request only.\n\n"
        f"## Decisions\nA reservation holds a copy for {hold} days.{' ' + DESIGNER_ANSWER if hold == 'three' else ''}\n\n"
        "## API contract\nThe reservation endpoint is described in the API contract of this feature.\n\n"
        "## Test strategy\n| Criterion | Applies to | Method | Level | Notes |\n|---|---|---|---|---|\n"
        f"| AC-1 | {CATALOG} | automated | integration | The reservation is created for the signed-in reader |\n"
        f"| AC-2 | {READER} | manual | end-to-end | |\n"
        f"| AC-3 | {CATALOG}, {READER} | manual | end-to-end | Reserve in the app and read the catalog |\n"
    )


def contract_page(status: str = "agreed", version: int = 1) -> str:
    return (
        f"---\nfeature-id: {FEATURE_ID}\nversion: {version}\nstatus: {status}\n---\n\n"
        "## Endpoints\n- `POST /api/v1/reservations` reserves an available copy. Request body: `copyId`. Response body: `Reservation` (201). Errors: 401, 404, 409.\n\n"
        "## Data models\n### Reservation\n- `id`: string\n- `copyId`: string\n- `pickupBy`: date\n\n"
        "## Authentication requirements\nBearer token of the signed-in reader.\n\n"
        "## Notes\nA reservation is created for the signed-in reader.\n"
    )


def contract_body(text: str | None = None) -> str:
    """The body of the contract page, without its front matter."""

    return split_page(text or contract_page())[1]


def contract_cell(version: int = 1) -> str:
    return contract_citation(FEATURE_ID, version, contract_body())


# -- bugs, releases, incidents -------------------------------------------------------------------------------------------


def slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def bug_path(number: int, title: str) -> str:
    return f"{BUG_DIR}/BUG-{number:03d}-{slug(title)}.md"


_BUG_OWNERS = {"open": "dev", "in-fix": "dev", "fixed": "qa", "verified": "release", "released": "none", "closed": "none"}


def bug_page(
    number: int,
    title: str,
    found_in: str,
    *,
    status: str = "open",
    apps: Sequence[str] = (READER,),
    feature: str = FEATURE_ID,
    severity: str = "high",
    blocking: bool = True,
    environment: str = "internal-test",
    fix: str = "",
    verification: str = "",
    release: str = "",
    history: str = "",
    extra: Mapping[str, Any] | None = None,
) -> str:
    """A bug page (CONTRACTS 6.2); a new bug is `open`, owned by `dev`, with empty Fix, Verification, Release and Evidence history."""

    frontmatter: dict[str, Any] = {
        "id": f"BUG-{number:03d}",
        "title": title,
        "status": status,
        "owner": _BUG_OWNERS[status],
        "severity": severity,
        "blocking": blocking,
        "apps": list(apps),
        "feature": feature,
        "found-in": found_in,
        "environment": environment,
        "sources": [],
        **(extra or {}),
    }
    return (
        f"---\n{yaml.safe_dump(frontmatter, sort_keys=False).rstrip()}\n---\n\n"
        f"## Summary\n{title}.\n\n"
        "## Steps to reproduce\n1. Open the book page of an available copy.\n2. Press the reserve button.\n\n"
        "## Expected\nThe reservation is created and the pickup date is shown.\n\n"
        "## Actual\nNothing happens and no reservation is created.\n\n"
        "## Impact\nReaders cannot reserve a book.\n\n"
        f"## Fix\n{fix}\n\n"
        f"## Verification\n{verification}\n\n"
        f"## Release\n{release}\n\n"
        f"## Evidence history\n{history}\n"
    )


INCIDENT_TITLE = "Reservations fail after the catalog fix"
INCIDENT_PATH = f"{INCIDENT_DIR}/INC-001-reservations-fail-after-the-catalog-fix.md"
UNKNOWN_CAUSE = "**Unknown:** The reservation endpoint failed after REL-003; the failing path is not known yet."


def incident_page(
    *,
    status: str = "open",
    cause: str = UNKNOWN_CAUSE,
    mitigation: str = "",
    resolution: str = "",
    follow_ups: str = "",
    follow_up_ids: Sequence[str] = (),
    releases: Sequence[str] = ("REL-003",),
    timeline: Sequence[str] = (
        f"- {TODAY} 08:15: Reservations started failing after REL-003.",
    ),
) -> str:
    """INC-001 (CONTRACTS 6.2): a dated record whose Cause is filled later and whose status steps open, mitigated, resolved."""

    frontmatter = {
        "id": "INC-001",
        "title": INCIDENT_TITLE,
        "date": TODAY,
        "status": status,
        "severity": "high",
        "apps": [CATALOG],
        "releases": list(releases),
        "follow-ups": list(follow_up_ids),
    }
    return (
        f"---\n{yaml.safe_dump(frontmatter, sort_keys=False).rstrip()}\n---\n\n"
        "## Impact\nReaders could not reserve books for 25 minutes.\n\n"
        "## Timeline\n" + "\n".join(timeline) + "\n\n"
        f"## Cause\n{cause}\n\n"
        f"## Mitigation\n{mitigation}\n\n"
        f"## Resolution\n{resolution}\n\n"
        f"## Follow-ups\n{follow_ups}\n"
    )


# -- workspace -----------------------------------------------------------------------------------------------------------


def create_lumen_workspace(parent: Path) -> Path:
    """The Lumen Library workspace under `parent`: installed workflow files, two apps, the policy, and the pending brief."""

    root = parent / "lumen-library"
    root.mkdir(parents=True)
    receipt = apply_install(root, plan_install(root, name=WORKSPACE_NAME, apps=["backend"]))
    if receipt["status"] != "applied":
        raise AssertionError(f"The workflow install did not apply: {receipt}")
    manifest_path = root / "prism.workspace.yml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["repositories"] = [{"id": "workspace"}, {"id": "reader-repo", "remote": READER_REMOTE}]
    manifest["apps"] = [
        {"id": CATALOG, "name": "Catalog API", "stack": "spring-backend", "repository": "workspace", "path": "backend"},
        {"id": READER, "name": "Reader app", "stack": "android-compose", "repository": "reader-repo", "path": "app"},
    ]
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    (root / "backend").mkdir(exist_ok=True)
    (root / "backend" / ".gitkeep").write_text("", encoding="utf-8")
    (root / SETTINGS_PATH).write_text(SETTINGS_TEXT, encoding="utf-8", newline="\n")
    brief = root / "knowledge" / "intake" / "pending" / BRIEF
    brief.mkdir(parents=True)
    (brief / "brief.md").write_text(
        "# Reserve a book\n\nReaders want to reserve an available copy of a book from the reader app and see the reservation in the catalog.\n",
        encoding="utf-8",
    )
    return root


def temporary_parent() -> tempfile.TemporaryDirectory:
    return tempfile.TemporaryDirectory(prefix="prism-lumen-")


def tracks(ui: str = "pending", technical: str = "pending", **reasons: str) -> DesignTracks:
    return DesignTracks(ui, technical, reasons.get("ui_reason"), reasons.get("technical_reason"))
