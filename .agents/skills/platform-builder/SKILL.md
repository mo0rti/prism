---
name: platform-builder
description: Add or extend a platform slice in this Copier template repo by following the current repo docs, matching established template patterns, updating docs and AI context, and validating generation. Use when working on backend, web, mobile-android, or mobile-ios template support.
---

# Platform Builder

Use this skill for template-repo work that adds a new platform slice or materially expands an existing one.

## Workflow

1. Read the relevant implementation status and platform context in `docs/current-status.md`, `docs/maintainer-workflow.md`, `README.md`, and the strongest existing template slices.
2. Study the strongest reference slices before editing:
   - `packs/spring-backend/` (the pack shape: every path under `{{ app_path }}/`, versions read from `packs/versions.yml`)
   - `template/mobile-android/`
   - `template/mobile-ios/`
3. Edit the files of the stack: a pack under `packs/{stack}/`, or a full sample under `template/{platform}/` until its pack exists.
   - Keep Jinja syntax balanced.
   - Add `.jinja` to any file with template expressions.
   - Use `{% if "stack" in stacks %}` or `{% if "app-id" in app_ids %}` guards only when the file truly needs them.
4. Update the app's docs: `packs/{stack}/{{ app_path }}/docs/` for a pack, `template/{platform}/docs/` for a sample.
5. Update AI context when the platform contract changes:
   - `template/CLAUDE.md.jinja`
   - `template/AGENTS.md.jinja`
   - `template-skills/`, the one source of the platform's skills, commands and Cursor rule; run `python scripts/build-skill-layers.py` and never edit `template/.agents/skills/`, `template/.claude/commands/`, `template/.claude/skills/` or `template/.cursor/rules/` by hand
6. Update shared wiring only when required:
   - `template/Taskfile.yml.jinja`
   - `template/.github/workflows/` (a pack carries its own workflow)
   - `copier.yml` and `prism_cli/packs.py`
   - `template/_templates/`
7. Keep maturity language explicit: implemented, partial, experimental, or planned.
8. Run `$test-template` or an equivalent `prism new` generation before finishing.

## Output

- Template changes for the selected platform
- Matching docs and AI-context updates
- A short note on what generation scenarios were validated
