---
id: F-001
title: Review summary export
status: in-dev
owner: dev
introduced: '2026-10-05'
last-updated: '2026-10-05'
platforms:
- backend
sources:
- knowledge/intake/processed/review-summary
advisory-review: not-needed
---

## Summary
A reviewer who has finished reviewing a document can export a one-page summary of their review. The summary shows the document title, the reviewer, the decision (approved, changes requested or rejected) and the comments that reviewer left. Reviewers in legal operations currently copy their comments into an email by hand after every review, which takes about ten minutes per document and loses comments. Reviewers named this manual summary as their biggest frustration in the last two feedback rounds.

## User story
As a [Legal operations document reviewer](../personas/legal-operations-reviewer.md), I want to export a summary of my finished review, so that I can send it on without editing and without copying my comments by hand.

## Acceptance criteria
- [ ] For a finished review, the backend service operation provides the summary to the calling client for the requesting reviewer.
- [ ] The backend serves the export through a service operation. The "Export summary" button from question 4 lives in the client that calls the backend, and that client is outside this feature. Only the backend platform is in scope.
- [ ] The summary contains the document title, the reviewer, the decision (approved, changes requested or rejected) and the comments the reviewer left, subject to the one-page limit below.
- [ ] The summary is one page.
- [ ] The summary can be sent on without editing.
- [ ] The summary never includes comments from other reviewers.
- [ ] Export is not available while the review is still in progress.

- [ ] A downloaded PDF file. The system only produces it; the reviewer sends it on themselves.
- [ ] One page stays the limit. Show as many whole comments as fit and end with a line saying how many more comments are not shown.
- [ ] The header shows the date the review was finished. It does not show a document version.

## Open questions
| # | Question | Owner | Status |
|---|----------|-------|--------|
| 1 | In what format and by what channel does the reviewer receive the summary (for example a downloaded file, text to copy, or an email)? | po | resolved: A downloaded PDF file. The system only produces it; the reviewer sends it on themselves. |
| 2 | If the comments do not fit on one page, what should happen? | po | resolved: One page stays the limit. Show as many whole comments as fit and end with a line saying how many more comments are not shown. |
| 3 | Should the summary include the date of the review or the document version? | po | resolved: The header shows the date the review was finished. It does not show a document version. |
| 4 | Where does the export control appear and what does the summary look like? | designer | resolved: One "Export summary" button on the finished review page. The summary is one A4 page: a header with the document title, the reviewer, the decision and the review date, then the comments in the order they were left. |
| 5 | Which platform presents the export control, given that backend is the only platform declared for this project? | dev | resolved: The backend serves the export through a service operation. The "Export summary" button from question 4 lives in the client that calls the backend, and that client is outside this feature. Only the backend platform is in scope. |
| 6 | Does the summary have to be available in more than one language? | po | resolved: Only English. No other language is needed for this feature. |

## Platform scope
- **backend**: Serve the review summary through a service operation for a finished review, containing only the requesting reviewer's own comments, and refuse to produce it while the review is in progress.

Developer clarification (question 5): The backend serves the export through a service operation. The "Export summary" button from question 4 lives in the client that calls the backend, and that client is outside this feature. Only the backend platform is in scope.

## Design
Not started.

## Related features
None identified.

## API surface
The backend adds one endpoint, `GET /api/v1/reviews/:reviewId/summary`, which returns the review summary of a finished review as a PDF to the signed-in reviewer who wrote it.

## Board review summary
Not needed.

## Post-ship notes
Not shipped yet.
