# Lint wiki - health-check the knowledge base

## Usage
/lint-wiki

## What this command does

1. Read `knowledge/wiki/SCHEMA.md`
2. Read `knowledge/wiki/SETTINGS.md` if present
3. Read `knowledge/wiki/index.md`
4. Read all files in all wiki subdirectories
5. Check for and report:
   - **missing-platform-requirements**
   - **missing-design**
   - **api-contract-not-ready**
   - contradictions across platform requirements, feature specs, and business rules
   - **pending-board-review**
   - skipped board reviews with their recorded reason
   - orphan pages
   - index drift
   - stale status using `wiki-stale-after-days`
   - quarantine backlog
   - **unresolved-open-questions**
   - **cross-platform-dependency**
   - missing ADRs for significant technical choices
6. Output a lint report as `knowledge/wiki/lint-[YYYY-MM-DD].md`
7. Append to `knowledge/wiki/log.md`

## WIKI_REPORT boundary

- never write `knowledge/wiki/WIKI_REPORT.md`
- do not refresh `WIKI_REPORT.md`
- if `WIKI_REPORT.md` is missing or stale, tell the user to rerun `/feature-status`
- `lint-wiki` is the authoritative structural-health command
- `WIKI_REPORT.md` is only a summary artifact and must not be treated as the lint report

If `knowledge/wiki/SETTINGS.md` is absent or invalid, fall back to
`wiki-stale-after-days: 14` and tell the user.

## Recommended output shape

```text
## Lint Summary

- missing-platform-requirements: 2
- missing-design: 1
- api-contract-not-ready: 1
- pending-board-review: 1
- unresolved-open-questions: 2
- cross-platform-dependency: 1

## Issues

1. F-012 - Saved Checkout
   Category: missing-platform-requirements
   Files:
   - knowledge/wiki/features/F-012-saved-checkout.md
   Problem:
   - Feature is ready-for-dev but no platform requirements exist for mobile-ios.
   Suggested remediation:
   - Run /design-handoff F-012 after the missing platform requirement is specified.

2. F-014 - Nutrition Goal Alerts
   Category: pending-board-review
   Files:
   - knowledge/wiki/features/F-014-nutrition-goal-alerts.md
   Problem:
   - Feature is in-design but advisory-review is still pending.
   Suggested remediation:
   - Run /board-review F-014 or explicitly skip with a documented reason.

## WIKI_REPORT note

knowledge/wiki/WIKI_REPORT.md was not modified.
If it is missing or stale, rerun /feature-status after addressing the relevant issues.
```

## Partial/error-state examples

```text
## Lint Summary

Wiki is consistent. No issues found.

## WIKI_REPORT note

knowledge/wiki/WIKI_REPORT.md was not modified.
If you want a refreshed orientation summary, rerun /feature-status.
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
Rerun /feature-status after the malformed pages are fixed.
```

## Notes for the agent

- Do not auto-fix anything. Report and let the human decide.
- Use the canonical blocker vocabulary from `knowledge/wiki/SCHEMA.md`.
- Keep skipped board reviews visible for team awareness, but do not report them as a hard error.
