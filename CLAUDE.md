# Multi-Platform Project Template

Copier template that scaffolds monorepo projects with Backend (Spring Boot 4), User Web App (Next.js), Admin Web Portal (Next.js), Android (Kotlin/Compose), and iOS (Swift/SwiftUI).

The questionnaire keeps roadmap-facing options visible. Backend, Android, and iOS are the primary implemented slices today; the user web app, admin web portal, and some auth/deployment choices remain intentionally visible while their end-to-end support continues to evolve.

## Project Structure

```
docs/                    # Documentation for this template repository
copier.yml              # Template questionnaire (project identity, platforms, auth, database, deployment)
template/               # All templated output - Jinja2 files (.jinja suffix stripped on generation)
  backend/              # Spring Boot 4 (Kotlin 2.2+, Java 21)
  web-user-app/         # Next.js user-facing web app
  web-admin-portal/     # Next.js admin web portal
  mobile-android/              # Kotlin + Jetpack Compose (MVVM)
  mobile-ios/                  # Swift 6 + SwiftUI (MVVM)
  shared/               # OpenAPI 3.1 spec + design tokens
  docs/                 # Project-wide reference docs (architecture, API conventions, deployment)
  .claude/              # Claude context for generated projects (commands, skills)
  .agents/              # Codex skills for generated projects
  .cursor/              # Cursor rules for generated projects
  .github/              # CI/CD workflow templates
  _templates/           # Hygen in-project generators
```

## Two distinct AI context layers

1. **Template repo layer** (this file, `.claude/`, `.agents/`) — context for AI working
   on the template itself: adding platforms, fixing Jinja2 templates, updating schemas.

2. **Generated project layer** (`template/.claude/`, `template/.agents/`) — context
   templates rendered into generated projects. Changes here affect every generated project.

The `knowledge/` directory in `template/knowledge/` is the template for the wiki system.
When working on the template, you are authoring the system, not using it. Do not run
wiki commands from a generated project against this repository.

## Key Rules

- **Two layers of AI context**: `template/.claude/` is for generated projects; `.claude/` (root) is for this template repo
- **Documentation organization**: Template-repo docs live in root `docs/`. Generated-project docs stay in `template/docs/`. Platform-specific technical docs live inside each platform directory (`template/mobile-android/docs/`, `template/backend/docs/`, `template/mobile-ios/docs/`). Entity docs are backend-specific (`template/backend/docs/entities/`). Platform docs are auto-excluded with their platform via `_exclude` rules.
- **Test with `copier copy`** after changes: `copier copy --trust . C:\temp\template-test`
- **Maturity matters**: selectable options should be described as implemented, partial, or planned; they should never silently degrade into broken output

## Common Commands

```bash
# Test template generation (all platforms)
copier copy --trust . C:\temp\template-test

# Test with specific options
copier copy --trust --data 'project_name=TestApp' --data 'platforms=[backend, mobile-android]' . C:\temp\template-test-mobile

# Update an existing generated project
cd /path/to/generated-project && copier update --trust
```

## Reference

- `docs/README.md` - root documentation index for this template repo
- `docs/maintainer-workflow.md` - template maintenance workflow and validation variants
- `docs/questionnaire.md` - questionnaire inputs and maturity notes
- `copier.yml` - template configuration and questionnaire
- `template/CLAUDE.md.jinja` - Claude context template for generated projects
- `template/AGENTS.md.jinja` - Codex context template for generated projects

Use `plans/` for planning references.
