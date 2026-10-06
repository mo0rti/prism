---
name: wiki-query
description: "Read-only conservative wiki search. Prefer Prism CLI JSON; use direct text search when it is unavailable."
layers: [codex, command]
codex:
  display_name: "Wiki Query"
  short_description: "Read-only retrieval-assisted search across the wiki"
  default_prompt: "Use @@invoke:wiki-query@@ \"text\" to find compact, typed matches across the product wiki."
  implicit: true
---

# Wiki query - conservative search across the wiki

Provide compact, conservative search facts across the wiki.

## Usage

`@@invoke:wiki-query@@ "text"`

## Primary path: Prism CLI

Probe the optional CLI before selecting the JSON path:

```bash
prism --version
```

Use this path only when the probe reports `prism 0.5.0` or newer (the `prism-kit>=0.5.0` distribution contract)
and the command response has `"schema_version": 1`:

```bash
prism wiki search "text" --json
```

The CLI reads `knowledge/wiki/index.md` first: the index lines that contain the text name
their pages, and those pages come first in `facts.results`, each with its `index_line` and
`index` among its `matched_fields`. Render `facts.query`, `facts.results`,
`facts.index_match_count`, `diagnostics`, and `sources` exactly as returned. Treat returned diagnostics, including errors, as facts to surface
rather than replacing them with optimistic manual state.

## Fallback path

If the version probe or schema check fails, or `prism` is missing, too old,
fails, or lacks `wiki search`, say:
`Prism CLI read surface unavailable; falling back to direct wiki reads.` Read
`knowledge/wiki/index.md` first and search its lines for the text: each matching line
names a page, and those pages come first. Then run literal text search over:

- `knowledge/wiki/features/`
- `knowledge/wiki/personas/`
- `knowledge/wiki/business-rules/`
- `knowledge/wiki/design/`
- `knowledge/wiki/app-requirements/`
- `knowledge/wiki/api-contracts/`
- `knowledge/wiki/decisions/`
- `knowledge/wiki/topics/`
- `knowledge/wiki/research/`
- `knowledge/wiki/plans/`
- `knowledge/wiki/direction.md` and `knowledge/wiki/roadmap.md`

Collect matching lines and page types, then synthesize a compact result set.

## Match classes

Use these match classes: exact feature ID or exact filename match, title or heading
match, body-text match, and related-page enrichment. Explain each match.

## Rules and output

- Keep the operation read-only. Do not write wiki files or refresh `WIKI_REPORT.md`.
- Use conservative substring matching. Do not invent numeric scores, semantic
  ranking, or hidden relevance claims; keep the default result set small (for
  example, top 8).
- separate facts from advice and label optional suggested next steps.

Return the original query, candidates, page type, feature status when relevant,
match class, relevant headings or sections, diagnostics, and source paths. Use a
clean no-results response when no candidates match and request refinement when
more than 8 diffuse matches would be misleading.
