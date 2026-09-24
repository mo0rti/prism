# Prism: One spec. Every platform.

![Version](https://img.shields.io/badge/version-0.2.0-blue)
![Status](https://img.shields.io/badge/status-in%20development-2ea44f)
![Template Validation](https://github.com/mo0rti/prism/actions/workflows/template-validation.yml/badge.svg)
![Python](https://img.shields.io/badge/python-%3E%3D3.10-3776AB?logo=python&logoColor=white)
![Repo Type](https://img.shields.io/badge/repo-template%20%2B%20CLI-6f42c1)

![Prism](docs/media/prism.png)

Prism is a shared workflow and board for humans and agents. Product knowledge,
questions, evidence, and delivery state live in the repository's wiki. Application
template generation is an optional way to start a workspace.

It helps product and engineering teams:

- carry work through PO, design, and development using shared evidence and explicit handoffs
- connect coding agents through standard MCP and the same versioned Prism skills
- review and confirm supported human actions directly in the board
- optionally generate backend, web, Android, and iOS foundations

This repository contains Prism's CLI, workflow service, board, and application template.
It is the maintainer repository, not a workspace for running product lifecycle actions.

Start with the [shared board guide](docs/shared-board.md) to adopt the workflow in
an existing repository or an empty workspace. See [current status](docs/current-status.md)
for the implementation's acceptance boundary.

If you want to see Prism applied to a concrete product story, follow the
[local wiki visualization guide](docs/wiki-visualization.md). It builds a
synthetic TreasuryFlow fixture that is safe to regenerate for dashboard
inspection.

![Prism wiki visualization Graph view](docs/media/wiki-dashboard-graph.png)

_Graph view from the synthetic local TreasuryFlow fixture._

![Prism home screen](docs/media/prism-menu.png)

The Prism launcher provides workspace actions, generation, validation, and orientation.

## What Prism Generates

A Prism-generated repository can include:

- **Backend**: Spring Boot 4, Kotlin 2.2+, Java 21
- **User Web App**: Next.js + TypeScript
- **Admin Web Portal**: Next.js + TypeScript
- **Android**: Kotlin + Jetpack Compose
- **iOS**: Swift + SwiftUI

Every generated repository also includes:

- a living product wiki under `knowledge/wiki/`
- generated AI context for Claude, Codex, and Cursor
- lifecycle commands for PO, design, dev, and advisory review
- project docs, generators, and workflow wiring

## Quick Start

Install Prism from this checkout:

```bash
pip install -e .
```

To preview workflow adoption, first open a separate existing or newly created
workspace directory. Choose its display name and relevant scope. The current
scope identifiers remain the five platform IDs; selecting one does not generate
an application. Do not install the workflow into this maintainer checkout.

```bash
prism workflow install . --name "My workspace" --platform backend
```

Review the diff, then apply with the same inputs:

```bash
prism workflow install . --name "My workspace" --platform backend --apply
```

The [shared board guide](docs/shared-board.md)
covers participant access, starting the local service, and standard MCP setup.
For optional application generation, run `prism` and choose `New Project`.

![Prism guided project creation](docs/media/prism-new-project.png)

From the Prism home screen:

- choose `Doctor` to check prerequisites
- choose `New Project` to generate a sample repo
- choose `Presets` if you want to browse the recommended starting paths first

After generating a project:

1. open the generated repository
2. inspect `README.md`, `CONTEXT.md`, and `knowledge/wiki/SCHEMA.md`
3. initialize the workflow with:
   - Claude Code: `/setup-project`
   - Codex: `$setup-project`
   - Cursor: ask the agent to run `setup-project`
4. to enable the shared board and MCP writes, preview `prism workflow upgrade .`,
   then confirm with `prism workflow upgrade . --apply` and register participants
   as described in the [shared board guide](docs/shared-board.md).

For the full first-run path, read [docs/getting-started.md](docs/getting-started.md).

## Start Here By Goal

### I want a board for humans and coding agents

Read the [shared board guide](docs/shared-board.md), then the
[wiki workflow](docs/wiki-workflow.md). The local service shares one workspace
between the browser and standard MCP clients.

### I want to generate a project and evaluate Prism

Read these first:

1. [docs/getting-started.md](docs/getting-started.md)
2. [docs/questionnaire.md](docs/questionnaire.md)
3. [docs/generated-projects.md](docs/generated-projects.md)

### I already have a generated Prism project

Read these first:

1. `README.md` inside the generated repository
2. `CONTEXT.md` inside the generated repository
3. [docs/generated-projects.md](docs/generated-projects.md)
4. [docs/wiki-workflow.md](docs/wiki-workflow.md)

### I want to understand the Prism operating model

Read these in order:

1. [docs/prism-model.md](docs/prism-model.md)
2. [docs/wiki-workflow.md](docs/wiki-workflow.md)
3. [docs/ai-surfaces.md](docs/ai-surfaces.md)

### I want to maintain or improve Prism itself

Start with:

1. [docs/maintainer-workflow.md](docs/maintainer-workflow.md)
2. [docs/current-status.md](docs/current-status.md)
3. [docs/README.md](docs/README.md)

## Current Status

- Core workflow and human/agent board implementation follows the
  [approved plan](docs/prism-core-workflow-plan.md); current acceptance is recorded separately from sample builds.
- Application scaffolds remain partial. Generated web build checks are configured
  in CI; this does not establish runtime or deployment acceptance for the current changes.
- Apple Sign-In remains experimental.
- Core acceptance uses disposable neutral workspaces. Template changes also receive
  generated-output validation; sample behavior does not define the core workflow.

For the detailed maturity snapshot, read [docs/current-status.md](docs/current-status.md).

## Learn More

For the full documentation index, read [docs/README.md](docs/README.md).

## Related Repo Files

- [AGENTS.md](AGENTS.md) for Codex maintainer guidance in this repo
- [CLAUDE.md](CLAUDE.md) for Claude maintainer guidance in this repo
