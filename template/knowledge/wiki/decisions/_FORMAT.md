# Architecture Decision Record (ADR) format

Use this format for every file in `wiki/decisions/`. Filename: `ADR-XXX-[slug].md`.

```markdown
---
id: ADR-XXX
title: [Decision title]
date: YYYY-MM-DD
status: proposed | accepted | deprecated | superseded
# Only on an ADR that replaces an earlier decision:
supersedes: ADR-NNN
# Only on an ADR that a later decision replaced (its status is `superseded`):
superseded-by: ADR-MMM
---

## Context
What situation forced this decision.

## Decision
What we decided.

## Rationale
Why this option over alternatives.

## Consequences
What becomes easier, what becomes harder.
```

An ADR is a dated record (see Records and decision supersession in `SCHEMA.md`). It is never rewritten;
only its status fields change.

## Superseding a decision

A decision is superseded by a new ADR, in one operation (the decision-supersession
workflow in `SCHEMA.md`):

1. The new ADR has `supersedes: ADR-NNN`.
2. The old ADR gets `status: superseded` and `superseded-by: ADR-MMM`. Its body stays
   unchanged.
3. Every current-state page that relied on the old decision is updated to state the
   current decision and link the new ADR.

`prism wiki lint` reports `supersession-mismatch` (error) when the two links disagree or
one is missing, and `superseded-decision-cited` (warning) when a current-state page links
a superseded ADR.
