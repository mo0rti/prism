---
feature-id: F-001
title: Review summary export technical design
apps: [backend]
decisions: []
---

## Summary
The backend serves the review summary as a PDF through one read endpoint of the review API.

## Architecture impact
| App | Modules | Change |
|---|---|---|
| backend | reviews | A summary renderer that produces one A4 page from a finished review |

## Data model and migrations
No migration is needed; the summary is produced when it is requested and is not stored.

## Security and privacy
Only the reviewer who wrote the review may request its summary, and the summary holds only that reviewer's comments.

## Non-functional requirements
The summary is generated in one request and fits one A4 page; comments that do not fit end with a count of those not shown.

## Risks
A review with very long comments needs the one-page truncation rule; the renderer shows whole comments only.

## Decisions
No new technical decision is needed.

## API contract
[The API contract](../api-contracts/F-001.md) defines the endpoint `GET /api/v1/reviews/:reviewId/summary`.

## Test strategy
| Criterion | Applies to | Method | Level | Notes |
|---|---|---|---|---|
| AC-1 | backend | automated | integration | |
| AC-2 | backend | automated | integration | |
| AC-3 | backend | automated | integration | |
| AC-4 | backend | automated | integration | |
| AC-5 | backend | automated | integration | |
| AC-6 | backend | automated | integration | |
| AC-7 | backend | automated | integration | |
| AC-8 | backend | automated | integration | |
| AC-9 | backend | automated | integration | |
