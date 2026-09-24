# Shared local board

This is the usage contract for the connected-core implementation. Current acceptance and remaining checks are recorded in the [core plan](prism-core-workflow-plan.md). The first release runs on one computer: one service per workspace serves the browser board and an MCP endpoint. Remote hosting is deferred.

## Install the workflow

For an empty workspace or an existing repository, preview the files first:

```text
prism workflow install . --name "Document review" --platform backend
prism workflow install . --name "Document review" --platform backend --apply
```

Repeat `--platform` for additional scope IDs. Initially these are `backend`, `web-user-app`, `web-admin-portal`, `mobile-android`, and `mobile-ios`. A workflow-only workspace does not need corresponding application directories. Installation creates workflow assets, a manifest and a local-state ignore rule; it does not generate an application. Existing source code, wiki content and custom agent instructions are preserved. Conflicting owned guidance stops installation and identifies the file for resolution.

Review the plan's optional steps when existing `AGENTS.md` or `CLAUDE.md` files
are preserved. Add the suggested `knowledge/wiki/CONNECTED.md` pointer to your
own guidance if you want agents to discover the connection there; installation
does not rewrite those custom files.

Generated workspaces, including a fresh `prism new` result, use an explicit
upgrade preview to activate connected writes. Generation supplies the wiki and
agent guidance; this step adds the board identity and canonical workflow pin:

```text
prism workflow upgrade .
prism workflow upgrade . --apply
```

`--apply` shows the proposed changes and asks for confirmation. Automation must explicitly use `--apply --yes`. Reading or viewing an older workspace does not upgrade it. The manifest records a board UUID, workflow version, mode and canonical asset digest. An incompatible pin disables connected writes until an explicit upgrade.

Before upgrading an existing connected workspace, finish or recover its pending
operations and stop its board service. Upgrade uses the same workspace process
lock as the service and refuses to change the pin while an operation is incomplete.
The preview identifies `.prism/state/board.lock` when the upgrade needs to create
it; this does not initialize the board database. A changed workflow version or
asset digest invalidates existing grants, so issue new participant grants after
the upgrade. Fresh workflow installation and generated-workspace activation do
not create runtime state.

Use the existing agent-led `setup-project` skill to initialize product context after installing assets. Setup and advisory-board authoring retain their direct-file workflow in this slice; connected skill discovery must state which operations can actually write through the service.

Application generation remains available through `prism new`. Its template trust, release selection and update/provenance rules are independent of workflow adoption.

## Register participants and run the service

```text
prism board grant "Product owner" --kind human --write --path .
prism board grant "Coding agent" --kind agent --write --path .
prism board serve . --port 8765
```

Each grant prints its own token once. Keep it private. Enter the human token in the board's sign-in form; configure an agent's token in that host's environment. Tokens do not belong in URLs, repository files or prompts. Without `--write`, a grant is read-only. Participant names identify locally registered grants; they do not independently verify a person's identity or assign a workflow role.

The server binds to loopback. The browser uses an HttpOnly session cookie and same-origin request checks. MCP uses its participant Bearer token. Revoke access with the participant ID returned when the grant was created:

```text
prism board revoke PARTICIPANT_ID --path .
```

Connected workspaces require ordinary local files and directories. The service
rejects symbolic links, junctions and other reparse points in the workspace paths.

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

Direct an agent in its CLI, for example: “Use Prism's PO intake skill to refine the pending document-review brief.” The agent discovers the board, retrieves its pinned skill and references, reads current workspace data, and follows the skill's required conflict checks, semantic review and confirmation. It sends a bounded proposal to `preview_skill`, shows the exact changes for confirmation, and applies the returned preview with an operation ID. There is no second approval queue in the board.

`list_workspace` discovers approved wiki and intake paths in pages;
`read_workspace` returns their text and content digests. `query` reuses Prism's
existing feature, owner, platform, blocker, search, lint and lifecycle preflight
facts. These read operations work with read-only participant grants.

Connected intake in this release supports UTF-8 `.md`, `.txt`, `.yaml` and `.yml`
sources up to 512 KiB per file. Inventory results identify unsupported attachments
and oversized files. PDF/image extraction is deferred; an intake containing a
required unreadable source stops with a clear limitation instead of ignoring it.
Agents read every `required_workspace_reads` path returned by `get_skill`, plus
the operation's target, linked context and intake evidence, through the service.

The board directly supports human `po-handoff`, `design-start` and `dev-start`. Dragging and the action controls enter the same preview. The human reviews the evidence and exact changes, supplies the required review acknowledgement and any permitted PO advisory skip reason, then confirms. A blocked mapped drop explains the blockers with confirmation disabled. Specification, design handoff, Done and reopening continue through the existing agent skills. A gesture alone never moves canonical state or manufactures evidence.

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

Skill discovery exposes 23 complete canonical skills. Connected writes are
available for `po-intake`, `design-intake`, `ask`, `po-clarify`, `design-clarify`,
`po-specify`, `po-handoff`, `design-start`, `design-handoff`, `dev-start`,
`dev-done`, and `feature-reopen`. The three reopen routes are actions of the
last skill. Other skills provide guidance or read operations: always inspect
`write_supported` and `limitations`. An unavailable or rejected connected write
stops that attempt. A direct-file compatibility workflow requires an explicit
human choice and follows the original skill's complete review and confirmation.

Relevant source changes invalidate the preview. Unrelated index rows and log additions are preserved. Direct filesystem edits are external changes with no invented participant attribution. Service access controls do not restrict a coding agent's independent filesystem permissions.

Connected clarification has a deterministic traceability requirement: each changed
requirement or design section includes the full text of at least one answer
resolved in that proposal. Case and whitespace differences are ignored;
paraphrases alone do not pass. Skill discovery reports this limitation. Including
an answer does not establish that every edit follows it: the agent and reviewer
still perform that semantic check before confirmation.

## Interrupted operations

Cancellation before submission writes nothing. After submission, keep the operation ID and retrieve its receipt before deciding whether to retry. The same participant, preview and operation ID identify the same operation; retries must not duplicate a transition or log entry.

The board separates pending or conflicted operations from lifecycle columns. Recovery reconciles recorded before/after states and preserves conflicting external edits. A completed receipt followed by a failed refresh is shown as applied with a stale view. Multi-file writes are recoverable; they are not an atomic transaction against arbitrary external filesystem writers.

A writable human can inspect and recover an agent's interrupted operation even
after that agent's grant is revoked. The board requires a fresh inspection of the
remaining changes and an explicit acknowledgement. Relevant changes invalidate
that confirmation. The receipt preserves the original actor and records the
recovering human separately; other agents, read-only participants and unrelated
human operations do not gain this recovery permission.

Static exports and `prism wiki graph --open` retain the legacy read-only preview/copy behavior. They do not gain write authority from a displayed action or a Prism version string.
