---
feature-id: F-001
title: Reserve a book technical design
apps: [catalog-api, reader-app]
decisions: []
---

## Summary
The catalog stores a reservation for an available copy and the reader app calls the new endpoint.

## Architecture impact
| App | Modules | Change |
|---|---|---|
| catalog-api | catalog | The reservation endpoint is added to the existing catalog module. |
| reader-app | book page | A reserve action that calls the reservation endpoint. |

## Data model and migrations
A reservations table links a reader to a copy; the migration is additive.

## Security and privacy
Only the signed-in reader can reserve a copy for themself.

## Non-functional requirements
A reservation is visible in the catalog within one minute.

## Risks
Two readers may reserve the last copy at once; the catalog accepts the first request only.

## Decisions
A reservation holds a copy for three days. The book page shows the pickup date, and a copy is held for three days.

## API contract
The reservation endpoint is described in the API contract of this feature.

## Test strategy
| Criterion | Applies to | Method | Level | Notes |
|---|---|---|---|---|
| AC-1 | catalog-api | automated | integration | The reservation is created for the signed-in reader |
| AC-2 | reader-app | manual | end-to-end | |
| AC-3 | catalog-api, reader-app | manual | end-to-end | Reserve in the app and read the catalog |
