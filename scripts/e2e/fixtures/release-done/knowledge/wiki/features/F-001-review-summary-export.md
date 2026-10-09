---
id: F-001
title: Review summary export
status: released
owner: none
apps:
- backend
sources:
- knowledge/intake/processed/2026-09-30-review-summary
advisory-review: not-needed
criteria-high-water: 10
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
- [ ] AC-1 [backend] For a finished review, the backend service operation provides the summary to the calling client for the requesting reviewer.
- [ ] AC-2 [backend] The backend serves the export through a service operation. The "Export summary" button from question 4 lives in the client that calls the backend, and that client is outside this feature. Only the backend app is in scope.
- [ ] AC-3 [backend] The summary contains the document title, the reviewer, the decision (approved, changes requested or rejected) and the comments the reviewer left, subject to the one-page limit below.
- [ ] AC-4 [backend] The summary is one page.
- [ ] AC-5 [backend] The summary can be sent on without editing.
- [ ] AC-6 [backend] The summary never includes comments from other reviewers.
- [ ] AC-7 [backend] Export is not available while the review is still in progress.

- [ ] AC-8 [backend] A downloaded PDF file. The system only produces it; the reviewer sends it on themselves.
- [ ] AC-9 [backend] One page stays the limit. Show as many whole comments as fit and end with a line saying how many more comments are not shown.
- [ ] AC-10 [backend] The header shows the date the review was finished. It does not show a document version.

## Open questions
| # | Question | Owner | Status |
|---|----------|-------|--------|
| 1 | In what format and by what channel does the reviewer receive the summary (for example a downloaded file, text to copy, or an email)? | po | resolved: A downloaded PDF file. The system only produces it; the reviewer sends it on themselves. |
| 2 | If the comments do not fit on one page, what should happen? | po | resolved: One page stays the limit. Show as many whole comments as fit and end with a line saying how many more comments are not shown. |
| 3 | Should the summary include the date of the review or the document version? | po | resolved: The header shows the date the review was finished. It does not show a document version. |
| 4 | Where does the export control appear and what does the summary look like? | designer | resolved: One "Export summary" button on the finished review page. The summary is one A4 page: a header with the document title, the reviewer, the decision and the review date, then the comments in the order they were left. |
| 5 | Which app presents the export control, given that backend is the only app declared for this project? | dev | resolved: The backend serves the export through a service operation. The "Export summary" button from question 4 lives in the client that calls the backend, and that client is outside this feature. Only the backend app is in scope. |
| 6 | Does the summary have to be available in more than one language? | po | resolved: Only English. No other language is needed for this feature. |

## App scope
- **backend**: Serve the review summary through a service operation for a finished review, containing only the requesting reviewer's own comments, and refuse to produce it while the review is in progress.

Developer clarification (question 5): The backend serves the export through a service operation. The "Export summary" button from question 4 lives in the client that calls the backend, and that client is outside this feature. Only the backend app is in scope.

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
| backend | commit:3f9c2ab | none | Pull request #42 in the review-summary-service repository, merged as commit 3f9c2ab | CI run 1187 on commit 3f9c2ab: 31 tests passed, 0 failed | attested |

## QA verification
| Row | Criteria | Method | Artifact | Environment | Attempt | Result | Evidence | Basis |
|---|---|---|---|---|---|---|---|---|
| backend | AC-1@v1:04ffe6d40206381b1ce4a82ea76bfa7a16ba640a3fb5f5a3331d96c26aca36ce, AC-2@v1:a1a4cd14785822442748a750a48cf7c7bd5072516cd6a2f784b0373823dc2143, AC-3@v1:64f4a2d78bbfd82762a158db9dee5e966de27bc9f271755d2a40fc07cdafd74a, AC-4@v1:41c5d37e9f7f493d5f935b5de2b7112ded204f86c324bd92f1be24d7154a1ac1, AC-5@v1:7c69ce361c8ce71c3cf89eebfd97ae5431280e06fcb6ff74ce4e2473a2f8faa8, AC-6@v1:f8e465e19df7412181a61fe736a65f77715479368edf0b2f438ff826c691697b, AC-7@v1:f9b37971c19a64bac5878802d874885f36b05c6ea62304422c9d942fe44f4605, AC-8@v1:fdf15330cb3864fa11c3ddc6933d8d115789831c7a646452dcb3d7b801105674, AC-9@v1:60a85e65068ce5e9428a74a5ad919761c43b01901daa64df5b168431defed69d, AC-10@v1:b076c857a8927be84b237cf0f0a668da902ad1382c267a73f1fd12cbedc2fd12 | automated | `commit:3f9c2ab` | ci | qa-1 | pass | [CI run 1190](https://ci.example.com/runs/1190) | attested |

## Release
| App | Target | Version | Attempt | Outcome | Record | Basis |
|---|---|---|---|---|---|---|
| backend | production | `commit:3f9c2ab` | release-1 | released | [REL-001](../releases/REL-001.md) | attested |

## Evidence history
