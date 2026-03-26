# Multi-Platform Project Template

A [Copier](https://copier.readthedocs.io/) template for scaffolding a multi-platform monorepo with:

- **Backend**: Spring Boot 4 (Kotlin 2.2+)
- **Web Client**: Next.js + TypeScript
- **Admin Portal**: Next.js + TypeScript
- **Android**: Kotlin + Jetpack Compose (MVVM)
- **iOS**: Swift + SwiftUI (MVVM)

This repository is the template itself, not a generated project.

The questionnaire keeps future-facing options visible on purpose. Some slices are more mature than others, so the safest way to use this repo today is to generate explicit sample variants and validate the output you care about.

## Current Status

| Area | Status | Notes |
|------|--------|-------|
| Template generation | Usable | `copier copy` works when required inputs such as `project_name` are supplied. |
| Backend scaffold | Partial | Core backend files generate, but build-wrapper and lint/tooling remediation is still in progress. |
| Android scaffold | Partial | This is currently the most believable application slice in the template. |
| iOS scaffold | Partial | Present, but naming and task-generation details are still being hardened. |
| Web scaffold | Planned | Visible in the questionnaire, but not scaffolded end to end yet. |
| Admin scaffold | Planned | Visible in the questionnaire, but not scaffolded end to end yet. |
| Apple Sign-In | Experimental | Selectable, but not yet production-hardened. |
| Database choice | Current input | PostgreSQL is the only available choice today. |
| Backend deployment choice | Current input | Azure is the only available choice today. |
| Web deployment choice | Current input | Cloudflare Pages is the only available choice today. |

If you need a fully validated all-platform starter today, this repository is not there yet.

## What This Repo Is For

- Teams evaluating the template direction before adopting it.
- Maintainers improving the scaffold itself.
- Contributors generating sample repos for specific platform combinations.

If your goal is to inspect, improve, and validate the scaffold, this repo is ready for that workflow.

## Recommended Way To Use This Repo

### 1. Install prerequisites

Start with the minimum required to generate a project, then install the rest based on the workflow you want to use.

Required to generate a project:

- Python 3.10+ with `pip install copier`
  This is required to run `copier copy` and `copier update`.

Required to use generated task commands:

- [go-task](https://taskfile.dev/)
  This runs the generated `Taskfile.yml` commands such as `task generate-clients`, `task validate-api`, `task lint`, and platform-specific tasks.

Required for shared tooling in generated projects:

- Node.js LTS
  This is needed for JavaScript-based tooling and package-managed utilities used by the generated repo.
- `npm install -g @openapitools/openapi-generator-cli`
  This validates the OpenAPI spec and generates typed API clients from it.
- `npm install -g hygen`
  This powers the in-project generators under `_templates/`, such as `feature new`, `screen new`, and `endpoint new`.

Required for platform-specific build paths:

- JDK 21
  This is required for the Spring Boot backend build and is also used by Android Gradle tooling.
- Docker Desktop
  This is useful for `docker compose` local services and Docker image workflows in generated projects.

For iOS work on macOS:

- `brew install xcodegen`
- Xcode
- `gem install fastlane`

`copier`, `go-task`, and the generator CLIs are external dependencies. They are not bundled with this repository or with generated projects.

### 2. Understand the questionnaire

Copier will walk you through the following questions:

| Question | Description | Default |
|----------|-------------|---------|
| **Project name** | Human-readable name (e.g., `My Awesome App`) | *(required)* |
| **Project slug** | Lowercase slug for directories (e.g., `my-awesome-app`) | derived from name |
| **Package identifier** | Reverse-domain ID (e.g., `com.example.myawesomeapp`) | derived from slug |
| **Description** | One-line project description | `A multi-platform application` |
| **Platforms** | Which platform slices to include (multi-select) | backend, web, admin, android, ios |
| **Auth methods** | Google, Apple, Facebook, Microsoft, Password (multi-select) | Google, Apple, Password |
| **Database** | Which database to target | PostgreSQL |
| **Docker Compose** | Include local dev services? | yes |
| **Backend deployment** | Where backend services should be deployed | Azure |
| **Web deployment** | Where web applications should be deployed | Cloudflare Pages |
| **GitHub org** | GitHub organization or username | *(empty)* |

Short status notes:

- `Platforms`: backend, Android, and iOS are the strongest current paths; web and admin remain visible as todo work.
- `Auth methods`: Google and password are implemented; Apple remains selectable but still needs more hardening.
- `Database`, `Backend deployment`, and `Web deployment`: implemented as questionnaire inputs, with one available option each for now.

### 3. Generate a project directly from GitHub

```bash
copier copy --trust https://github.com/mo0rti/Template.git ../my-new-project
```

The `--trust` flag is required because this template uses the `jinja2_time` Jinja extension.

Recommended first selections:

- **Backend only** for contract inspection and repository-shape validation.
- **Backend + Android** for the strongest current application path.
- **Backend + iOS** only if you are prepared to validate iOS generation details locally.
- **Web** and **Admin** should currently be treated as roadmap-facing selections.

### 4. Generate from a local checkout

If you are contributing to the template itself, generating from a local checkout is the fastest feedback loop:

```bash
copier copy --trust . ../my-new-project
```

### 5. Generate a sample project non-interactively

Backend-only sample:

```bash
copier copy --trust --defaults \
  --data "project_name=My Backend App" \
  --data "platforms=[backend]" \
  . ../my-backend-app
```

Backend plus Android sample:

```bash
copier copy --trust --defaults \
  --data "project_name=My Mobile App" \
  --data "platforms=[backend, android]" \
  . ../my-mobile-app
```

### 6. Update an existing generated project

Inside a generated repository:

```bash
copier update --trust
```

Use this only after reviewing template changes and only in a generated project that is already under version control.

### 7. Validate what was generated

Start with structural checks before treating the generated repo as production-ready:

- confirm the selected platform directories actually exist
- inspect the generated root `Taskfile.yml` for references to missing modules
- inspect the generated `README.md` and platform docs
- validate the API contract with `task validate-api` if you have `go-task` installed
- generate clients with `task generate-clients` if you have the OpenAPI generator installed

Do not assume `task lint`, `task test`, or the default all-platform selection are validated for every combination yet.

### 8. Use generated docs as a starting point, not an absolute guarantee

Generated projects include:

- a generated `README.md`
- platform-specific docs under `docs/`, `backend/docs/`, `android/docs/`, and `ios/docs/`
- generated AI context files such as `AGENTS.md` and `CLAUDE.md`
- GitHub workflow files
- Hygen generators under `_templates/`

Those outputs are part of the product and still under active hardening. Validate the paths you plan to rely on.

## Practical Validation Snapshot

The following checks were confirmed during the current repository review:

- `copier copy` works when `project_name` is provided.
- Backend-only generation produces a coherent directory set.
- Default generation still produces root `web` and `admin` task references without corresponding generated directories.
- Generated backend output still lacks the wrapper scripts expected by backend task documentation.
- `go-task` was not installed in the current review environment, so task-based flows were validated structurally rather than executed here.

This is why the recommended process starts with explicit generation choices and structural validation.

## Getting Started After Generation

Generated projects do include their own `README.md`, but the safest practical flow right now is:

1. confirm the selected platform directories exist
2. copy `.env.example` to `.env`
3. inspect the generated root `Taskfile.yml` and generated `README.md`
4. run `task validate-api` and `task generate-clients` if `go-task` and the OpenAPI generator are installed
5. validate platform-specific build/run commands before treating them as settled workflow

For now, treat **backend-only** and **backend + Android** as the best first evaluation paths.

## Generated Project Capabilities

### AI Agent Commands

Generated projects include agent context for Claude, Codex, and Cursor. Explicit slash commands are currently templated for Claude under `.claude/commands/`:

| Command | Purpose |
|---------|---------|
| `/scaffold-feature` | Guide feature delivery across the generated slices that exist in the project |
| `/add-endpoint` | Add an API endpoint and update the contract/backend scaffolding |
| `/generate-clients` | Regenerate platform clients after OpenAPI changes |
| `/document-entity` | Create or refine backend entity documentation |
| `/document-feature` | Create or refine feature documentation |

### Code Generators

Generated projects currently include these Hygen generators under `_templates/`:

| Generator | Purpose |
|-----------|---------|
| `feature new` | Scaffold a backend + Android + iOS feature slice and related docs |
| `screen new` | Scaffold a new Android or iOS screen |
| `endpoint new` | Scaffold an OpenAPI path snippet and backend endpoint starter |

Typical usage inside a generated project:

```bash
npx hygen feature new
npx hygen screen new
npx hygen endpoint new
```

The `page` generator still exists in the template repo, but it is not part of the current generated output.

### GitHub Actions

The current generated workflow set includes:

| Workflow | Generated today | Purpose |
|----------|-----------------|---------|
| `api-contracts.yml` | Yes | Validate the OpenAPI contract |
| `backend.yml` | Yes | Backend test, image build, and deployment flow |
| `android.yml` | Yes | Android test, lint, build, and release flow |
| `ios.yml` | Yes | iOS test and release flow |
| `web.yml` | No | Still roadmap-facing in current generated output |
| `admin.yml` | No | Still roadmap-facing in current generated output |

## Template Structure

```text
copier.yml          # Questionnaire and generation contract
template/           # Files copied into generated projects
  .claude/          # Claude project context and slash commands
  .codex/           # Codex project context and skills
  .cursor/          # Cursor project rules
  .github/          # Workflow templates
  _templates/       # Hygen generators
  backend/          # Backend scaffold
  android/          # Android scaffold
  ios/              # iOS scaffold
  shared/           # OpenAPI and design tokens
  docs/             # Generated project documentation
  infra/            # Infrastructure scripts
  README.md.jinja   # Generated-project README
  Taskfile.yml.jinja # Generated-project root Taskfile
  AGENTS.md.jinja   # Generated-project Codex guidance
  CLAUDE.md.jinja   # Generated-project Claude guidance
README.md           # This repository guide
AGENTS.md           # Contributor guidance for this template repo
CLAUDE.md           # Claude guidance for this template repo
PLAN.md             # Architecture and intended direction
```

There is intentionally no `template/web/` or `template/admin/` directory yet. Those options remain visible in the questionnaire as roadmap-facing product surfaces, not as full generated slices today.

## Maintainer Workflow

Use this flow when changing the template itself:

1. Update `copier.yml` and/or files under `template/`.
2. Generate explicit sample variants instead of relying on assumptions.
3. Compare generated output against the root README, generated README/docs, task wiring, and the selected platform combinations.
4. Update repository docs when the template contract changes.
5. Keep roadmap-visible options honest about whether they are current, partial, experimental, or planned.

Recommended sample variants for maintainers:

- `platforms=[backend]`
- `platforms=[backend, android]`
- `platforms=[backend, ios]`
- default generation as a contract-sanity check, not as the main proof of usability

## Related Documentation

- `PLAN.md` for architecture and intended direction
- `AGENTS.md` and `CLAUDE.md` for contributor guidance in this template repo
- `copier.yml` for the questionnaire contract
- `template/README.md.jinja` for the generated-project starting guide
- `template/AGENTS.md.jinja` and `template/CLAUDE.md.jinja` for generated-project AI guidance

## Short Version

Use this repository to generate and validate targeted sample repos.

Treat **backend + Android** as the most practical evaluation path today.

Treat **web**, **admin**, and **Apple Sign-In** as visible roadmap or experimental options until they are scaffolded and validated end to end.
