# Generated Projects

Generated Prism repositories include more than application code.

They also include:

- project documentation
- AI context for multiple tools
- the product wiki and lifecycle wiring
- generators and workflow scaffolding inside the generated repo

This page answers two questions:

1. what do I have after Prism generation?
2. how do I work inside the generated project?

## What You Get

Generated projects include:

- a generated `README.md`
- a generated `CONTEXT.md` as the root AI context anchor
- a required `knowledge/` tree with raw intake and the living product wiki
- platform-specific docs under `docs/`, `backend/docs/`, `mobile-android/docs/`,
  `mobile-ios/docs/`, `web-user-app/docs/`, and `web-admin-portal/docs/`
- generated AI context files such as `AGENTS.md` and `CLAUDE.md`
- GitHub workflow files
- Hygen generators under `_templates/`
- deployment docs such as `docs/deployment/cloudflare-setup.md` when web platforms are
  selected

Treat those outputs as part of the product, not as disposable scaffolding.

## First-Time Use

The first-run path lives in [getting-started.md](getting-started.md).

What matters here is the generated-project operating model:

- the repository already contains the wiki skeleton
- `setup-project` initializes the project-specific advisory board state
- after that, the read/query layer and lifecycle commands become the main way you work with Prism

Initialize the wiki with:

- Claude Code: `/setup-project`
- Codex: `$setup-project`
- Cursor: ask the agent to run `setup-project`

That setup flow creates the advisory board in `knowledge/wiki/advisory/BOARD.md` and
prepares the wiki for `po-intake`, `design-intake`, and the rest of the lifecycle.

## How To Read The Generated Repo

The most important generated areas are:

- root `README.md` for the generated repo overview
- root `CONTEXT.md` for AI orientation
- `knowledge/intake/` for raw human input and workflow state
- `knowledge/wiki/` for structured product knowledge
- platform-specific docs and source trees for implementation

If you are trying to understand the product state, the wiki matters more than the code
tree.

If you are trying to understand the generated implementation surface, read the generated
docs and platform slices together.

## AI Agent Surfaces

Generated projects include agent context for Claude, Codex, and Cursor.

Invocation model:

- Claude Code uses slash commands under `.claude/commands/`
- Codex uses skills under `.agents/skills/` and invokes the structured workflow surface
  with a `$` prefix
- Cursor users ask the agent to run the same named operations

For the broader model behind these surfaces, see:

- [prism-model.md](prism-model.md)
- [wiki-workflow.md](wiki-workflow.md)
- [ai-surfaces.md](ai-surfaces.md)

## What Is Safe To Run First

The most important operational distinction is:

- some commands are read-oriented and safe for navigation
- some are review tools that may write reports or logs without changing lifecycle state
- others change lifecycle or wiki state

Start with the read-oriented layer first, then use the review tools when you want explicit
health or audit output.

Cursor does not use the same slash or `$` invocation syntax. In practice, Cursor users ask
the agent to run the same named operation.

### Orient / read-only

| Role | Claude Code | Codex | Purpose |
|------|-------------|-------|---------|
| Dev | `/prep-sprint` | `$prep-sprint` | Show what is ready to build |
| Shared | `/feature-status` | `$feature-status` | Full pipeline view and refresh of the generated orientation report |
| Shared | `/wiki-show F-XXX` | `$wiki-show F-XXX` | Assemble focused feature context from linked wiki files |
| Shared | `/wiki-blockers` | `$wiki-blockers` | Show blockers using the canonical blocker categories |
| Shared | `/wiki-query "text"` | `$wiki-query "text"` | Retrieval-assisted search across the wiki |
| Shared | `/wiki-owner po\|designer\|dev` | `$wiki-owner po\|designer\|dev` | Show pending work and stale items for one owner role |
| Shared | `/wiki-platform <platform-id>` | `$wiki-platform <platform-id>` | Show the active feature queue for one platform |

Recommended first use:

1. `feature-status`
2. `prep-sprint` if you are a developer
3. `wiki-show` or `wiki-query` for focused drill-down

### Lifecycle / write

| Role | Claude Code | Codex | Purpose |
|------|-------------|-------|---------|
| Shared | `/setup-project` | `$setup-project` | One-time project initialization that interviews you and builds the advisory board |
| PO | `/po-intake [folder]` | `$po-intake [folder]` | Process raw PO notes into feature specs |
| PO | `/po-clarify` | `$po-clarify` | Answer open questions assigned to PO |
| PO | `/po-handoff [F-XXX]` | `$po-handoff [F-XXX]` | Hand off a feature to design |
| Designer | `/design-intake [F-XXX] [folder]` | `$design-intake [F-XXX] [folder]` | Attach design artifacts to a feature |
| Designer | `/design-clarify` | `$design-clarify` | Answer open design questions |
| Designer | `/design-handoff [F-XXX]` | `$design-handoff [F-XXX]` | Hand off a feature to dev |
| Dev | `/dev-done [F-XXX]` | `$dev-done [F-XXX]` | Mark a feature as shipped |
| Shared | `/ask [F-XXX] "q" --to po\|designer\|dev` | `$ask [F-XXX] "q" --to po\|designer\|dev` | Route a question to a role |

Use these only when you are intentionally changing project state.

### Audit / review

| Role | Claude Code | Codex | Purpose |
|------|-------------|-------|---------|
| Shared | `/lint-wiki` | `$lint-wiki` | Health-check the knowledge base and emit a dated lint report |
| Board | `/board-review [F-XXX]` | `$board-review [F-XXX]` | Domain expert review before dev starts |
| Shared | `/audit-feature [F-XXX]` | `$audit-feature [F-XXX]` | Cross-check spec vs. source intake |

### Coding utilities

| Role | Claude Code | Codex | Purpose |
|------|-------------|-------|---------|
| Dev | `/add-endpoint` | backend-scoped `$endpoint` | Add an API endpoint and update the contract/backend scaffolding |
| Shared | `/generate-clients` | `$generate-clients` | Regenerate platform clients after OpenAPI changes |
| Backend | `/document-entity` | backend-scoped `$document-entity` | Create or refine backend entity documentation |

## What The Wiki Adds

Generated projects are different from a plain code scaffold because the wiki is part of
the operating model.

Important wiki artifacts include:

- `knowledge/wiki/SCHEMA.md`
- `knowledge/wiki/SETTINGS.md`
- `knowledge/wiki/WIKI_REPORT.md` once `feature-status` has generated it
- `knowledge/wiki/features/`
- `knowledge/wiki/platform-requirements/`
- `knowledge/wiki/index.md`

If you are new to the Prism workflow, continue with [wiki-workflow.md](wiki-workflow.md)
after reading this page.

## Code Generators

Generated projects currently include these Hygen generators under `_templates/`:

| Generator | Purpose |
|-----------|---------|
| `feature new` | Scaffold a backend + Android + iOS feature slice and create an intake note in `knowledge/intake/pending/` for `po-intake` to process |
| `screen new` | Scaffold a new Android or iOS screen |
| `endpoint new` | Scaffold an OpenAPI path snippet and backend endpoint starter |
| `page new` | Scaffold a new page for generated web slices when `web-user-app` or `web-admin-portal` is included |

Typical usage inside a generated project:

```bash
npx hygen feature new
npx hygen screen new
npx hygen endpoint new
npx hygen page new
```

## GitHub Actions

The current generated workflow set includes:

| Workflow | Generated today | Purpose |
|----------|-----------------|---------|
| `api-contracts.yml` | Yes | Validate the OpenAPI contract |
| `backend.yml` | Yes | Backend test, image build, and deployment flow |
| `mobile-android.yml` | Yes | Android test, lint, build, and release flow |
| `mobile-ios.yml` | Yes | iOS test and release flow |
| `web-user-app.yml` | Yes | User web app install/build/deploy flow |
| `web-admin-portal.yml` | Yes | Admin web portal install/build/deploy flow |

## What To Read Next

- [prism-model.md](prism-model.md) for the conceptual workflow model
- [wiki-workflow.md](wiki-workflow.md) for the wiki lifecycle and read/query layer
- [ai-surfaces.md](ai-surfaces.md) for Claude/Codex packaging guidance
