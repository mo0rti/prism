# Wiki owner - role dashboard for one owner value

## Usage
/wiki-owner po|designer|dev

## Purpose

Show pending work and open questions for one owner role.

## Read-only rules

- read-only command
- do not write any wiki files
- do not refresh `WIKI_REPORT.md`
- if `WIKI_REPORT.md` is missing, tell the user to run `/feature-status` for an updated orientation summary

## Files to read

- `knowledge/wiki/SETTINGS.md` if present
- all files in `knowledge/wiki/features/`
- all files in `knowledge/wiki/platform-requirements/`
- optionally `knowledge/wiki/index.md` for lifecycle grouping confirmation

## Invocation rules

- `wiki-owner` is an explicitly invoked role view
- do not attempt to infer the caller's role automatically
- supported owner values are exactly:
  - `po`
  - `designer`
  - `dev`

## Detection rules

- Collect open questions assigned to the selected owner
- Collect features whose current `owner` frontmatter matches the selected owner
- Collect features likely waiting on the selected owner:
  - `po`: PO-owned open questions or intake conflicts needing clarification
  - `designer`: features in `ready-for-design` or `in-design`, plus design-owned open questions
  - `dev`: features in `ready-for-dev` or `in-dev`, plus dev-owned open questions
- Mark an item as stale using `wiki-stale-after-days` from `knowledge/wiki/SETTINGS.md`
- If `SETTINGS.md` is absent, the key is absent, or the value is malformed, fall back to
  `wiki-stale-after-days: 14`
- If the settings value is malformed, report that it is invalid and that the default fallback
  is being used

## Recommended output shape

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

## Partial/error-state examples

```text
Owner view: designer

No current work found.

Notes:
- No open questions are assigned to designer.
- No features are currently owned by designer.
```

```text
Owner view: qa

Problem:
`qa` is not a supported owner value.

Supported values:
- po
- designer
- dev
```
