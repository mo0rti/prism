---
id: F-001
title: Review summary export
status: raw
owner: po
introduced: 2026-10-05
last-updated: 2026-10-05
apps: [backend]
sources: [knowledge/intake/processed/review-summary]
advisory-review: not-needed
---

## Summary
A reviewer who has finished reviewing a document can export a one-page summary of their review. The summary shows the document title, the reviewer, the decision (approved, changes requested or rejected) and the comments that reviewer left. Reviewers in legal operations currently copy their comments into an email by hand after every review, which takes about ten minutes per document and loses comments. Reviewers named this manual summary as their biggest frustration in the last two feedback rounds.

## User story
As a [Legal operations document reviewer](../personas/legal-operations-reviewer.md), I want to export a summary of my finished review, so that I can send it on without editing and without copying my comments by hand.

## Acceptance criteria
- [ ] A reviewer who has finished a review can choose export on that review and receive a summary.
- [ ] The summary contains the document title, the reviewer, the decision (approved, changes requested or rejected) and the comments the reviewer left.
- [ ] The summary is one page.
- [ ] The summary can be sent on without editing.
- [ ] The summary never includes comments from other reviewers.
- [ ] Export is not available while the review is still in progress.

## Open questions
| # | Question | Owner | Status |
|---|----------|-------|--------|
| 1 | In what format and by what channel does the reviewer receive the summary (for example a downloaded file, text to copy, or an email)? | po | open |
| 2 | If the comments do not fit on one page, what should happen? | po | open |
| 3 | Should the summary include the date of the review or the document version? | po | open |
| 4 | Where does the export control appear and what does the summary look like? | designer | open |
| 5 | Which app presents the export control, given that backend is the only app declared for this project? | dev | open |

## App scope
- **backend**: Produce the review summary for a finished review, containing only the requesting reviewer's own comments, and refuse to produce it while the review is in progress.

## Design

## Related features

## API surface

## Board review summary

## Post-ship notes
