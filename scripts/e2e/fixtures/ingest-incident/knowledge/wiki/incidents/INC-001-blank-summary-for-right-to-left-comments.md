---
id: INC-001
title: Blank review summary for right-to-left comments
date: 2026-10-09
status: open
severity: high
apps: [backend]
releases: [REL-002]
follow-ups: []
---

## Impact
Every export of a review with right-to-left comment text returned a blank page; eleven reviewers reported it in the first hour. Exports of reviews without such text were not affected.

## Timeline
- 2026-10-09 09:10: Support received the first report of a blank summary, about forty minutes after REL-002 reached production.
- 2026-10-09 09:25: Support confirmed that only reviews with right-to-left comment text are affected.
- 2026-10-09 09:40: The on-call engineer was paged.

## Cause
**Unknown:** The blank page appeared only after REL-002; the cause has not been found.

## Mitigation
None yet. Reviewers were told to send their comments on by hand.

## Resolution


## Follow-ups

