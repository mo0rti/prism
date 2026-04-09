---
name: platform-builder
description: Add or extend a platform slice in this Copier template repo by following the current repo docs, matching established template patterns, updating docs and AI context, and validating generation. Use when working on backend, web-user-app, web-admin-portal, mobile-android, or mobile-ios template support.
---

# Platform Builder

Use this skill for template-repo work that adds a new platform slice or materially expands an existing one.

## Workflow

1. Read the relevant implementation status and platform context in `docs/current-status.md`, `docs/maintainer-workflow.md`, `README.md`, and the strongest existing template slices.
2. Study the strongest reference slices before editing:
   - `template/backend/`
   - `template/mobile-android/`
   - `template/mobile-ios/`
3. Edit the platform files under `template/{platform}/`.
   - Keep Jinja syntax balanced.
   - Add `.jinja` to any file with template expressions.
   - Use `{% if "platform" in platforms %}` guards only when the file truly needs them.
4. Update platform docs in `template/{platform}/docs/`.
5. Update AI context when the platform contract changes:
   - `template/CLAUDE.md.jinja`
   - `template/AGENTS.md.jinja`
   - `template/.cursor/rules/`
   - `template/.claude/`
   - `template/.agents/skills/`
6. Update shared wiring only when required:
   - `template/Taskfile.yml.jinja`
   - `template/.github/workflows/`
   - `copier.yml`
   - `template/_templates/`
7. Keep maturity language explicit: implemented, partial, experimental, or planned.
8. Run `$test-template` or an equivalent `copier copy` validation before finishing.

## Output

- Template changes for the selected platform
- Matching docs and AI-context updates
- A short note on what generation scenarios were validated
