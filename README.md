# Multi-Platform Project Template

A [Copier](https://copier.readthedocs.io/) template for scaffolding a multi-platform monorepo with:

- **Backend**: Spring Boot 4 (Kotlin 2.2+, Java 21)
- **User Web App**: Next.js + TypeScript
- **Admin Web Portal**: Next.js + TypeScript
- **Android**: Kotlin + Jetpack Compose (MVVM)
- **iOS**: Swift + SwiftUI (MVVM)

This repository is the template itself, not a generated project.

The questionnaire keeps future-facing options visible on purpose. Some slices are more mature than others, so the safest way to use this repo today is to generate explicit sample variants and validate the output you care about.

## Current Status

| Area | Status | Notes |
|------|--------|-------|
| Template generation | Usable | `copier copy` works with the current questionnaire when required inputs are supplied. |
| Backend scaffold | Partial | Core backend files generate, but build-wrapper and lint/tooling hardening is still in progress. |
| User Web App scaffold | Partial | An initial Next.js slice now generates with routing, auth wiring, docs, and workflow/task setup, but it still needs broader validation across auth and deployment combinations. |
| Admin Web Portal scaffold | Partial | An initial Next.js admin slice now generates with dashboard/auth structure, docs, and workflow/task setup, but it is still early and needs more hardening. |
| Android scaffold | Partial | This remains one of the stronger application paths in the template. |
| iOS scaffold | Partial | Present, but naming and task-generation details still need validation. |
| Apple Sign-In | Experimental | Selectable, but not yet production-hardened. |
| Database choice | Current input | PostgreSQL is the only available choice today. |
| Backend deployment choice | Current input | Azure is the only available choice today. |
| Web deployment choice | Current input | Cloudflare via OpenNext is the only available choice today. |

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
  This powers the in-project generators under `_templates/`, such as `feature new`, `screen new`, `endpoint new`, and `page new`.

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
| **Platforms** | Which platform slices to include (multi-select) | backend, web-user-app, web-admin-portal, mobile-android, mobile-ios |
| **Auth methods** | Google, Apple, Facebook, Microsoft, Password (multi-select) | Google, Apple, Password |
| **Database** | Which database to target | PostgreSQL |
| **Docker Compose** | Include local dev services? | yes |
| **Backend deployment** | Where backend services should be deployed | Azure |
| **Web deployment** | Where web applications should be deployed | Cloudflare via OpenNext |
| **GitHub org** | GitHub organization or username | *(empty)* |

Short status notes:

- `Platforms`: backend, Android, and iOS remain the more proven paths; `web-user-app` and `web-admin-portal` now generate initial setup, but they still need broader end-to-end validation.
- `Auth methods`: Google and password are implemented; Apple remains selectable but still needs more hardening.
- `Admin Web Portal`: currently requires `password` auth when selected.
- `User Web App`: currently requires at least one auth method when selected.
- `Database`, `Backend deployment`, and `Web deployment`: implemented as questionnaire inputs, with one available option each for now.

### 3. Generate a project directly from GitHub

```bash
copier copy --trust https://github.com/mo0rti/Template.git ../my-new-project
```

The `--trust` flag is required because this template uses the `jinja2_time` Jinja extension.

Recommended first selections:

- **Backend only** for contract inspection and repository-shape validation.
- **Backend + Android** for the strongest current application path.
- **Backend + User Web App** or **Backend + Admin Web Portal** to evaluate the new initial web slices in isolation.
- **Backend + User Web App + Admin Web Portal** if you want to validate the initial web/admin setup together.
- **Backend + iOS** only if you are prepared to validate iOS generation details locally.

### 4. Generate from a local checkout

If you are contributing to the template itself, generating from a local checkout is the fastest feedback loop:

```bash
copier copy --trust . ../my-new-project
```

### 5. Generate sample projects non-interactively

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
  --data "platforms=[backend, mobile-android]" \
  . ../my-mobile-app
```

Backend plus initial web/admin setup sample:

```bash
copier copy --trust --defaults \
  --data "project_name=My Web App" \
  --data "platforms=[backend, web-user-app, web-admin-portal]" \
  . ../my-web-app
```

### 6. Update an existing generated project

Inside a generated repository:

```bash
cd /path/to/generated-project
copier update --trust
```

Use this only after reviewing template changes and only in a generated project that is already under version control.

### 7. Validate what was generated

Start with structural checks before treating the generated repo as production-ready:

- confirm the selected platform directories actually exist
- inspect the generated root `Taskfile.yml` for references to missing modules
- inspect the generated `README.md` and platform docs
- inspect `.github/workflows/` for the slices you selected
- validate the API contract with `task validate-api` if you have `go-task` installed
- generate clients with `task generate-clients` if you have the OpenAPI generator installed
- for `web-user-app` and `web-admin-portal`, inspect the generated Next.js routes, auth handlers, and OpenNext/Wrangler config before treating the setup as settled

Do not assume `task lint`, `task test`, or every multi-platform selection is validated for every combination yet.

### 8. Use generated docs as a starting point, not an absolute guarantee

Generated projects include:

- a generated `README.md`
- platform-specific docs under `docs/`, `backend/docs/`, `mobile-android/docs/`, `mobile-ios/docs/`, `web-user-app/docs/`, and `web-admin-portal/docs/`
- generated AI context files such as `AGENTS.md` and `CLAUDE.md`
- GitHub workflow files
- Hygen generators under `_templates/`
- deployment docs such as `docs/deployment/cloudflare-setup.md` when web platforms are selected

Those outputs are part of the product and still under active hardening. Validate the paths you plan to rely on.

## Practical Validation Snapshot

The following checks were confirmed during the current repository review and follow-up generation checks:

- `copier copy` works when required inputs such as `project_name` are provided.
- A generated sample with `platforms=[backend, web-user-app, web-admin-portal]` produces coherent top-level directories for those slices, shared assets, docs, task wiring, and matching workflow files.
- `web-user-app/` and `web-admin-portal/` now generate initial Next.js application structure, auth route handlers, docs, and platform Taskfiles.
- Generated backend output still needs build-wrapper and lint/tooling hardening.

This is why the recommended process starts with explicit generation choices and structural validation.

## Getting Started After Generation

Generated projects do include their own `README.md`, but the safest practical flow right now is:

1. confirm the selected platform directories exist
2. copy `.env.example` to `.env`
3. inspect the generated root `Taskfile.yml` and generated `README.md`
4. run `task validate-api` and `task generate-clients` if `go-task` and the OpenAPI generator are installed
5. validate platform-specific build, install, and run commands before treating them as settled workflow

For now, treat **backend-only**, **backend + Android**, and focused web/admin samples as the best first evaluation paths.

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
| `page new` | Scaffold a new page for generated web slices when `web-user-app` or `web-admin-portal` is included |

Typical usage inside a generated project:

```bash
npx hygen feature new
npx hygen screen new
npx hygen endpoint new
npx hygen page new
```

### GitHub Actions

The current generated workflow set includes:

| Workflow | Generated today | Purpose |
|----------|-----------------|---------|
| `api-contracts.yml` | Yes | Validate the OpenAPI contract |
| `backend.yml` | Yes | Backend test, image build, and deployment flow |
| `mobile-android.yml` | Yes | Android test, lint, build, and release flow |
| `mobile-ios.yml` | Yes | iOS test and release flow |
| `web-user-app.yml` | Yes | User web app install/build/deploy flow |
| `web-admin-portal.yml` | Yes | Admin web portal install/build/deploy flow |

## Template Structure

```text
copier.yml            # Questionnaire and generation contract
template/             # Files copied into generated projects
  .claude/            # Claude project context and slash commands
  .codex/             # Codex project context and skills
  .cursor/            # Cursor project rules
  .github/            # Workflow templates
  _templates/         # Hygen generators
  backend/            # Backend scaffold
  web-user-app/       # User-facing web scaffold
  web-admin-portal/   # Admin web scaffold
  mobile-android/            # Android scaffold
  mobile-ios/                # iOS scaffold
  shared/             # OpenAPI and design tokens
  docs/               # Generated project documentation
  infra/              # Infrastructure scripts
  README.md.jinja     # Generated-project README
  Taskfile.yml.jinja  # Generated-project root Taskfile
  AGENTS.md.jinja     # Generated-project Codex guidance
  CLAUDE.md.jinja     # Generated-project Claude guidance
README.md             # This repository guide
AGENTS.md             # Contributor guidance for this template repo
CLAUDE.md             # Claude guidance for this template repo
PLAN.md               # Architecture and intended direction
```

## Maintainer Workflow

Use this flow when changing the template itself:

1. Update `copier.yml` and/or files under `template/`.
2. Generate explicit sample variants instead of relying on assumptions.
3. Compare generated output against the root README, generated README/docs, task wiring, and the selected platform combinations.
4. Update repository docs when the template contract changes.
5. Keep roadmap-visible options honest about whether they are current, partial, experimental, or planned.

Recommended sample variants for maintainers:

- `platforms=[backend]`
- `platforms=[backend, mobile-android]`
- `platforms=[backend, mobile-ios]`
- `platforms=[backend, web-user-app]`
- `platforms=[backend, web-admin-portal]`
- `platforms=[backend, web-user-app, web-admin-portal]`
- default generation as a contract-sanity check, not as the main proof of usability

## Related Documentation

- `PLAN.md` for architecture and intended direction
- `REPOSITORY_REVIEW.md` for the latest repository review
- `REMEDIATION_PLAN.md` for the stabilization plan
- `AGENTS.md` and `CLAUDE.md` for contributor guidance in this template repo
- `copier.yml` for the questionnaire contract
- `template/README.md.jinja` for the generated-project starting guide
- `template/AGENTS.md.jinja` and `template/CLAUDE.md.jinja` for generated-project AI guidance

## Short Version

Use this repository to generate and validate targeted sample repos.

Treat **backend + Android** as the most practical evaluation path today.

Treat **User Web App** and **Admin Web Portal** as selectable, generated initial setup that now exists in the template, but is still under active hardening and should be validated locally before being treated as production-ready.

Treat **Apple Sign-In** as experimental until it is scaffolded and validated end to end.
