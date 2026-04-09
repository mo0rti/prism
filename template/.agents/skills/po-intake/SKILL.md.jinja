---
name: po-intake
description: Process raw PO intake notes into structured wiki entries. Use when turning files from `knowledge/intake/pending/` into features, personas, business rules, index updates, and intake manifests.
---

# PO Intake

Use this skill to process one pending intake folder into structured wiki content.

## Usage

`$po-intake [folder-name]`

## Workflow

1. Read `knowledge/wiki/SCHEMA.md`
2. Read `knowledge/wiki/index.md`
3. Read `knowledge/wiki/personas/`
4. Read `knowledge/wiki/business-rules/`
5. Read all files in `knowledge/intake/pending/[folder-name]/`
6. Run a conflict check before any writes
7. Show the user an interpretation summary and wait for confirmation
8. If confirmed, create or update the required wiki files
9. Update `knowledge/wiki/index.md` and append to `knowledge/wiki/log.md`
10. Move the intake folder to `knowledge/intake/processed/[folder-name]/` and add `MANIFEST.md`

## Rules

- write-capable skill
- do not write anything until the conflict check passes
- if conflicts exist, quarantine the intake folder and stop
- do not write anything until the user confirms the interpretation summary
- do not invent requirements that are missing from the intake material
- turn gaps or ambiguity into open questions instead of invented spec text

## Canonical format reference

Mirror the detailed workflow and write behavior from:

- `/.claude/commands/po-intake.md`

## Output behavior

Return:

- conflict summary or confirmation summary before writes
- created or updated feature IDs and titles
- any personas or business rules created or updated
- any open questions added
- the processed intake folder path

## Error and stop conditions

- if the intake folder does not exist, return a clean missing-folder response
- if the input conflicts with existing wiki content, quarantine and stop
- if the user does not confirm the interpretation summary, stop without writing
