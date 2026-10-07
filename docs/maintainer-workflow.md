# Maintainer Workflow

Use this guide when changing the template itself rather than a generated project.

## Template Structure

```text
docs/                 # Documentation for this template repository
prism_cli/            # The prism CLI, board service, MCP adapter and packaged workflow assets
tests/                # Python regression tests; tests/browser holds the opt-in browser tests
scripts/              # Validation, measurement and demo scripts, and the generators of the workflow asset and the skill layers
template-skills/      # The one source of every skill, command and Cursor rule; generated into the layers of template/
copier.yml            # Questionnaire and generation contract
packs/                # App layers, one pack per stack with a pack (spring-backend, nextjs-web, android-compose, ios-swiftui), and versions.yml with the pinned versions
template/             # Files copied into generated projects (the workspace layer)
  .claude/            # Claude commands and skills (generated from template-skills/)
  .agents/            # Codex skills (generated from template-skills/)
  .cursor/            # Cursor rules: scoped stack facts and the board review (generated from template-skills/)
  .github/            # Workflow templates
  _templates/         # Hygen generators
  shared/             # OpenAPI and design tokens
  docs/               # Generated-project documentation
  knowledge/          # Generated-project product wiki skeleton
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

1. Update `copier.yml` and/or files under `template/`. Change a skill, command or Cursor rule only in `template-skills/` (see [Skill Sources](#skill-sources)); never edit a file under `template/.agents/skills/`, `template/.claude/commands/`, `template/.claude/skills/` or `template/.cursor/rules/`.
2. After editing `template-skills/`, run `python scripts/build-skill-layers.py`, then `python scripts/build-workflow-assets.py` when a packaged workflow skill changed.
3. Run `./scripts/validate-template.ps1` after template changes, and `python -B -m unittest discover -s tests` after changes to `prism_cli/`, the packaged assets or the template. When the board UI changes, also run the browser tests that [current-status.md](current-status.md#validation) describes.
4. Generate any extra explicit variants you need instead of relying on assumptions.
5. Compare generated output against the root docs, generated README/docs, task wiring, and the selected platform combinations.
6. Update repository docs when the template contract changes. When a CLI command, message, board behaviour or security check changes, also update the README quickstart, `docs/shared-board.md`, `docs/troubleshooting.md` and `SECURITY.md`, run the documented commands in a disposable workspace, and add the change under `Unreleased` in `CHANGELOG.md`.
7. Keep roadmap-visible options honest about whether they are current, partial, experimental, or planned.

To check the lifecycle with real Claude Code and Codex sessions and a browser against the board, run `scripts/e2e/journey.py`; [`scripts/e2e/README.md`](../scripts/e2e/README.md) describes the tiers and the report.

## Skill Sources

`template-skills/<name>/skill.md` is the one source of a skill. A generated workspace carries the same guidance in the layout each tool discovers, and `scripts/build-skill-layers.py` renders every layer file from the source:

| Layer | Generated file | Tool |
|-------|----------------|------|
| `codex` | `template/.agents/skills/<name>/SKILL.md.jinja` and `agents/openai.yaml` | Codex, and Cursor (it loads `.agents/skills/`) |
| `command` | `template/.claude/commands/<name>.md.jinja` | Claude Code |
| `claude-skill` | `template/.claude/skills/<name>/SKILL.md.jinja` | Claude Code, and Cursor (it loads `.claude/skills/`) |
| `cursor` | `template/.cursor/rules/<file>.mdc.jinja` | Cursor rules |

The front matter of a source holds:

- `name` (the folder name), one `description` and `layers`, the layers the skill ships to;
- `platforms`, when the skill ships only with some apps (it ships when any listed platform is selected); `reference-platforms` does the same for a file or folder under `references/`. The generator writes these conditions into the generated block of `_exclude` in `copier.yml`;
- the per-host fields: `codex` (`display_name`, `short_description`, `default_prompt`, `implicit` for `allow_implicit_invocation`), `claude-skill` (`argument-hint`, `disable-model-invocation`, `user-invocable`, `allowed-tools`) and `cursor` (`file`, and `globs` or `always-apply`).

The body is written once. Copier conditions and variables (`{% if "backend" in platforms %}`, `{{ project_name }}`) pass through unchanged. Two mechanisms cover the differences between hosts:

- `@@invoke:<name>@@` becomes the host's way to run that skill: `$name` in Codex, `/name` in a Claude command, and the bare name in a Claude skill or a Cursor rule;
- a block from `::: only <layers>` to `:::` stays only in those layers (`codex`, `command`, `claude-skill`, `cursor`, or `claude` for both Claude layers).

A skill's `references/` folder is copied into the `.agents/skills/<name>/` and `.claude/skills/<name>/` folders. A Cursor-only rule is a source whose only layer is `cursor`.

After editing a source:

```bash
python scripts/build-skill-layers.py          # renders template/ and the _exclude block of copier.yml
python scripts/build-workflow-assets.py       # when one of the packaged workflow skills changed
python scripts/build-skill-layers.py --check  # fails when a generated file differs from its source
```

`tests/test_skill_layers.py` runs the check, fails when a layer file is edited without its source, and tests how each tool discovers the rendered skills.

## Recommended Validation Variants

- `backend` alone, and `backend` with a second backend at another path (`prism app add api-two --stack spring-backend --path services/api-two --scaffold`)
- `backend` and `mobile-android`
- `backend`, `mobile-android` and `partner-android` (two apps of the `android-compose` stack, the second at `apps/partner`)
- `backend` and `mobile-ios`
- `backend`, `mobile-ios` and `partner-ios` (two apps of the `ios-swiftui` stack, the second at `apps/partner-ios`)
- `backend` and `web`
- `backend`, `web` and `admin` (two apps of the `nextjs-web` stack, with different audiences)
- the preset defaults as a contract-sanity check, not as the main proof of usability

Generate each through the CLI, with a preset or an answers file that lists the apps, because Copier does not ask about apps. Generation renders the working tree (tracked or not), so a test that needs committed state, such as an update across a tag, builds a snapshot repository under a temporary folder (`tests/layered_support.py`).

`./scripts/validate-template.ps1 -Mode contract` generates through `prism new` and checks rendered files and workflows. The default `full` mode also runs backend smoke checks (the pack's tests and boot jar, which need a JDK); both modes disable the script's web smoke helper. Generated web `npm ci`, lint, typecheck, tests and Next.js builds run for two web apps in the separate `web-smoke` CI job in `.github/workflows/template-validation.yml`, and the Gradle `assembleDebug` and unit tests of two Android apps run in its `android-build` job, and XcodeGen, a simulator build and the tests of two iOS apps run in its macOS `ios-build` job. A configured job is not evidence of a passing run on the current changes.

## Reference Commands

Contract validation requires actionlint on PATH (CI installs 1.7.12), or an explicit
`-ActionlintPath` argument. It checks rendered workflows for every generated app.

```bash
./scripts/validate-template.ps1
prism new --preset backend-only --project-name "Test App" --dest ../template-test-backend --yes
prism new --preset backend-web --project-name "Test Web App" --dest ../template-test-web --yes
copier copy --trust --defaults --data "project_name=Test App" . ../template-test-workspace-layer   # one layer only
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
