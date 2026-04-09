# Wiki platform - platform-specific feature queue

## Usage
/wiki-platform backend|mobile-android|mobile-ios|web-user-app|web-admin-portal

## Purpose

Show all active and ready features affecting one platform.

## Read-only rules

- read-only command
- do not write any wiki files
- do not refresh `WIKI_REPORT.md`
- if `WIKI_REPORT.md` is missing, tell the user to run `/feature-status` for an updated orientation summary

## Files to read

- all files in `knowledge/wiki/features/`
- all files in `knowledge/wiki/platform-requirements/`
- all files in `knowledge/wiki/design/`
- all files in `knowledge/wiki/api-contracts/`
- all files in `knowledge/wiki/advisory/` except `BOARD.md`

## Platform rules

- the required platform identifier must use one of the exact Prism platform IDs:
  - `backend`
  - `mobile-android`
  - `mobile-ios`
  - `web-user-app`
  - `web-admin-portal`
- do not infer aliases such as `ios`, `android`, or `web`

## Inclusion rules

- include any feature whose `platforms` frontmatter contains the selected platform
- include features in:
  - `ready-for-design`
  - `in-design`
  - `ready-for-dev`
  - `in-dev`
  - optionally `done` in a separate closed section
- attach the matching platform-requirement file if it exists
- compute blockers relevant to that platform from missing design, missing platform requirements,
  advisory review state, and API contract readiness

## Recommended sort order

- `in-dev`
- `ready-for-dev`
- `in-design`
- `ready-for-design`
- then `done` if included

## Recommended output shape

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

Done recently:
- F-007 - Profile Edit
```

## Partial/error-state examples

```text
Platform view: mobile-ios

No active or ready features currently target this platform.
```

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
