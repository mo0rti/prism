# Generated Projects

Generated repositories include more than application code. They also include documentation, AI context, workflow wiring, and in-project generators.

## Included Outputs

Generated projects include:

- a generated `README.md`
- platform-specific docs under `docs/`, `backend/docs/`, `mobile-android/docs/`, `mobile-ios/docs/`, `web-user-app/docs/`, and `web-admin-portal/docs/`
- generated AI context files such as `AGENTS.md` and `CLAUDE.md`
- GitHub workflow files
- Hygen generators under `_templates/`
- deployment docs such as `docs/deployment/cloudflare-setup.md` when web platforms are selected

Treat those outputs as part of the product, but still validate the paths you plan to rely on.

## AI Agent Commands

Generated projects include agent context for Claude, Codex, and Cursor. Explicit slash commands are currently templated for Claude under `.claude/commands/`:

| Command | Purpose |
|---------|---------|
| `/scaffold-feature` | Guide feature delivery across the generated slices that exist in the project |
| `/add-endpoint` | Add an API endpoint and update the contract/backend scaffolding |
| `/generate-clients` | Regenerate platform clients after OpenAPI changes |
| `/document-entity` | Create or refine backend entity documentation |
| `/document-feature` | Create or refine feature documentation |

## Code Generators

Generated projects currently include these Hygen generators under `_templates/`:

| Generator | Purpose |
|-----------|---------|
| `feature new` | Scaffold a backend + Android + iOS feature slice and related docs |
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
