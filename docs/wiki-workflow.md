# Wiki Workflow

This page explains how the generated-project product wiki works, how the read/query layer
fits into it, and how to interpret `WIKI_REPORT.md`.

## Core Idea

The wiki is the shared source of truth for product intent in generated Prism projects.

The important directories are:

- `knowledge/wiki/features/`
- `knowledge/wiki/design/`
- `knowledge/wiki/platform-requirements/`
- `knowledge/wiki/business-rules/`
- `knowledge/wiki/api-contracts/`
- `knowledge/wiki/advisory/`

The lifecycle operations create and refine that state. The read/query operations help
agents and humans navigate it.

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

If `WIKI_REPORT.md` disagrees with the underlying wiki files, the wiki files win.

## `SETTINGS.md`

`knowledge/wiki/SETTINGS.md` is the canonical home for project-level wiki behavior
settings.

Current shipped setting:

```markdown
---
wiki-stale-after-days: 14
---

# Wiki Settings

Project-level settings for wiki read/query behavior.
```

Commands that use this setting must fall back cleanly to `14` if the file is missing, the
key is missing, or the value is malformed.

## Orientation and Read/Query Commands

The current wiki usability layer includes:

- `feature-status`
- `prep-sprint`
- `lint-wiki`
- `wiki-show`
- `wiki-blockers`
- `wiki-query`
- `wiki-owner`
- `wiki-platform`

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
  - recently updated wiki pages
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

- writes a dated lint report to the wiki directory (`knowledge/wiki/lint-YYYY-MM-DD.md`)
- appends to `knowledge/wiki/log.md`
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

Platform requirements:
- backend: in-progress
- mobile-ios: pending
- mobile-android: pending
- web-user-app: pending

Current blockers:
- api-contract-not-ready: mobile-ios platform requirements depend on the API contract status changing from draft to agreed
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
- No platform requirements found for mobile-ios

Next step:
Create the missing linked files before treating this feature as fully implementation-ready.
```

## `wiki-blockers`

Purpose:

- compute the current blockers across the wiki using the canonical blocker vocabulary

Canonical blocker categories:

- `pending-board-review`
- `missing-design`
- `missing-platform-requirements`
- `unresolved-open-questions`
- `api-contract-not-ready`
- `cross-platform-dependency`

Example:

```text
Blockers summary:
- 2 pending board review
- 1 missing design
- 3 missing platform requirements
- 2 unresolved open questions

Blocked features:

F-009 - Subscription Pause
- Category: pending-board-review
- Status: ready-for-design
- Why blocked: advisory-review is still pending
- Next step: run board-review F-009 or explicitly skip with a documented reason

F-012 - Saved Checkout
- Category: missing-platform-requirements
- Status: ready-for-dev
- Why blocked: no platform requirements page exists for mobile-ios
- Next step: generate or write the missing platform requirement before implementation continues
```

No-blockers state:

```text
Blockers summary:
- 0 pending board review
- 0 missing design
- 0 missing platform requirements
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

Example:

```text
Owner view: designer

Open questions:
- F-012 - What does the invalid saved address state look like?
- F-014 - What is the empty state for alert history?

Waiting on designer:
- F-012 - Saved Checkout [ready-for-design]
- F-014 - Nutrition Goal Alerts [in-design]

Potentially stale:
- F-011 - Account Merge Flow [ready-for-design, last updated 18 days ago]

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
```

## `wiki-platform`

Purpose:

- show the active and ready features affecting one platform

Supported identifiers:

- `backend`
- `mobile-android`
- `mobile-ios`
- `web-user-app`
- `web-admin-portal`

Example:

```text
Platform view: mobile-ios

Active features:

F-012 - Saved Checkout
- Feature status: ready-for-dev
- Advisory review: done
- Platform requirement: pending
- API contract: agreed
- Blockers:
  - Design does not define expired payment-method handling

F-014 - Nutrition Goal Alerts
- Feature status: in-design
- Advisory review: pending
- Platform requirement: not created
- API contract: not applicable
- Blockers:
  - Board review still pending
  - No platform requirements page yet
```

Invalid-platform example:

```text
Platform view: ios

Problem:
`ios` is not a valid platform identifier for Prism.

Supported identifiers:
- backend
- mobile-android
- mobile-ios
- web-user-app
- web-admin-portal
```

## Source-of-Truth Boundary

The most important rule is simple:

- the wiki files are the source of truth
- `WIKI_REPORT.md` is only an orientation layer
- read/query commands assemble context, but they do not replace the underlying files

## Related Docs

- [prism-model.md](prism-model.md)
- [ai-surfaces.md](ai-surfaces.md)
- [wiki-validation.md](wiki-validation.md)
- [generated-projects.md](generated-projects.md)
