# Advisory file formats

`wiki/advisory/` contains:

- `BOARD.md` - the active advisory board definition
- `PROJECT_FOUNDATION.md` - setup-project interview answers, risk framing, and board rationale
- `F-XXX-review.md` - board review output for one feature

## PROJECT_FOUNDATION.md

Use this format for the setup-project foundation artifact:

```markdown
# Project Foundation

Initialized by `setup-project` on YYYY-MM-DD for [Project Name].

## Project identity
- Name: [project name]
- Description: [one-sentence summary]
- Platforms: [backend, web-user-app, ...]
- Auth methods: [if known]
- Infrastructure choices: [if known]
- Important correction or note: [optional]

## Setup interview

### 1. Primary users and trust
**Question:** Who are your primary users, and what do they trust this app to get right?
**Answer:** [confirmed answer]

### 2. Core decision or calculation
**Question:** What is the most important decision or calculation this app makes on behalf of users?
**Answer:** [confirmed answer]

### 3. Failure consequences
**Question:** What could go wrong if the app gets that wrong?
**Answer:** [confirmed answer]

### 4. Vulnerable groups
**Question:** Are there any user groups who might be especially vulnerable to a mistake?
**Answer:** [confirmed answer]

## Risk summary
- Core trust surface: [bullets]
- Primary failure modes: [bullets]
- Business impact: [bullets]
- Vulnerable groups: [bullets]
- Expertise gaps: [bullets]

## Why this board
Short paragraph explaining why the selected advisory board composition fits the
project's domain risks.

## Seed artifacts from setup
- [BOARD.md](BOARD.md)
- [persona or rule links created during setup]
```

## F-XXX-review.md

Use this format for board review output files in `wiki/advisory/`. Filename: `F-XXX-review.md`.

This is intentionally short, one page maximum. The purpose is to give the team something
they can read together in 15 minutes and act on.

```markdown
---
feature-id: F-XXX
reviewed: YYYY-MM-DD
board-members-consulted: [list of board member names from BOARD.md]
---

## 1. Conflicts
Does this feature conflict with anything already built or decided?
Named conflicts only. Reference specific feature IDs, ADR IDs, or business rule IDs.
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
- [ ] [Specific action with owner - po / designer / dev]

## Actions that can be deferred
- [Action that can be addressed post-ship with acceptable risk]
```
