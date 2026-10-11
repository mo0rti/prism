---
id: F-001
title: Reserve a book
status: released
owner: none
apps:
- catalog-api
- reader-app
sources:
- knowledge/intake/processed/2026-10-01-reserve-a-book-brief/brief.md
advisory-review: not-needed
criteria-high-water: 3
revalidation: []
design-tracks:
  ui: done
  technical: done
design-reaffirm: []
---

## Summary
A reader reserves an available copy of a book in the reader app, and the catalog records the reservation.

## User story
As a reader, I want to reserve an available copy of a book, so that it waits for me at the library.

## Acceptance criteria
- [ ] AC-1 [catalog-api] A reservation request for an available copy returns the reservation with its pickup date.
- [ ] AC-2 [reader-app] A reader can reserve an available copy from the book page.
- [ ] AC-3 [integration: catalog-api, reader-app] A reservation made in the reader appears in the catalog within one minute.

## Open questions
| # | Question | Owner | Status |
|---|----------|-------|--------|
| 1 | How many copies can a reader reserve at once? | po | resolved: One copy at a time. |
| 2 | What does the book page show after a reservation? | designer | resolved: The book page shows the pickup date, and a copy is held for three days. |
| 3 | Should the reservation response include the pickup date? | po | resolved: A reservation request for an available copy returns the reservation with its pickup date. |

## App scope
- **catalog-api**: Reserve a copy and record the reservation.
- **reader-app**: Offer the reservation on the book page.

## Design
The book page design is in [the design page](../design/F-001-reserve-a-book.md).

## Related features
No related feature is required for this workflow.

## API surface
A new endpoint `POST /api/v1/reservations` reserves an available copy for the signed-in reader and returns the reservation.

## Board review summary
The acceptance checks cover the scoped reservation workflow.

## Delivery evidence
| App | Artifact | Contract | Implementation | Tests | Basis |
|---|---|---|---|---|---|
| catalog-api | `build:catalog-api#412` | F-001@v1:c1:2b2b19ee0ec1eb3232dd2b3b2ef2a475b91dc05f0e817127e9058038ccc7ce18 | [PR 31](https://git.example/lumen/pull/31) | `./run-tests`: 214 passed ([run](https://ci.example/412)) | checked |
| reader-app | `build:reader-app#91` | F-001@v1:c1:2b2b19ee0ec1eb3232dd2b3b2ef2a475b91dc05f0e817127e9058038ccc7ce18 | [PR 33](https://git.example/lumen/pull/33) | `./run-tests`: 214 passed ([run](https://ci.example/91)) | checked |

## QA verification
| Row | Criteria | Method | Artifact | Environment | Attempt | Result | Evidence | Basis |
|---|---|---|---|---|---|---|---|---|
| catalog-api | AC-1@v1:eb51000a53696a6ce4dd1d2161f00ecb09dea8dda431261815979840412d9502 | manual | `build:catalog-api#412` | staging | qa-1 | pass | [notes](https://qa.example/s/1ca) | attested |
| reader-app | AC-2@v1:5bb5044292f5a0da84b388351f35ae0075528aba346205cc45e7d4483f7cf7eb | manual | `build:reader-app#91` | internal-test | qa-2 | pass | [notes](https://qa.example/s/2re) | attested |
| integration:catalog-api+reader-app | AC-3@v1:f8227cf343a7840c64f0f2c7bac24b8526e02de5f27e18bef16502c54b777897 | manual | catalog-api=`build:catalog-api#412`; reader-app=`build:reader-app#91` | ci | qa-2 | pass | [notes](https://qa.example/s/2in) | attested |

## Release
| App | Target | Version | Attempt | Outcome | Record | Basis |
|---|---|---|---|---|---|---|
| catalog-api | production | `build:catalog-api#413` | release-1 | released | [REL-003](../releases/REL-003.md) | checked |
| reader-app | play-store | `build:reader-app#91` | release-2 | released | [REL-002](../releases/REL-002.md) | checked |

## Evidence history
### 2026-10-09 - qa-fail
- Reason: The reserve button does nothing in the reader app.
- Affected apps: reader-app
- Participants: none
- Affected tracks: none
- Archived evidence:
  | Delivery evidence | reader-app | `build:reader-app#90` | F-001@v1:c1:2b2b19ee0ec1eb3232dd2b3b2ef2a475b91dc05f0e817127e9058038ccc7ce18 | [PR 32](https://git.example/lumen/pull/32) | `./run-tests`: 214 passed ([run](https://ci.example/90)) | checked |
  | QA verification | reader-app | AC-2@v1:5bb5044292f5a0da84b388351f35ae0075528aba346205cc45e7d4483f7cf7eb | manual | `build:reader-app#90` | internal-test | qa-1 | fail | [notes](https://qa.example/s/1re) | attested |
- Reaffirmed evidence: none
- Requirement/API invalidations: knowledge/wiki/app-requirements/F-001-reader-app.md: done -> in-progress; knowledge/wiki/api-contracts/F-001.md: implemented -> agreed
- Linked bugs: BUG-001

