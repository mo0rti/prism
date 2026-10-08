---
name: po-specify
description: "Promote one raw feature page to a structured specified draft after source checks and explicit confirmation. Use when raw wiki content is ready to become a PO-owned specification."
layers: [codex, command]
codex:
  display_name: "PO Specify"
  short_description: "Promote one raw feature page to a specified draft"
  default_prompt: "Use @@invoke:po-specify@@ F-XXX to validate and confirmation-gate the raw-to-specified feature transition."
  implicit: false
---

# PO specify - structure one raw feature page

<!-- prism:po-specify-contract:v2 -->

Read one raw feature page, prepare a canonical structured specification draft,
and, after explicit confirmation, write one feature-only transition:

`raw` + `po` -> `specified` + `po`

## Usage

`@@invoke:po-specify@@ [F-XXX]`

## Scope and source guard

- Resolve `[F-XXX]` to exactly one existing file at
  `knowledge/wiki/features/[F-XXX]-[slug].md`. A missing, invalid, or ambiguous
  ID is a stop condition.
- Accept only the exact source pair `status: raw` and `owner: po`.
- This action processes one feature page. It does not process, move, or rename
  anything under `knowledge/intake/pending/`, `processed/`, or `quarantined/`.
- Preserve the existing `advisory-review`, `sources`, `apps`, and valid
  tracked questions. Keep `owner: po`.
- Raw input is an authoring source. If it already has the canonical structured
  sections and substantive values required for `specified`, verify and preserve
  that body; otherwise author the missing structure from supported facts. In
  either case, show the body and metadata in the preview rather than performing
  an unverified status-only write.

## Read, preview, and confirmation

Read `knowledge/wiki/SCHEMA.md`, `knowledge/wiki/LIFECYCLE.md`, `knowledge/wiki/ACTIONS.md`, `status-board.md`, the complete feature, linked context,
and the workspace identity before preparing the preview. If the optional CLI is
available, use:

```text
prism --version
prism wiki transition-preflight F-XXX [path] --action po-specify --json
```

Accept a preflight only when it reports envelope schema 1, command facts,
capability version 3 with an action-specific `po-specify` surface, transition
version 2, the exact source pair, and a consistent current snapshot. A Prism
version alone is insufficient. If the probe is missing, old, unsupported, or fails, state the direct-file
fallback and follow `LIFECYCLE.md` and `ACTIONS.md`. The preflight is copy-only and never
authorizes a write.

Before using copied facts, reread this current skill or command, the `po-specify`
instructions of the other agent surface when available, SCHEMA, LIFECYCLE, ACTIONS, status
board, feature, linked context, and identity. A mismatch or unavailable comparison
requires a fresh preview.

Show the observed source fields, structural checks, proposed destination, and
the complete write set before asking for confirmation. The preview is copy-only;
it does not authorize a write. Immediately before confirmation, reread the
source, status board, identity, and linked context and compare the recorded path,
identity, status, owner, advisory state, and fingerprint.

## Structured draft preparation

Read the complete raw body and prepare a proposed canonical feature body. Carry
forward facts that are present in the raw page or linked workspace context and
do not invent product substance. The draft must show proposed values for all
required feature sections, including:

- `## Summary`
- `## User story`
- `## Acceptance criteria`
- `## App scope`
- `## Open questions`
- `## Design`
- `## Related features`
- `## API surface`
- `## Board review summary`
- `## Delivery evidence`, `## QA verification`, `## Release` and `## Evidence history`: the evidence sections exist as headings and stay empty; the evidence arrives with later work

A raw page written by `po-intake` already carries Summary, User story, Acceptance
criteria, Open questions, and App scope, and leaves the other sections empty. Complete Design,
Related features, API surface and Board review summary with one line each: supported content, or
an explicit statement that nothing exists yet (for example `Not started.`, `None identified.`,
`None.` under API surface, `Not reviewed yet.`). Add the four evidence sections as empty headings.

Give every acceptance criterion an ID and the apps that verify it: `- [ ] **Decided:** AC-1 [app] text`
for a criterion each listed app verifies in its own QA row, or `AC-2 [integration: app-a, app-b] text`
for one that two or more apps verify together. Number from 1, name every app of the scope in at least
one criterion, and set `criteria-high-water` in the front matter to the highest number used. A missing
ID, an invalid `applies-to`, a duplicate ID, an app named by no criterion or a wrong mark is rejected
(`criterion_id_required`, `invalid_applies_to`, `duplicate_criterion_id`, `app_without_criteria`,
`criteria_high_water_invalid`).

Any API surface text other than `None.`
declares API work and needs an API contract page before `dev-start`, so write `None.`
unless the intake material or an answered question states an API change. Keep open
questions in the Open questions table, never in these sections. The connected
board rejects an empty required section with `required_section_missing` and names
the section.

Unknown facts remain explicit owned questions for `po`, `designer`, `tech-lead` or `dev`.
An open question is valid structured output; `TODO`, `TBD`, copied template
filler, and empty placeholder requirements are not. Show the complete proposed
body diff together with the frontmatter, status board, and log metadata before asking
for confirmation. When structure or content is missing, the confirmed write set
includes the authored body. When the raw page already meets the structured draft
contract, preserve that valid body and show that no body rewrite is proposed;
the confirmed write set may then contain only the status/metadata, index, and log
updates. In both cases, never perform an unverified status-only write.

## Specification checks

- The feature ID and filename resolve to one canonical page.
- Required feature frontmatter and the feature page shape are valid.
- The declared app list is valid and its `## App scope` section is
  present and limited to the feature's apps.
- The proposed body (which may be unchanged when the raw body is verified as
  complete) supplies every required section with either supported content or an
  explicit owned question.
- Missing product facts are represented as explicit open questions owned by
  `po`, `designer`, `tech-lead` or `dev`; do not invent requirements or silently delete
  questions. Tracked questions, including open PO questions, are allowed at
  `specified`.
- Preserve the existing advisory state. A pending review remains pending and is
  still a blocker for later actions that require advisory completion.

These are observable structure checks. They do not claim semantic completeness
or authorize the next handoff.

## Write order and recovery

After a second confirmation-gated reread, write the confirmed structured body
and metadata, update the feature status to `specified`, keep `owner: po`,
update the matching `status-board.md` row and the feature's `index.md` line, and append the required `log.md` entry in the
log format that the wiki schema defines. Feature pages carry no date field; do not add one.
Do not move intake folders or write unrelated wiki files. If the user declines
or cancels, make no feature, index, or log change. If a multi-file write is
partially applied, report every file and observed field that changed, stop, and
require a fresh read before recovery; do not claim the update was transactional.

## Page rules

- write current-state pages: replace superseded content in place, state rationale as a current fact and keep history in `log.md` and the records; mark each claim `**Decided:**`, `**Observed:**`, `**Proposed:**` or `**Assumed:**` (gaps stay in the Open questions table) and link the evidence of every Decided and Observed claim: the processed intake item, a record or a URL (see Evidence labels in the wiki schema)

## Output

Return the exact source and destination fields, structural evidence, preserved
advisory/question state, proposed writes, and the final observed result. Never
claim that this action proves design, implementation, testing, or shipment.
