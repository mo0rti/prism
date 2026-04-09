# Intake — dropping raw inputs into the wiki

This is where raw, unprocessed inputs live before the AI organizes them.

## Who drops what here

**Product Owner:** meeting transcripts, client feedback summaries, user research notes,
feature request descriptions. Use PO_BRIEF_TEMPLATE.md as a guide. Raw notes are fine —
the more structured your input, the more accurate the output.

**Designer:** design spec notes, Figma annotations, interaction descriptions, component
decisions. Use DESIGN_HANDOFF_TEMPLATE.md as a guide. Attach a Figma link or exported
PNG/PDF if available.

**Developer:** technical constraints, feasibility findings, platform-specific edge cases
discovered during implementation. Drop as a markdown note referencing the feature ID.

## How to contribute

1. Create a folder: intake/pending/[descriptive-name]/
   Examples: meeting-client-2026-04-01/, feature-search-design/, f003-feasibility-notes/
2. Drop your files into that folder
3. Run the appropriate command:

   Command syntax by tool:
   - Claude Code: `/po-intake [folder]` or `/design-intake [F-XXX] [folder]`
   - Codex: `$po-intake [folder]` or `$design-intake [F-XXX] [folder]`
   - Cursor: ask the agent to "run po-intake on [folder]" or "run design-intake on F-XXX [folder]"

## After processing

Processed items are moved to intake/processed/[folder-name]/ automatically with a
manifest of what was extracted.

Items that conflict with existing wiki content are moved to intake/quarantined/[folder-name]/
with a conflict explanation. A human must resolve the conflict before the item can be
processed.

## What "conflict" means

A conflict occurs when the new input directly contradicts established wiki content.
Examples:
- PO notes say "feature X requires no authentication" but BR-001 says all features require auth
- Design handoff shows a flow explicitly rejected in ADR-002
- New feature request duplicates an existing feature with different acceptance criteria

Conflicts are not errors — they are important signals. The quarantine mechanism ensures
they surface for human resolution rather than silently overwriting agreed decisions.
