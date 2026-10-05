# Agent hosts: Claude Code and Codex

Claude Code and Codex connect to the shared board through the same Streamable HTTP MCP endpoint and the same tool contract. This page records the versions Prism was tested with, the settings that matter, what each host does well and where it needs help. [Shared board](shared-board.md) is the usage contract and [Troubleshooting](troubleshooting.md) lists the failures.

## Tested versions

| | Claude Code | Codex |
| --- | --- | --- |
| Version | 2.1.286 | codex-cli 0.159.0 |
| Model and effort | Claude Sonnet 5.5, medium | GPT-6.1 Sol, medium |
| Transport | Streamable HTTP (`"type": "http"`) | Streamable HTTP through the standard `mcp_servers` configuration |
| Authentication | `Authorization: Bearer ${PRISM_BOARD_TOKEN}` header | `bearer_token_env_var = "PRISM_BOARD_TOKEN"` |
| Tested mode | Non-interactive (`claude -p`) | Non-interactive (`codex exec`) |

Both hosts ran against a local board service on Windows 11. A full journey was exercised with them: `po-intake`, `po-clarify`, `po-specify`, the human `po-handoff`, `design-start` and `dev-start`, `design-clarify`, `design-handoff`, `dev-clarify`, `dev-done`. Every agent apply succeeded on its first call and the agent read the operation receipt back.

## Connect a host

The exact configuration for both hosts is in [Connect an agent host](shared-board.md#connect-an-agent-host). Two rules apply to both:

- Give each host its own grant (`prism board grant "NAME" --kind agent --write --path .`) and keep the token in the `PRISM_BOARD_TOKEN` environment variable of the process that starts the host. A token does not belong in a configuration file, a URL or a prompt.
- Start the host from a shell where the variable is set, with the board running. The host expands the variable itself.

No other host setting is needed. In particular, `MAX_MCP_OUTPUT_TOKENS` is not needed: both hosts delivered the largest preview results whole, without truncation or a saved-to-file fallback. A host with a much smaller tool-result limit was not tested; raise its limit if a result arrives cut off.

## Claude Code

- **Tool discovery.** With Prism as the only MCP server, Claude Code loads all 13 Prism tools (`mcp__prism__*`) directly. With many MCP servers configured (hundreds of tools), Claude Code defers MCP tools behind tool search. The agent then finds the Prism tools with one search, because every Prism tool description starts with `Prism board:`, and calls them from the next turn on. This costs one extra turn. No setting is required; `ENABLE_TOOL_SEARCH=false` loads every tool up front if you prefer that. See Claude Code's [MCP documentation](https://code.claude.com/docs/en/mcp).
- **Result format.** The model reads the complete `structuredContent` JSON as the tool result text.
- **Non-interactive runs.** In `claude -p` nothing outside the pre-approved tools can run, so allow the Prism tools explicitly with `--allowedTools "mcp__prism__*"`. Add `--strict-mcp-config` with `--mcp-config <file>` to isolate Prism from other configured servers, and `--tools ""` to remove the built-in tools so the agent works only through the board. Set the model and effort explicitly in every launch.
- **First previews are often incomplete.** Claude's first `preview_skill` call often leaves out a source it needs, and the board answers `missing_read_revisions` with the paths to read. Claude reads them and previews again in the same run. It should leave `read_revisions` out entirely; a digest it types by hand can be wrong (`read_digest_mismatch`).
- **It retries within the rule.** Claude retries a rejected preview with the fix the error names and stops when the same error repeats ([Retrying a rejected proposal](shared-board.md#retrying-a-rejected-proposal)).
- **It can call a tool that does not exist.** The host returns an error and the run continues.

## Codex

- **Tool discovery.** The Prism tools are available from the first turn and are called directly. There is no search step.
- **Configuration.** The two `[mcp_servers.prism]` keys in [Connect an agent host](shared-board.md#connect-an-agent-host) work as `-c` overrides on the command line (`-c mcp_servers.prism.url="..."` and `-c mcp_servers.prism.bearer_token_env_var="PRISM_BOARD_TOKEN"`). The same keys in Codex's TOML configuration file were not tested. Codex still reads its own configuration file when overrides are given, so a model or effort set there applies unless a launch overrides it.
- **Result format.** The event stream carries both a one-line summary and the structured result; the agent used the structured data.
- **Paging.** Codex follows `next_cursor` chains through `read_workspace`, including a cursor-bound request repeated with the same `paths`. An `invalid_cursor` or `path_not_approved` error was recovered in the same run.
- **It may stop at the first rejected preview.** Codex cites the retry rule in `knowledge/wiki/CONNECTED.md` and reports the rejection. Quote the rejection and ask it to try again; the retry then succeeds when the error names a fix. It also stops, and names the conflict, when your request contradicts an earlier answer.
- **It may try a shell command first,** for example to read `CONNECTED.md` from disk, and then continue with the MCP tools. Where Codex's shell sandbox cannot run commands, the journey is unaffected, because it needs only MCP tools.
- **A headless run can fail to exit.** Once, `codex exec` produced its final message and kept running. Set a timeout on automated runs; the work it reported was complete.
- **Codex keeps its own records.** It stores session records and a memory file in its configuration folder, and it may consult the memory file.

## What to expect

- **Time.** A run that reaches a preview takes about one to three minutes, and an apply run under a minute. The agent reads the skill, its references and the workspace sources before it proposes anything.
- **A rejected preview is normal.** The board validates every preview in full. An agent corrects exactly what the error names and previews again, at most 2 more times, and never with a wider change; then it stops and reports the error codes and messages. If it stops, read the error, tell it what to change or fix the source it names, and ask it to try again. The count starts anew with your instruction. Nothing is written by a rejected preview.
- **Agents never perform the three direct human actions.** `po-handoff`, `design-start` and `dev-start` are done by a human in the board. An agent that needs one asks you to complete it there.
- **You confirm before anything is applied.** The agent shows the exact changes and applies the preview only after your confirmation in the host. The board has no second approval queue.
- **The agent cannot read everything.** `read_workspace` reads approved UTF-8 text under `knowledge/wiki/` and `knowledge/intake/`. The workspace manifest is not readable; `discover` reports the board identity ([details](troubleshooting.md#read_workspace-fails-with-path_not_approved)).

## Not tested

- Remote hosting, Cursor and other hosts.
- Codex with its TOML configuration file instead of `-c` overrides, and Claude Code in interactive mode.
- A host with a small tool-result limit.

Another host works when it supports Streamable HTTP MCP with a Bearer token. Treat configuration support and verified behavior as separate: record the host version and result when you try one.
