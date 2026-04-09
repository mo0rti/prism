---
name: wiki-owner
description: Read-only owner dashboard for po, designer, or dev. Shows open questions, waiting work, and stale items.
---

# Wiki Owner

Read-only role dashboard for one explicit owner value.

## Usage

`$wiki-owner po|designer|dev`

## Workflow

1. Read `knowledge/wiki/SETTINGS.md` if present
2. Read all feature files
3. Read all platform-requirement files
4. Optionally read `knowledge/wiki/index.md` for lifecycle grouping confirmation
5. Assemble open questions, waiting work, and stale items for the requested owner

## Rules

- read-only skill
- do not write any wiki files
- do not refresh `WIKI_REPORT.md`
- do not infer the caller's role automatically
- supported owner values are exactly `po`, `designer`, and `dev`
- read `wiki-stale-after-days` from `knowledge/wiki/SETTINGS.md`
- if the settings file or key is absent, fall back to `wiki-stale-after-days: 14`
- if the settings value is malformed, report it and still fall back to `14`

## Canonical format reference

Mirror the detailed output contract from:

- `/.claude/commands/wiki-owner.md`

## Output shape

Return:

- owner view heading
- open questions assigned to that owner
- features currently waiting on that owner
- potentially stale items using the configured threshold
- suggested next actions

## Error behavior

- if no current work matches the selected owner, return a clean empty-state response
- if the owner value is unsupported, return a clean invalid-owner response
