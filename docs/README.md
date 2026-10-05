# Documentation Index

This folder documents Prism's shared workflow and board, agent connections, and
optional application generation.

If you are not sure where to start, choose the path that matches your goal.

## Start Here By Audience

### I want a shared board in an existing or empty workspace

Start with the [README quickstart](../README.md#quickstart-a-shared-board-for-you-and-your-agents),
then [shared-board.md](shared-board.md) for adoption, participant access, the local
service, and standard MCP configuration, and [agent-hosts.md](agent-hosts.md) for what to
expect from Claude Code and Codex. When something fails, read
[troubleshooting.md](troubleshooting.md). [`SECURITY.md`](../SECURITY.md) describes what the
local service protects. Read [current-status.md](current-status.md) for the current
validation boundary.

### I want to install Prism, generate a project, and try it

Start here:

1. [getting-started.md](getting-started.md)
2. [questionnaire.md](questionnaire.md)
3. [generated-projects.md](generated-projects.md)
4. [wiki-visualization.md](wiki-visualization.md) for the local dashboard demo

### I already have a generated Prism project

Start here:

1. `README.md` inside the generated repository
2. `CONTEXT.md` inside the generated repository
3. [generated-projects.md](generated-projects.md)
4. [wiki-workflow.md](wiki-workflow.md)

### I want to understand the Prism model

Read these in order:

1. [prism-model.md](prism-model.md)
2. [wiki-workflow.md](wiki-workflow.md)
3. [ai-surfaces.md](ai-surfaces.md)

### I maintain the Prism template and CLI

Start here:

1. [maintainer-workflow.md](maintainer-workflow.md)
2. [current-status.md](current-status.md)
3. [questionnaire.md](questionnaire.md)

## Core Docs

These are the best pages for understanding Prism quickly.

| Document | Best for | Purpose |
|----------|----------|---------|
| [shared-board.md](shared-board.md) | Humans and agents sharing a workspace | Adopt the workflow, connect through MCP, and use supported human board actions |
| [agent-hosts.md](agent-hosts.md) | Anyone connecting Claude Code or Codex | Tested host versions, transport, the settings that matter, known limitations and what to expect, including the retry rule |
| [troubleshooting.md](troubleshooting.md) | Anyone whose setup or connection fails | Symptom, cause and fix for cloud-synced folders, a busy port, stale previews, upgraded grants, cursor errors, missing tools and the doctor checks |
| [getting-started.md](getting-started.md) | Builders and evaluators | Install Prism, generate a first sample, validate it, and enter the generated workflow |
| [generated-projects.md](generated-projects.md) | Generated-project users | What a generated repo contains and what is safe to do first |
| [prism-model.md](prism-model.md) | Evaluators and role leads | What Prism is, what problem it solves, and how the wiki-driven lifecycle works |
| [wiki-workflow.md](wiki-workflow.md) | PO, design, and dev | How the wiki lifecycle actions, read/query layer, evidence, and handoff flow behave |
| [wiki-visualization.md](wiki-visualization.md) | Evaluators and generated-project users | Run the synthetic TreasuryFlow demo and inspect the read-only previews for all nine lifecycle actions across Graph, Board, Platforms, and Guide |

## Supporting Reference Docs

Use these once you already understand the basic flow.

| Document | Best for | Purpose |
|----------|----------|---------|
| [questionnaire.md](questionnaire.md) | Builders and maintainers | Generation inputs, defaults, and maturity notes |
| [ai-surfaces.md](ai-surfaces.md) | Users comparing tool surfaces | How Claude, Codex, and Cursor surfaces are packaged and why some differences are intentional |
| [wiki-validation.md](wiki-validation.md) | Evaluators and maintainers | How the wiki usability layer is validated and what confidence boundaries apply |
| [current-status.md](current-status.md) | Evaluators and maintainers | Maturity, validation suites, board performance, sample status and safest evaluation routes |

## Maintainer Docs

These pages are about the template repository and Prism CLI rather than day-to-day work
inside a generated project.

| Document | Purpose |
|----------|---------|
| [prism-core-workflow-plan.md](prism-core-workflow-plan.md) | Core scope, contracts, human and agent entry paths, verification layers and deferred work |
| [maintainer-workflow.md](maintainer-workflow.md) | Template structure, CLI/template workflow, and validation guidance |
| [cli-release.md](cli-release.md) | Local CLI release preparation, wheel checks, and publication boundary |

## Acceptance Records

These pages record the evidence and limits of one delivery at the time it was written.

| Document | Purpose |
|----------|---------|
| [connected-core-acceptance.md](connected-core-acceptance.md) | The connected-core acceptance run: tests, actual-host evidence and remaining limits |
| [lifecycle-transitions-acceptance.md](lifecycle-transitions-acceptance.md) | Acceptance of the nine lifecycle actions through the read-only preview and agent-skill path |
| [board-transitions-acceptance.md](board-transitions-acceptance.md) | Local evidence and acceptance boundaries for the first Board handoff slice |
| [cli-v2-acceptance.md](cli-v2-acceptance.md) | CLI v2 acceptance evidence and the remaining release review boundary |
| [reviews/](reviews/) | Dated independent reviews and their provenance records |

## Related Root Files

- [`README.md`](../README.md) for the short product overview and the quickstart
- [`SECURITY.md`](../SECURITY.md) for the local threat model and how to report a vulnerability
- [`CHANGELOG.md`](../CHANGELOG.md) for user-visible changes
- [`AGENTS.md`](../AGENTS.md) for Codex maintainer guidance in this repo
- [`CLAUDE.md`](../CLAUDE.md) for Claude maintainer guidance in this repo
