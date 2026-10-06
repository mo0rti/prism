---
feature-id: F-001
app: backend
status: pending
---

## What to build
Produce the review summary for a finished review as a downloadable PDF file. The system only produces the file; the reviewer sends it on themselves.

- Generate the summary only for a finished review, and only for the requesting reviewer. Refuse to produce it while the review is still in progress.
- Include only the requesting reviewer's own comments. Never include comments from other reviewers.
- Layout is one A4 page: a header with the document title, the reviewer, the decision (approved, changes requested or rejected) and the date the review was finished, followed by the comments in the order they were left. Do not show a document version.
- One page is the hard limit. Show as many whole comments as fit and end with a line saying how many more comments are not shown.
- The output must be sendable without editing.

## Technical constraints
No app-specific constraints are recorded in the wiki. The output format is PDF and the page size is A4. Choice of PDF library and following existing backend patterns are left to the developer.

## Design reference
Not applicable for backend.

## API contract reference
See [the API contract](../api-contracts/F-001.md) for the summary endpoint.

## Acceptance criteria
- [ ] A reviewer who has finished a review receives a downloaded PDF summary of that review.
- [ ] The summary header contains the document title, the reviewer, the decision and the date the review was finished, and no document version.
- [ ] The comments follow the header in the order they were left and are only the requesting reviewer's own.
- [ ] The summary is exactly one A4 page; when not all comments fit, whole comments are shown and the last line states how many more comments are not shown.
- [ ] The summary can be sent on without editing.
- [ ] Producing a summary for a review that is still in progress is refused.

## Dependencies
Open question 5 on F-001 (dev-owned: which app presents the export control, given that backend is the only declared app) is unresolved and must be resolved through dev-clarify.
