# Intake - dropping raw inputs into the wiki

This is where raw, unprocessed inputs live before the AI organizes them. A raw source is a
record of what was said or produced at one point in time, so it keeps its date.

## Who drops what here

**Product Owner:** meeting transcripts, client feedback summaries, user research notes,
feature request descriptions. Use PO_BRIEF_TEMPLATE.md as a guide. Raw notes are fine -
the more structured your input, the more accurate the output.

**Designer:** design spec notes, Figma annotations, interaction descriptions, component
decisions. Use DESIGN_HANDOFF_TEMPLATE.md as a guide. Attach a Figma link or exported
PNG/PDF if available.

**Developer:** technical constraints, feasibility findings, platform-specific edge cases
discovered during implementation. Drop as a markdown note referencing the feature ID.

**Agents:** a review packet an agent was given, or an output an agent produced, can be
archived here as a source (see "Archiving agent packets and outputs" below).

## How to contribute

1. Create a folder: intake/pending/YYYY-MM-DD-slug/
   The date is the day the source was captured; the slug is lowercase words joined by
   hyphens. Examples: 2026-04-01-client-call/, 2026-04-03-search-design/,
   2026-04-07-f003-feasibility-notes/
2. Drop your files into that folder. State when the material was captured in its
   `Captured:` line (the templates have one); it matches the date in the folder name.
3. Run the appropriate command:

   Command syntax by tool:
   - Claude Code: `/po-intake [folder]` or `/design-intake [F-XXX] [folder]`
   - Codex: `$po-intake [folder]` or `$design-intake [F-XXX] [folder]`
   - Cursor: ask the agent to "run po-intake on [folder]" or "run design-intake on F-XXX [folder]"

The connected board requires the `YYYY-MM-DD-slug` name for the folder it moves; any other
name is rejected with `intake_name_invalid`.

## After processing

Processed items are moved to intake/processed/[folder-name]/ (the same dated name) with a
`MANIFEST.md` that lists every page the item produced, by full relative path and canonical
ID. Every feature the intake creates starts as `raw`; run `/po-specify [F-XXX]` (Codex:
`$po-specify [F-XXX]`) to complete it and move it to `specified`.

A processed item is immutable. Nobody edits its files, and a board proposal that writes
into one is rejected with `processed_source_immutable`. New or corrected material is a new
dated folder in `pending/`. Pages that rely on a source link it as evidence, for example
`../../intake/processed/2026-04-01-client-call/notes.md` from a feature page.

`prism wiki lint` warns with `processed-source-without-manifest` when a processed item has
no `MANIFEST.md`.

## Archiving agent packets and outputs

An agent review packet (what a reviewer was given) or an agent output (what it returned)
is archived as a source like any other:

1. Save it as a markdown file in `pending/YYYY-MM-DD-slug/`, for example
   `pending/2026-04-09-board-review-f003/packet.md` and `output.md`. The date is the day
   the packet was sent or the output returned.
2. Process the folder. Its `MANIFEST.md` names the pages the packet or output informed;
   write `No pages extracted.` and one sentence on why when it informed none.
3. A page that relies on the output links the processed file as evidence.

## Conflicts

Items that contradict existing wiki content are moved to intake/quarantined/[folder-name]/
with a `CONFLICT.md`. The existing page stays untouched until a human decides which claim
holds. `CONFLICT.md` has front matter `status: open | resolved` and gives both claims with
their scope and links; `SCHEMA.md` (Conflict quarantine) defines the format. After the
decision, set `status: resolved` and add a `## Resolution` section. The resolved record
stays in `quarantined/`. A source that should still be ingested is dropped again as a new
dated folder.

A non-empty quarantine is not an error. Lint warns with `unresolved-conflict` for each
open conflict, and reports a `CONFLICT.md` that does not follow the format as
`malformed-conflict`.

## What "conflict" means

A conflict occurs when the new input directly contradicts established wiki content.
Examples:
- PO notes say "feature X requires no authentication" but BR-001 says all features require auth
- Design handoff shows a flow explicitly rejected in ADR-002
- New feature request duplicates an existing feature with different acceptance criteria

Conflicts are not errors. They are important signals. The quarantine mechanism ensures
they surface for human resolution rather than silently overwriting agreed decisions.
