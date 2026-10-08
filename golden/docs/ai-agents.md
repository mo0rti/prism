# AI Agents

This workspace includes a layered AI guidance system so Claude Code, Codex, Cursor,
and humans can all work from the same product and technical context.

## Purpose

The agent system in this workspace does four jobs:

1. give every agent a shared starting point
2. keep product work anchored to the living wiki in `knowledge/wiki/`
3. provide platform-specific implementation rules close to each codebase
4. package repeatable workflows into commands and reusable skills

## How The Layers Fit Together

| Layer | Where | Purpose |
|------|-------|---------|
| Root agent instructions | [`AGENTS.md`](../AGENTS.md), [`CLAUDE.md`](../CLAUDE.md) | `AGENTS.md` is the single source of workspace rules and the first file an agent reads; `CLAUDE.md` imports it |
| Human overview | [`README.md`](../README.md) | Setup, repository layout and the operation names by tool |
| Product wiki | [`knowledge/wiki/SCHEMA.md`](../knowledge/wiki/SCHEMA.md), [`knowledge/wiki/LIFECYCLE.md`](../knowledge/wiki/LIFECYCLE.md), [`knowledge/wiki/ACTIONS.md`](../knowledge/wiki/ACTIONS.md) | Source of truth for features, app requirements, contracts, rules, and advisory reviews |
| Claude commands | [`.claude/commands/`](../.claude/commands/) | Structured project operations such as setup, PO intake, review, handoff, and wiki maintenance |
| Claude skills | [`.claude/skills/`](../.claude/skills/) | Reusable Claude Code guidance for implementation, conventions, testing, and platform work |
| Codex skills | [`.agents/skills/`](../.agents/skills/) | Reusable Codex guidance for shared workflows and supported platform work |
| Cursor rules | [`.cursor/rules/`](../.cursor/rules/) | Stack facts scoped by file path; Cursor reads `AGENTS.md` itself and loads the skills in `.agents/skills/` and `.claude/skills/` |
| Backend guidance | [`backend/AGENTS.md`](../backend/AGENTS.md), [`backend/CLAUDE.md`](../backend/CLAUDE.md), [`backend/docs/guide.md`](../backend/docs/guide.md) | Backend-specific architecture, conventions, and delivery rules |
| Web guidance | [`web/AGENTS.md`](../web/AGENTS.md), [`web/CLAUDE.md`](../web/CLAUDE.md), [`web/docs/guide.md`](../web/docs/guide.md) | Web implementation rules, the sign-in slice and workflow expectations |
| Android App guidance | [`mobile-android/AGENTS.md`](../mobile-android/AGENTS.md), [`mobile-android/CLAUDE.md`](../mobile-android/CLAUDE.md), [`mobile-android/docs/guide.md`](../mobile-android/docs/guide.md) | Android implementation rules, the sign-in slice and workflow expectations |
| iOS App guidance | [`mobile-ios/AGENTS.md`](../mobile-ios/AGENTS.md), [`mobile-ios/CLAUDE.md`](../mobile-ios/CLAUDE.md), [`mobile-ios/docs/guide.md`](../mobile-ios/docs/guide.md) | iOS implementation rules and workflow expectations |
| Agent Service guidance | [`agent-service/AGENTS.md`](../agent-service/AGENTS.md), [`agent-service/CLAUDE.md`](../agent-service/CLAUDE.md), [`agent-service/docs/guide.md`](../agent-service/docs/guide.md) | Agent service rules: the agent turn, providers, identity, safety and evaluation |


## Agent File Map

<pre>
prism-golden/
├── AGENTS.md
├── CLAUDE.md
├── .cursor/
│   └── rules/
├── knowledge/
│   └── wiki/
│       ├── SCHEMA.md
│       ├── LIFECYCLE.md
│       ├── ACTIONS.md
│       ├── index.md
│       ├── status-board.md
│       └── advisory/BOARD.md
├── .claude/
│   ├── commands/
│   └── skills/
├── .agents/
│   └── skills/
├── backend/
│   ├── AGENTS.md
│   ├── CLAUDE.md
│   └── docs/guide.md
├── web/
│   ├── AGENTS.md
│   ├── CLAUDE.md
│   └── docs/guide.md
├── mobile-android/
│   ├── AGENTS.md
│   ├── CLAUDE.md
│   └── docs/guide.md
├── mobile-ios/
│   ├── AGENTS.md
│   ├── CLAUDE.md
│   └── docs/guide.md
├── agent-service/
│   ├── AGENTS.md
│   ├── CLAUDE.md
│   └── docs/guide.md
└── docs/
    ├── ai-agents.md
    ├── architecture.md
    └── ... selective examples; see docs/README.md for the full docs map
</pre>

## One Source Of Instructions

Each rule is written once, in `AGENTS.md`. The tools load it like this:

- **Codex** reads `AGENTS.md` from the repository root down to the working directory.
- **Claude Code** loads `CLAUDE.md`, whose first line `@AGENTS.md` imports the sibling `AGENTS.md`.
  A platform folder's `CLAUDE.md` does the same for that folder's `AGENTS.md` and adds only
  the Claude Code skills and commands that no other tool shares.
- **Cursor** applies `AGENTS.md` at the root and in subfolders itself, so no rule repeats or
  references it. The rules in `.cursor/rules/` carry only stack facts scoped by file path, and Cursor loads the skills in `.agents/skills/` and
  `.claude/skills/` too (the board review is a skill, not a rule, so Cursor does not load it twice).

Add or change a rule in `AGENTS.md`, or in the platform `AGENTS.md` that owns it, and nowhere
else. The skills in `.agents/skills/` and `.claude/skills/` and the commands in
`.claude/commands/` carry the same text, written once and generated into each layout; when you
change a skill in this workspace, change every copy of it.

After `setup-project`, the advisory area should contain both `BOARD.md` and
`PROJECT_FOUNDATION.md`, which preserves the setup interview, risk framing, and
initial board rationale.

## Commands Vs Skills

Commands and skills are related, but they are not the same thing:

- **Commands** are explicit operations invoked by name, mainly through Claude Code using `/command-name`.
- **Skills** are reusable guidance bundles that agents load when the work matches a workflow or platform need.

Surface split:

- [`.claude/commands/`](../.claude/commands/) powers Claude Code slash commands
- [`.claude/skills/`](../.claude/skills/) holds Claude Code skills
- [`.agents/skills/`](../.agents/skills/) holds Codex skills

Many lifecycle workflows appear in both places:

- as a Claude command for direct invocation
- as a Codex skill so the same workflow can be executed from Codex

## Command Surface

The command layer is mainly exposed through [`.claude/commands/`](../.claude/commands/).
These commands drive the Prism workflow around product intake, advisory review,
design handoff, delivery prep, and wiki maintenance.

Key command groups:

- setup: `setup-project`
- product workflow: `po-intake`, `ingest`, `po-clarify`, `po-specify`, `po-handoff`
- design workflow: `design-intake`, `design-clarify`, `design-start`, `design-handoff`
- development helpers: `add-endpoint`, `add-integration`, `document-entity`, `generate-clients`, `create-migration`
- backend review and debugging: `review-query`, `review-security-surface`, `debug-prod-issue`
- delivery workflow: `prep-sprint`, `dev-clarify`, `dev-start`, `dev-done`, `feature-reopen`, `feature-scope`
- governance and support: `board-review`, `feature-status`, `ask`, `audit-feature`, `lint-wiki`, `wiki-*`

Read [`README.md`](../README.md) for the operation names by tool surface.

When the optional Prism CLI is installed, `prism wiki graph --open` renders an
interactive dashboard of the wiki (features, lifecycle board, app lanes),
and `prism wiki graph --serve` keeps it live-updating as wiki files change.
The dashboard includes Graph, Board, Apps, and Guide views. It is
read-only and derived; the wiki files remain the source of truth. The
inspector exposes source paths, confidence, workflow blockers, and page-health
diagnostics so an agent can follow the evidence before changing project state.
For a terminal fallback, use `prism wiki graph --json` or
`prism wiki graph --mermaid --view lifecycle`.

### Connected board

`prism board serve .` runs one local service
that serves the browser board and a standard MCP endpoint. Agents that connect to it
read the same canonical skills through the endpoint and need no `.claude/` or
`.agents/` folder; [`knowledge/wiki/CONNECTED.md`](../knowledge/wiki/CONNECTED.md)
describes how they use it. In that board a human performs `po-handoff`,
`design-start` and `dev-start` directly after reviewing the exact changes. The other
actions, and every agent action, keep the confirmation of the skill in the agent's
own interface. The board adds no approval queue.

### Feature lifecycle boundary

The exact feature-only actions are `po-specify` (`raw` + `po` to `specified` +
`po`), `po-handoff` (`specified` + `po` to `ready-for-design` + `designer`),
`design-start` (`ready-for-design` + `designer` to `in-design` + `designer`),
`design-handoff` (`in-design` + `designer` to `ready-for-dev` + `dev`),
`dev-start` (`ready-for-dev` + `dev` to `in-dev` + `dev`), and `dev-done`
(`in-dev` + `dev` to `done` + `none`). `feature-reopen` selects one of
`reopen-spec`, `reopen-design`, or `reopen-dev`. `po-specify` authors the
canonical structured body from one raw page, so no action is a generic status
setter.

Detailed behavior is canonical in the selected `.agents/skills/<action>/SKILL.md`
or `.claude/commands/<action>.md` plus `knowledge/wiki/SCHEMA.md`, `knowledge/wiki/LIFECYCLE.md` and `knowledge/wiki/ACTIONS.md`. The selected
surface is independent; its matching `prism:<command>-contract:v1` marker is
required, while the other surface is optional. Every write action rereads one
feature and linked evidence, shows the complete proposed write set, and waits
for final confirmation. Dashboard, clipboard, and CLI preflight output is
copy-only; the Board reflects current source fields and cannot prove who made a
change or whether confirmation happened.

If the optional CLI surface is present, use
`prism wiki transition-preflight F-XXX [path] --action <action> --json` only when
the response identifies envelope schema 1, command facts for the requested
action, transition capability version 2 with that action's surface, transition
version 1, and a consistent snapshot. A version string alone is insufficient;
missing or unsupported probes fall back to direct-file reads. Use **Copy
request** only for a ready result. Static captures are snapshot-relative; live
refresh observes later source changes. Delivery evidence, UI design exemptions,
and reopen revalidation are defined in `LIFECYCLE.md`.

## Skill Map

The sections below describe the real skill sets on disk and what each one helps with.

### Codex Workflow Skills

These are the shared delivery skills under [`.agents/skills/`](../.agents/skills/) that
mirror much of the Claude command surface for Codex:

| Skill | Purpose |
|------|---------|
| `setup-project` | Initializes the workspace wiki, records the setup interview, and generates the advisory board |
| `po-intake` | Converts raw product input into structured feature intake |
| `ingest` | Converts a raw source from any role into wiki pages of any kind: topic, research, plan, direction, roadmap, persona, business rule, decision or feature |
| `po-clarify` | Resolves product ambiguity before implementation starts |
| `po-specify` | Authors one raw feature page as a structured specified draft |
| `po-handoff` | Confirmation-gated `specified` + `po` to `ready-for-design` + `designer` handoff |
| `design-intake` | Turns design input into structured workspace-ready design context |
| `design-clarify` | Resolves unclear design requirements and interaction decisions |
| `design-start` | Confirmation-gated `ready-for-design` + `designer` to `in-design` + `designer` transition |
| `design-handoff` | Finalizes design guidance for development |
| `prep-sprint` | Read-only session view showing what is ready to build, blocked, or awaiting board review |
| `dev-clarify` | Answers open questions owned by `dev`, one feature at a time; open dev questions block `dev-start` and `dev-done` |
| `dev-start` | Confirmation-gated `ready-for-dev` + `dev` to `in-dev` + `dev` transition |
| `dev-done` | Wraps up delivery and updates project state |
| `feature-reopen` | Reopens one shipped feature through a specified impact-review route and active revalidation |
| `feature-scope` | Edits the app scope of one feature that is not `done`: its `apps`, its `## App scope` section and the requirement pages of the apps it gains |
| `board-review` | Runs a structured advisory-board review for domain-sensitive work; not for CRUD, auth, settings, or infrastructure |
| `ask` | Routes focused questions to the right delivery role |
| `audit-feature` | Reviews a feature against the workspace process and expectations |
| `feature-status` | Shows the full feature pipeline and may refresh only `WIKI_REPORT.md`; it does not change lifecycle state |
| `lint-wiki` | Checks the wiki for structure or consistency problems |
| `wiki-blockers` | Surfaces unresolved blockers from the wiki |
| `wiki-owner` | Read-only owner dashboard showing open questions, waiting work, and stale pages (last verification older than `wiki-stale-after-days`) for `po`, `designer`, `dev`, or `none` |
| `verify-pages` | Records that current-state pages were checked against their sources: one `verify` entry in `log.md`; it never edits a page |
| `wiki-app` | Focuses a feature view by app |
| `wiki-query` | Searches and summarizes wiki content |
| `wiki-show` | Opens a specific feature or wiki record |
| `document-entity` | Updates or creates backend entity documentation |
| `generate-clients` | Regenerates API clients from the shared OpenAPI contract |

### Deployment Skill

| Skill | Surface | Purpose |
|------|---------|---------|
| `deployment` | Claude, Codex | Worked examples for deploying the generated stacks: the backend container to Azure Container Apps, the web apps to Cloudflare through OpenNext, and notes on mobile store releases. The user and their agent own the cloud choice, the secrets and the deployment; the files are an example for one choice |


### Backend Skills

These skills support backend implementation. The `Surface` column shows whether the
skill is available to Claude Code, Codex, or both.

| Skill | Surface | Purpose |
|------|---------|---------|
| `spring-boot-conventions` | Claude, Codex | Core backend structure, layering, and framework usage rules |
| `security-auth` | Claude, Codex | Authentication, authorization, session, and security guidance |
| `authorization-rules` | Claude | Method-level authorization, ownership checks, and business-policy access rules beyond route security |
| `observability-and-telemetry` | Claude | Production observability guidance for logs, metrics, traces, Actuator exposure, and context propagation |
| `external-integrations-and-resilience` | Claude | Outbound client, timeout, retry, idempotency, and remote error-translation guidance |
| `auditing-and-actor-context` | Claude | Entity timestamps, actor attribution, and domain audit-trail guidance |
| `performance-and-query-shaping` | Claude | Fetch strategy, projections, specifications, pagination, and N+1 review expectations |
| `caching-strategy` | Claude | Cache suitability, TTL, invalidation, and local versus shared cache tradeoffs |
| `migration-conventions` | Claude | Reference skill for Flyway naming, SQL style, column types, constraints, and cascade guidance |
| `jpa-kotlin-patterns` | Claude | Entity modeling, persistence patterns, and Kotlin/JPA pitfalls |
| `jackson-spring-boot4` | Claude | Spring Boot 4 JSON serialization/deserialization guidance |
| `backend-feature-delivery` | Claude | Reference guidance for contract-first backend feature delivery across OpenAPI, DTOs, services, persistence, validation, and schema changes |
| `endpoint` | Codex | Add or evolve backend endpoints and align them with the API contract |
| `test-endpoint` | Claude | Generate curl and Postman requests for manual endpoint exercise; complements `testing-patterns` rather than replacing test-code guidance |
| `error-handling` | Claude, Codex | Error-code, exception, and API error-response patterns |
| `testing-patterns` | Claude, Codex | Unit and integration testing strategy for the backend |
| `code-review` | Claude | Multi-perspective review across correctness, architecture, security, performance, and maintainability across platforms |



### Web Skills

| Skill | Surface | Purpose |
|-------|---------|---------|
| `web-conventions` | Claude, Codex | The sign-in and profile slice, the generated API client, the session cookie, tests and commands of the web apps |

Start with:

- [`AGENTS.md`](../AGENTS.md) for workspace-level rules, workflow and command context
- [`docs/api/conventions.md`](api/conventions.md) for API usage rules
- [`shared/api-contracts/openapi.yml`](../shared/api-contracts/openapi.yml) for the source contract
- [`web/docs/guide.md`](../web/docs/guide.md) for the `web` slice
- the local `AGENTS.md` and `CLAUDE.md` files inside each web app



### Android Skills

| Skill | Surface | Purpose |
|------|---------|---------|
| `android-conventions` | Claude, Codex | The sign-in slice, MVVM, the client and session, strings and replacing the dev identity |
| `android-feature-delivery` | Claude, Codex | End-to-end Android feature implementation workflow |
| `android-testing` | Claude, Codex | ViewModel, client and Compose UI test patterns (JVM, Robolectric) |
| `android-build-verify` | Claude, Codex | Local build and verification checklist before handoff |
| `android-contract-alignment` | Claude, Codex | Keep the hand-written Android client and DTOs equal to the OpenAPI contract |
| `deploy-device` | Claude | Build, install, and launch an Android app on a connected device or emulator via `adb`, with `adb reverse` to the local backend |
| `compose-design-system` | Claude, Codex | Jetpack Compose design-system and UI composition guidance |



### iOS Skills

| Skill | Surface | Purpose |
|------|---------|---------|
| `ios-conventions` | Claude, Codex | The sign-in and profile slice, MVVM with Swift 6 concurrency, the API client, and replacing the local development sign-in |
| `ios-feature-delivery` | Claude, Codex | End-to-end iOS feature implementation workflow |
| `ios-testing` | Claude, Codex | Unit tests with the fake client, UI tests and the hittable wait |
| `ios-build-verify` | Claude, Codex | Local build and verification checklist before handoff |
| `ios-contract-alignment` | Claude, Codex | Keep iOS models, endpoints and the API client aligned with the OpenAPI contract |
| `swiftui-design-system` | Claude, Codex | SwiftUI screen, accessibility and Dynamic Type guidance |



### Agent Service Skills

| Skill | Surface | Purpose |
|------|---------|---------|
| `agent-conventions` | Claude, Codex | Structure, request flow, the provider interface, configuration and typing rules of the agent service |
| `add-tool` | Claude, Codex | Add a read-only tool that calls the backend with the user's own token, with its tests |
| `add-evaluation-case` | Claude, Codex | Add a case to the evaluation set and run it with the fake or the live provider |
| `agent-safety` | Claude, Codex | The safety rules, where each is enforced and tested, and how to adapt the notice to your domain |


## How To Work With The Agents

1. Start with [`AGENTS.md`](../AGENTS.md).
2. Read [`knowledge/wiki/index.md`](../knowledge/wiki/index.md) to find the pages the task needs, [`knowledge/wiki/status-board.md`](../knowledge/wiki/status-board.md) for feature status, and the relevant feature page.
3. Read the platform-local `AGENTS.md`, `CLAUDE.md`, and `docs/guide.md` files for the slice you are changing.
4. Use the command layer for lifecycle work such as setup, intake, review, and completion.
5. Use the skill folders as implementation guidance, not as a replacement for the wiki.

## When Humans Should Read This

This document is especially useful for:

- product managers who want to understand how Prism structures AI-assisted delivery
- tech leads who want to understand where rules live and how agents stay aligned
- senior engineers who want a quick map before editing commands, skills, or guidance files

## Related Docs

- [README.md](../README.md) for workspace setup and top-level navigation
- [AGENTS.md](../AGENTS.md) for the single source of agent instructions
- [docs/architecture.md](architecture.md) for platform boundaries and system design
- [knowledge/wiki/SCHEMA.md](../knowledge/wiki/SCHEMA.md) for wiki structure and operational rules
- [knowledge/wiki/LIFECYCLE.md](../knowledge/wiki/LIFECYCLE.md) for the feature, board and advisory protocol
- [knowledge/wiki/ACTIONS.md](../knowledge/wiki/ACTIONS.md) for the lifecycle action registry, approver roles and write scopes
