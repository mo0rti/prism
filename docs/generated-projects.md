# Generated Projects

Generated Prism repositories include more than application code.

They also include:

- project documentation
- AI context for multiple tools
- the product wiki and lifecycle wiring
- generators and workflow scaffolding inside the generated repo

This page answers two questions:

1. what do I have after `copier copy`?
2. what should I do next inside the generated project?

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

## First Five Things To Do After Generation

After `copier copy`, the generated repository already contains the wiki skeleton, but it
does not yet contain your project-specific advisory board state.

Use this first-run flow:

1. confirm the selected platform directories exist
2. read the generated `README.md` and `CONTEXT.md`
3. inspect `knowledge/wiki/SCHEMA.md`
4. initialize the wiki with `setup-project`
5. use the read-only orientation commands before changing lifecycle state

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

### Orient / read-only

| Claude Code | Purpose |
|-------------|---------|
| `/prep-sprint` | Show what is ready to build |
| `/feature-status` | Full pipeline view and refresh of the generated orientation report |
| `/wiki-show F-XXX` | Assemble focused feature context from linked wiki files |
| `/wiki-blockers` | Show blockers using the canonical blocker categories |
| `/wiki-query "text"` | Retrieval-assisted search across the wiki |
| `/wiki-owner po\|designer\|dev` | Show pending work and stale items for one owner role |
| `/wiki-platform <platform-id>` | Show the active feature queue for one platform |

Representative Codex equivalents:

- `$prep-sprint`
- `$feature-status`
- `$wiki-show`
- `$wiki-blockers`
- `$wiki-query`
- `$wiki-owner`
- `$wiki-platform`

Recommended first use:

1. `feature-status`
2. `prep-sprint` if you are a developer
3. `wiki-show` or `wiki-query` for focused drill-down

### Lifecycle / write

| Claude Code | Purpose |
|-------------|---------|
| `/setup-project` | One-time project initialization that interviews you and builds the advisory board |
| `/po-intake [folder]` | Process raw PO notes into feature specs |
| `/po-clarify` | Answer open questions assigned to PO |
| `/po-handoff [F-XXX]` | Hand off a feature to design |
| `/design-intake [F-XXX] [folder]` | Attach design artifacts to a feature |
| `/design-clarify` | Answer open design questions |
| `/design-handoff [F-XXX]` | Hand off a feature to dev |
| `/dev-done [F-XXX]` | Mark a feature as shipped |
| `/ask [F-XXX] "q" --to po\|designer\|dev` | Route a question to a role |

Representative Codex equivalents:

- `$setup-project`
- `$po-intake`
- `$po-clarify`
- `$po-handoff`
- `$design-intake`
- `$design-clarify`
- `$design-handoff`
- `$dev-done`
- `$ask`

Use these only when you are intentionally changing project state.

### Audit / review

| Claude Code | Purpose |
|-------------|---------|
| `/lint-wiki` | Health-check the knowledge base and emit a dated lint report |
| `/board-review [F-XXX]` | Domain expert review before dev starts |
| `/audit-feature [F-XXX]` | Cross-check spec vs. source intake |

Representative Codex equivalents:

- `$lint-wiki`
- `$board-review`
- `$audit-feature`

### Coding utilities

| Claude Code | Purpose |
|-------------|---------|
| `/add-endpoint` | Add an API endpoint and update the contract/backend scaffolding |
| `/generate-clients` | Regenerate platform clients after OpenAPI changes |
| `/document-entity` | Create or refine backend entity documentation |

Representative Codex equivalents:

- backend-scoped `$endpoint` for backend endpoint implementation guidance
- `$generate-clients`
- `$document-entity` is available in backend-scoped guidance

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
