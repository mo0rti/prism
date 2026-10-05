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

## Model workflow for maintainer work

This applies to work on this repository, not to generated projects. Set the model and effort explicitly in every launch, because tool defaults differ. For example, Codex runs GPT-6.1 Sol at low effort when none is set.

| Role | Claude | Codex |
| --- | --- | --- |
| Planning, orchestration and review | Claude Opus 5.5, xhigh | GPT-6 Astra, xhigh |
| Implementation | Claude Sonnet 5.5, high; medium for a well-scoped change | GPT-6.1 Sol, high; medium for a well-scoped change |
| Narrow lookups and small fixes | Claude Sonnet 5.5, medium | GPT-6 Luna, high |
| One bounded hard problem | Claude Opus 5.5, max | GPT-6 Astra, max |

- **Why these levels:**
  - In a blind comparison that included a Prism ticket, Sonnet 5.5 at medium and high met every acceptance criterion that xhigh met, at about half the cost.
  - OpenAI's coding benchmark puts GPT-6.1 Sol at high level with GPT-6 Astra at about a seventh of the cost per task. Sol's score drops at xhigh and max.
- **Output limit:** keep Claude's full 128,000-token output limit and never set a smaller per-run cap. Thinking and the written result share it. At max, Claude can spend the whole limit thinking on open-ended work and return nothing. If a run returns nothing, rerun it one level lower with a narrower brief.
- **Effort ceiling:** do not use `ultra` effort for workers; it fans out into parallel subagents.
- **Implementer agent:** `.claude/agents/prism-implementer.md` runs Sonnet 5.5 at high for one written brief at a time.
- **Headless runs on Windows:** call the Claude Code executable directly and pass the prompt on stdin. The npm `claude.cmd` shim cuts a multi-line argument at its first newline and drops the flags after it.
- **Checking a run:** read the transcript, not the prompt. Claude Code transcripts record the model and effort on each message, and Codex rollout files record them in `turn_context`.
- **Evidence:** keep run logs, traces and screenshots in a durable folder outside the repository, never only in the operating system's temp directory.

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
- The 24 canonical workflow skills (`template/.agents/skills/<name>/SKILL.md.jinja` and `template/.claude/commands/<name>.md.jinja`), everything under `template/knowledge/` and the "Connected board workflow" section of the root guidance templates are packaged into `prism_cli/assets/workflow-v1.json`. After editing one of them, run `python scripts/build-workflow-assets.py` to regenerate the asset; `--check` verifies it. A new asset digest invalidates existing board grants. The asset's `previous_digests` list the earlier shipped versions of each installer-owned file, which lets `prism workflow upgrade` replace an unmodified old copy without a conflict; the build appends to it, so rebuild from the checked-in asset and never delete or hand-edit it.
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
prism workflow install . --name "Scratch" --platform backend --apply --yes
prism doctor --workspace .
prism board grant "Tester" --kind human --write --path .
prism board serve . --port 8765
```
