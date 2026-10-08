# Ingest - process raw sources into wiki pages of any kind

Process one input folder from intake/pending/ into wiki pages. Any role can run it, and it can write any page kind. `/po-intake` and `/design-intake` remain the role-specific entry points for feature requests and design handoffs.

## Usage

`/ingest [folder-name]`

Example: `/ingest 2026-10-06-payments-research`

The folder is named `YYYY-MM-DD-slug`: the day the source was captured, then lowercase words
joined by hyphens. The connected board rejects any other name.

## Workflow

1. Read `knowledge/wiki/SCHEMA.md` and `knowledge/wiki/LIFECYCLE.md` in full. The Ingest
   section of the schema lists the page kinds.
2. Read `knowledge/wiki/index.md` and `knowledge/wiki/status-board.md`. The index lists every
   page, one line each: use it to find the pages the source touches, then read those pages.
3. Read all files in `knowledge/intake/pending/[folder-name]/`. If the folder is not named
   `YYYY-MM-DD-slug`, stop and ask the user to rename it
4. **STOP. Conflict check (before any writes):**
   Check whether anything in the input conflicts with the pages you read. Conflicts include:
   a point that directly contradicts an existing feature spec, business rule, ADR or other
   Decided claim; a feature request that duplicates an existing feature with different
   acceptance criteria; a decision explicitly rejected in an ADR.
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
   - If no conflicts: proceed to step 5.
5. Choose the page kind for each part of the input with the Ingest table in `SCHEMA.md`,
   and read the `_FORMAT.md` of each kind you will write.
6. **Summarize your interpretation:**
   - Which pages does this input create? List each by kind and proposed title.
   - Which existing topic, research, plan, direction or roadmap pages does it replace in place?
   - Which new features, bugs, personas, business rules or decisions does it introduce?
   - What is ambiguous or unclear that you could not resolve?
   - For each new feature: does it appear to need an advisory board review?

   Where the human confirms depends on how you write:
   - **Direct-file workflow: STOP.** Show the summary and wait for the user to confirm, correct, or
     cancel before proceeding.
   - **Connected board (a Prism MCP connection): do not stop before the preview.** The preview is
     where the human confirms. Prepare the writes of the steps below as the `preview_skill` proposal,
     then show the summary together with the complete preview in one message and ask the human to
     confirm, correct, or cancel it. Call `apply` only after that confirmation; a correction is a new
     preview, and a cancel means no `apply`. In the proposal, write `**Decided:**` only for what the
     input or the user already states, and set `advisory-review: pending` where the need is
     ambiguous, naming that choice in the summary so the human can correct it.
7. Write the confirmed pages (on the connected board: the pages as proposed in the preview and confirmed there):
   - A topic, research page or plan: create `knowledge/wiki/topics|research|plans/[slug].md`
     in the format of its folder, or replace the page in place when it exists and the
     source changes what it says.
   - `knowledge/wiki/direction.md` and `knowledge/wiki/roadmap.md`: replace the page in
     place, in the format that `SCHEMA.md` defines.
   - A persona, business rule or decision: create it; never rewrite an existing one. A new
     decision replaces an older one only through the decision-supersession workflow in
     `SCHEMA.md`.
   - A defect report: assign the next free bug number and create `knowledge/wiki/bugs/[BUG-XXX]-[slug].md`
     in the format of `knowledge/wiki/bugs/_FORMAT.md`: `status: open` and `owner: dev`, none of `deferred-reason`,
     `close-reason`, `duplicate-of` and `promoted-to`, empty Fix, Verification, Release and Evidence history sections
     (`bug_creation_invalid`), `feature` an existing feature or `none`, and `apps` apps of that feature. A bug is
     created and never rewritten here; `/bug-update` changes it.
   - A feature: assign the next available feature ID and create
     `knowledge/wiki/features/[F-XXX]-[slug].md` with `status: raw` and `owner: po`, under
     the `/po-intake` rules: the Summary, User story, Acceptance criteria, Open questions
     and App scope sections written from the input, only active apps of the workspace in
     `apps` (a retired app is rejected with `app-retired`, `app_retired` on the connected
     board), open questions for every gap, and `advisory-review` set from the team's
     confirmation. `/po-specify [F-XXX]` completes it.
   Mark each claim with an evidence label (`**Observed:**`, `**Decided:**` for what the user
   confirmed in step 6, `**Proposed:**`, `**Assumed:**`) and link the processed path of the
   source file as the evidence of every Decided or Observed claim, for example
   `../../intake/processed/[folder-name]/notes.md`. List the processed path in `sources`.
8. Add or replace the `knowledge/wiki/index.md` line of every page you write: one sentence
   in the present tense that states what the page says now. Add a row to
   `knowledge/wiki/status-board.md` for each new feature.
9. Append a `knowledge/wiki/log.md` entry in the log format that the wiki schema defines.
   The pages carry no date field; the log entry records when they were written
10. Move `knowledge/intake/pending/[folder-name]/` to `knowledge/intake/processed/[folder-name]/`
    (the same dated name; a processed item is never edited afterwards) with a `MANIFEST.md`
    listing every page you created or replaced. List each by its full relative path and,
    where the page has one, its canonical ID, for example
    `knowledge/wiki/features/F-001-slug.md (F-001)` or `knowledge/wiki/topics/payment-flows.md`;
    the connected board rejects a manifest that omits one

## Rules

- write-capable skill
- never rewrite an existing feature, persona, business rule or decision, and never edit a processed intake item; corrected material is a new dated pending folder
- never rewrite an existing bug page; a bug in the material is created as a new bug page
- Do not invent requirements not present in the input. Mark gaps as open questions on a
  feature and as `**Unknown:**` items on other pages.
- Update or conflict: a source that refines a claim, or replaces an Observed claim with a newer
  observation, updates the page in place (new label, new link, no "was/now" note). A source that
  contradicts a Decided claim, a business rule or an ADR is a conflict. When unsure, quarantine.
- If the input mentions an existing page by name or description, check whether it updates that
  page rather than creating a duplicate. An existing feature, persona, business rule or decision
  is never rewritten by ingest, and neither is a bug; say so and point to the operation that changes it.
- A single input folder may produce several pages of different kinds.
- Never set a new feature to `specified`. Ingest writes `raw` + `po` only.
- write current-state pages: replace superseded content in place, state rationale as a current fact and keep history in `log.md` and the records; mark each claim `**Decided:**`, `**Observed:**`, `**Proposed:**` or `**Assumed:**` (gaps stay in the Open questions table of a feature) and link the evidence of every Decided and Observed claim: the processed intake item, a record or a URL (see Evidence labels in the wiki schema)

## Output behavior

Return:

- conflict summary, and the interpretation summary (before writes in the direct-file workflow; together with the preview on the connected board)
- the pages created or replaced, by path and kind
- any new feature IDs and titles
- any open questions added
- the processed intake folder path

## Error and stop conditions

- if the intake folder does not exist, return a clean missing-folder response
- if the input contradicts existing wiki content, quarantine it with a `CONFLICT.md` and stop
- if the user does not confirm the interpretation summary (direct-file) or the preview (connected board), stop without writing; on the connected board that means no `apply`
