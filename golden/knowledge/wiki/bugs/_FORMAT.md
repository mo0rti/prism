# Bug page format

Use this format for every file in `wiki/bugs/`. Filename: `BUG-XXX-[slug].md`, with `BUG-` and the
number of the `id`, then lowercase words joined by hyphens. A bug page is a current-state page: it
states the bug as it is now, and the evidence rows that leave its tables are copied into `## Evidence
history`.

```markdown
---
id: BUG-XXX
title: [Bug title]
status: open | in-fix | fixed | verified | released | closed
owner: dev | qa | release | none
severity: critical | high | medium | low
blocking: true | false
apps: [list of app IDs the bug is in]
feature: F-XXX | none
found-in: [where it was found: an artifact such as build:reader-app#88, a release or a report]
environment: [short environment name, such as staging, local, ci or production]
sources: [paths to intake/processed/ items or other references, or []]
# Written only when set:
deferred-reason: [why a non-blocking bug is left for later]
close-reason: wont-fix: [reason] | duplicate | promoted
duplicate-of: BUG-NNN
promoted-to: F-XXX
regression-of: BUG-NNN
---

## Summary
One or two sentences: what is wrong and who it affects.

## Steps to reproduce
1. [step]

## Expected
What should happen.

## Actual
What happens.

## Impact
Who or what the bug affects, and how badly.

## Fix
| App | Artifact | Implementation | Tests | Basis |
|---|---|---|---|---|

## Verification
| App | Method | Artifact | Environment | Attempt | Result | Evidence | Basis |
|---|---|---|---|---|---|---|---|

## Release
| App | Target | Version | Attempt | Outcome | Record | Basis |
|---|---|---|---|---|---|---|

## Evidence history
Append-only entries, one for every action that removes evidence from the active tables.

### YYYY-MM-DD - [action]
- Reason: [why]
- Affected apps: [app IDs]
- Archived evidence:
  | Fix | reader-app | `build:reader-app#91` | [PR 40](https://git.example/lumen/pull/40) | `./gradlew test`: 90 passed | checked |
```

## Status and owner

| Status | Owner | Meaning |
|---|---|---|
| `open` | `dev` | Found; waiting for a developer. Triage (`severity`, `blocking`) changes only now. |
| `in-fix` | `dev` | A developer is fixing it. |
| `fixed` | `qa` | Every app of the bug has a Fix row; QA verifies it. |
| `verified` | `release` | Every app of the bug has a passing Verification row; the bug waits for a release. |
| `released` | `none` | `release-done` released the bug (every app of the bug). |
| `closed` | `none` | Closed with a disposition in `close-reason`. |

`released` and `closed` with `duplicate` or `promoted` are final. A recurrence is a new bug with
`regression-of: BUG-XXX`.

## Creating a bug

A new bug is `open` + `dev`, has none of `deferred-reason`, `close-reason`, `duplicate-of` and
`promoted-to`, and has empty Fix, Verification, Release and Evidence history sections
(`bug_creation_invalid`). Its ID is free (`bug_id_taken`); its `feature` names an existing feature
or `none`, and its `apps` are apps of that feature. `qa-verify`, `qa-pass` and `qa-fail` create a
bug in the same proposal that records the failure; `ingest` creates one from a defect report.

## Changing a bug

`bug-update` changes one existing bug page. The change selects the action, and each action may
change only the front matter keys and sections of its row (`bug_frontmatter_scope`,
`lifecycle_body_scope`):

| Action | From | To | Roles | Changes |
|---|---|---|---|---|
| triage | `open` | unchanged | `dev` or `qa` | `severity`, `blocking` |
| scope | `open`, `in-fix`, `fixed`, `verified` | unchanged; `fixed` or `verified` to `in-fix` when `apps` or `feature` change, with Fix and Verification archived | `qa` | `apps`, `feature`, `title`, `found-in`, `environment`, `sources` |
| start | `open` | `in-fix` | `dev` | `status`, `owner` |
| fixed | `in-fix` | `fixed` | `dev` | `status`, `owner`, a Fix row per app |
| verified | `fixed` | `verified` | `qa` | `status`, `owner`, a passing Verification row per app on the verification artifact |
| reverify | `verified` | unchanged | `qa` | a new passing Verification row on the current verification artifact; the old row is archived |
| reject | `fixed`, `verified` | `in-fix` | `qa` | `status`, `owner`; the failing row is written and archived with the active Fix and Verification rows |
| close, `wont-fix` | `open`, `in-fix`, `fixed`, `verified` | `closed` | `po` | `status`, `owner`, `close-reason: wont-fix: [reason]` |
| close, `duplicate` | `open`, `in-fix`, `fixed` | `closed` | `qa` | `close-reason: duplicate`, `duplicate-of` |
| close, `promoted` | `open`, `in-fix`, `fixed`, `verified` | `closed` | `po` | `close-reason: promoted`, `promoted-to` |
| defer, undefer | `open`, `in-fix`, `fixed` | unchanged | `po` | `deferred-reason` (only on a bug with `blocking: false`) |
| reopen | `closed` with `wont-fix` | `open` | `po` | `status`, `owner`, `close-reason` removed; Fix, Verification and Release archived |

A bug becomes `released` only inside `release-done`.

## Evidence

- **Fix** has one row for each app of the bug, written by `bug-update` to `fixed`. Artifact is
  `version:`, `build:`, `image:`, `package:` or `commit:` with its form (`artifact_reference_invalid`);
  Implementation and Tests are substantive references; Basis is `checked` or `attested`. A bug
  cannot be fixed while an app of its feature is in its QA cycle (`feature_in_qa_cycle`): fail
  the app first with `qa-fail`, citing the bug.
- **Verification** has one passing row for each app, on the verification artifact: the app's
  Delivery evidence artifact when the bug is linked to a feature app that is at `ready-for-qa` or
  later and not `released`, otherwise the Fix artifact (`bug_verification_required`). The attempt is
  `qa-<n>`, one more than the number of Evidence history entries that archived a Verification row.
  A rebuild after verification needs `reverify` or `reject` (`bug_verified_on_other_artifact`).
- **Evidence history** copies each archived row verbatim, prefixed by its section name (`Fix`,
  `Verification` or `Release`), under `- Archived evidence:`, with `- Reason:` and `- Affected
  apps:`. The entry is headed with the preview day and the action (`### YYYY-MM-DD - bug-reject`).

## Blocking

A bug blocks `qa-pass` and `release-done` for an app when its `feature` is the feature, its `apps`
include the app, its status is not `verified`, `released` or `closed`, and it is not deferred. A
blocking bug cannot be deferred (`bug_not_deferrable`).

## Duplicates

A bug closed as `duplicate` names the canonical bug in `duplicate-of`. The canonical bug exists, is
not the duplicate itself, is not closed and does not reach the duplicate through `duplicate-of`; it
has the duplicate's feature (or the duplicate's feature is `none`) and lists the duplicate's apps;
and it is not deferred when the duplicate is blocking. The rule is checked again whenever the
canonical bug changes (`duplicate_target_invalid`).

## Promotion

A bug closed as `promoted` names a feature in `promoted-to` that is not `released` and that lists the
bug page in `sources`, or the bug under Linked bugs in its latest Evidence history entry
(`bug_promotion_unreopened`). Create the feature with `ingest` and cite the bug page, or reopen the
feature first.
