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
- the backend and platform guidance skills that exist in both tools carry the same text;
  some deeper backend skills and commands exist only on the Claude side

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
| Cursor | `AGENTS.md` at the root and in subfolders, and `.cursor/rules/*.mdc`. | Nothing: Cursor reads `AGENTS.md` itself. The rules scope stack facts by `globs`, and none of them repeats or references `AGENTS.md`. |

Sources: Claude Code [memory and imports](https://code.claude.com/docs/en/memory), the Codex [AGENTS.md guide](https://developers.openai.com/codex/guides/agents-md) and the Cursor [rules documentation](https://cursor.com/docs/context/rules).

There is no `CONTEXT.md`. The human overview is the generated `README.md`, the rules are in `AGENTS.md`, and the template-owned `docs/` pages are listed in the "Project docs" group of `knowledge/wiki/index.md`. The skills exist in several layouts (`.claude/` and `.agents/`) that cannot import each other, so they are generated from one source (see below). The repository's `sync-ai-context` skill covers the remaining manual checks: the Cursor stack facts against the platform guidance, and the root layer of this repository.

## One Source Of Skills

Each skill, command and Cursor rule is written once, in `template-skills/<name>/skill.md` of this repository, and `scripts/build-skill-layers.py` renders every layer file under `template/` from it. [maintainer-workflow.md](maintainer-workflow.md#skill-sources) describes the source format. The layers follow how each tool discovers its guidance:

| Tool | Where it looks | What Prism generates there |
|------|----------------|----------------------------|
| Claude Code | `.claude/commands/<name>.md` and `.claude/skills/<name>/SKILL.md`. Custom commands have been merged into skills: both create `/name`, a skill folder can carry supporting files, and every front matter field is optional (`description` is recommended). | A command file without front matter, so Claude Code does not invoke it on its own, and a skill with `name`, `description` and, where the skill needs them, `argument-hint`, `disable-model-invocation`, `user-invocable` and `allowed-tools`. |
| Codex | `.agents/skills/<name>/SKILL.md`, which needs `name` and `description`, and an optional `agents/openai.yaml` for the interface and the `allow_implicit_invocation` policy. | `SKILL.md` with `name` and `description`, and an `openai.yaml` with `display_name`, `short_description`, `default_prompt` and the policy, for every skill. |
| Cursor | `AGENTS.md`, `.cursor/rules/*.mdc` with `description`, `globs` and `alwaysApply`, and skills from `.agents/skills/` and `.claude/skills/`. | Rules with a `description` and either `globs` or `alwaysApply: false`, which scope stack facts and describe the board review; no rule repeats `AGENTS.md`. |

Sources: Claude Code [skills and commands](https://code.claude.com/docs/en/skills), the Codex [skills guide](https://developers.openai.com/codex/skills), and the Cursor [rules](https://cursor.com/docs/context/rules) and [skills](https://cursor.com/docs/context/skills) documentation.

Cursor reads `AGENTS.md` and loads both skill folders itself, so the always-on rule `project.mdc`, whose only content was `@AGENTS.md`, does not exist: it would load `AGENTS.md` twice.

A workflow skill that ships as a Codex skill and a Claude command has one body. The layers differ in the invocation (`$name` in Codex, `/name` in Claude Code) and in the few host-specific lines the source marks. A skill that exists in only some layers is a conscious choice, listed under [What Still Needs Deliberate Review](#what-still-needs-deliberate-review).

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
- deployment (worked examples for the backend and web apps; the same skill, with the same reference files, in `.claude/skills/` and `.agents/skills/`)

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
