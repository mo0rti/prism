# Troubleshooting

Each entry gives the symptom, its cause and the fix. Start with `prism doctor --workspace .`: its "Shared board" section is read-only and checks the causes behind most of these entries. The [shared board guide](shared-board.md) documents the commands and tools mentioned here.

- [prism new stops because the template release tag is missing](#prism-new-stops-because-the-template-release-tag-is-missing)
- [The workspace is in a cloud-synced folder](#the-workspace-is-in-a-cloud-synced-folder)
- [The board will not start because the port is busy](#the-board-will-not-start-because-the-port-is-busy)
- [A second board service refuses to start](#a-second-board-service-refuses-to-start)
- [An apply is rejected as stale](#an-apply-is-rejected-as-stale)
- [Calls fail with grant_identity_changed after an upgrade](#calls-fail-with-grant_identity_changed-after-an-upgrade)
- [Workflow install stops on a modified CONNECTED.md](#workflow-install-stops-on-a-modified-connectedmd)
- [An operation is stuck in conflict and blocks other writes](#an-operation-is-stuck-in-conflict-and-blocks-other-writes)
- [Grants stop working after prism.workspace.yml was deleted](#grants-stop-working-after-prismworkspaceyml-was-deleted)
- [Status warns that an external repository has no checkout](#status-warns-that-an-external-repository-has-no-checkout)
- [A cursor is rejected as invalid_cursor or stale_cursor](#a-cursor-is-rejected-as-invalid_cursor-or-stale_cursor)
- [The agent host does not show the Prism tools](#the-agent-host-does-not-show-the-prism-tools)
- [The agent can read but cannot write](#the-agent-can-read-but-cannot-write)
- [The browser asks for the token again](#the-browser-asks-for-the-token-again)
- [Requests fail with local_origin_required](#requests-fail-with-local_origin_required)
- [What the doctor checks mean](#what-the-doctor-checks-mean)

## prism new stops because the template release tag is missing

**Symptom.** `prism new` without `--template`, run from an installed Prism, prints the generation review and `Default generation requires the matching template release tag` followed by the tag, then exits with code 3 and one message. No project is created and no Copier traceback appears:

```text
The template release tag `v0.3.0` is not published, so the default template cannot be used. Pass `--template <path or URL>` or install a released version of Prism.
```

**Cause.** The default template is the canonical GitHub repository at the tag that matches the installed Prism version, so a generated project is always rendered from the template that release shipped with. The tag does not exist yet for a version that has not been released. Other failures, such as no network, keep the Copier output and exit code 5.

**Fix.** Pass `--template` with a local checkout or another template URL, and trust it:

```bash
prism new --preset backend-only --project-name "My App" --dest ../my-app --template /path/to/prism --trust-template --yes
```

Or install a released version of Prism, whose tag is published. `prism workflow install` and the shared board do not use the template, so they work without the tag.

## The workspace is in a cloud-synced folder

**Symptom.** `prism workflow install`, `prism workflow upgrade` or a `prism board` command stops with:

```text
This workspace is inside a cloud-synced folder (for example OneDrive or Dropbox Files On-Demand). Prism needs ordinary local files for safe atomic writes. Move the workspace to a local folder that is not synced, then retry.
```

Connected HTTP and MCP calls return the `cloud_sync_path` error (403) with the same sentence, and `prism doctor --workspace .` reports `[fail] Workspace is outside cloud-synced folders`.

**Cause.** On Windows, OneDrive and Dropbox Files On-Demand mark synced files and folders as reparse points, and Known Folder Move puts Documents and Desktop under OneDrive. A sync engine can rewrite or dehydrate files while Prism writes them, so Prism refuses the workspace.

**Fix.** Move the workspace to a local folder that is not synced, such as `C:\work\my-workspace`, and run the command again. Wiki files are ordinary files, so moving the folder keeps them. Do not copy `.prism/state/` to the new location: issue new grants there instead.

## The board will not start because the port is busy

**Symptom.** `prism board serve` prints one line and exits with code 4, before it creates any board state:

```text
Cannot start the Prism board on port 8765: it is already in use. Choose another with --port.
```

`prism wiki graph --serve` also exits with code 4 and one line when its port is busy.

**Cause.** Another process, often an earlier board still running, is listening on that loopback port. While a board runs on the default port, `prism doctor --workspace .` shows a `[warn]` for port 8765 being busy; that is expected then.

**Fix.** Stop the other process, or choose another port with `prism board serve . --port 8766`. A different port changes the MCP endpoint, so update each agent host's URL to `http://127.0.0.1:8766/mcp`. Browser sign-ins and agent tokens are unaffected.

## A second board service refuses to start

**Symptom.** `prism board serve` exits with code 4 and prints:

```text
Cannot start the Prism board: Another Prism board service or workflow upgrade already holds this workspace lock.
```

**Cause.** One service owns each workspace through `.prism/state/board.lock`. A running board, or a `prism workflow upgrade` in progress, holds it.

**Fix.** Use the board that is already running, or stop it first with Ctrl+C. Wait for an upgrade to finish before starting the board.

## An apply is rejected as stale

**Symptom.** `apply` fails with status 409 and one of `stale_preview`, `stale_move`, `stale_write`, `stale_index_row` or `stale_read_revision`. In the board, a preview that was open when its feature changed says that the feature source changed and disables confirmation.

**Cause.** A file that the preview depended on changed after the preview was made: someone edited the feature page, another operation applied, or new relevant context appeared. A source the skill must read can also appear after the preview, for example a design page created for the feature: `stale_preview` then says "a source this skill must read changed or appeared after the preview; preview again" and `details.paths` names it. Prism refuses to apply a preview whose basis has moved, so a confirmation never covers changes nobody reviewed.

**Fix.** Nothing was written. In the board, choose **Preview again** to build a new preview from the current files; through MCP, read the current files again and create a new preview. Then review and confirm it. Unrelated `index.md` rows and `log.md` additions do not make a preview stale. If an operation was submitted and its outcome is unclear, retrieve its receipt with `operation` before retrying, as described under [Interrupted operations](shared-board.md#interrupted-operations).

## A preview is rejected for a digest

**Symptom.** `preview_skill` fails with status 409 and `missing_read_revisions`, `read_digest_mismatch` or `stale_read_revision`, naming a file under `knowledge/`.

**Cause.** Every source a skill depends on needs the digest of the file as it was read. The board records the digest of each file `read_workspace` returned to a participant and uses it when the proposal leaves `read_revisions` out. `missing_read_revisions` means a required source was never read by this participant (another participant's reads are never used), or the service restarted and cleared the record; `details.paths` lists the sources. `read_digest_mismatch` means a digest sent in `read_revisions` is not one the board returned for that file: a character was mistyped, or the digest was copied from the wrong file or invented. The file did not necessarily change. `stale_read_revision` means the board returned that digest earlier and the file has changed since, or it was created or removed.

**Fix.** After `missing_read_revisions`, read the listed paths with `read_workspace` and send the preview again without `read_revisions`. The error names the file's current digest. After `read_digest_mismatch`, leave `read_revisions` out, or copy the digest from `read_workspace` exactly, and send the preview again. After `stale_read_revision`, read the file again, review what changed, update the proposal if needed and send a new preview.

## A reopen record is rejected as delivery_evidence_not_archived

**Symptom.** `preview_skill` for `feature-reopen` fails with `delivery_evidence_not_archived` (409), and the message names a missing `| app | ... |` row.

**Cause.** A reopen record must keep every prior Delivery evidence row verbatim under its `- Prior completion/release evidence:` bullet. The row must be on that line or on the lines directly below it, before the next `- Label:` bullet or heading. A row placed after another bullet, under its own heading or with changed cell text is not found. Spaces around `|` and letter case do not matter.

**Fix.** Move the rows (a table or a list) directly under the bullet and copy the cells from the active Delivery evidence table. The layout is in `knowledge/wiki/features/_FORMAT.md`. Reopen reads the active table with the same parser that `dev-done` uses, so any column order, header case and app letter case that `dev-done` accepted is accepted here; copy each row exactly as it stands in the table, in the table's own column order.

## A dev-done proposal is rejected for its delivery evidence

**Symptom.** `preview_skill` for `dev-done` fails with `delivery_evidence_required` or `delivery_evidence_invalid` (409). The `details` list the declared `apps`, the `missing_apps` and the `problems`.

**Cause.** `dev-done` takes the delivery evidence in its proposal. The `## Delivery evidence` table of the proposed feature page must have one row per declared app, in the cell order `| App | Implementation | Tests | Release |`, and every cell must be a substantive reference. A table with no app rows, a placeholder such as `n/a` or `[artifact or source reference]`, a duplicate app or an app the feature does not declare is rejected. Nothing was written.

**Fix.** Ask the developer for the missing implementation, test and release references and add the row for each declared app to the proposed table, then preview again. Do not invent a value. A reference the agent cannot check goes into the proposed Post-ship notes as the developer's attestation.

## A Release cell is rejected as release-evidence-required

**Symptom.** `preview_skill` for `dev-done` fails with `release_evidence_required` (409), the `dev-done` transition check `release-evidence-required` is blocked, or `prism wiki lint` reports `release-evidence-required` for a feature that is `done`. The message names the app and says that a commit or pull request proves which code changed, not that it shipped.

**Cause.** The `Release` cell of each delivery evidence row must be release evidence or a delivery attestation. Release evidence is `release: <reference>`, `tag: <reference>` or `deployment: <reference>`, where the reference is the URL of, or a workspace path to, a release, tag or deployment record. A delivery attestation is `attested by <Name>: <reference>`, where the reference is a URL or a path to what that person checked. The prefix is matched without regard to case. A bare commit SHA, a pull-request or merge-request URL, `merged`, a branch name, free text without a prefix and a placeholder are rejected, and so is a `release:` cell whose reference is a pull request or commit link.

**Fix.** Ask the developer for the release, tag or deployment record, or for the person who confirms the shipment and what they checked, and write the cell in one of those forms, for example `release: https://example.com/releases/v1.4.0`. An app in an external repository is linked by URL; no local checkout is needed. Do not invent a value.

## A feature is flagged app-retired-in-scope

**Symptom.** `prism wiki lint` reports `app-retired-in-scope` for a feature before `done`, every lifecycle action on it is blocked with that code, or the board rejects a proposal with `app_retired_in_scope` or `app_retired` (409).

**Cause.** The feature's `apps` still lists an app that `prism app retire` has retired. Retiring an app never changes a feature's scope by itself, so the feature stays flagged until someone edits its scope. A feature that is `done` keeps a retired app as history and is not flagged. `app_retired` is the rejection of a new feature, or of an edit that adds a retired app to a scope.

**Fix.** Edit the feature's `apps` and its `## App scope` explicitly: drop the retired app, or point the work at another app and adjust the app requirement pages, and record the change in `log.md`. No command re-points features. Nothing was deleted by the retirement.

## API work has no app that serves an API

**Symptom.** `prism wiki lint` reports `api-surface-without-api-app`, a `design-handoff`, `dev-start` or `dev-done` check with that code is blocked, or the board rejects a `design-handoff` proposal with `api_surface_without_api_app` (409).

**Cause.** The feature's `## API surface` declares API work, but no active app in its `apps` has the `serves-api` capability. A retired app does not count, and `unknown` counts as serving an API.

**Fix.** Add an app that serves an API to the feature's `apps` (and its app requirement page), or change the API surface through `po-clarify` or `dev-clarify` if the feature has no API work.

## A design-handoff proposal is rejected for its API contract

**Symptom.** `preview_skill` for `design-handoff` fails with `api_contract_required`, `api_contract_untraceable`, `api_contract_initial_status`, `api_contract_not_applicable` or `api_contract_exists` (409). The `details` name the contract `path` and, for `api_contract_untraceable`, the `endpoints` or `models` that the feature's API surface does not support.

**Cause.** A feature whose `## API surface` declares API work (any text other than an empty section or a plain statement such as `None.`) gets its API contract from `design-handoff`: a new page `knowledge/wiki/api-contracts/F-XXX.md` with `status: agreed`, written only from the API surface. The board rejects a missing page, a status other than `agreed`, a page for a feature with no declared API work, a second page for a feature that a contract already covers, and endpoints or data models that the API surface does not name. It never rewrites an existing contract. Nothing was written.

**Fix.** Add or correct the page as the message says, then preview again. When the API surface is too vague to write endpoints from, route a question with `ask`, resolve it with `po-clarify` or `dev-clarify` so the API surface states the endpoint, and run the handoff again. An existing `draft` contract is not changed by the handoff; edit it by hand or replace it through a human-directed file change before `dev-start`.

## A new feature is raw and po-handoff does not accept it

**Symptom.** `po-handoff` reports that the feature is not `specified`, or `po-intake` fails with `invalid_intake_feature` (409).

**Cause.** `po-intake` creates every new feature as `raw` + `po`, and a proposal that sets another status is rejected. `po-handoff` accepts only `specified` + `po`. `po-specify` completes a raw feature and moves it to `specified`; it fails with `required_section_missing` when Design, Related features, API surface, Board review summary or Post-ship notes is empty.

**Fix.** Run `po-specify` on the feature. Under each section it names, write one line of supported content or an explicit statement such as `Not started.`, `None identified.`, `Not reviewed yet.` or `Not shipped yet.`, and `None.` under API surface (any other API surface text needs an API contract page before `dev-start`)

## An intake proposal is rejected for a source link

**Symptom.** `preview_skill` for `po-intake` fails with `intake_source_not_processed` or `source_link_missing` (409). The `details` name the page `path`, the `source` entry and, for `intake_source_not_processed`, the `expected` path.

**Cause.** The page lists a `sources` entry that would not resolve after the proposal applies. A folder under `knowledge/intake/pending/` moves to `knowledge/intake/processed/<folder>` when intake applies, so a link to the pending path would point at a folder that no longer exists, and the next agent could not read its source. A `source_link_missing` entry names a path that is not on disk, is not written by the proposal and is not in the processed folder the proposal's move creates. Nothing was written.

**Fix.** List the processed path, such as `knowledge/intake/processed/<folder>/brief.md`, or another path that exists, then preview again.

## dev-start or dev-done is blocked by an open dev question

**Symptom.** The preflight says `1 open action-relevant question remains: question 4.` and the question's owner is `dev`.

**Cause.** Open questions owned by `dev` block `dev-start` and `dev-done`; they do not block `design-handoff`, which only open `po` or `designer` questions block. `po-clarify` and `design-clarify` resolve only PO and designer questions.

**Fix.** Use `dev-clarify`. It resolves the dev-owned questions of a feature that is not `done`, with the developer's answers. Each section it changes, in the feature or in an app requirement page, must contain an answer verbatim. If the feature is `done`, reopen it with `feature-reopen` first.

## An agent stopped after the board rejected a proposal

**Symptom.** The agent reports a rejection such as `clarify_scope_exceeded` and does not retry, or it reports the same rejection three times.

**Cause.** An agent may retry a rejected proposal only with the fix the error names, at most 2 more times, and never with a wider change. When the error names no fix, needs your decision, or the third preview is rejected, it stops and reports the error code and message.

**Fix.** Read the error and decide: tell the agent what to change, or correct the source it names. Ask it to try again; the count starts anew with your instruction. The agent does not write the files directly. [Agent hosts](agent-hosts.md) describes how Claude Code and Codex behave after a rejection.

## Calls fail with grant_identity_changed after an upgrade

**Symptom.** An agent call or a board action fails with status 409 and `grant_identity_changed`: "The workspace workflow identity changed after this grant was created." Writes can also fail with `workspace_identity_changed`: "The adopted workflow identity changed; writes are disabled until grants are reissued."

**Cause.** A grant records the workflow version and asset digest it was issued under. After `prism workflow upgrade . --apply` changes either one (for example when a newer Prism ships new skills), every earlier grant stops working. Before the upgrade, a workspace pinned to an older digest opens read-only, `prism board status` reports it as incompatible and `prism doctor --workspace .` shows `[fail] Workflow pin is compatible with this Prism installation`. The app scope is part of the board identity too: after `prism app add` changes it, a running board returns `workspace_identity_changed` until you stop it and start it again.

**Fix.** For each workspace:

1. Stop the board service.
2. Preview the upgrade with `prism workflow upgrade .`, then apply it with `prism workflow upgrade . --apply`.
3. Issue new grants with `prism board grant` and update the token in each agent host's environment.
4. Start the board again and sign in with the new human token.

If the message asks for a newer Prism, upgrade Prism first. [Upgrading a pinned workspace](shared-board.md#upgrading-a-pinned-workspace) lists the same steps. After `prism app add`, restart the board with `prism board serve`, and reissue grants for any participant the board still rejects.

## Workflow install stops on a modified CONNECTED.md

**Symptom.** `prism workflow install` or `prism workflow upgrade` exits with code 3 and prints, with or without `--apply`:

```text
Conflict: knowledge/wiki/CONNECTED.md is present with different contents; preserve or reconcile it explicitly before installing the Prism-owned binding.
```

**Cause.** `knowledge/wiki/CONNECTED.md` is a Prism-owned file: it binds the workspace's wiki workflow to the board service. Prism replaces a copy that equals an earlier packaged version, but never overwrites a copy that matches no packaged version, for example one you edited or truncated. Nothing was written. Line endings do not make a copy different: a Git checkout with `core.autocrlf=true` turns the file into CRLF, and Prism still treats an otherwise unmodified CRLF copy as its own. If the conflict appears right after a fresh clone and nobody edited the file, check what changed with `git diff --ignore-space-at-eol`; only a real text difference needs the fix below.

**Fix.**

1. Copy your version to a place outside `knowledge/wiki/`, so your changes are not lost.
2. Delete `knowledge/wiki/CONNECTED.md`.
3. Run the install again: preview with `prism workflow install .`, then apply with `prism workflow install . --apply`. For a generated workspace, use `prism workflow upgrade .` and `prism workflow upgrade . --apply` instead.
4. Put your own notes in your own guidance, such as `AGENTS.md` or `CLAUDE.md`, or in wiki pages that are not Prism-owned. The installed `CONNECTED.md` stays as Prism writes it. Installation does not rewrite your `AGENTS.md` or `CLAUDE.md`; add a short pointer to `knowledge/wiki/CONNECTED.md` there if you want agents to find it.

To keep Git from rewriting the line endings of the Prism-owned text, `prism workflow install` and `prism workflow upgrade` add `knowledge/** text eol=lf` to `.gitattributes` (an existing file keeps its content and receives the rule at the end). In a clone made before that rule existed, run `git add --renormalize .` once after the rule is in place.

## An operation is stuck in conflict and blocks other writes

**Symptom.** An `apply` fails with status 409 and `unresolved_operation_overlap`: "Operation `<id>` has unresolved writes that overlap this operation." `recover` on that operation keeps returning `state: conflict` with `recovery_source_changed`, `recovery_conflict` or `recovery_move_conflict` (for example "Both the recorded intake source and destination are missing"). In the board, the operation stays in the pending operations list. `prism workflow upgrade` also stops while it is listed.

**Cause.** An operation was interrupted or ended in conflict, and a file it depends on was then edited by hand, or its intake folder was renamed or deleted. The board does not guess: it keeps the recorded writes and refuses every new write that overlaps them. A `po-intake` operation lists every existing feature page as a source, so one stuck intake operation can block every feature write.

**Fix.** A writable human decides, in the board's operation review (the **Operations** button in the board header) or with `recover`:

1. Inspect the operation and acknowledge the review. If a page was edited by hand, **Recover recorded operation** now checks the remaining writes against the current files and completes the operation when they still pass the current rules. An agent's own `recover` still stops at the changed source; the human's reviewed recovery does not.
2. If recovery still fails because the folder move or a written file can no longer match the record, choose **Abandon operation** (over HTTP or MCP, `recover` with `abandon: true`, the fresh `review_revision` and `semantic_review_acknowledged: true`). The operation becomes `abandoned`: nothing already written is undone, the receipt lists which writes and folder moves were applied and which were not, and the operation stops blocking other writes. Agents cannot abandon (`abandon_requires_human`), and an operation that can still be recovered is refused with `abandon_not_needed`.
3. Finish by hand what the receipt lists as not applied, or ask for a new preview.

## Grants stop working after prism.workspace.yml was deleted

**Symptom.** After deleting `prism.workspace.yml` and running `prism workflow install . --apply` again, every earlier token fails with `grant_identity_changed` (HTTP 409), and `prism doctor --workspace .` shows:

```text
[warn] At least one active board grant exists
  1 grant(s) were issued for an earlier workflow pin and no longer work.
```

**Cause.** The manifest holds the board identity (`workflow.board_id`). Installing without a manifest creates a new identity, and a grant counts only for the identity it was issued under. The wiki files are untouched.

**Fix.** Issue new grants with `prism board grant "NAME" --kind human|agent --write --path .`, update the token in each agent host's environment and sign in to the browser with the new human token. To keep your existing grants, restore `prism.workspace.yml` from version control or a backup instead of reinstalling.

## Status warns that an external repository has no checkout

**Symptom.** `prism status` or `prism app list` shows `external-repository-unresolved`, and the repository's `checkout` is `unresolved`:

```text
External repository `mobile-apps` has no checkout on this machine (prism.local.yml has no entry for it); add `repositories: {mobile-apps: <absolute path>}` to prism.local.yml. Links into it are skipped.
```

**Cause.** An app lives in a repository other than the workspace, and this machine has not said where it keeps a checkout. `prism.local.yml` is per machine and is not committed. The checkout also stays unresolved, with the reason in the same warning, when the recorded folder does not exist or is a symlink or reparse point, and a relative path is reported as `invalid-local-repository-path`. A `prism.local.yml` that is a symlink or reparse point is ignored.

**Fix.** Create `prism.local.yml` next to `prism.workspace.yml` with the absolute path of your checkout: `repositories:` followed by an indented `mobile-apps: /path/to/mobile-apps`. The warning is harmless otherwise: the workspace loads, and only links into that repository are skipped. [The workspace model](workspace-model.md#repositories-and-prismlocalyml) describes the file.

## A proposal is rejected as invalid_path for a file or folder name

**Symptom.** `preview_skill` fails with `invalid_path` (400) and the message names a path segment, for example ``Workspace path segment `F-001.md:stream.md` contains `:` ``. `details` carry `path`, `segment` and `reason`. Nothing was written.

**Cause.** Windows cannot hold a name that contains `:` `<` `>` `"` `|` `?` `*` or a control character, that ends in a dot or a space, or that is a reserved device name (`CON`, `PRN`, `AUX`, `NUL`, `COM1` to `COM9`, `LPT1` to `LPT9`, with or without an extension, in any case). Prism refuses these names on every operating system, so that a workspace written on Linux or macOS can be checked out on Windows and an apply never starts a write that the filesystem then refuses.

**Fix.** Rename the file or folder in the proposal, for example `F-001-document-review.md`, and preview again. An existing file that already has such a name on Linux or macOS is not listed by `list_workspace` and cannot be read through the board; rename it in the workspace. It does not stop the board: `changes` and the intake and skill previews skip such a name and `changes` reports it under `skipped_paths` with a count and examples, so the rest of the workspace keeps working until you rename it.

## A cursor is rejected as invalid_cursor or stale_cursor

**Symptom.** A paged call (`get_skill`, `get_skill_reference`, `read_workspace`, `list_workspace`, `query`, `get_preview`, `operation`) fails with `invalid_cursor` (400) or `stale_cursor` (409). `list_workspace` can also return `stale_source_cursor`, and `query` can return `stale_read`.

**Cause.** `invalid_cursor` means the cursor does not belong to the request: it was changed, it comes from another tool, skill, path or query, or it was sent with different arguments. `stale_cursor` means the workspace files or facts behind the earlier pages changed, so the remaining pages would no longer fit together.

**Fix.** Pass `next_cursor` back exactly as returned, with the same arguments as the first call, and do not build cursors yourself. After `stale_cursor`, restart from the first page and read the new text again. A reader that joins chunks should check the digest of the joined text, as in the loop under [MCP tool contract](shared-board.md#mcp-tool-contract-version-2). The `changes` cursor is a number, or `N~K` while the oversize event `N` is being returned in chunks; pass it back unchanged. Any other value, such as `1_0`, ` 5 `, `+5` or `1e3`, is `invalid_cursor`.

## The agent host does not show the Prism tools

**Symptom.** The host lists no Prism tools, or the agent says it has none.

**Cause and fix**, in the order to check:

1. **The service is not running or the URL is wrong.** `prism board serve` prints the MCP endpoint on its second line. The host must use that exact URL, including the port.
2. **The token is missing in the host's environment.** The entries in [Connect an agent host](shared-board.md#connect-an-agent-host) read `PRISM_BOARD_TOKEN`. Set it in the shell that starts the host, then restart the host. An unset variable, a revoked grant or a read-only grant used for a write shows up as `unauthorized` or `write_scope_required`.
3. **The host loads tools on demand.** Some hosts keep MCP tools out of the prompt until the agent searches for them. Every Prism tool description starts with `Prism board:`, so ask the agent to search for "Prism board". Claude Code's setting `ENABLE_TOOL_SEARCH=false` loads all tools up front; see Claude Code's [MCP documentation](https://code.claude.com/docs/en/mcp) and [Agent hosts](agent-hosts.md) for how each tested host discovers the tools.
4. **The host does not support the transport.** Prism uses standard Streamable HTTP MCP with a Bearer token. A host without both cannot connect.

Large results do not need a host setting. Every Prism tool result is at most 32,000 characters, and longer text arrives in pages, so Claude Code's default MCP result limit of 25,000 tokens does not need `MAX_MCP_OUTPUT_TOKENS`. A host that sets a much lower limit still needs it raised.

## read_workspace fails with path_not_approved

**Symptom.** `read_workspace` fails with `path_not_approved` (403) for the whole call, and the message names a path such as `prism.workspace.yml` or `.copier-answers.yml`.

**Cause.** `read_workspace` reads only approved UTF-8 text files under `knowledge/wiki/` and `knowledge/intake/`. A skill that says to read the workspace identity is met by `discover`, which reports the board, project and workflow version; the manifest itself is not readable through MCP. One unreadable path fails the call, so the readable paths in it are not returned either.

**Fix.** Leave the path out and read the rest again. The `details` of the error list the approved folders.

## The agent can read but cannot write

**Symptom.** Reads such as `discover` and `query` work, but `preview_skill`, `preview_transition` or `apply` fail with `write_scope_required` (403) or `participant_kind_required` (403).

**Cause.** A grant without `--write` is read-only. Some operations also require a participant of one kind: `preview_transition`, the board's direct human actions `po-handoff`, `design-start` and `dev-start`, needs a human grant, and `preview_skill` needs an agent grant. `list_skills` shows `participant_kinds` and `write_tools` for each skill.

**Fix.** Issue a writable grant with `prism board grant "NAME" --kind agent --write --path .` (or `--kind human`), update the host's token, and revoke the old grant with `prism board revoke PARTICIPANT_ID --path .`.

## The browser asks for the token again

**Symptom.** The board shows "Connect to your Prism board", or "Board session expired" with a **Reconnect** action, after it was working. An apply that runs after the session ended shows the same expiry message with **Reconnect**.

**Cause.** The browser session lasts 12 hours and ends sooner when the service restarts, when the grant is revoked, or when the workflow identity changes. Only a human grant can sign in to the browser, so an agent token is refused with `human_grant_required`.

**Fix.** Choose **Reconnect** (it reloads the page) and enter the human token again. If it was lost, issue a new human grant; tokens are shown once and cannot be recovered. Open previews are not approved again: preview the action again after you sign in.

## Requests fail with local_origin_required

**Symptom.** A request to the board fails with status 400 and `local_origin_required`: "Use the local same-origin Prism board address."

**Cause.** The service accepts only requests whose `Host` is `127.0.0.1:PORT` or `localhost:PORT` and whose `Origin` and `Sec-Fetch-Site` headers, when present, are same-origin. A reverse proxy, a custom host name or any address other than `127.0.0.1` or `localhost` fails this check on purpose. [SECURITY.md](../SECURITY.md) explains why.

**Fix.** Open `http://127.0.0.1:8765/` (or the port you chose) on the same computer, and point agent hosts at `http://127.0.0.1:8765/mcp`.

## What the doctor checks mean

`prism doctor --workspace .` prints a "Shared board" section. Each line starts with `[ok]`, `[warn]`, `[fail]` or `[skip]`, and a line that needs action is followed by a `Fix:` line. The section never creates board state. Only `[fail]` lines change the exit code, which is 3.

| Check | What a problem means | What to do |
| --- | --- | --- |
| Workspace is outside cloud-synced folders | `[fail]`: the path or one of its parents is a cloud placeholder. | [Move the workspace](#the-workspace-is-in-a-cloud-synced-folder). |
| Workflow pin is compatible with this Prism installation | `[fail]`: the workspace pin does not match this Prism. A workspace with no pin gets `[warn]` and the checks below do not run. | Preview `prism workflow upgrade` (or `prism workflow install` for a non-generated workspace with no pin) and apply it after review. See [grant_identity_changed](#calls-fail-with-grant_identity_changed-after-an-upgrade). |
| At least one active board grant exists | `[warn]`: no grant exists yet (`No grants yet.`), every grant is revoked (`No active grants (N revoked).`) or every grant predates the current pin. `[fail]`: the board state cannot be read safely. | Issue a grant with `prism board grant`. |
| Default board port 8765 is free | `[warn]`: the port is busy. Expected while the board runs. | [Choose another port](#the-board-will-not-start-because-the-port-is-busy) if no board is running. |
| `.prism/state` is ignored by git | `[fail]`: grants and the operation journal could be committed. `[skip]`: git is unavailable or the folder is not a repository. | Add `.prism/state/` to `.gitignore`. |

Warnings and skips leave the exit code at 0.
