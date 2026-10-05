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
# Required and non-blank when advisory-review is skipped:
advisory-skip-reason: [reason]
# Optional only when the user explicitly confirms that UI design is not applicable:
design: not-applicable
design-exemption-reason: [non-blank reason]
# Omit or use [] until a confirmed reopen marks domains for fresh evidence:
revalidation: [specification | design | implementation | tests | release]
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

For UI work, `design: not-applicable` and a nonblank
`design-exemption-reason` are allowed only when the user explicitly confirms
that the visual design is not applicable. Ordinary non-UI features omit both
fields.

## Design
Link to design artifacts. Empty until /design-intake is run.

## Related features
- [F-XXX](F-XXX-[slug].md) - [why this relationship exists]

## API surface
High-level description of API changes required. Empty if no API changes.

## Board review summary
Populated by /board-review. Empty until then.

## Post-ship notes
Populated by /dev-done. Empty until then. Record a delivery reference the agent could
not check as the developer's attestation.

## Delivery evidence
| Platform | Implementation | Tests | Release |
|---|---|---|---|
| [declared platform] | [verified artifact or source reference] | [test command and result] | [release artifact or target] |

Include exactly one substantive row per declared platform in the `dev-done`
proposal; the developer supplies the references.
Agents must verify the referenced artifacts and results; file presence or lint
alone is not shipment evidence. Partial delivery stays `in-dev`.

## Reopen history
Append-only records for confirmed reopen actions. Archive the prior active
Delivery evidence here and remove it from the active table on confirmation.

### YYYY-MM-DD - reopen-[spec|design|dev]
- Reason: [why the feature was reopened]
- Impact review: [what changed and what was assessed]
- Affected platforms: [declared platform IDs]
- Affected artifacts: [paths or named artifacts]
- Prior completion/release evidence: [archived evidence]
- Requirement/API invalidations: [exact affected pages and proposed statuses]
```

## Raw and specified pages

`/po-intake` creates every new feature as `status: raw`, `owner: po`. Its page has
substantive Summary, User story, Acceptance criteria, Open questions and Platform
scope sections; Design, Related features, API surface, Board review summary and
Post-ship notes stay empty. `/po-specify` completes the page and sets
`status: specified`: each of those five sections gets one line of supported content
or an explicit statement that nothing exists yet (`Not started.`, `None identified.`,
`None.` under API surface, `Not reviewed yet.`, `Not shipped yet.`). API surface text
other than `None.` declares API work and needs an API contract page before
`/dev-start`, so write `None.` unless the intake material or an answered question
states an API change. Keep open questions in the Open questions table, never in these
sections. A later action replaces that line with its real content.

## Reopen record layout

Each reopen record has one `###` heading and the six bullets above, with the label
text unchanged. Under `- Prior completion/release evidence:` keep every prior
Delivery evidence row verbatim, one row per declared platform, in the same
`| Platform | Implementation | Tests | Release |` cell order. Put the rows on that
line, or on the lines directly below it as a table or a list, indented or not.
They must come before the next `- Label:` bullet or heading. Rows after the next
bullet or under another heading are not found, and the connected board rejects the
record with `delivery_evidence_not_archived` and the first missing row. Letter case
and spaces around `|` do not matter; the cell text does.

```markdown
- Prior completion/release evidence: Archived unchanged from the active table.

  | Platform | Implementation | Tests | Release |
  |---|---|---|---|
  | backend | PR #42 merged as 3f9c2ab | CI run 1187: 31 passed | v1.4.0 deployed |
- Requirement/API invalidations: knowledge/wiki/platform-requirements/F-001-backend.md: done -> in-progress
```

Under `- Requirement/API invalidations:` write each invalidated requirement or API page as
its full relative path, a colon, its current status, `->` and its new status, and name
the same path under `- Affected artifacts:`. When no page is invalidated, write a
sentence such as `No requirement or API page is invalidated.`; a bare `None` is too short
and the connected board rejects it with `impact_review_required`.
