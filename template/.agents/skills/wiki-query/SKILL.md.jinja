---
name: wiki-query
description: Read-only retrieval-assisted search across the wiki. Finds compact, typed matches without inventing ranking scores.
---

# Wiki Query

Read-only wiki search for compact navigation across features, rules, design pages,
platform requirements, personas, API contracts, and decisions.

## Usage

`$wiki-query "text"`

## Workflow

1. Use tool-level text search across:
   - `knowledge/wiki/features/`
   - `knowledge/wiki/personas/`
   - `knowledge/wiki/business-rules/`
   - `knowledge/wiki/design/`
   - `knowledge/wiki/platform-requirements/`
   - `knowledge/wiki/api-contracts/`
   - `knowledge/wiki/decisions/`
2. Collect candidate pages and matching lines
3. Group matches by coarse match class
4. Synthesize a compact result set from the retrieved candidates

## Rules

- read-only skill
- do not write any wiki files
- do not refresh `WIKI_REPORT.md`
- do not invent numeric scores or fake search precision
- explain why each candidate matched
- keep the default result set small, for example top 8 candidates

## Canonical format reference

Mirror the detailed output contract from:

- `/.claude/commands/wiki-query.md`

## Match classes

- exact feature ID or exact filename match
- title or heading match
- body-text match
- related-page enrichment when a matched page belongs to a feature context

## Output shape

Return:

- the original query
- candidate matches
- page type
- feature status when relevant
- match class
- relevant headings or sections when available

## Error and partial-state behavior

- if no candidates match, return a clean no-results response
- if more than 8 candidates match and the results are too diffuse, return a refinement prompt
