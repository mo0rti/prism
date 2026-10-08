# Feature page format

Use this format for every file in `wiki/features/`. Filename: `F-XXX-[slug].md`.

```markdown
---
id: F-XXX
title: [Feature name]
status: raw | specified | ready-for-design | in-design | ready-for-dev | in-dev | ready-for-qa | in-qa | ready-for-release | released
owner: po | designer | tech-lead | dev | qa | release | none
apps: [list of app IDs this feature affects]
sources: [paths to intake/processed/ items that produced this page]
advisory-review: not-needed | pending | done | skipped
# Required and non-blank when advisory-review is skipped:
advisory-skip-reason: [reason]
# The highest acceptance-criterion number ever assigned; required from `specified` on:
criteria-high-water: 3
# From the first design action on (absent before design starts and after a return to `specified`):
design-tracks:
  ui: pending            # pending | done | not-applicable
  technical: pending     # pending | done | not-applicable
  ui-reason: "..."       # only with ui: not-applicable
  technical-reason: "..." # only with technical: not-applicable
design-reaffirm: []      # [ui] | [technical] | [ui, technical]
# Omit or use [] until a return or reopen marks domains for fresh evidence:
revalidation: [specification | design | technical-design]
# Per app, the domains that need fresh evidence:
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

Owner must be one of: po | designer | tech-lead | dev | qa | release
Status must be one of: open | resolved: [answer]
This table is the Unknown form of the evidence labels in SCHEMA.md: write a gap here, not
as an `**Unknown:**` item.

## App scope
- **backend**: [what backend must implement, or "not in scope"]
- **mobile-android**: [what Android must implement, or "not in scope"]
- **mobile-ios**: [what iOS must implement, or "not in scope"]
- **web**: [what the web app must implement, or "not in scope"]

Only list apps that `prism.workspace.yml` declares.

## Design
Link to design artifacts. Empty until /design-intake is run.

## Related features
- [F-XXX](F-XXX-[slug].md) - [why this relationship exists]

## API surface
High-level description of API changes required. Empty if no API changes.

## Board review summary
Populated by /board-review. Empty until then.

## Delivery evidence
| App | Artifact | Contract | Implementation | Tests | Basis |
|---|---|---|---|---|---|
| [declared app] | `build:backend#412` | none | [PR or source reference](https://example.com) | `./gradlew test`: 214 passed | checked |

## QA verification
| Row | Criteria | Method | Artifact | Environment | Attempt | Result | Evidence | Basis |
|---|---|---|---|---|---|---|---|---|

## Release
| App | Target | Version | Attempt | Outcome | Record | Basis |
|---|---|---|---|---|---|---|

## Evidence history
Append-only dated entries; empty until evidence is archived.

### YYYY-MM-DD - [action]
- Reason: [why]
- Affected apps: [app IDs]
- Participants: [apps that lost a Release row through a removed integration row, or none]
- Affected tracks: [ui, technical, or none]
- Archived evidence:
  | Delivery evidence | backend | `build:backend#412` | none | [PR](https://example.com) | `./gradlew test`: 214 passed | checked |
- Reaffirmed evidence: [rows kept active, verbatim, or none]
- Requirement/API invalidations: [path: done -> in-progress, or a sentence that none are invalidated]
- Linked bugs: [BUG-XXX, or none]
```

## Evidence labels

Claims in Summary, Acceptance criteria and the other sections carry the evidence labels
that `SCHEMA.md` defines (Decided, Observed, Proposed, Assumed, Unknown) as a bold run-in
label. A Decided or Observed claim links its evidence: the processed intake item, a record
or a URL. A later source that changes a claim replaces the item in place.

## Acceptance criteria

Each criterion has an ID and says which apps verify it:

- `AC-<n> [app, app]`: each listed app verifies it in its own QA row.
- `AC-<n> [integration: app, app]`: two or more apps verify it together in one integration row.

The ID is unique and never reused: `criteria-high-water` holds the highest number ever
assigned, a new criterion takes that number plus 1, and the same write raises the mark. Every
app in `apps` is named by at least one criterion. A criterion has a revision, `v1:` and a
SHA-256 over its feature, ID, `applies-to`, evidence label and text (links as `text <url>`,
whitespace collapsed); QA rows cite `AC-<n>@v1:<64 hex digits>`, and a changed criterion makes
the rows that cite its old revision stale. The board shows each criterion's current revision
when it reads a feature.

## Raw and specified pages

`/po-intake` creates every new feature as `status: raw`, `owner: po`. Its page has
substantive Summary, User story, Acceptance criteria, Open questions and App
scope sections; the other sections stay empty. `/po-specify` completes the page and sets
`status: specified`: each of Design, Related features, API surface and Board review summary
gets one line of supported content or an explicit statement that nothing exists yet
(`Not started.`, `None identified.`, `None.` under API surface, `Not reviewed yet.`), the four
evidence sections exist and stay empty, and every criterion gets its ID and `applies-to`. API
surface text other than `None.` declares API work and needs an API contract page before
`/dev-start`, so write `None.` unless the intake material or an answered question states an API
change. Keep open questions in the Open questions table, never in these sections. A later
action replaces that line with its real content.

## Design tracks

A feature in design has two tracks under one owner, the design owner (`designer` while an active app has a
UI, otherwise `tech-lead`). `ui` covers the design pages and `technical` the technical design page and the API
contract. Each track is `pending`, `done` or `not-applicable`; `not-applicable` carries a non-blank reason
(`ui-reason`, `technical-reason`).

- The first design action (`design-start`, `design-ui-done`, `tech-design-done` or `design-handoff`) writes
  `technical: pending` and `ui: pending`, or `ui: not-applicable` with the reason `No app in scope has a UI.`
  when every active app has `has-ui: false`. `unknown` counts as a UI, so only an explicit exemption by the
  designer makes the UI track `not-applicable` for such an app. `design-reaffirm` is written with the tracks.
- `design-ui-done` sets `ui` (needs design pages whose `apps` cover every app with a UI, or a reason).
  `tech-design-done` sets `technical` (needs a complete technical design page whose Test strategy names every
  criterion, the agreed API contract when the API surface declares API work, or a reason and no API work).
  `design-handoff` needs both settled and `design-reaffirm` empty, and may settle either track in the same
  confirmation. `ready-for-dev` and later need both tracks settled (`design-track-pending`).
- Changing the pages of a settled track sets that track back to `pending` in the same write and lists the
  other track in `design-reaffirm` when it is `done` (`track_reset_required`). The other track's action, run
  with no page change, removes its entry. A scope change in design sends every settled track back to `pending`.
  The track pages are locked from `ready-for-dev` on (`track_page_locked`).
- A return to `specified` removes both keys. A return to `in-design` sets the affected tracks to `pending` and
  lists every other `done` track in `design-reaffirm`.

## Evidence tables

A feature at `in-dev` or later carries its evidence in three tables. Each app has its own rows,
so one app can be in QA while another is still in development.

- **Delivery evidence**: one row per app that delivered. `Artifact` is `version:1.4.0`,
  `build:backend#412`, `image:registry/app@sha256:<64 hex digits>`, `package:name@1.4.0` or
  `commit:<7 to 40 hex digits>`; the board checks the form, never that the artifact exists.
  `Contract` is `none` when the feature has no API contract, otherwise the citation of the current contract,
  `F-XXX@v<version>:c1:<digest>`, as the board reports it beside the contract page (`contract_binding_stale`
  when the contract changed since).
  `Implementation` and `Tests` are substantive references. `Basis` is `checked` (the proposer
  verified the references) or `attested` (the approving human vouches for them).
- **QA verification**: one row per app, or an `integration:app+app` row for criteria that two
  apps verify together. It records the criteria and their revisions, the method (`automated`,
  `manual` or `exploratory`), the verified artifact, the environment, the attempt `qa-<n>`, the
  result (`pass`, `fail` or `blocked`), the evidence and the basis.
- **Release**: one row per app and delivery, with the target, the version, the attempt
  `release-<n>`, the outcome (`pending`, `released` or `failed`), the record and the basis.

A QA row names an app (`backend`) or an integration (`integration:backend+web`, the participants
sorted and joined by `+`) and cites the criteria it covered as `AC-<n>@v1:<64 hex digits>`. The
artifact is the delivered artifact of the app (an integration row writes `app=artifact` for every
participant, joined by `;`), and the environment is `local`, `ci` or an environment the app's
delivery target declares. The attempt of an app is 1 plus the Evidence history entries that list it
under Affected apps and archived a QA row that names it; an integration row takes the highest attempt
of its participants. A row is replaced by a row with the same key and criterion in the current attempt.
`/qa-verify` records QA rows, `/qa-pass` adds the `pending` Release row of each app it passes, and
`/qa-fail` archives the rows of an app that failed. A defect found in QA is a bug page in `wiki/bugs/`
(format in `bugs/_FORMAT.md`), created in the same proposal as the QA row.

An app's stage follows its rows: `in-dev` without a delivery row, `ready-for-qa` with one,
`in-qa` once a QA row names it, `ready-for-release` with a pending or failed Release row, and
`released` when its Release row is `released`. The feature's status is the lowest stage of its
active apps.

## Evidence history

Each action that removes evidence from the active tables (a return, a reopen, a failed QA or a
scope edit that drops an app) appends one entry, headed `### YYYY-MM-DD - action` with the
preview day, and keeps the earlier entries as they are. Under `- Archived evidence:` keep every
removed row verbatim, one row per line, as a table row that starts with its section name
(`Delivery evidence`, `QA verification`, `Release`) and then the row's own cells. Put the rows on
the lines directly below the label, before the next `- Label:` bullet. Letter case and spaces
around `|` do not matter; the cell text does. A row that is both archived and still in its
active table is rejected with `evidence_still_active`, and a removed row that is not archived
with `evidence_not_archived`.

Under `- Requirement/API invalidations:` write each invalidated requirement or API page as its
full relative path, a colon, its current status, `->` and its new status. When no page is
invalidated, write a sentence such as `No requirement or API page is invalidated.`; a bare `None`
is too short and the connected board rejects it with `impact_review_required`.
