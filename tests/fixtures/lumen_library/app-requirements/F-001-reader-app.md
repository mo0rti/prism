---
feature-id: F-001
app: reader-app
status: done
---

## What to build
Offer the reservation on the book page and show its pickup date.

## Technical constraints
Use the shared reader network client.

## Design reference
[Reservation design](../design/F-001-reserve-a-book.md) shows the book page.

## API contract reference
[API contract](../api-contracts/F-001.md)

## Acceptance criteria
- A reader can reserve an available copy from the book page.

## Dependencies
The catalog-api reservation endpoint is available.
