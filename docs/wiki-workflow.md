# Wiki Workflow

This page explains how the generated-project product wiki works, how the read/query layer
fits into it, and how to interpret `WIKI_REPORT.md`.

If you are new to Prism, read this page in this order:

1. understand the wiki and source-of-truth boundary
2. follow the role flow that matches your work
3. use the command reference examples for deeper drill-down

## Core Idea

The wiki is the shared source of truth for product intent in generated Prism projects.

The most important directories are:

- `knowledge/wiki/features/`
- `knowledge/wiki/design/`
- `knowledge/wiki/app-requirements/`
- `knowledge/wiki/business-rules/`
- `knowledge/wiki/api-contracts/`
- `knowledge/wiki/advisory/`

The lifecycle operations create and refine that state. The read/query operations help
agents and humans navigate it.

## Source-of-Truth Boundary

The most important rule is simple:

- the wiki files are the source of truth
- `WIKI_REPORT.md` is only an orientation layer
- read/query commands assemble context, but they do not replace the underlying files

If `WIKI_REPORT.md` disagrees with the underlying wiki files, the wiki files win.

## Current State And History

Wiki pages state what is true now. No page carries a date about itself: feature,
persona, business-rule, design, app-requirement and API-contract pages have no
`introduced`, `last-updated` or similar field, and `index.md` has no date column. A
date about the world, such as an effective date or a deadline, is a domain fact and
may appear in a page.

Two kinds of record keep their own date, because the date is part of what they
record: an ADR (`date`), an advisory review (`reviewed`) and each entry under a
feature's `## Reopen history`.

When something was written, decided, verified or amended is recorded in
`knowledge/wiki/log.md`, which is append-only and the only home for history. Every
entry has the same shape:

```text
## 2026-10-06 po-handoff | F-001
- paths: knowledge/wiki/features/F-001-review-summary-export.md, knowledge/wiki/index.md
- evidence: knowledge/intake/processed/review-summary
- by: Claude Code (confirmed by Riley)
Handed to design after the board review.
```

`paths` lists the changed paths, `evidence` links to the evidence and never copies
it, and `by` names who made the change. One optional line of plain text, at most one
sentence, may follow. The board service writes its entries in this format; its
`evidence` is the board preview, and it keeps the actor and a preview marker as HTML
comments inside the entry. `SCHEMA.md` defines the format.

`prism wiki lint` reports:

| Code | Severity | Meaning |
|---|---|---|
| `history-date-on-page` | error | A history-date field (`introduced`, `last-updated`, `created`, `updated`, `date-updated` and similar) in the front matter of a current-state page. The message points to `log.md`. |
| `malformed-log-entry` | warning | A `log.md` entry that is not in the format. Lint reports it and never rewrites the log. |
| `missing-schema-version` | error | `SCHEMA.md` or `LIFECYCLE.md` without the front matter `schema-version: 1`. |

## Feature Lifecycle Actions

Lifecycle actions are named, feature-only workflows. They resolve one exact
feature path, read the current source and linked context, prepare a complete
proposal, and write only after the user confirms the full write set.

| Action | Source | Destination |
|---|---|---|
| `po-specify` | `raw` + `po` | `specified` + `po` |
| `po-handoff` | `specified` + `po` | `ready-for-design` + `designer` |
| `design-start` | `ready-for-design` + `designer` | `in-design` + `designer` |
| `design-handoff` | `in-design` + `designer` | `ready-for-dev` + `dev` |
| `dev-start` | `ready-for-dev` + `dev` | `in-dev` + `dev` |
| `dev-done` | `in-dev` + `dev` | `done` + `none` |
| `reopen-spec` | `done` + `none` | `specified` + `po` |
| `reopen-design` | `done` + `none` | `in-design` + `designer` |
| `reopen-dev` | `done` + `none` | `in-dev` + `dev` |

Use `feature-reopen F-XXX [specified|in-design|in-dev]` to select one reopen
route. It is not a generic status setter. `po-specify` reads the raw body and
authors the required structured sections, carrying supported facts forward and
keeping unknowns as explicit questions owned by `po`, `designer`, or `dev`. If
the raw body is already structured, it may be verified and preserved; otherwise
the missing sections are authored. It must show and confirm the body rather than
performing an unverified status-only write. `po-handoff` remains the stricter
specified-to-design handoff and checks factual Summary, User story, acceptance
criteria, matching app scope, PO questions, and advisory outcome.

`design-handoff` requires design evidence for apps with a UI (`has-ui`) unless the feature
frontmatter has `design: not-applicable` and a nonblank
`design-exemption-reason`, with the user's explicit confirmation in the final
handoff preview. Non-UI features do not need a design page or exemption. When the
feature's API surface declares API work and no API contract covers it yet,
`design-handoff` also creates `api-contracts/F-XXX.md` at `agreed`, written only from
that API surface; the person confirming the handoff preview is the agreement. A
`revalidation` list records domains invalidated by a confirmed reopen;
downstream actions treat those domains as active until fresh evidence is
verified and explicitly cleared.

`dev-done` means shipped for every declared app. The feature must have one
substantive, verifiable `## Delivery evidence` row per declared app with
Implementation and Tests references and a `Release` cell that is release
evidence (`release:`, `tag:` or `deployment:` and a URL or record path) or a
delivery attestation (`attested by <Name>:` and a URL or path), plus complete
applicable requirements and API contracts. A commit or pull request proves
which code changed, not that it shipped. File presence and lint alone are not shipment
evidence. A partial app remains `in-dev`.

Reopen previews record the reason, impact, route, affected apps/artifacts,
and prior completion/release evidence. Confirmation appends that record to
`## Reopen history`, removes prior active Delivery evidence so it cannot satisfy
a future Done check, sets route-specific revalidation domains, and names exact
affected requirement/API status invalidations. Unaffected evidence is preserved
only when explicitly reaffirmed. Shared API contracts are never reset in bulk.
The complete protocol and formats are in
[`knowledge/wiki/LIFECYCLE.md`](../template/knowledge/wiki/LIFECYCLE.md).

## `WIKI_REPORT.md`

`knowledge/wiki/WIKI_REPORT.md` is a generated orientation summary.

It is:

- generated on demand
- written only by `feature-status`
- read-only
- ignored from version control in generated projects
- useful for quick orientation before deeper reading

It is not:

- the source of truth
- a hand-maintained document
- a replacement for `index.md` or feature pages

## `SETTINGS.md`

`knowledge/wiki/SETTINGS.md` is the canonical home for project-level wiki behavior
settings.

The setting:

```markdown
---
wiki-stale-after-days: 14
---

# Wiki Settings

Project-level settings for wiki read/query behavior.
```

Commands that use this setting must fall back cleanly to `14` if the file is missing, the
key is missing, or the value is malformed.

Pages carry no date, so lint does not report page age. Freshness is derived from
`log.md`, never from a date on the page; `status` still reports the setting. Source
integrity errors and action-specific prerequisites gate lifecycle requests.

## Start Here By Role

### If you are a Product Owner

Typical flow:

1. place raw notes in `knowledge/intake/pending/`
2. run `po-intake`
3. review the generated feature pages and open questions
4. use `po-clarify` to answer PO-owned questions
5. use `po-specify` on a raw feature page to author its structured draft
6. use `po-handoff` when the feature is ready for design

Helpful read/query commands:

- `feature-status` for the full lifecycle board
- `wiki-show F-XXX` for one feature
- `wiki-owner po` for PO-owned open work
- `wiki-blockers` when a feature seems stuck

### If you are a Designer

Typical flow:

1. inspect the feature with `wiki-show F-XXX`
2. attach design artifacts with `design-intake`
3. resolve open design questions with `design-clarify`
4. start work with `design-start` after the PO handoff
5. confirm app implications in the wiki
6. use `design-handoff` when the feature is ready for development

Helpful read/query commands:

- `wiki-owner designer`
- `wiki-app <app-id>`
- `wiki-query "text"` for targeted product context search

### If you are a Developer

Typical flow:

1. read `WIKI_REPORT.md` when present, or run `feature-status`
2. run `prep-sprint` to see what is actually ready
3. use `wiki-show F-XXX` to assemble focused implementation context
4. read app requirements before implementation
5. use `dev-clarify` to answer dev-owned open questions, which block `dev-start`
6. use `dev-start` to take confirmed ready-for-dev work
7. use `dev-done` only when implementation is truly complete and shipped
8. use `feature-reopen` after impact review when shipped work needs revalidation

Helpful read/query commands:

- `wiki-blockers`
- `wiki-app <app-id>`
- `wiki-query "text"`

## Orientation and Read/Query Commands

The current wiki usability layer includes:

- `feature-status`
- `prep-sprint`
- `lint-wiki`
- `wiki-show`
- `wiki-blockers`
- `wiki-query`
- `wiki-owner`
- `wiki-app`

General workflow:

1. Read `WIKI_REPORT.md` first when present.
2. If it is absent, run `feature-status`.
3. Use the read/query commands for focused drill-down.
4. Use the lifecycle commands when you are actually changing project state.

## `feature-status`

Purpose:

- show the full feature pipeline
- refresh `WIKI_REPORT.md`

It is the only command that writes `WIKI_REPORT.md`.

It should produce:

- pipeline grouped by lifecycle stage
- open questions by owner
- blocker snapshot
- `WIKI_REPORT.md` with:
  - project summary
  - lifecycle stage counts
  - advisory review snapshot
  - open questions by owner
  - blocker snapshot
  - recently changed wiki pages
  - structural health pointer to `lint-wiki`
  - suggested next actions

## `prep-sprint`

Purpose:

- give a developer-focused readiness view across the wiki

It is read-only. It should use `WIKI_REPORT.md` when present for fast orientation, then
confirm readiness from the underlying wiki files.

## `lint-wiki`

Purpose:

- inspect the wiki for structural issues and blocker categories

It:

- reports deterministic wiki diagnostics in the response by default
- writes a dated lint report to the wiki directory (`knowledge/wiki/lint-YYYY-MM-DD.md`) only when explicitly requested
- appends to `knowledge/wiki/log.md` only when explicitly requested
- never writes or refreshes `WIKI_REPORT.md`

If `WIKI_REPORT.md` is missing or stale, `lint-wiki` should tell the user to rerun
`feature-status`.

## `wiki-show`

Purpose:

- assemble a focused feature context bundle for one feature

Example:

```text
Feature: F-012 - Saved Checkout
Status: ready-for-dev
Owner: dev
Advisory review: done

Summary:
Customers can reuse a saved shipping address and payment preference during checkout.

Open questions:
- Designer: What does the invalid saved address state look like? [open]
- Dev: Should guest checkout support saved addresses later? [resolved: no, account only]

Linked context:
- Design: knowledge/wiki/design/F-012-saved-checkout.md
- API contract: knowledge/wiki/api-contracts/F-012.md
- Board review: knowledge/wiki/advisory/F-012-review.md
- Business rules:
  - BR-004-checkout-address-validation.md
  - BR-011-payment-method-eligibility.md

App requirements:
- backend: in-progress
- mobile-ios: pending
- mobile-android: pending
- web-user-app: pending

Current blockers:
- api-contract-not-ready: mobile-ios app requirements depend on the API contract status changing from draft to agreed
- missing-design: design page does not define the expired payment-method state

Suggested next action:
Run design-clarify or update the design page before active implementation begins.
```

Missing-feature example:

```text
Feature: F-099
Status: error

Problem:
No feature file matching F-099 was found in knowledge/wiki/features/.

Next step:
Check the feature ID or run feature-status to inspect the current board.
```

Partial-state example:

```text
Feature: F-012 - Saved Checkout
Status: partial
Owner: dev
Advisory review: done

Summary:
Feature file found, but linked implementation context is incomplete.

Missing linked context:
- No design page found
- No app requirements found for mobile-ios

Next step:
Create the missing linked files before treating this feature as fully implementation-ready.
```

## `wiki-blockers`

Purpose:

- compute the current blockers across the wiki using the canonical blocker vocabulary

Canonical blocker categories:

- `pending-board-review`
- `missing-design`
- `missing-app-requirements`
- `unresolved-open-questions`
- `api-contract-not-ready`
- `cross-app-dependency`

Example:

```text
Blockers summary:
- 2 pending board review
- 1 missing design
- 3 missing app requirements
- 2 unresolved open questions

Blocked features:

F-009 - Subscription Pause
- Category: pending-board-review
- Status: ready-for-design
- Why blocked: advisory-review is still pending
- Next step: run board-review F-009 or explicitly skip with a documented reason

F-012 - Saved Checkout
- Category: missing-app-requirements
- Status: ready-for-dev
- Why blocked: no app requirements page exists for mobile-ios
- Next step: generate or write the missing app requirement before implementation continues
```

No-blockers state:

```text
Blockers summary:
- 0 pending board review
- 0 missing design
- 0 missing app requirements
- 0 unresolved open questions

Blocked features:

No current blockers found.
```

Malformed-page example:

```text
Blockers summary:

Problem:
One or more wiki pages are malformed, so blockers could not be computed reliably.

Malformed pages:
- knowledge/wiki/features/F-099-broken.md

Next step:
Repair the malformed pages, then rerun wiki-blockers.
```

## `wiki-query`

Purpose:

- search across the wiki for relevant pages using retrieval-assisted synthesis

It is not a numeric-ranking search engine. It should:

- search the wiki files first
- group candidates by match class
- return a compact typed result set

Example:

```text
Query: offline checkout

Candidate matches:

1. F-012 - Saved Checkout
   Type: feature
   Status: ready-for-dev
   Match class: title/heading match
   Relevant sections:
   - Summary
   - Open questions
   - API surface

2. BR-004 - Checkout Address Validation
   Type: business-rule
   Related feature: F-012
   Match class: body-text match
   Relevant sections:
   - Rule
   - Rationale
```

If the result set is too broad, it should return a refinement prompt instead of pretending
the results are coherent.

No-results example:

```text
Query: offline checkout

No matches found.

Next step:
Try a broader term, a feature ID, or run feature-status to inspect current feature names.
```

Broad-query example:

```text
Query: auth

Too many broad matches to summarize reliably in one response.

Suggested refinement:
- /wiki-query "password auth"
- /wiki-query "OAuth callback"
- /wiki-query "login flow"
```

## `wiki-owner`

Purpose:

- show pending work and open questions for one owner role

Supported values:

- `po`
- `designer`
- `dev`
- `none`

Example:

```text
Owner view: designer

Open questions:
- F-012 - What does the invalid saved address state look like?
- F-014 - What is the empty state for alert history?

Waiting on designer:
- F-012 - Saved Checkout [ready-for-design]
- F-014 - Nutrition Goal Alerts [in-design]

Suggested next actions:
- Run design-intake for F-012
- Resolve open questions on F-014 before design-handoff
```

Invalid-owner example:

```text
Owner view: qa

Problem:
`qa` is not a supported owner value.

Supported values:
- po
- designer
- dev
- none
```

## `wiki-app`

Purpose:

- show the active and ready features affecting one app

Supported identifiers (the app IDs of the workspace; a default generated workspace has these):

- `backend`
- `mobile-android`
- `mobile-ios`
- `web-user-app`
- `web-admin-portal`

Example:

```text
App view: mobile-ios

Active features:

F-012 - Saved Checkout
- Feature status: ready-for-dev
- Advisory review: done
- App requirement: pending
- API contract: agreed
- Blockers:
  - Design does not define expired payment-method handling

F-014 - Nutrition Goal Alerts
- Feature status: in-design
- Advisory review: pending
- App requirement: not created
- API contract: not applicable
- Blockers:
  - Board review still pending
  - No app requirements page yet
```

Invalid-app example:

```text
App view: ios

Problem:
`ios` is not an app of this workspace.

Supported identifiers (the app IDs of the workspace; a default generated workspace has these):
- backend
- mobile-android
- mobile-ios
- web-user-app
- web-admin-portal
```

## Related Docs

- [prism-model.md](prism-model.md)
- [ai-surfaces.md](ai-surfaces.md)
- [wiki-validation.md](wiki-validation.md)
- [generated-projects.md](generated-projects.md)

## CLI result codes

`wiki show` returns exit code 3 when the feature is missing.
`wiki transition-preflight` returns 0 for a supported, ready transition and 3
for blocked or unknown results, in both human and JSON modes. Empty searches
remain successful with exit code 0. These commands only inspect state.
