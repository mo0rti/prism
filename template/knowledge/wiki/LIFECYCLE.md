---
schema-version: 1
---

# Wiki lifecycle protocol - features, board and advisory files

This file extends `SCHEMA.md`, which is read first. It holds the feature page format,
the status and owner lifecycle, the design tracks, the evidence rules and the advisory file
formats, and is read for every feature, board or advisory operation. The lifecycle actions
(the registry, the approver roles, the write scope of each action and the contracts of
the specification and PO handoff) are in [`ACTIONS.md`](ACTIONS.md).

---


## Feature page format

Every file in `wiki/features/` must follow this format:

```markdown
---
id: F-XXX
title: [Feature name]
status: raw | specified | ready-for-design | in-design | ready-for-dev | in-dev | ready-for-qa | in-qa | ready-for-release | released
owner: po | designer | tech-lead | dev | qa | release | none
apps: [list of app IDs this feature affects - use the app IDs `prism.workspace.yml` declares]
sources: [paths to intake/processed/ items that produced this page]
advisory-review: not-needed | pending | done | skipped
# Required and non-blank when advisory-review is skipped:
advisory-skip-reason: [reason]
# The highest acceptance-criterion number ever assigned; required from specified on:
criteria-high-water: 3
# Absent or [] until a return or reopen invalidates domains for revalidation:
revalidation: [specification | design | technical-design]
# Per app, the domains that need fresh evidence (absent when none):
app-revalidation:
  backend: [implementation | tests | qa | release]
---

## Summary
One paragraph. What this feature does, why it exists, and what user problem it solves.
Written in business language, not technical language.
- **Observed:** [what the source shows] ([source](../../intake/processed/YYYY-MM-DD-slug/notes.md))
- **Assumed:** [what is taken as true without evidence]

## User story
As a [persona from personas/], I want to [action], so that [business outcome].

## Acceptance criteria
- [ ] **Decided:** AC-1 [backend] Condition 1 (testable, unambiguous) ([source](../../intake/processed/YYYY-MM-DD-slug/notes.md))
- [ ] **Proposed:** AC-2 [integration: backend, web] Condition 2 that two apps verify together

## Open questions
| # | Question | Owner | Status |
|---|----------|-------|--------|
| 1 | What is the fallback when the user is offline? | po | open |
| 2 | What does the empty state look like? | designer | open |
| 3 | Is real-time sync feasible without WebSockets? | dev | resolved: use polling |

This table is the Unknown form of the evidence labels in `SCHEMA.md`: write a gap here,
not as an `**Unknown:**` item.

## App scope
- **backend**: [what backend must implement, or "not in scope"]
- **mobile-android**: [what Android must implement, or "not in scope"]
- **mobile-ios**: [what iOS must implement, or "not in scope"]
- **web**: [what the web app must implement, or "not in scope"]

## Design
Link to design artifacts and key design decisions.
Format: [Description](../design/F-XXX-[slug].md) once design intake is complete.
This section is empty until /design-intake is run.

## Related features
- [F-XXX](F-XXX-[slug].md) - [why this relationship exists]

## API surface
High-level description of API changes required (expanded in api-contracts/).
Empty if no API changes are needed.

## Board review summary
Populated by /board-review command. Empty until then.
One paragraph summarizing the key concerns raised and what was resolved.

## Delivery evidence
| App | Artifact | Contract | Implementation | Tests | Basis |
|---|---|---|---|---|---|
| backend | `build:backend#412` | none | [PR 31](https://git.example/app/pull/31) | `./gradlew test`: 214 passed ([run](https://ci.example/412)) | checked |

## QA verification
| Row | Criteria | Method | Artifact | Environment | Attempt | Result | Evidence | Basis |
|---|---|---|---|---|---|---|---|---|

## Release
| App | Target | Version | Attempt | Outcome | Record | Basis |
|---|---|---|---|---|---|---|

## Evidence history
Append-only entries, one for every action that removes evidence from the active tables.

### YYYY-MM-DD - [action]
- Reason: [why]
- Affected apps: [app IDs]
- Participants: [apps that lost a Release row through a removed integration row, or none]
- Affected tracks: [ui, technical, or none]
- Archived evidence:
  | Delivery evidence | backend | `build:backend#412` | none | [PR 31](https://git.example/app/pull/31) | 214 passed | checked |
- Reaffirmed evidence: [rows kept active, verbatim, or none]
- Requirement/API invalidations: [path: done -> in-progress, or a sentence that none are invalidated]
- Linked bugs: [BUG-XXX, or none]
```

Owner values in the open-questions table must be one of: `po`, `designer`, `tech-lead`, `dev`,
`qa`, `release`.
Open-question status values must be one of: `open`, `resolved: [answer]`.

The open-questions table is the Unknown form of the evidence labels in `SCHEMA.md`; the other
sections carry the Decided, Observed, Proposed and Assumed labels, and a Decided or Observed claim
links its evidence (the processed intake item, a record or a URL). A later source that changes a
claim replaces the item in place.

Each owner has one clarify action that resolves only that owner's open questions:
`/po-clarify` (`po`), `/design-clarify` (`designer`, `tech-lead`) and `/dev-clarify` (`dev`).
Each one preserves question text, owners and lifecycle fields. A clarify action
that changes a requirement-bearing section of the feature, a design page or an
app requirement page must carry the full text of at least one answer it
resolves in that section. `/dev-clarify` may update the feature's Acceptance
criteria, App scope and API surface sections and the What to build, Technical
constraints, API contract reference and Acceptance criteria sections of its existing
app requirement pages, leaving their frontmatter unchanged except that a new criterion raises `criteria-high-water`.
`/po-clarify` and `/dev-clarify` change what the stage of the apps allows: a criterion is
not changed while an app it names is `ready-for-release` or `released`; the App scope section is
not changed from `ready-for-dev` on, and the API surface section not once an app is delivered
(use the feature-scope action, or a return route; the actions are in [`ACTIONS.md`](ACTIONS.md)). Open dev-owned questions block `/dev-start` and `/dev-done`; `qa` and `release` questions are resolved by the
QA and release actions.

### Acceptance criteria and their revisions

Every acceptance criterion of a feature that is `specified` or later has an ID and an
`applies-to`:

- `AC-<n> [app, app]`: each listed app verifies it in its own QA row.
- `AC-<n> [integration: app, app]`: two or more apps verify it together in one integration row.

Every app of the scope is named by at least one criterion (`app-without-criteria`). The ID is
unique (`duplicate-criterion-id`) and never reused: `criteria-high-water` holds the highest
number ever assigned, a new criterion takes that number plus 1 and the same write raises the
mark (`criterion_id_reused`, `criteria_high_water_decreased`; an ID above the mark is lint
`criterion-high-water-invalid`).

A criterion has a revision: `v1:` and the SHA-256 of the canonical JSON `[1, feature ID,
criterion ID, applies-to, evidence label, text]`. The applies-to is a sorted list, or
`{"integration": [...]}` sorted; the text is NFC with links written as `text <destination>`
and whitespace collapsed; the checkbox is not part of it. QA rows cite `AC-<n>@v1:<64 hex
digits>`. A change to a criterion's applies-to, label, text or link destination changes its revision
and makes the rows that cite the old one stale (`stale-qa-evidence`). `read_workspace` (as
`annotations.criteria`), the `show` query and a preview return the revisions, the preview with the QA rows the change makes stale.

### Status and owner lifecycle

The `status` and `owner` fields together represent the feature's position in the lifecycle and
change together; updates across the feature page, status board, and log are not a filesystem transaction.

| Status | Owner | Meaning |
|--------|-------|---------|
| raw | po | Captured by `/po-intake` with Summary, User story, Acceptance criteria, Open questions and App scope; [`/po-specify`](ACTIONS.md) completes the structure |
| specified | po | Structured spec written, open questions may remain |
| ready-for-design | design owner | PO has handed off; the design owner picks up |
| in-design | design owner | The design owner is actively working |
| ready-for-dev | dev | Design complete; developer picks up |
| in-dev | dev | The developer is delivering; at least one app has no delivery evidence yet |
| ready-for-qa | qa | Every app has delivery evidence |
| in-qa | qa | QA has recorded a result for every app that is not yet in release |
| ready-for-release | release | Every app is verified and has a pending or failed release row |
| released | none | Every app is released |

The **design owner** (see "Design owner and design tracks") is resolved from the scope when the
action is previewed and again when it is applied.

From `in-dev` on, a feature's status is the **minimum over the stages of its active apps**
(`in-dev` < `ready-for-qa` < `in-qa` < `ready-for-release` < `released`), and its owner follows
the status. A retired app is left out of the minimum. An app's stage comes from its rows:

1. its authoritative Release row has outcome `released`: `released`;
2. no Delivery evidence row: `in-dev`;
3. no QA verification row names it (an app row, or an integration row it takes part in): `ready-for-qa`;
4. no authoritative Release row (attempt `release-<n>`): `in-qa`;
5. a Release row that is `pending` or `failed`: `ready-for-release`.

A rule that matches first wins, so a released app is never demoted. `prism wiki lint` reports a
status that differs from the minimum (`feature-status-not-minimum`) and a status that needs a row
an app lacks (`app-row-missing`).

### advisory-review field

This field tracks whether domain review has been done; only these commands set it:

- `not-needed` - set by `/po-intake` for features with no domain complexity
  (authentication flows, settings screens, CRUD operations, admin tools, infrastructure)
- `pending` - set by `/po-intake` for features with domain complexity. A board review
  must happen before dev can start.
- `done` - set by `/board-review` after a review is completed. Only this command sets it.
- `skipped` - set by [`/po-handoff`](ACTIONS.md) or `/design-handoff` when the team explicitly
  decides to skip review. It requires a non-blank reason recorded in
  `advisory-skip-reason` frontmatter. For `/po-handoff`, the skip and reason stay
  as a proposal until that command's final handoff confirmation.

No other command touches `advisory-review`. Lint flags features from `ready-for-design` up to
`ready-for-release` with `advisory-review: pending` as incomplete; `skipped` with a reason suppresses it.

#### Design owner and design tracks

The design owner `D` is `designer` while an active app in the feature's `apps` has a UI (`has-ui`,
`unknown` counting as a UI) and `tech-lead` otherwise. The scope decides the owner, so a scope edit at
`ready-for-design` or `in-design` moves the owner to the design owner of the new scope.

From the first design action on, the feature page carries `design-tracks` and `design-reaffirm`:

```yaml
design-tracks:
  ui: pending              # pending | done | not-applicable
  technical: done          # pending | done | not-applicable
  ui-reason: "..."         # only with ui: not-applicable
  technical-reason: "..."  # only with technical: not-applicable
design-reaffirm: []        # [ui] | [technical] | [ui, technical]
```

- The first design action writes `technical: pending` and `ui: pending`, or `ui: not-applicable` with the
  reason `No app in scope has a UI.` when every active scoped app has `has-ui: false`. The keys are absent
  before design starts and after a return to `specified`; they are required from `in-design` on
  (`design-tracks-missing`, `design-tracks-invalid`).
- `ui` is settled by [`design-ui-done`](ACTIONS.md) (design pages in `design/` whose `apps` together cover every active app with a UI:
  `design-coverage-incomplete`) or `not-applicable` with a non-blank `ui-reason` (`ui-exemption-reason-required`);
  only the designer's explicit exemption makes the track `not-applicable` for an `unknown` app.
- `technical` is settled by `tech-design-done`: a complete technical design page in `technical-design/`
  (`technical-design-incomplete`) whose Test strategy names every criterion ID (`test-strategy-incomplete`), the agreed
  API contract when the API surface declares API work, and an active app that serves an API; or `not-applicable` with a
  non-blank `technical-reason` and no declared API work (`technical-track-required`).
- `design-handoff` needs both tracks settled and `design-reaffirm` empty after the proposal
  (`design-tracks-incomplete`, `design-reaffirm-pending`), and each track it settles passes that track's checks. It writes
  the pages of a track only when it settles that track, and the API contract only when it settles the technical track.
  `ready-for-dev` and later need both tracks settled (blocker `design-track-pending`).
- The track pages (`design/` for `ui`; `technical-design/` and the API contract for `technical`) are writable while
  `design-tracks` is absent and at `ready-for-design` or `in-design`, and locked from `ready-for-dev` on
  (`track_page_locked`), except a contract `status` change by `dev-done` or a return. Changing the pages of a settled
  track sets that track to `pending` in the same proposal (without its reason) and lists the other track in
  `design-reaffirm` when it is `done` (`track_reset_required`); `design-clarify` and `design-intake` do this when they
  change such a page. The other track's action, run with no page change, removes its entry. Each track action writes only
  the keys and pages of its own track (`track_scope`).
- A scope change at `ready-for-design` or `in-design` sets every settled track back to `pending` and applies the no-UI
  initialization again. A return to `in-design` (from development or QA) sets the affected tracks, named in the Evidence
  history entry, to `pending` and lists every other `done` track in `design-reaffirm`; a return to `specified` removes both keys.

#### API contract

When the feature's API surface declares API work, [`tech-design-done`](ACTIONS.md) (or a `design-handoff` that
settles the technical track with the `tech-lead` role) creates `api-contracts/F-XXX.md` with
`status: agreed` and `version: 1`; the user confirming the preview is the agreement, and no other action writes a
contract body. The page is written only from the API surface: each endpoint as `METHOD /path` (the paths the surface
names or, when it names none, a resource word it uses) and only data models that the surface or an endpoint names.
No contract is written when the surface declares none, and a feature has one contract.
A contract changes after its creation only as a revision while the feature is in design: `version` plus one, a changed body
and `status: agreed` (`contract_revision_required` for a changed body without the bump). A revision is refused with
`shared_contract_in_use` while another feature that links the contract has an app between `ready-for-dev` and
`ready-for-release`; that feature returns first with `dev-return-design`.
The contract has a digest, `c1:` and the SHA-256 of `[1, feature ID, version, sections]`, with the body's sections as
heading and text pairs (NFC, whitespace collapsed); front matter other than `version` is not part of it. Delivery evidence
cites it as `F-XXX@v<version>:c1:<digest>`, and the board reports that citation beside the contract page. A delivery row
that cites another contract, a revised one or `none` for a feature with a contract is `contract_binding_stale`.
Requirement pages link the contract in `## API contract reference`. `dev-start` accepts an `agreed` contract and
blocks on a `draft` one; `dev-done` marks it `implemented` once every app has delivered, keeping its digest.

#### Requirement pages at handoff

[`design-handoff`](ACTIONS.md) leaves exactly one requirement page per scoped app (`requirements_incomplete`): a missing page is
created `pending`, a `pending` or `in-progress` page may change its body sections and is set to `pending`, and a
`done` page stays unchanged (`requirement_body_change`).

#### Returns from implementation

[`dev-return-spec`](ACTIONS.md) and `dev-return-design` send a feature at `ready-for-dev` or `in-dev` back while no app is in QA or beyond.
One `## Evidence history` entry lists every app as affected, no participants, the affected tracks (`ui, technical` for
`specified`), every evidence row archived verbatim, and each requirement or contract page lowered. The same write sets
`revalidation` (`specification`, `design`, `technical-design` for `specified`; `design`, `technical-design` for `in-design`)
and gives every app all four `app-revalidation` domains, merged with what is pending (`revalidation_required`), and resets
the tracks as above. Released and unreleased apps together: `partial_release_requires_new_feature`.

API work needs an app that serves an API: when the API surface declares API work, at
least one active app in the feature's `apps` must have the `serves-api` capability
(`unknown` counts as serving one). Otherwise lint reports `api-surface-without-api-app`
for the feature before `released`, and `design-handoff`, `dev-start` and `dev-done` block
with that code (`api_surface_without_api_app` on the connected board).

#### Delivery and revalidation

Delivery evidence is an input to `dev-done`: the proposal carries the rows of the apps it names and the board checks
them in the same preview. Each named app gets one row in `## Delivery evidence` (`App | Artifact | Contract | Implementation | Tests | Basis`):

- **Artifact**: `version:<semver>`, `build:<name>#<number>`, `image:<name>@sha256:<64 hex>`, `package:<name>@<version>`
  or `commit:<7 to 40 hex>`; the board checks the form only (`artifact_reference_invalid`).
- **Contract**: `none`, or `F-XXX@v<version>:c1:<digest>` when the feature has an API contract.
- **Implementation**, **Tests**: substantive references (a pull request or source reference; a test command and its
  result). A placeholder is rejected.
- **Basis**: `checked` when the agent verified the references, `attested` when the approving human vouches for them
  (`basis_invalid` otherwise).

A reference the agent cannot check is `attested`, and the agent says so; it never invents delivery evidence.

An app that has a row is delivered. The proposal adds rows only for apps that are `in-dev` and that no earlier row
covers (`evidence_still_active`, `app_stage_mismatch`); delivered rows leave the table only when a return archives them.
The status is the minimum over the app stages (`in-dev` while an app has no row, `ready-for-qa` once every active app has
one; `app_stage_mismatch` otherwise). The named apps' requirement pages become `done`, and once every app has delivered
the API contract becomes `implemented`.

A `revalidation` list invalidates current readiness even when older status fields or evidence
still say delivered. Its domains are `specification`, `design` and `technical-design` for the
feature; `app-revalidation` lists `implementation`, `tests`, `qa` and `release` per app. A
feature domain blocks `dev-start` and `dev-done`. [`dev-done`](ACTIONS.md) clears `implementation` and `tests`
for the apps it delivers, `po-handoff` clears `specification` and `design-handoff` clears `design`
and `technical-design`, each only after fresh evidence and in the same write.

A dependency on another feature is satisfied when that feature is `released`; a dependency on a
requirement page is satisfied when the app's stage in its feature is `released`. An unmet
dependency is shown as a `warning` at `dev-start` and `dev-done`, and blocks [`release-done`](ACTIONS.md)
(`dependency_not_released`) unless the same release delivers it. Pages that wait for each other are the lint error `dependency-cycle`.

#### QA verification, QA outcomes and bugs

[`qa-verify`](ACTIONS.md) records what QA ran. A row names an app, or an integration of two or more apps
(`integration:app+app`), and cites the criteria it covered with their revisions; it is checked
against the delivered artifact (`qa_artifact_mismatch`), the criterion's revision and applicability
(`criterion_revision_stale`, `criterion_not_applicable`), the attempt (`qa_attempt_mismatch`) and the
environment (`environment_unknown`). An app's first row opens its QA stage (`in-qa`); an app can only
be tested while it is `ready-for-qa` or `in-qa` (`app_stage_mismatch`), and an integration row needs
every participant delivered.

`qa-pass` passes the apps it names: each needs coverage (every criterion that lists it has a passing
row on its current artifact in its current attempt, every integration criterion naming it has a
passing integration row, and no `fail` or `blocked` row is in the attempt), and no bug of the feature
may block it. A bug blocks an app when it names the feature and the app, is not `verified`, `released`
or `closed`, and is not deferred; a blocking bug cannot be deferred, and a verified bug must be verified
on the current artifact (`bug_verified_on_other_artifact`). The proposal may carry the missing QA rows,
so a clean run is one approval. With `qa-separate-from-dev` on, the approver is not a grant that
produced, recovered or repaired the app's Delivery evidence (`separation_required`).

`qa-fail` sends the apps it names back to development and archives their evidence. It needs a failure
on record for each app: a `fail` or `blocked` QA row in its current attempt, or a linked, non-deferred
bug that is `open`, `in-fix` or `fixed`. Archiving a QA row advances the app's attempt (`qa-<n+1>`).
`qa-return-spec` and `qa-return-design` (through `feature-reopen`) send the whole feature back from QA
before anything shipped; an app that is released refuses them (`partial_release_requires_new_feature`).

A bug page (`wiki/bugs/`, format in `bugs/_FORMAT.md`) moves `open`, `in-fix`, `fixed`, `verified`, and
from there to `released` inside `release-done`. `bug-update` performs the bug actions: triage and scope,
start, fixed, verified, reverify, reject, close (`wont-fix`, `duplicate`, `promoted`), defer and reopen.
A fix cannot be recorded while an app of the bug's feature is in its QA cycle (`feature_in_qa_cycle`):
the app returns first with `qa-fail`, citing the bug. Rejecting or reopening a bug archives its rows and
advances the generation of the Fix rows and the attempt of the verification.

#### Release, records and reopening

[`release-done`](ACTIONS.md) settles the authoritative Release row of each app it releases (`released` or `failed`) and writes one
dated release record, `releases/REL-XXX.md` (format in `releases/_FORMAT.md`). The row's Target is the app's delivery target in
`SETTINGS.md` when the release is recorded and a `released` row keeps it; its Version is the artifact QA verified
(`release_version_not_verified`); its Attempt is one more than the records that delivered the app for the feature, rollbacks and
redeploys excluded (`release_attempt_mismatch`); its Record links the record. Staging rows (a target that is an environment of the
app, attempt `—`) are informational and never count for a stage or an attempt. QA must still cover the app (`qa_evidence_stale`),
no bug may block it (`open_bug_blocks_release`), every verified bug of the feature and the app ships with it
(`verified_bug_not_included`), and the rows of one app and target in a record share their Version and Outcome
(`release_artifact_conflict`). A bug becomes `released` when every app of the bug is released, and ships with its feature
unless it has no feature or its feature app is already released; a released feature app that a bug fix reaches takes the
new record in its Release row (`bug_release_requires_feature`).

A record's number is one more than the highest on disk, allocated when the release is applied (`release_sequence_invalid`,
`release_id_taken`); recovery and repair keep the number already assigned. The **current delivery** of an (app, target) is
the highest-numbered record with a `released` row for it, redeploys included. `release-rollback` binds to it
(`rollback_target_invalid`), and `release-redeploy` retries a rollback of it, or a failed redeploy (`redeploy_version_mismatch`
when the version differs). A failed delivery that needs development is `release-return-dev`. A `released` feature is reopened
with `reopen-spec`, `reopen-design` (every row of every app is archived, released rows included, and every app gets all four
`app-revalidation` domains) or `reopen-dev` (only the apps that change are archived; the rows of the others are quoted under
Reaffirmed evidence). Release records are never changed by a reopen.

#### Evidence history and scope edits

`## Evidence history` is append-only. Every action that removes evidence from the active tables appends exactly
one entry, headed `### <preview day> - <action>`, and copies each removed row verbatim under `- Archived evidence:`
as a table row that starts with its section name. A row both archived and active is `evidence_still_active`; a
removed row that is not archived is `evidence_not_archived`; changing earlier entries is `history_not_append_only`.
An app's rows are archived as a unit; a released app never loses rows to another app's change.

From `ready-for-dev` on, `feature-scope` is the [`scope-edit`](ACTIONS.md) action and only removes apps: a retired
app, or an active app that has no evidence rows. Adding an app (`scope_stage_unavailable`; return
the feature to design), removing the last app (`scope_empty`) and replacing the apps of an all-retired
scope (`scope_replacement_requires_return`) are refused. In one write the edit drops the removed app
from every `applies-to`, removes a criterion left with no app, turns an integration criterion left
with one app into a per-app criterion, archives the removed app's rows and every integration row
naming it, archives the `pending` or `failed` Release row of every remaining app whose criteria
changed (those apps gain the `qa` and `release` revalidation domains), and sets the status to the
minimum of the remaining app stages. Released apps keep their rows.

**App scope and membership.** A feature's scope is its `apps` list; a change to the workspace's apps never edits it:

- Adding an app (`prism app add`) leaves every feature's `apps` as it is; a feature gains
  the app only by an explicit scope edit, recorded in `log.md`.
- Retiring an app (`prism app retire <id>`) sets `status: retired` in
  `prism.workspace.yml` and deletes no code, wiki page, requirement page or evidence.
  A retired app stays valid in the `apps` of a feature that is `released`, as history.
  Every feature before `released` that still lists it is flagged `app-retired-in-scope`:
  lint reports an error and every lifecycle action on that feature is blocked with
  that code until its `apps` is edited explicitly (the scope edit itself is not blocked).
  A new feature, and any edit that adds a retired app to a feature's scope, is
  rejected with `app-retired`.
- Re-pointing a feature from one app to another is an explicit scope edit through the
  normal lifecycle: the current owner edits `apps`, the `## App scope` entry and the app
  requirement pages, and records the change in `log.md`. No command does it automatically.


---

## Advisory file formats

`wiki/advisory/` holds three artifact types:

- `BOARD.md` - the current advisory board composition generated by `setup-project`
- `PROJECT_FOUNDATION.md` - the setup interview, risk framing, and initial board rationale
- `F-XXX-review.md` - per-feature board review outputs from `/board-review`

### PROJECT_FOUNDATION.md format

```markdown
# Project Foundation

## Project identity
- Name: [project name]
- Description: [one-sentence summary]
- Apps: [backend, web, ...]
- Auth methods: [if known]
- Infrastructure choices: [if known]
- Important correction or note: [optional]

## Setup interview

### 1. Primary users and trust
**Question:** Who are your primary users, and what do they trust this app to get right?
**Answer:** [confirmed answer]

### 2. Core decision or calculation
**Question:** What is the most important decision or calculation this app makes on behalf of users?
**Answer:** [confirmed answer]

### 3. Failure consequences
**Question:** What could go wrong if the app gets that wrong?
**Answer:** [confirmed answer]

### 4. Vulnerable groups
**Question:** Are there any user groups who might be especially vulnerable to a mistake?
**Answer:** [confirmed answer]

## Risk summary
- Core trust surface: [bullets]
- Primary failure modes: [bullets]
- Business impact: [bullets]
- Vulnerable groups: [bullets]
- Expertise gaps: [bullets]

## Why this board
Short paragraph explaining why the selected advisory board composition fits the
project's domain risks.

## Seed artifacts from setup
- [BOARD.md](BOARD.md)
- [persona or rule links created during setup]
```

### F-XXX-review.md format

Output format for `/board-review`. One page maximum.

```markdown
---
feature-id: F-XXX
reviewed: YYYY-MM-DD
board-members-consulted: [list of board member names from BOARD.md]
---

## 1. Conflicts
Does this feature conflict with anything already built or decided?
Named conflicts only - reference specific feature IDs, ADR IDs, or business rule IDs.
If none: "No conflicts identified."

## 2. Gaps
Is there anything missing from the current spec that will block development before it starts?
If none: "Spec is complete."

## 3. Build order
Across apps, what must be built first?
If no dependencies: "No cross-app ordering constraints."

## 4. Biggest risk
One sentence. What is most likely to cause this feature to fail, cause user harm, or
take significantly longer than expected?

## Board perspective summaries
[One short paragraph per board member who has a relevant concern.]
[Only include members with something substantive to say.]

## Actions required before dev starts
- [ ] [Specific action with owner - po / designer / dev]

## Actions that can be deferred
- [Action that can be addressed post-ship with acceptable risk]
```

