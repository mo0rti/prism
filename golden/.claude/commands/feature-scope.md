# Feature scope - edit the apps of one feature

<!-- prism:feature-scope-contract:v1 -->

A feature's scope is its `apps` list. Adding an app to the workspace and retiring one never change a feature's scope by themselves; this skill is the explicit edit. It never changes the feature's status or owner.

## Usage

`/feature-scope [F-XXX] [+app-id ...] [-app-id ...]`

## When to use it

- A feature gains an app that was registered after the feature was written.
- A feature drops an app, or points to another app (remove one, add the other).
- A feature before `done` still lists a retired app: every lifecycle action on it is blocked with `app_retired_in_scope` (`app-retired-in-scope` in lint) until its scope is edited. Remove the retired app, and add the active app that takes its place when there is one.

A `done` feature keeps its scope as history, and a retired app stays valid in it. To change the scope of a shipped feature, reopen it with `/feature-reopen` first.

## Workflow

1. Read `knowledge/wiki/SCHEMA.md`, `knowledge/wiki/LIFECYCLE.md`, the complete feature page, its app requirement pages and `prism.workspace.yml` (the apps and their status)
2. Resolve `[F-XXX]` to exactly one feature page that is not `done`. A missing, ambiguous or `done` feature is a stop condition
3. Work out the new scope with the user: which apps leave, which apps join. A retired app can only leave; naming one that the feature does not already list is refused (`app_retired`). The new `apps` list is never empty
4. Prepare one proposal:
   - the feature page with the new `apps` list and a rewritten `## App scope` section that describes the new scope, with nothing else changed (status, owner, sources, advisory fields and every other section stay as they are)
   - for each app the scope gains, one new app requirement page `knowledge/wiki/app-requirements/F-XXX-<app-id>.md` with `feature-id`, `app` and `status: pending` and the canonical sections, written only from what the feature page and its sources support. A feature that has not reached `ready-for-dev` needs none yet; a later handoff creates them
   - never rewrite an existing requirement page, and leave the page of a removed app as it is: it stays as history
5. Show the user the old and new scope, the rewritten section, any new requirement page and the log entry. Direct files: wait for confirmation before writing. Connected board: do not stop before the preview; show this together with the complete preview of step 6 and wait for the confirmation there
6. Write the confirmed proposal:
   - **Connected board:** call `preview_skill` with `skill` set to `feature-scope` and the changed pages in `changes` (no `moves`), then `apply` the preview after the user confirms it. The board writes the `index.md` lines and the `log.md` entry itself; do not send them
   - **Direct files:** edit the pages, then append one entry to `knowledge/wiki/log.md` in the log format of the wiki schema (`paths:` the pages you changed, `by:` who confirmed it)
7. Run `prism wiki lint` when the CLI is available, and report any `app-retired-in-scope` or `requirement`-related finding that remains

## Rules

- write-capable skill
- change only `apps`, the `## App scope` section and new requirement pages; never a status, an owner or another field
- both the list and the section change in one proposal; a list change without the section (or the reverse) is refused (`scope_text_unchanged`, `scope_unchanged`)
- never add a retired app, and never edit a `done` feature (`scope_stage_unavailable`)
- the owner of the feature at its current stage edits its scope; do not edit the scope of a feature that another owner is working on without asking the user
- write current-state pages: replace superseded content in place, state rationale as a current fact and keep history in `log.md` and the records; mark each claim `**Decided:**`, `**Observed:**`, `**Proposed:**` or `**Assumed:**` (gaps stay in the Open questions table) and link the evidence of every Decided and Observed claim: the processed intake item, a record or a URL (see Evidence labels in the wiki schema)

## Error and stop conditions

- if the proposal is rejected, read the error code and its details, change only what they name and retry at most 2 more times, then stop and report it
- if the user does not confirm, stop without writing

## Output

Return the feature, the old and new `apps`, the rewritten App scope section, the requirement pages created, how the change was recorded, and any lint finding that remains.
