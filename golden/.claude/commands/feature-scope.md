# Feature scope - edit the apps of one feature

<!-- prism:feature-scope-contract:v2 -->

A feature's scope is its `apps` list. Adding an app to the workspace and retiring one never change a feature's scope by themselves; this skill is the explicit edit. Before `ready-for-dev` it is an ordinary write: at `ready-for-design` or `in-design` it also sets the owner to the design owner of the new scope (`designer` while an active app has a UI, otherwise `tech-lead`). From `ready-for-dev` on it is the gated `scope-edit` action that only removes apps, and the board sets the status to the lowest stage of the apps that remain.

## Usage

`/feature-scope [F-XXX] [+app-id ...] [-app-id ...]`

## When to use it

- A feature gains an app that was registered after the feature was written.
- A feature drops an app, or points to another app (remove one, add the other).
- A feature before `released` still lists a retired app: every lifecycle action on it is blocked with `app_retired_in_scope` (`app-retired-in-scope` in lint) until its scope is edited. Remove the retired app, and add the active app that takes its place when there is one.

A `released` feature keeps its scope as history, and a retired app stays valid in it.

From `ready-for-dev` on, the edit only removes an app: a retired app, or an active app that has no evidence rows. Adding an app is refused (`scope_stage_unavailable`; return the feature to design first), so is removing the last app (`scope_empty`). In the same proposal drop the removed app from every criterion's `applies-to`, remove a criterion left with no app, turn an integration criterion left with one app into a per-app one, archive the removed app's evidence rows (and every integration QA row that names it) into a new `## Evidence history` entry headed `### YYYY-MM-DD - scope-edit`, archive the `pending` or `failed` Release row of each remaining app whose criteria changed, add `qa` and `release` to those apps' `app-revalidation`, and set the status to the lowest stage of the remaining apps.

## Workflow

1. Read `knowledge/wiki/SCHEMA.md`, `knowledge/wiki/LIFECYCLE.md`, the complete feature page, its app requirement pages and `prism.workspace.yml` (the apps and their status)
2. Resolve `[F-XXX]` to exactly one feature page. A missing or ambiguous feature is a stop condition
3. Work out the new scope with the user: which apps leave, which apps join. A retired app can only leave; naming one that the feature does not already list is refused (`app_retired`). The new `apps` list is never empty
4. Prepare one proposal:
   - the feature page with the new `apps` list and a rewritten `## App scope` section that describes the new scope, with nothing else changed (status, owner, sources, advisory fields and every other section stay as they are)
   - for each app the scope gains, one new app requirement page `knowledge/wiki/app-requirements/F-XXX-<app-id>.md` with `feature-id`, `app` and `status: pending` and the canonical sections, written only from what the feature page and its sources support. A feature that has not reached `ready-for-dev` needs none yet; a later handoff creates them
   - never rewrite an existing requirement page, and leave the page of a removed app as it is: it stays as history
5. Show the user the old and new scope, the rewritten section, any new requirement page and the log entry, and wait for confirmation
6. Write the confirmed proposal:
   - **Connected board:** call `preview_skill` with `skill` set to `feature-scope` and the changed pages in `changes` (no `moves`), then `apply` the preview after the user confirms it. The board writes the `index.md` lines and the `log.md` entry itself; do not send them
   - **Direct files:** edit the pages, then append one entry to `knowledge/wiki/log.md` in the log format of the wiki schema (`paths:` the pages you changed, `by:` who confirmed it)
7. Run `prism wiki lint` when the CLI is available, and report any `app-retired-in-scope` or `requirement`-related finding that remains

## Rules

- write-capable skill
- change only `apps`, the `## App scope` section, the acceptance criteria where the scope needs it, and new requirement pages; before `ready-for-dev` also the owner at `ready-for-design` or `in-design`; never another field
- both the list and the section change in one proposal; a list change without the section (or the reverse) is refused (`scope_text_unchanged`, `scope_unchanged`)
- never add a retired app, and never add an app from `ready-for-dev` on (`scope_stage_unavailable`)
- the owner of the feature at its current stage edits its scope; do not edit the scope of a feature that another owner is working on without asking the user
- write current-state pages: replace superseded content in place, state rationale as a current fact and keep history in `log.md` and the records; mark each claim `**Decided:**`, `**Observed:**`, `**Proposed:**` or `**Assumed:**` (gaps stay in the Open questions table) and link the evidence of every Decided and Observed claim: the processed intake item, a record or a URL (see Evidence labels in the wiki schema)

## Error and stop conditions

- if the proposal is rejected, read the error code and its details, change only what they name and retry at most 2 more times, then stop and report it
- if the user does not confirm, stop without writing

## Output

Return the feature, the old and new `apps`, the rewritten App scope section, the requirement pages created, how the change was recorded, and any lint finding that remains.
