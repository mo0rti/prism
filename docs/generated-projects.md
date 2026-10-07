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

- a generated `README.md` with the human overview, setup and the operation names by tool
- a required `knowledge/` tree with raw intake and the living product wiki
- the code of each scaffolded app under its own path, from a stack pack (`packs/<stack>/`) or, until the stack's pack exists, a full sample, each with its own `AGENTS.md`, `CLAUDE.md` and `docs/`; `docs/` holds the project-wide docs
- a generated `AGENTS.md`, the single source of agent rules, and a `CLAUDE.md` that only imports it with `@AGENTS.md`; each app folder repeats the pattern
- Cursor rules under `.cursor/rules/` that scope stack facts by file path and describe the board review; Cursor reads `AGENTS.md` itself and loads the skills in `.agents/skills/` and `.claude/skills/`
- Codex skills in `.agents/skills/`, Claude commands in `.claude/commands/` and Claude skills in `.claude/skills/`, generated from one source in this repository (`template-skills/`), so the guidance has the same text in every tool
- GitHub workflow files that build and test, one `<app-id>.yml` for each scaffolded app, scoped to the app's path; they hold no deploy job and no secrets
- Hygen generators under `_templates/`
- a `docker-compose.yml` with the PostgreSQL development database and one service for each backend app, when a backend app exists
- a `deployment` skill in `.claude/skills/deployment/` and `.agents/skills/deployment/` with worked
  examples for the backend on Azure Container Apps and the web apps on Cloudflare Workers; hosting,
  secrets and deployment belong to the user and their agent

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

## Dashboard View

Generated projects can be explored through the wiki graph dashboard:

- `prism wiki graph --open` opens the interactive dashboard in the browser
- `prism wiki graph --serve` keeps it live-updating as wiki files change

The dashboard is derived from the wiki and stays read-only. Its Graph, Board,
Apps, and Guide views are meant for orientation: feature counts, lifecycle
state, intake visibility, graph relationships, app requirements, and
first-run guidance before the wiki has been initialized. Confidence and source
paths remain visible so a stale or malformed source can be inspected before it
informs a workflow decision.

The shared board that `prism board serve` provides shows the same views and adds direct
human actions (`po-handoff`, `design-start` and `dev-start`) plus an MCP endpoint for
agents. A generated project activates it with `prism workflow upgrade . --apply`; see
[shared-board.md](shared-board.md).

A generated project's `prism.workspace.yml` declares the apps you listed, each `scaffolded` (Prism
generated its code) or `registered`. A preset's apps have the IDs `backend`, `web`, `mobile-android`
and `mobile-ios`, all in this repository; any other slug names a further app, such as a second web app
`admin`. `prism status` lists them, `prism app add` registers another app, in this repository or in another one, without generating
code, and `prism app add --scaffold` generates a new app into the workspace from its recorded template
tag ([workspace-model.md](workspace-model.md#scaffolding-apps)). `prism update` brings the workspace layer
and every scaffolded app to a newer template tag on a branch, one commit per layer. A machine that keeps an external
repository's checkout records it in `prism.local.yml`, which the generated `.gitignore`
excludes. [workspace-model.md](workspace-model.md) describes the manifest.

For a repeatable local capture, use the [wiki visualization guide](wiki-visualization.md),
which builds a synthetic TreasuryFlow fixture in a new destination. The
fixture demonstrates fresh, intake, and populated stages; it contains no
production data or observed project history.

![Wiki dashboard Board view](media/wiki-dashboard-board.png)

![Wiki dashboard Graph view](media/wiki-dashboard-graph.png)

![Generated-project dashboard empty state](media/wiki-graph-dashboard-empty-state.png)

## How To Read The Generated Repo

The most important generated areas are:

- root `README.md` for the generated repo overview
- root `AGENTS.md` for AI orientation and the rules every agent follows
- `knowledge/intake/` for raw human input and workflow state
- `knowledge/wiki/` for structured product knowledge
- platform-specific docs and source trees for implementation

If you are trying to understand the product state, the wiki matters more than the code
tree.

If you are trying to understand the generated implementation surface, read the generated
docs and platform slices together.

If the generated project includes a backend app, the first successful local startup usually
looks like this:

- start only the database container with `task db-up` (`docker compose up -d db`)
- run the backend with `task <app-id>:dev` (for the default app, `task backend:dev`), which sets
  `SPRING_PROFILES_ACTIVE=local` explicitly, on the port recorded in the app's answers file and
  `application.yml` (`8080` for the first backend, `8081` for the next)
- sign in with `POST /api/dev-identity/token` and read the profile with `GET /api/me` (the app's
  `README.md` has the `curl` commands); `GET /actuator/health` is open and reports the database

### The backend slice

Each `spring-backend` app is one compiling vertical slice with its tests, not a finished backend:
the `users` entity and its Flyway migration, a repository, a service and the controller of
`GET /api/me`, the shared error model, the dev identity and an OAuth2 resource-server configuration.
There are no example business features.

- The dev identity is **local development sign-in, not authentication**. `POST /api/dev-identity/token`
  exists only under the `local` Spring profile, answers loopback requests only, and signs a short-lived
  JWT (`iss=prism-dev-identity`) with a key generated in memory at startup. The default profile answers
  it with 404, and startup fails when `local` is active together with a configured identity provider.
  No JWT secret exists in the template, and the generated `docker-compose.yml` sets no profile.
- The OpenAPI contract (`shared/api-contracts/openapi.yml`) defines both operations, with
  `x-prism-dev-only` on the token operation. Prism owns that contract; you own the real identity
  provider, and the generated `security-auth` skill explains how to replace the dev identity with it.
- The integration tests start PostgreSQL with Testcontainers, so `./gradlew test` needs Docker and no
  credentials. The app's workflow runs `./gradlew build` on a clean runner.
- Several backends can share the workspace database: each keeps its tables in its own schema.

If the generated project includes a web app (`nextjs-web`), each one is a Next.js app under its own path
(`web/` for the default app) with one working slice and its tests:

- copy `<app>/.env.example` to `<app>/.env.local`, run `npm ci` and `task <app-id>:dev`, on the port
  recorded in the app's answers file (`3000` for the first web app, `3001` for the next)
- the "Local development sign-in" page signs in through the backend's dev identity
  (`POST /api/dev-identity/token`, served only when the backend runs under its `local` profile) and keeps the
  token in an httpOnly cookie; the home page shows `GET /api/me` through the API client that
  `openapi-typescript` generates from `shared/api-contracts/openapi.yml`
- the dev identity is not complete authentication: replace it with your identity provider before anything
  ships (the generated `web-conventions` and `security-auth` skills describe how)
- `task <app-id>:test` runs the Vitest and Testing Library tests, and `task lint` and `task test` at the
  root run lint, typecheck and the tests of every web app
- the app's `audience` (for example `B2C` or `internal`) is display text; no route or check reads it, and
  a label never enforces authorization

If the generated project includes an Android app (`android-compose`), each one is a Kotlin and Jetpack Compose
app under its own path (`mobile-android/` for the default app) with one working slice and its tests, and no
example business features:

- the "Local development sign-in" screen signs in through the backend's dev identity, and the profile screen
  shows `GET /api/me`, through a hand-written Retrofit client that a unit test checks against
  `shared/api-contracts/openapi.yml`; the token lives in memory only and is never logged
- the dev identity answers loopback requests only, so the app calls `http://localhost:8080/` and
  `adb reverse tcp:8080 tcp:8080` (`task <app-id>:reverse`) carries that to your machine, from an emulator
  and from a USB device; `10.0.2.2` and LAN addresses are refused by design (the app's `README.md` has the steps)
- `./gradlew assembleDebug testDebugUnitTest` (or `task <app-id>:build` and `task <app-id>:test`) builds the
  debug APK and runs the JVM tests: both ViewModels against a fake client, the client against a MockWebServer,
  the contract check and a Compose UI test of the sign-in screen under Robolectric; no emulator is needed
- the dev identity is not complete authentication: replace it with your identity provider before anything
  ships (the generated `android-conventions` and `security-auth` skills describe how); release signing and
  store upload are yours, and the `deployment` skill's mobile note describes them
- two Android apps in one workspace differ in application ID, namespace, package directories, Gradle project
  name and workflow, all derived from the app ID

## AI Agent Surfaces

Generated projects include agent context for Claude, Codex, and Cursor.

Invocation model:

- Claude Code uses slash commands under `.claude/commands/`
- Codex uses skills under `.agents/skills/` and invokes the structured workflow surface
  with a `$` prefix
- Cursor users ask the agent to run the same named operations

Workspace recommendation:

- Open the **generated repository root** when using Claude Code or Codex.
- Root AI context and skill surfaces live at the generated repo root, not inside
  platform subfolders such as `mobile-android/` or `mobile-ios/`.
- If you open only a platform subfolder as a standalone workspace, do not assume the
  agent will automatically discover parent-level skills or root guidance.
- In that narrower setup, manually inspect the generated repo root files such as
  `README.md`, `AGENTS.md`, `CLAUDE.md`, `.agents/skills/`, and
  `.claude/skills/` when they are available.

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
| Shared | `/wiki-owner po\|designer\|dev\|none` | `$wiki-owner po\|designer\|dev\|none` | Show pending work and stale pages (last verification older than `wiki-stale-after-days`) for one owner role |
| Shared | `/verify-pages <page>...` | `$verify-pages <page>...` | Record that current-state pages were checked against their sources: one `verify` entry in `log.md`, no page edited |
| Shared | `/wiki-app <app-id>` | `$wiki-app <app-id>` | Show the active feature queue for one app |

Recommended first use:

1. `feature-status`
2. `prep-sprint` if you are a developer
3. `wiki-show` or `wiki-query` for focused drill-down

### Lifecycle / write

| Role | Claude Code | Codex | Purpose |
|------|-------------|-------|---------|
| Shared | `/setup-project` | `$setup-project` | One-time project initialization that interviews you and builds the advisory board |
| PO | `/po-intake [folder]` | `$po-intake [folder]` | Process raw PO notes into `raw` feature pages |
| Shared | `/ingest [folder]` | `$ingest [folder]` | Process a pending folder, for any role, into a topic, research page, plan, direction, roadmap, persona, business rule, decision or feature |
| PO | `/po-clarify` | `$po-clarify` | Answer open questions assigned to PO |
| PO | `/po-specify [F-XXX]` | `$po-specify [F-XXX]` | Complete a `raw` feature and move it to `specified` |
| PO | `/po-handoff [F-XXX]` | `$po-handoff [F-XXX]` | Hand off a feature to design |
| Designer | `/design-intake [F-XXX] [folder]` | `$design-intake [F-XXX] [folder]` | Attach design artifacts to a feature |
| Designer | `/design-clarify` | `$design-clarify` | Answer open design questions |
| Designer | `/design-start [F-XXX]` | `$design-start [F-XXX]` | Start design on a feature that was handed off |
| Designer | `/design-handoff [F-XXX]` | `$design-handoff [F-XXX]` | Hand off a feature to dev |
| Dev | `/dev-clarify` | `$dev-clarify` | Answer open questions assigned to Dev |
| Dev | `/dev-start [F-XXX]` | `$dev-start [F-XXX]` | Start development on a feature that is ready for dev |
| Dev | `/dev-done [F-XXX]` | `$dev-done [F-XXX]` | Mark a feature as shipped, recording the delivery evidence the developer supplies |
| Shared | `/feature-reopen [F-XXX] [specified\|in-design\|in-dev]` | `$feature-reopen [F-XXX] [specified\|in-design\|in-dev]` | Reopen shipped work through one impact-reviewed route |
| Shared | `/ask [F-XXX] "q" --to po\|designer\|dev` | `$ask [F-XXX] "q" --to po\|designer\|dev` | Route a question to a role |

Use these only when you are intentionally changing project state.

### Audit / review

| Role | Claude Code | Codex | Purpose |
|------|-------------|-------|---------|
| Shared | `/lint-wiki` | `$lint-wiki` | Health-check the knowledge base; writes a lint report only when you ask for one |
| Board | `/board-review [F-XXX]` | `$board-review [F-XXX]` | Domain expert review before dev starts |
| Shared | `/audit-feature [F-XXX]` | `$audit-feature [F-XXX]` | Cross-check spec vs. source intake |

### API and contract workflow

For feature work in generated projects, keep the layers distinct:

- the wiki defines what to build
- `shared/api-contracts/openapi.yml` defines the API contract
- `task generate-clients` regenerates derived client code from that contract
- backend, mobile, and web code then implement or consume the contract

For endpoint changes, the default order is:

1. update the OpenAPI contract
2. run `task generate-clients`
3. implement the backend and downstream consumers

### Coding utilities

| Role | Claude Code | Codex | Purpose |
|------|-------------|-------|---------|
| Dev | `/add-endpoint` | backend-scoped `$endpoint` | Add an API endpoint with a contract-first workflow and update backend scaffolding |
| Shared | `/generate-clients` | `$generate-clients` | Regenerate platform clients after OpenAPI changes |
| Backend | `/document-entity` | backend-scoped `$document-entity` | Create or refine backend entity documentation |

## What The Wiki Adds

Generated projects are different from a plain code scaffold because the wiki is part of
the operating model.

Important wiki artifacts include:

- `knowledge/wiki/SCHEMA.md`
- `knowledge/wiki/LIFECYCLE.md`
- `knowledge/wiki/SETTINGS.md`
- `knowledge/wiki/WIKI_REPORT.md` once `feature-status` has generated it
- `knowledge/wiki/features/`
- `knowledge/wiki/app-requirements/`
- `knowledge/wiki/index.md`, which also lists the pages of `docs/` under "Project docs"
- `knowledge/wiki/status-board.md`

If you are new to the Prism workflow, continue with [wiki-workflow.md](wiki-workflow.md)
after reading this page.

## Code Generators

Generated projects include these Hygen generators under `_templates/`:

| Generator | Purpose |
|-----------|---------|
| `feature new` | Scaffold a backend + iOS feature slice and create a dated intake note in `knowledge/intake/pending/YYYY-MM-DD-feature-name/` for `po-intake` to process |
| `screen new` | Scaffold a new iOS screen |
| `endpoint new` | Scaffold an OpenAPI path snippet and backend endpoint starter |

Typical usage inside a generated project:

```bash
npx hygen feature new
npx hygen screen new
npx hygen endpoint new
```

## GitHub Actions

The generated workflow set is:

| Workflow | Generated | Purpose |
|----------|-----------|---------|
| `api-contracts.yml` | Always | Validate the OpenAPI contract |
| `<app-id>.yml` | One for each scaffolded `spring-backend` app (`backend.yml` for the default app) | `./gradlew build` (compile, every test with Testcontainers PostgreSQL, the jar), scoped to the app's path |
| `<app-id>.yml` | One for each scaffolded `android-compose` app (`mobile-android.yml` for the default app) | `./gradlew assembleDebug testDebugUnitTest` on a clean runner (the debug APK and the JVM unit tests), scoped to the app's path |
| `mobile-ios.yml` | With `mobile-ios` | iOS test |
| `<app-id>.yml` | One for each scaffolded `nextjs-web` app (`web.yml` for the default app) | `npm ci`, lint, typecheck, Vitest tests and `next build` on a clean runner, scoped to the app's path |

No workflow deploys. The `deployment` skill describes the deploy jobs to add once you choose a host.

## What To Read Next

- [prism-model.md](prism-model.md) for the conceptual workflow model
- [wiki-workflow.md](wiki-workflow.md) for the wiki lifecycle and read/query layer
- [ai-surfaces.md](ai-surfaces.md) for Claude/Codex packaging guidance
