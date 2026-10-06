# AI Surfaces

Prism's connected workflow exposes one standard MCP tool contract and canonical,
versioned skills to compatible agent hosts. See the [shared board guide](shared-board.md)
for configuration and the [current status](current-status.md) for runtime evidence.
It does not require a custom workflow connector per coding agent.

Generated projects also retain local Claude commands, Codex skills and Cursor
guidance. The remainder of this page describes that direct-file compatibility
path and its intentional packaging differences. Custom local skill edits stay
on that path; they do not redefine the server's pinned workflow contract.

## Short Version

The practical status is:

- wiki read/query guidance is present in both generated surfaces
- the nine core lifecycle actions are present in both generated surfaces
- the backend production guidance surface is deeper on the Claude side, while
  Codex is intentionally narrower and more implementation-focused

The important framing is:

- Claude is command-first for workflow operations
- Codex is skill-first for workflow operations
- packaging differences are expected
- the real question is whether the generated-project guidance exposes usable capabilities in
  each tool

## Important Framing

Comparing `template/.claude/commands/` directly to `template/.agents/skills/` is not
enough.

Claude has two user-facing layers:

- slash commands
- skills

Codex uses skills as its main structured surface.

So the real comparison is not:

- "does every Claude command have a Codex skill with the same name?"

The real comparison is:

- does the generated-project guidance advertise usable capabilities in each tool?
- are the important workflow operations available in structured form?
- are the remaining differences intentional?

## What This Means In Practice

If you are using a generated project:

- use the generated `AGENTS.md` for the rules every tool follows and the operation names; Claude Code
  loads it through `CLAUDE.md`, which imports it with `@AGENTS.md`
- invoke an operation as `/name` in Claude Code, `$name` in Codex, or by asking the agent to run it in
  Cursor; the root `README.md` lists the operations by tool
- use the project wiki as the product source of truth
- use `WIKI_REPORT.md` as an orientation artifact, not authority

If a capability exists in both tools, it may still be packaged differently.

That is normal in Prism.

## Current Surface Model

### Claude

Claude generated projects use:

- slash commands for workflow operations under `.claude/commands/`
- skills for deeper technical or platform-specific guidance under `.claude/skills/`

This makes Claude command-first for workflow orchestration.

### Codex

Codex generated projects use:

- skills under `.agents/skills/` as the main structured surface

This makes Codex skill-first for workflow orchestration.

## One Source Of Instructions

A generated workspace states each rule once. How each tool loads instructions decides the layout:

| Tool | What it loads | What follows |
|------|---------------|--------------|
| Claude Code | `CLAUDE.md`, which expands `@path` imports relative to the file and loads them at launch. A folder's `CLAUDE.md` loads when Claude works in that folder. | Every `CLAUDE.md` is `@AGENTS.md` plus Claude Code notes no other tool shares, such as the platform skills and commands. |
| Codex | `AGENTS.md` from the repository root down to the working directory, concatenated, up to a size limit of 32 KiB. It has no import. | `AGENTS.md` holds the rules, so the root file and the largest platform file together stay under the limit. |
| Cursor | `AGENTS.md` at the root and in subfolders, and `.cursor/rules/*.mdc`. A rule may reference a file with `@filename`. | `project.mdc` is the one always-on rule and references `@AGENTS.md`. The other rules scope stack facts by `globs`. |

Sources: Claude Code [memory and imports](https://code.claude.com/docs/en/memory), the Codex [AGENTS.md guide](https://developers.openai.com/codex/guides/agents-md) and the Cursor [rules documentation](https://cursor.com/docs/context/rules).

There is no `CONTEXT.md`. The human overview is the generated `README.md`, the rules are in `AGENTS.md`, and the template-owned `docs/` pages are listed in the "Project docs" group of `knowledge/wiki/index.md`. The skills still exist in two packagings (`.claude/` and `.agents/`) that cannot import each other, so keeping them aligned is a manual check; the repository's `sync-ai-context` skill covers that, the Cursor scoped rules and the import layout.

## What Is Shared

The following areas are available in structured form across both tools:

- project setup
- advisory board review
- lifecycle operations for PO, design, and dev handoff
- one clarify skill per owner: `po-clarify`, `design-clarify` and `dev-clarify`
- feature status and wiki health checks
- wiki read/query operations
- backend endpoint work at different abstraction levels
- security/auth guidance
- testing and platform-convention guidance

The packaging differs, but the major workflow layer is available in both tools.

## What Is Intentional

### Claude is command-first for workflow packaging

Claude exposes the Prism workflow mainly through slash commands such as:

- `/setup-project`
- `/po-intake`
- `/dev-clarify`
- `/design-handoff`
- `/dev-done`
- `/feature-status`
- `/wiki-show`

That is an intentional packaging choice, not a parity defect.

### Codex is skill-first for workflow packaging

Codex exposes those same workflow operations as skills such as:

- `$setup-project`
- `$po-intake`
- `$dev-clarify`
- `$design-handoff`
- `$dev-done`
- `$feature-status`
- `$wiki-show`

That is also intentional.

### Deep technical guidance is skill-oriented in both tools

Platform and discipline helpers are primarily skills rather than workflow commands.

Examples:

- Android conventions
- iOS conventions
- endpoint work
- error handling
- security/auth
- testing guidance

## Same Capability, Different Packaging

Several important operations exist in both tools but under different mechanisms:

- Claude: slash command
- Codex: skill

Examples:

- `feature-status`
- `setup-project`
- `generate-clients`
- `lint-wiki`
- `prep-sprint`
- `wiki-show`
- `wiki-blockers`
- `wiki-query`
- `wiki-owner`
- `wiki-app`
- `verify-pages`

This is acceptable as long as the generated-project guidance stays explicit about how to
invoke them in each tool.

## Different Abstraction Levels

Some concepts exist at different abstraction levels across tools.

The clearest example is backend endpoint work:

- Claude command: `add-endpoint`
- Claude reference skill: `backend-feature-delivery`
- Codex skill: `endpoint`

These are not clean one-to-one equivalents.

- `add-endpoint` is a broader workflow command spanning OpenAPI, client generation,
  backend implementation, and downstream consumers
- `backend-feature-delivery` is Claude-side reference guidance for the
  contract-first backend delivery flow
- `endpoint` is a Codex backend implementation skill that follows the same
  contract-first order for backend endpoint changes

So this is a scope difference, not just a naming mismatch.

## What Still Needs Deliberate Review

The remaining deliberate packaging question set is around Claude-only deep technical skills such as:

- `test-endpoint`
- `observability-and-telemetry`
- `authorization-rules`
- `external-integrations-and-resilience`
- `auditing-and-actor-context`
- `performance-and-query-shaping`
- `caching-strategy`
- `migration-conventions`
- `jpa-kotlin-patterns`
- `create-migration` (Claude command)
- `add-integration` (Claude command)
- `review-query` (Claude command)
- `review-security-surface` (Claude command)
- `debug-prod-issue` (Claude command)
- `code-review`

These are not necessarily bugs, but they should be treated as conscious product decisions:

- add Codex counterparts
- keep them Claude-only
- or document that broader Codex skills already cover the need sufficiently

## Practical Reading Guidance

When you are orienting in a generated project:

1. read the generated `README.md`
2. use the generated `AGENTS.md` for the rules and the invocation of each tool
3. use the wiki and `WIKI_REPORT.md` to understand product state
4. use this page only when you need to understand why Claude and Codex surfaces differ

## What To Read Next

- [generated-projects.md](generated-projects.md) for the generated-repo structure and command groups
- [wiki-workflow.md](wiki-workflow.md) for the wiki lifecycle and read/query behavior
- [prism-model.md](prism-model.md) for the overall Prism workflow model
- [wiki-validation.md](wiki-validation.md) for validation and confidence boundaries
