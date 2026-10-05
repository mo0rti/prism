# Prism Core and Application Template

Prism's core is the workflow and board shared by humans and agents. Application generation is an optional capability. Follow `docs/prism-core-workflow-plan.md` for the scope, contracts and deferred work. Test lifecycle writes, workflow adoption and the shared HTTP/MCP service only in disposable neutral workspaces, never in this maintainer repository. Connected agents use pinned standard skills through one provider-neutral service; custom skills retain the direct-file path, with no extra board approval queue.

Copier template that scaffolds multi-platform workspaces with Backend (Spring Boot 4), User Web App (Next.js), Admin Web Portal (Next.js), Android (Kotlin/Compose), and iOS (Swift/SwiftUI).

The questionnaire keeps roadmap-facing options visible. Backend, Android and web samples are verified locally; the iOS sample is verified only by the macOS CI job, and live deployments are unverified. Apple Sign-In is experimental. `docs/current-status.md` records the verification per platform.

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
- **User docs match behaviour**: keep the README quickstart, `docs/shared-board.md`, `docs/troubleshooting.md` and `SECURITY.md` equal to the CLI and service. After changing a documented command, message or security check, run it in a disposable workspace and fix the docs to match the real output
- **Packaged workflow assets**: the 24 canonical workflow skills, `template/knowledge/` and the "Connected board workflow" section of the root guidance templates are packaged into `prism_cli/assets/workflow-v1.json`; run `python scripts/build-workflow-assets.py` after editing them (`--check` verifies), because a new digest invalidates existing board grants; the asset's `previous_digests` keep the earlier shipped versions of each installer-owned file so `prism workflow upgrade` can replace an unmodified old copy, so rebuild from the checked-in asset and never delete or hand-edit it
- **Changelog**: record user-visible changes under `Unreleased` in `CHANGELOG.md`; version numbers and release tags are chosen at release time
- **Current state only**: instruction and guidance files describe current behaviour; dates and history belong in logs, ledgers and the changelog
- **Model and effort**: follow the maintainer model workflow in `AGENTS.md`. Launch with an explicit model and effort, keep the full output limit, and use `max` only for one bounded hard problem

## Common Commands

```bash
# Test template generation (all platforms)
copier copy --trust . C:\temp\template-test

# Test with specific options
copier copy --trust --data 'project_name=TestApp' --data 'platforms=[backend, mobile-android]' . C:\temp\template-test-mobile

# Update an existing generated project through Prism's manifest/provenance checks
cd /path/to/generated-project
prism update

# Shared board, in a disposable workspace and never in this repository
prism workflow install . --name "Scratch" --platform backend --apply --yes
prism doctor --workspace .
prism board grant "Tester" --kind human --write --path .
prism board serve . --port 8765
```

## Reference

- `docs/README.md` - root documentation index for this template repo
- `docs/shared-board.md` - shared-board usage contract and MCP tool contract
- `docs/troubleshooting.md` - symptoms, causes and fixes
- `SECURITY.md` - local threat model
- `CHANGELOG.md` - user-visible changes
- `docs/maintainer-workflow.md` - template maintenance workflow and validation variants
- `docs/questionnaire.md` - questionnaire inputs and maturity notes
- `copier.yml` - template configuration and questionnaire
- `template/CLAUDE.md.jinja` - Claude context template for generated projects
- `template/AGENTS.md.jinja` - Codex context template for generated projects
