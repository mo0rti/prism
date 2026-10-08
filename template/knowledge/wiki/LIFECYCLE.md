---
schema-version: 1
---

# Wiki lifecycle protocol - features, board and advisory files

This file extends `SCHEMA.md`, which is read first. It holds the feature page format,
the status and owner lifecycle, the lifecycle action registry and the advisory file
formats, and is read for every feature, board or advisory operation.

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
(use the feature-scope action, or a return route). Open dev-owned questions block `/dev-start` and `/dev-done`; `qa` and `release` questions are resolved by the
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
| raw | po | Captured by `/po-intake` with Summary, User story, Acceptance criteria, Open questions and App scope; `/po-specify` completes the structure |
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
- `skipped` - set by `/po-handoff` or `/design-handoff` when the team explicitly
  decides to skip review. It requires a non-blank reason recorded in
  `advisory-skip-reason` frontmatter. For `/po-handoff`, the skip and reason stay
  as a proposal until that command's final handoff confirmation.

No other command touches `advisory-review`. Lint flags features from `ready-for-design` up to
`ready-for-release` with `advisory-review: pending` as incomplete; `skipped` with a reason suppresses it.

### PO handoff transition contract

The PO handoff action is a confirmation-gated transition from
`status: specified` and `owner: po` to `status: ready-for-design` and
`owner:` the design owner of the feature's scope.

- Resolve the requested ID to exactly one existing
  `knowledge/wiki/features/[F-XXX]-[slug].md` source file. `/po-handoff`
  accepts only `specified` + `po`; use `/po-specify` for the separate raw to
  specified structured-draft action.
  Do not invent a legacy adapter or a generic transition setter.
- Read the current `SCHEMA.md`, `LIFECYCLE.md`, `status-board.md`, feature, linked context, workspace
  identity, and any available source fingerprint before preparing a preview, and again immediately before
  confirmation and before writing. Compare the unique path, identity, status, owner, advisory state, and
  fingerprint with any copied request or static snapshot; a mismatch or unavailable comparison blocks the
  write and requires a fresh preview.
- Factual PO completeness requires a non-empty Summary, one singular `## User
  story` section with content, meaningful acceptance criterion entries, a non-empty
  frontmatter `apps` list with a non-empty matching `## App scope` entry
  for every declared app, and no open questions owned by `po`. A `skipped`
  advisory requires a non-blank
  `advisory-skip-reason`. Semantic sufficiency remains a human or agent judgment.
- When advisory review is `pending`, offer an independent `/board-review F-XXX` (with its own confirmation
  and write rules), then reread all source files and rerun the checks. If the user declines, request an explicit
  non-blank reason and keep the skip fields as a proposal until the final handoff confirmation; evaluate that
  proposed skip as the `skipped` outcome for this preview while the source stays `pending`. Never silently skip review.
- A preview is not an approval or a status write. It shows the observed source fields, advisory and
  completeness checks, identity/fingerprint facts, exact destination fields, and every file that would change.
  Decline or cancel means no mutation.
- A dashboard or clipboard request is copy-only: it executes no agent, mutates no wiki
  and moves no board card. The Board derives columns from current source fields and
  cannot prove who changed them or whether confirmation happened.
- The selected generated handoff surface (Codex: `.agents/skills/po-handoff/SKILL.md`;
  Claude: `.claude/commands/po-handoff.md`) must contain `<!-- prism:po-handoff-contract:v2 -->`.
  A missing marker means older, unsupported instructions: refresh the file from the current
  template. A Prism version alone cannot prove capability.
- The optional `prism wiki transition-preflight F-XXX [path] --action po-handoff
  --json` response uses the common envelope with `schema_version: 1` and
  `command: "wiki transition-preflight"`. Its `facts` include
  `requested_action`, `transition_capability` (`version: 3`, `mode: "copy-only"`,
  the supported action list, per-action surfaces, and a consistent snapshot),
  and a per-feature `transition` (`version: 2`, `action`, `target_owner`,
  `supported`, `classification`, and surface `invocations`). A check has the status
  `pass`, `warning`, `review`, `blocked` or `unknown`; a `warning` is shown to the
  approver and never blocks the action. Use
  **Copy request** only for the selected invocation with `supported: true`,
  `classification: "ready"`, and a consistent snapshot. Blocked or unknown
  results are review/repair guidance.

### Lifecycle action registry

The generated workflow exposes these named, feature-only actions. Each requires the exact source
status/owner pair and, after final user confirmation, writes only the proposed feature and the
corresponding status board, index, log or evidence records. `D` is the design owner of the scope.

| Action | Exact source | Destination | Primary responsibility |
|---|---|---|---|
| `po-specify` | `raw` + `po` | `specified` + `po` | Author a structured body from one raw page, with every criterion's ID and `applies-to`; keep facts and turn unknowns into owned questions. |
| `po-handoff` | `specified` + `po` | `ready-for-design` + `D` | Verify factual PO completeness and hand the specification to design. |
| `design-start` | `ready-for-design` + `D` | `in-design` + `D` | Start design work after rereading the assigned feature, and write the initial design tracks. |
| `design-ui-done` | `ready-for-design` or `in-design` + `D` | `in-design` + `D` | Settle the UI track: design pages that cover every app with a UI, or an exemption with a reason. |
| `tech-design-done` | `ready-for-design` or `in-design` + `D` | `in-design` + `D` | Settle the technical track: the technical design page, its test strategy and, for declared API work, the agreed API contract. |
| `design-handoff` | `ready-for-design` or `in-design` + `D` | `ready-for-dev` + `dev` | Verify both tracks are settled (settling either in the same confirmation) and prepare the app requirements. |
| `dev-start` | `ready-for-dev` + `dev` | `in-dev` + `dev` | Start implementation after rereading requirements and applicable API contracts. |
| `dev-done` | `ready-for-dev` or `in-dev` + `dev` | the minimum of the app stages: `in-dev` + `dev`, or `ready-for-qa` + `qa` once every app has delivered | Record the delivery evidence of the apps it names: the artifact, tests and implementation for each. |
| `dev-return-spec` | `ready-for-dev` or `in-dev` + `dev` | `specified` + `po` | Send the feature back to the PO: archive every evidence row, remove the design tracks and set the revalidation domains. |
| `dev-return-design` | `ready-for-dev` or `in-dev` + `dev` | `in-design` + `D` | Send the feature back to design: archive every evidence row; the affected tracks go back to `pending`, the other settled track awaits reaffirmation. |
| `qa-verify` | `in-dev` + `dev`, `ready-for-qa` + `qa` or `in-qa` + `qa` | the minimum of the app stages | Record QA rows for apps or integrations; the first row of an app opens its QA stage. |
| `qa-pass` | as `qa-verify` | the minimum of the app stages: `ready-for-release` + `release` once every app has passed | Pass the apps it names: a `pending` Release row for each, with the QA rows still missing in the same proposal. |
| `qa-fail` | as `qa-verify`, or `ready-for-release` + `release` | `in-dev` + `dev` | Send the apps it names back to development; their delivery, QA and Release rows move to Evidence history. |
| `qa-return-spec`, `qa-return-design` | as `qa-fail` | `specified` + `po`, or `in-design` + the design owner | Send the whole feature back to specification or design from QA (`feature-reopen`); refused when an app is released. |
| `scope-edit` | `ready-for-dev` up to `released` | the minimum of the app stages after the edit | Remove an app from the scope (the `feature-scope` skill from `ready-for-dev` on). |

`/dev-done` from `ready-for-dev` also starts development in the same write. Before `ready-for-dev`,
`/feature-scope` is an ordinary write that edits `apps` and the App scope section and, at `ready-for-design`
or `in-design`, sets the owner to the design owner of the new scope.

Bug handling is the `bug-update` skill, which selects one of the bug actions below. The release
actions and the routes back from released work are registered but answer `action_unavailable` in
this version of the board; a feature in `ready-for-release` stays there.

Each gated action needs a human who holds the role that approves it: `po` for `po-specify`,
`po-handoff` and `scope-edit`; the design owner role for `design-start` and `design-handoff`, and
`designer` for `design-ui-done` and `tech-lead` for `tech-design-done`; `dev` for `dev-start`,
`dev-done` and the returns from implementation; `qa` for `qa-verify`, `qa-pass`, `qa-fail` and the
routes back from QA. A `design-handoff` that settles the UI track also needs `designer`, and one that
settles the technical track `tech-lead`, on top of the design owner. The board checks the role when
it applies the action.

#### Common action protocol

1. Resolve one canonical feature path and read `SCHEMA.md`, this file, `status-board.md`, the
   feature, linked context, relevant requirements and API contracts, workspace
   identity, and current fingerprints. Intake folders are outside these actions.
2. If a Prism preflight is available, accept it only when the common envelope is
   schema 1, command facts name the requested action, transition capability
   is version 3 with the requested action in its per-action surfaces, transition
   version is 2, and the snapshot is consistent. Check the selected generated
   Codex or Claude file for its matching `prism:<command>-contract:v2` marker; a
   version string alone is insufficient. An older capability or generated
   instruction falls back to these direct-file rules after the instructions are refreshed.
3. Verify the exact source pair, action-specific checks, advisory and question
   state, and affected app evidence. Show observed facts and the complete proposed
   write diff. Unknown or blocked checks need review or repair guidance.
4. Every proposed write must name its exact feature, requirement, API, status board,
   index, log, evidence, revalidation, and history paths. Preserve unrelated
   statuses and API contracts.
5. Reread the source and context immediately before asking for final
   confirmation. A copied dashboard, clipboard request, or CLI preflight is
   read-only and never approval. Decline or cancel means no mutation. If a
   multi-file write is partial, report the exact observed changes and recover
   from a fresh reread. After confirmation, reread the same sources once more and
   compare the recorded identity, path, status, owner, advisory, revalidation, and
   fingerprint before writing anything.

Each action may change only what its row allows; the board refuses anything else
(`lifecycle_frontmatter_scope`, `lifecycle_body_scope`, `lifecycle_write_scope`):

| Action | Front matter | Feature sections | Other pages |
|---|---|---|---|
| `po-specify` | `status`, `owner`, `criteria-high-water` | every section except the evidence sections, which exist and stay empty | none |
| `po-handoff` | `status`, `owner`, `advisory-review`, `advisory-skip-reason`, `revalidation` | none | none |
| `design-start` | `status`, `owner`, `design-tracks`, `design-reaffirm` | none | none |
| `design-ui-done` | `status`, `owner`, `design-tracks` (`ui`, `ui-reason`), `design-reaffirm` | Design | this feature's `design/` pages |
| `tech-design-done` | `status`, `owner`, `design-tracks` (`technical`, `technical-reason`), `design-reaffirm` | Design | `technical-design/F-XXX-*.md`, `api-contracts/F-XXX.md` |
| `design-handoff` | `status`, `owner`, `revalidation`, `design-tracks` (the tracks it settles), `design-reaffirm` | Design | the pages of each track it settles, requirement pages |
| `dev-start` | `status`, `owner` | none | none |
| `dev-done` | `status`, `owner`, `app-revalidation` | Delivery evidence (add rows) | the named apps' requirement pages (to `done`), the API contract (to `implemented` once every app has delivered) |
| `dev-return-spec`, `dev-return-design` | `status`, `owner`, `revalidation`, `app-revalidation`, `design-tracks`, `design-reaffirm` | the three evidence tables (remove every row); Evidence history (one entry) | requirement pages and the API contract, only to a lower `status` |
| `qa-verify` | `status`, `owner` | QA verification (add or replace rows); Open questions (`qa` rows) | new bug pages |
| `qa-pass` | `status`, `owner`, `app-revalidation` | QA verification; Release (a `pending` row per app passed); Open questions (`qa` rows) | new bug pages |
| `qa-fail` | `status`, `owner`, `app-revalidation` | Delivery evidence, QA verification, Release (remove rows); Evidence history | the named apps' requirement pages and the API contract, to a lower `status`; new bug pages |
| `qa-return-spec`, `qa-return-design` | as the returns from implementation | as the returns from implementation | as the returns from implementation |
| `scope-edit` | `apps`, `status`, `owner`, `app-revalidation`, `criteria-high-water` | App scope; Acceptance criteria (three edits); the evidence tables and Evidence history | none |

#### Specification and handoff boundaries

`po-intake` creates every new feature as `raw` + `po`, with the Summary, User story, Acceptance
criteria, Open questions and App scope sections from the intake material and the others empty.
`po-specify` adds what is missing: each of Design, Related features, API surface and Board review
summary gets one line of supported content or an explicit statement that nothing exists yet (for
example `Not started.`; under API surface, `None.`), the four evidence sections exist and stay
empty, every criterion gets its ID and `applies-to`, and the spec checks below hold before the
feature becomes `specified`.
An API surface other than an empty section or a plain statement that there is none
(`None.`) declares API work and needs an API contract page before `dev-start` (created by `tech-design-done`, or by a
`design-handoff` that settles the technical track), so `po-specify` writes `None.` unless the intake material or
an answered question states an API change. Open questions stay in the Open questions table, never in these sections.

`po-specify` must verify or author the complete required feature body from raw input and show and
confirm that body. An incomplete raw page is filled from supported facts and explicit questions
owned by `po`, `designer`, `tech-lead` or `dev`, and the write set includes the authored body; a raw
page that already passes the structured-output gate may be preserved, so the write set may hold only
status/metadata, status board, index, and log updates. No placeholder text is accepted as a
requirement. Existing advisory state is preserved, and a pending advisory remains a later-action blocker.

`po-handoff` is the stricter factual handoff from specified to design. Its completeness checks
include a nonempty Summary, exactly one substantive `## User story`, meaningful acceptance entries,
a nonempty matching app scope, no open PO questions, and a nonblank skip reason for a proposed
advisory skip. The destination owner is the design owner of the scope (`design_owner_mismatch` otherwise).

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
- `ui` is settled by `design-ui-done` (design pages in `design/` whose `apps` together cover every active app with a UI:
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

When the feature's API surface declares API work, `tech-design-done` (or a `design-handoff` that
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

`design-handoff` leaves exactly one requirement page per scoped app (`requirements_incomplete`): a missing page is
created `pending`, a `pending` or `in-progress` page may change its body sections and is set to `pending`, and a
`done` page stays unchanged (`requirement_body_change`).

#### Returns from implementation

`dev-return-spec` and `dev-return-design` send a feature at `ready-for-dev` or `in-dev` back while no app is in QA or beyond.
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
feature domain blocks `dev-start` and `dev-done`. `dev-done` clears `implementation` and `tests`
for the apps it delivers, `po-handoff` clears `specification` and `design-handoff` clears `design`
and `technical-design`, each only after fresh evidence and in the same write.

A dependency on another feature is satisfied when that feature is `released`; a dependency on a
requirement page is satisfied when the app's stage in its feature is `released`. An unmet
dependency is shown as a `warning` at `dev-start` and `dev-done`.

#### QA verification, QA outcomes and bugs

`qa-verify` records what QA ran. A row names an app, or an integration of two or more apps
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

#### Evidence history and scope edits

`## Evidence history` is append-only. Every action that removes evidence from the active tables appends exactly
one entry, headed `### <preview day> - <action>`, and copies each removed row verbatim under `- Archived evidence:`
as a table row that starts with its section name. A row both archived and active is `evidence_still_active`; a
removed row that is not archived is `evidence_not_archived`; changing earlier entries is `history_not_append_only`.
An app's rows are archived as a unit; a released app never loses rows to another app's change.

From `ready-for-dev` on, `feature-scope` is the `scope-edit` action and only removes apps: a retired
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

