---
name: board-review
description: Run a structured domain expert review of a feature using the advisory board defined in knowledge/wiki/advisory/BOARD.md. Use for features with domain-specific calculations, behavioral implications, vulnerable user groups, or cultural assumptions. Not for auth flows, settings, CRUD, or infrastructure changes.
---

# Board Review

Use this skill to review a feature through domain expert lenses before development starts.

## Workflow

1. Read `knowledge/wiki/advisory/BOARD.md` in full — load the board composition and each
   member's typical questions.
2. Read `knowledge/wiki/SCHEMA.md` for the pre-dev review output format.
3. Read `knowledge/wiki/features/[F-XXX]-[slug].md` in full.
4. Read `knowledge/wiki/personas/` to understand who uses this feature.
5. Read `knowledge/wiki/business-rules/` for relevant constraints.
6. Read `knowledge/wiki/decisions/` for architectural constraints.
7. Read related feature pages and any existing board reviews for context.
8. For each board member with relevant domain concerns, apply their expertise lens:
   - Use their "typical questions" as the primary lens
   - Identify concerns, edge cases, and failure modes specific to their domain
   - Only include members with substantive concerns — omit members with nothing to add
9. Identify where board members disagree — make debates explicit.
10. Generate the review file at `knowledge/wiki/advisory/[F-XXX]-review.md` using the
    four-question format from SCHEMA.md: Conflicts, Gaps, Build order, Biggest risk.
11. For each required action: add an open question to the feature file tagged "[Board: Name]".
12. Propose any new business rules implied by the review; confirm before writing.
13. Set the feature's `advisory-review` field to `done`.
14. Update `knowledge/wiki/index.md` and append to `knowledge/wiki/log.md`.

## Output format

```markdown
---
feature-id: F-XXX
reviewed: YYYY-MM-DD
board-members-consulted: [names]
---

## 1. Conflicts
Named conflicts only. Reference specific feature IDs, ADR IDs, or business rule IDs.
If none: "No conflicts identified."

## 2. Gaps
Missing information that will block development. If none: "Spec is complete."

## 3. Build order
Cross-platform dependency sequencing. If none: "No cross-platform ordering constraints."

## 4. Biggest risk
One sentence. Most likely cause of failure, user harm, or delay.

## Board perspective summaries
[One paragraph per member with substantive concerns.]

## Actions required before dev starts
- [ ] [Action with owner: po / designer / dev]

## Actions that can be deferred
- [Action acceptable to address post-ship]
```

## Notes

- Specificity is the entire value of this review. Name the board member and domain
  context for every concern. Generic concerns ("consider security") are useless.
- A review that finds no concerns is valid. Do not invent concerns.
- The review is an intelligence input, not a governance gate.
