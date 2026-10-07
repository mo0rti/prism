# Research page format

Use this format for every file in `wiki/research/`. Filename: `[slug].md`, with lowercase
words joined by hyphens, such as `offline-sync-options.md`.

A research page answers one question from the sources gathered for it: a comparison, a
feasibility check, a market or technology survey. The page holds the current answer and the
gaps that remain, not the story of how the research went.

```markdown
---
kind: research
title: [Research title]
status: open | concluded
sources: [processed intake items, records or URLs the findings rest on]
---

## Question
The one question this page answers.

## Summary
One paragraph with the current answer. Its first sentence is the page's line in
`index.md`, so write it in the present tense.

## Findings
- **Observed:** [what a source shows] ([source](../../intake/processed/YYYY-MM-DD-slug/notes.md))
- **Proposed:** [a recommendation nobody has confirmed yet]
- **Assumed:** [what is taken as true without evidence]

## Gaps
- **Unknown:** [what the sources do not answer]
```

- `status: open` marks a question that new sources can still change; `concluded` marks one
  whose answer is settled. A conclusion that drives a decision is recorded as an ADR in
  `wiki/decisions/`, which this page then links.
- `sources` lists every processed intake item, record or URL the findings rest on, and each
  **Observed** finding links its evidence in place.
- A later source replaces a finding in place; the page carries no date and no "was" or
  "now" note, and `log.md` records the change. A source that contradicts a **Decided**
  claim elsewhere in the wiki is quarantined, not merged.
