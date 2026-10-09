# Incident record format

Use this format for every file in `wiki/incidents/`. Filename: `INC-XXX-[slug].md`, with `INC-` and the
number of the `id`, then lowercase words joined by hyphens. An incident is a dated record: it states
what happened, and it changes only where this file allows. `ingest` writes it from an incident report
or an update to one; there is no incident engine and no incident action, so any role may ingest it.

```markdown
---
id: INC-XXX
title: [Incident title]
date: YYYY-MM-DD
status: open | mitigated | resolved
severity: critical | high | medium | low
apps: [list of app IDs the incident affected]
releases: [REL-001]
follow-ups: [BUG-001, F-002]
---

## Impact
Who or what the incident affected, and how badly. One or two sentences first.

## Timeline
- 2026-10-09 08:15: Alerts showed reservations failing after the release.
- 2026-10-09 08:40: The release was rolled back.

## Cause
What caused the incident. While the cause is not known, start with **Unknown:** and say what is known.

## Mitigation
What stopped the harm, and when.

## Resolution
What ended the incident and how it was checked.

## Follow-ups
- [BUG-001](../bugs/BUG-001-reservation-fails.md): the defect behind the incident
```

`date` is the day the incident began, a fact about the world. `releases` lists the release records
(`REL-XXX`) the incident involves, and `follow-ups` the bugs and features that come out of it; both are
`[]` when there are none. The page holds these six sections, each once and in this order, with nothing
above `## Impact`.

## Timeline lines

Each line of `## Timeline` is `- YYYY-MM-DD[ HH:MM]: what happened`. The time may end with `Z`, `UTC` or an
offset. A line is added at the end and never rewritten.

## Status

| Status | Meaning |
|---|---|
| `open` | The incident goes on, or its harm has not been stopped. |
| `mitigated` | The harm is stopped; `## Mitigation` says how. The cause or the fix may still be open. |
| `resolved` | The incident is over; `## Resolution` says how. |

A `resolved` incident is final. A recurrence is a new incident.

## Changing an incident

`ingest` creates an incident in any status that its sections support, and updates one from a new intake
item. An update may only:

- step `status` (`open` to `mitigated` or `resolved`, `mitigated` to `open` or `resolved`);
- append lines to `## Timeline`;
- add entries to `releases` and `follow-ups`;
- while the incident is not `resolved`, fill or replace `## Cause`, `## Mitigation`, `## Resolution` and
  `## Follow-ups`.

A new `## Cause` adds a Timeline line that links the intake item the cause came from, for example
`- 2026-10-10: Cause recorded ([intake item](../../intake/processed/2026-10-10-postmortem/MANIFEST.md))`
(`incident_cause_uncited`). `title`, `date`, `severity`, `apps` and `## Impact` never change
(`incident_frontmatter_scope`, `incident_body_scope`). A `resolved` incident changes only by appended
Timeline lines and added follow-ups and releases (`incident_resolved_final`, `incident_body_scope`,
`incident_timeline_not_append_only`).

## Rules

- A new incident has a free ID (`incident_id_taken`). Every release in `releases` has a record in
  `releases/` (`incident_release_unknown`).
- `prism wiki lint` reports a malformed page as `incident-record-invalid` (error) and a follow-up that
  names no bug or feature page as `incident-follow-up-missing` (warning).
- The status board lists an incident that is not `resolved` under each app it names, in the Operations
  table.
- An incident is a record, so it carries no evidence labels and is not asked for review.
