# Design page format

Use this format for every file in `wiki/design/`. Filename: `F-XXX-[slug].md`.

```markdown
---
feature-id: F-XXX
title: [Design title]
apps: [the apps of the feature this design covers, each with a UI]
figma: [Figma URL or "not applicable"]
---

## Summary
What this design covers and what decisions were made.

## Key design decisions
Decisions that affect implementation (not just aesthetics).
Example: "The confirmation dialog is modal and blocks all interaction, not a toast."
- **Decided:** [a decision that affects implementation] ([source](../../intake/processed/YYYY-MM-DD-slug/notes.md))

## States covered
List all UI states designed: empty, loading, error, success, edge cases.
Flag any states NOT designed that the developer will need to handle.

## Component references
Links to relevant entries in design/ for reused components or patterns.

## Open design questions
Questions for the Designer that affect implementation. This section is the Unknown form of
the evidence labels.
```

## Rules

- `apps` lists the apps of the feature that this page designs. Together the feature's design pages cover
  every active app with a UI (`has-ui` true or `unknown`, which counts as a UI); `design-coverage-incomplete`
  names the apps no page covers. A page does not carry a designer's name.
- Design pages belong to the `ui` design track of the feature. `design-ui-done` writes them and settles the
  track, or `design-handoff` does when it settles the track. They are writable while the feature is
  `ready-for-design` or `in-design` and locked from `ready-for-dev` on. Changing a page while the track is
  settled sets the track back to `pending` in the same write, and the technical track joins `design-reaffirm`
  when it is `done`.
