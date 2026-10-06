---
name: po-intake
description: "Process raw PO intake notes into structured wiki entries. Use when turning files from `knowledge/intake/pending/` into features, personas, business rules, index updates, and intake manifests."
layers: [codex, command]
codex:
  display_name: "PO Intake"
  short_description: "Process raw intake notes into structured wiki entries"
  default_prompt: "Use @@invoke:po-intake@@ [folder-name] to turn a pending intake folder into features, personas, business rules, and index updates."
  implicit: false
---

# PO intake - process raw notes into feature specs

Process a raw input document from intake/pending/ into structured wiki entries.

## Usage
@@invoke:po-intake@@ [folder-name]

Example: @@invoke:po-intake@@ 2026-04-01-client-call

The folder is named `YYYY-MM-DD-slug`: the day the source was captured, then lowercase words
joined by hyphens. The connected board rejects any other name.

## Workflow

1. Read `knowledge/wiki/SCHEMA.md` and `knowledge/wiki/LIFECYCLE.md` in full
2. Read `knowledge/wiki/index.md` to find the existing pages and `knowledge/wiki/status-board.md` for the existing features
3. Read `knowledge/wiki/personas/` - understand who the current users are
4. Read `knowledge/wiki/business-rules/` - understand existing constraints
5. Read all files in `knowledge/intake/pending/[folder-name]/`. If the folder is not named
   `YYYY-MM-DD-slug`, stop and ask the user to rename it
6. **STOP. Conflict check (before any writes):**
   Check whether anything in the input conflicts with existing wiki content.
   Conflicts include: a point that directly contradicts an existing feature spec,
   business rule, or ADR; a feature request that duplicates an existing feature
   with different acceptance criteria; a design or workflow explicitly rejected in
   an ADR; auth requirements that contradict existing business rules.
   - If conflicts exist: move `knowledge/intake/pending/[folder-name]/` to
     `knowledge/intake/quarantined/[folder-name]/` and write a `CONFLICT.md` in the
     quarantined folder in the format that `SCHEMA.md` defines (Conflict quarantine):
     front matter `status: open`; an `## Existing claim` and an `## Incoming claim`
     section, each with `**Claim:**`, `**Scope:**` and an `**Evidence:**` item that links
     the existing page or the incoming file; and a `## Decision needed` section naming
     what the human decides. Inform the user.
     **Stop - do not write or modify any wiki files.** The existing pages stay untouched.
     The human resolves the conflict and sets `status: resolved` with a `## Resolution`;
     corrected input is dropped again as a new `YYYY-MM-DD-slug` pending folder.
   - If no conflicts: proceed to step 7.
7. **STOP. Show the user a summary of your interpretation:**
   - What new features does this input describe? (list by proposed title)
   - What existing features does it update or clarify?
   - What new personas or business rules does it introduce?
   - What is ambiguous or unclear that you could not resolve?
   - For each new feature: does it appear to need an advisory board review?
     (reference the criteria in the "When to use" section of `@@invoke:board-review@@`)
   **Wait for the user to confirm, correct, or cancel before proceeding.**
8. For each new feature identified and confirmed:
   - Assign the next available feature ID
   - Create `knowledge/wiki/features/[F-XXX]-[slug].md` using the feature format from LIFECYCLE.md
   - Set status: `raw`, owner: `po`. A new feature always starts `raw`; `@@invoke:po-specify@@ [F-XXX]`
     completes it and moves it to `specified`.
   - List only active apps of the workspace in `apps`; a retired app is rejected with
     `app-retired` (`app_retired` on the connected board)
   - Write the Summary, User story, Acceptance criteria, Open questions and App scope
     sections from the input. Mark each claim with an evidence label (`**Observed:**`,
     `**Decided:**` for what the user confirmed in step 7, `**Proposed:**`, `**Assumed:**`)
     and link the processed path of the source file as the evidence of every Decided or
     Observed claim, for example `../../intake/processed/[folder-name]/notes.md`. Gaps stay
     in the Open questions table. Leave Design, Related features, API surface, Board review
     summary and Post-ship notes empty; `@@invoke:po-specify@@` completes them.
   - Set `advisory-review` field based on team confirmation:
     `pending` if domain complexity confirmed, `not-needed` if confirmed simple feature
   - Populate open questions for anything missing from the input
   - Route design-related open questions to owner: `designer`
   - Route technical feasibility questions to owner: `dev`
9. For each new persona identified, create or update `knowledge/wiki/personas/[slug].md`
10. For each business rule identified, create `knowledge/wiki/business-rules/[BR-XXX]-[slug].md`
11. Add the `knowledge/wiki/index.md` line of each page you create, and a row in `knowledge/wiki/status-board.md` for each new feature
12. Append a `knowledge/wiki/log.md` entry in the log format that the wiki schema defines. The new pages carry no date field; the log entry records when they were written
13. Move `knowledge/intake/pending/[folder-name]/` to `knowledge/intake/processed/[folder-name]/`
    (the same dated name; a processed item is never edited afterwards) with a `MANIFEST.md` listing what was extracted. List every page you create by its
    full relative path and its canonical ID, for example
    `knowledge/wiki/features/F-001-slug.md (F-001)`; the connected board rejects a
    manifest that omits one

## Rules

- write-capable skill
- never edit a processed intake item; corrected material is a new dated pending folder
- write every new feature as `status: raw`, `owner: po`
- Do not invent requirements not present in the input. Mark gaps as open questions.
- Update or conflict: a source that refines a claim, or replaces an Observed claim with a newer
  observation, updates the page in place (new label, new link, no "was/now" note). A source that
  contradicts a Decided claim, a business rule or an ADR is a conflict. When unsure, quarantine.
- Business language in the input should stay business language in the summary.
- If the input mentions an existing feature by name or description, check whether it
  updates that feature's spec rather than creating a duplicate.
- A single input document may produce multiple features, personas, and business rules.
- Never set a new feature to `specified`. `po-intake` writes `raw` + `po` only.
- Do not set `advisory-review: not-needed` by default. Ask the user explicitly for any
  feature where domain complexity is ambiguous.
- write current-state pages: replace superseded content in place, state rationale as a current fact and keep history in `log.md` and the records; mark each claim `**Decided:**`, `**Observed:**`, `**Proposed:**` or `**Assumed:**` (gaps stay in the Open questions table) and link the evidence of every Decided and Observed claim: the processed intake item, a record or a URL (see Evidence labels in the wiki schema)

## Output behavior

Return:

- conflict summary or confirmation summary before writes
- created or updated feature IDs and titles
- any personas or business rules created or updated
- any open questions added
- the processed intake folder path

## Error and stop conditions

- if the intake folder does not exist, return a clean missing-folder response
- if the input contradicts existing wiki content, quarantine it with a `CONFLICT.md` and stop
- if the user does not confirm the interpretation summary, stop without writing
