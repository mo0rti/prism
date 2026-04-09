# Multi-Platform Project Template

This repository is the Copier template itself. Treat the root `AGENTS.md` as maintainer guidance for the template repo, and treat files under `template/` as instructions that will be copied into generated projects.

## Two distinct AI context layers

1. **Template repo layer** (this file, `.agents/skills/`) — context for AI working
   on the template itself: adding platforms, fixing Jinja2 templates, updating schemas.

2. **Generated project layer** (`template/.agents/skills/`) — skill templates rendered
   into generated projects. Changes here affect every generated project.

The `knowledge/` directory in `template/knowledge/` is the template for the wiki system.
When working on the template, you are authoring the system, not using it. Do not run
wiki lifecycle operations (po-intake, design-intake, etc.) against this repository.

Note: `$scaffold-feature` and `$advisory-review` were removed from generated projects
and must not be referenced. They are replaced by the wiki lifecycle system
(`$setup-project`, `$board-review`, and the lifecycle operations documented in
`template/AGENTS.md.jinja`). The template-repo skills (`$platform-builder`,
`$sync-ai-context`, `$test-template`) are unaffected.

## How Codex Context Works Here

- Codex reads `AGENTS.md` from the repo root down to the current working directory.
- Repository-local Codex skills live in `.agents/skills/`, following the current Codex docs.
- Generated projects scaffold their own Codex skills from `template/.agents/skills/`.
- Keep shared facts aligned across `AGENTS.md`, `CLAUDE.md`, `template/AGENTS.md.jinja`, `template/CLAUDE.md.jinja`, and `.cursor/rules/`, but preserve tool-specific syntax instead of forcing identical wording.

## Repository Focus

- This template scaffolds backend, web-user-app, web-admin-portal, mobile-android, and mobile-ios slices.
- Backend, Android, and iOS are the stronger implemented paths today.
- User web app, admin web portal, and some auth or deployment combinations remain partial or experimental; keep maturity language explicit and honest.
- Never leave questionnaire-visible options silently generating broken output.

## Working Rules

- Keep template-repo docs in root `docs/`.
- Keep project-wide docs in `template/docs/`.
- Keep platform-specific technical docs in `template/{platform}/docs/`.
- Keep entity docs in `template/backend/docs/entities/`.
- Run `copier copy --trust . <tempdir>` after template changes.
- When editing files under `template/`, keep Jinja syntax valid:
  - all `{{` have matching `}}`
  - all `{% if %}` and `{% for %}` blocks are balanced
  - platform conditionals use `{% if "backend" in platforms %}` style
  - Kotlin and Java directory paths use `{{package_path}}`
  - any file containing Jinja expressions keeps a `.jinja` suffix
- Update AI context when commands, paths, maturity, or workflow expectations change.

## Repo Skills

Project skills for this template repo live in `.agents/skills/` and are best invoked explicitly:

- `$platform-builder` for adding or extending a platform slice in the template
- `$sync-ai-context` for repairing drift between Claude, Codex, and Cursor guidance
- `$test-template` for Copier generation checks after template edits

## Key Files

- `README.md` for the short repository overview
- `docs/README.md` for the repo docs index
- `docs/maintainer-workflow.md` for template maintenance flow
- `docs/current-status.md` for maturity and validation context
- `copier.yml` for questionnaire inputs and exclusions
- `template/AGENTS.md.jinja` for generated-project Codex guidance
- `template/CLAUDE.md.jinja` for generated-project Claude guidance

Use `plans/` for planning references.

## Common Commands

```bash
copier copy --trust . C:\temp\template-test
copier copy --trust --defaults --data "project_name=Test App" --data "platforms=[backend]" . C:\temp\template-test-backend
rg -n --hidden --glob '!**/.git/**' "\.agents/skills|AGENTS\.md|CLAUDE\.md" .
```
