# Design page format

Use this format for every file in `wiki/design/`. Filename: `F-XXX-[slug].md`.

```markdown
---
feature-id: F-XXX
title: [Design title]
designer: [name, optional]
date: YYYY-MM-DD
figma: [Figma URL or "not applicable"]
---

## Summary
What this design covers and what decisions were made.

## Key design decisions
Decisions that affect implementation (not just aesthetics).
Example: "The confirmation dialog is modal and blocks all interaction — not a toast."

## States covered
List all UI states designed: empty, loading, error, success, edge cases.
Flag any states NOT designed that the developer will need to handle.

## Component references
Links to relevant entries in design/ for reused components or patterns.

## Open design questions
Questions for the Designer that affect implementation.
```
