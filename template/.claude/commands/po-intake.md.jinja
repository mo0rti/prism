# PO intake — process raw notes into feature specs

Process a raw input document from intake/pending/ into structured wiki entries.

## Usage
/po-intake [folder-name]

Example: /po-intake meeting-client-2026-04-01

## What this command does

1. Read `knowledge/wiki/SCHEMA.md` in full
2. Read `knowledge/wiki/index.md` to understand existing features
3. Read `knowledge/wiki/personas/` — understand who the current users are
4. Read `knowledge/wiki/business-rules/` — understand existing constraints
5. Read all files in `knowledge/intake/pending/[folder-name]/`
6. **STOP. Conflict check (before any writes):**
   Check whether anything in the input conflicts with existing wiki content.
   Conflicts include: a point that directly contradicts an existing feature spec,
   business rule, or ADR; a feature request that duplicates an existing feature
   with different acceptance criteria; a design or workflow explicitly rejected in
   an ADR; auth requirements that contradict existing business rules.
   - If conflicts exist: move `knowledge/intake/pending/[folder-name]/` to
     `knowledge/intake/quarantined/[folder-name]/`, write a `CONFLICT.md` in the quarantined
     folder explaining what the new input claims, what the existing wiki says, which
     files are in conflict, and what decision the human needs to make. Inform the user.
     **Stop — do not write or modify any wiki files.** The human resolves the conflict,
     then re-runs `/po-intake` on the corrected input.
   - If no conflicts: proceed to step 7.
7. **STOP. Show the user a summary of your interpretation:**
   - What new features does this input describe? (list by proposed title)
   - What existing features does it update or clarify?
   - What new personas or business rules does it introduce?
   - What is ambiguous or unclear that you could not resolve?
   - For each new feature: does it appear to need an advisory board review?
     (reference the criteria in /board-review.md)
   **Wait for the user to confirm, correct, or cancel before proceeding.**
8. For each new feature identified and confirmed:
   - Assign the next available feature ID
   - Create `knowledge/wiki/features/[F-XXX]-[slug].md` using the feature format from SCHEMA.md
   - Set status: `specified`, owner: `po`
   - Set `advisory-review` field based on team confirmation:
     `pending` if domain complexity confirmed, `not-needed` if confirmed simple feature
   - Populate open questions for anything missing from the input
   - Route design-related open questions to owner: `designer`
   - Route technical feasibility questions to owner: `dev`
9. For each new persona identified, create or update `knowledge/wiki/personas/[slug].md`
10. For each business rule identified, create `knowledge/wiki/business-rules/[BR-XXX]-[slug].md`
11. Update `knowledge/wiki/index.md` status board with new feature rows
12. Append to `knowledge/wiki/log.md`
13. Move `knowledge/intake/pending/[folder-name]/` to `knowledge/intake/processed/[folder-name]/`
    with a `MANIFEST.md` listing what was extracted

## Notes for the agent

- Do not invent requirements not present in the input. Mark gaps as open questions.
- Business language in the input should stay business language in the summary.
- If the input mentions an existing feature by name or description, check whether it
  updates that feature's spec rather than creating a duplicate.
- A single input document may produce multiple features, personas, and business rules.
- Do not set `advisory-review: not-needed` by default. Ask the user explicitly for any
  feature where domain complexity is ambiguous.
