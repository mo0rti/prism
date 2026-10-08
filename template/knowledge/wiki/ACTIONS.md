---
schema-version: 1
---

# Wiki lifecycle actions - registry, write scopes and action contracts

This file extends `SCHEMA.md` and `LIFECYCLE.md`, which are read first. It holds the lifecycle
action registry (sources, destinations, approver roles and write scopes), the common action
protocol and the contracts of the specification and PO handoff actions, and is read for every
lifecycle action. The statuses, owners, design tracks and evidence rules that the actions apply
are in `LIFECYCLE.md`.

---


## Lifecycle action registry

The generated workflow exposes these named, feature-only actions. Each requires the exact source
status/owner pair and, after final user confirmation, writes only the proposed feature and the
corresponding status board, index, log or evidence records. `D` is the design owner of the scope (see
`LIFECYCLE.md`, Design owner and design tracks).

| Action | Exact source | Destination | Primary responsibility |
|---|---|---|---|
| `po-specify` | `raw` + `po` | `specified` + `po` | Author a structured body from one raw page, with every criterion's ID and `applies-to`; keep facts and turn unknowns into owned questions. |
| `po-handoff` | `specified` + `po` | `ready-for-design` + `D` | Verify factual PO completeness and hand the specification to design. |
| `design-start` | `ready-for-design` + `D` | `in-design` + `D` | Start design work after rereading the assigned feature, and write the initial design tracks. |
| `design-ui-done` | `ready-for-design` or `in-design` + `D` | `in-design` + `D` | Settle the UI track: design pages that cover every app with a UI, or an exemption with a reason. |
| `tech-design-done` | `ready-for-design` or `in-design` + `D` | `in-design` + `D` | Settle the technical track: the technical design page, its test strategy and, for declared API work, the agreed API contract. |
| `design-handoff` | `ready-for-design` or `in-design` + `D` | `ready-for-dev` + `dev` | Verify both tracks are settled (settling either in the same confirmation) and prepare the app requirements. |
| `dev-start` | `ready-for-dev` + `dev` | `in-dev` + `dev` | Start implementation after rereading requirements and applicable API contracts. |
| `dev-done` | `ready-for-dev` or `in-dev` + `dev` | the minimum of the app stages: `in-dev` + `dev`, or `ready-for-qa` + `qa` once every app has delivered | Record the delivery evidence of the apps it names: the artifact, tests and implementation for each. |
| `dev-return-spec` | `ready-for-dev` or `in-dev` + `dev` | `specified` + `po` | Send the feature back to the PO: archive every evidence row, remove the design tracks and set the revalidation domains. |
| `dev-return-design` | `ready-for-dev` or `in-dev` + `dev` | `in-design` + `D` | Send the feature back to design: archive every evidence row; the affected tracks go back to `pending`, the other settled track awaits reaffirmation. |
| `qa-verify` | `in-dev` + `dev`, `ready-for-qa` + `qa` or `in-qa` + `qa` | the minimum of the app stages | Record QA rows for apps or integrations; the first row of an app opens its QA stage. |
| `qa-pass` | as `qa-verify` | the minimum of the app stages: `ready-for-release` + `release` once every app has passed | Pass the apps it names: a `pending` Release row for each, with the QA rows still missing in the same proposal. |
| `qa-fail` | as `qa-verify`, or `ready-for-release` + `release` | `in-dev` + `dev` | Send the apps it names back to development; their delivery, QA and Release rows move to Evidence history. |
| `qa-return-spec`, `qa-return-design` | as `qa-fail` | `specified` + `po`, or `in-design` + the design owner | Send the whole feature back to specification or design from QA (`feature-reopen`); refused when an app is released. |
| `scope-edit` | `ready-for-dev` up to `released` | the minimum of the app stages after the edit | Remove an app from the scope (the `feature-scope` skill from `ready-for-dev` on). |

`/dev-done` from `ready-for-dev` also starts development in the same write. Before `ready-for-dev`,
`/feature-scope` is an ordinary write that edits `apps` and the App scope section and, at `ready-for-design`
or `in-design`, sets the owner to the design owner of the new scope.

Bug handling is the `bug-update` skill, which selects one of the bug actions of `bugs/_FORMAT.md`. The release
actions and the routes back from released work are registered but answer `action_unavailable` in
this version of the board; a feature in `ready-for-release` stays there.

Each gated action needs a human who holds the role that approves it: `po` for `po-specify`,
`po-handoff` and `scope-edit`; the design owner role for `design-start` and `design-handoff`, and
`designer` for `design-ui-done` and `tech-lead` for `tech-design-done`; `dev` for `dev-start`,
`dev-done` and the returns from implementation; `qa` for `qa-verify`, `qa-pass`, `qa-fail` and the
routes back from QA. A `design-handoff` that settles the UI track also needs `designer`, and one that
settles the technical track `tech-lead`, on top of the design owner. The board checks the role when
it applies the action.

### Common action protocol

1. Resolve one canonical feature path and read `SCHEMA.md`, `LIFECYCLE.md`, this file, `status-board.md`, the
   feature, linked context, relevant requirements and API contracts, workspace
   identity, and current fingerprints. Intake folders are outside these actions.
2. If a Prism preflight is available, accept it only when the common envelope is
   schema 1, command facts name the requested action, transition capability
   is version 3 with the requested action in its per-action surfaces, transition
   version is 2, and the snapshot is consistent. Check the selected generated
   Codex or Claude file for its matching `prism:<command>-contract:v2` marker; a
   version string alone is insufficient. An older capability or generated
   instruction falls back to these direct-file rules after the instructions are refreshed.
3. Verify the exact source pair, action-specific checks, advisory and question
   state, and affected app evidence. Show observed facts and the complete proposed
   write diff. Unknown or blocked checks need review or repair guidance.
4. Every proposed write must name its exact feature, requirement, API, status board,
   index, log, evidence, revalidation, and history paths. Preserve unrelated
   statuses and API contracts.
5. Reread the source and context immediately before asking for final
   confirmation. A copied dashboard, clipboard request, or CLI preflight is
   read-only and never approval. Decline or cancel means no mutation. If a
   multi-file write is partial, report the exact observed changes and recover
   from a fresh reread. After confirmation, reread the same sources once more and
   compare the recorded identity, path, status, owner, advisory, revalidation, and
   fingerprint before writing anything.

Each action may change only what its row allows; the board refuses anything else
(`lifecycle_frontmatter_scope`, `lifecycle_body_scope`, `lifecycle_write_scope`):

| Action | Front matter | Feature sections | Other pages |
|---|---|---|---|
| `po-specify` | `status`, `owner`, `criteria-high-water` | every section except the evidence sections, which exist and stay empty | none |
| `po-handoff` | `status`, `owner`, `advisory-review`, `advisory-skip-reason`, `revalidation` | none | none |
| `design-start` | `status`, `owner`, `design-tracks`, `design-reaffirm` | none | none |
| `design-ui-done` | `status`, `owner`, `design-tracks` (`ui`, `ui-reason`), `design-reaffirm` | Design | this feature's `design/` pages |
| `tech-design-done` | `status`, `owner`, `design-tracks` (`technical`, `technical-reason`), `design-reaffirm` | Design | `technical-design/F-XXX-*.md`, `api-contracts/F-XXX.md` |
| `design-handoff` | `status`, `owner`, `revalidation`, `design-tracks` (the tracks it settles), `design-reaffirm` | Design | the pages of each track it settles, requirement pages |
| `dev-start` | `status`, `owner` | none | none |
| `dev-done` | `status`, `owner`, `app-revalidation` | Delivery evidence (add rows) | the named apps' requirement pages (to `done`), the API contract (to `implemented` once every app has delivered) |
| `dev-return-spec`, `dev-return-design` | `status`, `owner`, `revalidation`, `app-revalidation`, `design-tracks`, `design-reaffirm` | the three evidence tables (remove every row); Evidence history (one entry) | requirement pages and the API contract, only to a lower `status` |
| `qa-verify` | `status`, `owner` | QA verification (add or replace rows); Open questions (`qa` rows) | new bug pages |
| `qa-pass` | `status`, `owner`, `app-revalidation` | QA verification; Release (a `pending` row per app passed); Open questions (`qa` rows) | new bug pages |
| `qa-fail` | `status`, `owner`, `app-revalidation` | Delivery evidence, QA verification, Release (remove rows); Evidence history | the named apps' requirement pages and the API contract, to a lower `status`; new bug pages |
| `qa-return-spec`, `qa-return-design` | as the returns from implementation | as the returns from implementation | as the returns from implementation |
| `scope-edit` | `apps`, `status`, `owner`, `app-revalidation`, `criteria-high-water` | App scope; Acceptance criteria (three edits); the evidence tables and Evidence history | none |

### Specification and handoff boundaries

`po-intake` creates every new feature as `raw` + `po`, with the Summary, User story, Acceptance
criteria, Open questions and App scope sections from the intake material and the others empty.
`po-specify` adds what is missing: each of Design, Related features, API surface and Board review
summary gets one line of supported content or an explicit statement that nothing exists yet (for
example `Not started.`; under API surface, `None.`), the four evidence sections exist and stay
empty, every criterion gets its ID and `applies-to`, and the spec checks below hold before the
feature becomes `specified`.
An API surface other than an empty section or a plain statement that there is none
(`None.`) declares API work and needs an API contract page before `dev-start` (created by `tech-design-done`, or by a
`design-handoff` that settles the technical track), so `po-specify` writes `None.` unless the intake material or
an answered question states an API change. Open questions stay in the Open questions table, never in these sections.

`po-specify` must verify or author the complete required feature body from raw input and show and
confirm that body. An incomplete raw page is filled from supported facts and explicit questions
owned by `po`, `designer`, `tech-lead` or `dev`, and the write set includes the authored body; a raw
page that already passes the structured-output gate may be preserved, so the write set may hold only
status/metadata, status board, index, and log updates. No placeholder text is accepted as a
requirement. Existing advisory state is preserved, and a pending advisory remains a later-action blocker.

`po-handoff` is the stricter factual handoff from specified to design. Its completeness checks
include a nonempty Summary, exactly one substantive `## User story`, meaningful acceptance entries,
a nonempty matching app scope, no open PO questions, and a nonblank skip reason for a proposed
advisory skip. The destination owner is the design owner of the scope (`design_owner_mismatch` otherwise).

## PO handoff transition contract

The PO handoff action is a confirmation-gated transition from
`status: specified` and `owner: po` to `status: ready-for-design` and
`owner:` the design owner of the feature's scope.

- Resolve the requested ID to exactly one existing
  `knowledge/wiki/features/[F-XXX]-[slug].md` source file. `/po-handoff`
  accepts only `specified` + `po`; use `/po-specify` for the separate raw to
  specified structured-draft action.
  Do not invent a legacy adapter or a generic transition setter.
- Read the current `SCHEMA.md`, `LIFECYCLE.md`, `ACTIONS.md`, `status-board.md`, feature, linked context, workspace
  identity, and any available source fingerprint before preparing a preview, and again immediately before
  confirmation and before writing. Compare the unique path, identity, status, owner, advisory state, and
  fingerprint with any copied request or static snapshot; a mismatch or unavailable comparison blocks the
  write and requires a fresh preview.
- Factual PO completeness requires a non-empty Summary, one singular `## User
  story` section with content, meaningful acceptance criterion entries, a non-empty
  frontmatter `apps` list with a non-empty matching `## App scope` entry
  for every declared app, and no open questions owned by `po`. A `skipped`
  advisory requires a non-blank
  `advisory-skip-reason`. Semantic sufficiency remains a human or agent judgment.
- When advisory review is `pending`, offer an independent `/board-review F-XXX` (with its own confirmation
  and write rules), then reread all source files and rerun the checks. If the user declines, request an explicit
  non-blank reason and keep the skip fields as a proposal until the final handoff confirmation; evaluate that
  proposed skip as the `skipped` outcome for this preview while the source stays `pending`. Never silently skip review.
- A preview is not an approval or a status write. It shows the observed source fields, advisory and
  completeness checks, identity/fingerprint facts, exact destination fields, and every file that would change.
  Decline or cancel means no mutation.
- A dashboard or clipboard request is copy-only: it executes no agent, mutates no wiki
  and moves no board card. The Board derives columns from current source fields and
  cannot prove who changed them or whether confirmation happened.
- The selected generated handoff surface (Codex: `.agents/skills/po-handoff/SKILL.md`;
  Claude: `.claude/commands/po-handoff.md`) must contain `<!-- prism:po-handoff-contract:v2 -->`.
  A missing marker means older, unsupported instructions: refresh the file from the current
  template. A Prism version alone cannot prove capability.
- The optional `prism wiki transition-preflight F-XXX [path] --action po-handoff
  --json` response uses the common envelope with `schema_version: 1` and
  `command: "wiki transition-preflight"`. Its `facts` include
  `requested_action`, `transition_capability` (`version: 3`, `mode: "copy-only"`,
  the supported action list, per-action surfaces, and a consistent snapshot),
  and a per-feature `transition` (`version: 2`, `action`, `target_owner`,
  `supported`, `classification`, and surface `invocations`). A check has the status
  `pass`, `warning`, `review`, `blocked` or `unknown`; a `warning` is shown to the
  approver and never blocks the action. Use
  **Copy request** only for the selected invocation with `supported: true`,
  `classification: "ready"`, and a consistent snapshot. Blocked or unknown
  results are review/repair guidance.
