# QA pass - pass apps through QA

<!-- prism:qa-pass-contract:v1 -->

Use this skill when QA is satisfied with one or more apps of a feature: each gets a `pending` Release row, which moves the
app to `ready-for-release`. The proposal may carry the QA rows that are still missing, so a clean run is one approval. A
feature whose apps have all passed is `ready-for-release`.

## Usage

`/qa-pass [F-XXX] [app ...]`

Without app names, the apps are those the tester reports as passed.

## Read-only preflight

When available, use:

```text
prism wiki transition-preflight F-XXX [path] --action qa-pass --json
```

Accept it only with common envelope schema 1, command facts, capability version 3 and an action-specific `qa-pass`
surface, transition version 2 and a consistent snapshot. The Prism version alone does not prove support. Otherwise fall
back to direct-file checks. The preflight is copy-only and never authorizes a write.

## Supported action

`in-dev` + `dev`, `ready-for-qa` + `qa` or `in-qa` + `qa` -> the minimum of the app stages: `ready-for-release` +
`release` once every active app has passed

Resolve exactly one feature page and require one of those source pairs. Each named app is at `ready-for-qa` or `in-qa`
(`app_stage_mismatch`).

## Evidence and confirmation

Read `knowledge/wiki/SCHEMA.md`, `knowledge/wiki/LIFECYCLE.md`, `knowledge/wiki/ACTIONS.md`, `status-board.md`, the complete feature (criteria with
their revisions, Delivery evidence, QA verification, Release, Evidence history), every bug page of the feature,
`knowledge/wiki/SETTINGS.md` and the active `revalidation` and `app-revalidation` domains.

The proposal:

- adds the QA rows that are still missing, in the format of `/qa-verify` (the same checks apply to them);
- adds one `pending` row to the proposed `## Release` table for each app it passes, in the column order
  `| App | Target | Version | Attempt | Outcome | Record | Basis |`: Target `—`, Version the app's delivered artifact,
  Attempt `release-<n>` (one more than the number of release records that delivered the app for this feature), Outcome
  `pending`, Record `—`, Basis `—`. A staging row names an environment of the app as its Target and `—` as its attempt;
  it is informational;
- clears the `qa` domain of each passed app in `app-revalidation`, and nothing else;
- sets the feature's status and owner to the minimum over the app stages;
- may resolve open questions owned by `qa`.

The board refuses the pass when any of these fails:

- coverage of each named app: every criterion that lists the app has a passing row of the app at its current revision, on its
  current artifact, in its current attempt (`criterion_not_covered`); every integration criterion naming the app has a
  passing row of exactly its participants with every participant's artifact current (`integration_not_covered`); no row of
  the current attempt is `fail` or `blocked` (`qa_result_failed`);
- a bug of the feature that lists the app and is not `verified`, `released` or `closed` blocks the pass unless it is deferred
  (`open_bug_blocks_qa`); a verified bug whose Verification row is on another artifact than the current verification artifact
  needs `bug-update reverify` or `reject` (`bug_verified_on_other_artifact`); a closed duplicate whose canonical bug no longer
  qualifies is `duplicate_target_invalid`;
- an open question owned by `po`, `designer`, `tech-lead`, `dev` or `qa` that the proposal leaves open, a pending feature
  `revalidation` domain, and a pending `implementation` or `tests` domain of a named app block the pass;
- with `qa-separate-from-dev: true` in `SETTINGS.md`, the human who approves must not be the grant that produced, recovered or
  repaired the Delivery evidence of a named app (`separation_required`; `separation_unverifiable` when the board has no
  record of who delivered it).

Show the complete feature, status board and log write set. Reread the source and context immediately before confirmation
and once again after it. Only after explicit confirmation may the rows, the status, the status board row and a `log.md`
entry be written.

If a multi-file write is partial, report the exact observed changes and stop for fresh recovery; no transaction is
implied. Decline or cancel means no mutation. This action records that QA passed; it does not release anything.

## Rules

- write-capable skill
- one Release row per passed app; never rewrite a Release row that has an attempt
- write current-state pages: replace superseded content in place, state rationale as a current fact and keep history in `log.md` and the records; mark each claim `**Decided:**`, `**Observed:**`, `**Proposed:**` or `**Assumed:**` (gaps stay in the Open questions table) and link the evidence of every Decided and Observed claim: the processed intake item, a record or a URL (see Evidence labels in the wiki schema)

## Output behavior

Return:

- feature and the apps passed
- the QA rows added, with their basis
- bugs that were checked
- the feature's new status

## Error and stop conditions

- if the feature file does not exist, return a clean missing-feature response
- if coverage or a bug blocks the pass, report the board's code and what to do next, and stop without writing
- if the user wants to cancel, stop without writing
