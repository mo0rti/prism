---
id: BUG-001
title: Summary does not say how many comments are not shown
status: in-fix
owner: dev
severity: high
blocking: true
apps: [backend]
feature: F-001
found-in: commit:3f9c2ab
environment: ci
sources: []
---

## Summary
When a finished review has more comments than fit on one page, the summary stops after the last whole comment and does not say how many comments are not shown.

## Steps to reproduce
1. Finish a review that has more comments than fit on one A4 page.
2. Export the summary from the backend service operation.
3. Read the last line of the PDF.

## Expected
The last line states how many more comments are not shown (AC-8).

## Actual
The summary ends after the last whole comment and says nothing about the comments that are left out.

## Impact
A reviewer who sends the summary on cannot tell that it is incomplete.

## Fix


## Verification


## Release


## Evidence history

