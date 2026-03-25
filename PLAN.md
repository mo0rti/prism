# Multi-Platform Project Templating System - Implementation Plan

> **Date**: February 2026
> **Status**: In Progress
> **Purpose**: Reference document for the multi-platform template architecture, decisions, and usage workflows.

---

## Context

This is a reusable template repository that scaffolds complete multi-platform projects (Android, iOS, backend, web, admin) in minutes. It encodes all architectural decisions once, so AI agents (Claude Code, Codex, Cursor) can generate a fully wired monorepo for any new idea.

**Environment:**
- **Primary dev machine: Windows** - all platforms except iOS must be fully developable on Windows
- **iOS development: Mac only** (Xcode requirement) - iOS code lives in the monorepo but builds only on Mac
- **Backend/DB/AI services: Azure** (Container Apps, Azure DB for PostgreSQL, Azure AI Services)
- **Web hosting: Cloudflare** (Pages for web/admin, Workers if needed)
- **AI coding tools: Claude Code, Codex, Cursor** - all three need context
- **Architecture: MVVM consistently** across both Android and iOS
- **Backend: Spring Boot 4** (released Nov 2025, requires Kotlin 2.2+, Java 17+/21 recommended, Jackson 3.x, JUnit Jupiter 6, Jakarta EE 11)
- **Auth: OAuth (Google, Apple, Facebook, Microsoft) + optional username/password**

---

## What is Jinja2?

Jinja2 is the templating language used by Copier. Files ending in `.jinja` contain placeholders like `{{ project_name }}` that get replaced with real values when you scaffold a project. After generation, the `.jinja` suffix is stripped. Conditional blocks like `{% if "android" in platforms %}` control which directories/code are included.

---

## Key Decisions

| Decision | Choice | Why |
|----------|--------|-----|
| Template engine | **Copier** | `copier update` pushes template improvements to existing projects; YAML config; cross-platform |
| Architecture | **Monorepo** | AI agents see everything; atomic cross-platform changes |
| Mobile architecture | **MVVM on both Android and iOS** | Consistent mental model; ViewModel + UiState pattern on both |
| API contract | **OpenAPI 3.1 + openapi-generator** | One YAML -> typed clients for Kotlin, Swift, TypeScript |
| Build orchestration | **Taskfile (go-task)** | Cross-platform (Windows/Mac/Linux); simpler than Make |
| iOS project gen | **XcodeGen** | Template `project.yml`, generate `.xcodeproj` on Mac only |
| Backend | **Spring Boot 4** (Kotlin 2.2+, Java 21) | Latest stable, improved startup, modular auto-config |
| Auth | **OAuth (Google/Apple/Facebook/Microsoft) + optional password** | Spring Security OAuth2 Client + optional form login |
| Backend hosting | **Azure Container Apps** | Cloud choice |
| Database | **Azure Database for PostgreSQL** | Managed, Azure-native |
| Web hosting | **Cloudflare Pages** | Hosting choice |
| Documentation | **Living docs in `docs/`** | Entities, deployment, business logic - AI context |

---

## Cross-Platform Windows/Mac Compatibility

### What works on Windows
- **Backend** (Spring Boot/Kotlin): Gradle via `gradlew.bat`
- **Web + Admin** (Next.js): Node.js, fully cross-platform
- **Android**: Android Studio + Gradle natively on Windows
- **Shared/API contracts**: openapi-generator is Java-based, runs everywhere
- **Taskfile**: go-task has native Windows binaries
- **All AI agents**: Claude Code, Codex, Cursor all work on Windows
- **Docker**: Docker Desktop for Windows

### What requires Mac
- **iOS build/run**: Xcode, xcodegen, xcodebuild, Fastlane - Mac only
- **iOS Taskfile tasks**: Guarded with `platforms: [darwin]`, skip gracefully on Windows

### Client generation
Cross-platform Taskfile task calls `openapi-generator-cli` (Java). iOS client generation works on Windows - you just can't compile it without Xcode.

---

## Authentication Architecture

Auth is configurable per project via `copier.yml`:

```yaml
auth_methods:
  type: yaml
  multiselect: true
  help: "Which authentication methods?"
  choices:
    Google OAuth: google
    Apple Sign-In: apple
    Facebook Login: facebook
    Microsoft Account: microsoft
    Username + Password: password
  default: "[google, apple, password]"
```

**Backend implementation (Spring Boot 4):**
- Spring Security OAuth2 Client for social providers
- Each provider configured via `application.yml` with `${GOOGLE_CLIENT_ID}` env vars
- Optional password auth via Spring Security's form login + BCrypt
- All providers issue the same JWT token format after successful auth
- `SecurityConfig.kt.jinja` conditionally wires each provider based on `auth_methods`

**Client implementation (all platforms):**
- Each client shows login screen with enabled provider buttons
- OAuth flow: client opens provider's auth URL -> gets auth code -> sends to backend -> backend exchanges for token -> returns JWT
- Password flow: client sends credentials -> backend validates -> returns JWT
- Same token storage mechanism regardless of provider

---

## Advisory Board System

A virtual advisory board provides AI agents with stakeholder perspectives to evaluate features before implementation. When scaffolding a new project, you provide a `board.md` file describing your advisors.

### How it works

**`docs/advisory-board.md`** - provided by you when creating the project:

```markdown
# Advisory Board

## Members

### Sarah Chen - Chief Product Officer
- **Expertise**: Product strategy, user experience, market fit
- **Focus**: Does this feature serve the target user? Is the UX intuitive? What's the MVP?
- **Challenge lens**: "Is this solving a real problem or a nice-to-have?"

### Marcus Rivera - CTO / Architecture Lead
- **Expertise**: System design, scalability, technical debt
- **Focus**: Is this architecturally sound? Will it scale? What are the maintenance costs?
- **Challenge lens**: "What breaks at 100x scale? What's the simplest solution?"

### Aisha Patel - Security & Compliance Officer
- **Expertise**: InfoSec, data privacy, GDPR/SOC2, authentication
- **Focus**: Is user data protected? Are there compliance implications?
- **Challenge lens**: "What happens if this gets breached? What data are we exposing?"

### David Kim - Business & Revenue Strategist
- **Expertise**: Monetization, growth metrics, unit economics
- **Focus**: How does this feature drive revenue or retention?
- **Challenge lens**: "What's the ROI? How do we measure success?"
```

### Integration with AI tools

**Claude Code skill** (`.claude/skills/advisory-review/SKILL.md`):
```yaml
---
name: advisory-review
description: Review a feature proposal with the virtual advisory board
---
```
When triggered, the skill reads `docs/advisory-board.md`, adopts each persona sequentially, and generates structured feedback.

**Codex skill** (`.codex/skills/advisory-review/SKILL.md`): Same concept, adapted for Codex's format.

**Cursor rule** (`.cursor/rules/advisory-review.mdc`): Agent Requested rule that triggers when discussing feature design.

### Workflow
1. You describe a new feature idea
2. AI runs `/advisory-review` (Claude) or `$advisory-review` (Codex)
3. Each board member "responds" with their perspective
4. You decide based on synthesized feedback
5. Feature doc is created with "Board Review" section capturing the decision

---

## AI Agent Context - Correct Structure per Tool

### Claude Code (reads `CLAUDE.md`, uses `.claude/`)

```
CLAUDE.md                              # Root - architecture, conventions, commands
.claude/
  commands/                            # Manual slash commands (/name)
    scaffold-feature.md                # /scaffold-feature
    generate-clients.md                # /generate-clients
    add-endpoint.md                    # /add-endpoint
    document-entity.md                 # /document-entity
    document-feature.md                # /document-feature
  skills/                              # Auto-invoked based on description
    advisory-review/
      SKILL.md                         # Board review skill (auto-triggers on feature discussions)
    code-review/
      SKILL.md                         # Multi-perspective code review
  settings.json                        # Hooks, permissions
backend/CLAUDE.md                      # Lazy-loaded when working in backend/
web/CLAUDE.md                          # Lazy-loaded when working in web/
admin/CLAUDE.md                        # Lazy-loaded when working in admin/
android/CLAUDE.md                      # Lazy-loaded when working in android/
ios/CLAUDE.md                          # Lazy-loaded when working in ios/
```

**Key**: CLAUDE.md files are hierarchical. Root loads on startup; subdirectory files lazy-load when Claude touches those files. Keep root under 100 lines, point to `docs/` for details.

### OpenAI Codex (reads `AGENTS.md`, uses `.codex/`)

```
AGENTS.md                              # Root - mirrors CLAUDE.md content
.codex/
  skills/                              # Auto-invoked based on description
    advisory-review/
      SKILL.md                         # Board review (same concept as Claude skill)
    scaffold-feature/
      SKILL.md                         # Feature scaffolding
    generate-clients/
      SKILL.md                         # API client generation
backend/AGENTS.md                      # Backend-specific instructions
web/AGENTS.md                          # Web-specific instructions
android/AGENTS.md                      # Android-specific instructions
ios/AGENTS.md                          # iOS-specific instructions
```

**Key**: AGENTS.md files concatenate root-to-leaf (up to 32KB). Codex skills use `$skill-name` syntax or auto-invoke based on description in SKILL.md frontmatter.

### Cursor (reads `.cursor/rules/*.mdc`, also reads `AGENTS.md`)

```
.cursor/
  rules/
    project.mdc                        # alwaysApply: true - global conventions
    backend.mdc                        # globs: "backend/**" - auto-attached for backend files
    web.mdc                            # globs: "web/**,admin/**" - auto-attached for web files
    android.mdc                        # globs: "android/**" - auto-attached for Android files
    ios.mdc                            # globs: "ios/**" - auto-attached for iOS files
    advisory-review.mdc                # description: "Review feature..." - agent requested
    api-conventions.mdc                # globs: "shared/api-contracts/**" - OpenAPI rules
```

**Key**: `.cursorrules` is deprecated. Use `.cursor/rules/*.mdc` with four rule types:
- **Always** (`alwaysApply: true`): loaded every prompt
- **Auto Attached** (`globs: "pattern"`): loaded when matching files are in context
- **Agent Requested** (`description: "..."`): AI decides when to use
- **Manual**: only when you `@mention` it

### Keeping Content in Sync

Since Claude reads `CLAUDE.md`, Codex reads `AGENTS.md`, and Cursor reads `.mdc` files, we avoid maintaining 3x copies:

1. **`docs/` is the single source of truth** for all substantive documentation
2. **CLAUDE.md and AGENTS.md** are thin pointers (~50-100 lines each): architecture summary + common commands + `@docs/` references
3. **`.cursor/rules/*.mdc`** files contain only rule metadata + brief conventions; reference `docs/` for details
4. **A Taskfile task `sync-ai-context`** validates that all three files reference the same docs and flags drift

---

## Documentation Strategy (Critical for AI Context)

```
docs/
  architecture.md              # System overview, platform map, tech decisions, MVVM
  advisory-board.md            # Virtual advisory board (provided at project creation)
  entities/
    _template.md               # Entity doc template
    user.md                    # User entity: fields, relationships, validation, business logic
    example.md                 # Example entity (placeholder)
  deployment/
    azure-setup.md             # Azure Container Apps, PostgreSQL, AI Services, Key Vault
    cloudflare-setup.md        # Cloudflare Pages config, env vars, build settings
    ci-cd.md                   # GitHub Actions pipelines, required secrets
  features/
    _template.md               # Feature doc template (includes Board Review section)
    auth.md                    # Auth: OAuth providers, password flow, token lifecycle
    example-feature.md         # Example feature (placeholder)
  api/
    conventions.md             # Naming, pagination, error format, versioning
  platform-guides/
    android.md                 # MVVM patterns, Hilt, Compose, testing
    ios.md                     # MVVM patterns, SwiftUI, testing
    web.md                     # Next.js patterns, Cloudflare deployment
    backend.md                 # Spring Boot 4 patterns, Azure deployment
```

**Feature doc template includes Board Review section:**
```markdown
# Feature: [Name]

## Board Review
- **Product (Sarah)**: [approval/concerns]
- **Architecture (Marcus)**: [approval/concerns]
- **Security (Aisha)**: [approval/concerns]
- **Business (David)**: [approval/concerns]
- **Decision**: [Go / Rework / Defer]

## Business Logic
## Entities
## API Endpoints
## Platform Implementation Status
- [ ] API contract defined
- [ ] Backend implemented
- [ ] Web implemented
- [ ] Admin implemented
- [ ] Android implemented
- [ ] iOS implemented
```

---

## Implementation Plan

### Phase 1: Template Repository Foundation

**Files to create:**
- `copier.yml` - Questionnaire: project_name, project_slug, package_identifier, description, platforms (multiselect), auth_methods (multiselect), database, use_docker, github_org (cloud_provider=azure and web_hosting=cloudflare are hardcoded)
- `README.md` - Template maintainer instructions
- `.gitignore`
- `template/` - All templated output (via `_subdirectory: template`)
- `template/README.md.jinja`
- `template/.gitignore.jinja` - Combined gitignore (all platforms + Windows/macOS/Linux)
- `template/Taskfile.yml.jinja` - Root task runner; iOS tasks guarded with `platforms: [darwin]`
- `template/.env.example.jinja` - Azure + Cloudflare + OAuth env vars
- `template/.editorconfig`

### Phase 2: Documentation Skeleton + Shared Infrastructure

**`template/docs/`:**
- architecture.md.jinja, advisory-board.md.jinja
- entities/_template.md, user.md.jinja, example.md.jinja
- deployment/azure-setup.md.jinja, cloudflare-setup.md.jinja, ci-cd.md.jinja
- features/_template.md, auth.md.jinja, example-feature.md.jinja
- api/conventions.md.jinja
- platform-guides/android.md.jinja, ios.md.jinja, web.md.jinja, backend.md.jinja

**`template/shared/`:**
- api-contracts/openapi.yml.jinja - OpenAPI 3.1 with auth + example CRUD
- api-contracts/.openapi-generator-ignore
- design-tokens/tokens.json.jinja, README.md

### Phase 3: Platform Templates

#### 3A: Backend (Spring Boot 4 / Kotlin 2.2+)
Directory: `template/{% if "backend" in platforms %}backend{% endif %}/`

- `build.gradle.kts.jinja` - Spring Boot 4.0.x, Kotlin 2.2+, Java 21, Spring Security OAuth2 Client, JPA, Flyway, SpringDoc, Jackson 3.x, JUnit Jupiter 6
- `Taskfile.yml` - run, build, test, lint (cross-platform via gradlew/gradlew.bat)
- `Dockerfile.jinja` - Multi-stage, targets Azure Container Apps
- `src/main/kotlin/{{package_path}}/`
  - `Application.kt.jinja`
  - `bootstrap/SecurityConfig.kt.jinja` - Conditionally wires OAuth providers + optional password auth
  - `bootstrap/WebConfig.kt.jinja` - CORS for Cloudflare-hosted frontends
  - `bootstrap/OpenApiConfig.kt.jinja` - SpringDoc/Swagger config
  - `bootstrap/OAuth2Config.kt.jinja` - OAuth2 client registration per provider
  - `bootstrap/security/JwtTokenProvider.kt.jinja`, `JwtAuthenticationFilter.kt.jinja`
  - `shared/exception/ApiException.kt.jinja`, `GlobalExceptionHandler.kt.jinja`
  - `shared/model/ApiErrorResponse.kt.jinja`, `PagedResponse.kt.jinja`
  - `shared/audit/AuditableEntity.kt.jinja`
  - `modules/auth/` - controller, dto, model, repository, service
  - `modules/example/` - Controller, Service, Repository, Entity, DTOs
- `src/main/resources/application.yml.jinja` - Azure PostgreSQL, OAuth env vars, JWT config
- `src/main/resources/db/migration/V1__init.sql.jinja`
- `src/test/kotlin/` - Tests
- `CLAUDE.md.jinja`, `AGENTS.md.jinja`

#### 3B: Web Client (Next.js + TypeScript)
Directory: `template/{% if "web" in platforms %}web{% endif %}/`

- `package.json.jinja`, `next.config.ts.jinja` (Cloudflare compatible), `wrangler.toml.jinja`
- `tailwind.config.ts.jinja`, `tsconfig.json`, `Taskfile.yml`
- `src/app/` - Auth pages (OAuth buttons + optional login form), dashboard, example CRUD
- `src/lib/api/client.ts.jinja` - Axios with Bearer interceptor
- `src/lib/auth/` - AuthContext, AuthProvider, ProtectedRoute
- `src/components/`, `src/types/`
- `CLAUDE.md.jinja`, `AGENTS.md.jinja`

#### 3C: Admin Portal (Next.js + TypeScript)
Directory: `template/{% if "admin" in platforms %}admin{% endif %}/`

Same as web + sidebar layout, data tables, stat cards, admin role guard, separate `wrangler.toml.jinja`

#### 3D: Android (Kotlin + Jetpack Compose) - MVVM
Directory: `template/{% if "android" in platforms %}android{% endif %}/`

```
core/         -> DI modules, networking, database, datastore, models
feature/      -> Feature modules (auth, example) with ui + data + domain
designsystem/ -> Theme, components, text utilities
navigation/   -> NavGraph + Screen routes
```

- `build.gradle.kts.jinja` - Compose BOM, Hilt, Retrofit, Room
- `Taskfile.yml` - cross-platform (gradlew.bat on Windows)
- Full MVVM structure with auth (OAuth + password), example screens
- `CLAUDE.md.jinja`, `AGENTS.md.jinja`

#### 3E: iOS (Swift + SwiftUI) - MVVM (matching Android)
Directory: `template/{% if "ios" in platforms %}ios{% endif %}/`

```
UI/           -> View layer (SwiftUI views)
ViewModel/    -> ViewModels with ViewState (@Observable)
Domain/       -> Use cases (mirrors Android)
Data/         -> Repositories, API client, local storage
DI/           -> Dependency container
Navigation/   -> Router + routes
```

- `project.yml.jinja` - XcodeGen spec (Mac-only)
- `Taskfile.yml` - guarded with `platforms: [darwin]`
- Full MVVM structure mirroring Android's pattern
- `CLAUDE.md.jinja`, `AGENTS.md.jinja`

**MVVM consistency:**

| Concept | Android | iOS |
|---------|---------|-----|
| View | `@Composable` functions | SwiftUI `View` structs |
| ViewModel | `@HiltViewModel` + `StateFlow<UiState>` | `@Observable` + `ViewState` enum |
| UiState | Sealed class: Idle, Loading, Success, Error | Enum: idle, loading, success, error |
| DI | Hilt (`@Inject`) | Protocol-based via `.environment()` |
| Repository | Concrete classes, Hilt `@Inject` constructor | Concrete classes, container-injected |
| Navigation | Jetpack Navigation Compose | NavigationStack + navigationDestination |

### Phase 4: AI Context Layer

**Claude Code**: CLAUDE.md + commands + skills (see AI Agent Context section above)
**Codex**: AGENTS.md + skills
**Cursor**: .cursor/rules/*.mdc

### Phase 5: CI/CD and Infrastructure

**GitHub Actions** with path-based triggers per platform:
- backend.yml -> Azure Container Registry -> Azure Container Apps
- web.yml, admin.yml -> Cloudflare Pages via Wrangler
- android.yml -> Fastlane -> Google Play
- ios.yml -> macOS runner -> Fastlane -> TestFlight
- api-contracts.yml -> validate OpenAPI spec

**Infrastructure**: docker-compose.yml, Azure Bicep templates, Fastlane configs

### Phase 6: Hygen In-Project Generators

`_templates/` with generators for: feature, endpoint, screen, page

---

## Usage Guide: How to Use This Template

### Scenario 1: Starting a New Project from an Idea

**When**: You have a new app idea and want to go from zero to working codebase.

#### Step 1: Prepare Your Inputs
1. **A one-paragraph description** of your idea (what it does, who it's for)
2. **Your advisory board file** (`board.md`) - personas who will evaluate features
3. **OAuth credentials** - register with Google, Apple, Facebook, Microsoft (can be done later)

#### Step 2: Scaffold the Project
```bash
copier copy https://github.com/YOUR_ORG/Template ./my-new-idea

# Copier asks interactively:
# - Project name? -> "FoodieHub"
# - Slug? -> "foodiehub"
# - Package ID? -> "com.example.foodiehub"
# - Description? -> "A restaurant discovery and booking platform"
# - Platforms? -> [backend, web, admin, android, ios]
# - Auth methods? -> [google, apple, password]
# - Use Docker? -> yes
# - GitHub org? -> "my-org"
```

#### Step 3: Set Up Your Project
```bash
cd my-new-idea

# 1. Copy your advisory board
cp ~/my-boards/foodiehub-board.md ./docs/advisory-board.md

# 2. Initialize git
git init && git add -A && git commit -m "Initial scaffold from template"

# 3. Copy .env.example and fill in your values
cp .env.example .env
# Edit .env: add Azure connection strings, OAuth client IDs, etc.

# 4. Generate typed API clients from OpenAPI spec
task generate-clients

# 5. Start local development
docker compose up -d          # PostgreSQL + backend
task backend:run              # Spring Boot on :8080
task web:dev                  # Next.js on :3000
```

#### Step 4: Verify
Open `http://localhost:3000` - login page with OAuth buttons + optional password form. Example CRUD pages work end-to-end.

#### Step 5: Start Building
See Scenario 2.

---

### Scenario 2: Adding a New Feature

**When**: You want to add a new capability (e.g., "restaurant listings", "payment processing").

#### Using Claude Code
```bash
claude

# Option A: Use the command
> /scaffold-feature

# Option B: Describe naturally - advisory-review skill auto-triggers
> I want to add a restaurant listing feature. Users should browse by
> cuisine, location, and rating. Restaurant owners manage their listings.
```

#### What the AI agent does (in order):
1. **Advisory Board Review** - each board member evaluates the feature
2. **Creates feature doc** -> `docs/features/restaurant-listings.md`
3. **Creates entity docs** -> `docs/entities/restaurant.md`, `docs/entities/review.md`
4. **Updates OpenAPI spec** -> new endpoints in `shared/api-contracts/openapi.yml`
5. **Regenerates API clients** -> `task generate-clients`
6. **Implements backend** -> controller, service, repository, entity, Flyway migration
7. **Implements web** -> pages, API client calls, components
8. **Implements admin** -> management pages, data tables
9. **Implements Android** -> Screen + ViewModel (MVVM)
10. **Implements iOS** -> View + ViewModel (MVVM)
11. **Updates feature doc status** -> checks off completed platforms

#### Using Codex
```bash
codex
> $scaffold-feature
```

#### Using Cursor
Open in Cursor, `.cursor/rules/` auto-load. Describe the feature in chat.

---

### Scenario 3: Modifying an Existing Feature

**When**: Change behavior, add a field, update business logic, or fix a bug.

#### For significant modifications
```bash
# In Claude Code:
> I need to modify the restaurant listing feature. Add a "verified" badge
> for inspected restaurants. Update the feature doc first, then implement.
```

The AI will:
1. Read existing docs
2. Update entity doc (add `verified` field)
3. Update feature doc (add verification business logic)
4. Run advisory board review (optional for small changes)
5. Update OpenAPI spec
6. Regenerate clients
7. Add Flyway migration
8. Update backend + all client platforms

#### For small modifications (bug fixes, UI tweaks)
```bash
> The restaurant list on Android isn't showing rating stars correctly.
> The ViewModel maps rating as Int but should be Float.
```

#### For cross-platform changes
```bash
> Change the restaurant card design across all platforms. Title larger,
> add subtitle with cuisine type, show distance if location available.
```

---

### Scenario 4: Adding a New API Endpoint

```bash
> /add-endpoint

# Or describe it:
> Add GET /restaurants/nearby with latitude, longitude, radius params.
> Return paginated list sorted by distance.
```

The AI adds to OpenAPI spec -> generates clients -> implements backend.

---

### Scenario 5: Adding a New Screen/Page (Single Platform)

```bash
# Android:
> Add "Favorites" screen showing saved restaurants in LazyColumn with
> swipe-to-remove. Follow MVVM pattern in docs/platform-guides/android.md.

# iOS:
> Add "Favorites" view matching Android. Use docs/platform-guides/ios.md.

# Web:
> Add /favorites page with grid layout and remove button.
```

---

### Scenario 6: Consulting the Advisory Board

```bash
> Review this idea with the advisory board: Adding a subscription tier
> for restaurant owners with analytics and promoted placement.

# Also works for non-feature decisions:
> Should we add dark mode now or wait for more users?
> Should we switch from REST to GraphQL for mobile?
```

---

### Scenario 7: Onboarding a New AI Session (Context Recovery)

**Happens automatically:**
- Claude Code reads `CLAUDE.md` on startup
- Codex reads `AGENTS.md` hierarchy
- Cursor loads `.cursor/rules/project.mdc` (always) + platform rules

All point to `docs/` for deep context. If AI seems confused:
```bash
> Read docs/architecture.md and docs/features/ to understand current state.
```

---

### Scenario 8: Deploying to Production

#### Backend (Azure)
```bash
cd infra/azure
az deployment group create --resource-group myapp-rg --template-file main.bicep
# Subsequent: automatic on merge to main, or `task backend:deploy`
```

#### Web + Admin (Cloudflare)
```bash
cd web && npx wrangler pages project create foodiehub-web
# Subsequent: automatic on merge to main, or `task web:deploy`
```

#### Mobile
```bash
git tag -a v1.0.0 -m "First release" && git push origin v1.0.0
# GitHub Actions -> Fastlane -> Play Store / TestFlight
```

---

### Scenario 9: Updating Template in Existing Projects

```bash
cd my-existing-project
copier update
# Shows diff, accept/reject changes, custom code preserved
```

---

### Scenario 10: Working Across Windows and Mac

**Windows (daily):** Backend, web, admin, Android all work. iOS code generated but can't compile.
**Mac (iOS):** Pull latest -> `task ios:generate-project` -> `task ios:build` -> Xcode.
**CI/CD:** iOS uses `runs-on: macos-latest`, everything else `ubuntu-latest`.

---

## Quick Reference: Commands

| Action | Command |
|--------|---------|
| Generate API clients | `task generate-clients` |
| Start local dev | `docker compose up -d && task backend:run` |
| Web dev server | `task web:dev` |
| Admin dev server | `task admin:dev` |
| Build Android APK | `task android:build` |
| Build iOS (Mac) | `task ios:generate-project && task ios:build` |
| Run all tests | `task test` |
| Lint all | `task lint` |
| Deploy backend | `task backend:deploy` |
| Deploy web | `task web:deploy` |
| Scaffold feature (Claude) | `/scaffold-feature` |
| Scaffold feature (Codex) | `$scaffold-feature` |
| Advisory board review | Auto-triggers, or `/advisory-review` |
| Document entity (Claude) | `/document-entity` |
| Document feature (Claude) | `/document-feature` |
| Update from template | `copier update` |

## Quick Reference: AI Context Files

| File | Tool | Purpose |
|------|------|---------|
| `CLAUDE.md` | Claude Code | Architecture, conventions, commands |
| `AGENTS.md` | Codex + Cursor | Architecture, conventions |
| `.claude/commands/*.md` | Claude Code | Manual slash commands |
| `.claude/skills/*/SKILL.md` | Claude Code | Auto-invoked skills |
| `.codex/skills/*/SKILL.md` | Codex | Auto-invoked skills |
| `.cursor/rules/*.mdc` | Cursor | Typed rules (Always, Auto, Agent, Manual) |
| `docs/` | All tools | Single source of truth |
| `docs/advisory-board.md` | All tools | Virtual advisory board |

---

## Build Order & Progress

| # | Phase | Status |
|---|-------|--------|
| 1 | `copier.yml` + `template/` skeleton | **Done** |
| 2 | `docs/` skeleton + `shared/` (OpenAPI, design tokens) | **Done** |
| 3A | Backend (Spring Boot 4, Kotlin 2.2+, Java 21) | **Done** |
| 3B | Web client (Next.js + TypeScript) | Pending |
| 3C | Admin portal (Next.js + TypeScript) | Pending |
| 3D | Android (Kotlin + Jetpack Compose, MVVM, Room) | **Done** |
| 3E | iOS (Swift 6 + SwiftUI, MVVM, SwiftData) | **Done** |
| 4 | AI context layer (CLAUDE.md, AGENTS.md, commands, skills, Cursor rules) | **Done** |
| 5 | CI/CD workflows + infrastructure templates | **Done** |
| 6 | Hygen in-project generators | **Done** |

### Library Versions (as of Mar 2026)

**Android:**
- AGP 8.9.1, Kotlin 2.3.10, Compose BOM 2026.01.01, Hilt 2.57.2
- Retrofit 3.0.0, Room 2.8.4
- Gradle 8.13

**iOS:**
- Swift 6.0, Xcode 26, iOS 17.0 min
- SwiftData for local persistence
- Keychain (Security framework) for token storage

**Backend:**
- Spring Boot 4.0.1, Kotlin 2.2+, Java 21
- JJWT 0.12.6, Jackson 3.x, JUnit Jupiter 6

## Prerequisites

**Windows:** Python 3.10+ (copier), go-task, openapi-generator-cli, hygen, Docker Desktop, JDK 21, Node.js LTS, Android Studio

**Mac (iOS only):** All above + xcodegen, Xcode, fastlane

## Verification

1. `copier copy` with all platforms -> all present
2. `copier copy` without iOS -> iOS absent
3. Backend `gradlew.bat build` -> compiles
4. Web `npm run build` -> compiles
5. `task generate-clients` -> all clients generated
6. `docker compose up` -> running
7. Android `gradlew.bat assembleDebug` -> APK
8. iOS (Mac) `xcodebuild build` -> compiles
9. AI context loads correctly in all three tools
10. `/scaffold-feature` creates docs + code across platforms
