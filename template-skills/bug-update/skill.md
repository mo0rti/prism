---
name: bug-update
description: "Move one bug through its lifecycle. Use to triage, scope, start, fix, verify, reverify, reject, close, defer or reopen a bug, recording the fix and verification evidence."
layers: [codex, command]
codex:
  display_name: "Bug Update"
  short_description: "Move one bug through triage, fix, verification and closure"
  default_prompt: "Use @@invoke:bug-update@@ BUG-XXX triage|scope|in-fix|fixed|verified|reverify|reject|closed|defer|undefer|open to change one bug page."
  implicit: false
---

# Bug update - move one bug through its lifecycle

<!-- prism:bug-update-contract:v1 -->

Use this skill to change one existing bug page in `knowledge/wiki/bugs/`. A bug is created by `@@invoke:qa-verify@@`,
`@@invoke:qa-pass@@`, `@@invoke:qa-fail@@` or `@@invoke:ingest@@`, never by this skill. The change you propose selects the
action; each action may change only the front matter keys and sections of its row (`bug_frontmatter_scope`).

## Usage

`@@invoke:bug-update@@ BUG-XXX triage|scope|in-fix|fixed|verified|reverify|reject|closed|defer|undefer|open`

## Actions

| Argument | From | To | Approver | You change |
|---|---|---|---|---|
| `triage` | `open` | unchanged | `dev` or `qa` | `severity`, `blocking` |
| `scope` | `open`, `in-fix`, `fixed`, `verified` | unchanged (see below) | `qa` | `apps`, `feature`, `title`, `found-in`, `environment`, `sources` |
| `in-fix` | `open` | `in-fix` + `dev` | `dev` | `status`, `owner` |
| `fixed` | `in-fix` | `fixed` + `qa` | `dev` | `status`, `owner`, the Fix rows |
| `verified` | `fixed` | `verified` + `release` | `qa` | `status`, `owner`, the Verification rows |
| `reverify` | `verified` | unchanged | `qa` | the Verification rows and Evidence history |
| `reject` | `fixed`, `verified` | `in-fix` + `dev` | `qa` | `status`, `owner`, Fix, Verification and Evidence history |
| `closed` | `open`, `in-fix`, `fixed`, `verified` | `closed` + `none` | `po` (`qa` for a duplicate) | `status`, `owner`, `close-reason` and its key |
| `defer`, `undefer` | `open`, `in-fix`, `fixed` | unchanged | `po` | `deferred-reason` |
| `open` | `closed` (`wont-fix`) | `open` + `dev` | `po` | `status`, `owner`, `close-reason`, Fix, Verification, Release, Evidence history |

## Read first

Read `knowledge/wiki/SCHEMA.md`, `knowledge/wiki/LIFECYCLE.md`, `knowledge/wiki/bugs/_FORMAT.md`, the bug page, every other
bug page (duplicates and IDs), the linked feature page (when the bug links one) with its Delivery evidence and QA rows, and
`knowledge/wiki/SETTINGS.md`.

## Rules of each action

- **triage** runs only while the bug is `open`. A deferred bug cannot become blocking.
- **scope** changes the bug's apps or feature; `feature` names an existing feature or `none`, and `apps` are apps of that
  feature (`bug_feature_missing`, `bug_apps_outside_feature`). On a `fixed` or `verified` bug a change of `apps` or `feature`
  resets it to `in-fix` + `dev` and archives its Fix and Verification rows in one `### <today> - bug-scope` Evidence history
  entry. A closed duplicate whose canonical bug is this bug is checked again (`duplicate_target_invalid`).
- **in-fix** needs a bug that is not deferred.
- **fixed** adds one Fix row for each app of the bug (`| App | Artifact | Implementation | Tests | Basis |`;
  `bug_fix_evidence_required`). It is refused while an app of the bug's feature is in its QA cycle
  (`feature_in_qa_cycle`): fail the app first with `@@invoke:qa-fail@@`, citing the bug.
- **verified** adds one passing Verification row for each app, on the verification artifact (the app's delivered artifact when the
  bug is linked to a feature app at `ready-for-qa` or later that is not released, otherwise the Fix artifact;
  `bug_verification_required`), in the attempt `qa-<n>` and an environment the app can be tested in. With
  `qa-separate-from-dev` on, the approving human must not be the grant that produced, recovered or repaired the Fix evidence
  (`separation_required`).
- **reverify** archives the old Verification rows and writes new passing rows on the current verification artifact, in the next
  attempt.
- **reject** writes the failing Verification row and archives it, with the active Fix and Verification rows, in one
  `### <today> - bug-reject` entry; neither table keeps a row.
- **closed** sets `close-reason`: `wont-fix: <reason>` (the product owner approves), `duplicate` with `duplicate-of` naming the
  canonical bug (QA approves; the canonical bug exists, is not closed, has the same feature and covers the apps, and is not
  deferred for a blocking duplicate), or `promoted` with `promoted-to` naming a feature that is not released and lists the bug
  page in `sources` or the bug under Linked bugs in its latest Evidence history entry (`bug_promotion_unreopened`).
- **defer** sets `deferred-reason` on a bug with `blocking: false` (`bug_not_deferrable`); **undefer** removes it.
- **open** reopens a bug closed `wont-fix`: it archives the Fix, Verification and Release rows and removes `close-reason`. It is
  refused once any app of the bug has a released Release row (`bug_reopen_after_release`); a recurrence is a new bug with
  `regression-of`.
- A bug becomes `released` only inside `release-done`.

An Evidence history entry is headed `### <today> - <action>`, lists `- Reason:` and `- Affected apps:`, and copies each archived
row verbatim under `- Archived evidence:` as a table row that starts with its section name (`Fix`, `Verification` or `Release`).

## Confirmation

Show the complete bug page change. Reread the bug, the feature and the other bugs immediately before confirmation and once
again after it. After explicit confirmation write the page, its index line and a `log.md` entry. If a multi-file write is
partial, report the exact observed changes and stop for fresh recovery. Decline or cancel means no mutation.

## Rules

- write-capable skill
- one bug page per proposal; never create a bug here
- never invent fix or verification evidence: get the artifact, implementation, tests and results from the people who produced them
- write current-state pages: replace superseded content in place, state rationale as a current fact and keep history in `log.md` and the records; mark each claim `**Decided:**`, `**Observed:**`, `**Proposed:**` or `**Assumed:**` (gaps stay in the Open questions table) and link the evidence of every Decided and Observed claim: the processed intake item, a record or a URL (see Evidence labels in the wiki schema)

## Output behavior

Return:

- the bug, the action and its new status and owner
- the evidence rows written and whether each is checked or attested
- the rows archived

## Error and stop conditions

- if the bug page does not exist, return a clean missing-bug response
- if the change matches no action above, say which fields it changes and stop without writing
- if the user wants to cancel, stop without writing
