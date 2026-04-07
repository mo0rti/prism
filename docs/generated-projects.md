# Generated Projects

Generated repositories include more than application code. They also include documentation, AI context, workflow wiring, and in-project generators.

## Included Outputs

Generated projects include:

- a generated `README.md`
- a generated `CONTEXT.md` as the root AI context anchor
- a required `knowledge/` tree with raw intake and the living product wiki
- platform-specific docs under `docs/`, `backend/docs/`, `mobile-android/docs/`, `mobile-ios/docs/`, `web-user-app/docs/`, and `web-admin-portal/docs/`
- generated AI context files such as `AGENTS.md` and `CLAUDE.md`
- GitHub workflow files
- Hygen generators under `_templates/`
- deployment docs such as `docs/deployment/cloudflare-setup.md` when web platforms are selected

Treat those outputs as part of the product, but still validate the paths you plan to rely on.

## First-Time Setup

After `copier copy`, generated projects have a wiki skeleton but no project-specific
advisory board state yet. Before building the first feature, open the generated project
in your AI agent and initialize it:

- Claude Code: `/setup-project`
- Codex: `$setup-project`
- Cursor: ask the agent to "run setup-project"

This creates the advisory board in `knowledge/wiki/advisory/BOARD.md` and prepares the
wiki for `po-intake`, `design-intake`, and the rest of the lifecycle.

## AI Agent Commands

Generated projects include agent context for Claude, Codex, and Cursor. The commands below are Claude Code slash commands under `.claude/commands/`. Codex equivalents are invoked by plain name (e.g. `po-intake`, `design-handoff`) except for the five operations that ship as Codex skills under `.agents/skills/` and use a `$` prefix: `$setup-project`, `$board-review`, `$prep-sprint`, `$feature-status`, `$lint-wiki`. Cursor users invoke the same operations by asking the agent by name.

### Wiki lifecycle (all roles)

| Claude Code | Purpose |
|-------------|---------|
| `/setup-project` | One-time project initialization — interviews you and builds the advisory board |
| `/po-intake [folder]` | Process raw PO notes into feature specs |
| `/po-clarify` | Answer open questions assigned to PO |
| `/po-handoff [F-XXX]` | Hand off a feature to design |
| `/design-intake [F-XXX] [folder]` | Attach design artifacts to a feature |
| `/design-clarify` | Answer open design questions |
| `/design-handoff [F-XXX]` | Hand off a feature to dev |
| `/board-review [F-XXX]` | Domain expert review before dev starts |
| `/prep-sprint` | Show what is ready to build |
| `/dev-done [F-XXX]` | Mark a feature as shipped |
| `/feature-status` | Full pipeline view |
| `/lint-wiki` | Health-check the knowledge base |
| `/ask [F-XXX] "q" --to po\|designer\|dev` | Route a question to a role |
| `/audit-feature [F-XXX]` | Cross-check spec vs. source intake |

### Coding utilities

| Claude Code | Purpose |
|-------------|---------|
| `/add-endpoint` | Add an API endpoint and update the contract/backend scaffolding |
| `/generate-clients` | Regenerate platform clients after OpenAPI changes |
| `/document-entity` | Create or refine backend entity documentation |

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
