# Documentation Index

This folder holds the main documentation for Prism itself and for the workflow embedded in
generated Prism repositories.

If you are not sure where to start, choose the path that matches your goal.

## Start Here By Audience

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
| [getting-started.md](getting-started.md) | Builders and evaluators | Install Prism, generate a first sample, validate it, and enter the generated workflow |
| [generated-projects.md](generated-projects.md) | Generated-project users | What a generated repo contains and what is safe to do first |
| [prism-model.md](prism-model.md) | Evaluators and role leads | What Prism is, what problem it solves, and how the wiki-driven lifecycle works |
| [wiki-workflow.md](wiki-workflow.md) | PO, design, and dev | How the wiki lifecycle actions, read/query layer, evidence, and handoff flow behave |
| [wiki-visualization.md](wiki-visualization.md) | Evaluators and generated-project users | Run the synthetic TreasuryFlow demo and inspect the copy-only PO handoff preview across Graph, Board, Platforms, and Guide |

## Supporting Reference Docs

Use these once you already understand the basic flow.

| Document | Best for | Purpose |
|----------|----------|---------|
| [questionnaire.md](questionnaire.md) | Builders and maintainers | Generation inputs, defaults, and maturity notes |
| [ai-surfaces.md](ai-surfaces.md) | Users comparing tool surfaces | How Claude, Codex, and Cursor surfaces are packaged and why some differences are intentional |
| [wiki-validation.md](wiki-validation.md) | Evaluators and maintainers | How the wiki usability layer was validated and what confidence boundaries apply today |
| [current-status.md](current-status.md) | Evaluators and maintainers | Current maturity, validated paths, and safest evaluation routes |

## Maintainer Docs

These pages are about the template repository and Prism CLI rather than day-to-day work
inside a generated project.

| Document | Purpose |
|----------|---------|
| [maintainer-workflow.md](maintainer-workflow.md) | Template structure, CLI/template workflow, and validation guidance |
| [questionnaire.md](questionnaire.md) | Generation inputs, defaults, and the current option-specific caveats maintainers need to track |
| [cli-release.md](cli-release.md) | Local CLI release preparation, wheel checks, and publication boundary |
| [cli-v2-acceptance.md](cli-v2-acceptance.md) | CLI v2 acceptance evidence and the remaining release review boundary |
| [board-transitions-acceptance.md](board-transitions-acceptance.md) | Local evidence and acceptance boundaries for Board transition implementation |

## Related Root Files

- [`README.md`](../README.md) for the short product overview and fastest entry path
- [`AGENTS.md`](../AGENTS.md) for Codex maintainer guidance in this repo
- [`CLAUDE.md`](../CLAUDE.md) for Claude maintainer guidance in this repo
