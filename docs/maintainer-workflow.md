# Maintainer Workflow

Use this guide when changing the template itself rather than a generated project.

## Template Structure

```text
docs/                 # Documentation for this template repository
copier.yml            # Questionnaire and generation contract
template/             # Files copied into generated projects
  .claude/            # Claude project context and slash commands
  .agents/            # Codex project skills
  .cursor/            # Cursor project rules
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
  CONTEXT.md.jinja    # Generated-project root AI context anchor
  README.md.jinja     # Generated-project README
  Taskfile.yml.jinja  # Generated-project root Taskfile
  AGENTS.md.jinja     # Generated-project Codex guidance
  CLAUDE.md.jinja     # Generated-project Claude guidance
README.md             # Short repository entrypoint
AGENTS.md             # Codex maintainer guidance for this repo
CLAUDE.md             # Claude maintainer guidance for this repo
plans/                # Private planning and review docs kept out of version control
```

## Recommended Maintainer Flow

1. Update `copier.yml` and/or files under `template/`.
2. Run `./scripts/validate-template.ps1` after template changes.
3. Generate any extra explicit sample variants you need instead of relying on assumptions.
4. Compare generated output against the root docs, generated README/docs, task wiring, and the selected platform combinations.
5. Update repository docs when the template contract changes.
6. Keep roadmap-visible options honest about whether they are current, partial, experimental, or planned.

## Recommended Validation Variants

- `platforms=[backend]`
- `platforms=[backend, mobile-android]`
- `platforms=[backend, mobile-ios]`
- `platforms=[backend, web-user-app]`
- `platforms=[backend, web-admin-portal]`
- `platforms=[backend, web-user-app, web-admin-portal]`
- default generation as a contract-sanity check, not as the main proof of usability

`./scripts/validate-template.ps1` now also smoke-tests generated web slices through `npm install`, `npm run lint`, `npm run typecheck`, `npm run build`, `npm run build:cloudflare`, and `wrangler deploy --dry-run` when Node.js is available.

## Reference Commands

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
