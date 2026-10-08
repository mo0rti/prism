# QA verify - record the results of testing delivered apps

<!-- prism:qa-verify-contract:v1 -->

Use this skill to record what QA found when it tested the delivered work of a feature: one row for each app, or for
each integration of two or more apps, listing the acceptance criteria it covered and the result. It does not pass the
feature to release (`/qa-pass` does) and it does not send an app back to development (`/qa-fail`
does). The first QA row of an app opens its QA stage.

## Usage

`/qa-verify [F-XXX] [app ...]`

Without app names, the apps are those the tester reports.

## Read-only preflight

When available, use:

```text
prism wiki transition-preflight F-XXX [path] --action qa-verify --json
```

Accept it only with common envelope schema 1, command facts, capability version 3 and an action-specific
`qa-verify` surface, transition version 2 and a consistent snapshot. The Prism version alone does not prove support. If
any required fact, schema, action, capability or snapshot is missing or fails, fall back to direct-file checks. The
preflight is copy-only and never authorizes a write; it reports the QA rows as not yet supplied, because the proposal
adds them.

## Supported action

`in-dev` + `dev`, `ready-for-qa` + `qa` or `in-qa` + `qa` -> the minimum of the app stages (the status never moves
forward past an app that has not been tested)

Resolve exactly one `knowledge/wiki/features/[F-XXX]-[slug].md` and require one of those source pairs. An app row needs
the app at `ready-for-qa` or `in-qa`. An integration row needs every participant delivered with its current artifact and at
least one participant at `ready-for-qa` or `in-qa`. A missing, invalid, ambiguous or different source pair is a stop
condition.

## Evidence and confirmation

Read `knowledge/wiki/SCHEMA.md`, `knowledge/wiki/LIFECYCLE.md`, `status-board.md`, the complete feature (its acceptance
criteria with their `AC-n@v1:<hex>` revisions, its Delivery evidence and the QA rows already recorded), every bug page of the
feature, `knowledge/wiki/SETTINGS.md` (the delivery targets name the environments an app can be tested in) and the
workspace identity.

Get from the tester the criteria covered, the method, the artifact tested, the environment, the result and where the
evidence is. Add one row to the proposed feature page's `## QA verification` table, in the column order
`| Row | Criteria | Method | Artifact | Environment | Attempt | Result | Evidence | Basis |`:

- **Row**: an app ID, or `integration:` and the participants sorted and joined by `+`, for example
  `integration:catalog-api+reader-app`.
- **Criteria**: `AC-n@v1:<hex>` references joined by commas, copied from the criteria the feature page shows
  (`criterion_revision_stale` when the revision has changed; `criterion_not_applicable` when the criterion does not apply
  to the row: a per-app criterion is verified by the row of an app it lists, an integration criterion by an integration row
  of exactly its participants).
- **Method**: `automated`, `manual` or `exploratory`.
- **Artifact**: the delivered artifact of the app, as its Delivery evidence row names it (`qa_artifact_mismatch`
  otherwise). An integration row writes one `app=artifact` entry per participant, joined by `;`.
- **Environment**: `local`, `ci` or an environment the app's delivery target declares (`environment_unknown`).
- **Attempt**: `qa-<n>`, the current attempt of the app (the highest among the participants for an integration row;
  `qa_attempt_mismatch`).
- **Result**: `pass`, `fail` or `blocked`.
- **Evidence**: a URL or path.
- **Basis**: `checked` when you verified the evidence, `attested` when the approving human vouches for it. Say in your
  summary which rows are attested.

A row is replaced by a row with the same key and criterion in the current attempt (for example after a criterion
changed); any other row stays. Never rewrite a row the tester did not re-run. Ask for any value you do not have; never invent a
result.

A defect found while testing is a new bug page in the same proposal: `knowledge/wiki/bugs/BUG-XXX-[slug].md`, `open` +
`dev`, in the format of `knowledge/wiki/bugs/_FORMAT.md`, with `feature` the feature (or `none`), only apps of the
feature, and empty Fix, Verification, Release and Evidence history sections (`bug_creation_invalid`, `bug_id_taken`). Take the
next free bug number. A `fail` row records the failure; the bug records the defect.

The proposal may also resolve open questions owned by `qa`, each with its answer. It changes no other section and no front
matter beyond `status` and `owner`, which become the minimum over the app stages after the new rows (`app_stage_mismatch`
otherwise).

Show the complete feature, bug, status board and log write set. Reread the source and context immediately before
confirmation and once again after it. Only after explicit confirmation may the rows, the bug pages, the status, the status
board row and a `log.md` entry in the log format that the wiki schema defines be written.

If a multi-file write is partial, report the exact observed changes and stop for fresh recovery; no transaction is
implied. The preflight and any copied request are copy-only and never authorize a write. Decline or cancel means no
mutation.

## Rules

- write-capable skill
- one row per app or integration and criterion in the current attempt; never rewrite a row that was not re-tested
- a QA result is evidence of what the tester ran, not proof the feature works: record only what the tester reports
- write current-state pages: replace superseded content in place, state rationale as a current fact and keep history in `log.md` and the records; mark each claim `**Decided:**`, `**Observed:**`, `**Proposed:**` or `**Assumed:**` (gaps stay in the Open questions table) and link the evidence of every Decided and Observed claim: the processed intake item, a record or a URL (see Evidence labels in the wiki schema)

## Output behavior

Return:

- feature and the rows recorded, with each result
- which rows are checked and which are attested
- bugs created
- the feature's new status

## Error and stop conditions

- if the feature file does not exist, return a clean missing-feature response
- if the tester has no result to record, stop without writing
- if the user wants to cancel instead of recording the results, stop without writing
