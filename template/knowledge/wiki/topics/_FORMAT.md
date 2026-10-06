# Topic page format

Use this format for every file in `wiki/topics/`. Filename: `[slug].md`, with lowercase
words joined by hyphens, such as `payment-flows.md`.

A topic is a synthesis page. It combines what several sources and pages say about one
subject, such as a domain concept, an architecture area, a market or a process, into the
current understanding. It is not a feature, a business rule or a decision: use the typed
folder when one fits, and a topic when several pages would otherwise repeat the same
background.

```markdown
---
kind: topic
title: [Topic title]
status: draft | current
sources: [processed intake items, records or URLs the page rests on]
---

## Summary
One paragraph that states the current understanding. Its first sentence is the page's line
in `index.md`, so write it in the present tense.

## Key points
- **Observed:** [what a source shows] ([source](../../intake/processed/YYYY-MM-DD-slug/notes.md))
- **Decided:** [what a human confirmed] ([ADR-001](../decisions/ADR-001-slug.md))
- **Assumed:** [what is taken as true without evidence]
- **Unknown:** [a gap nobody has filled]

## Related pages
Links to the features, rules, decisions and topics that this page relies on or explains.
```

- `status: draft` marks a page whose understanding is still forming; `current` marks one
  that is maintained as the best statement of the subject.
- `sources` lists every processed intake item, record or URL that a claim on the page rests
  on. A **Decided** or **Observed** claim also links its evidence in place.
- When a later source changes a claim, replace the item in place with its new label and its
  new link. The page carries no date and no "was" or "now" note; `log.md` records the
  change. A source that contradicts a **Decided** claim is quarantined, not merged (see
  Conflict quarantine in `SCHEMA.md`).
