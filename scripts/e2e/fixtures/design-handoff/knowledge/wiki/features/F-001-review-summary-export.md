---
id: F-001
title: Review summary export
status: ready-for-dev
owner: dev
apps:
- backend
sources:
- knowledge/intake/processed/2026-09-30-review-summary
advisory-review: not-needed
criteria-high-water: 9
design-tracks:
  ui: not-applicable
  technical: done
  ui-reason: No app in scope has a UI.
design-reaffirm: []
---

## Summary
A reviewer who has finished reviewing a document can export a one-page summary of their review. The summary shows the document title, the reviewer, the decision (approved, changes requested or rejected) and the comments that reviewer left. Reviewers in legal operations currently copy their comments into an email by hand after every review, which takes about ten minutes per document and loses comments. Reviewers named this manual summary as their biggest frustration in the last two feedback rounds.

## User story
As a [Legal operations document reviewer](../personas/legal-operations-reviewer.md), I want to export a summary of my finished review, so that I can send it on without editing and without copying my comments by hand.

## Acceptance criteria
- [ ] AC-1 [backend] A reviewer who has finished a review can choose export on that review and receive a summary.
- [ ] AC-2 [backend] The summary contains the document title, the reviewer, the decision (approved, changes requested or rejected) and the comments the reviewer left, subject to the one-page limit below.
- [ ] AC-3 [backend] The summary is one page.
- [ ] AC-4 [backend] The summary can be sent on without editing.
- [ ] AC-5 [backend] The summary never includes comments from other reviewers.
- [ ] AC-6 [backend] Export is not available while the review is still in progress.

- [ ] AC-7 [backend] A downloaded PDF file. The system only produces it; the reviewer sends it on themselves.
- [ ] AC-8 [backend] One page stays the limit. Show as many whole comments as fit and end with a line saying how many more comments are not shown.
- [ ] AC-9 [backend] The header shows the date the review was finished. It does not show a document version.

## Open questions
| # | Question | Owner | Status |
|---|----------|-------|--------|
| 1 | In what format and by what channel does the reviewer receive the summary (for example a downloaded file, text to copy, or an email)? | po | resolved: A downloaded PDF file. The system only produces it; the reviewer sends it on themselves. |
| 2 | If the comments do not fit on one page, what should happen? | po | resolved: One page stays the limit. Show as many whole comments as fit and end with a line saying how many more comments are not shown. |
| 3 | Should the summary include the date of the review or the document version? | po | resolved: The header shows the date the review was finished. It does not show a document version. |
| 4 | Where does the export control appear and what does the summary look like? | designer | resolved: One "Export summary" button on the finished review page. The summary is one A4 page: a header with the document title, the reviewer, the decision and the review date, then the comments in the order they were left. |
| 5 | Which app presents the export control, given that backend is the only app declared for this project? | dev | open |
| 6 | Does the summary have to be available in more than one language? | po | resolved: Only English. No other language is needed for this feature. |

## App scope
- **backend**: Produce the review summary for a finished review, containing only the requesting reviewer's own comments, and refuse to produce it while the review is in progress.

## Design
Not started.

## Related features
None identified.

## API surface
None.

## Board review summary
Not needed.

## Delivery evidence
| App | Artifact | Contract | Implementation | Tests | Basis |
|---|---|---|---|---|---|

## QA verification
| Row | Criteria | Method | Artifact | Environment | Attempt | Result | Evidence | Basis |
|---|---|---|---|---|---|---|---|---|

## Release
| App | Target | Version | Attempt | Outcome | Record | Basis |
|---|---|---|---|---|---|---|

## Evidence history
