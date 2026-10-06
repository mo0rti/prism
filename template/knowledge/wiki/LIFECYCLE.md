---
schema-version: 1
---

# Wiki lifecycle protocol - features, board and advisory files

This file extends `SCHEMA.md`, which is read first. It holds the feature page format,
the status and owner lifecycle, the lifecycle action registry and the advisory file
formats. Read it, after `SCHEMA.md`, for every feature, board or advisory operation.

---


## Feature page format

Every file in `wiki/features/` must follow this format:

```markdown
---
id: F-XXX
title: [Feature name]
status: raw | specified | ready-for-design | in-design | ready-for-dev | in-dev | done
owner: po | designer | dev | none
apps: [list of app IDs this feature affects - use the app IDs `prism.workspace.yml` declares]
sources: [paths to intake/processed/ items that produced this page]
advisory-review: not-needed | pending | done | skipped
# Required and non-blank when advisory-review is skipped:
advisory-skip-reason: [reason]
# Optional only for an explicitly confirmed UI design exemption:
design: not-applicable
design-exemption-reason: [non-blank reason]
# Absent or [] until a reopen invalidates domains for revalidation:
revalidation: [specification | design | implementation | tests | release]
---

## Summary
One paragraph. What this feature does, why it exists, and what user problem it solves.
Written in business language, not technical language.

## User story
As a [persona from personas/], I want to [action], so that [business outcome].

## Acceptance criteria
- [ ] Condition 1 (testable, unambiguous)
- [ ] Condition 2

## Open questions
| # | Question | Owner | Status |
|---|----------|-------|--------|
| 1 | What is the fallback when the user is offline? | po | open |
| 2 | What does the empty state look like? | designer | open |
| 3 | Is real-time sync feasible without WebSockets? | dev | resolved: use polling |

## App scope
- **backend**: [what backend must implement, or "not in scope"]
- **mobile-android**: [what Android must implement, or "not in scope"]
- **mobile-ios**: [what iOS must implement, or "not in scope"]
- **web-user-app**: [what user web app must implement, or "not in scope"]
- **web-admin-portal**: [what admin portal must implement, or "not in scope"]

## Design
Link to design artifacts and key design decisions.
Format: [Description](../design/F-XXX-[slug].md) once design intake is complete.
This section is empty until /design-intake is run.

## Related features
- [F-XXX](F-XXX-[slug].md) - [why this relationship exists]

## API surface
High-level description of API changes required (expanded in api-contracts/).
Empty if no API changes are needed.

## Board review summary
Populated by /board-review command. Empty until then.
One paragraph summarizing the key concerns raised and what was resolved.

## Post-ship notes
Notes added after shipping. Populated by /dev-done command. Empty until then.

## Delivery evidence
| App | Implementation | Tests | Release |
|---|---|---|---|
| backend | [artifact or source reference] | [test command and result] | release: [URL of the release, tag or deployment record] |

One row is required for every declared app in the `/dev-done` proposal. Each
cell must contain a substantive, current reference that an agent can verify. A
file being present or a clean lint result does not prove implementation or
shipment.

The `Release` cell is release evidence or a delivery attestation, matched without
regard to case on its prefix:

- release evidence: `release: <reference>`, `tag: <reference>` or
  `deployment: <reference>`, where the reference is the URL of, or a workspace
  path to, a release, tag or deployment record
- delivery attestation: `attested by <Name>: <reference>`, where the reference is
  a URL or a workspace path to what that person checked

Any other `Release` cell is rejected with `release-evidence-required`: a commit or
pull request proves which code changed, not that it shipped.

## Reopen history
Append one record for every confirmed reopen. Keep the prior completion and
release evidence here, then remove it from the active `## Delivery evidence`
section so it cannot satisfy a later `/dev-done` automatically.

### YYYY-MM-DD - reopen-[spec|design|dev]
- Reason: [why the feature was reopened]
- Impact review: [what changed and what was assessed]
- Affected apps: [declared app IDs]
- Affected artifacts: [feature, design, requirement, API, implementation, test, or release paths]
- Prior completion/release evidence: [archived evidence, or links to the archived entries]
- Requirement/API invalidations: [exact affected pages and proposed statuses]
```

Owner values in the open-questions table must be one of: `po`, `designer`, `dev`.
Open-question status values must be one of: `open`, `resolved: [answer]`.

Each owner has one clarify action that resolves only that owner's open questions:
`/po-clarify` (`po`), `/design-clarify` (`designer`) and `/dev-clarify` (`dev`).
Each one preserves question text, owners and lifecycle fields. A clarify action
that changes a requirement-bearing section of the feature, a design page or a
app requirement page must carry the full text of at least one answer it
resolves in that section. `/dev-clarify` may update the feature's Acceptance
criteria, App scope and API surface sections and the What to build,
Technical constraints, API contract reference and Acceptance criteria sections of
that feature's existing app requirement pages; it leaves their frontmatter
unchanged and does not change a `done` feature. Open dev-owned questions block
`/dev-start` and `/dev-done`.

### Status and owner lifecycle

The `status` and `owner` fields together represent the feature's position in the
lifecycle. An approved handoff updates both fields together in the feature page;
updates across the feature page, index, and log are not a filesystem transaction.

| Status | Owner | Meaning |
|--------|-------|---------|
| raw | po | Captured by `/po-intake` with Summary, User story, Acceptance criteria, Open questions and App scope; `/po-specify` completes the structure |
| specified | po | Structured spec written, open questions may remain |
| ready-for-design | designer | PO has handed off; designer picks up |
| in-design | designer | Designer is actively working |
| ready-for-dev | dev | Design complete; developer picks up |
| in-dev | dev | Developer is actively building |
| done | none | Shipped |

### advisory-review field

This field tracks whether domain review has been done. Only specific commands set it:

- `not-needed` - set by `/po-intake` for features with no domain complexity
  (authentication flows, settings screens, CRUD operations, admin tools, infrastructure)
- `pending` - set by `/po-intake` for features with domain complexity. A board review
  must happen before dev can start.
- `done` - set by `/board-review` after a review is completed. Only this command sets it.
- `skipped` - set by `/po-handoff` or `/design-handoff` when the team explicitly
  decides to skip review. It requires a non-blank reason recorded in
  `advisory-skip-reason` frontmatter. For `/po-handoff`, the skip and reason stay
  as a proposal until that command's final handoff confirmation.

No other command touches the `advisory-review` field.

The lint command flags features in `ready-for-design`, `in-design`, `ready-for-dev`, or `in-dev` with `advisory-review: pending`
as incomplete. Setting `skipped` with a reason suppresses this flag.

### PO handoff transition contract

The PO handoff action is a confirmation-gated transition from
`status: specified` and `owner: po` to `status: ready-for-design` and
`owner: designer`.

- Resolve the requested ID to exactly one existing
  `knowledge/wiki/features/[F-XXX]-[slug].md` source file. `/po-handoff`
  accepts only `specified` + `po`; use `/po-specify` for the separate raw to
  specified structured-draft action.
  Do not invent a legacy adapter or a generic transition setter.
- Read the current `SCHEMA.md`, `LIFECYCLE.md`, `index.md`, feature, linked context, workspace
  identity, and any available source fingerprint before preparing a preview.
  Re-read them immediately before confirmation and once again before writing.
  Compare the unique path, identity, status, owner, advisory state, and fingerprint
  with any copied request or static snapshot; a mismatch or unavailable comparison
  blocks the write and requires a fresh preview.
- Factual PO completeness requires a non-empty Summary, one singular `## User
  story` section with content, meaningful acceptance criterion entries, a non-empty
  frontmatter `apps` list with a non-empty matching `## App scope` entry
  for every declared app, and no open questions owned by `po`. A `skipped`
  advisory requires a non-blank
  `advisory-skip-reason`. Semantic sufficiency remains a human or agent judgment.
- When advisory review is `pending`, offer an independent `/board-review F-XXX`.
  Preserve that command's own confirmation and write rules, then reread all source
  files and rerun the advisory and completeness checks after any board changes. If
  the user declines, request an explicit non-blank reason and keep the skip fields
  as a proposal until the final handoff confirmation. Evaluate that valid proposed
  skip as the `skipped` advisory outcome for this preview while leaving the current
  `pending` source unchanged. Never silently skip review.
- A preview is not an approval or a status write. It must show the observed source
  fields, advisory and completeness checks, identity/fingerprint facts, exact
  destination fields, and every feature/advisory/index/log file that would change.
  Decline or cancel means no feature, advisory, index, or log mutation.
- A dashboard or clipboard request is copy-only. It must not execute an agent,
  mutate the wiki, or move a board card. The intended process is a confirmed agent
  workflow followed by a fresh source snapshot. The Board derives columns from
  current source fields and cannot prove which human or agent changed them or
  whether confirmation happened.
- The selected generated handoff surface must contain
  `<!-- prism:po-handoff-contract:v1 -->`: Codex checks
  `.agents/skills/po-handoff/SKILL.md`, while Claude checks
  `.claude/commands/po-handoff.md`. The other surface is optional. A missing marker
  on the selected file means its instructions are older and unsupported; refresh
  that file from the current template before using the handoff. A Prism version
  alone cannot prove capability.
- The optional `prism wiki transition-preflight F-XXX [path] --action po-handoff
  --json` response uses the common envelope with `schema_version: 1` and
  `command: "wiki transition-preflight"`. Its `facts` include
  `requested_action`, `transition_capability` (`version: 2`, `mode: "copy-only"`,
  the supported action list, per-action surfaces, and a consistent snapshot),
  and a per-feature `transition` (`version: 1`, `action`, `target_owner`,
  `supported`, `classification`, and surface `invocations`). Use
  **Copy request** only for the selected invocation with `supported: true`,
  `classification: "ready"`, and a consistent snapshot. Blocked or unknown
  results are review/repair guidance.

### Lifecycle action registry

The generated workflow exposes these named, feature-only actions. Each action
requires the exact source status/owner pair and writes only the proposed feature
and the directly corresponding index/log or evidence records after final user
confirmation.

| Action | Exact source | Destination | Primary responsibility |
|---|---|---|---|
| `po-specify` | `raw` + `po` | `specified` + `po` | Author a canonical structured body from one raw page; preserve facts and represent unknowns as owned questions. |
| `po-handoff` | `specified` + `po` | `ready-for-design` + `designer` | Verify factual PO completeness and hand the specification to design. |
| `design-start` | `ready-for-design` + `designer` | `in-design` + `designer` | Start design work after rereading the assigned feature. |
| `design-handoff` | `in-design` + `designer` | `ready-for-dev` + `dev` | Verify design evidence or the confirmed UI design exemption, prepare app requirements and, when the API surface declares API work, create the agreed API contract. |
| `dev-start` | `ready-for-dev` + `dev` | `in-dev` + `dev` | Start implementation after rereading requirements and applicable API contracts. |
| `dev-done` | `in-dev` + `dev` | `done` + `none` | Verify current per-app implementation, tests, release evidence or delivery attestation, requirements, and APIs. |
| `reopen-spec` | `done` + `none` | `specified` + `po` | Revalidate specification, design, implementation, tests, and release domains after impact review. |
| `reopen-design` | `done` + `none` | `in-design` + `designer` | Revalidate design, implementation, tests, and release domains after impact review. |
| `reopen-dev` | `done` + `none` | `in-dev` + `dev` | Revalidate implementation, tests, and release domains after impact review. |

`/feature-reopen [F-XXX] [specified|in-design|in-dev]` selects the matching
reopen action. It is one feature and one route per invocation; it does not
provide a generic status setter.

#### Common action protocol

1. Resolve one canonical feature path and read `SCHEMA.md`, this file, `index.md`, the
   feature, linked context, relevant requirements and API contracts, workspace
   identity, and current fingerprints. Intake folders remain outside these
   feature-only actions.
2. If a Prism preflight is available, accept it only when the common envelope is
   schema 1, command facts identify the requested action, transition capability
   is version 2 with the requested action in its per-action surfaces, transition
   version is 1, and the snapshot is consistent. Check the selected generated
   Codex or Claude file for its matching `prism:<command>-contract:v1` marker;
   the other surface is optional. A version string alone is insufficient. An
   older capability or generated instruction falls back to these direct-file
   rules after the selected instructions are refreshed.
3. Verify the exact source pair, action-specific checks, current advisory and
   question state, and affected app evidence. Show observed facts and the
   complete proposed body/metadata/write diff. Unknown or blocked checks require
   review or repair guidance.
4. Every proposed write must name its exact feature, requirement, API, index,
   log, evidence, revalidation, and reopen-history paths. Preserve unrelated
   statuses and API contracts; never reset a shared contract or all features as
   a convenience.
5. Reread the source and context immediately before asking for final
   confirmation. A copied dashboard, clipboard request, or CLI preflight is
   read-only and never approval. Decline or cancel means no mutation. If a
   multi-file write is partial, report the exact observed changes and recover
   from a fresh reread; no transaction is implied. After confirmation, reread
   the same sources once more and compare the recorded identity, path, status,
   owner, advisory, revalidation, and fingerprint before writing anything.

#### Specification and handoff boundaries

`po-intake` creates every new feature as `raw` + `po`. It writes the Summary, User
story, Acceptance criteria, Open questions and App scope sections from the
intake material and leaves Design, Related features, API surface, Board review
summary and Post-ship notes empty. `po-specify` adds what is missing: each of
those five sections gets one line of supported content or an explicit statement
that nothing exists yet (for example `Not started.`; under API surface, `None.`),
and the spec checks below are satisfied before the feature becomes `specified`.
An API surface other than an empty section or a plain statement that there is none
(`None.`) declares API work and needs an API contract page before `dev-start`, which
`design-handoff` creates, so `po-specify` writes `None.` unless the intake material or
an answered question states an API change. Open questions stay in the Open questions table, never in these
sections.

`po-specify` must verify or author the complete required feature body from raw
input. It must not merely change status, index, and log without showing and
confirming the body. When the raw page is incomplete, the confirmed write set
includes the authored body. A raw page that already passes the complete
structured-output gate may be preserved after verification; in that case the
confirmed write set may contain only status/metadata, index, and log updates.
An incomplete raw page is filled from supported facts and explicit questions
owned by `po`, `designer`, or `dev`. No placeholder text is accepted as a
requirement. Existing advisory state is preserved, and a pending advisory remains
a later-action blocker.

`po-handoff` remains the stricter factual handoff from specified to design. Its
completeness checks include nonempty Summary, exactly one substantive `## User
story`, meaningful acceptance entries, a nonempty matching app scope, no
open PO questions, and a nonblank skip reason when a proposed advisory skip is
used. The proposal is evaluated without writing the pending advisory early.

#### Design exemption

For an app with a UI (`has-ui`), `design-handoff` requires design evidence unless the feature
frontmatter includes `design: not-applicable` and a nonblank
`design-exemption-reason`, and the user explicitly confirms that exemption in
the final write preview. A non-UI feature does not need a design page or an
exemption field. The exemption applies to the feature and declared UI scope;
it does not silently waive other requirements.

#### API contract at design handoff

When the feature's API surface declares API work and no API contract exists for it,
`design-handoff` creates `api-contracts/F-XXX.md` as a new page with `status:
agreed`; the user confirming the handoff preview is the agreement. The page is
written only from the API surface: each endpoint as `METHOD /path`, using the paths
the API surface names (or, when it names none, a resource word it uses), and only data
models that the API surface or a listed endpoint names. The handoff writes no
contract when the API surface declares none, never rewrites an existing contract, and
creates no second contract for a feature that a linked or existing page already covers.
Requirement pages link the contract in `## API contract reference`. `dev-start` accepts
an `agreed` contract and blocks on a `draft` one; `dev-done` marks the contract
`implemented`.

API work needs an app that serves an API: when the API surface declares API work, at
least one active app in the feature's `apps` must have the `serves-api` capability
(`unknown` counts as serving one). Otherwise lint reports `api-surface-without-api-app`
for the feature before `done`, and `design-handoff`, `dev-start` and `dev-done` block
with that code (`api_surface_without_api_app` on the connected board).

#### Delivery and revalidation

`dev-done` means shipped for every app in the feature's `apps` scope. The active
Delivery evidence table must contain, per app, substantive and verifiable
Implementation and Tests entries and a `Release` entry that is release evidence or
a delivery attestation, and applicable requirements/API contracts must be
complete. Pending or `in-progress` requirement pages and an `agreed` API contract
may be proposed as complete by `dev-done` only after the exact implementation,
test, and release evidence is verified; a draft API contract blocks. Agents
verify actual artifacts and results; table text, file presence,
or lint alone is insufficient. Partial delivery remains `in-dev`: every app in
scope needs a valid row.

The `Release` cell is one of two forms, matched without regard to case on its prefix:

- release evidence: `release: <reference>`, `tag: <reference>` or
  `deployment: <reference>`, where the reference is the URL of, or a workspace path
  to, a release, tag or deployment record
- delivery attestation: `attested by <Name>: <reference>`, where a named person
  confirms the shipment and the reference is a URL or a workspace path to what they
  checked

The reference is the first word after the prefix, and it must be substantive. A
commit or pull request proves which code changed, not that it shipped, so a bare
commit SHA, a pull-request or merge-request URL, `merged`, a branch name and free
text without a prefix do not satisfy `dev-done`. They are rejected with
`release-evidence-required`: by lint for a feature that is `done`, by the
`dev-done` transition check, and by the board as `release_evidence_required`. An app
in an external repository keeps its evidence there and links it by URL; an
unresolved checkout in `prism.local.yml` never blocks evidence given by link. The
`Implementation` and `Tests` cells keep their rule: a substantive reference.

Delivery evidence is an input to `dev-done`. The developer supplies, for each
declared app, the implementation, test and release references, and the
proposal writes them into the `## Delivery evidence` table in the same preview
as the status change; a table already filled in an earlier edit is also valid
input. A proposal whose table is absent, has no rows, or has a placeholder or
missing cell keeps the feature `in-dev`. A reference the agent cannot check is
recorded in `## Post-ship notes` as the developer's attestation, which the
developer confirms with the final confirmation. That attestation stands in for the
agent's own check: with it, the agent may propose the exact requirement pages and
API contract that the evidence covers as complete, and says in its summary that it
did not verify the references itself. It differs from the delivery attestation of
the `Release` cell: the first says the agent could not verify a reference and the
developer vouches for it, the second says a named person confirmed the shipment and
links what they checked. The `Release` cell must be one of the two forms either way.
The agent must not invent delivery evidence or imply that an absent or incomplete
table is complete.

An active `revalidation` list invalidates current readiness even when older
status fields or evidence still say done. `dev-done` may perform fresh checks and
propose clearing only the revalidated domains before final confirmation; it must
evaluate that proposal while the source remains unchanged. Already complete
requirement/API statuses are preserved, and only exact evidence-backed changes
are written.

#### Reopen contract

Every reopen requires an impact review and a proposed route before confirmation.
The preview records the reason, route, date, affected apps and artifacts,
prior completion/release evidence, and exact affected requirement/API status
invalidations. On confirmation, append the record to `## Reopen history`, copy
the prior active Delivery evidence into that history, remove it from the active
Delivery evidence section, and set the route's active `revalidation` domains.
Preserve unaffected evidence only when it is explicitly reaffirmed after the
impact review. Affected per-feature requirement pages are invalidated with
exact proposed statuses (`pending` for new or changed requirements/design, or
`in-progress`/`pending` for implementation fixes according to actual work), and
the prior status is retained in the history. Shared API contracts are marked by
affected scope only; no blanket reset is allowed. `po-handoff` clears verified
specification, `design-handoff` clears verified design, and `dev-done` clears
implementation/tests/release only after fresh evidence.

**App scope and membership.** A feature's scope is its `apps` list. The workspace's apps
change over time, and a change never edits a feature's scope by itself:

- Adding an app (`prism app add`) leaves every existing feature's `apps` as it is. A
  feature gains the app only by an explicit scope edit, recorded in `log.md`.
- Retiring an app (`prism app retire <id>`) sets `status: retired` in
  `prism.workspace.yml` and deletes no code, wiki page, requirement page or evidence.
  A retired app stays valid in the `apps` of a feature that is `done`, as history.
  Every feature before `done` that still lists it is flagged `app-retired-in-scope`:
  lint reports an error and every lifecycle action on that feature is blocked with
  that code until its `apps` is edited explicitly.
  A new feature, and any edit that adds a retired app to a feature's scope, is
  rejected with `app-retired`.
- Re-pointing a feature from one app to another is an explicit scope edit through the
  normal lifecycle: the feature's current owner edits `apps`, its `## App scope`
  entry and its app requirement pages, and records the change in `log.md`. No command
  re-points features automatically.


---

## Advisory file formats

`wiki/advisory/` holds three artifact types:

- `BOARD.md` - the current advisory board composition generated by `setup-project`
- `PROJECT_FOUNDATION.md` - the setup interview, risk framing, and initial board rationale
- `F-XXX-review.md` - per-feature board review outputs from `/board-review`

### PROJECT_FOUNDATION.md format

```markdown
# Project Foundation

## Project identity
- Name: [project name]
- Description: [one-sentence summary]
- Apps: [backend, web-user-app, ...]
- Auth methods: [if known]
- Infrastructure choices: [if known]
- Important correction or note: [optional]

## Setup interview

### 1. Primary users and trust
**Question:** Who are your primary users, and what do they trust this app to get right?
**Answer:** [confirmed answer]

### 2. Core decision or calculation
**Question:** What is the most important decision or calculation this app makes on behalf of users?
**Answer:** [confirmed answer]

### 3. Failure consequences
**Question:** What could go wrong if the app gets that wrong?
**Answer:** [confirmed answer]

### 4. Vulnerable groups
**Question:** Are there any user groups who might be especially vulnerable to a mistake?
**Answer:** [confirmed answer]

## Risk summary
- Core trust surface: [bullets]
- Primary failure modes: [bullets]
- Business impact: [bullets]
- Vulnerable groups: [bullets]
- Expertise gaps: [bullets]

## Why this board
Short paragraph explaining why the selected advisory board composition fits the
project's domain risks.

## Seed artifacts from setup
- [BOARD.md](BOARD.md)
- [persona or rule links created during setup]
```

### F-XXX-review.md format

Output format for `/board-review`. One page maximum.

```markdown
---
feature-id: F-XXX
reviewed: YYYY-MM-DD
board-members-consulted: [list of board member names from BOARD.md]
---

## 1. Conflicts
Does this feature conflict with anything already built or decided?
Named conflicts only - reference specific feature IDs, ADR IDs, or business rule IDs.
If none: "No conflicts identified."

## 2. Gaps
Is there anything missing from the current spec that will block development before it starts?
If none: "Spec is complete."

## 3. Build order
Across apps, what must be built first?
If no dependencies: "No cross-app ordering constraints."

## 4. Biggest risk
One sentence. What is most likely to cause this feature to fail, cause user harm, or
take significantly longer than expected?

## Board perspective summaries
[One short paragraph per board member who has a relevant concern.]
[Only include members with something substantive to say.]

## Actions required before dev starts
- [ ] [Specific action with owner - po / designer / dev]

## Actions that can be deferred
- [Action that can be addressed post-ship with acceptable risk]
```

