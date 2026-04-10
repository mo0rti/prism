# Prism: One spec. Every platform.

![Prism](docs/media/prism.png)

Prism is a production-grade, AI-ready multi-platform system generator with a living product
wiki.

It scaffolds a monorepo and gives every AI-assisted role the same product source of truth,
so PO, design, and implementation work stay aligned as the product evolves.

This repository is the template itself, not a generated project.

## What This Repo Gives You

A generated project can include:

- **Backend**: Spring Boot 4, Kotlin 2.2+, Java 21
- **User Web App**: Next.js + TypeScript
- **Admin Web Portal**: Next.js + TypeScript
- **Android**: Kotlin + Jetpack Compose
- **iOS**: Swift + SwiftUI

Every generated project also includes:

- a living product wiki under `knowledge/wiki/`
- AI context for Claude, Codex, and Cursor
- lifecycle operations for PO, design, dev, and advisory review
- generators, docs, and workflow wiring inside the generated repo

## Who This Is For

Prism is useful for three main audiences:

- **Builders and evaluators** who want to generate a project and start exploring the workflow
- **POs, designers, and developers** who want AI agents to share one evolving product spec
- **Maintainers and contributors** who want to improve the template itself

## Start Here By Goal

### I want to generate a project and try Prism

1. Read [docs/getting-started.md](docs/getting-started.md).
2. Skim [docs/questionnaire.md](docs/questionnaire.md).
3. Generate a focused sample with `copier copy --trust`.
4. In the generated project, run:
   - Claude Code: `/setup-project`
   - Codex: `$setup-project`
   - Cursor: ask the agent to run `setup-project`
5. Then read:
   - [docs/generated-projects.md](docs/generated-projects.md)
   - [docs/prism-model.md](docs/prism-model.md)
   - [docs/wiki-workflow.md](docs/wiki-workflow.md)

### I want to understand how the Prism workflow works

Read these in order:

1. [docs/prism-model.md](docs/prism-model.md)
2. [docs/wiki-workflow.md](docs/wiki-workflow.md)
3. [docs/ai-surfaces.md](docs/ai-surfaces.md)
4. [docs/wiki-validation.md](docs/wiki-validation.md)

### I want to maintain or improve the template

Start with:

1. [docs/maintainer-workflow.md](docs/maintainer-workflow.md)
2. [docs/current-status.md](docs/current-status.md)
3. [docs/questionnaire.md](docs/questionnaire.md)
4. [docs/README.md](docs/README.md)

## How Prism Works

Prism solves the context-broadcasting problem in AI-assisted product development.

Instead of forcing each AI agent to rediscover the product from scratch, generated projects
use one shared wiki under `knowledge/wiki/` as the coordination layer.

The basic flow is:

1. **PO** adds raw notes and runs `po-intake`
2. **Designer** adds design artifacts and runs `design-intake`
3. **Developer** reads the wiki and platform requirements before implementation
4. **Advisory board** reviews domain-sensitive features when needed

The wiki becomes the persistent product memory that every role reads before making changes.

For the full model, read [docs/prism-model.md](docs/prism-model.md).

## Generated-Project Workflow

After generating a project, the practical first-use sequence is:

1. confirm the selected platform directories exist
2. inspect `CONTEXT.md` and `knowledge/wiki/SCHEMA.md`
3. initialize the wiki with `setup-project`
4. use `feature-status` to generate `knowledge/wiki/WIKI_REPORT.md` when needed
5. use the read/query layer for drill-down:
   - `prep-sprint`
   - `wiki-show`
   - `wiki-blockers`
   - `wiki-query`
   - `wiki-owner`
   - `wiki-platform`
6. use lifecycle commands when changing state:
   - `po-intake`
   - `po-clarify`
   - `po-handoff`
   - `design-intake`
   - `design-clarify`
   - `design-handoff`
   - `dev-done`
   - `ask`

For the complete behavior and examples, read [docs/wiki-workflow.md](docs/wiki-workflow.md).

## Commands Reference

Claude Code slash commands (`/cmd`), Codex skills (`$cmd`), and Cursor prompts all map to
the same generated-project workflow operations.

The most important generated-project command groups are:

- **Orient / navigation**
  - `feature-status`
  - `prep-sprint`
  - `wiki-show`
  - `wiki-blockers`
  - `wiki-query`
  - `wiki-owner`
  - `wiki-platform`
- **Lifecycle / write**
  - `setup-project`
  - `po-intake`
  - `po-clarify`
  - `po-handoff`
  - `design-intake`
  - `design-clarify`
  - `design-handoff`
  - `dev-done`
  - `ask`
- **Audit / review**
  - `board-review`
  - `lint-wiki`
  - `audit-feature`
- **Coding utilities**
  - `add-endpoint`
  - `generate-clients`
  - `document-entity`

Representative cross-tool mapping:

| Role | Claude Code | Codex | Purpose |
|------|-------------|-------|---------|
| All | `/setup-project` | `$setup-project` | One-time project initialization |
| PO | `/po-intake [folder]` | `$po-intake [folder]` | Process raw notes into feature specs |
| PO | `/po-clarify` | `$po-clarify` | Answer open questions assigned to PO |
| PO | `/po-handoff [F-XXX]` | `$po-handoff [F-XXX]` | Hand off a feature to design |
| Designer | `/design-intake [F-XXX] [folder]` | `$design-intake [F-XXX] [folder]` | Attach design artifacts |
| Designer | `/design-clarify` | `$design-clarify` | Answer open design questions |
| Designer | `/design-handoff [F-XXX]` | `$design-handoff [F-XXX]` | Hand off a feature to dev |
| Dev | `/prep-sprint` | `$prep-sprint` | Show what is ready to build |
| Dev | `/dev-done [F-XXX]` | `$dev-done [F-XXX]` | Mark a feature as shipped |
| Board | `/board-review [F-XXX]` | `$board-review [F-XXX]` | Domain expert feature review |
| Shared | `/feature-status` | `$feature-status` | Full pipeline view and orientation report |
| Shared | `/wiki-show [F-XXX]` | `$wiki-show [F-XXX]` | Assemble focused feature context |
| Shared | `/wiki-query "text"` | `$wiki-query "text"` | Search across the wiki |
| Shared | `/ask [F-XXX] "q" --to po\|designer\|dev` | `$ask [F-XXX] "q" --to po\|designer\|dev` | Route a question |
| Shared | `/audit-feature [F-XXX]` | `$audit-feature [F-XXX]` | Cross-check spec vs. source intake |

For the full grouped command surface, including read/query tools, audit behavior, and
coding utilities, read [docs/generated-projects.md](docs/generated-projects.md).

## Current Status

- Backend, Android, and iOS are the stronger paths today.
- User web app and admin web portal generate real slices and pass install/build smoke
  checks, but still need live Cloudflare deployment validation.
- Apple Sign-In remains experimental.
- The safest maintainer workflow is explicit sample generation plus
  `./scripts/validate-template.ps1`.

For the detailed maturity snapshot, read [docs/current-status.md](docs/current-status.md).

## Documentation Map

### Core journey docs

| Document | Purpose |
|----------|---------|
| [docs/getting-started.md](docs/getting-started.md) | Prerequisites, generation commands, and first validation steps |
| [docs/generated-projects.md](docs/generated-projects.md) | What generated repositories include and how the generated workflow is surfaced |
| [docs/prism-model.md](docs/prism-model.md) | What Prism is, the problems it solves, and the role/lifecycle model |
| [docs/wiki-workflow.md](docs/wiki-workflow.md) | How the product wiki works, how `WIKI_REPORT.md` fits, and how the read/query layer behaves |

### Supporting reference docs

| Document | Purpose |
|----------|---------|
| [docs/questionnaire.md](docs/questionnaire.md) | Copier inputs, defaults, and maturity notes |
| [docs/ai-surfaces.md](docs/ai-surfaces.md) | How Claude and Codex surfaces are packaged and what differences are intentional |
| [docs/wiki-validation.md](docs/wiki-validation.md) | How the wiki layer was validated and what confidence applies today |
| [docs/current-status.md](docs/current-status.md) | Template maturity and recommended evaluation paths |
| [docs/maintainer-workflow.md](docs/maintainer-workflow.md) | Template-repo structure and maintainer workflow |
| [docs/README.md](docs/README.md) | Full documentation index |

## Related Repo Files

- [AGENTS.md](AGENTS.md) for Codex maintainer guidance in this repo
- [CLAUDE.md](CLAUDE.md) for Claude maintainer guidance in this repo
