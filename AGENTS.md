# Prism Core and Application Template

This repository is the Copier template itself. Treat the root `AGENTS.md` as maintainer guidance for the template repo, and treat files under `template/` as instructions that will be copied into generated projects.

Prism's core is the workflow and board shared by humans and agents. Application generation is an optional capability. Keep core acceptance independent of application samples; use disposable neutral workspaces for lifecycle writes, adoption, HTTP/MCP and recovery tests. The scope, contracts and deferred work are in `docs/prism-core-workflow-plan.md`.

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
- Keep shared facts aligned across `AGENTS.md`, `CLAUDE.md`, `template/AGENTS.md.jinja`, `template/CLAUDE.md.jinja`, and `template/.cursor/rules/`, but preserve tool-specific syntax instead of forcing identical wording.

## Repository Focus

- This template scaffolds backend, web-user-app, web-admin-portal, mobile-android, and mobile-ios slices.
- Backend, Android and web samples are verified locally. The iOS sample is verified only by the macOS CI job, and live Cloudflare and Azure deployments are unverified. Apple Sign-In is experimental. Keep maturity language explicit and honest, and keep `docs/current-status.md` equal to the verification that exists.
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
- Keep provider-neutral workflow guidance and its packaged assets synchronized. Connected agents use the shared service and pinned standard skills; custom skills retain the direct-file path. Do not add per-agent workflow implementations or an extra board approval queue.
- The 24 canonical workflow skills (`template/.agents/skills/<name>/SKILL.md.jinja` and `template/.claude/commands/<name>.md.jinja`), everything under `template/knowledge/` and the "Connected board workflow" section of the root guidance templates are packaged into `prism_cli/assets/workflow-v1.json`. After editing one of them, run `python scripts/build-workflow-assets.py` to regenerate the asset; `--check` verifies it. A new asset digest invalidates existing board grants. The asset is generated, so never hand-edit it. Its `previous_digests` history is empty; `PREVIOUS_DIGESTS` in the build script records the digests of earlier shipped installer-owned files from the first release that has external users, which lets `prism workflow upgrade` then replace an unmodified copy without a conflict.
- Keep the README quickstart, `docs/shared-board.md`, `docs/troubleshooting.md` and `SECURITY.md` equal to the CLI and service behaviour. After changing a documented command, message or security check, run it in a disposable workspace and fix the docs to match the real output.
- Record user-visible changes under `Unreleased` in `CHANGELOG.md`. Version numbers and release tags are chosen at release time, not in the changelog's unreleased section.
- Instruction and guidance files state the current behaviour only. Keep dates and history in logs, ledgers and the changelog.

## Repo Skills

Project skills for this template repo live in `.agents/skills/` and are best invoked explicitly:

- `$platform-builder` for adding or extending a platform slice in the template
- `$sync-ai-context` for repairing drift between Claude, Codex, and Cursor guidance
- `$test-template` for Copier generation checks after template edits

## Key Files

- `README.md` for the short repository overview and the shared-board quickstart
- `docs/README.md` for the repo docs index
- `docs/shared-board.md` for the shared-board usage contract and the MCP tool contract
- `docs/troubleshooting.md` for symptoms, causes and fixes
- `docs/agent-hosts.md` for the tested agent hosts, their settings and limitations
- `SECURITY.md` for the local threat model
- `CHANGELOG.md` for user-visible changes
- `docs/maintainer-workflow.md` for template maintenance flow
- `docs/current-status.md` for maturity and validation context
- `copier.yml` for questionnaire inputs and exclusions
- `template/AGENTS.md.jinja` for generated-project Codex guidance
- `template/CLAUDE.md.jinja` for generated-project Claude guidance

## Common Commands

```bash
copier copy --trust . C:\temp\template-test
copier copy --trust --defaults --data "project_name=Test App" --data "platforms=[backend]" . C:\temp\template-test-backend
rg -n --hidden --glob '!**/.git/**' "\.agents/skills|AGENTS\.md|CLAUDE\.md" .

# Shared board, in a disposable workspace and never in this repository
prism workflow install . --name "Scratch" --app backend --apply --yes
prism app add web --stack nextjs-web --apply --yes .
prism app list .
prism doctor --workspace .
prism board grant "Tester" --kind human --write --path .
prism board serve . --port 8765
```
