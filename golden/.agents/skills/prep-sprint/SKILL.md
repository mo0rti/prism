---
name: prep-sprint
description: Read-only command that shows all features ready to build, what is blocked, what is awaiting board review, and what is in earlier lifecycle stages. Use at the start of a sprint or development session.
---

# Prep sprint — show what is ready to build

Read-only skill. Shows the current buildable state of the product wiki.

## Usage

`$prep-sprint`

## Primary path: Prism CLI

Probe the optional CLI before selecting the JSON path:

```bash
prism --version
```

Use `prism status --json` only when the probe reports `prism 0.5.0` or newer (the `prism-kit>=0.5.0` distribution contract) and the response has `"schema_version": 1`. Use
`facts.wiki`, `facts.advisory_review`, `blocker_facts`, `diagnostics`, and
`sources` as the shared source for lifecycle counts, readiness, health, and
canonical blockers. Treat returned diagnostics, including errors, as facts to
surface; do not replace them with optimistic manual state. Read matching feature
and app-requirement pages only for the names and delivery details needed in
the report, and do not recompute status or blocker facts.

## Fallback path

If the version probe or schema check fails, or `prism status --json` is missing,
too old, fails, or returns an unsupported schema, say:
`Prism CLI status unavailable; falling back to direct wiki reads.` Then use the
complete workflow below and report facts proved by those files.

## Fallback workflow

1. Read `knowledge/wiki/WIKI_REPORT.md` first if it exists for a quick orientation summary
2. If `knowledge/wiki/WIKI_REPORT.md` is absent, tell the user to run `$feature-status`
   first so the orientation report exists on demand
3. Read `knowledge/wiki/SCHEMA.md` and `knowledge/wiki/LIFECYCLE.md`
4. Read `knowledge/wiki/status-board.md`
5. Read all feature files with status = `ready-for-dev` or `in-dev`
6. For each feature, read its app-requirements pages
7. Output a structured report:

   ```
   ## Ready to build

   ### F-002 — Profile Edit [ready-for-dev]
   Apps: mobile-android, mobile-ios, backend
   Design: knowledge/wiki/design/F-002-profile-edit.md
   Board review: done
   Requirements:
   - Android: knowledge/wiki/app-requirements/F-002-mobile-android.md
   - iOS: knowledge/wiki/app-requirements/F-002-mobile-ios.md
   - Backend: knowledge/wiki/app-requirements/F-002-backend.md
   Open dev questions: none
   Dependencies: none

   ## Blocked (has dev-owned open questions)
   - F-006 — Search: "Is full-text search feasible with current DB? [dev, open]"

   ## Board review pending (not ready for dev)
   - F-007 — Nutrition Score [specified, advisory-review: pending]

   ## Not ready (in earlier lifecycle stages)
   - F-003 — Admin dashboard [in-design, owner: designer]
   ```

8. Do not modify any wiki files. This is a read-only operation.

## Notes for the agent

- `WIKI_REPORT.md` is an orientation artifact, not the source of truth; use the underlying
  feature and requirement pages for actual delivery decisions.
- Features with `advisory-review: pending` must not appear in the "Ready to build"
  section. List them separately under "Board review pending."
- Dependencies must be checked and stated explicitly.
- If any ready-for-dev feature has no app-requirements pages, flag it as incomplete.
