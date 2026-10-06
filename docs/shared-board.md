# Shared local board

This is the usage contract for the shared board. [Current status](current-status.md) records what is verified, and the [core plan](prism-core-workflow-plan.md) states the scope and contracts. Prism runs on one computer: one service per workspace serves the browser board and an MCP endpoint. Remote hosting is not supported.

## Install the workflow

For an empty workspace or an existing repository, preview the files first:

```text
prism workflow install . --name "Document review" --app backend
prism workflow install . --name "Document review" --app backend --apply
```

`--app` registers a generated app in the manifest; repeat it for more. The IDs are `backend`, `web-user-app`, `web-admin-portal`, `mobile-android`, and `mobile-ios`. Without `--app`, a new workspace has no apps; register apps later with `prism app add` ([the workspace model](workspace-model.md) describes apps, repositories and `prism.local.yml`). `--knowledge-root` starts a workspace that holds the shared wiki for apps in other repositories instead: it cannot be combined with `--app`, and it records `workflow.purpose: knowledge-root` ([the workspace model](workspace-model.md#knowledge-root-over-several-repositories) has a worked example). A workflow-only workspace does not need corresponding application directories. Installation creates workflow assets, a manifest, ignore rules for the local state (`.prism/state/`) and for `prism.local.yml`, and a `.gitattributes` rule (`knowledge/** text eol=lf`) that keeps the Prism-owned `knowledge/` text on LF line endings; an existing `.gitattributes` keeps its content and receives the rule at the end. It does not generate an application. Existing source code, wiki content and custom agent instructions are preserved. Conflicting owned guidance stops installation and identifies the file for resolution.

The one Prism-owned file that can conflict is `knowledge/wiki/CONNECTED.md`. Line endings are ignored when a copy is compared with the packaged text: a copy that a Git checkout with `core.autocrlf=true` rewrote with CRLF still counts as unmodified and is left as it is, and Prism writes LF. When the copy differs, for example after you edited it, `prism workflow install` and `prism workflow upgrade` exit with code 3, write nothing and print:

```text
Conflict: knowledge/wiki/CONNECTED.md is present with different contents; preserve or reconcile it explicitly before installing the Prism-owned binding.
```

Copy your version somewhere outside `knowledge/wiki/`, delete the file, run the install again, and keep your own notes in your `AGENTS.md`, `CLAUDE.md` or other pages that Prism does not own. [Troubleshooting](troubleshooting.md#workflow-install-stops-on-a-modified-connectedmd) lists the steps.

A new workspace gets the same instruction layout as a generated one: `AGENTS.md` holds the
connected-workflow section and `CLAUDE.md` is only the `@AGENTS.md` import. Review the plan's
optional steps when existing `AGENTS.md` or `CLAUDE.md` files are preserved. Add the suggested
`knowledge/wiki/CONNECTED.md` pointer to your own `AGENTS.md`, and `@AGENTS.md` to your own
`CLAUDE.md`, if you want agents to discover the connection there; installation does not rewrite
those custom files. When it keeps your `knowledge/wiki/index.md`, it only adds a line for each
page it installs and leaves every existing line as it is.

Generated workspaces, including a fresh `prism new` result, use an explicit
upgrade preview to activate connected writes. Generation supplies the wiki and
agent guidance; this step adds the board identity and canonical workflow pin:

```text
prism workflow upgrade .
prism workflow upgrade . --apply
```

`--apply` shows the proposed changes and asks for confirmation. Automation must explicitly use `--apply --yes`. Reading or viewing an older workspace does not upgrade it. The manifest records a board UUID, workflow version, mode and canonical asset digest. An incompatible pin disables connected writes until an explicit upgrade.

Before upgrading an existing connected workspace, finish, recover or abandon its pending
operations and stop its board service. Upgrade uses the same workspace process
lock as the service and refuses to change the pin while an operation is incomplete.
The preview identifies `.prism/state/board.lock` when the upgrade needs to create
it; this does not initialize the board database. A changed workflow version or
asset digest invalidates existing grants, so issue new participant grants after
the upgrade. Fresh workflow installation and generated-workspace activation do
not create runtime state.

Use the existing agent-led `setup-project` skill to initialize product context after installing assets. Setup and advisory-board authoring use the direct-file workflow; connected skill discovery must state which operations can actually write through the service.

The manifest `prism.workspace.yml` carries the board identity. If you delete it and install again, the workspace gets a new board identity, so every earlier grant stops counting: calls with an old token fail with `grant_identity_changed`, and `prism doctor --workspace .` warns that grants were issued for an earlier workflow pin. Issue new grants with `prism board grant` and update each agent host's token, or restore the manifest from version control or a backup instead of reinstalling.

The app scope is part of the board identity too: each active app's ID, stack, repository and path. After `prism app add` changes it, a running board answers with `workspace_identity_changed` and keeps writes disabled until you stop it and start it again with `prism board serve`. Reissue grants with `prism board grant` for any participant the board still rejects. A workspace with no apps is served with writes enabled.

Application generation remains available through `prism new`. Its template trust, release selection and update/provenance rules are independent of workflow adoption. Without `--template`, an installed Prism renders the canonical template at the release tag that matches its version and stops with one message and exit code 3 while that tag is not published; pass `--template <path or URL>` instead ([details](troubleshooting.md#prism-new-stops-because-the-template-release-tag-is-missing)).

## Register participants and run the service

```text
prism board grant "Product owner" --kind human --write --path .
prism board grant "Coding agent" --kind agent --write --path .
prism board serve . --port 8765
```

Each grant prints its own token once. Keep it private. Enter the human token in the board's sign-in form; configure an agent's token in that host's environment. Tokens do not belong in URLs, repository files or prompts. Without `--write`, a grant is read-only. Participant names identify locally registered grants; they do not independently verify a person's identity or assign a workflow role.

Press Ctrl+C to stop the service. It stops promptly even while a browser is connected.

When the server starts, its first line is the board URL. The next lines give the MCP endpoint for agent hosts and the grant command to run if you have no token yet:

```text
Prism board: http://127.0.0.1:8765/
MCP endpoint: http://127.0.0.1:8765/mcp
Issue a participant grant (the token is printed once): prism board grant "NAME" --kind human|agent [--write] --path .
Local only. Press Ctrl+C to stop.
```

The lines are flushed as they are printed, so a pipe or a log file shows them while the service runs.

The `--path` in the hint is the folder being served. If the port is already in use, the command prints one line, `Cannot start the Prism board on port 8765: it is already in use. Choose another with --port.`, and exits with code 4 without creating any board state. `prism wiki graph --serve` exits with code 4 and one line in the same way.

### Check readiness with doctor

Run `prism doctor --workspace .` before the first `prism board serve`. Its "Shared board" section is read-only: it never creates board state, grants or files. Each line starts with `[ok]`, `[warn]`, `[fail]` or `[skip]`, and a line that needs action is followed by a `Fix:` line. Plain `prism doctor`, run inside a workflow or generated workspace folder, gives the next step "Run `prism doctor --workspace .` to check this workspace." instead of the generation hint.

| Check | Passes when | Otherwise |
| --- | --- | --- |
| Workspace is outside cloud-synced folders | No part of the path is a cloud-files placeholder. | `[fail]` with the cloud-sync guidance. |
| Workflow pin is compatible with this Prism installation | The manifest pin matches this installation, using the same check as `prism board status` and the server. | `[fail]` with the reason and a preview of `prism workflow upgrade`. A workspace with no workflow pin gets `[warn]` and a preview of `prism workflow install`, or of `prism workflow upgrade` for a generated project; the checks below do not run for it. |
| At least one active board grant exists | An unrevoked grant was issued for the current pin. | `[warn]` with the `prism board grant` command when there are no grants yet (`No grants yet.`), every grant is revoked (`No active grants (N revoked).`) or all of them predate the current pin. `[fail]` when the board state cannot be read safely. |
| Default board port 8765 is free | A loopback bind on the port succeeds and is released at once. | `[warn]` naming the busy port. This is expected while the board is running. |
| `.prism/state` is ignored by git | `git check-ignore` ignores the state directory. | `[fail]` with the `.gitignore` rule to add. `[skip]` when git is unavailable or the folder is not a git repository. |

Only `[fail]` lines change the exit code: doctor exits with code 3 and ends with a count of failures. Warnings and skips leave it at 0.

```text
Shared board
[ok] Workspace is outside cloud-synced folders
[ok] Workflow pin is compatible with this Prism installation
  Workflow version 1 matches this installation.
[warn] At least one active board grant exists
  No grants yet.
  Fix: Issue one with `prism board grant "NAME" --kind human|agent --write --path D:/work/editorial`.
[ok] Default board port 8765 is free
[fail] `.prism/state` is ignored by git
  Grants and the operation journal could be committed by mistake.
  Fix: Add `.prism/state/` to .gitignore.
```

The server binds to loopback. The browser uses an HttpOnly session cookie and same-origin request checks. MCP uses its participant Bearer token. Revoke access with the participant ID returned when the grant was created:

```text
prism board revoke PARTICIPANT_ID --path .
```

Connected workspaces require ordinary local files and directories. The service
rejects symbolic links, junctions and other reparse points in the workspace paths.

### Cloud-synced folders

On Windows, OneDrive and Dropbox Files On-Demand mark synced files and folders as reparse points. Windows Known Folder Move puts Documents and Desktop under OneDrive by default, so a workspace there is refused: `prism workflow install`, `prism workflow upgrade` and the `prism board` commands fail with a cloud-sync message, and connected HTTP and MCP calls return the `cloud_sync_path` error. Prism cannot guarantee atomic writes while a sync engine may rewrite or dehydrate the files. Move the workspace to a local folder that is not synced, then retry. `prism doctor --workspace PATH` reports "Workspace is outside cloud-synced folders" and fails with this guidance when the path or one of its ancestors is a cloud placeholder.

The `.prism/state/` journal holds grants, previews and operation receipts. It is local operational state, not the board's source of truth. Wiki files remain authoritative. Do not copy this state directory into another workspace or commit it.

## Connect an agent host

Use the host's standard Streamable HTTP MCP configuration with `http://127.0.0.1:8765/mcp`. Prism has one tool contract; it does not implement separate workflow connectors for each model or coding agent. A model can participate only through a host that supports the required MCP transport and authentication.

For Codex, a server entry can reference an environment variable for the token:

```toml
[mcp_servers.prism]
url = "http://127.0.0.1:8765/mcp"
bearer_token_env_var = "PRISM_BOARD_TOKEN"
```

These fields use Codex's [standard MCP configuration](https://learn.chatgpt.com/docs/extend/mcp?surface=cli).

For Claude Code, the equivalent MCP server entry is:

```json
{
  "mcpServers": {
    "prism": {
      "type": "http",
      "url": "http://127.0.0.1:8765/mcp",
      "headers": { "Authorization": "Bearer ${PRISM_BOARD_TOKEN}" }
    }
  }
}
```

The environment reference follows Claude Code's [MCP configuration rules](https://code.claude.com/docs/en/mcp#environment-variable-expansion-in-mcp-json). Give each host a separate Prism participant token. Host configuration support and verified runtime compatibility are separate evidence; record actual host versions and results when testing.

## Work together

Direct an agent in its CLI, for example: “Use Prism's PO intake skill to refine the pending document-review brief.” The agent discovers the board, retrieves its pinned skill and each reference it needs, reads current workspace data, and follows the skill's required conflict checks, semantic review and confirmation. It sends a bounded proposal to `preview_skill`, shows the exact changes for confirmation, and applies the returned preview with an operation ID. There is no second approval queue in the board.

`list_workspace` discovers approved wiki and intake paths in pages;
`read_workspace` returns their text and content digests, paged to the result limit. `query` reuses Prism's
existing feature, owner, app, blocker, search, lint and lifecycle preflight
facts. These read operations work with read-only participant grants.

Connected intake supports UTF-8 `.md`, `.txt`, `.yaml` and `.yml`
sources up to 512 KiB per file. Inventory results identify unsupported attachments
and oversized files. PDF/image extraction is deferred; an intake containing a
required unreadable source stops with a clear limitation instead of ignoring it.
Agents read every `required_workspace_reads` path returned by `get_skill`, plus
the operation's target, linked context and intake evidence, through the service.

The board directly supports human `po-handoff`, `design-start` and `dev-start`. Through MCP, `preview_transition` accepts only a human participant: an agent that calls it gets `participant_kind_required`. `list_skills` and `get_skill` report, for every skill, `participant_kinds` and `write_tools` (which tool each kind may use) and add a "Direct human action" limitation to these three. An agent that needs one of them prepares it with `preview_skill` and the human's confirmation in the host, or asks the human to complete it in the board. Dragging and the action controls enter the same preview. The human reviews the evidence and exact changes, supplies the required review acknowledgement and any permitted PO advisory skip reason, then confirms. A blocked mapped drop explains the blockers with confirmation disabled. Specification, design handoff, Done and reopening continue through the existing agent skills. A gesture alone never moves canonical state or manufactures evidence.

Direct human transitions preserve frontmatter values outside the action's scope,
but serialize the complete YAML frontmatter block. Formatting, quoting and YAML
comments may change. The preview calls this out and shows the exact before/after
text so the human can inspect that normalization before confirming.

For those agent-only actions, a connected board requests the service's current
preflight and offers **Copy MCP request** when its checks allow it. The request
identifies the board and canonical skill; paste it into an agent connected to that
board, where the skill's review and confirmation take place. Generated Codex or
Claude instruction folders are not required. Copying dispatches no agent and
writes no lifecycle state. A stale or unavailable connection disables copying;
static and legacy boards retain their existing tool-specific copy behavior.

Skill discovery exposes 26 complete canonical skills. Connected writes are
available for `po-intake`, `design-intake`, `ingest`, `ask`, `po-clarify`, `design-clarify`,
`dev-clarify`, `po-specify`, `po-handoff`, `design-start`, `design-handoff`,
`dev-start`, `dev-done`, `feature-reopen` and `verify-pages`. The three reopen routes are actions
of `feature-reopen`. `verify-pages` records that current-state pages were checked against their
sources and changes no page: its `preview_skill` call has an empty `changes` list and names each
verified page in `read_revisions` with the digest `read_workspace` returned for it, and the preview
writes one `verify` entry to `log.md` (`prism wiki verify` is the direct path). Applying it is refused
as stale when a verified page changed after the preview. Other skills provide guidance or read operations: always
inspect `write_supported` and `limitations`. An unavailable connected write stops
that attempt. When the board rejects a proposal, the agent may correct exactly what
the error names and preview again, at most 2 more times, without widening the
change; it then stops and reports the rejection
([Rejected proposals](#rejected-proposals)). A direct-file compatibility workflow
requires an explicit human choice and follows the original skill's complete review
and confirmation.

### The index, the status board and the log are service-managed

A proposal never supplies `knowledge/wiki/index.md`, `knowledge/wiki/status-board.md` or
`knowledge/wiki/log.md` (rejected with `managed_file`); the preview carries their exact before and
after text. `status-board.md` holds one row per feature, merged by feature ID. `index.md` is the
general index of the wiki, one line per page: the board adds or replaces the line of each wiki
page the operation writes, derived from the page's title and the first sentence of its summary
(a persona uses its `## Who they are` section, a business rule its `## Rule` and a decision its
`## Decision`; a superseded decision reads "ADR-NNN supersedes this decision."). Both merge by
key: a row or line that changed after the preview is a conflict (`stale_status_row`,
`stale_index_entry`), unrelated rows and lines are kept, applying twice changes nothing more,
and an interrupted operation rolls forward from the recorded rows and lines. The index changes with
every page the board writes, and a preview requires the participant's read of `index.md`, so an agent
reads it again before each preview. A workspace needs
both files, besides `SCHEMA.md` and `LIFECYCLE.md`, or the board stays read-only.

### Intake, dev answers and delivery evidence

- **`po-intake` writes `raw` features.** Every new feature is `raw` + `po`, with its
  Summary, User story, Acceptance criteria, Open questions and App scope. A
  proposal that creates a feature in another status is rejected with
  `invalid_intake_feature`. `po-specify` completes the page and moves it to
  `specified`: Design, Related features, API surface, Board review summary and
  Post-ship notes each get one line of supported content or an explicit statement
  such as `Not started.` (`None.` under API surface unless an API change is stated; any other
  API surface text needs an API contract page before `dev-start`, which `design-handoff` creates, and open questions stay in the question table), and `po-handoff` accepts only
  `specified`. A page that leaves one of those sections empty is rejected with
  `required_section_missing`, which names the sections. Features that were
  `specified` before stay valid.
- **`ingest` writes any page kind, for any role.** `po-intake` and `design-intake` stay the
  role-specific entry points for features and design pages; `ingest` processes one pending
  folder into a topic, research page, plan, `knowledge/wiki/direction.md`,
  `knowledge/wiki/roadmap.md`, persona, business rule, decision (ADR) or new feature. The board
  has participants, not roles, so any writable agent may use it. Its validator is built on the
  intake validators: the moved folder, its `MANIFEST.md` (every written page listed by path and
  canonical ID, rejected otherwise with `intake_manifest_required`, `intake_manifest_scope` or
  `intake_manifest_incomplete`), the processed-source links and the quarantine rules are
  those of `po-intake`; a new feature is held to every `po-intake` rule (`raw` + `po`, the five
  required sections, no rewrite of an existing feature). A topic, research page, plan, direction
  or roadmap page is created, or replaced in place when it exists (the proposal must have read
  it). A persona, business rule or decision is created and never rewritten, except that a new
  decision with `supersedes: ADR-NNN` must come with the old ADR changed in its status fields
  only: `status: superseded` and `superseded-by`, with an unchanged body. `ingest` cannot write
  design, requirement, API-contract or advisory pages, and a page in a sub-folder is refused.
- **Intake pages link the processed folder.** A feature's `sources` lists paths under
  `knowledge/intake/processed/`. A proposal that lists a path under
  `knowledge/intake/pending/` is rejected with `intake_source_not_processed`, which
  names the processed path to use, because the move turns the pending folder into the
  processed one. A path that will not exist after the proposal applies is rejected with
  `source_link_missing`. Links already on a page are not rechecked.
- **Raw sources are dated and immutable.** The folder an intake proposal moves is named
  `YYYY-MM-DD-slug`, the same under `pending`, `processed` and `quarantined`; another name
  is rejected with `intake_name_invalid`. A processed item is never edited: a proposal that
  writes into an existing processed item, or moves a folder onto one, is rejected with
  `processed_source_immutable`. Every processed folder carries a `MANIFEST.md`;
  `design-intake` supplies one too and lists the design page and the feature in it.
- **A quarantine is a conflict record.** An intake that contradicts an existing page moves
  its folder to `knowledge/intake/quarantined/YYYY-MM-DD-slug/` and writes only a
  `CONFLICT.md` with `status: open`, an `## Existing claim` and an `## Incoming claim`
  section (each with `**Claim:**`, `**Scope:**` and a linked `**Evidence:**`), as `SCHEMA.md`
  defines. Any other write, or a page that does not follow the format, is rejected with
  `quarantine_write_scope` or `conflict_report_invalid`, so the existing page stays
  untouched until a human resolves the conflict.
- **`dev-clarify` answers dev-owned questions**, as `po-clarify` does for `po` and
  `design-clarify` for `designer`. It resolves only questions owned by `dev`, on any
  feature that is not `done`, and cannot change the feature's status or owner. Next
  to the question table it may change the feature's Acceptance criteria, App
  scope and API surface sections and, on that feature's existing app
  requirement pages, What to build, Technical constraints, API contract reference
  and Acceptance criteria. It leaves a requirement page's frontmatter, including
  `status`, unchanged. Every section it changes must contain the full text of an
  answer it resolves in the same proposal. Open dev-owned questions block
  `dev-start` and `dev-done`.
- **`dev-done` takes the delivery evidence in its proposal.** The agent asks the
  developer for the implementation, test and release references of every declared
  app, or reads them from the page, and writes them as the `## Delivery
  evidence` table of the proposed feature page. The preview shows the evidence rows
  with the status change, so nothing has to be edited by hand first. A table with no
  app rows is rejected with `delivery_evidence_required`; an invalid row, a
  placeholder cell, a duplicate or an undeclared app with
  `delivery_evidence_invalid`; a `Release` cell that is neither release evidence
  (`release:`, `tag:` or `deployment:` and a URL or workspace path) nor a delivery
  attestation (`attested by <Name>:` and a URL or path) with
  `release_evidence_required`: a commit or pull request proves which code changed,
  not that it shipped. A reference the agent cannot check is recorded in the
  proposed Post-ship notes as the developer's attestation. `dev-done` stays an agent
  skill: the board offers no direct human `dev-done`.
- **`design-handoff` creates the API contract.** When the feature's API surface declares
  API work (any text other than an empty section or a plain statement that there is none,
  such as `None.`) and no contract covers the feature yet, the proposal must add
  `knowledge/wiki/api-contracts/F-XXX.md` as a new page with `feature-id`, `version: 1`,
  `status: agreed` and the sections Endpoints, Data models, Authentication requirements
  and Notes; the human confirming the preview is the agreement, and `dev-start` then
  finds an agreed contract. A page is rejected for another feature, a path other than
  `F-XXX.md`, a status other than `agreed`, a feature without declared API work, or a
  feature that an existing or linked contract already covers; the handoff never rewrites
  an existing contract. The page is written only from the API surface: each endpoint is a
  `METHOD /path` line, every path matches a path the API surface names (when it names none,
  each endpoint needs a resource word the API surface uses), and every data model is named
  by the API surface or by a listed endpoint. This is a structural check; the reviewer still
  confirms that the contract says what the API surface means. A declared API surface with no
  page is rejected with `api_contract_required`.

A transition changes the lifecycle fields of the feature's front matter (`status` and `owner`, and the advisory and revalidation fields where the action allows it) and writes no date, because pages carry none. It updates the feature's row in `status-board.md`, which has no date column. Every apply appends one entry to `knowledge/wiki/log.md` in the log format that `SCHEMA.md` defines. A `design-start` by a participant named Riley wrote:

```text
<!-- prism:board-history:v1 preview=27a3751e-2a5b-45bb-802e-d89658f34609 -->
## 2026-10-06 board-design-start | F-001
- paths: knowledge/wiki/features/F-001-document-review.md, knowledge/wiki/status-board.md
- evidence: board preview 27a3751e-2a5b-45bb-802e-d89658f34609
- by: Riley (human)
<!-- prism:board-actor:v1 {"action":"design-start","kind":"human","name":"Riley","participant_id":"54448713-7e43-4b1d-9b24-e0f2b92bdcb9","preview_id":"27a3751e-2a5b-45bb-802e-d89658f34609"} -->
```

`paths` lists the files the operation wrote (`log.md` itself is left out), `evidence` is the board preview, followed by the processed intake folders a move creates, and `by` is the participant's name and kind. The two comments are the idempotence marker and the recorded actor. Existing entries are never edited.

Relevant source changes invalidate the preview. Unrelated status board rows, index lines and log additions are preserved. Direct filesystem edits are external changes with no invented participant attribution. Service access controls do not restrict a coding agent's independent filesystem permissions.

### Live updates and expired sessions

One change poller per service watches the workspace for every connected viewer. It reuses the stored hash of a file whose size and modification time are unchanged and rehashes every file at least every 60 seconds. An external edit that keeps both a file's size and modification time can therefore go unnoticed by the poller for up to 60 seconds. Preview and apply always re-read the files they depend on, so a late view never lets an unreviewed change through.

When an apply is rejected because its sources changed, the board shows the service's reason and a **Preview again** action. Nothing was written. **Preview again** builds a new preview from the current files, and you review and confirm that one. The rejection happens before an operation exists, so there is no operation to look up.

A browser session ends after 12 hours, when the board service restarts, when the grant is revoked or when the workflow identity changes. The board then shows "Board session expired" with a **Reconnect** action, and an apply that runs after expiry shows the same message in its dialog. **Reconnect** reloads the page and asks for the human token again.

Connected clarification has a deterministic traceability requirement: each changed
requirement-bearing section of a feature, an app requirement page or a design
page includes the full text of at least one answer resolved in that proposal. Case and whitespace differences are ignored,
and the answer must stand as whole words (`no` is not found inside `not` or `know`);
paraphrases alone do not pass. Skill discovery reports this limitation. Including
an answer does not establish that every edit follows it: the agent and reviewer
still perform that semantic check before confirmation.

### Rejected proposals

A rejected proposal keeps its stable error code and status. The message names
the exact place and the fix. A rejection can also carry a small `details`
object: HTTP returns it as `error.details`, and MCP appends it as compact JSON
after the message in the tool error text. Both transports redact the
participant token everywhere, and the whole error stays under 2,000 characters.
Only short excerpts of workspace text appear in an error.

| Code | `details` |
| --- | --- |
| `clarify_answer_unlinked`, `design_answer_unlinked`, `requirement_answer_unlinked` | `path`, `section`, `resolved_questions` (numbers), `resolved_answers` (question number to the first 160 characters of its answer). One of those answers must appear verbatim in that section; case and whitespace are ignored. |
| `managed_file` (403) | The proposal supplies `index.md`, `status-board.md` or `log.md`. The board derives their changes; leave them out. |
| `write_path_unavailable` (403) | A skill writes Markdown pages directly in its wiki directories, for example `knowledge/wiki/features/F-001-export.md` (`ingest` also `topics/`, `research/`, `plans/`, `decisions/`, `direction.md` and `roadmap.md`), and the intake `MANIFEST.md` or `CONFLICT.md` of a processed or quarantined folder. A page in a sub-folder such as `knowledge/wiki/features/2026/F-001-export.md` is refused, because the wiki reads one folder level and would never lint, graph or query it. |
| `stale_preview` (409) at `apply` | The preview's sources changed, or a source this skill must read changed or appeared after the preview. `details.paths` lists the sources that appeared. Nothing was written: read them and preview again. |
| `invalid_path` (400) | For a path segment that Windows cannot hold: `path`, `segment` and `reason`. A segment may not contain `:` `<` `>` `"` `|` `?` `*` or a control character, end in a dot or a space, or be a reserved device name (`CON`, `PRN`, `AUX`, `NUL`, `COM1` to `COM9`, `LPT1` to `LPT9`, with or without an extension, in any case). Prism applies this on every operating system, so a workspace written on Linux or macOS can be checked out on Windows. The preview is rejected and nothing is written. This applies to paths a caller supplies. A name that already exists on disk and that Windows cannot hold is skipped when the board reads the workspace, as `list_workspace` skips it: it is not listed, read or fingerprinted, and `changes` reports it under `skipped_paths` (`count`, up to five `examples` and a `reason`) instead of failing. Rename such a file. |
| `invalid_markdown`, `invalid_frontmatter` | `path`, `problem`, and for a YAML error `line` and `column` within the file. A page starts with `---`, a YAML mapping and a closing `---`. |
| `invalid_change`, `invalid_move` | `index` of the item in `changes` or `moves`, `missing` and `unexpected` field names, `expected` field names (`path`, `content` or `source`, `destination`), and `not_string` for fields with the wrong type. |
| `invalid_changes`, `invalid_moves` | `index` of the first item over the limit, `maximum` and `received`; or `expected` and `received` when the value is not a list. |
| `lifecycle_frontmatter_scope`, `unknown_frontmatter_fields`, `clarify_frontmatter_change`, `design_frontmatter_change`, `requirement_frontmatter_change` | `path` and the offending `fields`; the first two also list the `allowed` fields. |
| `lifecycle_body_scope`, `clarify_scope_exceeded`, `design_clarify_scope_exceeded`, `requirement_clarify_scope_exceeded`, `ask_scope_exceeded` | `sections`: the sections outside the action's scope that the proposal changed. Restore them to their current text. `whitespace_only` lists the sections that differ from the current text only in whitespace, usually the file's missing final newline: send unchanged sections exactly as `read_workspace` returned them. |
| `linked_page_scope` | `path`: the linked requirement or API contract that changes more than its `status`. Restore everything else to the current text. |
| `invalid_intake_feature` | `path`, `status`, `owner` and the expected `expected_status` (`raw`) and `expected_owner` (`po`). |
| `intake_source_not_processed`, `source_link_missing` | `path` (the page), `source` (the entry) and, for `intake_source_not_processed`, `expected`: the `knowledge/intake/processed/<folder>` path to list instead of the pending one. A feature's `sources`, a persona's `sources` and a business rule's `source` may link only a path that exists on disk, that the proposal writes, or that lies in the processed folder the proposal's own move creates. An entry already on the page, a URL, and a persona or business-rule entry that is not a `knowledge/` path are not checked. Nothing is written. |
| `intake_name_invalid` | `path` (the destination folder), `name` and `expected` (`YYYY-MM-DD-slug`). The move's folder is not a date, then lowercase words joined by hyphens, with a real calendar date. Rename the pending folder. |
| `processed_source_immutable` (409) | `path` (the written or destination path) and `item` (the existing `knowledge/intake/processed/<folder>`). A processed intake item is immutable: put new or changed material in a new dated pending folder. |
| `conflict_report_invalid` | `path`, `status` (the status found, or `null`) and `problems` (up to ten). A quarantine's `CONFLICT.md` needs `status: open`, an `## Existing claim` and an `## Incoming claim` section each with `**Claim:**`, `**Scope:**` and a linked `**Evidence:**`. |
| `quarantine_write_scope` | A quarantine writes only its `CONFLICT.md`, with substantive text, and changes no wiki page. |
| `intake_manifest_required`, `intake_manifest_scope`, `intake_manifest_incomplete` | A processed folder gets exactly one written file, `MANIFEST.md`. `po-intake` lists every page it creates by path and canonical ID; `design-intake` lists the design page and the feature; `ingest` lists every wiki page it writes by path and, where the page has one, canonical ID. |
| `intake_existing_feature`, `intake_existing_page` | `po-intake` and `ingest` create features, personas and business rules and never rewrite an existing one. |
| `invalid_topic`, `invalid_research`, `invalid_plan`, `invalid_direction`, `invalid_roadmap` | `path` and, for a status, `allowed`. The page's `kind` is that of its folder, a topic, research page or plan has a nonblank `title` and a `status` of its kind (topic `draft` or `current`; research `open` or `concluded`; plan `proposed`, `active`, `paused`, `done` or `dropped`), and `sources` is a nonempty list of the intake items, records or URLs it rests on. Other front matter fields are rejected with `unknown_frontmatter_fields`; the required sections (`required_section_missing`) are listed in `SCHEMA.md`. |
| `wiki_path_invalid` | A topic, research page or plan is named with lowercase words joined by hyphens, such as `payment-flows.md`. |
| `invalid_decision`, `decision_path_mismatch` | `path`. A new decision has an ADR-number `id` that its file name carries, a title, an ISO `date`, the status `proposed` or `accepted`, and the sections Context, Decision, Rationale and Consequences. |
| `record_immutable` | `path` and `changed` (the front matter fields that differ). A decision is a record: `ingest` changes only `status: superseded` and `superseded-by` on it, with its body unchanged, and only when a new decision in the same proposal supersedes it. |
| `supersession_incomplete` | `path`. A new decision's `supersedes` needs the existing old ADR in the proposal with `status: superseded` and `superseded-by` naming the new one, and the reverse. |
| `stale_status_row`, `stale_index_entry` (409) at `apply` | The status board row of a feature, or the index line of a page, changed after the preview. Nothing was written: preview again. |
| `duplicate_status_row`, `duplicate_index_entry` (409) | A feature has more than one row in `status-board.md`, or a page more than one line in `index.md`. Remove the duplicates, then preview again. |
| `invalid_status_board` (409) | `status-board.md` lacks the canonical `\| ID \| Feature \| Status \| Owner \| Board Review \|` table. |
| `required_section_missing` | For `po-specify`: `path` and `sections`, the empty sections to fill. The message gives a line to write under each. |
| `clarify_stage_unavailable` | `path` and `status` (`done`): `dev-clarify` does not change a done feature; reopen it first. |
| `api_contract_required` | `path` (the contract page to add), `feature_id`, `status` (`agreed`) and `sections` (the four required sections). |
| `api_contract_not_applicable`, `api_contract_exists` | `path` and `feature_id`. `api_contract_exists` for a second contract also lists the `existing` pages. |
| `api_contract_initial_status` | `path`, `status` and `expected_status` (`agreed`). |
| `api_contract_untraceable` | `path`, `feature_id` and `endpoints` (the `METHOD /normalized/path` entries that the API surface does not support) or `models` (the data models that neither the API surface nor an endpoint names). |
| `delivery_evidence_required`, `delivery_evidence_invalid` | `path`, `apps` (the declared apps), `missing_apps` and `problems` (up to six parse problems). The message shows the row to add: `\| app \| implementation reference \| test command and result \| release: URL of the release or deployment record \|`. |
| `release_evidence_required` | `path`, `apps`, `missing_apps` and `problems`: each names the app whose `Release` cell is not release evidence (`release:`, `tag:` or `deployment:` and a URL or workspace path) or a delivery attestation (`attested by <Name>:` and a URL or path). A bare commit SHA, a pull-request or merge-request URL, `merged`, a branch name and free text are rejected. |
| `app_retired` | `apps`, `retired_apps` and `board_apps`. A new feature, or an edit that adds an app to a feature's scope, names an app that has been retired. Name an active app. |
| `app_retired_in_scope` | `feature_id`, `apps` and `retired_apps`. A feature before `done` still lists a retired app, so no lifecycle action runs until its `apps` is edited explicitly; retirement never changes scope by itself. |
| `api_surface_without_api_app` | `feature_id`, `apps` and `board_apps`. The `design-handoff` proposal's feature declares API work in `## API surface`, but no active app in its `apps` serves an API (`serves-api`; `unknown` counts as serving one). |
| `missing_read_revisions` | `paths` (the sources to read, as many as fit), `total` (how many are missing) and `read_with` (`read_workspace`). A required source has neither a digest in `read_revisions` nor a read by this participant. Read those paths with `read_workspace` and preview again. |
| `read_digest_mismatch`, `stale_read_revision` | `path`, `supplied` (the digest you sent or the one recorded from your read, shortened) and `expected` (the file's current digest). `read_digest_mismatch` means the board never returned the digest you sent for that file, so it is mistyped or copied wrongly; leave `read_revisions` out or copy it from `read_workspace` exactly. `stale_read_revision` means the board returned that digest and the file has changed since; read it again and review the change. |
| `invalid_feature_output` | For an app outside the board's scope: `apps` (the declared ones) and `board_apps` (the IDs of the board's apps); `discover` lists the apps under `board.apps`. A board with no apps rejects every feature scope and says to register an app with `prism app add`. |
| `lifecycle_action_required` | For a status or owner change that the skill does not perform: `path`, `skill`, `from` and `to` (status and owner pairs). A clarify skill never changes either. |
| `new_question_must_be_open` | `path`, `question` (the number that is not in the current table) and `existing_questions`. A question that is not in the table is added with `ask` before it is answered. |
| `impact_review_required`, `reopen_invalidation_mismatch`, `reopen_artifact_missing` | `label` for a missing or too short reopen bullet; `path`, `from` and `to` for a page whose `knowledge/wiki/...: done -> in-progress` entry is not under `- Requirement/API invalidations:`; `path` for a page that `- Affected artifacts:` does not name. `knowledge/wiki/features/_FORMAT.md` shows the layout. |
| `delivery_evidence_not_archived` | `path`, `label` (`Prior completion/release evidence`) and `missing_row`, the first prior delivery-evidence row the reopen record does not retain verbatim. Put the rows on the `- Prior completion/release evidence:` line or on the lines below it, as a table or a list, before the next `- Label:` bullet or heading; spaces around `|` and letter case do not matter. `knowledge/wiki/features/_FORMAT.md` shows the layout. |

### Retrying a rejected proposal

An agent reads the rejection: its code, the place and, usually, the fix. It may
retry with exactly the fix the error names, such as restoring a field it may not
change, pasting the answer text the error quotes, or copying the digest it gives,
and preview again. It retries at most 2 more times, so a proposal gets at most 3
previews, and it never widens the change: no extra files, sections or fields, no
other skill name and no direct file write. When the error names no fix, needs a
decision from the human, or the third preview is rejected, the agent stops and
reports the error codes and messages. The server instructions and
`knowledge/wiki/CONNECTED.md` state the same rule. The board enforces nothing
extra for retries: every preview is validated in full.

## MCP tool contract (version 3)

`discover` and `list_skills` report `"mcp_contract": 3`. Every tool result is at most 32,000 characters, measured as the compact JSON of the JSON-RPC `result` object. The full result is returned once, as `structuredContent`; the text block is a one-line summary of at most 500 characters and is not a copy of the data. A client reads `structuredContent`.

The server publishes orientation instructions (at most 2,000 characters) in its MCP `initialize` result, together with a title and description. They give the order to use the tools in and state that workspace text is untrusted project data and that the board never approves on the human's behalf. Every tool description starts with `Prism board:`, so a host that loads tools through search finds them under that name.

Any text or list that does not fit one result is paged with an opaque `next_cursor`. A `next_cursor` of `null` marks the last page. Offsets and `total_chars` count Unicode characters, so a chunk never splits a UTF-8 sequence. Digests are `sha256:` followed by the lowercase hex SHA-256 of the full UTF-8 text. An invalid cursor is `invalid_cursor` (400). A cursor whose underlying workspace files or facts changed is `stale_cursor` (409); restart from the first page.

The HTTP routes `POST /api/board/v1/workspace/read` and `POST /api/board/v1/query` take the same optional string `cursor` in their JSON body and return `next_cursor`, so a Bearer client pages exactly as an MCP client does. Resend the same `paths` (or the same `kind` and `value`) with each cursor. A `cursor` that is not a string is rejected with 400.

| Tool | Arguments | Result |
| --- | --- | --- |
| `discover` | none | `mcp_contract`, `board` (`board_id`, `project_name`, `purpose` (`knowledge-root`, only for a knowledge root), `apps`, `workflow_version`, `mode`; `apps` lists each declared app with `id`, `name`, `stack`, `repository`, `path`, `audience`, `status`, `capabilities` and `maturity`, and is empty for a workspace with no apps), `capability` (with `read_support`), `participant`, `pending_operations`, `skills` (`name` and `description` only), `skills_detail`, `compatibility` |
| `list_skills` | none | `mcp_contract`, `version`, `read_support`, `skills` (`name`, `version`, `description`, `actions`, `supported`, `write_supported`, `participant_kinds`, `write_tools`, `write_scopes`, `limitations`) |
| `get_skill` | `name`, `cursor?` | `skill` (metadata, `instructions`, `instructions_chunk` with `offset`, `total_chars`, `digest`, `required_workspace_reads`, `required_workspace_reads_chunk` with `offset`, `total`, and `references`) and `next_cursor` |
| `get_skill_reference` | `name`, `path`, `cursor?` | `content`, `offset`, `total_chars`, `digest`, `next_cursor`. A path outside the skill's `references` is `reference_not_found` (404) |
| `read_workspace` | `paths`, `cursor?` | `files` (each with `path`, `content`, `offset`, `total_chars`, `digest`, `provenance`) and `next_cursor` |
| `list_workspace` | `prefix?`, `cursor?` | unchanged: `files`, `total`, `next_cursor` |
| `query` | `kind`, `value?`, `action?`, `cursor?` | the existing result, plus `next_cursor`; `owner`, `app` and `search` also return `total` |
| `preview_skill` | `skill`, `changes`, `moves?`, `read_revisions?` (usually left out: see "Recorded reads") | the preview header (`preview_id`, `classification`, `applicable`, `checks`, `blockers`, `source`, `target`, `source_revision`, `moves`), `writes` and `writes_chunk` (`offset`, `count`, `total`), and `next_cursor` |
| `preview_transition` | `feature_id`, `action`, `inputs?` | the same as `preview_skill`; only a human participant may call it |
| `get_preview` | `preview_id`, `cursor?` | the same result as the preview call, for a preview the caller created. An unknown preview or another participant's is `preview_not_found` (404) |
| `apply` | `preview_id`, `operation_id` | the receipt |
| `operation` | `operation_id`, `cursor?` | `state` (`pending`, `conflict`, `applied` or `abandoned`), `receipt`, and for an unfinished operation `actor`, `moves`, `recovery_review_revision`, `remaining_changes` and `remaining_changes_chunk`, and `next_cursor` |
| `recover` | `operation_id`, `review_revision?`, `semantic_review_acknowledged?`, `abandon?` | the receipt. `abandon` is for a writable human only: see "Abandoning an operation" |
| `changes` | `cursor?` | `cursor`, `head_cursor`, `board_revision`, `changes`, `has_more`, and `skipped_paths` when existing names were skipped. The cursor is a number the board returned, or `N~K` while an oversize event is returned in chunks; any other value is `invalid_cursor` (400) |

`references` is an index: each entry has `path`, `title` (the first Markdown heading, or the file name), `size_chars` and `digest`. It never carries the reference text.

`get_skill` continues first through its `instructions` and then through `required_workspace_reads`. Every page repeats the metadata and the references index. Join the `instructions` chunks and concatenate the `required_workspace_reads` lists across the pages.

`read_workspace` returns whole files in request order until the next file would not fit, then a `next_cursor`. A file larger than one result is returned in chunks. Resend the same `paths` with each cursor. The 64-path, approved-path and 2 MiB limits of the request are unchanged.

**Recorded reads.** The service records, for each participant, the digest of every file `read_workspace` returned in full (the last chunk of a chunked file counts). When a `preview_skill` proposal omits `read_revisions`, or omits a source the skill requires, the service uses that participant's recorded digest for the source. The stale check is the same as for a digest the caller sends: a file that changed after the read is rejected as `stale_read_revision`. A required source the participant never read, including one only another participant read, is rejected as `missing_read_revisions` with `details.paths` listing what to read. The record is held in memory per participant and is empty after a service restart, so the agent reads again. A digest the caller does send is checked as before.

Every path in the `references` of `get_skill`, and every path an instructions text lists as a canonical reference (`.claude/commands/<name>.md`), resolves with `get_skill_reference` exactly as written.

`query` pages `owner`, `app` and `search`. For `owner` the pages walk `facts.features` and then `facts.open_questions`; for `app`, `facts.features` and then `facts.app_requirements`; for `search`, `facts.results`. `total` counts those items, and every item appears on exactly one page. An item that alone is larger than one result is replaced by an entry that keeps its short fields and adds `oversize: true`, `size_chars` and a `note`; read its `path` with `read_workspace`, which returns it in chunks. `facts.feature_count` and the other counts stay totals. `sources` lists the paths of the page's items.

Results contain no absolute paths: preview checks, `root` and `sources` of query results and every other path are relative to the workspace, with forward slashes.

#### Previews, operation records and change feeds

A preview carries the exact before and after text of every write, which can exceed one result. `preview_skill`, `preview_transition` and `get_preview` return the preview in pages. Every page repeats the header and lists a window of `writes`. Each write has `path`, `role` (`canonical`, `index` or `log`), `before_digest`, `after_digest`, `merge`, `before_chars`, `after_chars`, `before` and `after`. A write whose text does not fit one page is split: each slice carries `before_chunk` or `after_chunk` (`offset` and `total_chars`), and a side whose key is absent was sent on an earlier page or arrives on a later one. Follow `next_cursor` with `get_preview(preview_id, cursor)` until it is `null`, join the slices of each `path` in order and compare the joined text with its digest. A preview that fits one result has `next_cursor: null`, whole `before` and `after` text and no `*_chunk` keys.

The result leaves out `proposed_changes` and `read_revisions`, which copy the caller's own input (`read_revisions_count` keeps the count), and the internal `source_map` (`source_count` keeps the count). `moves` lists `source`, `destination`, `source_digest` and `source_file_count`. A cursor belongs to one preview: another preview's cursor is `invalid_cursor`. A preview is immutable, so its cursors do not go stale.

`operation` pages `remaining_changes` of an unfinished operation the same way, with `before` and `after` text per path, and the same header (`state`, `actor`, `recovery_review_revision`) on every page. A cursor for an operation whose state or files changed since the first page is `stale_cursor`. `changes` returns the events that fit one result, oldest first, and sets `cursor` to the last event returned and `has_more` to whether events remain; call it again with that `cursor`. An event that alone is larger than one result is never skipped: it is returned alone as a record whose `event` is `{"type": ..., "chunked": true}` and whose `event_chunk` carries `offset`, `total_chars` and `text`, a slice of the event's compact JSON. The page's `cursor` is then `N~K` (event number `N`, next character `K`); call `changes` with it to continue. After the last slice, `cursor` is the event number and the feed goes on. Join the `text` slices in order and parse the result as the event. `apply`, `recover`, `discover`, `query` and `list_skills` return their whole result when it fits. When it does not, the tail of the longest lists is cut and every cut is named in `truncated` with the number of items left out.

A client loop that reads every chunk and checks its digest:

```python
import hashlib

def read_all(call_tool, tool, arguments, field="content"):
    """Fetch every chunk of a text and verify it against the digest."""
    parts, cursor = [], None
    while True:
        result = call_tool(tool, {**arguments, **({"cursor": cursor} if cursor else {})})
        data = result["structuredContent"]
        parts.append(data[field])
        cursor = data["next_cursor"]
        if cursor is None:
            break
    text = "".join(parts)
    if "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest() != data["digest"]:
        raise ValueError("The reassembled text does not match its digest.")
    if len(text) != data["total_chars"]:
        raise ValueError("The reassembled text has the wrong length.")
    return text

schema = read_all(call_tool, "get_skill_reference", {"name": "po-intake", "path": "knowledge/wiki/SCHEMA.md"})
```

For `read_workspace`, group the chunks of each file by `path` and compare the joined text with that file's `digest`; `offset + len(content) == total_chars` marks a file's last chunk.

### Upgrading a pinned workspace

A workspace pinned to an earlier workflow asset digest opens read-only until it is upgraded, and grants record the digest they were issued under, so every earlier grant stops working after the upgrade (`grant_identity_changed`). For each workspace, stop the board service, run `prism workflow upgrade . --apply`, issue new grants with `prism board grant`, and update each agent host's token. Reference text is available only through `get_skill_reference`.

## Interrupted operations

Cancellation before submission writes nothing. After submission, keep the operation ID and retrieve its receipt before deciding whether to retry. The same participant, preview and operation ID identify the same operation; retries must not duplicate a transition or log entry.

The board separates pending or conflicted operations from lifecycle columns. Recovery reconciles recorded before/after states and preserves conflicting external edits. A completed receipt followed by a failed refresh is shown as applied with a stale view. Multi-file writes are recoverable; they are not an atomic transaction against arbitrary external filesystem writers.

A writable human can inspect and recover an agent's interrupted operation even
after that agent's grant is revoked. The board requires a fresh inspection of the
remaining changes and an explicit acknowledgement. Relevant changes invalidate
that confirmation. The receipt preserves the original actor and records the
recovering human separately; other agents, read-only participants and unrelated
human operations do not gain this recovery permission.

### Recovery against the current files

A writable human who recovers with a fresh `review_revision` and
`semantic_review_acknowledged: true` has inspected the current relevant files: the
`review_revision` binds them. Recovery then checks the remaining writes against the
files on disk now, not against the sources recorded when the preview was made, so a
page edited by hand while the operation was interrupted no longer blocks it. The
current rules still apply: a write whose file matches neither its recorded before-state
nor its recorded after-state, a folder move whose tree changed, a stale review and a
revoked or read-only participant still stop the recovery and leave the files as they
are. An agent that recovers its own operation keeps the recorded-source check.

### Abandoning an operation

A conflicted or interrupted operation that can no longer be rolled forward, for
example because its intake folder was renamed or deleted, would otherwise block every
new write that overlaps it. A writable human closes it with `recover` and
`abandon: true`, the same inspection and the same fresh `review_revision` with
`semantic_review_acknowledged: true` that recovery needs; the board's operation
review has an **Abandon operation** button for it. Agents cannot abandon
(`abandon_requires_human`, 403). An operation that can still be recovered against the
current files is not abandoned (`abandon_not_needed`, 409): recover it. An applied
operation cannot be abandoned (`operation_already_applied`, 409).

Abandoning undoes nothing. Files already written and folders already moved stay as they
are, and the receipt records them: `applied_paths` and `unapplied_paths` for the writes,
`moved_folders` and `unmoved_folders` for the moves, the `reason` recovery failed, the
original actor under `actor` and the human under `abandoned_by`. The state is
`abandoned`, which is final: the operation no longer counts as pending, no longer
blocks overlapping writes, no longer blocks `prism workflow upgrade`, and asking for it
again returns the same receipt. Finish by hand whatever the receipt lists as not
applied, or preview the change again.

### Changes

`changes` returns durable board events after an optional cursor, each as `cursor`, `operation_id`, `event` and `created_at`. The event `type` is one of:

| Event type | Recorded when | Event fields |
| --- | --- | --- |
| `operation-applied` | An operation finishes. | `receipt` |
| `operation-recovery-started` | A writable human starts recovering another participant's operation. | `actor`, `operation_id` |
| `operation-conflict` | An operation ends in `conflict`. | `operation_id`, `paths` |
| `operation-abandoned` | A writable human abandons an operation. | `operation_id`, `actor` (the original actor), `abandoned_by`, `applied_paths`, `unapplied_paths`, `moved_folders`, `unmoved_folders` |

`paths` lists the workspace paths that block the operation, such as a file edited outside the board after it was journaled. It is empty when no single path is at fault. An event carries paths only, never file content. Repeating `recover` on an operation that is still in conflict for the same paths records no further event; a later conflict with different paths records a new one. Clients that read the event type should ignore types they do not recognize.

Static exports and `prism wiki graph --open` retain the legacy read-only preview/copy behavior. They do not gain write authority from a displayed action or a Prism version string.
