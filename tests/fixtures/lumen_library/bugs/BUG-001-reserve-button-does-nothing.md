---
id: BUG-001
title: Reserve button does nothing
status: released
owner: none
severity: high
blocking: true
apps:
- reader-app
feature: F-001
found-in: build:reader-app#90
environment: internal-test
sources: []
---

## Summary
Reserve button does nothing.

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
| reader-app | `build:reader-app#91` | [PR 40](https://git.example/lumen/pull/40) | `./run-tests`: 220 passed ([run](https://ci.example/91)) | checked |

## Verification
| App | Method | Artifact | Environment | Attempt | Result | Evidence | Basis |
|---|---|---|---|---|---|---|---|
| reader-app | manual | `build:reader-app#91` | internal-test | qa-1 | pass | [notes](https://qa.example/bug/1) | attested |

## Release
| App | Target | Version | Attempt | Outcome | Record | Basis |
|---|---|---|---|---|---|---|
| reader-app | play-store | `build:reader-app#91` | release-2 | released | [REL-002](../releases/REL-002.md) | checked |

## Evidence history

