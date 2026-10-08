# Feature reopen - reopen one shipped feature through an impact-reviewed route

<!-- prism:feature-reopen-contract:v2 -->

## Usage

`/feature-reopen [F-XXX] [specified|in-design|in-dev]`

The route selects one exact action:

| Route | Action | Source | Destination | Pending revalidation |
|---|---|---|---|---|
| `specified` | `reopen-spec` | `done` + `none` | `specified` + `po` | specification, design, implementation, tests, release |
| `in-design` | `reopen-design` | `done` + `none` | `in-design` + `designer` | design, implementation, tests, release |
| `in-dev` | `reopen-dev` | `done` + `none` | `in-dev` + `dev` | implementation, tests, release |

Resolve exactly one source file at
`knowledge/wiki/features/[F-XXX]-[slug].md`. A missing, invalid, ambiguous, or
non-`done`/`none` source is a stop condition. Do not invent another route or a
generic status setter.

### Routes back from QA

While an app has reached QA, the same `specified` and `in-design` arguments select the QA return routes. They send the
whole feature back before anything shipped:

| Route | Action | Source | Destination | Pending revalidation |
|---|---|---|---|---|
| `specified` | `qa-return-spec` | `in-dev` + `dev` (an app at `ready-for-qa` or later), `ready-for-qa` + `qa`, `in-qa` + `qa`, `ready-for-release` + `release` | `specified` + `po` | specification, design, technical-design; every app: implementation, tests, qa, release |
| `in-design` | `qa-return-design` | the same | `in-design` + the design owner of the scope | design, technical-design; every app: implementation, tests, qa, release |

A feature in which some but not all apps are released cannot return to specification or design
(`partial_release_requires_new_feature`): put changed requirements or contracts in a new feature, and an implementation defect
in a bug. An implementation defect of one app is a `qa-fail`, not a return.

The proposal, in one write, moves every Delivery evidence, QA verification and Release row of every app to
`## Evidence history` in one `### <today> - qa-return-spec` (or `qa-return-design`) entry, copying each row verbatim under
`- Archived evidence:` with its section name in front. The entry fills `- Reason:`, `- Affected apps:` (every app of the scope),
`- Participants: none`, `- Affected tracks:` (`ui`, `technical`; `qa-return-design` names the tracks it sends back),
`- Reaffirmed evidence: none`, `- Requirement/API invalidations:` and `- Linked bugs:`. It sets the status and owner, adds the
revalidation domains above, and:

- `qa-return-spec` removes `design-tracks` and `design-reaffirm` (the design starts again) and sets a requirement page that was
  `done` to `in-progress` and an API contract that was `agreed` or `implemented` to `draft`;
- `qa-return-design` sets each affected track in `design-tracks` to `pending` (its reason removed), lists every other `done` track
  in `design-reaffirm`, sets a requirement page that was `done` to `in-progress` and an `implemented` API contract to `agreed`.

Change only `status` in a requirement page or API contract.

## Read-only preflight and impact review

Read SCHEMA, LIFECYCLE, status board, the complete feature, linked design, app requirements,
applicable API contract, delivery evidence, and workspace identity. When available,
probe the matching action:

```text
prism wiki transition-preflight F-XXX [path] --action reopen-dev --json
```

Replace `reopen-dev` with `reopen-spec` or `reopen-design` for the selected route.
Accept the response only with envelope schema 1, command facts, capability version
2 and a matching action-specific surface, transition version 1, exact target owner,
and a consistent snapshot. A version string alone is not capability evidence. If
the probe is missing or unsupported, report the direct-file fallback; the preflight
is copy-only and never authorizes a write.

A ready Copy request may initiate the impact review; no review record needs to
exist in the wiki before this action is requestable. The request remains
copy-only until the review and final confirmation are complete. Before any
proposed write, obtain a confirmed impact review recording the reason, selected
route, affected apps, affected artifacts, and any additional revalidation
domains. Archive the prior `## Delivery evidence` table in the append-only reopen
history and remove it from the active section on confirmation. Existing evidence
cannot automatically satisfy a new Done check; unaffected evidence must be
explicitly reaffirmed after impact review. Show exact affected app-
requirement and API pages with their proposed invalidated statuses, preserve
prior statuses in history, and never reset unrelated shared contracts.

Write the archived evidence under the `- Prior completion/release evidence:` bullet
of the reopen record. Copy each prior Delivery evidence row verbatim, with its
`| app | implementation | tests | release |` cells, on that line or on the
lines directly below it as a table or a list, before the next `- Label:` bullet or
heading. A row anywhere else is not found, and the connected board rejects the
record with `delivery_evidence_not_archived`. `knowledge/wiki/features/_FORMAT.md` shows the
layout.

Write `- Requirement/API invalidations:` with one entry for each requirement or API page
you change: its full relative path, a colon, the page's current status, an arrow and its
new status, for example `knowledge/wiki/app-requirements/F-001-backend.md: done ->
in-progress` (on one line). Name each of those pages by the same path in
`- Affected artifacts:`. When no page changes, write a sentence such as `No requirement
or API page is invalidated.`; the bullet cannot be empty or a bare `None`.

Show the current and destination fields, active `revalidation` list, archived
evidence, and every feature/status board/log write. Reread the source, status board, identity,
and linked context immediately before confirmation and once again after it. Only
then write the selected status/owner pair, active revalidation domains, history,
status board, and log. Decline or cancel means no mutation. If a multi-file write is
partial, report exact changes and stop for fresh recovery; no transaction is
implied.

Return the prior route, new route, impact review, affected artifacts, active
revalidation domains, and archived evidence. Reopening records a route and review; it does not prove that the feature is ready,
implemented, tested, or shipped again.

## Record rules

- a reopen entry is a dated record: append it and never rewrite an earlier reopen entry
