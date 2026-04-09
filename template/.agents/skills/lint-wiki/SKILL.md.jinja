---
name: lint-wiki
description: Health-check the knowledge wiki for structural issues and blocker categories. Writes a lint report, but never refreshes WIKI_REPORT.md.
---

# Lint Wiki

Health-check the full knowledge wiki. Reports issues; does not auto-fix.

## Workflow

1. Read `knowledge/wiki/SCHEMA.md`
2. Read `knowledge/wiki/SETTINGS.md` if present
3. Read `knowledge/wiki/index.md`
4. Read all files in all wiki subdirectories
5. Check for:
   - `missing-platform-requirements`
   - `missing-design`
   - `api-contract-not-ready`
   - contradictions
   - `pending-board-review`
   - skipped board reviews with their recorded reason
   - orphan pages
   - index drift
   - stale status using `wiki-stale-after-days`
   - quarantine backlog
   - `unresolved-open-questions`
   - `cross-platform-dependency`
   - missing ADRs
6. Output lint report as `knowledge/wiki/lint-[YYYY-MM-DD].md`
7. Append to `knowledge/wiki/log.md`

## WIKI_REPORT boundary

- never write `knowledge/wiki/WIKI_REPORT.md`
- if it is missing or stale, tell the user to rerun `$feature-status`
- keep `WIKI_REPORT.md` framed as a summary artifact, not authority

If `knowledge/wiki/SETTINGS.md` is absent or invalid, fall back to
`wiki-stale-after-days: 14` and tell the user.

## Canonical format reference

Mirror the detailed output contract from:

- `/.claude/commands/lint-wiki.md`

## Report format

For each issue: affected file(s), blocker category when applicable, description of the
problem, and suggested remediation.

If no issues are found: state explicitly `Wiki is consistent. No issues found.`

## Partial/error-state examples

```text
## Lint Summary

Wiki is consistent. No issues found.

## WIKI_REPORT note

knowledge/wiki/WIKI_REPORT.md was not modified.
If you want a refreshed orientation summary, rerun $feature-status.
```

```text
## Lint Summary

Malformed wiki pages detected.

## Issues

1. knowledge/wiki/features/F-099-broken.md
   Category: malformed-page
   Problem:
   - Required frontmatter field `status` is missing.
   Suggested remediation:
   - Repair the feature frontmatter before treating this page as valid project state.

## WIKI_REPORT note

knowledge/wiki/WIKI_REPORT.md was not modified.
Rerun $feature-status after the malformed pages are fixed.
```

## Notes

- Do not auto-fix anything. Report and let the human decide.
- Use the canonical blocker vocabulary from `knowledge/wiki/SCHEMA.md`.
- Keep skipped board reviews visible for awareness, not as a hard error.
