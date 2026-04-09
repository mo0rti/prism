# Wiki query - retrieval-assisted search across the wiki

## Usage
/wiki-query "text"

## Purpose

Search across the wiki for relevant features, rules, personas, design pages, decisions,
API contracts, and platform requirements.

## Read-only rules

- read-only command
- do not write any wiki files
- do not refresh `WIKI_REPORT.md`
- if `WIKI_REPORT.md` is missing, tell the user to run `/feature-status` for an updated orientation summary

## Files to read

- all files in `knowledge/wiki/features/`
- all files in `knowledge/wiki/personas/`
- all files in `knowledge/wiki/business-rules/`
- all files in `knowledge/wiki/design/`
- all files in `knowledge/wiki/platform-requirements/`
- all files in `knowledge/wiki/api-contracts/`
- all files in `knowledge/wiki/decisions/`
- optionally `knowledge/wiki/index.md` for feature status cross-reference

## Retrieval model

- `wiki-query` is not a search engine and must not invent numeric ranking
- use tool-level text search first to collect candidate pages and matching lines
- group candidate pages by coarse match class instead of fake confidence scores
- synthesize a compact result summary from those retrieved candidates

## Match classes

- exact feature ID or exact filename match
- title or heading match
- body-text match
- related-page enrichment when a matched page belongs to a feature context

## Output rules

- return a small result set by default, for example top 8 candidates
- explain the match class for each result
- include matching headings or section names when possible
- if more than 8 candidate pages match and the results are too diffuse to summarize
  cleanly, return a refinement prompt instead of pretending the result set is coherent

## Recommended output shape

```text
Query: offline checkout

Candidate matches:

1. F-012 - Saved Checkout
   Type: feature
   Status: ready-for-dev
   Match class: title/heading match
   Relevant sections:
   - Summary
   - Open questions
   - API surface

2. BR-004 - Checkout Address Validation
   Type: business-rule
   Related feature: F-012
   Match class: body-text match
   Relevant sections:
   - Rule
   - Rationale

3. F-012-mobile-ios
   Type: platform-requirement
   Status: pending
   Match class: body-text match
   Relevant sections:
   - What to build
   - Technical constraints
```

## Partial/error-state examples

```text
Query: offline checkout

No matches found.

Next step:
Try a broader term, a feature ID, or run /feature-status to inspect current feature names.
```

```text
Query: auth

Too many broad matches to summarize reliably in one response.

Suggested refinement:
- /wiki-query "password auth"
- /wiki-query "OAuth callback"
- /wiki-query "login flow"
```
