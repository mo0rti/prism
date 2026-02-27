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

## Usage

### Create a new project

```bash
copier copy https://github.com/YOUR_ORG/Template ./my-new-idea
```

### Update an existing project with latest template changes

```bash
cd my-existing-project
copier update
```

## Template Structure

```
copier.yml          # Template questionnaire and configuration
template/           # All files that get copied to new projects
  docs/             # Living documentation (entities, features, deployment)
  shared/           # API contracts (OpenAPI), design tokens
  backend/          # Spring Boot 4 template (conditional)
  web/              # Next.js web client template (conditional)
  admin/            # Next.js admin portal template (conditional)
  android/          # Android app template (conditional)
  ios/              # iOS app template (conditional)
  .claude/          # Claude Code context (commands, skills)
  .codex/           # OpenAI Codex context (skills)
  .cursor/          # Cursor context (rules)
  .github/          # GitHub Actions CI/CD workflows
  _templates/       # Hygen in-project generators
```

## Documentation

See [PLAN.md](PLAN.md) for the full architecture plan, decisions, and usage scenarios.
