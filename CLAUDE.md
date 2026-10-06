# Prism Core and Application Template

Prism's core is the workflow and board shared by humans and agents. Application generation is an optional capability. Follow `docs/prism-core-workflow-plan.md` for the scope, contracts and deferred work. Test lifecycle writes, workflow adoption and the shared HTTP/MCP service only in disposable neutral workspaces, never in this maintainer repository. Connected agents use pinned standard skills through one provider-neutral service; custom skills retain the direct-file path, with no extra board approval queue.

Copier template that scaffolds workspaces from an app list: Backend (Spring Boot 4, a stack pack), User Web App and Admin Web Portal (Next.js samples), Android (Kotlin/Compose sample), and iOS (Swift/SwiftUI sample).

Generation has two layers under one `copier.yml` and one template tag. The hidden question `prism_layer` chooses `workspace` (`template/`) or a stack with a pack (`packs/<stack>/`, one app, every path under `{{ app_path }}/`). The Prism CLI collects the app list and runs the workspace layer and then each scaffolded app's pack, each from its own answers file. The backend, Android and web samples are verified locally; the iOS sample is verified only by the macOS CI job. Deployment is a generated skill with worked examples that are not verified against live accounts. Apple Sign-In is experimental. `docs/current-status.md` records the verification per platform.

## Project Structure

```
docs/                    # Documentation for this template repository
copier.yml              # Template questionnaire: the hidden prism_layer, project identity, the layers' internal answers, auth
packs/                  # App layers: one pack per stack, rendered once per scaffolded app
  versions.yml          # The one place that pins versions; packs read it as `versions`
  spring-backend/       # Spring Boot pack, one tested slice (dev identity + GET /api/me): everything under {{ app_path }}/, plus .github/workflows/{{ app_id }}.yml and .cursor/rules/{{ app_id }}.mdc
template-skills/        # The one source of every skill, command and Cursor rule (generated into template/)
template/               # The workspace layer - Jinja2 files (.jinja suffix stripped on generation)
  web-user-app/         # Next.js user-facing web app (full sample, switch in prism_cli/packs.py)
  web-admin-portal/     # Next.js admin web portal
  mobile-android/              # Kotlin + Jetpack Compose (MVVM)
  mobile-ios/                  # Swift 6 + SwiftUI (MVVM)
  shared/               # OpenAPI 3.1 spec + design tokens
  docs/                 # Project-wide reference docs (architecture, API conventions, deployment)
  .claude/              # Claude commands and skills for generated projects (generated from template-skills/)
  .agents/              # Codex skills for generated projects (generated from template-skills/)
  .cursor/              # Cursor rules for generated projects: scoped stack facts and the board review (generated from template-skills/)
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
- **Documentation organization**: Template-repo docs live in root `docs/`. Generated-project docs stay in `template/docs/`. Technical docs of an app in a pack live in `packs/<stack>/{{ app_path }}/docs/`; those of a full sample live inside its directory (`template/mobile-android/docs/`, `template/mobile-ios/docs/`). Sample docs are auto-excluded with their sample via `_exclude` rules, and every `_exclude` entry applies to the workspace layer only (`prism_layer == 'workspace'`).
- **Layers and packs**: the workspace layer never holds app code of a stack that has a pack; a pack's paths are all under `{{ app_path }}/` except its workflow and Cursor rule; pinned versions live only in `packs/versions.yml`, and a test fails when a pack file repeats one; per-app files of a pack are the pack's own source, not the skill generator's. The switches for the stacks without a pack are named in `prism_cli/packs.py` (`NEXTJS_WEB_FULL_SAMPLE`, `ANDROID_COMPOSE_FULL_SAMPLE`, `IOS_SWIFTUI_FULL_SAMPLE`); each pack removes its switch and sample.
- **Test with the CLI** after changes: `prism new --preset backend-only --project-name "Test App" --dest C:\temp\template-test --yes` (a checkout generates from its working tree). Raw `copier copy --trust --defaults --data "project_name=Test App" . C:\temp\layer-test` renders the workspace layer alone
- **Maturity matters**: selectable options should be described as implemented, partial, or planned; they should never silently degrade into broken output
- **User docs match behaviour**: keep the README quickstart, `docs/shared-board.md`, `docs/troubleshooting.md` and `SECURITY.md` equal to the CLI and service. After changing a documented command, message or security check, run it in a disposable workspace and fix the docs to match the real output
- **One source of generated-project rules**: `template/AGENTS.md.jinja` (and each platform's `AGENTS.md.jinja`) holds the rules; every `CLAUDE.md.jinja` only imports its sibling with `@AGENTS.md` plus Claude Code notes no other tool shares; there is no `CONTEXT.md`; Cursor reads `AGENTS.md` itself, so no Cursor rule references it; add a rule once, where it belongs
- **One source of generated skills**: every skill, command and Cursor rule is `template-skills/<name>/skill.md`; edit the source, run `python scripts/build-skill-layers.py`, then `python scripts/build-workflow-assets.py` when a packaged workflow skill changed; never hand-edit a file under `template/.agents/skills/`, `template/.claude/commands/`, `template/.claude/skills/` or `template/.cursor/rules/`, because the generator owns them and `--check` and a test fail when one differs from its source
- **Packaged workflow assets**: the 26 canonical workflow skills (generated from `template-skills/`), `template/knowledge/` and the "Connected board workflow" section of `template/AGENTS.md.jinja` are packaged into `prism_cli/assets/workflow-v1.json` (a `.jinja` file under `template/knowledge/` ships rendered in its workflow-only form); run `python scripts/build-workflow-assets.py` after editing them (`--check` verifies), because a new digest invalidates existing board grants; the asset is generated, so never hand-edit it; its `previous_digests` history is empty, and `PREVIOUS_DIGESTS` in the build script records the digests of earlier shipped installer-owned files from the first release that has external users, so `prism workflow upgrade` can then replace an unmodified copy
- **Changelog**: record user-visible changes under `Unreleased` in `CHANGELOG.md`; version numbers and release tags are chosen at release time
- **Current state only**: instruction and guidance files describe current behaviour; dates and history belong in logs, ledgers and the changelog
- **Model and effort**: launch every agent run with an explicit model and effort, and keep the full output limit

## Common Commands

```bash
# Test template generation through the CLI (the workspace layer and each scaffolded app's pack)
prism new --preset backend-only --project-name "Test App" --dest C:\temp\template-test --yes

# Test an app list: an answers file with apps: [{id: backend, stack: spring-backend}, {id: mobile-android, stack: android-compose}]
prism new --answers C:\temp\answers.yml --dest C:\temp\template-test-mobile --yes

# Scaffold a second app into a committed generated workspace (needs a versioned template; a git+file:// URL of a tagged copy works)
prism app add api-two --stack spring-backend --path services/api-two --scaffold --apply --yes --trust-template C:\temp\template-test

# Rebuild the generated skill layers after editing template-skills/, then the packaged asset
python scripts/build-skill-layers.py
python scripts/build-workflow-assets.py
python scripts/build-skill-layers.py --check

# Update an existing generated project through Prism's manifest/provenance checks
cd /path/to/generated-project
prism update

# Shared board, in a disposable workspace and never in this repository
prism workflow install . --name "Scratch" --app backend --apply --yes
prism app add web --stack nextjs-web --apply --yes .
prism app list .
prism doctor --workspace .
prism board grant "Tester" --kind human --write --path .
prism board serve . --port 8765
```

## Reference

- `docs/README.md` - root documentation index for this template repo
- `docs/shared-board.md` - shared-board usage contract and MCP tool contract
- `docs/troubleshooting.md` - symptoms, causes and fixes
- `docs/agent-hosts.md` - tested agent hosts, their settings and limitations
- `SECURITY.md` - local threat model
- `CHANGELOG.md` - user-visible changes
- `docs/maintainer-workflow.md` - template maintenance workflow and validation variants
- `docs/questionnaire.md` - questionnaire inputs, the app list and what each stack generates
- `packs/` - the stack packs and `packs/versions.yml`, the pinned versions
- `copier.yml` - template configuration and questionnaire
- `template-skills/` - the source of every generated skill, command and Cursor rule
- `scripts/build-skill-layers.py` - renders the skill layers of `template/` from `template-skills/`
- `template/AGENTS.md.jinja` - agent rules for generated projects, the single source for every tool
- `template/CLAUDE.md.jinja` - Claude Code import of `AGENTS.md` for generated projects
