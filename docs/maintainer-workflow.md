# Maintainer Workflow

Use this guide when changing the template itself rather than a generated project.

## How the Source Directories Fit Together

Four directories hold the sources of every generated workspace. Two are sources for the generated project's layers (`template/`, `packs/`), one is the source of the skills (`template-skills/`), and one is a generated reference (`golden/`).

- **`template/`** is the workspace layer. Copier renders it once per workspace. It holds no app code: the wiki template (`knowledge/`), `AGENTS.md` and `CLAUDE.md`, `docs/`, `shared/` (the API contracts), the root `Taskfile.yml` and `docker-compose.yml`, `README.md` and the manifest `prism.workspace.yml`. Its agent skill folders (`.agents/`, `.claude/`, `.cursor/`) are generated.
- **`packs/<stack>/`** is the app layer, one pack per stack (`spring-backend`, `nextjs-web`, `android-compose`, `ios-swiftui`, `python-agent-service`). Copier renders a pack once per app in the app list, at that app's path; every pack file sits under `{{ app_path }}/` except its CI workflow and its Cursor rule. `packs/versions.yml` is the one place every pinned version lives, and `packs/audit-allowlist.yml` lists the security advisories that have no fixed version.
- **`template-skills/<name>/skill.md`** is the one source of every skill, command and Cursor rule. It is rendered into the skill folders of `template/`, and its workflow skills are packed with `template/knowledge/` into `prism_cli/assets/workflow-v1.json`, which `prism workflow install` uses for a project that was not generated from the template.
- **`golden/`** is a generated workspace committed to the repository, one app of each stack, generated with `prism new` from `scripts/golden-answers.yml`. It shows a template change as a diff of generated files, and CI builds and tests its apps. It is not part of the published package.

One `copier.yml` and one release tag cover both layers; the hidden question `prism_layer` chooses the layer. `prism new` renders the workspace layer and then each scaffolded app's pack, each from its own answers file, and `prism update` updates each layer the same way.

```text
template-skills/  --build-skill-layers.py-->    template/.agents, .claude, .cursor
                  --build-workflow-assets.py--> prism_cli/assets/workflow-v1.json
template/        (workspace layer) --+
                                     +-- prism new --> a generated workspace
packs/<stack>/   (one per app)     --+               (golden/ is one, committed)
```

| Directory | Role | Edit it? | Rebuilt by | Guarded by |
|-----------|------|----------|-----------|-----------|
| `template-skills/` | source | yes | nothing (it is the source) | `build-skill-layers.py --check` and its test |
| `template/` (hand-written files) | source | yes | nothing | `validate-template.ps1` and the tests |
| `template/.agents/`, `.claude/`, `.cursor/` | generated | no | `build-skill-layers.py` | `build-skill-layers.py --check` |
| `packs/<stack>/` | source | yes | nothing | the pack tests and the pack CI jobs |
| `prism_cli/assets/workflow-v1.json` | generated | no | `build-workflow-assets.py` | `build-workflow-assets.py --check` |
| `golden/` | generated | no | `build-golden.py` | `build-golden.py --check` and the `golden-current` CI job |

Edit only sources. After editing `template-skills/`, run `build-skill-layers.py`, then `build-workflow-assets.py` when a packaged workflow skill changed. After any change to `template/`, `packs/`, `template-skills/` or `packs/versions.yml`, run `build-golden.py` and commit `golden/` with the change. [Skill Sources](#skill-sources), [Golden Workspace](#golden-workspace) and [Recommended Maintainer Flow](#recommended-maintainer-flow) give the details.

## Template Structure

```text
docs/                 # Documentation for this template repository
prism_cli/            # The prism CLI, board service, MCP adapter and packaged workflow assets
tests/                # Python regression tests; tests/browser holds the opt-in browser tests
scripts/              # Validation, measurement and demo scripts, and the generators of the workflow asset and the skill layers
template-skills/      # The one source of every skill, command and Cursor rule; generated into the layers of template/
copier.yml            # Questionnaire and generation contract
packs/                # App layers, one pack per stack with a pack (spring-backend, nextjs-web, android-compose, ios-swiftui, python-agent-service), and versions.yml with the pinned versions
golden/               # The generated reference workspace, one app of each stack; built and tested by CI, never packaged (scripts/build-golden.py)
template/             # Files copied into generated projects (the workspace layer)
  .claude/            # Claude commands and skills (generated from template-skills/)
  .agents/            # Codex skills (generated from template-skills/)
  .cursor/            # Cursor rules: the scoped API conventions (generated from template-skills/); each app's rule comes from its pack
  .github/            # Workflow templates
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
   After a change of `template/`, `packs/`, `template-skills/` or `packs/versions.yml`, also run `python scripts/build-golden.py` and commit `golden/` with it ([Golden Workspace](#golden-workspace)); after a pin moves, run `python scripts/sync-golden.py`, which also refreshes the pack lockfiles.
3. Run `./scripts/validate-template.ps1` after template changes, and `python -B scripts/run-tests.py` (the whole suite across worker processes, see [Python Tests](#python-tests)) after changes to `prism_cli/`, the packaged assets or the template. When the board UI changes, also run the browser tests that [current-status.md](current-status.md#validation) describes.
4. Generate any extra explicit variants you need instead of relying on assumptions.
5. Compare generated output against the root docs, generated README/docs, task wiring, and the selected app lists.
6. Update repository docs when the template contract changes. When a CLI command, message, board behaviour or security check changes, also update the README quickstart, `docs/shared-board.md`, `docs/troubleshooting.md` and `SECURITY.md`, run the documented commands in a disposable workspace, and add the change under `Unreleased` in `CHANGELOG.md`.
7. Keep roadmap-visible options honest about whether they are current, partial, experimental, or planned.

To check the lifecycle with real Claude Code and Codex sessions and a browser against the board, run `scripts/e2e/journey.py`; [`scripts/e2e/README.md`](../scripts/e2e/README.md) describes the tiers and the report.

## Python Tests

`python -B scripts/run-tests.py` runs `tests/` across worker processes (one per CPU by default) and prints one combined summary: the tests run, the failures, errors and skips, and the ID of every failing test. It finds the same tests as `python -B -m unittest discover -s tests` and fails when the workers ran a different number. It exits non-zero on any failure.

```bash
python -B scripts/run-tests.py                       # the whole suite
python -B scripts/run-tests.py -j 4                  # four workers
python -B scripts/run-tests.py test_core test_wiki   # the tests under these module, class or test names
python -B scripts/run-tests.py --shard 2/3           # the second of three fixed shares of the suite (how CI splits a slow job)
python -B scripts/run-tests.py --list                # the units and their expected seconds, without running them
python -B -m unittest tests.test_core                # one module in one process, the way you debug it
```

- A test module is one unit. A module slower than `--target-seconds` is split into units of whole test classes, so a class's fixtures stay with its tests. The workers take the slowest unit first.
- `scripts/test-timings.json` holds the expected seconds of each test class (the plan is a balance of these weights; a class without an entry is weighted by its test count). After a big change of the suite, refresh it from a run: `python -B scripts/run-tests.py -j 8 --write-timings scripts/test-timings.json`.
- Each worker imports the whole suite the way a serial run does, so a test sees the same imported modules in both. The output of a unit is shown only when the unit fails, or with `-v`.
- Every git process a test starts gets `gc.auto=0` and `maintenance.auto=false` through `GIT_CONFIG_COUNT`, `GIT_CONFIG_KEY_n` and `GIT_CONFIG_VALUE_n`, which the runner sets and the CI test steps repeat. A clone, Copier's included, then cannot start a background gc that races with a test's cleanup.
- A test must be safe next to any other test: it takes its folders from `tempfile` (never a fixed name), asks the system for a free port (never a fixed one for a real socket), restores the environment variables and the working directory it changes, and does not depend on the tests that ran before it.
- `browser-e2e` keeps `python -B -m unittest discover -s tests/browser -t .`: it is opt-in and drives one real Chromium.

In CI, every Python test job of `cli-validation.yml` runs `python -B scripts/run-tests.py --shard N/M`. The job is named `Python tests (<os>, <python>, shard N/M)`; the Windows job runs as two shards. The release gate (`scripts/check-ci-green.py`) judges whole workflows, not job names, so it needs no change when a job is renamed or split.

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
- `stacks`, when the skill ships only with some stacks (it ships when any listed stack has an app in the workspace); `reference-stacks` does the same for a file or folder under `references/`. The generator writes these conditions into the generated block of `_exclude` in `copier.yml`;
- the per-host fields: `codex` (`display_name`, `short_description`, `default_prompt`, `implicit` for `allow_implicit_invocation`), `claude-skill` (`argument-hint`, `disable-model-invocation`, `user-invocable`, `allowed-tools`) and `cursor` (`file`, and `globs` or `always-apply`).

The body is written once. Copier conditions and variables (`{% if "spring-backend" in stacks %}`, `{{ project_name }}`) pass through unchanged. Two mechanisms cover the differences between hosts:

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

A skill that teaches a stack's slice cites the files it teaches from in a `## Slice files` section, one bullet each, with the path inside the app's folder (`<package path>` stands for the app's package written with slashes). `tests/test_stack_skill_slice_paths.py` generates a workspace with all five stacks and checks that every cited path exists in every app of the skill's stack, in both skill layers; a skill source that names one stack and has no such section fails it, except the build and deploy task skills. Change a slice file and its skill in the same commit.

## Golden Workspace

`golden/` is a generated workspace in the repository: the CLI generates it from the committed answers file `scripts/golden-answers.yml`, with one app of each generated stack (`backend`, `web`, `mobile-android`, `mobile-ios` and `agent-service`). It shows what a generated project contains, so a template change appears as a diff of the generated files, and CI builds and tests that committed copy.

```bash
python scripts/build-golden.py           # regenerate golden/ (about half a minute)
python scripts/build-golden.py --check   # fail when golden/ differs from a fresh generation; writes nothing
python scripts/sync-golden.py            # after a pin moves: the pack lockfiles, then golden/
```

- **Deterministic.** The project identity is fixed by the answers file. The generation time and the template source in `prism.workspace.yml` and in every `.copier-answers.yml` are replaced by constants, line endings are LF (so a CRLF checkout compares equal), the local `.env` is not part of the workspace, and the files are compared and written in sorted order. A file that is already current is left untouched, and the folders that building leaves behind (`node_modules`, `build`, `.venv`, ...) are skipped. The one value that follows the release is the CLI version in the manifest: after a version bump, regenerate.
- **Kept current.** The `golden-current` job of `template-validation.yml` runs `--check`, and so does a test of the Python suite, so a change of a pack, of the workspace layer or of `packs/versions.yml` that does not refresh `golden/` fails CI.
- **Built and tested by CI.** Each pack's job in `template-validation.yml` also runs the golden app's own workflow, `golden/.github/workflows/<app>.yml`. GitHub runs only the workflows of the repository's own `.github/workflows`, so the job sets up the toolchain from the pins and calls `scripts/run-golden-workflow.py <app>`, which runs the `run:` steps of that generated workflow in order, in their working directory. It refuses an action it does not know, an expression and a condition other than `always()`, `success()` and `failure()`, so a pack workflow cannot change in a way the repository job does not notice (a test dry-runs every golden workflow).
- **Not part of the template or the package.** `copier.yml` renders only `template/` and `packs/<stack>/`; a local template is staged without `golden/`; `MANIFEST.in` prunes it from the source archive and the wheel packages only `prism_cli`.
- **Two files need the executable bit in git.** `golden/backend/gradlew` and `golden/mobile-android/gradlew` are committed as `100755` (`git update-index --chmod=+x`), as the packs' own wrappers are; the workflows also run `chmod +x`.
- Never edit `golden/` by hand: the next regeneration removes the edit.

## Pins in CI

`packs/versions.yml` is the one source of every version a pack uses, and the repository's workflows read it too. `scripts/read-pins.py <stack>` prints the stack's pins as `key=value` lines, and a job writes them to its step outputs:

```yaml
- name: Read the pinned versions
  id: pins
  run: python scripts/read-pins.py android-compose >> "$GITHUB_OUTPUT"
- uses: actions/setup-java@v4
  with:
    distribution: temurin
    java-version: ${{ steps.pins.outputs.jdk }}
```

The Java and JDK of the backend and Android jobs, the Node of the web jobs, the uv and Python of the agent service, and the Android SDK platform and build tools (`android_packages`, composed from `compile_sdk` and `build_tools`) all come from there. The macOS job selects the installed Xcode that matches the `xcode` pin (`--select-xcode`) and checks that it is the one in use, patch releases included (`--check-xcode`); the generated iOS workflow does the same on its pinned `macos-26` runner. The pins are read after Prism is installed, because the script needs PyYAML, which a fresh runner's Python lacks. `tests/test_pin_sources.py` fails when a pack workflow hard-codes a pinned toolchain input (`java-version`, `node-version`, uv's `version` and `python-version`, the SDK packages), spells out an Android SDK package, a build-tools version, an Xcode path or a Gradle version in a step, or reads the pins of one stack for another. Prism's own toolchain (the CLI tests, the npm launcher and the release workflow) is not a pack pin and stays in `cli-validation.yml`, `release.yml` and `npm-release.yml`.

## Dependency Updates

Renovate (`renovate.json`) proposes updates to `packs/versions.yml`, one pull request per pack (`<stack> pack`), on Mondays. A `# renovate: datasource=... depName=... depType=<stack>` line above a pin names what to look up; a pin without one is a baseline decision that moves by hand with a release (the JDK, Node and Python majors, the SDK levels, Xcode, Swift, the iOS target and the database image), and `tests/test_dependency_updates.py` requires every pin to be one or the other. `@types/node` stays on the Node major that the baseline pins. `golden/` is never updated directly, because it is regenerated.

The hosted Renovate app cannot run commands after an update, so `.github/workflows/dependency-sync.yml` does it: on a pull request from `renovate/*` in this repository, it refreshes the lockfile of each stack whose pins differ from the base branch (`scripts/refresh-nextjs-web-lock.py` for the web pack, `scripts/refresh-python-agent-service-lock.py` for the agent service; the Gradle wrapper version comes from the pins when the files are generated), regenerates `golden/`, and pushes one commit to the pull request branch. The work is split in two jobs so that tooling nobody reviewed never holds a write token: `regenerate` runs the branch's scripts and the newly selected toolchains with a read-only token that is not persisted, pinned to the head SHA of the pull request, and uploads one patch; `push` holds the write token, runs none of that code, checks that the branch is still at that SHA and that the patch touches only the pack lockfiles, `packs/versions.yml` and `golden/`, then applies and pushes it. The pull request then carries `packs/versions.yml`, the lockfiles and `golden/` together, and the validation workflows judge all of it. A push with the default token starts no workflows, so the sync workflow starts `template-validation.yml` and `cli-validation.yml` on the branch with `gh workflow run`; set the repository secret `PRISM_BOT_TOKEN` (a token that may push to the repository) to make the push itself start them. Renovate treats the commit of `github-actions[bot]` as its own through `gitIgnoredAuthors`, so it keeps rebasing the branch.

## Security Advisories

The golden web app and the golden agent service are audited in CI: `scripts/audit-gate.py npm golden/web --stack nextjs-web` runs `npm audit --audit-level=high` over the committed lockfile, and `scripts/audit-gate.py uv golden/agent-service --stack python-agent-service` runs `uv audit --locked`. A new advisory fails the job. The fix is a move of the pin in `packs/versions.yml` and `python scripts/sync-golden.py`. Only when no fixed version exists is the advisory listed in `packs/audit-allowlist.yml`, with its advisory link and the reason accepting it is safe, and recorded in [current-status.md](current-status.md#known-dependency-advisories); a test fails for an entry without the link or the reason or one the status page does not record, and the gate warns when an entry no longer matches a finding. The audit runs in the repository's CI, not in the generated project's workflow, so an advisory that has no fix never breaks a user's CI.

## Recommended Validation Variants

- `backend` alone, and `backend` with a second backend at another path (`prism app add api-two --stack spring-backend --path services/api-two --scaffold`)
- `backend` and `mobile-android`
- `backend`, `mobile-android` and `partner-android` (two apps of the `android-compose` stack, the second at `apps/partner`)
- `backend` and `mobile-ios`
- `backend`, `mobile-ios` and `partner-ios` (two apps of the `ios-swiftui` stack, the second at `apps/partner-ios`)
- `backend` and `web`
- `backend`, `web` and `admin` (two apps of the `nextjs-web` stack, with different audiences)
- `backend`, `web`, `mobile-android` and `mobile-ios` (the `full` preset)
- `backend` and `agent-service` (the `python-agent-service` stack; an answers file lists it, and `uv sync --locked`, ruff, mypy, pytest and `python -m evals.run --provider fake` pass in the generated app)
- the preset defaults as a contract-sanity check, not as the main proof of usability

Generate each through the CLI, with a preset or an answers file that lists the apps, because Copier does not ask about apps. Generation renders the working tree (tracked or not), so a test that needs committed state, such as an update across a tag, builds a snapshot repository under a temporary folder (`tests/layered_support.py`).

`./scripts/validate-template.ps1 -Mode contract` generates through `prism new` and checks rendered files and workflows. The default `full` mode also runs backend smoke checks (the pack's tests and boot jar, which need a JDK); both modes disable the script's web smoke helper. Generated web `npm ci`, lint, typecheck, tests and Next.js builds run for two web apps in the separate `web-smoke` CI job in `.github/workflows/template-validation.yml`, and the Gradle `assembleDebug` and unit tests of two Android apps run in its `android-build` job, and XcodeGen, a simulator build and the tests of two iOS apps run in its macOS `ios-build` job. The `backend-smoke`, `web-smoke`, `agent-service`, `android-build` and `ios-build` jobs also run the golden app of their pack, and `golden-current` checks `golden/`. A configured job is not evidence of a passing run on the current changes.

## Reference Commands

Contract validation requires actionlint on PATH (CI installs 1.7.12), or an explicit
`-ActionlintPath` argument. It checks rendered workflows for every generated app.

```bash
./scripts/validate-template.ps1
prism new --preset backend-only --project-name "Test App" --dest ../template-test-backend --yes
prism new --preset backend-web --project-name "Test Web App" --dest ../template-test-web --yes
prism new --preset full --project-name "Test Full App" --dest ../template-test-full --yes
copier copy --trust --defaults --data "project_name=Test App" . ../template-test-workspace-layer   # one layer only
python scripts/build-golden.py --check
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
