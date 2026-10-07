---
name: dev-done
description: Mark a feature as shipped. Use when implementation is complete and the wiki should be updated with done status, app completion, and any post-ship notes.
---

# Dev done - mark a feature as shipped

<!-- prism:dev-done-contract:v1 -->

Use this skill to mark one feature as shipped and close out its implementation state.

## Usage

`$dev-done [F-XXX]`

## Read-only preflight

When available, use:

```text
prism wiki transition-preflight F-XXX [path] --action dev-done --json
```

Accept it only with common envelope schema 1, command facts, capability version
2 and an action-specific `dev-done` surface, transition version 1, target owner
`none`, and a consistent snapshot. The Prism version alone does not prove
support. If any required fact, schema, action, capability, or snapshot is
missing or fails, fall back to direct-file checks. The preflight is copy-only
and never authorizes a write.

## Supported action

`in-dev` + `dev` -> `done` + `none`

Resolve exactly one `knowledge/wiki/features/[F-XXX]-[slug].md` source file and
require `status: in-dev` with `owner: dev`. A missing, invalid, ambiguous, or
different source pair is a stop condition. So is a feature that lists a retired
app (`app-retired-in-scope`): retirement never changes scope by itself, so ask for an
explicit edit of the feature's `apps` first.

## Evidence and confirmation

Read `knowledge/wiki/SCHEMA.md`, `knowledge/wiki/LIFECYCLE.md`, `status-board.md`, the complete feature, every declared
app-requirement page, any applicable API contract, linked context, workspace
identity, advisory state, delivery evidence, and active `revalidation` domains.

Delivery evidence is an input to this action. For every declared app, get
the implementation artifact, the test command and result, and the release
evidence or delivery attestation from the developer, or read them from the current
`## Delivery evidence` table when it already holds them. Write them into the
proposed feature page as that table: one row per declared app in the
`| App | Implementation | Tests | Release |` cell order, each cell a
substantive reference. The `Release` cell is one of two forms, matched without
regard to case: release evidence (`release: <reference>`, `tag: <reference>` or
`deployment: <reference>`, where the reference is the URL of, or a workspace path
to, a release, tag or deployment record) or a delivery attestation (`attested by
<Name>: <reference>`, where the reference is a URL or a path to what that person
checked). A commit, a pull request or merge request, `merged`, a branch name or
free text proves which code changed, not that it shipped, so it does not satisfy
this action. For an app in an external repository, link its record by URL; no
local checkout is needed. The same preview then shows the evidence rows and the
status change, and no hand edit is needed first. Ask the developer for any value
you do not have; never invent or imply a delivery claim. The connected board
rejects a proposal whose table has no rows or an invalid row with
`delivery_evidence_required`, `delivery_evidence_invalid` or
`release_evidence_required` and names the problem. A transition preflight
reports the table recorded on the page now (the check `release-evidence-required`
names a `Release` cell that is neither form); an empty table is expected until
the proposal supplies it.

For every declared app, verify the actual implementation artifact, test
result, and release artifact or target the evidence names. A substantive table
cell, file presence, or clean lint result is not verification. When a reference
cannot be checked from here, say so in the proposed `## Post-ship notes`: that
row is then the developer's attestation, and the developer confirms it with the
final confirmation. The attestation stands in for your own check below, so the
requirement pages and API contract it covers may be proposed as complete; say in
your summary that you did not verify the references yourself. This attestation
vouches for references you could not check; it is not the delivery attestation of
the `Release` cell, which names the person who confirmed the shipment, and the
`Release` cell must still be one of the two forms above. If `revalidation` includes `implementation`, `tests`, or
`release`, offer to perform fresh checks and prepare a proposal clearing only
the domains supported by that fresh evidence. Evaluate that proposal while the
current source remains unchanged.

Require a `## Delivery evidence` table in the proposal with exactly one row for
every declared app: a substantive Implementation and Tests entry and a `Release`
entry that is release evidence or a delivery attestation. Require
applicable app requirements to be `done`, applicable API contracts to be
`implemented`, and no unresolved revalidation or open-question blocker after
the proposed fresh evidence is evaluated. Pending or `in-progress` requirement
pages and an `agreed` API contract may be proposed as complete only when the
verified delivery evidence supports that exact change; a draft API contract
blocks. Show exact affected requirement/API changes; preserve statuses already
complete and never apply a blanket update.

Ask the user, unless the request already gives the answers or says there are none
(ask only for what it does not cover, and do not stop for lessons learned: propose
the notes you have and say in your summary that no lessons learned were given):

"Any deviations from the spec to record? Any board review concerns that turned
out differently in implementation than expected? Any lessons learned?"

If the user provides notes, keep them as proposed `## Post-ship notes` content
until final confirmation. Show the complete feature, exact requirements/API,
status board, and log write set. Reread the source and context immediately before
confirmation and once again after it. Only after explicit confirmation may the
confirmed notes and the confirmed delivery evidence rows be written, the feature
become `done`/`none`,
exact verified requirements become `done`, an applicable API contract become
`implemented`, and the status board and a `log.md` entry in the log format that the wiki schema defines be written.

On the feature page change only the lifecycle metadata, `## Delivery evidence` and
`## Post-ship notes`, and add no other section heading (not even an empty
`## Reopen history`); in a linked requirement or API contract page change only `status`.

Partial app delivery remains `in-dev`; do not mark a feature done until all
declared apps have current delivery evidence. If a multi-file write is
partial, report the exact observed changes and stop for fresh recovery; no
transaction is implied. The preflight and any copied request are copy-only and
never authorize a write. Decline or cancel means no mutation.

If a board review happened, ask whether any concerns materialized or proved
unfounded. Record meaningful deviations rather than silently dropping them. This
action records shipment; it does not prove a future release or deployment beyond
the evidence the user and agent recorded.

## Rules

- write-capable skill
- ask for post-ship notes before changing the final status, unless the request already gives them
- write current-state pages: replace superseded content in place, state rationale as a current fact and keep history in `log.md` and the records; mark each claim `**Decided:**`, `**Observed:**`, `**Proposed:**` or `**Assumed:**` (gaps stay in the Open questions table) and link the evidence of every Decided and Observed claim: the processed intake item, a record or a URL (see Evidence labels in the wiki schema)

## Output behavior

Return:

- feature being closed out
- any post-ship notes recorded
- pages whose status changed
- final status summary

## Error and stop conditions

- if the feature file does not exist, return a clean missing-feature response
- if the user wants to cancel instead of marking the feature done, stop without writing
