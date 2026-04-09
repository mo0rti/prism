---
name: platform-builder
description: Add or extend a platform template (web-user-app, web-admin-portal, backend, mobile-android, or mobile-ios) following established patterns from completed platforms.
argument-hint: [platform-name]
disable-model-invocation: true
---

# Platform Builder

Add or extend a platform template following established patterns.

## Request

$ARGUMENTS

## Steps

1. **Check current state** - Read `docs/current-status.md` and inspect the existing template slices to see which platforms are stronger vs still partial. Ask which platform to work on if not specified.

2. **Read the spec** - Infer the current platform contract from `copier.yml`, `template/`, `README.md`, and the maintainer docs.

3. **Study reference platforms** - Read completed platform templates to understand patterns:
   - `template/backend/` - Spring Boot patterns, Jinja usage, CLAUDE.md structure, `backend/docs/` for technical docs
   - `template/mobile-android/` - MVVM patterns, feature structure, Hilt DI, `mobile-android/docs/` for technical docs with 7 doc files
   - `template/mobile-ios/` - MVVM patterns mirroring Android, SwiftUI conventions

4. **Create the platform directory** - Build `template/{platform}/` with the files required by the current platform contract:
   - Add `.jinja` suffix if it contains any Jinja2 expressions
   - Use `{{ project_name }}`, `{{ project_slug }}`, `{{ package_identifier }}` for project identity
   - Use `{% if "provider" in auth_methods %}` for conditional auth provider code

5. **Create platform documentation** - Create `template/{platform}/docs/` with platform-specific technical docs (guide.md.jinja at minimum, more for complex platforms like Android's 7-doc structure).

6. **Create platform AI context** - Create `CLAUDE.md.jinja` and `AGENTS.md.jinja` for the platform:
   - Include doc table pointing to `docs/` within the platform directory
   - Reference skills with `@.claude/skills/` syntax
   - Include key conventions, doc-sync rules, and feature workflow

7. **Create platform skills** - Add project skills for the platform:
   - Claude skills in `template/.claude/skills/`
   - Codex skills in `template/.agents/skills/` when the workflow should be available in generated projects
   - Keep skill scope orthogonal: conventions, contract alignment, delivery, and verification should not collapse into one giant skill

8. **Update cross-cutting files**:
   - `template/Taskfile.yml.jinja` - add platform tasks
   - `template/CLAUDE.md.jinja` - add to architecture map and platform-specific context section
   - `template/AGENTS.md.jinja` - mirror changes
   - `template/.cursor/rules/{platform}.mdc.jinja` - add platform rule
   - `template/.github/workflows/{platform}.yml.jinja` - add CI/CD workflow
   - `template/_templates/` - add Hygen generators if applicable

9. **Update progress** - Update the committed repo docs when the public template contract changes, especially `docs/current-status.md`, `docs/maintainer-workflow.md`, and `README.md` where relevant.

10. **Test** - Run `/test-template` to verify generation works.
