# Release record format

Use this format for every file in `wiki/releases/`. Filename: `REL-XXX.md`, where `XXX` is the number of the
`id` with at least three digits and no other padding (`REL-001`, `REL-042`, `REL-1042`). A release record is a
dated record: `release-done` writes it once and nothing rewrites it. It states what one release, rollback or
redeploy delivered, to which target, in which version and with which outcome. It does not state what runs now:
the latest record for an app and a target says what is known.

```markdown
---
id: REL-XXX
title: [What this record delivers]
date: YYYY-MM-DD
operation: [the operation that wrote it]
outcome: released | failed | partial | rolled-back
features: [F-XXX, or []]
bugs: [BUG-XXX, or []]
# Written only when set:
retry-of: REL-NNN
rollback-of: REL-NNN
---

## Summary
One or two sentences: what was delivered, where, and how it ended.

## Delivery
| Item | App | Target | Version | Attempt | Outcome | Evidence | Basis |
|---|---|---|---|---|---|---|---|
| F-XXX | catalog-api | production | `build:catalog-api#412` | release-1 | released | deployment: https://ci.example/deploy/412 | checked |

## Contracts
### F-XXX catalog-api
- Contract: `F-XXX@v1:c1:[64 hex digits]`

````markdown
[the API contract page, verbatim]
````

## Rollback
None.

## Notes
None.
```

## Fields

- `id` is `REL-` and the number. The next record takes one more than the highest number on disk, allocated when the
  release is applied (`release_sequence_invalid`, `release_id_taken`). Recovery and repair keep the number already
  assigned, including for a record written by an operation that was abandoned.
- `date` is the preview day (`record_date_invalid`).
- `operation` names the operation that wrote the record. A proposal carries `operation: pending`; the board writes the
  ID of the operation that applies it, and repair leaves it unchanged.
- `outcome` follows the Delivery rows: `released` when every row is released, `failed` when none is, `partial`
  otherwise; `rolled-back` only on a rollback record.
- `features` and `bugs` list the items of the Delivery rows.
- A rollback record says in its `## Rollback` section what was rolled back and why; `None.` is not an answer there.
- `retry-of` names the record this one retries: a failed release, or for a redeploy the rollback or the failed redeploy it
  follows. `rollback-of` names the delivery a rollback rolls back.

## Kinds of record

| Kind | Marker | Rows |
|---|---|---|
| Release | no `rollback-of`; `retry-of`, when set, names an earlier release | One row per (item, app) delivered, attempt `release-<n>`, outcome `released` or `failed`. |
| Rollback | `rollback-of: REL-NNN` | One row per item that delivery carried for each (app, target) rolled back, attempt `—`, outcome `rolled-back`. |
| Redeploy | `retry-of` names a rollback or a failed redeploy | One row per item of the current delivery, attempt `—`, outcome `released` or `failed`, at the version of the current delivery. |

## Delivery

- **Item** is a feature (`F-XXX`) or a bug (`BUG-XXX`); **App** is one of its apps. A feature row and a bug row for the same
  app and target ship together.
- **Target** is the app's delivery target in `SETTINGS.md` when the release was recorded. **Version** is an artifact
  (`version:`, `build:`, `image:`, `package:` or `commit:` and its form): the artifact QA verified, or for a bug the bug's
  verification artifact.
- **Attempt** is `release-<n>`: one more than the release records that delivered the item for the app, rollbacks and
  redeploys excluded.
- **Outcome**: every row for one app and target in a record has the same Version and Outcome
  (`release_artifact_conflict`). A deploy rolled back within its own attempt is `failed`, and the Rollback section says so.
- **Evidence** is `release:`, `tag:`, `deployment:`, `store:` or `package:` and a URL or a path in the workspace. A commit
  or a pull request proves which code changed, not that it shipped, and is not accepted.
- **Basis** is `checked` (the proposer verified the evidence) or `attested` (the approving human vouches for it).

The Release row of the feature or the bug agrees with its Delivery row on target, version and outcome
(`release-row-record-mismatch`). A feature app released by a bug fix names the record that delivers the bug.

## Contracts

For each delivered feature row that cites an API contract, the record copies that contract page verbatim under
`### F-XXX <app>`, with its citation (`F-XXX@v<version>:c1:<digest>`), in a fence longer than any run of backticks inside it.
The digest of the snapshot is the citation of the Delivery evidence row. A released app is checked against its snapshot,
because the contract may be revised or reopened later. A rollback or redeploy record snapshots nothing.

## Current delivery

The current delivery of an (app, target) is the highest-numbered record with a `released` row for it, redeploys
included. A rollback names it in `rollback-of` (`rollback_target_invalid`); a redeploy follows the latest record for the
app and target, which is a rollback of the current delivery or a failed redeploy of it. A feature or bug row records its own
delivery and is not rewritten by a rollback or a redeploy.
