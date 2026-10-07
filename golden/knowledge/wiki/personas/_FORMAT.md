# Persona page format

Use this format for every file in `wiki/personas/`. Filename: `[slug].md`.

```markdown
---
id: P-XXX
name: [Persona name, e.g. "Restaurant Manager"]
sources: [intake sources that established this persona]
---

## Who they are
A paragraph describing this type of user: their role, context, and relationship to the product.
- **Observed:** [what the intake shows about this user type] ([source](../../intake/processed/YYYY-MM-DD-slug/notes.md))
- **Assumed:** [what is taken as true without evidence]

## Goals
What they are trying to accomplish. Bulleted list.

## Pain points
What currently frustrates them or slows them down. Label each one **Observed** (with its
link) or **Assumed**.

## Features that serve this persona
Links to feature IDs tagged for this persona.
```
