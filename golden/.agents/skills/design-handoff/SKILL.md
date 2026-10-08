---
name: design-handoff
description: Move a feature from design to development readiness. Use when both design tracks are settled and the feature should be handed to development with generated app requirements.
---

# Design handoff — move a feature to ready-for-development

<!-- prism:design-handoff-contract:v2 -->

Use this skill to move one feature into `ready-for-dev` and generate app requirements. The feature
has two design tracks, `ui` and `technical`. This skill needs both settled (`done` or
`not-applicable`) and `design-reaffirm` empty after the handoff; it may settle either track in the
same confirmation, and `$design-ui-done` and `$tech-design-done` settle one track
each beforehand.

## Usage

`$design-handoff [F-XXX]`

## Read-only preflight

When available, use:

```text
prism wiki transition-preflight F-XXX [path] --action design-handoff --json
```

Accept it only with common envelope schema 1, command facts, capability version
3 and an action-specific `design-handoff` surface, transition version 2, target
owner `dev`, and a consistent snapshot. The Prism version alone does not prove
support. If any required fact, schema, action, capability, or snapshot is
missing or fails, fall back to direct-file checks. The preflight is copy-only
and never authorizes a write.

## Workflow

1. Resolve exactly one `knowledge/wiki/features/[F-XXX]-[slug].md` source file
   and require `status: ready-for-design` or `in-design` with `owner` the design owner of the scope (`designer` while an active
   app has a UI, otherwise `tech-lead`).
2. Read SCHEMA, LIFECYCLE, `status-board.md`, the complete feature, linked design and technical design pages,
   workspace identity, current requirements/API/advisory evidence, and active revalidation.
3. Read the feature's `design-tracks` and `design-reaffirm`. Each track is one of:
   - settled (`done`, or `not-applicable` with its reason) and not listed in `design-reaffirm`: nothing to do;
   - settled and listed in `design-reaffirm`: the other track changed since; the handoff reaffirms it only
     with the owner's confirmation and no page change;
   - `pending`, or absent before design started: the handoff settles it in this confirmation, or stops.
4. For a track the handoff settles, run that track's completeness check, the same as its own skill:
   - **`ui`**: design pages in `knowledge/wiki/design/` whose `apps` cover every active scoped app with
     `has-ui` true or unknown (`unknown` counts as a UI), covering the UI states the acceptance criteria
     imply; or `not-applicable` with a non-blank `ui-reason` (`design-coverage-incomplete`,
     `ui-exemption-reason-required`). When no active app has a UI the track is `not-applicable` already.
   - **`technical`**: a complete technical design page in `knowledge/wiki/technical-design/` whose Test
     strategy names every criterion ID, and, when `## API surface` declares API work, the `agreed` API
     contract; or `not-applicable` with a non-blank `technical-reason` and no API work
     (`technical-design-incomplete`, `test-strategy-incomplete`, `technical-track-required`).
   Settling a track needs the role of that track on top of the design owner: `designer` for `ui`,
   `tech-lead` for `technical`. For all features: no open questions with owner = `po`, `designer` or
   `tech-lead`. An open question with owner = `dev` does not block this handoff; it stays open for
   `$dev-clarify`.
5. Check `advisory-review` field:
   - If `pending`: board review has not been run. Inform the user. Ask:
     "Do you want to run board-review F-XXX before handing to development?"
     - If yes: run board review, then re-check completeness (step 4) before continuing.
     - If no: set `advisory-review: skipped` and require a reason. Record the reason in
       the feature file frontmatter: `advisory-skip-reason: [reason]`. Do not allow
       handoff without a reason — this is the last gate before development starts.
   - If `done`: check that the board review's "Actions required before dev starts"
     checklist has been addressed. If items remain open, list them and ask how to proceed.
6. Check active `revalidation` domains. An active `specification` domain blocks
   this handoff. If `design` or `technical-design` is active, prepare a fresh verification of that track
   and propose clearing only those domains; evaluate the proposal while the source is
   unchanged. Do not clear other domains or shared contracts here.
7. If the completeness check fails, list what is missing and stop
8. If the check passes:
   - Show the user: status → `ready-for-dev`, owner → `dev`, and the tracks the handoff settles
   - Wait for confirmation
   - Update the feature file frontmatter: `status` and `owner`, the `design-tracks` the handoff settles
     (and `design-reaffirm`), and the verified `design` and `technical-design` revalidation domains.
     The `## Design` section may change; every other body section stays exactly as it is, and
     the service rejects any other change
   - Write the pages of each track the handoff settles, as its own skill would (design pages for `ui`,
     the technical design page and the API contract for `technical`). A page of a track the handoff does not
     settle is not written
   - Write the requirement pages (below) incorporating design decisions and any board review findings
     relevant to implementation
   - Update the feature's row in `status-board.md`, add the `index.md` line of each page created, and append a `log.md` entry in the log format that the wiki schema defines

Before confirmation show every feature, generated page, status board, index, and log
write. Reread the source and context immediately before confirmation and once
again after it. The preflight and any copied request are copy-only and never
authorize a write. Decline or cancel means no write. If a multi-file write is partial,
report the exact observed state and require fresh recovery; no transaction is
implied.

## Requirement pages

The feature leaves the handoff with exactly one requirement page per scoped app, in
`knowledge/wiki/app-requirements/F-XXX-[app].md`:

- missing for a scoped app: create it with `status: pending`;
- existing at `pending` or `in-progress`: it may change its body sections (What to build, Technical
  constraints, Design reference, API contract reference, Acceptance criteria, Dependencies) and is set to `pending`;
- existing at `done`: leave it unchanged; the board rejects a change with `requirement_body_change`.

## API contract

The contract belongs to the technical track. Only a handoff that settles the technical track writes
a contract page, and only `$tech-design-done` or this skill with the `tech-lead` role does
(`lifecycle_write_scope` otherwise). See `$tech-design-done` for its rules: created once at
`version: 1`, `status: agreed`; revised only while the feature is in design, with `version` raised by
one (`contract_revision_required`) and not while another feature that links it is between
`ready-for-dev` and `ready-for-release` (`shared_contract_in_use`); written only from the API surface
text, each endpoint as `METHOD /path`.

- Write it only from the API surface text. An API surface that is too vague to write from needs `ask` and
  `po-clarify` or `dev-clarify` first.
- Link the page from each generated requirement's `## API contract reference`.
- Never rewrite an existing contract page unless the technical track is settled in this handoff.
- API work needs an app that serves an API: at least one active app in the feature's
  `apps` must have the `serves-api` capability (`unknown` counts as serving one).
  Otherwise the handoff is blocked with `api-surface-without-api-app` (`api_surface_without_api_app`
  on the connected board); route the question to `$po-clarify` or `$dev-clarify` instead of
  writing a contract.

## Rules

- write-capable skill
- do not hand off an incomplete feature
- do not write status changes or app requirements until the user confirms the handoff
- In each generated requirement page, `## Dependencies` lists only real dependencies
  (other feature IDs or app-requirement files that must complete first) or says
  `None.`. Never write an open question, note or caveat there; `$dev-clarify` may not
  change that section, so the text would stay after the question is answered.
- Open questions owned by `po`, `designer` or `tech-lead` block this handoff: resolve them first with
  `$po-clarify` or `$design-clarify`. An open question owned by `dev` does not block it: it
  stays open in the feature's Open questions table, which this handoff cannot change, and
  `$dev-clarify` resolves it before `$dev-start`.

- App-requirements pages are generated at handoff time (not at intake time) because
  the spec is now complete and can be derived accurately.
- The developer-facing requirements must be in technical language. Translate design
  language: "modal that blocks interaction" → implementation pattern that fits the app's stack.
- If a board review found concerns, include relevant concerns in the app-requirements
  pages for the affected apps. Developers should not have to cross-reference the
  review file themselves.
- write current-state pages: replace superseded content in place, state rationale as a current fact and keep history in `log.md` and the records; mark each claim `**Decided:**`, `**Observed:**`, `**Proposed:**` or `**Assumed:**` (gaps stay in the Open questions table) and link the evidence of every Decided and Observed claim: the processed intake item, a record or a URL (see Evidence labels in the wiki schema)

## Output behavior

Return:

- completeness result and the state of each design track
- advisory-review result
- any blocking missing items
- proposed status and owner change, and the tracks the handoff settles
- generated app-requirements targets and the pages of each settled track, after confirmation

## Error and stop conditions

- if the feature file does not exist, return a clean missing-feature response
- if required design or advisory prerequisites are not met, stop without writing
- if the user does not confirm the handoff, stop without writing
