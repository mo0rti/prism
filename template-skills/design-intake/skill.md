---
name: design-intake
description: "Attach design artifacts to a feature. Use when processing one pending design intake folder into a design page, feature design linkage, open questions, and intake disposition."
layers: [codex, command]
codex:
  display_name: "Design Intake"
  short_description: "Attach design artifacts to a feature and create its design page"
  default_prompt: "Use @@invoke:design-intake@@ F-XXX [folder-name] to process pending design input into a feature-linked design page."
  implicit: false
---

# Design intake — attach design artifacts to a feature

Use this skill to process one pending design intake folder for one feature.

## Usage

`@@invoke:design-intake@@ [F-XXX] [folder-name]`

The folder is named `YYYY-MM-DD-slug`: the day the source was captured, then lowercase words
joined by hyphens, for example `2026-10-06-checkout-design`. The connected board rejects any other name.

## Workflow

1. Read `knowledge/wiki/SCHEMA.md` and `knowledge/wiki/LIFECYCLE.md`
2. Read `knowledge/wiki/features/[F-XXX]-[slug].md`
3. Read `knowledge/wiki/business-rules/`
4. Read `knowledge/wiki/advisory/[F-XXX]-review.md` if it exists — design must not
   contradict board review findings
5. Read all files in `knowledge/intake/pending/[folder-name]/`; if the folder is not named `YYYY-MM-DD-slug`, stop and ask the user to rename it
6. Run a conflict check, then summarize your interpretation:
   - Which feature flows does this design address?
   - What key design decisions does it make that affect implementation?
   - Which UI states are covered and which are missing?
   - Does any design decision conflict with the feature spec, business rules, ADRs,
     or board review findings?

   A conflict stops the operation in both workflows: quarantine the folder as step 11 describes, change
   no wiki page and do not preview. Without a conflict, where the human confirms depends on how you write:
   - **Direct-file workflow: STOP.** Show the summary and wait for the user to confirm before proceeding.
   - **Connected board (a Prism MCP connection): do not stop before the preview.** The preview is
     where the human confirms. Prepare steps 7-11 as the `preview_skill` proposal, then show the
     summary together with the complete preview in one message and ask the human to confirm, correct,
     or cancel it. Call `apply` only after that confirmation; a correction is a new preview, and a
     cancel means no `apply`.
7. Create `knowledge/wiki/design/[F-XXX]-[slug].md`. Mark each claim with an evidence label and link
   the processed path of the source file as the evidence of every Decided or Observed claim, for
   example `../../intake/processed/[folder-name]/notes.md`. When the new source changes a claim the
   page already makes, replace that claim in place
8. Update the `## Design` section of the feature file
9. For any UI states not covered, add open questions with owner = `designer`
10. Add or replace the design page's line in `index.md` and append a `log.md` entry in the log format that the wiki schema defines
11. Move the intake folder, under the same name, to `processed/` with a `MANIFEST.md` that lists the
    design page and the feature by full relative path. A processed item is never edited afterwards.
    If the design contradicts the feature spec, a business rule, an ADR or a board review finding,
    move it to `quarantined/` instead, write a `CONFLICT.md` there in the format that `SCHEMA.md`
    defines (`status: open`; `## Existing claim` and `## Incoming claim`, each with `**Claim:**`,
    `**Scope:**` and a linked `**Evidence:**`), and change no wiki page

## Rules

- write-capable skill
- direct-file workflow: do not write anything until the user confirms the interpretation summary; connected board: do not call `apply` until the user confirms the preview that shows the summary
- flag any conflicts with the feature spec, business rules, ADRs, or board review findings before writing
- on a contradiction, quarantine the folder under `knowledge/intake/quarantined/[folder-name]/` with a `CONFLICT.md` in the format that `SCHEMA.md` defines (Conflict quarantine): front matter `status: open`, then an `## Existing claim` and an `## Incoming claim` section, each with `**Claim:**`, `**Scope:**` and a linked `**Evidence:**`; change no wiki page and stop
- never edit a processed intake item; corrected material is a new dated pending folder
- if a board review exists, check whether the design addresses those concerns; if a board concern is unaddressed by the design, flag it as an open question with owner = `designer`
- note Figma links as references even when the content cannot be read directly: Figma links cannot be read, so note the URL and proceed with written descriptions
- write current-state pages: replace superseded content in place, state rationale as a current fact and keep history in `log.md` and the records; mark each claim `**Decided:**`, `**Observed:**`, `**Proposed:**` or `**Assumed:**` (gaps stay in the Open questions table) and link the evidence of every Decided and Observed claim: the processed intake item, a record or a URL (see Evidence labels in the wiki schema)

## Output behavior

Return:

- interpretation summary (before writes in the direct-file workflow; together with the preview on the connected board)
- design decisions extracted
- covered and missing UI states
- any conflicts found
- created design page path and any open questions added

## Error and stop conditions

- if the feature file or intake folder does not exist, return a clean missing-input response
- if the user does not confirm the interpretation summary (direct-file) or the preview (connected board), stop without writing; on the connected board that means no `apply`
- if conflicts require quarantine, stop after reporting them
