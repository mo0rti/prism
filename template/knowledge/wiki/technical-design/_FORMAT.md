# Technical design page format

Use this format for every file in `wiki/technical-design/`. Filename: `F-XXX-[slug].md`, named for
the feature it designs (`technical-design-feature-mismatch`). A feature has one technical design page. It is a current-state page: it
states what the technical design is now, and history lives in `log.md` and the decisions.

```markdown
---
feature-id: F-XXX
title: [Technical design title]
apps: [every app of the feature]
decisions: [ADR-001]
---

## Summary
What the technical design achieves and how, in two or three sentences.

## Architecture impact
| App | Modules | Change |
|---|---|---|
| backend | reviews, exports | A new export service behind the reviews module |
| web | review panel | A download action that calls the export endpoint |

## Data model and migrations
Tables, fields and the migrations the feature needs, or why none are needed.

## Security and privacy
Who may do what, which data is personal, how it is protected.

## Non-functional requirements
Performance, availability, limits and other qualities the implementation must meet.

## Risks
What could go wrong and how the design contains it.

## Decisions
- **Decided:** [a technical decision] ([ADR-001](../decisions/ADR-001-slug.md))

## API contract
Link to [the API contract](../api-contracts/F-XXX.md), or say that the feature has no API work.

## Test strategy
| Criterion | Applies to | Method | Level | Notes |
|---|---|---|---|---|
| AC-1 | backend | automated | integration | The export is created for the signed-in reviewer |
| AC-2 | web | manual | end-to-end | |
```

## Rules

- `apps` names every app of the feature. The Architecture impact table has a row for every app: the
  app, the modules it changes and the change (`technical-design-incomplete`).
- Every section has content of its own; a bare placeholder is rejected (`technical-design-incomplete`). A section with nothing to
  say states why, for example `No migration is needed.`
- The Test strategy names **every** acceptance criterion ID of the feature, one row per criterion
  (more rows for one criterion are fine). `Applies to` lists apps of the feature, `Method` is
  `automated`, `manual` or `exploratory`, `Level` is the kind of test (unit, integration,
  end-to-end, ...). QA verifies against this table. A criterion the feature does not have is rejected (`test-strategy-incomplete`).
- Mark each claim `**Decided:**`, `**Observed:**`, `**Proposed:**` or `**Assumed:**` and link the
  evidence of every Decided and Observed claim, as the wiki schema's Evidence labels say.
- `decisions` lists the ADR IDs the design rests on, or `[]`.
- The index line of a technical design page is its title and the first sentence of its Summary.
- The page belongs to the `technical` design track of the feature. `@@invoke:tech-design-done@@` writes it
  and settles the track. It is writable while the feature is `ready-for-design` or `in-design` and
  locked from `ready-for-dev` on. Changing it while the track is `done` sets the track back to `pending`
  in the same write, and the UI track joins `design-reaffirm` when it is `done`.
- The API contract of the feature, `api-contracts/F-XXX.md`, belongs to the same track.
