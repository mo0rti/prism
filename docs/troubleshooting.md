# Troubleshooting

Each entry gives the symptom, its cause and the fix. Start with `prism doctor --workspace .`: its "Shared board" section is read-only and checks the causes behind most of these entries. The [shared board guide](shared-board.md) documents the commands and tools mentioned here.

An error code names the failed check, the HTTP status is in parentheses, and the message names the place and the fix. The lifecycle codes are grouped by stage, in the order a feature meets them:

- [Installation and the workspace](#installation-and-the-workspace)
- [The board and the agent host](#the-board-and-the-agent-host)
- [Roles, proposals and approval](#roles-proposals-and-approval)
- [Previews, applies and interrupted operations](#previews-applies-and-interrupted-operations)
- [Lifecycle codes by stage](#lifecycle-codes-by-stage)
  - [Intake and specification](#intake-and-specification)
  - [Design and the API contract](#design-and-the-api-contract)
  - [Implementation and delivery evidence](#implementation-and-delivery-evidence)
  - [QA and bugs](#qa-and-bugs)
  - [Release](#release)
  - [Returns, reopening and scope](#returns-reopening-and-scope)
  - [Operations: incidents and the status board](#operations-incidents-and-the-status-board)
- [Lint reports a lifecycle finding](#lint-reports-a-lifecycle-finding)
- [Other lint findings](#other-lint-findings)
- [What the doctor checks mean](#what-the-doctor-checks-mean)

## Installation and the workspace

### prism new stops because the template release tag is missing

**Symptom.** `prism new` without `--template`, run from an installed Prism, prints the generation review and `Default generation requires the matching template release tag` followed by the tag, then exits with code 3 and one message. No project is created and no Copier traceback appears:

```text
The template release tag `v0.8.0` is not published, so the default template cannot be used. Pass `--template <path or URL>` or install a released version of Prism.
```

**Cause.** The default template is the canonical GitHub repository at the tag that matches the installed Prism version, so a generated project is always rendered from the template that release shipped with. The tag does not exist yet for a version that has not been released. Other failures, such as no network, keep the Copier output and exit code 5.

**Fix.** Pass `--template` with a local checkout or another template URL, and trust it:

```bash
prism new --preset backend-only --project-name "My App" --dest ../my-app --template /path/to/prism --trust-template --yes
```

Or install a released version of Prism, whose tag is published. `prism workflow install` and the shared board do not use the template, so they work without the tag.

### prism update stops before merging

**Symptom.** `prism update` prints an update report with a layer marked `CONFLICT in N file(s)` and `Update stopped before merging` followed by the names of the conflicted layers, then exits with code 6.

```text
workspace layer: updated, committed as d2149c3
app backend: updated, committed as 84480a7
app api-two: CONFLICT in 1 file(s), committed as 6565f95
    services/api-two/AGENTS.md
```

**Cause.** `prism update` brings each layer of the workspace (the workspace layer, then each scaffolded app) to the new template tag on its own update branch, with one commit per layer. Copier exits with 0 when a change of the template overlaps a change you made, so Prism scans every layer for `.rej` files and conflict markers and stops before anything is merged. The branch already holds the conflicting file, with the overlap between `<<<<<<< before updating` and `>>>>>>> after updating`.

**Fix.** On the update branch, which stays checked out, open each listed file, keep the text you want and remove the markers, then commit. Merge the branch when you are satisfied: `git switch <your branch>` and `git merge prism-update-<tag>`. To abandon the update, `git switch <your branch>` and `git branch -D prism-update-<tag>`; your branch was never changed. Other stops before any change: the working tree is not clean, git does not know who commits (`git config user.name` and `user.email`), the branch `prism-update-<tag>` already exists, or a scaffolded app has no `<path>/.copier-answers.yml` (restore it from git, or retire the app with `prism app retire` to leave it out of the update). `prism update` also refuses a layer whose saved answers cannot be trusted: an app that records another template source than the workspace's (`records the template source ... which is not the workspace's approved source`), a revision that is not a plain tag or commit name, an identity, path or package that disagrees with the manifest and the workspace, or an answers file behind a symlink or junction. The workspace's own `.copier-answers.yml` gets the same check: it must select the `workspace` layer and hold only the workspace layer's answers (`selects the layer ...`, `records answer(s) that the workspace layer does not ask`), and its project name, slug, package identifier, description and app list must be safe to render. A link at its place is never opened (`.copier-answers.yml is a symlink or a reparse point`). Restore the file from git or correct the manifest; `--trust-template` does not override this check.

### The workspace is in a cloud-synced folder

**Symptom.** `prism workflow install`, `prism workflow upgrade` or a `prism board` command stops with:

```text
This workspace is inside a cloud-synced folder (for example OneDrive or Dropbox Files On-Demand). Prism needs ordinary local files for safe atomic writes. Move the workspace to a local folder that is not synced, then retry.
```

Connected HTTP and MCP calls return the `cloud_sync_path` error (403) with the same sentence, and `prism doctor --workspace .` reports `[fail] Workspace is outside cloud-synced folders`.

**Cause.** On Windows, OneDrive and Dropbox Files On-Demand mark synced files and folders as reparse points, and Known Folder Move puts Documents and Desktop under OneDrive. A sync engine can rewrite or dehydrate files while Prism writes them, so Prism refuses the workspace.

**Fix.** Move the workspace to a local folder that is not synced, such as `C:\work\my-workspace`, and run the command again. Wiki files are ordinary files, so moving the folder keeps them. Do not copy `.prism/state/` to the new location: issue new grants there instead.

### Workflow install stops on a modified CONNECTED.md

**Symptom.** `prism workflow install` or `prism workflow upgrade` exits with code 3 and prints, with or without `--apply`:

```text
Conflict: knowledge/wiki/CONNECTED.md is present with different contents; preserve or reconcile it explicitly before installing the Prism-owned binding.
```

**Cause.** `knowledge/wiki/CONNECTED.md` is a Prism-owned file: it binds the workspace's wiki workflow to the board service. Prism never overwrites a copy that differs from the packaged text, for example one you edited or truncated. Nothing was written. Line endings do not make a copy different: a Git checkout with `core.autocrlf=true` turns the file into CRLF, and Prism still treats an otherwise unmodified CRLF copy as its own. If the conflict appears right after a fresh clone and nobody edited the file, check what changed with `git diff --ignore-space-at-eol`; only a real text difference needs the fix below.

**Fix.**

1. Copy your version to a place outside `knowledge/wiki/`, so your changes are not lost.
2. Delete `knowledge/wiki/CONNECTED.md`.
3. Run the install again: preview with `prism workflow install .`, then apply with `prism workflow install . --apply`. For a generated workspace, use `prism workflow upgrade .` and `prism workflow upgrade . --apply` instead.
4. Put your own notes in your own guidance, such as `AGENTS.md` or `CLAUDE.md`, or in wiki pages that are not Prism-owned. The installed `CONNECTED.md` stays as Prism writes it. Installation does not rewrite your `AGENTS.md` or `CLAUDE.md`; add a short pointer to `knowledge/wiki/CONNECTED.md` to your `AGENTS.md`, and `@AGENTS.md` to your `CLAUDE.md`, if you want agents to find it.

To keep Git from rewriting the line endings of the Prism-owned text, `prism workflow install` and `prism workflow upgrade` add `knowledge/** text eol=lf` to `.gitattributes` (an existing file keeps its content and receives the rule at the end). In a clone made before that rule existed, run `git add --renormalize .` once after the rule is in place.

### Grants stop working after prism.workspace.yml was deleted

**Symptom.** After deleting `prism.workspace.yml` and running `prism workflow install . --apply` again, every earlier token fails with `grant_identity_changed` (HTTP 409), and `prism doctor --workspace .` shows:

```text
[warn] At least one active board grant exists
  1 grant(s) were issued for an earlier workflow pin and no longer work.
```

**Cause.** The manifest holds the board identity (`workflow.board_id`). Installing without a manifest creates a new identity, and a grant counts only for the identity it was issued under. The wiki files are untouched.

**Fix.** Issue new grants with `prism board grant "NAME" --kind human|agent --write --path .`, update the token in each agent host's environment and sign in to the browser with the new human token. To keep your existing grants, restore `prism.workspace.yml` from version control or a backup instead of reinstalling.

### Status warns that an external repository has no checkout

**Symptom.** `prism status` or `prism app list` shows `external-repository-unresolved`, and the repository's `checkout` is `unresolved`:

```text
External repository `mobile-apps` has no checkout on this machine (prism.local.yml has no entry for it); add `repositories: {mobile-apps: <absolute path>}` to prism.local.yml. Links into it are skipped.
```

**Cause.** An app lives in a repository other than the workspace, and this machine has not said where it keeps a checkout. `prism.local.yml` is per machine and is not committed. The checkout also stays unresolved, with the reason in the same warning, when the recorded folder does not exist or is a symlink or reparse point, and a relative path is reported as `invalid-local-repository-path`. A `prism.local.yml` that is a symlink or reparse point is ignored. `prism wiki lint` reports the same warning once for each repository that a `repo:<repository-id>/<path>` link points into, and skips those links.

**Fix.** Create `prism.local.yml` next to `prism.workspace.yml` with the absolute path of your checkout: `repositories:` followed by an indented `mobile-apps: /path/to/mobile-apps`. The warning is harmless otherwise: the workspace loads, and only links into that repository are skipped. [The workspace model](workspace-model.md#repositories-and-prismlocalyml) describes the file.

## The board and the agent host

### The board will not start because the port is busy

**Symptom.** `prism board serve` prints one line and exits with code 4, before it creates any board state:

```text
Cannot start the Prism board on port 8765: it is already in use. Choose another with --port.
```

`prism wiki graph --serve` also exits with code 4 and one line when its port is busy.

**Cause.** Another process, often an earlier board still running, is listening on that loopback port. While a board runs on the default port, `prism doctor --workspace .` shows a `[warn]` for port 8765 being busy; that is expected then.

**Fix.** Stop the other process, or choose another port with `prism board serve . --port 8766`. A different port changes the MCP endpoint, so update each agent host's URL to `http://127.0.0.1:8766/mcp`. Browser sign-ins and agent tokens are unaffected.

### A second board service refuses to start

**Symptom.** `prism board serve` exits with code 4 and prints:

```text
Cannot start the Prism board: Another Prism board service or workflow upgrade already holds this workspace lock.
```

**Cause.** One service owns each workspace through `.prism/state/board.lock`. A running board, or a `prism workflow upgrade` in progress, holds it.

**Fix.** Use the board that is already running, or stop it first with Ctrl+C. Wait for an upgrade to finish before starting the board.

### Calls fail with grant_identity_changed after an upgrade

**Symptom.** An agent call or a board action fails with status 409 and `grant_identity_changed`: "The workspace workflow identity changed after this grant was created." Writes can also fail with `workspace_identity_changed`: "The adopted workflow identity changed; writes are disabled until grants are reissued."

**Cause.** A grant records the workflow version and asset digest it was issued under. After `prism workflow upgrade . --apply` changes either one (for example when a newer Prism ships new skills), every earlier grant stops working. Before the upgrade, a workspace pinned to an older digest opens read-only, `prism board status` reports it as incompatible and `prism doctor --workspace .` shows `[fail] Workflow pin is compatible with this Prism installation`. The app scope is part of the board identity too: after `prism app add` changes it, a running board returns `workspace_identity_changed` until you stop it and start it again.

**Fix.** For each workspace:

1. Stop the board service.
2. Preview the upgrade with `prism workflow upgrade .`, then apply it with `prism workflow upgrade . --apply`.
3. Issue new grants with `prism board grant` and update the token in each agent host's environment.
4. Start the board again and sign in with the new human token.

If the message asks for a newer Prism, upgrade Prism first. [Upgrading a pinned workspace](shared-board.md#upgrading-a-pinned-workspace) lists the same steps. After `prism app add`, restart the board with `prism board serve`, and reissue grants for any participant the board still rejects.

### The agent host does not show the Prism tools

**Symptom.** The host lists no Prism tools, or the agent says it has none.

**Cause and fix**, in the order to check:

1. **The service is not running or the URL is wrong.** `prism board serve` prints the MCP endpoint on its second line. The host must use that exact URL, including the port.
2. **The token is missing in the host's environment.** The entries in [Connect an agent host](shared-board.md#connect-an-agent-host) read `PRISM_BOARD_TOKEN`. Set it in the shell that starts the host, then restart the host. An unset variable, a revoked grant or a read-only grant used for a write shows up as `unauthorized` or `write_scope_required`.
3. **The host loads tools on demand.** Some hosts keep MCP tools out of the prompt until the agent searches for them. Every Prism tool description starts with `Prism board:`, so ask the agent to search for "Prism board". Claude Code's setting `ENABLE_TOOL_SEARCH=false` loads all tools up front; see Claude Code's [MCP documentation](https://code.claude.com/docs/en/mcp) and [Agent hosts](agent-hosts.md) for how each tested host discovers the tools.
4. **The host does not support the transport.** Prism uses standard Streamable HTTP MCP with a Bearer token. A host without both cannot connect.

Large results do not need a host setting. Every Prism tool result is at most 48,000 characters, and longer text arrives in pages, so Claude Code's default MCP result limit of 25,000 tokens does not need `MAX_MCP_OUTPUT_TOKENS`. A host that sets a much lower limit still needs it raised.

### The agent can read but cannot write

**Symptom.** Reads such as `discover` and `query` work, but `preview_skill`, `preview_transition` or `apply` fail with `write_scope_required` (403) or `participant_kind_required` (403).

**Cause.** A grant without `--write` is read-only. Some operations also require a participant of one kind: `preview_transition`, the board's direct human actions `po-handoff`, `design-start` and `dev-start`, needs a human grant, and `preview_skill` needs an agent grant. `list_skills` shows `participant_kinds` and `write_tools` for each skill.

**Fix.** Issue a writable grant with `prism board grant "NAME" --kind agent --write --path .` (or `--kind human`), update the host's token, and revoke the old grant with `prism board revoke PARTICIPANT_ID --path .`.

### The browser asks for the token again

**Symptom.** The board shows "Connect to your Prism board", or "Board session expired" with a **Reconnect** action, after it was working. An apply that runs after the session ended shows the same expiry message with **Reconnect**.

**Cause.** The browser session lasts 12 hours and ends sooner when the service restarts, when the grant is revoked, or when the workflow identity changes. Only a human grant can sign in to the browser, so an agent token is refused with `human_grant_required`.

**Fix.** Choose **Reconnect** (it reloads the page) and enter the human token again. If it was lost, issue a new human grant; tokens are shown once and cannot be recovered. Open previews are not approved again: preview the action again after you sign in.

### Requests fail with local_origin_required

**Symptom.** A request to the board fails with status 400 and `local_origin_required`: "Use the local same-origin Prism board address."

**Cause.** The service accepts only requests whose `Host` is `127.0.0.1:PORT` or `localhost:PORT` and whose `Origin` and `Sec-Fetch-Site` headers, when present, are same-origin. A reverse proxy, a custom host name or any address other than `127.0.0.1` or `localhost` fails this check on purpose. [SECURITY.md](../SECURITY.md) explains why.

**Fix.** Open `http://127.0.0.1:8765/` (or the port you chose) on the same computer, and point agent hosts at `http://127.0.0.1:8765/mcp`.

### A cursor is rejected as invalid_cursor or stale_cursor

**Symptom.** A paged call (`get_skill`, `get_skill_reference`, `read_workspace`, `list_workspace`, `query`, `get_preview`, `operation`) fails with `invalid_cursor` (400) or `stale_cursor` (409). `list_workspace` can also return `stale_source_cursor`, and `query` can return `stale_read`.

**Cause.** `invalid_cursor` means the cursor does not belong to the request: it was changed, it comes from another tool, skill, path or query, or it was sent with different arguments. `stale_cursor` means the workspace files or facts behind the earlier pages changed, so the remaining pages would no longer fit together.

**Fix.** Pass `next_cursor` back exactly as returned, with the same arguments as the first call, and do not build cursors yourself. After `stale_cursor`, restart from the first page and read the new text again. A reader that joins chunks should check the digest of the joined text, as in the loop under [MCP tool contract](shared-board.md#mcp-tool-contract-version-4). The `changes` cursor is a number, or `N~K` while the oversize event `N` is being returned in chunks; pass it back unchanged. Any other value, such as `1_0`, ` 5 `, `+5` or `1e3`, is `invalid_cursor`.

### read_workspace fails with path_not_approved

**Symptom.** `read_workspace` fails with `path_not_approved` (403) for the whole call, and the message names a path such as `prism.workspace.yml` or `.copier-answers.yml`.

**Cause.** `read_workspace` reads only approved UTF-8 text files under `knowledge/wiki/` and `knowledge/intake/`. A skill that says to read the workspace identity is met by `discover`, which reports the board, project and workflow version; the manifest itself is not readable through MCP. One unreadable path fails the call, so the readable paths in it are not returned either.

**Fix.** Leave the path out and read the rest again. The `details` of the error list the approved folders.

### A proposal is rejected as invalid_path for a file or folder name

**Symptom.** `preview_skill` fails with `invalid_path` (400) and the message names a path segment, for example ``Workspace path segment `F-001.md:stream.md` contains `:` ``. `details` carry `path`, `segment` and `reason`. Nothing was written.

**Cause.** Windows cannot hold a name that contains `:` `<` `>` `"` `|` `?` `*` or a control character, that ends in a dot or a space, or that is a reserved device name (`CON`, `PRN`, `AUX`, `NUL`, `COM1` to `COM9`, `LPT1` to `LPT9`, with or without an extension, in any case). Prism refuses these names on every operating system, so that a workspace written on Linux or macOS can be checked out on Windows and an apply never starts a write that the filesystem then refuses.

**Fix.** Rename the file or folder in the proposal, for example `F-001-document-review.md`, and preview again. An existing file that already has such a name on Linux or macOS is not listed by `list_workspace` and cannot be read through the board; rename it in the workspace. It does not stop the board: `changes` and the intake and skill previews skip such a name and `changes` reports it under `skipped_paths` with a count and examples, so the rest of the workspace keeps working until you rename it.

## Roles, proposals and approval

A gated action needs a human who holds a role, and the board is the only place that approves it. These codes are returned in the order the board checks them ([the flow](shared-board.md#roles-proposals-and-approval)).

| Code (status) | Cause | Fix |
| --- | --- | --- |
| `invalid_role`, `agent_role_forbidden`, `role_requires_write` (400) | `prism board grant` was given an unknown role or a role twice, a role for an agent, or a role without `--write`. Nothing was stored. | Use a role of `po`, `designer`, `tech-lead`, `dev`, `qa`, `release`, once each, on a writable human grant: `prism board grant "Quinn" --kind human --write --role qa,release --path .` |
| `role_required` (403) | The grant that previews or applies the action does not hold the role the action needs. The message names the required roles and the roles of the grant. | Roles are fixed for a grant's life. Issue a grant with the role (`--role`), revoke the old one with `prism board revoke`, sign in with the new human token, or have a person who holds the role approve. |
| `approval_required` (403) | An agent applied, recovered or declined a gated preview or operation. | Leave it in the proposal list. A human who holds the role opens **Proposals** in the board and chooses **Approve and apply**. |
| `approval_requires_board_session` (403) | A gated apply, decline, recovery or repair came over MCP or a Bearer token, even from a human token with the right roles. | Sign in to the board in the browser with the human token and approve there. |
| `approval_review_required` (409) | The apply carries no `review_revision`, or its `semantic_review_acknowledged` is not the literal `true`. | In the board, open the proposal, review it and tick the acknowledgement. Over HTTP, read the preview with `get_preview`, then apply with its `approval.review_revision` and `semantic_review_acknowledged: true`. |
| `stale_approval_review` (409) | The preview, the policy or a source changed after the review. | Review the preview again; nothing was written. |
| `proposer_revoked` (409) | The grant that proposed the action was revoked before the apply. | Ask for a new proposal from an active agent grant. |
| `proposal_declined` (409) | The proposal was declined. | Ask for a new proposal. |
| `invalid_policy` (409) | `qa-separate-from-dev` in `SETTINGS.md` is neither `true` nor `false`, or the front matter cannot be read. The board never reads a bad value as `false`. | Fix the setting. Lint reports `invalid-workflow-policy`. |
| `stale_policy` (409) | The policy changed after the preview. | Preview again. |
| `separation_required` (403) | `qa-separate-from-dev` is `true` and the approving grant produced, recovered or repaired the evidence it verifies. | Another grant with the role approves. The setting separates grants, not people: reissuing a grant defeats it. |
| `separation_unverifiable` (409) | With the setting on, the journal has no operation that produced the evidence row, or the row's digest differs: the evidence was written outside the board, or `.prism/state/` was deleted. | Record the evidence again through the board, or set `qa-separate-from-dev: false`. Use `prism board state reset`, never a manual delete. |
| `evidence_generation_conflict` (409) | Another operation already produced the same evidence of the same item and app in this generation. | Archive the earlier evidence first, then preview again. The error names the operation that produced it and its state; if that operation is still unresolved, recover or abandon it first (abandoning releases only evidence that its pages no longer hold). |
| `trusted_facts_required` (409) | A gated apply or recovery reached the service without the facts the live board resolved (the approver's roles, the design owner and the separation provenance). The board refuses to guess them. | Apply or recover through the running board (a browser session), not through a path that bypasses the service. |
| `human_action_unavailable` (403) | A direct human action other than `po-handoff`, `design-start`, `dev-start` or `operation-repair` was requested. | An agent proposes the action with `preview_skill`; a human approves it. |
| `action_unavailable` (409) | The action is registered but this Prism version does not provide it. `discover` lists it with `available: false`. | Upgrade Prism, then `prism workflow upgrade`. |
| `unsupported_board_state` (409) | The board's state database was created by an earlier Prism version and has no role support. | Run `prism board state reset` (it writes an audit export first), issue new grants and start the board again. |
| `unresolved_operations` (409) | `prism board state reset` was refused: an operation is neither applied nor abandoned, or a board service holds the workspace. | Recover or abandon the operation (see [stuck operations](#an-operation-is-stuck-in-conflict-and-blocks-other-writes)), stop the board, then reset. |
| `repair_invalid` (409) | `operation-repair` was refused: the operation is not abandoned, is already repaired, has a file that matches neither its before nor its after state, or the repaired pages would not lint clean. | Inspect the operation with `operation`. A pending or conflicting operation is recovered or abandoned first. For an abandoned one, a human who holds the original action's roles previews the repair (the **Repair** control in the Operations dialog, or `operation-repair`) and approves it from **Proposals**. A file that matches neither state is restored to the before-state or after-state its receipt records, then the repair is previewed again. |

A proposal in the list that is marked **stale** was made before a source changed. Review it again or decline it; the agent then makes a new proposal.

## Previews, applies and interrupted operations

### An apply is rejected as stale

**Symptom.** `apply` fails with status 409 and one of `stale_preview`, `stale_move`, `stale_write`, `stale_status_row`, `stale_index_entry` or `stale_read_revision`. In the board, a preview that was open when its feature changed says that the feature source changed and disables confirmation.

**Cause.** A file that the preview depended on changed after the preview was made: someone edited the feature page, another operation applied, or new relevant context appeared (a bug page or a release record created in between counts, because a QA pass, a release and a bug update depend on them). A source the skill must read can also appear after the preview, for example a design page created for the feature: `stale_preview` then says "a source this skill must read changed or appeared after the preview; preview again" and `details.paths` names it. Prism refuses to apply a preview whose basis has moved, so a confirmation never covers changes nobody reviewed.

**Fix.** Nothing was written. In the board, choose **Preview again** to build a new preview from the current files; through MCP, read the current files again and create a new preview. Then review and confirm it. Unrelated `status-board.md` rows, `index.md` lines and `log.md` additions do not make a preview stale. If an operation was submitted and its outcome is unclear, retrieve its receipt with `operation` before retrying, as described under [Interrupted operations](shared-board.md#interrupted-operations).

### A preview is rejected for a digest

**Symptom.** `preview_skill` fails with status 409 and `missing_read_revisions`, `read_digest_mismatch` or `stale_read_revision`, naming a file under `knowledge/`.

**Cause.** Every source a skill depends on needs the digest of the file as it was read. The board records the digest of each file `read_workspace` returned to a participant and uses it when the proposal leaves `read_revisions` out. `missing_read_revisions` means a required source was never read by this participant (another participant's reads are never used), or the service restarted and cleared the record; `details.paths` lists the sources. `read_digest_mismatch` means a digest sent in `read_revisions` is not one the board returned for that file: a character was mistyped, or the digest was copied from the wrong file or invented. The file did not necessarily change. `stale_read_revision` means the board returned that digest earlier and the file has changed since, or it was created or removed.

**Fix.** After `missing_read_revisions`, read the listed paths with `read_workspace` and send the preview again without `read_revisions`. The error names the file's current digest. After `read_digest_mismatch`, leave `read_revisions` out, or copy the digest from `read_workspace` exactly, and send the preview again. After `stale_read_revision`, read the file again, review what changed, update the proposal if needed and send a new preview.

### An agent stopped after the board rejected a proposal

**Symptom.** The agent reports a rejection such as `clarify_scope_exceeded` and does not retry, or it reports the same rejection three times.

**Cause.** An agent may retry a rejected proposal only with the fix the error names, at most 2 more times, and never with a wider change. When the error names no fix, needs your decision, or the third preview is rejected, it stops and reports the error code and message.

**Fix.** Read the error and decide: tell the agent what to change, or correct the source it names. Ask it to try again; the count starts anew with your instruction. The agent does not write the files directly. [Agent hosts](agent-hosts.md) describes how Claude Code and Codex behave after a rejection.

### An operation is stuck in conflict and blocks other writes

**Symptom.** An `apply` fails with status 409 and `unresolved_operation_overlap`: "Operation `<id>` has unresolved writes that overlap this operation." `recover` on that operation keeps returning `state: conflict` with `recovery_source_changed`, `recovery_dependencies_unavailable`, `recovery_conflict` or `recovery_move_conflict` (for example "Both the recorded intake source and destination are missing"). In the board, the operation stays in the pending operations list. `prism workflow upgrade` also stops while it is listed.

**Cause.** An operation was interrupted or ended in conflict, and a file it depends on was then edited by hand, or its intake folder was renamed or deleted. The board does not guess: it keeps the recorded writes and refuses every new write that overlaps them. A `po-intake` operation lists every existing feature page as a source, so one stuck intake operation can block every feature write.

**Fix.** A writable human decides, in the board's operation review (the **Operations** button in the board header) or with `recover`:

1. Inspect the operation and acknowledge the review. If a page was edited by hand, **Recover recorded operation** now checks the remaining writes against the current files and completes the operation when they still pass the current rules. An agent's own `recover` still stops at the changed source; the human's reviewed recovery accepts the sources as they were when the review was inspected and keeps checking them: a source edited after the review, or a dependency that appeared after it (a new design page of the feature, for example), stops the recovery with `recovery_source_changed` or `stale_recovery_review` until the operation is inspected again. When the files an operation depends on cannot be determined at all (for example two feature pages share one ID), a write, a retry or a recovery stops with `recovery_dependencies_unavailable` and writes nothing; `prism wiki lint` reports the duplicate, and the operation continues once it is fixed.
2. If recovery still fails because the folder move or a written file can no longer match the record, choose **Abandon operation** (over HTTP or MCP, `recover` with `abandon: true`, the fresh `review_revision` and `semantic_review_acknowledged: true`). The operation becomes `abandoned`: nothing already written is undone, the receipt lists which writes and folder moves were applied and which were not, and the operation stops blocking other writes. Agents cannot abandon (`abandon_requires_human`), and an operation that can still be recovered is refused with `abandon_not_needed`.
3. Finish by hand what the receipt lists as not applied, or ask for a new preview.

## Lifecycle codes by stage

The codes below are the checks the board runs on a lifecycle proposal. Each rejection writes nothing. The agent may correct what the message names and preview again, at most 2 more times; a rule that needs your decision is yours.

| Code (status) | Cause | Fix |
| --- | --- | --- |
| `ambiguous_lifecycle_section` (409) | A feature proposal repeats a lifecycle heading or indents it, making the evidence sections ambiguous. | Keep exactly one `## Delivery evidence`, `## QA verification`, `## Release`, `## Evidence history` and `## API surface` heading, each in column zero, then preview again. |
| `lifecycle_evidence_changed` (409) | An intake proposal creates a feature with evidence rows, or a question skill changes a delivery, QA, release or Evidence history section. | Create intake features with empty evidence tables. For a question skill, restore the evidence sections exactly as `read_workspace` returned them; use the lifecycle action to record or archive evidence. |

### Intake and specification

| Code (status) | Cause | Fix |
| --- | --- | --- |
| `invalid_intake_feature` (409) | `po-intake` or `ingest` creates a feature in a status other than `raw` + `po`. | Create it `raw` + `po`; `po-specify` completes it. |
| `required_section_missing` (409) | `po-specify` leaves Design, Related features, API surface or Board review summary empty, or a feature is missing the four evidence sections. The message names them. | Write one supported line under each, or `Not started.`, `None identified.` or `Not reviewed yet.`; write `None.` under API surface unless an API change is stated. Add the evidence sections (Delivery evidence, QA verification, Release, Evidence history) as empty headings. |
| `evidence_sections_not_empty` (409) | A feature being specified already holds evidence rows or history. | Leave the evidence sections empty until the work they record happens. |
| `criterion_id_required`, `incomplete_specification` (409) | The feature has no acceptance criterion, or a required section is empty. | Write criteria as `- [ ] **Decided:** AC-1 [app] text`. |
| `duplicate_criterion_id`, `criterion_id_reused` (409) | An ID appears twice, or a new criterion takes an ID at or below the high-water mark of a removed criterion. | Give each criterion its own ID; a new one takes `criteria-high-water` plus 1. |
| `criteria_high_water_invalid`, `criteria_high_water_decreased` (409) | `criteria-high-water` is missing, is not the highest number ever assigned, or drops. | Set it to the highest criterion number, and raise it in the same write that adds a criterion. |
| `invalid_applies_to` (409) | A criterion applies to an app outside the feature's `apps`. | List only the feature's apps, or `[integration: app, app]` for two or more. |
| `app_without_criteria` (409) | An app in scope is named by no criterion. | Add a criterion that verifies the app's part, or remove the app from the scope. |
| `design_owner_mismatch` (409) | The destination owner of `po-handoff`, `design-start` or a scope edit is not the design owner of the scope (`designer` when an active app has a UI or an unknown one, otherwise `tech-lead`). | Set `owner` to the design owner the message names. |
| `advisory_skip_reason_required`, `invalid_advisory_skip`, `advisory_skip_scope` (400, 409) | A proposed advisory skip has no reason, is not on a pending `po-handoff` review, or changes something else. | Give a nonblank reason for the pending-to-skipped decision, or run `board-review`. |
| `intake_*`, `processed_source_immutable`, `source_link_missing`, `conflict_report_invalid`, `quarantine_write_scope` (409) | An intake proposal breaks a rule of dated, immutable sources. | See [an intake proposal is rejected](#an-intake-proposal-is-rejected-for-a-source-link) and [for its folder name](#an-intake-proposal-is-rejected-for-its-folder-name-or-a-processed-item). |

#### A new feature is raw and po-handoff does not accept it

**Symptom.** `po-handoff` reports that the feature is not `specified`, or `po-intake` fails with `invalid_intake_feature` (409).

**Cause.** `po-intake` creates every new feature as `raw` + `po`, and a proposal that sets another status is rejected. `po-handoff` accepts only `specified` + `po`. `po-specify` completes a raw feature and moves it to `specified`; it fails with `required_section_missing` when Design, Related features, API surface or Board review summary is empty, or when the evidence sections (Delivery evidence, QA verification, Release, Evidence history) are missing.

**Fix.** Run `po-specify` on the feature. Under each section it names, write one line of supported content or an explicit statement such as `Not started.`, `None identified.` or `Not reviewed yet.`, and `None.` under API surface (any other API surface text needs an API contract page before `dev-start`). Add the four evidence sections as empty headings.

#### An intake proposal is rejected for a source link

**Symptom.** `preview_skill` for `po-intake` fails with `intake_source_not_processed` or `source_link_missing` (409). The `details` name the page `path`, the `source` entry and, for `intake_source_not_processed`, the `expected` path.

**Cause.** The page lists a `sources` entry that would not resolve after the proposal applies. A folder under `knowledge/intake/pending/` moves to `knowledge/intake/processed/<folder>` when intake applies, so a link to the pending path would point at a folder that no longer exists, and the next agent could not read its source. A `source_link_missing` entry names a path that is not on disk, is not written by the proposal and is not in the processed folder the proposal's move creates. Nothing was written.

**Fix.** List the processed path, such as `knowledge/intake/processed/<folder>/brief.md`, or another path that exists, then preview again.

#### An intake proposal is rejected for its folder name or a processed item

**Symptom.** `preview_skill` for `po-intake` or `design-intake` fails with `intake_name_invalid` or `processed_source_immutable` (409). The `details` name the `path` and, for `processed_source_immutable`, the existing `item`.

**Cause.** The folder an intake proposal moves must be named `YYYY-MM-DD-slug`: the day the source was captured, then lowercase words joined by hyphens, with a real calendar date, for example `2026-10-06-client-call`. A processed intake item is immutable once processed, so a proposal that writes a file into an existing `knowledge/intake/processed/<folder>/`, or moves a pending folder onto it, is rejected.

**Fix.** Rename the pending folder to the dated form, then preview again. Put new or corrected material in a new dated folder under `knowledge/intake/pending/` and process that folder; never edit a processed item.

#### A quarantine proposal is rejected

**Symptom.** `preview_skill` for `po-intake` or `design-intake`, moving a folder to `knowledge/intake/quarantined/`, fails with `conflict_report_invalid` or `quarantine_write_scope` (409). The `details` of `conflict_report_invalid` list the `problems`.

**Cause.** A quarantine holds the incoming source and writes one file, `CONFLICT.md`, and changes no wiki page. The file needs front matter `status: open`, an `## Existing claim` and an `## Incoming claim` section, each with a `**Claim:**` item, a `**Scope:**` item and an `**Evidence:**` item that links the page or the file. A `resolved` status, a missing section or field, an evidence item without a link, or any other written file is rejected.

**Fix.** Write the `CONFLICT.md` in the format that `SCHEMA.md` defines (Conflict quarantine) and propose only that file with the move. The existing page stays untouched until a human decides.

### Design and the API contract

| Code (status) | Cause | Fix |
| --- | --- | --- |
| `design_tracks_missing`, `design_tracks_invalid` (409) | From the first design action on, the feature needs `design-tracks` (`ui`, `technical`) and `design-reaffirm`; a value is outside `pending`, `done`, `not-applicable`. | `design-start` writes `design-tracks` with the right initial values; copy them from the message. |
| `track_scope` (409) | A track action changes keys or pages of the other track, `design-start` writes tracks other than the initial ones, or `reopen-dev` changes the tracks. | Each action writes only its own track's keys and pages. |
| `track_reset_required` (409) | A page of a settled track changed, or the scope changed in design, without setting the affected track back to `pending` (and the other settled track into `design-reaffirm`). | Write the resets the message spells out. `design-clarify` and `design-intake` do this when they change such a page. |
| `design_track_not_open` (409) | `design-ui-done` or `tech-design-done` ran on a track that is `done` or `not-applicable` and not waiting for reaffirmation. | Change its pages with `design-clarify` (which sets it back to `pending`), or send the feature back with `dev-return-design`. |
| `track_page_locked` (409) | A design, technical design or API contract page changed from `ready-for-dev` on. | Send the feature back with `dev-return-design` (or `qa-return-design`) first. |
| `design_scope_mismatch`, `technical_design_scope_mismatch` (409) | A design or technical design page lists an app the feature does not have. | List only the feature's apps. |
| `invalid_technical_design`, `technical_design_path_mismatch`, `technical_design_feature_mismatch` (409) | The technical design page lacks `feature-id`, `title` or `apps`, is not named `F-XXX-<slug>.md` for its feature, or links another feature. | Follow `technical-design/_FORMAT.md`; a feature has one technical design page. |
| `design_page_unavailable` (409) | A clarify skill proposes a design or technical design page that does not exist or is not linked to the feature. | Create the page with `design-intake` or `tech-design-done`. |
| `api_contract_required` (409) | The API surface declares API work and the proposal creates no contract. The message names the path and the four sections. | `tech-design-done` (or a `design-handoff` that settles the technical track) adds `api-contracts/F-XXX.md` with `status: agreed`, `version: 1`. |
| `api_contract_untraceable` (409) | The contract lists an endpoint or data model that the API surface does not support. `details` lists them. | Remove them, or have the PO state the endpoint in the API surface through `po-clarify` or `dev-clarify`. |
| `api_contract_initial_status` (409) | A new contract is not `agreed` at `version: 1`. | Create it `agreed`; the human confirming the preview is the agreement. |
| `api_contract_not_applicable`, `api_contract_exists` (409) | A contract for a feature with no declared API work, or a second contract for a feature that has one. | Leave the page out of the proposal. |
| `contract_revision_required` (409) | A contract body changed without `version` plus one, or a revision changes front matter other than `version` and `status`. | Revise it as a version bump with `status: agreed` while the feature is in design. |
| `shared_contract_in_use` (409) | Another feature that links the contract has an app between `ready-for-dev` and `ready-for-release`. | Return that feature first with `dev-return-design` or `qa-return-design`. |
| `requirements_incomplete`, `requirement_body_change`, `requirement_exists`, `requirement_initial_status` (409) | After `design-handoff` the feature lacks exactly one requirement page per app, or a page is handled wrongly: a `done` page changed, an existing page rewritten, a new page not `pending`. | Create the missing pages `pending`; change only body sections of `pending` or `in-progress` pages. |
| `revalidation_required` (409) | A return or a reopen does not write the `revalidation` and `app-revalidation` domains the action sets. | Write the domains the message lists, merged with those still pending. |

#### API work has no app that serves an API

**Symptom.** `prism wiki lint` reports `api-surface-without-api-app`, a `design-handoff`, `dev-start` or `dev-done` check with that code is blocked, or the board rejects a `design-handoff`, `dev-start` or `dev-done` proposal with `api_surface_without_api_app` (409).

**Cause.** The feature's `## API surface` declares API work, but no active app in its `apps` has the `serves-api` capability. A retired app does not count, and `unknown` counts as serving an API.

**Fix.** Add an app that serves an API to the feature's `apps` (and its app requirement page), or change the API surface through `po-clarify` or `dev-clarify` if the feature has no API work.

### Implementation and delivery evidence

| Code (status) | Cause | Fix |
| --- | --- | --- |
| `delivery_evidence_required` (409) | `dev-done` adds no Delivery evidence row for an app. | Ask the developer for the artifact, contract, implementation and test references of each delivered app and add the rows `App \| Artifact \| Contract \| Implementation \| Tests \| Basis`. Do not invent a value. |
| `delivery_evidence_invalid` (409) | A new Delivery evidence row is malformed: a placeholder cell, a missing app or column, or a second row for one app. `details.problems` lists up to six. | Correct the cell as the message says: one row per app, with substantive references. |
| `artifact_reference_invalid` (409) | An Artifact or Version cell is not `version:<semver>`, `build:<name>#<number>`, `image:<name>@sha256:<64 hex>`, `package:<name>@<version>` or `commit:<7 to 40 hex>`. | Write the artifact in one of those forms. |
| `basis_invalid` (409) | A Basis cell is neither `checked` nor `attested`. | Write `checked` when you verified the references, `attested` when the approving human vouches for them. |
| `contract_binding_stale` (409) | The Contract cell cites another contract, a revised one or `none` for a feature that has a contract. | Cite `F-XXX@v<version>:c1:<digest>` exactly as the contract page reports. While an API contract that applies to the feature, its own or a shared one its requirements link, has no citation because its `version` or `feature-id` is not usable, every Delivery row is refused, `none` included (`details.unusable` lists the contract paths): correct the contract page first. `release-done` is refused the same way. A contract applies through its `feature-id` or file name, or a link from the feature page or from the requirement page of an app in the feature's scope; a file whose name starts with `_` is a template and never applies. |
| `app_stage_mismatch` (409) | An action names an app at a stage it does not accept: `dev-done` for an app that already has a row, QA for an app that is not delivered, `qa-fail` for an app in development. | Name only the apps in the stage the action works on. |
| `evidence_still_active`, `delivery_evidence_removed`, `evidence_unexpectedly_removed` (409) | A proposal removes a delivered row without a return, or keeps a row it also archives. | Delivered rows leave the table only when a return, a QA failure or a reopen archives them in Evidence history. |
| `requirement_not_completed`, `requirement_status_change`, `api_contract_not_implemented`, `api_status_change` (409) | `dev-done` does not mark the requirement of each delivered app `done`, changes another app's requirement, or does not mark the API contract `implemented` once every app has delivered. | Include those pages with the statuses the message names. |
| `app_retired`, `app_retired_in_scope` (409) | A new feature or an edit names a retired app, or a feature before `released` still lists one. | See [app-retired-in-scope](#a-feature-is-flagged-app-retired-in-scope). |
| `no_active_app_in_scope` (409) | Every app in the feature's scope is retired. | Return the feature through a design route and edit its scope. |
| `clarify_stage_unavailable` (409) | A clarify skill changes something the stage does not allow: App scope from `ready-for-dev` on, a criterion of a released app, a `released` feature. | Use a return route, then clarify; reopen a released feature with `feature-reopen`. |

#### A feature is flagged app-retired-in-scope

**Symptom.** `prism wiki lint` reports `app-retired-in-scope` for a feature before `released`, every lifecycle action on it is blocked with that code, or the board rejects a proposal with `app_retired_in_scope` or `app_retired` (409).

**Cause.** The feature's `apps` still lists an app that `prism app retire` has retired. Retiring an app never changes a feature's scope by itself, so the feature stays flagged until someone edits its scope. A feature that is `released` keeps a retired app as history and is not flagged. `app_retired` is the rejection of a new feature, or of an edit that adds a retired app to a scope.

**Fix.** Edit the feature's `apps` and its `## App scope` explicitly: drop the retired app, or point the work at another app and adjust the app requirement pages, and record the change in `log.md`. No command re-points features. Nothing was deleted by the retirement.

#### An action is blocked by an open question

**Symptom.** The preflight says `1 open action-relevant question remains: question 4.`

**Cause.** An open question blocks an action when its owner belongs to a stage up to the action: `design-start` waits for `po` questions, `design-ui-done` for `designer` questions, `tech-design-done` for `tech-lead` questions, `design-handoff` for `po`, `designer` and `tech-lead` questions, `dev-start` and `dev-done` also for `dev` questions, and `qa-pass` and `release-done` also for `qa` questions. `po-clarify`, `design-clarify` and `dev-clarify` resolve the questions of their owners; `qa` and `release` questions are resolved by the QA and release actions.

**Fix.** For a `dev` question use `dev-clarify`. It resolves the dev-owned questions of a feature that is not `released`, with the developer's answers. Each section it changes, in the feature or in an app requirement page, must contain an answer verbatim, written inside a complete sentence that uses the question's wording (a short answer such as `yes` is never the whole text). If the feature is `released`, reopen it with `feature-reopen` first.

### QA and bugs

| Code (status) | Cause | Fix |
| --- | --- | --- |
| `qa_evidence_required` (409) | `qa-verify` adds or replaces no row in `## QA verification`. | Add one row per app or integration you verified: `Row \| Criteria \| Method \| Artifact \| Environment \| Attempt \| Result \| Evidence \| Basis`. |
| `qa_row_invalid` (409) | A QA row is malformed, repeated for the same criterion, or has a result or method outside the allowed values. | Replace a row; do not repeat it. |
| `criterion_revision_stale`, `criterion_not_applicable` (409) | A row cites a criterion at a revision that changed, or a criterion that does not apply to the row. | Cite `AC-n@v1:<digest>` as `wiki-show` or the preview reports it, for an app in the criterion's `applies-to`. |
| `qa_artifact_mismatch`, `qa_attempt_mismatch` (409) | The row verified another artifact than the delivered one, or is not in the current attempt (`qa-<n>`). | Verify and cite the delivered artifact, in the current attempt. |
| `environment_unknown` (409) | The environment is not `local`, `ci` or an environment of the app's delivery target. | Use one of those, or declare the environment under `delivery-targets` in `SETTINGS.md`. |
| `qa_pass_apps_required` (409) | `qa-pass` adds no `pending` Release row naming the apps it passes. | Add `\| app \| — \| <delivered artifact> \| release-<n> \| pending \| — \| — \|` for each app. |
| `criterion_not_covered`, `integration_not_covered` (409) | An app has no passing QA row for a criterion at its current revision on the current artifact, or an integration criterion lacks a passing integration row. | Record the missing rows with `qa-verify` (the same proposal may carry them). |
| `qa_result_failed` (409) | The attempt holds a `fail` or `blocked` row for the app. | Fix and verify again in a new attempt, or `qa-fail` the app. |
| `open_bug_blocks_qa` (409) | A bug of the feature blocks the app: it is neither `verified`, `released` nor `closed`, and not deferred. | Verify or close the bug, defer a non-blocking one (the PO confirms), or fail the app citing the bug. |
| `qa_failure_unsupported` (409) | `qa-fail` names an app without a `fail` or `blocked` row in its attempt or a linked, unresolved bug. | Record the failure with `qa-verify`, or list the bug under `- Linked bugs:`. |
| `duplicate_app_row`, `undeclared_app_row` (409) | An app has two authoritative rows, or a row names an app outside the scope or the bug. | One row per app; name only the apps of the feature or bug. |
| `bug_creation_invalid`, `bug_id_taken`, `bug_feature_missing` (409) | A new bug page is not `open` + `dev` with empty Fix, Verification, Release and Evidence history sections, reuses an ID, or names a feature that does not exist. | Follow `bugs/_FORMAT.md`; take the next free bug number. |
| `invalid_bug`, `bug_apps_outside_feature`, `linked_bug_invalid` (409) | A bug page has unknown or missing front matter, lists apps its feature does not have, or a Linked bugs entry names no bug page. | Correct the page as the message says. |
| `bug_not_found`, `one_bug_required` (409) | `bug-update` names a bug page that does not exist, or changes more or fewer than one bug. | Create the bug with `ingest` or a QA action; change one bug per proposal. |
| `lifecycle_action_required`, `unsupported_source_pair`, `invalid_transition_target` (409) | The change to a bug or a feature matches no action of its row (`lifecycle_action_required`, which is also the answer of a feature skill proposed from another status), or a bug action or `release-done` runs on an item in another status (`unsupported_source_pair`, which also guards internal invariants). | Use one action of the `bug-update` table in `bugs/_FORMAT.md`; release a feature that is in development, in QA or `ready-for-release`. |
| `bug_frontmatter_scope`, `lifecycle_body_scope` (409) | An action changes front matter keys or sections its row does not allow. | Restore the other fields to their current values. |
| `bug_fix_evidence_required` (409) | A bug set to `fixed` lacks a Fix row for each of its apps. | Add `\| App \| Artifact \| Implementation \| Tests \| Basis \|` rows for every app. |
| `bug_verification_required`, `bug_verified_on_other_artifact` (409) | A verified bug lacks a passing Verification row per app on the verification artifact, or was verified on another artifact. | Run `bug-update ... reverify` on the current artifact, or reject it. |
| `feature_in_qa_cycle` (409) | A fix is recorded while an app of the bug's feature is in its QA cycle. | Run `qa-fail` on the app first, citing the bug, then fix. |
| `bug_close_reason_required`, `bug_not_deferrable`, `bug_deferred` (409) | A closure lacks a reason, a blocking bug is deferred, or a deferred bug starts work. | `close-reason: wont-fix: <reason>`, `duplicate` or `promoted`; triage a bug to `blocking: false` before deferring it; undefer it before work starts. |
| `duplicate_target_invalid` (409) | The canonical bug of a duplicate is missing, closed, deferred or does not cover the duplicate, or a proposal closes a canonical bug that has closed duplicates. | Preserve the duplicate links and resolve the canonical bug through fixing, verification and release. It cannot close while closed duplicates point to it; the error names them. |
| `bug_promotion_unreopened` (409) | `promoted-to` names a released feature, or one that cites neither the bug page in `sources` nor the bug under Linked bugs. | Create the feature with `ingest` citing the bug page, or reopen the feature first. |
| `bug_reopen_after_release`, `bug_release_via_release_done` (409) | A released bug is reopened, or `bug-update` sets a bug to `released`. | Open a new bug with `regression-of: BUG-XXX`; only `release-done` releases a bug. |
| `bug_fix_evidence_invalid`, `bug_verification_invalid` (409) | A Fix or Verification row of a bug has a malformed cell (lint reports them as `bug-page-invalid`). | Correct the cell: an artifact form, a result, a `checked` or `attested` basis. |

### Release

| Code (status) | Cause | Fix |
| --- | --- | --- |
| `release_record_required` (409) | A release proposal writes no, or more than one, record under `knowledge/wiki/releases/`. | Write exactly one new record. |
| `release_apps_required` (409) | The proposal carries neither the feature page whose Release rows it settles nor the bug pages it ships. | Add the pages. |
| `release_sequence_invalid`, `release_id_taken` (409) | The record number is not one more than the highest on disk, or already exists. The board allocates the number when the release applies. | Take the next free number the message names. |
| `release_record_invalid`, `release_record_mismatch`, `release_contract_snapshot_invalid` (409) | The record's front matter, Delivery rows, Rollback section or contract snapshot do not follow `releases/_FORMAT.md`, or do not match the rows of the proposal. | Correct the record as the message says; a rollback record's `## Rollback` says what was rolled back and why. |
| `release_row_invalid` (409) | A Release row is malformed, an app has duplicate authoritative rows, a retained row disagrees with its record, or a release drops another app's row. | Write one authoritative row per bug app, preserve every unnamed app's row, and replace a pending or failed feature row only with a validated row for that same app. Use `App \| Target \| Version \| Attempt \| Outcome \| Record \| Basis`. |
| `release_target_mismatch`, `delivery_target_missing` (409) | The row's Target is not the app's delivery target, or the app has none. | Declare it under `delivery-targets` in `SETTINGS.md` (required for an app of stack `other`). |
| `release_version_not_verified` (409) | The Version is not the artifact QA verified (for a bug, the verification artifact). | Release the verified artifact. |
| `release_attempt_mismatch` (409) | The attempt is not one more than the records that delivered the item for the app. | Use `release-<n>` as the message says. |
| `release_artifact_conflict` (409) | Rows for one app and target in a record differ in version or outcome. | Release items that share a deployment together, or separately. |
| `qa_evidence_stale` (409) | QA no longer covers a released app: a criterion, an artifact or an attempt changed. | Verify the app again with `qa-verify` and `qa-pass`, or return it. |
| `open_bug_blocks_release` (409) | A bug blocks the app. | Verify or close the bug (a non-blocking bug can be deferred by the PO), or return the app with `qa-fail`. |
| `verified_bug_not_included` (409) | A verified bug of the feature and app is not in the release. | Add the bug with its own Release row. |
| `bug_release_requires_feature` (409) | A bug linked to a feature ships before its feature app is released. | Add the feature with the app's Release row to the proposal, or release the bug after the feature app. |
| `dependency_not_released` (409) | The feature or app depends on one that is not `released` and not in the same release. | Release the dependency first or together. |
| `rollback_target_invalid` (409) | `rollback-of` names no record, a rollback, or a delivery that is not the current one of the app and target. | Roll back the current delivery the message names. |
| `redeploy_version_mismatch` (409) | A redeploy lists another version or other items than the current delivery. | Redeploy the version and items of the current delivery. |
| `record_date_invalid` (409) | The record's `date` is not the preview day. | Write the date the message names. |
| `bug_frontmatter_scope` (409) | A shipped bug page changes more than `status`, `owner` and its Release rows. | Restore the other fields. |

### Returns, reopening and scope

| Code (status) | Cause | Fix |
| --- | --- | --- |
| `partial_release_requires_new_feature` (409) | A return or reopen to specification or design on a feature with a released app. | Put a changed requirement or contract in a new feature, and an implementation defect in a bug. |
| `app_stage_mismatch` (409) | A return names an app at the wrong stage: `dev-return-*` once an app is in QA (use `qa-return-*`), or `qa-fail` for a shipped app. | Choose the route that matches the stage. |
| `history_entry_required`, `impact_review_required` (409) | The write does not append exactly one Evidence history entry headed `### <preview day> - <action>` with a substantive `- Reason:`, or omits a bullet. | Add the entry in the format of `features/_FORMAT.md`. |
| `history_not_append_only` (409) | Earlier Evidence history entries changed. | Keep all earlier entries and append one. |
| `evidence_not_archived` (409) | A prescribed archive occurrence is missing, duplicated or not copied verbatim under `- Archived evidence:`, prefixed with its section name. | Archive each prescribed occurrence exactly once and preserve every other active row. |
| `evidence_unexpectedly_added` (409) | An archive or scope action adds, replaces or duplicates an active evidence row. | Keep exactly the original active rows minus the action's prescribed archive. Record new evidence through delivery, verification or release. |
| `history_participants_mismatch`, `reopen_app_scope` (409) | The entry's participants or affected apps differ from what the action removes. | List the apps the action affects; a whole-feature return lists every app and no participants. |
| `delivery_evidence_not_reaffirmed` (409) | `Reaffirmed evidence` does not quote exactly the rows that stay active. | Quote the kept rows verbatim, or write `none` for an action that archives everything. |
| `reopen_invalidation_mismatch` (409) | The entry's `Requirement/API invalidations` or the status of a lowered page does not match the write. | Write `<page>: <old status> -> <new status>` for each page. |
| `revalidation_scope` (409) | `qa-pass`, `release-done` or `reopen-dev` clears or sets domains it does not own. | Clear only the domain the action owns (`qa` for `qa-pass`, `release` for `release-done`). |
| `reopen_route_required`, `multiple_lifecycle_actions` (409) | `feature-reopen` names no route, or one preview performs two transitions. | Pick `specified`, `in-design` or `in-dev`; one action per preview. |
| `scope_stage_unavailable` (409) | From `ready-for-dev` on, a scope edit adds an app, or removes one that already has evidence rows. | Return the feature with `dev-return-design` or `qa-return-design` to add an app; retire the app first to drop one with evidence. |
| `scope_empty`, `scope_replacement_requires_return` (409) | A scope edit, at any stage, leaves the feature with no app (`scope_empty`), or from `ready-for-dev` on replaces an all-retired scope. | Remove the work through a bug or a new feature; return the feature through a design route. |
| `scope_criteria_invalid`, `scope_criteria_mismatch` (409) | The criteria are invalid, or do not equal the three edits a scope edit derives: drop the app from each `applies-to`, drop a criterion left with no app, make a one-app integration criterion per-app. | Fix the criteria first, then write exactly those edits. |

### Operations: incidents and the status board

| Code (status) | Cause | Fix |
| --- | --- | --- |
| `invalid_incident` (409) | An incident page has unknown or missing front matter, an `id` that does not match its file name `INC-<n>-<slug>.md`, or sections other than the six of `incidents/_FORMAT.md` in order. | Follow the format. |
| `incident_id_taken` (409) | A new incident reuses an ID. | Take the next free incident number. |
| `incident_release_unknown` (409) | `releases` names a record that does not exist in `releases/`. | List existing `REL-XXX` records. |
| `incident_frontmatter_scope`, `incident_body_scope` (409) | An update changes `title`, `date`, `severity`, `apps` or `## Impact`, or removes entries from `releases` or `follow-ups`. | An incident is a record: it steps `status`, appends Timeline lines and adds entries. |
| `incident_timeline_not_append_only` (409) | An earlier Timeline line changed. | Add lines at the end only. |
| `incident_cause_uncited` (409) | A new Cause adds no Timeline line that links the intake item it came from. | Add `- YYYY-MM-DD: Cause recorded ([intake item](../../intake/processed/<folder>/MANIFEST.md))`. |
| `incident_resolved_final` (409) | A `resolved` incident is changed. | A recurrence is a new incident. |
| `stale_status_row`, `stale_index_entry`, `duplicate_status_row`, `invalid_status_board` (409) | A status board row (feature, bug or app) or an index line changed after the preview, a row or line is duplicated, or `status-board.md` lacks its feature table. | Preview again; remove duplicates; restore the feature table header `\| ID \| Feature \| Status \| Owner \| Board Review \| Design tracks \| App stages \| Open bugs \|`. |

## Lint reports a lifecycle finding

**Symptom.** `prism wiki lint` reports one of the lifecycle codes. [The wiki workflow](wiki-workflow.md#lifecycle-lint-codes) says what each means.

**Fix.** By group:

| Code | Fix |
| --- | --- |
| `invalid-feature-status`, `invalid-feature-owner`, `invalid-status-owner-pairing`, `unsupported-feature-field`, `unsupported-design-field`, `invalid-feature-id` | Use a status and owner from [the lifecycle table](prism-model.md#the-lifecycle); remove fields the page kind does not carry. Do not edit status by hand on a connected workspace: use the action. A feature ID is `F-` and a number of at most 18 digits; every ID of the wiki (feature, bug, incident, release, criterion, attempt) takes the digits 0 to 9 only, so an ID with other Unicode digits is invalid. |
| `feature-status-not-minimum`, `app-row-missing`, `app-row-ahead-of-status`, `app-row-out-of-order` | The status must equal the lowest stage of the active apps, and each stage needs its rows (Delivery evidence, then QA verification, then Release). Record the missing rows with the action of the stage, or return the feature. |
| `undeclared-app-row`, `duplicate-app-row`, `invalid-evidence-row`, `no-active-app-in-scope`, `pending-revalidation` | Name only apps of the scope, keep one authoritative row per app, correct the cell the message names; return a feature whose apps are all retired; clear the revalidation domains with fresh evidence. |
| `app-without-criteria`, `duplicate-criterion-id`, `invalid-applies-to`, `criterion-high-water-invalid` | Fix the criteria as in the table above (`app_without_criteria`, `duplicate_criterion_id`, `invalid_applies_to`, `criteria_high_water_invalid`). `criteria-high-water` is an integer from 0 to 999999999999999999. Front matter or a manifest that holds a larger integer in any field, however it is written (hexadecimal and octal included), is malformed: lint reports "front matter holds an integer outside the supported range" and a board preview refuses it as `invalid_frontmatter`. |
| `stale-qa-evidence`, `stale-delivery-evidence` | A criterion, artifact, attempt or contract changed after the row. Verify again with `qa-verify`, or record delivery again after a return. An applicable API contract without a citation (its `version` or `feature-id` is not usable) makes every Delivery row of the feature stale, `none` included, until the contract page is corrected. |
| `design-tracks-missing`, `design-tracks-invalid`, `design-track-pending`, `design-coverage-incomplete`, `ui-exemption-reason-required`, `technical-track-required` | Settle the tracks with `design-ui-done` and `tech-design-done`; a design page covers every app with a UI; an exemption carries a reason; a technical track is `not-applicable` only without API work. |
| `missing-technical-design`, `technical-design-feature-mismatch`, `test-strategy-incomplete` | One technical design page per feature, named for it, whose Test strategy names every criterion ID. |
| `api-contract-required`, `api-contract-not-ready`, `delivered-api-contract`, `invalid-api-contract-version`, `invalid-api-contract-feature-id` | Create the contract with `tech-design-done`; agree a `draft` before development; `dev-done` marks it `implemented`. A contract `version` is an integer from 1 to 999999999999999999, however it is written; a contract with another version is invalid, has no citation, and no Delivery row can cite it. A contract `feature-id` is `F-` and at most 18 digits; a contract with a longer one is invalid in the same way. While such a contract applies to a feature, its own or a shared one its requirements link, the Delivery rows of that feature are blocked (`contract_binding_stale`, `contract-binding-stale`, `stale-delivery-evidence`), `none` included, until the contract page is corrected. |
| `page-in-sub-folder` | A page of `api-contracts/` or `app-requirements/` is in a sub-folder. The wiki reads one folder level, so no feature, link or lifecycle action finds the page (a contract there is not a contract of its feature, and a requirement there links nothing); move the page directly into the folder. The error does not gate an action. |
| `unused-api-contract` | The feature's one `## API surface` section declares no API work any more, so its `draft` contract blocks nothing; delete the page. A page with two `## API surface` sections establishes no absence of API work: `ambiguous-lifecycle-section` gates and the contract stays an obligation. |
| `missing-app-requirements`, `pending-board-review`, `unresolved-open-questions`, `done-app-requirement`, `done-advisory-actions` | Create the requirement pages with `design-handoff`; run `board-review` or skip it with a reason; resolve open questions with the clarify skills; a released feature has `done` requirements and no unchecked advisory actions. |
| `bug-page-invalid`, `invalid-bug-status-owner`, `bug-close-reason-required`, `duplicate-target-invalid`, `promoted-bug-unreopened`, `bug-feature-missing` | Correct the bug page as `bugs/_FORMAT.md` says; change a bug with `bug-update`, not by hand. A bug ID is `BUG-` and a number of at most 18 digits, written with the digits 0 to 9; a longer number, or one with other Unicode digits, is an invalid ID. |
| `open-bug-blocks-qa` | Return the app with `qa-fail` citing the bug, or verify, close or (for a non-blocking bug) defer the bug. |
| `release-record-invalid`, `release-row-record-mismatch` | A record is never rewritten: a Release row must agree with its record on target, version and outcome and link an existing record. Correct the row, or record a new release or rollback. A record number has at most 18 digits, written with the digits 0 to 9; a record with a longer number, or one with other Unicode digits, is invalid, takes no part in the release order and cannot be written. |
| `cross-app-dependency`, `dependency-cycle` | Release the dependency first, or together; break the cycle in the `Dependencies` sections. |
| `incident-record-invalid`, `incident-follow-up-missing` | Follow `incidents/_FORMAT.md`; a follow-up names an existing bug or feature page. An incident number has at most 18 digits, written with the digits 0 to 9. |
| `invalid-workflow-policy`, `invalid-delivery-target`, `invalid-app-runbook` | Fix `SETTINGS.md` (`qa-separate-from-dev` is `true` or `false`; `delivery-targets` names known apps and one of `deployment`, `store`, `artifact`, `other`); an app in this repository keeps its runbook at `<path>/docs/runbook.md` and declares none; an external app's `runbook` is an https link. |
| `status-board-frontmatter-drift`, `feature-missing-from-status-board`, `status-board-missing-feature` | The connected board writes the rows; fix a hand-edited row or add the missing one with the same cells as the pages. |
| `unknown-app-id`, `app-retired-in-scope`, `api-surface-without-api-app` | Name only apps the workspace declares and has not retired; an API surface needs an active app that serves an API. |

## Other lint findings

### Lint reports an evidence label, a decision, a source or a conflict

**Symptom.** `prism wiki lint` reports one of `unlinked-claim`, `unknown-evidence-label`, `supersession-mismatch`, `superseded-decision-cited`, `processed-source-without-manifest`, `unresolved-conflict`, `malformed-conflict`, `missing-index-entry`, `orphan-index-entry` or `duplicate-index-entry`. `supersession-mismatch` and `malformed-conflict` are errors; the others are warnings.

**Cause.** Lint checks the form of the records and never judges meaning:

| Code | Cause |
| --- | --- |
| `unlinked-claim` | A `**Decided:**` or `**Observed:**` item has no markdown link or URL to its evidence. |
| `unknown-evidence-label` | A bold run-in label such as `**Note:**` at the start of a list item or paragraph is not `Decided`, `Observed`, `Proposed`, `Assumed` or `Unknown`. |
| `supersession-mismatch` | Two ADRs disagree: the new ADR's `supersedes: ADR-NNN` needs the old ADR to carry `status: superseded` and `superseded-by` naming the new one, and the reverse. |
| `superseded-decision-cited` | A current-state page links an ADR that a newer ADR supersedes. |
| `processed-source-without-manifest` | A `knowledge/intake/processed/<folder>/` has no `MANIFEST.md`. |
| `unresolved-conflict` | A quarantined `CONFLICT.md` still has `status: open`. A non-empty quarantine is not a gate. |
| `malformed-conflict` | A quarantined item has no `CONFLICT.md`, or the file lacks a valid status, a claim section or a linked `**Evidence:**`. |
| `missing-index-entry` | A wiki page has no line in `index.md`. The message names the page. |
| `orphan-index-entry` | An `index.md` line links a wiki path that is not a page of the wiki, or a "Project docs" line links a `docs/` page that does not exist. |
| `duplicate-index-entry` | A page, or a project doc, has more than one line in `index.md`. |

**Fix.** Link the evidence (a processed intake item, a record or a URL) or change the label. For a supersession, set both links (`supersedes` on the new ADR; `status: superseded` and `superseded-by` on the old one) and update the pages that cite the old ADR to link the new one. Add the manifest in a new, separate operation; processed items are not edited. Add the missing `- [Label](path.md): one sentence in the present tense` line under the heading of the page's kind, and remove an orphan or duplicate line; the connected board writes these lines itself for every page it writes. A workspace that adopts the workflow with its own `index.md` keeps that file; the installer adds only a line for each page it installs (`CONNECTED.md`, `status-board.md`, `direction.md`, `roadmap.md` and similar) and never changes or replaces a line you wrote, so adoption leaves no `missing-index-entry` warning for those pages. Pages you add yourself still need their line. Resolve a conflict by deciding which claim holds, making that edit to the page, setting `status: resolved` and adding a `## Resolution` section. Fix a malformed `CONFLICT.md` to the format in `SCHEMA.md`.

### Lint reports broken-link or broken-anchor

**Symptom.** `prism wiki lint` reports `broken-link` (error) or `broken-anchor` (warning) on a page, with the link and its line:

```text
- broken-link: Relative link `../design/missing.md` (line 12) does not resolve to an existing file or folder.
- broken-link: `sources` entry `knowledge/intake/pending/2026-10-06-brief` (line 5) does not exist in the workspace. It is in the pending intake queue, which moves when intake applies; list `knowledge/intake/processed/2026-10-06-brief` instead.
```

**Cause.** Every relative Markdown link and every `sources` entry must resolve to an existing file or folder. The target was moved, renamed or never created; a pending intake folder moved to `processed`; the link leaves the workspace; or a `repo:<repository-id>/<path>` link names a repository that `prism.workspace.yml` does not declare, a malformed path, or a path that is missing from the checkout in `prism.local.yml`. A link that is not a plain relative path is refused as text, before any file is looked at: `Relative link `%2F%2Fhost%2Fshare%2Fx.md` (line 4) is not a safe relative path: it is rooted or a network path` (UNC, rooted, drive-qualified, backslash and double-encoded paths, and a path through a symlink or junction, which lint does not follow). A `broken-anchor` means the target page has no heading that gives the anchor.

**Fix.** Correct the link or the `sources` entry to the real path (the processed intake path for a moved folder), or restore the target. Link a file of another repository as `repo:<repository-id>/<path>`, not as a path that leaves the workspace, and write every link with `/` as a relative path. A link that only an agent can fix goes through the page's own operation; lint never rewrites a page. Only a broken link to a page of the wiki blocks a lifecycle action. [`SCHEMA.md`](../template/knowledge/wiki/SCHEMA.md) defines the rules under "Links and sources".

### Lint reports stale-page or never-verified

**Symptom.** `prism wiki lint` reports `stale-page` (warning) or `never-verified` (information) for a current-state page:

```text
- stale-page: `knowledge/wiki/topics/pricing.md` was last verified 2026-09-01, 35 days ago; `wiki-stale-after-days` is 14. Check it against its sources and run `prism wiki verify knowledge/wiki/topics/pricing.md`.
- never-verified: `knowledge/wiki/roadmap.md` has no `verify` entry in log.md. Once someone has checked it against its sources, record that with `prism wiki verify knowledge/wiki/roadmap.md`.
```

**Cause.** Pages carry no date, so freshness comes from `log.md`: the latest `verify` entry that lists the page. `stale-page` means that entry is older than `wiki-stale-after-days` in `SETTINGS.md` (14 when the file or the key is absent or invalid); `never-verified` means no `verify` entry lists the page, which is the state of every new page. Records, the log, the index, the status board and generated files are exempt. Neither finding changes a status or blocks a lifecycle action.

**Fix.** Check the page against its sources. If it is still true, record that with `prism wiki verify <page>... [--evidence <link>] [--by <name>]`, or through the connected board with the `verify-pages` skill; it appends one entry to `log.md` and never edits the page. If the page is out of date, correct it through its own operation first. Raise `wiki-stale-after-days` in `SETTINGS.md` if the interval does not suit the project. `prism wiki verify` refuses a path outside `knowledge/wiki`, a page that does not exist and a page that is not a current-state page, and then writes nothing.

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

