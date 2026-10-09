---
id: F-001
title: Review summary export
status: ready-for-release
owner: release
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
app-revalidation:
  backend:
  - release
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
- [ ] AC-10 [backend] The backend serves the export through a service operation. The "Export summary" button from question 4 lives in the client that calls the backend, and that client is outside this feature. Only the backend app is in scope.

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
- **backend**: Produce the review summary for a finished review, containing only the requesting reviewer's own comments, and refuse to produce it while the review is in progress.

## Design
The technical design is in [Review summary export technical design](../technical-design/F-001-review-summary-export.md).

## Related features
None identified.

## API surface
The backend adds one endpoint, `GET /api/v1/reviews/:reviewId/summary`, which returns the review summary of a finished review as a PDF to the signed-in reviewer who wrote it.

## Board review summary
Not needed.

## Delivery evidence
| App | Artifact | Contract | Implementation | Tests | Basis |
|---|---|---|---|---|---|
| backend | commit:5d7a1e4 | F-001@v1:c1:acd0d4da2450d65ab401f518cfd9d8c003a5b8238862630eec4f72a7ba968654 | Pull request #43 in the review-summary-service repository, merged as commit 5d7a1e4 | CI run 1204 on commit 5d7a1e4: 33 tests passed, 0 failed | attested |

## QA verification
| Row | Criteria | Method | Artifact | Environment | Attempt | Result | Evidence | Basis |
|---|---|---|---|---|---|---|---|---|
| backend | AC-1@v1:35abbfa4dfd5b8cc6d371558a3f1eda45207f3ef863ee9398dad7ca36cdfff23, AC-2@v1:d26bf9ccf0cd27c05e628bcf325fe440914afc1f7dea2cb056c75a6438ba2cee, AC-3@v1:86d762c492db5b7c670933c00a7b6720fa53b3372a85490a630ad6ed7b513c68, AC-4@v1:c79fc445218a5ffab67af3b5feb93d7fc2ffe1ce4c978fbb1ff31cecae9402bc, AC-5@v1:cf4633687c963c3e19aac510dc44ddc771118eee4b4df32df4d81cafd834171d, AC-6@v1:bf2f7b79b80394fffd8e24e9ee8507a448eb29654937cebf28b8a8d168b52195, AC-7@v1:dfdb726b41f8d10a63cba8e69a09d4d95afd4849b4ae5115c39d6b7b0a19cb8b, AC-8@v1:bb16b0265d56ec65757da77b18df5095d52c6e9a92cff86d223bec7c2a795c84, AC-9@v1:d0c73d0d910a00b63d87e8af0ac31d152d27d943db28f146fa3ac52841bb2ae0, AC-10@v1:17edd79956ef8942a718e84cc6580d52ecba0781c13917e89dc01c2205ae7e2c | automated | `commit:5d7a1e4` | ci | qa-2 | pass | [CI run 1210](https://ci.example.com/runs/1210) | attested |

## Release
| App | Target | Version | Attempt | Outcome | Record | Basis |
|---|---|---|---|---|---|---|
| backend | production | `commit:5d7a1e4` | release-1 | failed | [REL-001](../releases/REL-001.md) | attested |

## Evidence history


### 2026-10-09 - qa-fail
- Reason: AC-8 failed in QA: the summary does not say how many comments are not shown (BUG-001).
- Affected apps: backend
- Participants: none
- Affected tracks: none
- Archived evidence:
  | Delivery evidence | backend | commit:3f9c2ab | F-001@v1:c1:acd0d4da2450d65ab401f518cfd9d8c003a5b8238862630eec4f72a7ba968654 | Pull request #42 in the review-summary-service repository, merged as commit 3f9c2ab | CI run 1187 on commit 3f9c2ab: 31 tests passed, 0 failed | attested |
  | QA verification | backend | AC-1@v1:35abbfa4dfd5b8cc6d371558a3f1eda45207f3ef863ee9398dad7ca36cdfff23, AC-2@v1:d26bf9ccf0cd27c05e628bcf325fe440914afc1f7dea2cb056c75a6438ba2cee, AC-3@v1:86d762c492db5b7c670933c00a7b6720fa53b3372a85490a630ad6ed7b513c68, AC-4@v1:c79fc445218a5ffab67af3b5feb93d7fc2ffe1ce4c978fbb1ff31cecae9402bc, AC-5@v1:cf4633687c963c3e19aac510dc44ddc771118eee4b4df32df4d81cafd834171d, AC-6@v1:bf2f7b79b80394fffd8e24e9ee8507a448eb29654937cebf28b8a8d168b52195, AC-7@v1:dfdb726b41f8d10a63cba8e69a09d4d95afd4849b4ae5115c39d6b7b0a19cb8b, AC-9@v1:d0c73d0d910a00b63d87e8af0ac31d152d27d943db28f146fa3ac52841bb2ae0, AC-10@v1:17edd79956ef8942a718e84cc6580d52ecba0781c13917e89dc01c2205ae7e2c | automated | `commit:3f9c2ab` | ci | qa-1 | pass | [CI run 1190](https://ci.example.com/runs/1190) | attested |
  | QA verification | backend | AC-8@v1:bb16b0265d56ec65757da77b18df5095d52c6e9a92cff86d223bec7c2a795c84 | exploratory | `commit:3f9c2ab` | ci | qa-1 | fail | [CI run 1190 export log](https://ci.example.com/runs/1190#export-log) | attested |
- Reaffirmed evidence: none
- Requirement/API invalidations: knowledge/wiki/app-requirements/F-001-backend.md: done -> in-progress, knowledge/wiki/api-contracts/F-001.md: implemented -> agreed
- Linked bugs: BUG-001

