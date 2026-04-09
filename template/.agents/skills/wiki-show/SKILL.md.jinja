---
name: wiki-show
description: Read-only feature context bundle for one feature ID. Pulls together feature state, linked context, blockers, and suggested next action.
---

# Wiki Show

Read-only feature drill-down for one feature.

## Usage

`$wiki-show F-XXX`

## Workflow

1. Read `knowledge/wiki/index.md`
2. Read `knowledge/wiki/features/[F-XXX]-[slug].md`
3. Read matching linked files if present:
   - `knowledge/wiki/design/[F-XXX]-[slug].md`
   - `knowledge/wiki/api-contracts/[F-XXX].md`
   - `knowledge/wiki/platform-requirements/[F-XXX]-*.md`
   - `knowledge/wiki/advisory/[F-XXX]-review.md`
   - business-rule files that reference the feature ID
4. Assemble a focused context bundle

## Rules

- read-only skill
- do not write any wiki files
- do not refresh `WIKI_REPORT.md`
- treat missing optional linked files as partial context, not as a hard error

## Canonical format reference

Mirror the detailed output contract from:

- `/.claude/commands/wiki-show.md`

## Output shape

Return:

- feature name and ID
- status
- owner
- advisory-review state
- summary
- open questions
- linked context
- platform requirement status
- current blockers
- suggested next action

## Error and partial-state behavior

- if no feature file matches the requested ID, return a clean missing-feature response
- if optional linked files are absent, return a partial-state response that names the missing files
