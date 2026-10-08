# App requirements page format

Use this format for every file in `wiki/app-requirements/`. Filename: `F-XXX-[app-id].md`.

```markdown
---
feature-id: F-XXX
app: [an app ID from the feature's `apps` list]
status: pending | in-progress | done
---

## What to build
Specific, actionable description of what this app must implement.
Written for the AI agent working in this app's code.

## Technical constraints
App-specific constraints, existing patterns to follow, library choices.
- **Observed:** [an existing pattern or constraint] ([source](../../intake/processed/YYYY-MM-DD-slug/notes.md))
- **Assumed:** [what is taken as true without evidence]

## Design reference
Link to design/F-XXX-[slug].md for an app with a UI. Not applicable to an app without a UI.

## API contract reference
Link to api-contracts/F-XXX.md. List endpoints or data shapes this app consumes/produces.

## Acceptance criteria
App-specific done conditions.

## Dependencies
Other feature IDs or app-requirement files that must complete first, or `None.`
Open questions never go here; they stay in the feature's Open questions table.
```

`ACTIONS.md` and `LIFECYCLE.md` (Delivery and revalidation) define how the lifecycle actions create,
invalidate and complete these pages.
