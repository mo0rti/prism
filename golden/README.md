# Prism Golden

The reference workspace that Prism's CI regenerates and builds, one app of each stack

![Generated With Prism](https://img.shields.io/badge/generated%20with-Prism-5B4BFF)
![Status](https://img.shields.io/badge/status-generated%20workspace-1f6feb)
![Workflow](https://img.shields.io/badge/workflow-wiki--driven-0A7EA4)
![API](https://img.shields.io/badge/API-OpenAPI--first-6BA539)
![Backend](https://img.shields.io/badge/backend-Spring%20Boot%204%20%2B%20Kotlin-6DB33F?logo=springboot&logoColor=white)
![Web](https://img.shields.io/badge/web-Next.js-000000?logo=nextdotjs&logoColor=white)
![Android](https://img.shields.io/badge/android-Compose-3DDC84?logo=android&logoColor=white)
![iOS](https://img.shields.io/badge/iOS-SwiftUI-F05138?logo=swift&logoColor=white)
![Agent service](https://img.shields.io/badge/agent%20service-FastAPI-009688?logo=fastapi&logoColor=white)


## Built With Prism

This workspace was generated with [Prism](https://github.com/mo0rti/prism), a
multi-platform workspace generator and workflow model for AI-assisted product
development.

If you want to understand how this project is structured, why the docs and AI
context files are laid out this way, or how to generate a similar workspace,
start with the Prism repository.

## Workflow Status

When this workspace is connected to GitHub, add badges for the workflows that
apply to the generated project, such as backend, API contracts, web, Android,
or iOS.

## Architecture

This generated workspace currently includes:

- **backend/** - Backend: Spring Boot (Kotlin) REST API
- **web/** - Web: Next.js web app (TypeScript), for B2C
- **mobile-android/** - Android App: Android app (Kotlin/Jetpack Compose, MVVM)
- **mobile-ios/** - iOS App: iOS app (Swift/SwiftUI)
- **agent-service/** - Agent Service: AI agent service (Python, FastAPI): assists and never advises
- **shared/** - OpenAPI contract and shared design tokens
- **knowledge/** - Product wiki and delivery workflow metadata
- **docs/** - Human-readable architecture and operations docs


## First-Time Setup

This project includes a living product wiki at `knowledge/wiki/`. Before building
the first feature, initialize the wiki and advisory board:

- **Claude Code:** `/setup-project`
- **Codex:** `$setup-project`
- **Cursor:** ask the agent to "run setup-project"

This setup step interviews the team about domain risks, creates
`knowledge/wiki/advisory/BOARD.md`, and prepares the wiki for feature intake.

If the Prism CLI is installed, keep the product-truth dashboard open while you work:

```bash
prism wiki graph --serve   # live dashboard: intake -> lifecycle -> apps
prism wiki graph --open    # one-off snapshot in the browser
```

This dashboard is read-only: your agent is where you act, the dashboard is where
you look. Its Graph, Board, Apps, and Guide views derive their facts from
`knowledge/wiki/`, intake queues, and workspace metadata. Source paths,
confidence, workflow blockers, and page-health diagnostics stay inspectable.
On a fresh workspace it walks you through setup, your first intake brief, and
`po-intake` so your first feature appears on the board as it is born.

To let a human perform `po-handoff`, `design-start` and `dev-start` directly in the
board, and to connect agents over MCP, run `prism workflow upgrade .` to preview and
`prism workflow upgrade . --apply` to apply, issue grants with `prism board grant`, and
start the service with `prism board serve .`. `docs/shared-board.md` in the Prism
repository has the steps, and `knowledge/wiki/CONNECTED.md` describes how agents use
the connection.

For terminal output, use `prism wiki graph --json` or
`prism wiki graph --mermaid --view lifecycle`. The dashboard and these
read-oriented commands do not change wiki state; use the lifecycle commands
above when you intend to edit it.

## Working With AI Agents

[`AGENTS.md`](AGENTS.md) is the single source of agent rules. Codex and Cursor read it
directly and [`CLAUDE.md`](CLAUDE.md) imports it, so each rule is written once. Every platform
folder repeats the pattern with its own `AGENTS.md` and a `CLAUDE.md` that imports it.
[AI Agents](docs/ai-agents.md) explains how the instruction files, commands and skills fit
together.

Invoke a workflow operation by name:

- **Claude Code:** `/operation`, for example `/po-intake [folder]`
- **Codex:** `$operation`, for example `$po-intake [folder]`
- **Cursor:** ask the agent to "run operation", for example "run po-intake on the folder
  2026-04-07-client-call". The agent follows `.claude/commands/[command].md` and
  `knowledge/wiki/SCHEMA.md`, plus `knowledge/wiki/LIFECYCLE.md` for lifecycle operations.

| Category | Operations |
|----------|------------|
| Setup | `setup-project` |
| PO | `po-intake [folder]`, `ingest [folder]`, `po-clarify`, `po-specify [F-XXX]`, `po-handoff [F-XXX]` |
| Designer | `design-intake [F-XXX] [folder]`, `design-clarify`, `design-start [F-XXX]`, `design-handoff [F-XXX]` |
| Developer | `prep-sprint`, `dev-clarify`, `dev-start [F-XXX]`, `dev-done [F-XXX]` |
| Lifecycle | `feature-reopen [F-XXX] [specified\|in-design\|in-dev]` |
| Board | `board-review [F-XXX]` |
| Shared | `feature-status`, `ask [F-XXX] "question" --to po\|designer\|dev`, `audit-feature [F-XXX]`, `lint-wiki`, `wiki-show F-XXX`, `wiki-blockers`, `wiki-query "text"`, `wiki-owner po\|designer\|dev\|none`, `wiki-app <app-id>`, `verify-pages <page>...` |

Backend helpers differ by tool. Claude Code has `/add-endpoint`, `/add-integration`,
`/create-migration`, `/document-entity`, `/generate-clients`, `/review-query`,
`/review-security-surface` and `/debug-prod-issue`. Codex has `$endpoint`, `$document-entity`
and `$generate-clients`.

## Quick Start

```bash
# Review local configuration
# The local database defaults are already generated in `.env`
# mobile-ios: `task mobile-ios:generate-project` creates its Xcode project from `mobile-ios/project.yml` (Mac only)
# The Debug API_BASE_URL in that file is the local backend; set the Release one before production or TestFlight builds
cp web/.env.example web/.env.local
# Edit the local config files as needed for your machine and credentials

# Start the local database first
task db-up

# Start backend locally on port 8080 with the local development identity (profile `local`)
task backend:dev

# Start web on port 3000 (its "Local development sign-in" needs a backend running under its `local` profile)
task web:dev

# Start agent-service on port 8200 (its dev identity verifies the tokens of a backend running under its `local` profile; set AGENT_BACKEND_BASE_URL when that backend is not on port 8080)
task agent-service:dev

# Run mobile-android on an emulator or a USB device (its "Local development sign-in" needs a backend running under its `local` profile,
# reached through `adb reverse` because the dev identity accepts loopback requests only)
task mobile-android:reverse
task mobile-android:install

# Generate clients after any OpenAPI contract change
# npm install -g @openapitools/openapi-generator-cli
task generate-clients
```

## Documentation

- [Agent Instructions](AGENTS.md) for the single source of rules that every AI agent follows
- [Product Wiki Schema](knowledge/wiki/SCHEMA.md) for the structure and rules of the living product wiki
- [Product Wiki Lifecycle](knowledge/wiki/LIFECYCLE.md) for the feature, board and advisory protocol
- [AI Agents](docs/ai-agents.md) for the command layer, skill map, and platform guidance structure
- [Architecture Overview](docs/architecture.md) for system boundaries, platform map, and auth flow
- [API Conventions](docs/api/conventions.md) for URL structure, versioning, auth headers, and error responses
- [Backend Guide](backend/docs/guide.md) for the structure, conventions and commands of `backend`
- [Web Guide](web/docs/guide.md) for the structure, sign-in slice and commands of `web`
- [Android App Guide](mobile-android/docs/guide.md) for the structure, sign-in slice, local backend access and commands of `mobile-android`
- [iOS App Guide](mobile-ios/docs/guide.md) for the structure, sign-in slice and commands of `mobile-ios`
- [Agent Service Guide](agent-service/docs/guide.md) for the structure, request flow, providers and commands of `agent-service`
- [CI/CD](docs/deployment/ci-cd.md) for the generated GitHub Actions workflow layout (build and test)
- Deployment: the `deployment` skill (`.claude/skills/deployment/`, `.agents/skills/deployment/`) holds worked examples for the backend on Azure Container Apps and the web apps on Cloudflare; hosting, secrets and deployment are yours to choose

## Common Tasks

| Action | Command |
|--------|---------|
| Generate API clients | `task generate-clients` |
| Install web dependencies | `task web:install` |
| Start backend with the local development identity | `task backend:dev` |
| Start web | `task web:dev` |
| Start agent-service with the local development identity | `task agent-service:dev` |
| Evaluate agent-service with the fake provider | `task agent-service:eval` |
| Run all tests | `task test` |
| Lint all platforms | `task lint` |
