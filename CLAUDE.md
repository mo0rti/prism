# Multi-Platform Project Template

Copier template that scaffolds monorepo projects with Backend (Spring Boot 4), Web (Next.js), Admin (Next.js), Android (Kotlin/Compose), and iOS (Swift/SwiftUI).

## Project Structure

```
copier.yml              # Template questionnaire (project name, platforms, auth, database)
template/               # All templated output - Jinja2 files (.jinja suffix stripped on generation)
  backend/              # Spring Boot 4 (Kotlin 2.2+, Java 21)
  android/              # Kotlin + Jetpack Compose (MVVM)
  ios/                  # Swift 6 + SwiftUI (MVVM)
  shared/               # OpenAPI 3.1 spec + design tokens
  docs/                 # Project-wide documentation (features, API, advisory board)
  .claude/              # Claude context for generated projects (commands, skills)
  .codex/               # Codex context for generated projects
  .cursor/              # Cursor rules for generated projects
  .github/              # CI/CD workflow templates
  _templates/           # Hygen in-project generators
```

## Key Rules

- **Two layers of AI context**: `template/.claude/` is for generated projects; `.claude/` (root) is for this template repo
- **Documentation organization**: Project-wide docs stay in `template/docs/`. Platform-specific technical docs live inside each platform directory (`template/android/docs/`, `template/backend/docs/`, `template/ios/docs/`). Entity docs are backend-specific (`template/backend/docs/entities/`). Platform docs are auto-excluded with their platform via `_exclude` rules.
- **Test with `copier copy`** after changes: `copier copy --trust . /tmp/test-output`

## Common Commands

```bash
# Test template generation (all platforms)
copier copy --trust . /tmp/test-output

# Test with specific options
copier copy --trust --data 'project_name=TestApp' --data 'platforms=[backend, android]' . /tmp/test-output

# Update an existing generated project
cd /path/to/generated-project && copier update --trust
```

## Reference

- @PLAN.md - full architecture plan, decisions, build progress, library versions
- `copier.yml` - template configuration and questionnaire
- `template/CLAUDE.md.jinja` - Claude context template for generated projects
- `template/AGENTS.md.jinja` - Codex context template for generated projects
