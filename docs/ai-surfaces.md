# AI Surfaces

Generated Prism projects support multiple AI tools, but the surfaces are not packaged the
same way in each tool.

This page explains the packaging model so the differences are understandable instead of
looking accidental.

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

## Current Surface Model

Current practical status:

- wiki usability parity is shipped in both tools
- core lifecycle parity is shipped in both tools
- the main remaining smaller review area is the set of Claude-only deep technical skills

### Claude

Claude generated projects use:

- slash commands for workflow operations under `.claude/commands/`
- skills for deeper technical or platform-specific guidance under `.claude/skills/`

This makes Claude command-first for workflow orchestration.

### Codex

Codex generated projects use:

- skills under `.agents/skills/` as the main structured surface

This makes Codex skill-first for workflow orchestration.

## What Is Shared

The following areas are now available in structured form across both tools:

- project setup
- advisory board review
- lifecycle operations for PO, design, and dev handoff
- feature status and wiki health checks
- wiki read/query operations
- backend endpoint work (at different abstraction levels, see below)
- security/auth guidance
- testing and platform-convention guidance

The packaging differs, but the major workflow layer is now available in both tools.

## What Is Intentional

### Claude is command-first for workflow packaging

Claude exposes the Prism workflow mainly through slash commands such as:

- `/setup-project`
- `/po-intake`
- `/design-handoff`
- `/dev-done`
- `/feature-status`
- `/wiki-show`

That is an intentional packaging choice, not a parity defect.

### Codex is skill-first for workflow packaging

Codex exposes those same workflow operations as skills such as:

- `$setup-project`
- `$po-intake`
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

## Same capability, different packaging

Several important operations now exist in both tools but under different mechanisms:

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
- `wiki-platform`

This is acceptable as long as the generated-project guidance stays explicit about how to
invoke them in each tool.

## Different abstraction levels

Some concepts exist at different abstraction levels across tools.

The clearest example is endpoint work:

- Claude command: `add-endpoint`
- Codex skill: `endpoint`

These are not clean one-to-one equivalents.

- `add-endpoint` is a broader workflow command spanning OpenAPI, client generation,
  backend implementation, and downstream consumers
- `endpoint` is a backend-oriented implementation skill

So this is a scope difference, not just a naming mismatch.

## What Still Needs Deliberate Review

The remaining smaller question set is around Claude-only deep technical skills such as:

- `test-endpoint`
- `database-migrations`
- `jpa-kotlin-patterns`
- `migration`
- `code-review`

These are not necessarily bugs, but they should be treated as conscious product decisions:

- add Codex counterparts
- keep them Claude-only
- or document that broader Codex skills already cover the need sufficiently

## Practical Reading Guidance

When exploring a generated project:

- use the generated `CLAUDE.md` to understand the Claude command surface
- use the generated `AGENTS.md` to understand the Codex skill surface
- use the project wiki as the product source of truth
- use `WIKI_REPORT.md` as an orientation artifact, not authority

## Related Docs

- [prism-model.md](prism-model.md)
- [wiki-workflow.md](wiki-workflow.md)
- [wiki-validation.md](wiki-validation.md)
- [generated-projects.md](generated-projects.md)
