# Design handoff — move a feature to ready-for-development

## Usage
/design-handoff [F-XXX]

## What this command does

1. Read `knowledge/wiki/features/[F-XXX]-[slug].md`
2. Read `knowledge/wiki/design/[F-XXX]-[slug].md` if it exists
3. Determine whether this feature has UI platform scope:
   - UI platforms: `mobile-android`, `mobile-ios`, `web-user-app`, `web-admin-portal`
   - Non-UI: `backend`-only features, API-only features, infra changes, internal tooling
4. Run completeness check:
   - **If UI platforms are in scope:**
     - A design page linked in the `## Design` section (or `design: not-applicable`
       with a reason if the feature genuinely needs no visual design)
     - Design coverage for all UI states implied by acceptance criteria
   - **If no UI platforms are in scope (backend/API/infra):**
     - Design page is not required — skip design coverage check
     - Set `design: not-applicable` in the feature file if it is not already set
   - For all features: no open questions with owner = `designer`
   - Status of `in-design` or `ready-for-design`
5. Check `advisory-review` field:
   - If `pending`: board review has not been run. Inform the user. Ask:
     "Do you want to run board-review F-XXX before handing to development?"
     - If yes: run board review, then re-check completeness (step 4) before continuing.
     - If no: set `advisory-review: skipped` and require a reason. Record the reason in
       the feature file frontmatter: `advisory-skip-reason: [reason]`. Do not allow
       handoff without a reason — this is the last gate before development starts.
   - If `done`: check that the board review's "Actions required before dev starts"
     checklist has been addressed. If items remain open, list them and ask how to proceed.
6. If the completeness check fails, list what is missing and stop
7. If the check passes:
   - Show the user: status → `ready-for-dev`, owner → `dev`
   - Wait for confirmation
   - Update feature file frontmatter
   - Generate platform-requirements pages for all platforms in scope, incorporating
     design decisions and any board review findings relevant to implementation
   - Update `index.md` and append to `log.md`

## Notes for the agent

- Platform-requirements pages are generated at handoff time (not at intake time) because
  the spec is now complete and can be derived accurately.
- The developer-facing requirements must be in technical language. Translate design
  language: "modal that blocks interaction" → platform-appropriate implementation pattern.
- If a board review found concerns, include relevant concerns in the platform-requirements
  pages for the affected platforms. Developers should not have to cross-reference the
  review file themselves.
