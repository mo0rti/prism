# Maintainer Workflow

Use this guide when changing the template itself rather than a generated project.

## Template Structure

```text
docs/                 # Documentation for this template repository
prism_cli/            # The prism CLI, board service, MCP adapter and packaged workflow assets
tests/                # Python regression tests; tests/browser holds the opt-in browser tests
scripts/              # Validation, measurement and demo scripts
copier.yml            # Questionnaire and generation contract
template/             # Files copied into generated projects
  .claude/            # Claude project context and slash commands
  .agents/            # Codex project skills
  .cursor/            # Cursor rules: project.mdc references AGENTS.md, the others scope stack facts
  .github/            # Workflow templates
  _templates/         # Hygen generators
  backend/            # Backend scaffold
  web-user-app/       # User-facing web scaffold
  web-admin-portal/   # Admin web scaffold
  mobile-android/     # Android scaffold
  mobile-ios/         # iOS scaffold
  shared/             # OpenAPI and design tokens
  docs/               # Generated-project documentation
  knowledge/          # Generated-project product wiki skeleton
  infra/              # Infrastructure scripts
  README.md.jinja     # Generated-project README
  Taskfile.yml.jinja  # Generated-project root Taskfile
  AGENTS.md.jinja     # Generated-project agent rules, the single source for every tool
  CLAUDE.md.jinja     # Generated-project Claude Code import of AGENTS.md
README.md             # Short repository entrypoint and shared-board quickstart
SECURITY.md           # Local threat model
CHANGELOG.md          # User-visible changes
AGENTS.md             # Codex maintainer guidance for this repo
CLAUDE.md             # Claude maintainer guidance for this repo
```

## Recommended Maintainer Flow

1. Update `copier.yml` and/or files under `template/`.
2. Run `./scripts/validate-template.ps1` after template changes, and `python -B -m unittest discover -s tests` after changes to `prism_cli/`, the packaged assets or the template. When the board UI changes, also run the browser tests that [current-status.md](current-status.md#validation) describes.
3. Generate any extra explicit sample variants you need instead of relying on assumptions.
4. Compare generated output against the root docs, generated README/docs, task wiring, and the selected platform combinations.
5. Update repository docs when the template contract changes. When a CLI command, message, board behaviour or security check changes, also update the README quickstart, `docs/shared-board.md`, `docs/troubleshooting.md` and `SECURITY.md`, run the documented commands in a disposable workspace, and add the change under `Unreleased` in `CHANGELOG.md`.
6. Keep roadmap-visible options honest about whether they are current, partial, experimental, or planned.

To check the lifecycle with real Claude Code and Codex sessions and a browser against the board, run `scripts/e2e/journey.py`; [`scripts/e2e/README.md`](../scripts/e2e/README.md) describes the tiers and the report.

## Recommended Validation Variants

- `platforms=[backend]`
- `platforms=[backend, mobile-android]`
- `platforms=[backend, mobile-ios]`
- `platforms=[backend, web-user-app]`
- `platforms=[backend, web-admin-portal]`
- `platforms=[backend, web-user-app, web-admin-portal]`
- default generation as a contract-sanity check, not as the main proof of usability

`./scripts/validate-template.ps1 -Mode contract` checks rendered files and workflows. The default `full` mode also runs backend smoke checks; both modes disable the script's web smoke helper. Generated web install, lint, typecheck, authentication checks, Next.js/OpenNext builds, and Wrangler dry runs run in the separate `web-smoke` CI job in `.github/workflows/template-validation.yml`. A configured job is not evidence of a passing run on the current changes.

## Reference Commands

Contract validation requires actionlint on PATH (CI installs 1.7.12), or an explicit
`-ActionlintPath` argument. It checks rendered workflows for every sample.

```bash
./scripts/validate-template.ps1
copier copy --trust . ../template-test
copier copy --trust --defaults --data "project_name=Test App" --data "platforms=[backend]" . ../template-test-backend
copier copy --trust --defaults --data "project_name=Test Web App" --data "platforms=[backend, web-user-app, web-admin-portal]" . ../template-test-web
```

## Related Documentation

- [`README.md`](../README.md) for the short repository overview
- [`current-status.md`](current-status.md) for maturity and validated paths
- [`getting-started.md`](getting-started.md) for generation and validation commands
- [`questionnaire.md`](questionnaire.md) for the current questionnaire contract
- [`generated-projects.md`](generated-projects.md) for generated-project outputs and workflow support
- [`prism-model.md`](prism-model.md) for the conceptual Prism workflow model
- [`wiki-workflow.md`](wiki-workflow.md) for the generated-project wiki and query layer
- [`troubleshooting.md`](troubleshooting.md) for shared-board symptoms, causes and fixes
- [`SECURITY.md`](../SECURITY.md) for the local threat model
- [`CHANGELOG.md`](../CHANGELOG.md) for user-visible changes
