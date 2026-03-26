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

1. **Check current state** - Read `PLAN.md` Build Progress section to see which platforms are done vs pending. Ask which platform to work on if not specified.

2. **Read the spec** - Read the relevant Phase 3 section from `PLAN.md` for the target platform's full specification.

3. **Study reference platforms** - Read completed platform templates to understand patterns:
   - `template/backend/` - Spring Boot patterns, Jinja usage, CLAUDE.md structure, `backend/docs/` for technical docs
   - `template/mobile-android/` - MVVM patterns, feature structure, Hilt DI, `mobile-android/docs/` for technical docs with 7 doc files
   - `template/mobile-ios/` - MVVM patterns mirroring Android, SwiftUI conventions

4. **Create the platform directory** - Build `template/{platform}/` with all files listed in the PLAN.md spec:
   - Add `.jinja` suffix if it contains any Jinja2 expressions
   - Use `{{ project_name }}`, `{{ project_slug }}`, `{{ package_identifier }}` for project identity
   - Use `{% if "provider" in auth_methods %}` for conditional auth provider code

5. **Create platform documentation** - Create `template/{platform}/docs/` with platform-specific technical docs (guide.md.jinja at minimum, more for complex platforms like Android's 7-doc structure).

6. **Create platform AI context** - Create `CLAUDE.md.jinja` and `AGENTS.md.jinja` for the platform:
   - Include doc table pointing to `docs/` within the platform directory
   - Reference skills with `@.claude/skills/` syntax
   - Include key conventions, doc-sync rules, and feature workflow

7. **Create platform skills** - Add Claude skills in `template/.claude/skills/` for the platform:
   - Convention skills (auto-triggered): coding conventions, design system, contract alignment
   - Action skills (manual): feature delivery, build verify, deploy

8. **Update cross-cutting files**:
   - `template/Taskfile.yml.jinja` - add platform tasks
   - `template/CLAUDE.md.jinja` - add to architecture map and platform-specific context section
   - `template/AGENTS.md.jinja` - mirror changes
   - `template/.cursor/rules/{platform}.mdc.jinja` - add platform rule
   - `template/.github/workflows/{platform}.yml.jinja` - add CI/CD workflow
   - `template/_templates/` - add Hygen generators if applicable

9. **Update progress** - Update the Build Progress table in `PLAN.md`.

10. **Test** - Run `/test-template` to verify generation works.
