---
name: dev-start
description: "Start implementation for one feature after design handoff. Use when a feature is ready-for-dev and the developer is taking ownership."
layers: [codex, command]
codex:
  display_name: "Dev Start"
  short_description: "Start implementation for a ready feature"
  default_prompt: "Use @@invoke:dev-start@@ F-XXX to confirmation-gate the ready-for-dev to in-dev transition."
  implicit: false
---

# Dev start - take ownership of one ready feature

<!-- prism:dev-start-contract:v2 -->

## Usage

`@@invoke:dev-start@@ [F-XXX]`

## Supported action

Prepare, preview, and, after explicit confirmation, write one feature-only
transition:

`ready-for-dev` + `dev` -> `in-dev` + `dev`

Resolve exactly one existing source file at
`knowledge/wiki/features/[F-XXX]-[slug].md` and stop for any missing, invalid,
ambiguous, or different source pair. Read SCHEMA, LIFECYCLE, status board, the complete feature,
all declared app requirements, any applicable API contract, linked design
context, and workspace identity.

When available, use:

```text
prism wiki transition-preflight F-XXX [path] --action dev-start --json
```

Accept the response only with envelope schema 1, command facts, capability version
3 and an action-specific `dev-start` surface, transition version 2, target owner
`dev`, and a consistent snapshot. A version string alone is not capability
evidence. Fall back to direct-file checks when the probe is missing or unsupported;
the preflight is copy-only and never authorizes a write.

Check design, advisory, app requirement, API, and active `revalidation`
facts for this route. An active `specification`, `design` or `technical-design` domain blocks this
downstream start until the owning handoff verifies it. Other active delivery
domains identify work for the developer and may remain while implementation
starts. Show actual app and API evidence and the full feature/status board/log write set; presence
alone does not prove implementation or shipment. Reread immediately before
confirmation and once after it. After explicit confirmation, update the feature
to `in-dev` with `owner: dev`, update the status board row, and append the log.

Decline or cancel means no writes. If a multi-file write is partial, report the
exact observed changes and stop for fresh recovery; no transaction is implied.
This action starts implementation and does not mark any app shipped.
