# Prism: One spec. Every platform.

![Version](https://img.shields.io/badge/version-0.3.0-blue)
![PyPI](https://img.shields.io/pypi/v/prism-kit)
![Template Validation](https://github.com/mo0rti/prism/actions/workflows/template-validation.yml/badge.svg)
![Python](https://img.shields.io/badge/python-%3E%3D3.10-3776AB?logo=python&logoColor=white)
![Repo Type](https://img.shields.io/badge/repo-template%20%2B%20CLI-6f42c1)
![License](https://img.shields.io/badge/license-MIT-blue)

![Prism](https://raw.githubusercontent.com/mo0rti/prism/main/docs/media/prism.png)

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

Follow the [quickstart](https://github.com/mo0rti/prism/blob/main/README.md#quickstart-a-shared-board-for-you-and-your-agents) to adopt the
workflow in an existing repository or an empty workspace. The
[shared board guide](https://github.com/mo0rti/prism/blob/main/docs/shared-board.md) has the details, and
[current status](https://github.com/mo0rti/prism/blob/main/docs/current-status.md) records what is verified and what is open.

## Quickstart: a shared board for you and your agents

Prism runs on one computer. One local service per workspace serves the browser board and an MCP endpoint, so you and your coding agents work on the same wiki. Prism needs Python 3.10 or later; [uv](https://docs.astral.sh/uv/) installs one when none is present. Install it from PyPI as `prism-kit`, which provides the `prism` command:

```bash
uv tool install prism-kit
prism --version
```

`pipx install prism-kit` and `pip install prism-kit` work as well. If `prism` is not found after `uv tool install`, run `uv tool update-shell` and open a new terminal. To upgrade later, run `uv tool upgrade prism-kit`.

**Without a Python setup.** With Node.js 22 or later, the npm launcher runs the same CLI; it fetches uv and the matching `prism-kit` on first use:

```bash
npx @mortitech/prism --version
```

`npm install --global @mortitech/prism` installs it as the `prism` command. The rest of this page writes `prism <command>`.

**From source (contributors).** Clone the repository and install it in editable mode:

```bash
git clone https://github.com/mo0rti/prism.git
cd prism
pip install -e .
```

Run the remaining steps in a separate workspace folder, not in this maintainer checkout and not in a cloud-synced folder such as OneDrive.

**1. Add the workflow.** Use an empty folder or an existing repository. Choose a display name and, if you want, an app: `--app` takes one of the five generated app IDs (`backend`, `web-user-app`, `web-admin-portal`, `mobile-android`, `mobile-ios`) and registers it without generating an application. Without `--app` the workspace has no apps, and `prism app add` registers one later ([the workspace model](https://github.com/mo0rti/prism/blob/main/docs/workspace-model.md) covers apps, repositories and `prism app list`). The first command previews every file. The second asks you to confirm before it writes (`--apply --yes` skips the question for automation).

```bash
cd path/to/your-workspace
prism workflow install . --name "My workspace" --app backend
prism workflow install . --name "My workspace" --app backend --apply
```

**2. Check readiness.** The "Shared board" section lists what needs attention, each with a `Fix:` line. A warning that no grant exists yet is expected at this point.

```bash
prism doctor --workspace .
```

**3. Register a person and an agent.** Each command prints JSON whose `token` appears once. Keep tokens private and out of files and prompts. A grant without `--write` is read-only.

```bash
prism board grant "Product owner" --kind human --write --path .
prism board grant "Coding agent" --kind agent --write --path .
```

Put the agent's token in an environment variable before you start the agent host:

```bash
export PRISM_BOARD_TOKEN="<the agent's token>"      # macOS, Linux, Git Bash
$env:PRISM_BOARD_TOKEN = "<the agent's token>"      # PowerShell
```

**4. Start the board.**

```bash
prism board serve . --port 8765
```

It prints the board URL, the MCP endpoint (`http://127.0.0.1:8765/mcp`) and a hint for issuing another grant, then opens your browser (`--no-open` skips that). Sign in with the human token. Press Ctrl+C to stop. The service listens on loopback only.

**5. Connect Claude Code and Codex.** Both use their standard Streamable HTTP MCP configuration with that endpoint and `PRISM_BOARD_TOKEN`. The exact entries are in [Connect an agent host](https://github.com/mo0rti/prism/blob/main/docs/shared-board.md#connect-an-agent-host). Give each host its own grant, and start the host from a shell where the variable is set. [Agent hosts](https://github.com/mo0rti/prism/blob/main/docs/agent-hosts.md) lists the tested versions, settings and known limitations.

**6. Run a first journey.**

1. Ask the agent to run Prism's `setup-project` skill. Setup is an interview that writes the product context directly into the workspace, so it does not go through the board.
2. Create a folder such as `knowledge/intake/pending/my-first-feature/` and put your brief in it as a Markdown file, using `knowledge/intake/pending/PO_BRIEF_TEMPLATE.md` as a guide. Then ask the agent: "Use Prism's PO intake skill to refine the pending brief." The agent shows the exact file changes, you confirm them in the agent, and it applies them. A new feature appears on the board.
3. In the board, move the feature with `po-handoff` (drag its card or use its action control). Review the evidence and exact changes, acknowledge them and confirm. The board offers the same human action for `design-start` and `dev-start`. The remaining steps run through the agent's skills.

If a step fails, [docs/troubleshooting.md](https://github.com/mo0rti/prism/blob/main/docs/troubleshooting.md) lists the symptom, cause and fix for the common cases. The [shared board guide](https://github.com/mo0rti/prism/blob/main/docs/shared-board.md) covers every command, the MCP tools and recovery of interrupted operations, and [SECURITY.md](https://github.com/mo0rti/prism/blob/main/SECURITY.md) describes what the local service protects.

![Prism wiki visualization Graph view](https://raw.githubusercontent.com/mo0rti/prism/main/docs/media/wiki-dashboard-graph.png)

_Graph view from the synthetic local TreasuryFlow fixture._

To explore a populated example first, follow the [local wiki visualization guide](https://github.com/mo0rti/prism/blob/main/docs/wiki-visualization.md). It builds a synthetic TreasuryFlow fixture that is safe to regenerate.

## Optional: generate an application

Application generation is separate from the shared board. Run `prism` for the home screen, or `prism new` for the guided flow.

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

![Prism home screen](https://raw.githubusercontent.com/mo0rti/prism/main/docs/media/prism-menu.png)

From the Prism home screen:

- choose `Doctor` to check prerequisites
- choose `New Project` to generate a sample repo
- choose `Browse Presets` if you want to browse the recommended starting paths first

![Prism guided project creation](https://raw.githubusercontent.com/mo0rti/prism/main/docs/media/prism-new-project.png)

After generating a project:

1. open the generated repository
2. inspect `README.md`, `CONTEXT.md`, `knowledge/wiki/SCHEMA.md` and `knowledge/wiki/LIFECYCLE.md`
3. initialize the workflow with:
   - Claude Code: `/setup-project`
   - Codex: `$setup-project`
   - Cursor: ask the agent to run `setup-project`
4. to enable the shared board and MCP writes, preview `prism workflow upgrade .`,
   then confirm with `prism workflow upgrade . --apply` and register participants
   as in the quickstart above.

For the full first-run path, read [docs/getting-started.md](https://github.com/mo0rti/prism/blob/main/docs/getting-started.md).

## Start Here By Goal

### I want a board for humans and coding agents

Read the [shared board guide](https://github.com/mo0rti/prism/blob/main/docs/shared-board.md), then the
[wiki workflow](https://github.com/mo0rti/prism/blob/main/docs/wiki-workflow.md). The local service shares one workspace
between the browser and standard MCP clients. [The workspace model](https://github.com/mo0rti/prism/blob/main/docs/workspace-model.md)
explains how a workspace declares its apps and repositories.

### I want to generate a project and evaluate Prism

Read these first:

1. [docs/getting-started.md](https://github.com/mo0rti/prism/blob/main/docs/getting-started.md)
2. [docs/questionnaire.md](https://github.com/mo0rti/prism/blob/main/docs/questionnaire.md)
3. [docs/generated-projects.md](https://github.com/mo0rti/prism/blob/main/docs/generated-projects.md)

### I already have a generated Prism project

Read these first:

1. `README.md` inside the generated repository
2. `CONTEXT.md` inside the generated repository
3. [docs/generated-projects.md](https://github.com/mo0rti/prism/blob/main/docs/generated-projects.md)
4. [docs/wiki-workflow.md](https://github.com/mo0rti/prism/blob/main/docs/wiki-workflow.md)

### I want to understand the Prism operating model

Read these in order:

1. [docs/prism-model.md](https://github.com/mo0rti/prism/blob/main/docs/prism-model.md)
2. [docs/wiki-workflow.md](https://github.com/mo0rti/prism/blob/main/docs/wiki-workflow.md)
3. [docs/ai-surfaces.md](https://github.com/mo0rti/prism/blob/main/docs/ai-surfaces.md)

### I want to maintain or improve Prism itself

Start with:

1. [docs/maintainer-workflow.md](https://github.com/mo0rti/prism/blob/main/docs/maintainer-workflow.md)
2. [docs/current-status.md](https://github.com/mo0rti/prism/blob/main/docs/current-status.md)
3. [docs/README.md](https://github.com/mo0rti/prism/blob/main/docs/README.md)

## Current Status

- The workflow, the shared board, the MCP tool contract and the human board actions are implemented and tested; the [plan](https://github.com/mo0rti/prism/blob/main/docs/prism-core-workflow-plan.md) states their scope and contracts.
- Prism 0.3.0 is released: `prism-kit` on [PyPI](https://pypi.org/project/prism-kit/) and the [GitHub release](https://github.com/mo0rti/prism/releases/tag/v0.3.0) with checksums.
- Application samples: backend, Android and web are verified locally and in CI, and the iOS sample is built and tested by the macOS CI job. Live Cloudflare and Azure deployments are unverified, and Apple Sign-In is experimental.
- Core acceptance uses disposable neutral workspaces. Sample behavior does not define the core workflow.
- Prism is released under the MIT license and published to PyPI as `prism-kit`, with the `@mortitech/prism` launcher on npm. The [changelog](https://github.com/mo0rti/prism/blob/main/CHANGELOG.md) lists what each version contains.

For the detailed status, read [docs/current-status.md](https://github.com/mo0rti/prism/blob/main/docs/current-status.md).

## Learn More

For the full documentation index, read [docs/README.md](https://github.com/mo0rti/prism/blob/main/docs/README.md).

## Related Repo Files

- [AGENTS.md](https://github.com/mo0rti/prism/blob/main/AGENTS.md) for Codex maintainer guidance in this repo
- [CLAUDE.md](https://github.com/mo0rti/prism/blob/main/CLAUDE.md) for Claude maintainer guidance in this repo

## License

Prism is released under the [MIT license](https://github.com/mo0rti/prism/blob/main/LICENSE), copyright 2026 Mortitech. The vendored force-graph library keeps its own MIT license; see [third-party notices](https://github.com/mo0rti/prism/blob/main/THIRD_PARTY_NOTICES.md).
