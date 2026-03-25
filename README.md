# Multi-Platform Project Template

A [Copier](https://copier.readthedocs.io/) template for scaffolding multi-platform monorepo projects with:

- **Backend**: Spring Boot 4 (Kotlin 2.2+)
- **Web Client**: Next.js + TypeScript
- **Admin Portal**: Next.js + TypeScript
- **Android**: Kotlin + Jetpack Compose (MVVM)
- **iOS**: Swift + SwiftUI (MVVM)

## Prerequisites

- Python 3.10+ with `pip install copier`
- [go-task](https://taskfile.dev/) — cross-platform task runner
- `npm install -g @openapitools/openapi-generator-cli` — API client generation
- `npm install -g hygen` — in-project generators
- JDK 21, Node.js LTS, Docker Desktop

For iOS development (Mac only):
- `brew install xcodegen`, Xcode, `gem install fastlane`

## Create a New Project

### Interactive mode

```bash
copier copy --trust https://github.com/YOUR_ORG/Template ./my-new-idea
```

Copier will walk you through the following questions:

| Question | Description | Default |
|----------|-------------|---------|
| **Project name** | Human-readable name (e.g., `My Awesome App`) | *(required)* |
| **Project slug** | Lowercase slug for directories | derived from name |
| **Package identifier** | Reverse-domain ID (e.g., `com.example.myapp`) | derived from slug |
| **Description** | One-line project description | `A multi-platform application` |
| **Platforms** | Which platforms to include (multi-select) | all five |
| **Auth methods** | Google, Apple, Facebook, Microsoft, Password (multi-select) | Google, Apple, Password |
| **Database** | PostgreSQL or MySQL | PostgreSQL |
| **Docker Compose** | Include local dev services? | yes |
| **GitHub org** | GitHub organization or username | *(empty)* |

### Non-interactive mode

```bash
copier copy --trust --defaults \
  --data 'project_name=My App' \
  --data 'package_identifier=com.example.myapp' \
  https://github.com/YOUR_ORG/Template ./my-app
```

> The `--trust` flag is required because the template uses the `jinja2_time` Jinja extension.

### Update an existing project with latest template changes

```bash
cd my-existing-project
copier update --trust
```

## Getting Started After Generation

### 1. Set up environment variables

```bash
cp .env.example .env
# Fill in your OAuth client IDs/secrets, database credentials, cloud keys
```

### 2. Generate typed API clients

The OpenAPI spec at `shared/api-contracts/openapi.yml` is the single source of truth for all API contracts. Generate platform clients from it:

```bash
task generate-clients
```

This produces:
- **Backend**: Spring Boot controller interfaces in `backend/src/generated/`
- **Android**: Kotlin Retrofit clients in `android/app/src/main/java/generated/`
- **iOS**: Swift URLSession clients in `ios/Generated/APIClient/`
- **Web/Admin**: TypeScript Axios clients in `shared/generated/typescript-client/`

### 3. Start local services

```bash
docker compose up -d    # PostgreSQL + Redis + backend
```

### 4. Run each platform

```bash
task backend:run         # Spring Boot on http://localhost:8080
task ios:generate-project # Generate .xcodeproj (Mac only, run once)
task ios:build           # Build iOS app
task android:build       # Build Android debug APK
```

## Available Tasks

Run `task --list` to see all available tasks. Key ones:

### Cross-platform

| Task | Description |
|------|-------------|
| `task generate-clients` | Regenerate all API clients from OpenAPI spec |
| `task validate-api` | Validate OpenAPI spec syntax |
| `task lint` | Run linters on all platforms |
| `task test` | Run all test suites |

### Backend

| Task | Description |
|------|-------------|
| `task backend:run` | Start Spring Boot dev server |
| `task backend:build` | Build JAR (skip tests) |
| `task backend:test` | Run backend tests |
| `task backend:lint` | Run ktlintCheck |
| `task backend:docker-build` | Build Docker image |

### Android

| Task | Description |
|------|-------------|
| `task android:build` | Build debug APK |
| `task android:build-release` | Build release APK |
| `task android:test` | Run unit tests |
| `task android:lint` | Run Android lint |
| `task android:install` | Install debug APK on connected device |

### iOS (Mac only)

| Task | Description |
|------|-------------|
| `task ios:generate-project` | Generate .xcodeproj from project.yml |
| `task ios:build` | Build iOS app |
| `task ios:test` | Run iOS tests |
| `task ios:clean` | Clean build artifacts |

### Infrastructure (Azure)

| Task | Description |
|------|-------------|
| `task infra:setup` | Run all Azure setup scripts sequentially |
| `task infra:update-backend` | Zero-downtime backend redeployment |
| `task infra:info` | Show deployment details |
| `task infra:check-secrets` | Validate required secrets |

## Code Generators (Hygen)

Scaffold new code within your generated project using [Hygen](https://www.hygen.io/):

### Scaffold a full feature

```bash
npx hygen feature new
# Prompts: feature name, description, primary entity
# Creates: backend entity/repo/service/controller + Android screen/viewmodel + iOS view/viewmodel + docs
```

### Add a new screen

```bash
npx hygen screen new
# Prompts: platform (android/ios), screen name, feature folder
# Creates: Screen + ViewModel with MVVM pattern
```

### Add a new web/admin page

```bash
npx hygen page new
# Prompts: target (web/admin), route, title, requires auth?
# Creates: Next.js App Router page component
```

### Add a new API endpoint

```bash
npx hygen endpoint new
# Prompts: feature module, entity, HTTP method, path
# Outputs: OpenAPI path snippet to add to openapi.yml
```

## AI Agent Commands

If you use [Claude Code](https://claude.ai/), the generated project includes custom slash commands:

| Command | Description |
|---------|-------------|
| `/scaffold-feature` | Full-guided feature development: docs, API contract, client generation, and implementation across all platforms |
| `/add-endpoint` | Add a new API endpoint: update OpenAPI spec, regenerate clients, implement backend |
| `/generate-clients` | Regenerate all platform clients after OpenAPI changes and verify builds |
| `/document-entity` | Create or update entity documentation |
| `/document-feature` | Document a feature with optional advisory board review |

## CI/CD (GitHub Actions)

The template generates GitHub Actions workflows for each platform:

| Workflow | Trigger | Actions |
|----------|---------|---------|
| **API Contracts** | Push to `shared/api-contracts/` | Validate OpenAPI spec |
| **Backend** | Push to `backend/` or `shared/` | Test, build Docker image, deploy to Azure Container Apps |
| **Web** | Push to `web/` or `shared/` | Lint, build, deploy to Cloudflare Pages |
| **Admin** | Push to `admin/` or `shared/` | Lint, build, deploy to Cloudflare Pages |
| **Android** | Push to `android/` or `shared/`, `v*` tags | Test, lint, build APK, Fastlane release to Play Store |
| **iOS** | Push to `ios/` or `shared/`, `v*` tags | Test on simulator, Fastlane release to TestFlight |

Release deployments (Android/iOS) are triggered by pushing a git tag starting with `v` (e.g., `git tag v1.0.0`).

## Template Structure

```
copier.yml          # Template questionnaire and configuration
template/           # All files that get copied to new projects
  docs/             # Living documentation (entities, features, deployment)
  shared/           # API contracts (OpenAPI), design tokens
  backend/          # Spring Boot 4 template (conditional)
  android/          # Android app template (conditional)
  ios/              # iOS app template (conditional)
  infra/            # Cloud infrastructure scripts (conditional)
  .claude/          # Claude Code context (commands, skills)
  .codex/           # OpenAI Codex context (skills)
  .cursor/          # Cursor context (rules)
  .github/          # GitHub Actions CI/CD workflows
  _templates/       # Hygen in-project generators
```

## Architecture

See [PLAN.md](PLAN.md) for the full architecture plan, design decisions, and implementation details.
