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
- Generated projects scaffold their own Codex skills from `template/.agents/skills/`; the per-app files of a stack pack (its Cursor rule `.cursor/rules/{{ app_id }}.mdc`, its `AGENTS.md`) are the pack's own source under `packs/<stack>/`, not the generator's.
- Generated projects keep one source of agent rules: `template/AGENTS.md.jinja` (and the `AGENTS.md.jinja` of each platform) holds the rules, and each `CLAUDE.md.jinja` only imports its sibling with `@AGENTS.md` plus Claude Code notes that no other tool shares. `template/CONTEXT.md.jinja` does not exist. Cursor reads `AGENTS.md` directly and also loads the skills in `.agents/skills/` and `.claude/skills/`, so no Cursor rule references `AGENTS.md`; the Cursor rules carry scoped stack facts only (the board review is a skill, not a rule). Add a generated-project rule once, in the `AGENTS.md.jinja` that owns it.
- Every generated skill, command and Cursor rule is written once, in `template-skills/<name>/skill.md`, and `scripts/build-skill-layers.py` renders `template/.agents/skills/`, `template/.claude/commands/`, `template/.claude/skills/` and `template/.cursor/rules/` from it. Edit the source, run the generator, then rebuild the packaged asset; never hand-edit a generated layer file.
- Keep this repository's `AGENTS.md` and `CLAUDE.md`, and the Cursor stack facts and the platform guidance they scope, aligned, and preserve tool-specific syntax instead of forcing identical wording.

## Repository Focus

- This template scaffolds an app list. Generation has two layers under one `copier.yml` and one tag: the workspace layer (`template/`) and one app layer per scaffolded app (`packs/<stack>/`, chosen by the hidden question `prism_layer`). The backend, web, Android and iOS apps are stack packs with one tested slice each (the local development identity and `GET /api/me`, and the sign-in and profile screens that consume them), and the Python agent service (`python-agent-service`) is a pack whose slice is an agent turn with one read-only tool that calls the backend with the caller's token, verified against the key the backend's dev identity publishes (`GET /api/dev-identity/jwks`); the workspace layer renders no app code.
- The backend, web, Android and agent-service packs are verified locally. The iOS pack is verified only by the macOS CI job. The agent service's Claude adapter is tested against a stub only; its tests, evaluation and CI use the fake provider and never call a live model API. The generated `deployment` skill's Azure and Cloudflare examples are not verified against live accounts. Keep maturity language explicit and honest, and keep `docs/current-status.md` equal to the verification that exists.
- Never leave questionnaire-visible options silently generating broken output.

## Working Rules

- Keep template-repo docs in root `docs/`.
- Keep project-wide docs in `template/docs/`.
- Keep the technical docs of an app in `packs/<stack>/{{ app_path }}/docs/`.
- Keep the pinned versions in `packs/versions.yml` only; a pack reads them as `versions`.
- `golden/` is the workspace that `python scripts/build-golden.py` generates with `prism new` from `scripts/golden-answers.yml`, one app of each stack. Regenerate it after any change of `template/`, `packs/`, `template-skills/` or `packs/versions.yml`, and never hand-edit it: `--check`, the `golden-current` CI job and a test fail while it is stale. It is not part of the package or of any Copier render. After a pin moves, run `python scripts/sync-golden.py` (the pack lockfiles, then `golden/`); the dependency bot (`renovate.json`) proposes pin updates and `.github/workflows/dependency-sync.yml` pushes that regeneration to its pull request. Repository workflows read every pack toolchain version from `packs/versions.yml` through `scripts/read-pins.py` and never repeat one, and a test fails when one does. `packs/audit-allowlist.yml` lists the security advisories that have no fixed version, each with its advisory link and reason, and `docs/current-status.md` records them; never list one without both.
- Generate with `prism new` (a preset or an answers file that lists the apps) after template changes; raw `copier copy --trust --defaults --data "project_name=Test App" . <tempdir>` renders the workspace layer alone.
- When editing files under `template/`, keep Jinja syntax valid:
  - all `{{` have matching `}}`
  - all `{% if %}` and `{% for %}` blocks are balanced
  - stack conditionals use `{% if "spring-backend" in stacks %}`; per-app output loops over `apps`
  - every `_exclude` entry of `copier.yml` applies to the workspace layer only (`prism_layer == 'workspace'`), because an app layer's paths are its own; the three that restore Copier's own defaults (`__pycache__`, `*.py[co]`, `.DS_Store`) apply to both
  - Kotlin and Java directory paths of a pack use `{{ app_package_path }}`
  - any file containing Jinja expressions keeps a `.jinja` suffix
- A user value that reaches generated code, configuration or CI (an app's ID, path, name and audience, the project's name and description) follows `prism_cli/safe_values.py`, and `copier.yml` repeats it as validators. A pack workflow passes the app's path through the workflow's `env: APP_PATH` and never writes it into a `run:` step, and a template serializes a value wherever it enters YAML (`| tojson`). Every path that a wiki page names (a Markdown link, a `sources` entry, a `repo:` link) resolves through `prism_cli/wiki_paths.py` and nowhere else.
- Update AI context when commands, paths, maturity, or workflow expectations change.
- Keep provider-neutral workflow guidance and its packaged assets synchronized. Connected agents use the shared service and pinned standard skills; custom skills retain the direct-file path. Do not add per-agent workflow implementations or an extra board approval queue.
- The 27 canonical workflow skills (the generated `template/.agents/skills/<name>/SKILL.md.jinja` and `template/.claude/commands/<name>.md.jinja`, whose source is `template-skills/<name>/skill.md`), everything under `template/knowledge/` and the "Connected board workflow" section of `template/AGENTS.md.jinja` are packaged into `prism_cli/assets/workflow-v1.json`; the packaged `CLAUDE.md` is the `@AGENTS.md` import of `template/CLAUDE.md.jinja`. A `.jinja` file under `template/knowledge/` (the general `index.md.jinja`, whose "Project docs" group exists only when Copier supplies `apps`) ships rendered in its workflow-only form. After editing one of them (a skill in `template-skills/`, then `python scripts/build-skill-layers.py`), run `python scripts/build-workflow-assets.py` to regenerate the asset; `--check` verifies it. A new asset digest invalidates existing board grants. The asset is generated, so never hand-edit it. Its `previous_digests` history is empty; `PREVIOUS_DIGESTS` in the build script records the digests of earlier shipped installer-owned files from the first release that has external users, which lets `prism workflow upgrade` then replace an unmodified copy without a conflict.
- Keep the README quickstart, `docs/shared-board.md`, `docs/troubleshooting.md` and `SECURITY.md` equal to the CLI and service behaviour. After changing a documented command, message or security check, run it in a disposable workspace and fix the docs to match the real output.
- Record user-visible changes under `Unreleased` in `CHANGELOG.md`. Version numbers and release tags are chosen at release time, not in the changelog's unreleased section.
- Instruction and guidance files state the current behaviour only. Keep dates and history in logs, ledgers and the changelog.

## Repo Skills

Project skills for this template repo live in `.agents/skills/` and are best invoked explicitly:

- `$platform-builder` for adding or extending a platform slice in the template
- `$sync-ai-context` for checking the single-source instruction layout, the Cursor stack facts and the root layer of this repository
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
- `copier.yml` for the layer question, the questionnaire inputs and the exclusions
- `packs/` for the stack packs and `packs/versions.yml`, the one place that pins versions
- `golden/` and `scripts/golden-answers.yml` for the generated reference workspace and its answers, and `renovate.json` for the dependency bot
- `template-skills/` for the source of every generated skill, command and Cursor rule
- `template/AGENTS.md.jinja` for the generated-project agent rules, the single source for every tool
- `template/CLAUDE.md.jinja` for the generated-project Claude Code import of `AGENTS.md`

## Common Commands

```bash
python -B scripts/run-tests.py                # the Python suite across worker processes (-j N, module names, --shard N/M); same tests as unittest discover
prism new --preset backend-only --project-name "Test App" --dest C:\temp\template-test --yes
python scripts/build-skill-layers.py          # after editing template-skills/
python scripts/build-skill-layers.py --check
python scripts/build-golden.py                # regenerate golden/ after a change of template/, packs/ or a pin
python scripts/build-golden.py --check
python scripts/sync-golden.py                 # after a pin moves: the pack lockfiles, then golden/
prism new --answers C:\temp\answers.yml --dest C:\temp\template-test-mobile --yes   # an app list of your choice
rg -n --hidden --glob '!**/.git/**' "\.agents/skills|AGENTS\.md|CLAUDE\.md" .

# Shared board, in a disposable workspace and never in this repository
prism workflow install . --name "Scratch" --app backend --apply --yes
prism app add web --stack nextjs-web --apply --yes .
prism app list .
prism doctor --workspace .
prism board grant "Tester" --kind human --write --path .
prism board serve . --port 8765
```
