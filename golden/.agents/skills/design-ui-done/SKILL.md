---
name: design-ui-done
description: Settle the UI track of a feature in design. Use when the designer's design pages cover every app with a UI, or when the designer exempts the UI track with a reason, without handing the feature to development.
---

# Design UI done - settle the UI track of one feature

<!-- prism:design-ui-done-contract:v1 -->

Use this skill when the visual design of a feature is complete, or when the feature needs none. It
sets one track, `ui`, in the feature's `design-tracks`. It does not hand the feature to development:
`$design-handoff` does that once both tracks are settled.

## Usage

`$design-ui-done [F-XXX]`

## Supported action

`ready-for-design` or `in-design` + the design owner -> `in-design` + the design owner (`designer`
while an active app in scope has a UI, otherwise `tech-lead`)

Resolve exactly one `knowledge/wiki/features/[F-XXX]-[slug].md` source file. A missing, invalid,
ambiguous, or different source pair is a stop condition, and so is a feature that lists a retired
app (`app-retired-in-scope`). From `ready-for-design` this action also starts design and writes the
initial `design-tracks`. A connected board approves it only for a participant who holds the
`designer` role.

The action is open only while the UI track is `pending`, absent, or listed in `design-reaffirm`. A
track that is `done` or `not-applicable` is changed with `$design-clarify`, which sets it
back to `pending` when it changes a design page.

## Read-only preflight

When available, use:

```text
prism wiki transition-preflight F-XXX [path] --action design-ui-done --json
```

Accept it only with common envelope schema 1, command facts, capability version 3 and an
action-specific `design-ui-done` surface, transition version 2, target owner the design owner, and a
consistent snapshot. The Prism version alone does not prove support. If any required fact, schema,
action, capability, or snapshot is missing or fails, fall back to direct-file checks. The preflight
is copy-only and never authorizes a write.

## The track

Read `knowledge/wiki/SCHEMA.md`, `knowledge/wiki/LIFECYCLE.md`, `status-board.md`, the complete
feature, its design pages, linked context, the apps in `prism.workspace.yml` and their `has-ui`
capability (`unknown` counts as a UI), and the active `revalidation` domains.

- **`done`**: design pages in `knowledge/wiki/design/` whose `apps` together cover every active app of
  the feature with `has-ui` true or unknown (`design-coverage-incomplete` otherwise). The designer
  ensures the pages cover every UI state the acceptance criteria imply.
- **`not-applicable`**: a non-blank `ui-reason` that says why the feature needs no visual design
  (`ui-exemption-reason-required` otherwise). An app with `has-ui: unknown` is exempted only by this
  explicit reason. When no active app has a UI, the first design action already writes the track as
  `not-applicable` with the reason `No app in scope has a UI.`
- **Open questions**: an open question owned by `designer` blocks the action. Resolve it with
  `$design-clarify` first. An active `specification` domain in `revalidation` blocks it too.

## Writes

Show the observed fields, the proposed destination and every write, then wait for confirmation.

- Feature front matter: `design-tracks.ui` set to `done`, or to `not-applicable` with `ui-reason`
  (the other track and its reason stay as they are), `design-reaffirm`, and, from `ready-for-design`,
  `status: in-design`. When `design-tracks` is absent, write both keys together:
  `technical: pending` and `ui` as the action sets it, `design-reaffirm: []`.
- `design-reaffirm`: remove `ui` from it. When this action changes a design page of a track that was
  `done`, add `technical` to it if the technical track is `done`, because the other track is
  reaffirmed after a change. A run with no page change only removes the entry.
- Design pages: `knowledge/wiki/design/F-XXX-[slug].md` with the front matter `feature-id`, `title`,
  `apps` (the apps the page designs) and `figma` (a URL or `not applicable`), and the sections
  `## Summary`, `## Key design decisions`, `## States covered`, `## Component references` and
  `## Open design questions` (format in `knowledge/wiki/design/_FORMAT.md`).
- The feature's `## Design` section: link the design pages. No other section changes.
- The feature's row in `status-board.md`, the `index.md` line of each design page you write, and a
  `log.md` entry in the log format that the wiki schema defines.

Reread the source and context immediately before confirmation and once again after it. The
preflight and any copied request are copy-only and never authorize a write. Decline or cancel means
no write. If a multi-file write is partial, report the exact observed state and require fresh
recovery; no transaction is implied.

## Rules

- write-capable skill
- sets the `ui` track only: another track's keys, state, reason and pages stay unchanged (`track_scope`)
- never settle a track with a design page that does not cover the apps with a UI
- write current-state pages: replace superseded content in place, state rationale as a current fact and keep history in `log.md` and the records; mark each claim `**Decided:**`, `**Observed:**`, `**Proposed:**` or `**Assumed:**` (gaps stay in the Open questions table) and link the evidence of every Decided and Observed claim: the processed intake item, a record or a URL (see Evidence labels in the wiki schema)

## Output behavior

Return:

- the observed track state and the proposed one
- the apps with a UI and the design pages that cover them, or the exemption reason
- the proposed `design-reaffirm`
- the pages and files the action writes, after confirmation

## Error and stop conditions

- if the feature file does not exist or its source pair is not supported, return a clean stop
- if the UI track is not open, or a prerequisite is unmet, list it and stop without writing
- if the user does not confirm, stop without writing
