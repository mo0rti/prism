---
id: INC-001
title: Reservations fail after the catalog fix
date: '2026-10-09'
status: resolved
severity: high
apps:
- catalog-api
releases:
- REL-003
- REL-004
- REL-005
- REL-006
follow-ups:
- BUG-003
---

## Impact
Readers could not reserve books for 25 minutes.

## Timeline
- 2026-10-09 08:15: Reservations started failing after REL-003.
- 2026-10-09 08:40: REL-003 was rolled back by REL-004.
- 2026-10-09: Mitigation recorded ([update](../../intake/processed/2026-10-11-mitigation/note.md))
- 2026-10-09: Cause recorded ([post-mortem](../../intake/processed/2026-10-12-postmortem/note.md))
- 2026-10-09: Resolved by the redeploy REL-006 ([post-mortem](../../intake/processed/2026-10-12-postmortem/note.md))

## Cause
The reservation cache ignored the copy status after REL-003 ([post-mortem](../../intake/processed/2026-10-12-postmortem/note.md)).

## Mitigation
REL-003 was rolled back by REL-004 at 08:40.

## Resolution
Build 413 was redeployed by REL-006 and reservations succeed again.

## Follow-ups
- [BUG-003](../bugs/BUG-003-reservation-cache-ignores-copy-status.md): the cache defect behind the outage
