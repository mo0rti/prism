# Feature page format

Use this format for every file in `wiki/features/`. Filename: `F-XXX-[slug].md`.

```markdown
---
id: F-XXX
title: [Feature name]
status: raw | specified | ready-for-design | in-design | ready-for-dev | in-dev | done
owner: po | designer | dev | none
introduced: YYYY-MM-DD
last-updated: YYYY-MM-DD
platforms: [list of platforms this feature affects]
sources: [paths to intake/processed/ items that produced this page]
advisory-review: not-needed | pending | done | skipped
---

## Summary
One paragraph. What this feature does, why it exists, and what user problem it solves.
Written in business language, not technical language.

## User story
As a [persona from personas/], I want to [action], so that [business outcome].

## Acceptance criteria
- [ ] Condition 1 (testable, unambiguous)
- [ ] Condition 2

## Open questions
| # | Question | Owner | Status |
|---|----------|-------|--------|
| 1 | What is the fallback when the user is offline? | po | open |

Owner must be one of: po | designer | dev
Status must be one of: open | resolved: [answer]

## Platform scope
- **backend**: [what backend must implement, or "not in scope"]
- **mobile-android**: [what Android must implement, or "not in scope"]
- **mobile-ios**: [what iOS must implement, or "not in scope"]
- **web-user-app**: [what user web app must implement, or "not in scope"]
- **web-admin-portal**: [what admin portal must implement, or "not in scope"]

Only list platforms included in this generated project.

## Design
Link to design artifacts. Empty until /design-intake is run.

## Related features
- [F-XXX](features/F-XXX-[slug].md) — [why this relationship exists]

## API surface
High-level description of API changes required. Empty if no API changes.

## Board review summary
Populated by /board-review. Empty until then.

## Post-ship notes
Populated by /dev-done. Empty until then.
```
