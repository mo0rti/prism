# Plan page format

Use this format for every file in `wiki/plans/`. Filename: `[slug].md`, with lowercase words
joined by hyphens, such as `payments-migration.md`.

A plan page holds the current status of one plan: what it is for, where it stands now, what
comes next and what blocks it. It does not keep the plan's history: finished steps leave the
page, and `log.md` records when they happened.

```markdown
---
kind: plan
title: [Plan title]
status: proposed | active | paused | done | dropped
sources: [processed intake items, records or URLs the plan rests on]
---

## Summary
One paragraph on what the plan is and where it stands. Its first sentence is the page's line
in `index.md`, so write it in the present tense.

## Goal
What the plan achieves and how anyone can tell it is achieved.
- **Decided:** [the goal as confirmed] ([source](../../intake/processed/YYYY-MM-DD-slug/notes.md))

## Current status
Where the plan stands now, in present-tense statements.
- **Observed:** [what a source or a running system shows] ([source](../../intake/processed/YYYY-MM-DD-slug/notes.md))

## Next steps
- **Proposed:** [the next step and who takes it]

## Blockers
- **Unknown:** [what is not yet answered]. If nothing blocks the plan, write "No blockers."
```

- `proposed` is a plan nobody has accepted, `active` a plan under way, `paused` a plan on
  hold, `done` a plan that reached its goal and `dropped` a plan that was abandoned.
- When the status of the plan changes, replace the affected lines in place. A date for the
  world, such as a deadline or an external launch date, may appear in the body; a date for
  the page itself never does.
- A plan that depends on a decision links the ADR; a plan that delivers features links their
  feature pages.
