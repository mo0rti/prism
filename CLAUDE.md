# Multi-Platform Project Template

Copier template that scaffolds monorepo projects with Backend (Spring Boot 4), Web (Next.js), Admin (Next.js), Android (Kotlin/Compose), and iOS (Swift/SwiftUI).

## Project Structure

```
copier.yml              # Template questionnaire (project name, platforms, auth, cloud)
template/               # All templated output — Jinja2 files (.jinja suffix stripped on generation)
  backend/              # Spring Boot 4 (Kotlin 2.2+, Java 21)
  android/              # Kotlin + Jetpack Compose (MVVM)
  ios/                  # Swift 6 + SwiftUI (MVVM)
  shared/               # OpenAPI 3.1 spec + design tokens
  docs/                 # Living documentation templates
  .claude/              # Claude context for generated projects (commands, skills)
  .codex/               # Codex context for generated projects
  .cursor/              # Cursor rules for generated projects
  .github/              # CI/CD workflow templates
  _templates/           # Hygen in-project generators
PLAN.md                 # Architecture plan, decisions, progress tracking
README.md               # Template usage instructions
```

## How This Template Works

- `copier.yml` defines questions (project_name, platforms, auth_methods, cloud_provider, etc.)
- Files in `template/` use Jinja2: `{{ project_name }}` for substitution, `{% if "android" in platforms %}` for conditionals
- The `.jinja` suffix is stripped after generation
- `_exclude` in copier.yml omits entire directories based on selected platforms
- `_subdirectory: template` means only `template/` contents are copied to the output

## Key Rules for Template Development

- **All files under `template/` must use `.jinja` suffix** if they contain any Jinja2 expressions
- **Test with `copier copy`** after changes: `copier copy --trust . /tmp/test-output`
- **EJS inside Jinja**: Hygen templates (`_templates/`) use EJS (`.ejs.t`) wrapped in Jinja — use `{{ '<%' }}` to escape EJS tags inside Jinja
- **Single quotes in Jinja filters inside EJS**: Use `replace(' ', '-')` not `replace(" ", "-")` when inside EJS template strings
- **Platform guards**: Use `{% if "platform" in platforms %}...{% endif %}` for conditional content
- **Directory exclusion**: Whole directories excluded via `_exclude` in copier.yml, not per-file guards
- **Package path**: Use `{{package_path}}` (forward slashes) for Kotlin/Java directory structure
- **Two layers of AI context**: `template/.claude/` is for generated projects; `.claude/` (root) is for this template repo

## Build Progress

| Phase | Status |
|-------|--------|
| 1 — Foundation (copier.yml, skeleton) | Done |
| 2 — Docs + Shared (OpenAPI, design tokens) | Done |
| 3A — Backend (Spring Boot 4) | Done |
| 3B — Web client (Next.js) | Pending |
| 3C — Admin portal (Next.js) | Pending |
| 3D — Android (Kotlin/Compose MVVM) | Done |
| 3E — iOS (Swift/SwiftUI MVVM) | Done |
| 4 — AI context (CLAUDE.md, AGENTS.md, Cursor rules) | Done |
| 5 — CI/CD (GitHub Actions) | Done |
| 6 — Hygen generators | Done |

## Common Commands

```bash
# Test template generation (all platforms)
copier copy --trust . /tmp/test-output

# Test with specific options
copier copy --trust --data 'project_name=TestApp' --data 'platforms=[backend, android]' . /tmp/test-output

# Update an existing generated project
cd /path/to/generated-project && copier update --trust
```

## Library Versions (Mar 2026)

- **Android**: AGP 8.9.1, Kotlin 2.3.10, Compose BOM 2026.01.01, Hilt 2.57.2, Retrofit 3.0.0, Room 2.8.4
- **iOS**: Swift 6.0, Xcode 26, iOS 17.0 min, SwiftData
- **Backend**: Spring Boot 4.0.1, Kotlin 2.2+, Java 21, JJWT 0.12.6, Jackson 3.x

## Conventions

- MVVM on both Android and iOS with matching patterns (ViewModel + UiState/ViewState)
- API-first: OpenAPI 3.1 spec → openapi-generator → typed clients for all platforms
- Taskfile (go-task) for build orchestration, cross-platform (Windows/Mac/Linux)
- iOS tasks guarded with `platforms: [darwin]` in Taskfile
- Windows is primary dev machine; Mac required only for iOS build/run
- Auth: OAuth (Google/Apple/Facebook/Microsoft) + optional password, all produce JWT

## Reference

- `PLAN.md` — full architecture plan, all decisions, usage scenarios
- `copier.yml` — template configuration and questionnaire
- `template/CLAUDE.md.jinja` — Claude context template for generated projects
- `template/AGENTS.md.jinja` — Codex context template for generated projects
