# Wiki blockers - project-level blockers view

## Usage
/wiki-blockers

## Purpose

Show what is preventing features from progressing.

## Read-only rules

- read-only command
- do not write any wiki files
- do not refresh `WIKI_REPORT.md`
- if `WIKI_REPORT.md` is missing, tell the user to run `/feature-status` for an updated orientation summary

## Files to read

- `knowledge/wiki/index.md`
- all files in `knowledge/wiki/features/`
- all files in `knowledge/wiki/design/`
- all files in `knowledge/wiki/platform-requirements/`
- all files in `knowledge/wiki/api-contracts/`
- all files in `knowledge/wiki/advisory/` except `BOARD.md`

## Canonical blocker categories

- `pending-board-review`
- `missing-design`
- `missing-platform-requirements`
- `unresolved-open-questions`
- `api-contract-not-ready`
- `cross-platform-dependency`

## Detection rules

- `pending-board-review`
  Any feature with `advisory-review: pending` that is at `ready-for-design`, `in-design`,
  `ready-for-dev`, or `in-dev`
- `missing-design`
  Any feature in `ready-for-dev` or `in-design` with no matching design page when the
  feature affects a UI platform
- `missing-platform-requirements`
  Any feature in `ready-for-dev` or `in-dev` that is missing one or more platform
  requirement files for platforms listed in the feature frontmatter
- `unresolved-open-questions`
  Any feature in `ready-for-dev` or `in-dev` with open questions still assigned to `po`,
  `designer`, or `dev`
- `api-contract-not-ready`
  Any feature that depends on an API contract file still marked `draft` when downstream
  platforms are already `ready-for-dev` or `in-dev`
- `cross-platform-dependency`
  Any platform-requirement page whose `Dependencies` section points to unfinished feature
  IDs or unfinished platform-requirement pages

## Recommended output shape

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

## Partial/error-state examples

```text
Blockers summary:
- 0 pending board review
- 0 missing design
- 0 missing platform requirements
- 0 unresolved open questions

Blocked features:

No current blockers found.
```

```text
Blockers summary:

Problem:
One or more wiki pages are malformed, so blockers could not be computed reliably.

Malformed pages:
- knowledge/wiki/features/F-099-broken.md

Next step:
Repair the malformed pages, then rerun /wiki-blockers.
```
