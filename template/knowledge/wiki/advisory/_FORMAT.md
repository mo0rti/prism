# Pre-dev review format

Use this format for board review output files in `wiki/advisory/`. Filename: `F-XXX-review.md`.

This is intentionally short — one page maximum. The purpose is to give the team something
they can read together in 15 minutes and act on.

```markdown
---
feature-id: F-XXX
reviewed: YYYY-MM-DD
board-members-consulted: [list of board member names from BOARD.md]
---

## 1. Conflicts
Does this feature conflict with anything already built or decided?
Named conflicts only — reference specific feature IDs, ADR IDs, or business rule IDs.
If none: "No conflicts identified."

## 2. Gaps
Is there anything missing from the current spec that will block development before it starts?
If none: "Spec is complete."

## 3. Build order
Across platforms, what must be built first?
If no dependencies: "No cross-platform ordering constraints."

## 4. Biggest risk
One sentence. What is most likely to cause this feature to fail, cause user harm, or
take significantly longer than expected?

## Board perspective summaries
[One short paragraph per board member who has a relevant concern.]
[Only include members with something substantive to say.]

## Actions required before dev starts
- [ ] [Specific action with owner — po / designer / dev]

## Actions that can be deferred
- [Action that can be addressed post-ship with acceptable risk]
```
