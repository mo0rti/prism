---
id: BUG-002
title: Reservation response lacks the pickup date
status: released
owner: none
severity: high
blocking: true
apps:
- catalog-api
feature: F-001
found-in: build:catalog-api#412
environment: production
sources: []
---

## Summary
Reservation response lacks the pickup date.

## Steps to reproduce
1. Open the book page of an available copy.
2. Press the reserve button.

## Expected
The reservation is created and the pickup date is shown.

## Actual
Nothing happens and no reservation is created.

## Impact
Readers cannot reserve a book.

## Fix
| App | Artifact | Implementation | Tests | Basis |
|---|---|---|---|---|
| catalog-api | `build:catalog-api#413` | [PR 41](https://git.example/lumen/pull/41) | `./run-tests`: 220 passed ([run](https://ci.example/413)) | checked |

## Verification
| App | Method | Artifact | Environment | Attempt | Result | Evidence | Basis |
|---|---|---|---|---|---|---|---|
| catalog-api | manual | `build:catalog-api#413` | staging | qa-1 | pass | [notes](https://qa.example/bug/1) | attested |

## Release
| App | Target | Version | Attempt | Outcome | Record | Basis |
|---|---|---|---|---|---|---|
| catalog-api | production | `build:catalog-api#413` | release-1 | released | [REL-003](../releases/REL-003.md) | checked |

## Evidence history

