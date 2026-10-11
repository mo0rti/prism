---
id: BUG-003
title: Reservation cache ignores copy status
status: open
owner: dev
severity: medium
blocking: false
apps:
- catalog-api
feature: none
found-in: INC-001
environment: production
sources: []
---

## Summary
Reservation cache ignores copy status.

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


## Verification


## Release


## Evidence history

