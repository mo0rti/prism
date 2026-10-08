# Prism Golden

The reference workspace that Prism's CI regenerates and builds, one app of each stack

This file is the single source of agent instructions for this workspace. `CLAUDE.md` imports
it, Codex and Cursor read it directly, and each platform folder repeats the pattern with its
own `AGENTS.md`. Keep every rule here or in the platform file that owns it, never in both.
Open the **generated repository root** as the workspace, even when you work in only one
platform folder.

## Invoking operations

This file names an operation without a prefix, for example `po-intake`. Invoke it as:

- Claude Code: `/po-intake` (`.claude/commands/<operation>.md`)
- Codex: `$po-intake` (`.agents/skills/<operation>/SKILL.md`)
- Cursor: ask the agent to "run po-intake"; it follows `.claude/commands/<operation>.md`,
  `knowledge/wiki/SCHEMA.md` and, for lifecycle operations, `knowledge/wiki/LIFECYCLE.md`

## First-time setup

After `prism new` creates the project or `prism workflow install` adopts it, run `setup-project`. It
initializes the wiki, interviews the team about the domain, and generates the advisory board
configuration. It takes 15-20 minutes and runs once. It runs in the agent host on the files (the
direct-file workflow), never through a connected board.

Lifecycle work does not wait for setup. Until setup runs, the advisory board is not set up, so
`board-review` is unavailable, and a feature that needs a review keeps `advisory-review: pending`.

See `knowledge/wiki/SCHEMA.md` and `knowledge/wiki/LIFECYCLE.md` for the full cross-tool workflow.

## Connected board workflow

Read `knowledge/wiki/CONNECTED.md` when using a Prism MCP connection. Discover the
workspace's pinned standard skills and retrieve their complete instructions through
that connection. Keep required semantic reviews and confirmations in this CLI;
there is no second board approval queue. Check `write_supported` and `limitations`;
preview supported writes through the shared service, confirm and apply, then check
its durable receipt. When the service rejects a proposal, retry only with exactly the
fix the error names, at most 2 more times, and never widen the change; then stop and
report. Stop and report at once when a connected write is unavailable, denied or its
error names no fix. Custom local skills keep their direct-file
workflow. An older workspace needs an explicit `prism workflow upgrade` before
connected writes are enabled; the read-only board and existing skills remain usable.

## Product knowledge wiki

This project uses a shared product wiki at `knowledge/wiki/` as the single source of truth
for what to build. Before implementing any feature:

1. Read `knowledge/wiki/WIKI_REPORT.md` if it exists for a quick orientation summary.
2. If `knowledge/wiki/WIKI_REPORT.md` is absent, run `feature-status` first to generate it.
3. Read `knowledge/wiki/status-board.md` and confirm the feature is in `ready-for-dev` or `in-dev`
   status and that `advisory-review` is not `pending`. If `advisory-review` is `pending`,
   stop and inform the human - a board review should happen before implementation.
4. Read `knowledge/wiki/features/[feature-id]-[slug].md` for full context.
5. Read `knowledge/wiki/app-requirements/[feature-id]-[THIS_APP].md` for your
   app-specific implementation requirements.
6. Read `knowledge/wiki/api-contracts/[feature-id].md` if this feature has an API surface.
7. Check `knowledge/wiki/business-rules/` for rules that apply to this feature.
8. Check `knowledge/wiki/advisory/BOARD.md` to understand the domain intelligence layer.

`WIKI_REPORT.md` is only an orientation artifact. The underlying feature, design,
app-requirement, and rule pages remain the source of truth.

`knowledge/wiki/index.md` lists every wiki page, one line each, grouped by kind. Read it first
to find the pages a task needs beyond the feature's own context, then read those pages.

**Do not implement features without a wiki page.** Ask the human to run `po-intake [folder]`
first.

If you discover information during implementation that should update the wiki, propose the
update and ask for confirmation before writing, or route a question using
`ask F-XXX "..." --to po`. Separate facts from advice in every response.

Wiki pages state the current state and carry no date about the page itself. When a source
or a decision changes a fact, replace the superseded content in place and state rationale as
a current fact. When something was written, decided, verified or amended goes in
`knowledge/wiki/log.md`, in the entry format that `knowledge/wiki/SCHEMA.md` defines, and in
the records (ADRs, advisory reviews and processed intake items), which are never rewritten.
Mark each claim Decided, Observed, Proposed, Assumed or Unknown, and link the evidence of
every Decided and Observed claim. Raw sources are `knowledge/intake/pending/YYYY-MM-DD-slug/`
folders and are immutable once processed; an incoming source that contradicts a page is
quarantined with a `CONFLICT.md` and the page stays untouched until a human decides. A decision
is replaced by a new ADR through the supersession workflow in `knowledge/wiki/SCHEMA.md`.

## Architecture

Generated workspace with the selected platform slices. API-first:
`shared/api-contracts/openapi.yml` drives typed clients and should stay aligned with
the implemented platform routes.

```text
backend/ -> Spring Boot (Kotlin, Java 21)
web/ -> Next.js (TypeScript, Node 22), port 3000
mobile-android/ -> Android (Kotlin 2.3.10 + Jetpack Compose, MVVM, hand-wired), application ID com.example.prismgolden.mobileandroid
mobile-ios/ -> Swift 6.0 + SwiftUI (MVVM), iOS 17.0+ - Mac/Xcode only
agent-service/ -> Python agent service (FastAPI, Python 3.12), port 8200
shared/        -> OpenAPI spec + design tokens
knowledge/     -> Living product wiki (single source of truth for features)
docs/          -> Human-readable reference documentation
```

## Common Commands

| Task | Command |
|------|---------|
| Generate API clients | `task generate-clients` |
| Start backend | `task backend:run` |
| Test backend | `task backend:test` |
| Start web | `task web:dev` |
| Test web | `task web:test` |
| Build mobile-android | `task mobile-android:build` |
| Test mobile-android | `task mobile-android:test` |
| Reach the local backend from a device or emulator (mobile-android) | `task mobile-android:reverse` |
| Build mobile-ios (Mac) | `task mobile-ios:build` |
| Test mobile-ios (Mac) | `task mobile-ios:test` |
| Start agent-service with the dev identity (backend running under `local`) | `task agent-service:dev` |
| Test agent-service | `task agent-service:test` |
| Evaluate agent-service (fake provider) | `task agent-service:eval` |
| Run all tests | `task test` |

## Wiki operations

### Orient / read-only

- `feature-status` - pipeline view plus refresh of `knowledge/wiki/WIKI_REPORT.md`
- `prep-sprint` - developer session view: what is ready to build, what is blocked, what is pending board review
- `wiki-show F-XXX` - focused context bundle for one feature
- `wiki-blockers` - blockers view using the canonical blocker categories
- `wiki-query "text"` - retrieval-assisted wiki search across features, rules, design, and requirements
- `wiki-owner po|designer|dev|none` - role dashboard for open questions, waiting work, and stale pages (last verification older than `wiki-stale-after-days`)
- `wiki-app <app-id>` - app queue for active features, requirement state, and blockers

Read `knowledge/wiki/WIKI_REPORT.md` first when present. If it is absent, run
`feature-status` before deep reading.

`feature-status` is an orientation/report operation. It may write or refresh only
`knowledge/wiki/WIKI_REPORT.md`; it does not change lifecycle state. The other
read/query operations listed here are read-only.

### CLI read surfaces

For read/query operations (`wiki-show`, `wiki-blockers`, `wiki-query`, `wiki-owner`,
`wiki-app`, `lint-wiki`), probe the optional CLI before selecting the JSON path:

```bash
prism --version
```

Use the CLI only when the probe reports `prism 0.6.0` or newer (the `prism-kit>=0.6.0`
distribution contract) and the requested command response has `"schema_version": 1`. A
version probe alone does not prove that a particular command or capability exists. The
command is `prism`:

- `prism status --json`
- `prism wiki lint --json`
- `prism wiki show F-XXX --json`
- `prism wiki blockers --json`
- `prism wiki owner po|designer|dev|none --json`
- `prism wiki app <app-id> --json`
- `prism wiki search "text" --json`

Use `confidence`, facts, blocker facts, obligations, diagnostics, and sources exactly as
reported. Returned diagnostics, including errors, are facts to surface and must not be
replaced with optimistic manual state. If the version probe or schema check fails, or
`prism` is missing, too old, fails, or lacks a command, say the CLI read surface is
unavailable and fall back to direct wiki reads. Generated projects
must not hard-depend on an installed Prism CLI.

### Fallback path

The fallback reads `knowledge/wiki/SCHEMA.md`, `knowledge/wiki/LIFECYCLE.md`, `index.md` (to
find pages), `status-board.md`, feature pages, app requirements, and only the relevant
design, API, advisory, business-rule, persona, and decision pages. Keep malformed pages
visible and compute only categories proved by files; the canonical blocker categories are
`pending-board-review`, `design-track-pending`, `missing-app-requirements`,
`unresolved-open-questions`, `api-contract-not-ready`, and `cross-app-dependency`. Pages carry
no date, so freshness comes from `log.md`: a current-state page's last verification is the latest
`verify` entry that lists it, and it is stale when older than `wiki-stale-after-days` in
`SETTINGS.md` (14 when absent or invalid). All reads are read-only.

### Lifecycle / write

- `setup-project` - interactive project initialization (run once after `prism new` or `prism workflow install`)
- `po-intake [folder]` - process raw PO notes into feature specs
- `ingest [folder]` - process raw notes into topics, research, plans, direction, roadmap, personas, business rules, decisions, bugs or features (any role)
- `verify-pages <page>...` - record that current-state pages were checked against their sources (one `verify` entry in `log.md`; it never edits a page)
- `po-clarify` - answer open questions assigned to PO
- `po-specify [F-XXX]` - author one raw page as a structured `specified` draft
- `po-handoff [F-XXX]` - prepare the confirmed `specified` + `po` to `ready-for-design` + `designer` handoff
- `design-intake [F-XXX] [folder]` - attach design artifacts to a feature
- `design-clarify` - answer open questions assigned to the Designer or the Tech lead
- `design-start [F-XXX]` - move confirmed `ready-for-design` work to `in-design` and write its design tracks
- `design-ui-done [F-XXX]` - settle the UI design track (design pages that cover every app with a UI, or an exemption with a reason)
- `tech-design-done [F-XXX] [not-applicable]` - settle the technical design track (technical design page, test strategy, API contract)
- `design-handoff [F-XXX]` - move feature to ready-for-dev once both design tracks are settled
- `dev-clarify` - answer open questions assigned to Dev
- `dev-start [F-XXX]` - move confirmed `ready-for-dev` work to `in-dev`
- `dev-done [F-XXX] [app ...]` - record the delivery evidence of the named apps
- `qa-verify [F-XXX] [app ...]` - record QA results for apps or integrations, and a bug for each defect found
- `qa-pass [F-XXX] [app ...]` - pass apps through QA toward release
- `qa-fail [F-XXX] app ...` - send apps back to development after a QA failure
- `bug-update BUG-XXX <triage|scope|in-fix|fixed|verified|reverify|reject|closed|defer|undefer|open>` - move one bug through its lifecycle
- `feature-reopen [F-XXX] [specified|in-design|in-dev]` - send a feature in development or QA back to `specified` or `in-design`, or reopen one shipped feature, after impact review
- `feature-scope [F-XXX]` - edit the app scope of one feature that is not `done`: its `apps`, its `## App scope` section and the requirement pages of the apps it gains (the way out of `app-retired-in-scope`)
- `ask [F-XXX] "question" --to po|designer|dev` - route a question

### Feature lifecycle contract

The supported action mappings are exact: `po-specify` (`raw` + `po` to
`specified` + `po`), `po-handoff` (`specified` + `po` to `ready-for-design` +
`designer`), `design-start` (`ready-for-design` + `designer` to `in-design` +
`designer`), `design-ui-done` and `tech-design-done` (`ready-for-design` or
`in-design` + the design owner to `in-design`; each settles one design track),
`design-handoff` (`ready-for-design` or `in-design` + the design owner to
`ready-for-dev` + `dev`, with both design tracks settled), `dev-start`
(`ready-for-dev` + `dev` to `in-dev` + `dev`), and `dev-done` (`ready-for-dev` or
`in-dev` + `dev` to the minimum of the app stages). A return from implementation
uses the selected route in `feature-reopen` and the corresponding
`dev-return-spec` or `dev-return-design` action; a reopen of shipped work uses
`reopen-spec`, `reopen-design`, or `reopen-dev`. `po-specify` authors the structured
body; no action is a generic status setter.

Use the canonical selected-surface instructions and shared contract:

- Codex: `.agents/skills/<action>/SKILL.md`
- Claude: `.claude/commands/<action>.md`
- Shared protocol, evidence, exemptions, and reopen rules: `knowledge/wiki/LIFECYCLE.md`, read after `knowledge/wiki/SCHEMA.md`

Each action resolves one feature, rereads its source and context, shows a
complete proposed write set, and waits for final confirmation. In the board that
`prism board serve` provides, a human performs `po-handoff`, `design-start` and
`dev-start` directly after reviewing the exact changes; every other action stays
with the skills. Copy, clipboard,
dashboard, and preflight output are read-only; cancel means no mutation. The
selected generated file must carry its matching `prism:<command>-contract:v1`
marker. The other surface is optional.

When available, the read-only preflight is:

```text
prism wiki transition-preflight F-XXX [path] --action po-handoff --json
```

Use a preflight only when its common envelope is schema 1, command facts identify
the requested action, transition capability is version 2 with that action's
surface, transition version is 1, and the snapshot is consistent. A version
string alone is insufficient. Old or unsupported capabilities and generated
instructions require the direct-file protocol after the selected surface is
refreshed. Copy only a ready result; blocked or unknown results require review
or repair.

Before copying or acting on a request, reread the selected instructions,
`knowledge/wiki/SCHEMA.md`, `knowledge/wiki/LIFECYCLE.md`, `status-board.md`, the feature,
linked context, and workspace identity. Compare the path, identity, feature ID, status,
owner, advisory state, and fingerprint with current files. Use **Copy request** only for a
ready result on the selected invocation. The preview is not an "Approve move" action, does
not execute an agent, move a card, or mutate the wiki. The board derives its columns from
current source fields and cannot prove which human or agent changed them or whether
confirmation happened. Delivery evidence, design exemptions, and reopen revalidation follow
the shared schema.

### Audit / review

- `board-review [F-XXX]` - domain expert feature review via the advisory board
- `lint-wiki` - structural health check for the knowledge base
- `audit-feature [F-XXX]` - cross-check spec against source intake

## Auth

Prism owns the auth contract, and you own the real identity provider. `shared/api-contracts/openapi.yml` defines `POST /api/dev-identity/token` and `GET /api/dev-identity/jwks` (both tagged `x-prism-dev-only`) and `GET /api/me`.

A backend app validates bearer JWTs as a resource server. Under the `local` Spring profile only, it also signs short-lived development tokens for loopback requests with a key held in memory. That is **local development sign-in, never complete authentication**: do not present it as authentication, do not enable `local` in a shared or deployed environment, and replace it with your identity provider using the `security-auth` skill before the app is exposed. Docs and tasks set `local` explicitly; `docker-compose.yml` sets no profile, and no JWT secret exists in the template.

A web app calls the dev-identity endpoint from its server, keeps the token in an httpOnly cookie and calls the backend from its server, so browser scripts never read the token. Its "Local development sign-in" is the same development identity, not authentication.

An agent service accepts the backend's bearer tokens with no shared secret: under `AGENT_PROFILE=local` it verifies them against the public key the backend publishes at `GET /api/dev-identity/jwks`, otherwise against the JWKS of the configured issuer (`AGENT_OIDC_ISSUER`, `AGENT_OIDC_AUDIENCE`). It refuses to start with no identity configured, has no dev-identity endpoint of its own and no switch that turns authentication off. When the backend moves to a real provider, the service moves to the same issuer in the same change. It assists and never advises; the `agent-safety` skill lists its safety rules.

## Key Documentation

- `knowledge/wiki/SCHEMA.md` - wiki conventions and operational rules
- `knowledge/wiki/LIFECYCLE.md` - feature, board and advisory protocol, read after `SCHEMA.md` for lifecycle operations
- `knowledge/wiki/index.md` - one line per wiki page, grouped by kind; read it first
- `knowledge/wiki/status-board.md` - feature status board
- `knowledge/wiki/WIKI_REPORT.md` - generated orientation summary when present
- `knowledge/wiki/advisory/BOARD.md` - advisory board composition
- `knowledge/wiki/decisions/` - architecture decision records for long-lived technical decisions
- `README.md` - human overview, setup and common commands
- `docs/README.md` - map of the human-readable docs
- `docs/ai-agents.md` - how the agent files, commands and skills fit together
- `docs/architecture.md` - system design, platform map, tech decisions
- `docs/api/conventions.md` - API naming, pagination, error format
- `docs/deployment/ci-cd.md` - CI setup (build and test)
- `.agents/skills/deployment/` - deployment skill with worked examples; Claude Code uses `.claude/skills/deployment/`. Hosting, secrets and deployment belong to the user and their agent
- `shared/api-contracts/openapi.yml` - API contract (source of truth)
- `backend/docs/guide.md` - backend structure, conventions and commands
- `web/docs/guide.md` - web structure, sign-in slice and commands
- `agent-service/docs/guide.md` - agent-service structure, request flow, providers and commands; `agent-service/openapi.yml` is its own contract


## Conventions

Workspace-level conventions list only the slices present in the generated workspace.

- **API-first**: Define endpoints in OpenAPI -> generate clients -> implement
- **Backend module structure**: `bootstrap/`, `shared/`, and `modules/<domain>/`
- **Security**: bearer-JWT-protected routes with explicit public routes; the dev identity exists only under the `local` profile
- **Backend testing**: JUnit Jupiter 6 + MockK for service logic, plus Spring integration tests against Testcontainers PostgreSQL for security and request-path behavior
- **Mobile MVVM**: ViewModel + UiState/ViewState on the generated mobile platforms
- **Android structure**: ViewModels depend on one `ApiClient` interface and an in-memory session, wired by hand; the client is hand-written and checked against the contract by `ApiContractTest`; the Android app guides and `$android-conventions` describe them
- **Android testing**: JVM unit tests only (ViewModels, client, contract, a Robolectric Compose test); `./gradlew assembleDebug testDebugUnitTest` closes a change
- **iOS structure**: `@MainActor @Observable` view models, dependencies passed in by initializer, an API client kept to the OpenAPI contract and XCTest with a fake client; the iOS app guides and `$ios-conventions` describe them
- **Web structure**: server-side calls through the generated API client, an httpOnly session cookie and Vitest tests; the web app guides and `$web-conventions` describe them
- **Agent service**: one provider interface with a deterministic fake and a Claude adapter, read-only tools that use the user's own token, untrusted content passed as data, a per-user budget and an evaluation set; the agent app guides, `$agent-conventions` and `$agent-safety` describe them


Instructions load root-first. Codex reads `AGENTS.md` from the repo root down to the working
directory, Cursor applies a nested `AGENTS.md` to the files below it, and Claude Code loads a
folder's `CLAUDE.md`, which imports that folder's `AGENTS.md`, when it works there. Defer to
the platform-level file when working inside a specific platform folder.

Generated-workspace assumption:

- Open the **generated repository root** as the workspace.
- The generated repo keeps shared Claude skills at `.claude/skills/` and shared Codex skills at `.agents/skills/` in the repo root.
- Open root-first even when you plan to work in only one platform folder.
- This generated workspace includes multiple platform folders. Read the root guidance first, then defer to the platform-local files for the slices you touch.

- Platform folders in the generated repo are subfolders of that workspace, not separate skill roots.

## Platform-Specific Context

Each platform has its own `AGENTS.md` with detailed patterns. Its `CLAUDE.md` imports that file
and adds only what is specific to Claude Code:

- `backend/AGENTS.md` - backend: Spring Boot, Kotlin, Gradle
- `web/AGENTS.md` - web: Next.js, the local development sign-in slice, Vitest
- `mobile-android/AGENTS.md` - mobile-android: Compose, Retrofit, the local development sign-in slice, JVM tests
- `mobile-ios/AGENTS.md` - mobile-ios: SwiftUI, the local development sign-in slice, XCTest
- `agent-service/AGENTS.md` - agent-service: Python, FastAPI, uv, the agent turn, pytest and the evaluation set


## Adding Features

1. Read `knowledge/wiki/WIKI_REPORT.md` if present, or run `feature-status` first.
2. If no feature page exists, run `po-intake [folder]` to create one from raw notes.
3. For a raw feature page, run `po-specify [F-XXX]` to prepare the structured draft,
   then `po-handoff [F-XXX]` after PO completeness is verified.
4. Start design with `design-start [F-XXX]`; settle the UI track with `design-ui-done [F-XXX]` and the technical
   track with `tech-design-done [F-XXX]`; after both tracks are settled, run
   `design-handoff [F-XXX]` to generate app-requirements.
5. Answer open dev questions with `dev-clarify`; they block `dev-start` until resolved.
   Start implementation with `dev-start [F-XXX]`, add endpoints to
   `shared/api-contracts/openapi.yml`, and run `task generate-clients` as needed.
6. Implement the selected platform slices per `knowledge/wiki/app-requirements/`.
7. When shipped, verify delivery evidence (per app, release evidence or a delivery
   attestation, never a commit or pull request alone) and run `dev-done [F-XXX]`. Use
   `feature-reopen [F-XXX] [specified|in-design|in-dev]` only after impact review.
