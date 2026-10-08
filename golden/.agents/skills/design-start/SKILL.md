---
name: design-start
description: Start design work on one feature after the confirmed PO handoff. Use when a feature is ready-for-design and the designer is taking ownership.
---

# Design start - take ownership of one ready feature

<!-- prism:design-start-contract:v2 -->

## Usage

`$design-start [F-XXX]`

## Supported action

Prepare, preview, and, after explicit confirmation, write one feature-only
transition:

`ready-for-design` + the design owner -> `in-design` + the design owner (`designer` while an active app in scope has a UI, otherwise `tech-lead`)

Resolve exactly one existing feature file at
`knowledge/wiki/features/[F-XXX]-[slug].md`. Stop for a missing, invalid, or
ambiguous ID, or for any other source status/owner pair; accept only the exact
source pair above and do not infer a transition from another status or owner.
Read SCHEMA, LIFECYCLE, ACTIONS, status board, the feature, linked context, and workspace
identity. The feature's declared apps define its design scope.

When available, use:

```text
prism wiki transition-preflight F-XXX [path] --action design-start --json
```

Accept it only with envelope schema 1, command facts, capability version 3 and an
action-specific `design-start` surface, transition version 2, target owner
the design owner (`designer` or `tech-lead`), and a consistent snapshot. The Prism version alone does not prove
support. Fall back to direct-file checks when any capability or field is missing;
the preflight is copy-only and never authorizes a write.

Check the current source, feature app scope, advisory state, and active
`revalidation` domains. An active `specification` domain blocks this downstream
start until PO verifies it; an active `design` domain may be worked by the
designer and does not claim that a design artifact already covers the feature.
Designer-owned open questions may remain while design starts. Pending advisory
review remains an unresolved blocker; follow the existing board-review or
explicit skip policy instead of inventing a waiver.

Starting design also writes the feature's design tracks, which are absent until then:

```yaml
design-tracks:
  ui: pending           # not-applicable when every active scoped app has has-ui: false
  technical: pending
  ui-reason: "No app in scope has a UI."   # only with ui: not-applicable
design-reaffirm: []
```

`unknown` counts as a UI, so only an explicit exemption by the designer
(`$design-ui-done`) makes the UI track `not-applicable` for such an app. Write
nothing else about the tracks: the track actions settle them.

Show the observed fields, proposed destination, evidence, and every feature,
status board, and log write. Reread the source and context immediately before asking for
confirmation and once more after confirmation. Only then update `status` to
`in-design`, keep the owner the design owner, write the initial `design-tracks` and `design-reaffirm`,
update the status board row, and append the log.
Decline or cancel means no writes. If a multi-file write is partial, report the
exact observed changes and stop for fresh recovery; no transaction is implied.

Return the observed source and destination fields and the design-scope evidence.
This action starts work; it does not prove design completeness or development
readiness.
