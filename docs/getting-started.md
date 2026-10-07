# Getting Started

For the workflow and shared human/agent board without generating applications,
follow the [README quickstart](../README.md#quickstart-a-shared-board-for-you-and-your-agents)
and the [shared board guide](shared-board.md); [troubleshooting.md](troubleshooting.md)
lists fixes for the common failures. This page covers the optional
application-generation path.

This page is the safest first-run path for trying Prism.

If you only want the shortest route:

1. install Prism from PyPI
2. run `prism doctor`
3. run `prism`
4. generate one focused sample
5. validate the generated repo
6. inspect the generated repo and run `setup-project`
7. validate the slices you care about before treating them as settled

## 1. Pick A Small First Evaluation Path

Use the smallest path that answers your question.

Recommended first evaluation paths:

- **Backend only** for repository shape and contract inspection
- **Backend + Mobile** for the Android and iOS client path; the Android app builds and passes its JVM tests with JDK 21 and an Android SDK, and the iOS app is built and tested by the macOS CI job
- **Backend + Web** to inspect the web slice: a Next.js app with a local development sign-in and one authenticated read, built, tested and proven in CI
- **Full** for one app of every stack: the backend, a web app, an Android app and an iOS app

For the maturity notes behind those recommendations, read
[current-status.md](current-status.md).

## 2. Install Prism And Its Prerequisites

Start with the minimum needed to generate a project, then add the rest based on the
workflow you want to exercise.

Required to generate a project:

- Python 3.10+ (uv installs one when none is present)
- Prism from PyPI, which provides the `prism` command:

```bash
uv tool install prism-kit
prism --version
```

`pipx install prism-kit` and `pip install prism-kit` work as well. If `prism` is not
found after `uv tool install`, run `uv tool update-shell` and open a new terminal; upgrade
later with `uv tool upgrade prism-kit`. Without a Python setup, Node.js 22 or later can
run the same CLI through the npm launcher, which fetches uv and the matching `prism-kit`
on first use: `npx @mortitech/prism --version`, or `npm install --global @mortitech/prism`
for a `prism` command.
The distribution is `prism-kit` and the import package remains `prism_cli`. The install
brings the CLI's generation dependencies (`copier`, `jinja2-time` and `PyYAML`) and the
shared-board runtime dependencies (`mcp==2.2.0`, `starlette` and `uvicorn`); `pyproject.toml`
lists the exact ranges. The optional `e2e` extra adds Playwright for the browser tests.

To work on Prism itself, install an editable copy from a checkout:

```bash
git clone https://github.com/mo0rti/prism.git
cd prism
python -m pip install -e .
```

To check a wheel built from a checkout before it is published:

```bash
python -m pip install build
python -m build
python -m pip install dist/prism_kit-0.5.0-py3-none-any.whl
```

An installed CLI uses the canonical GitHub template by default, at the release tag
that matches the CLI version (`v0.5.0` for Prism 0.5.0). When that tag does not exist,
for example in a build of an unreleased checkout, `prism new` stops with exit code 3 and
one message, and creates nothing:

```text
The template release tag `v0.5.0` is not published, so the default template cannot be used. Pass `--template <path or URL>` or install a released version of Prism.
```

Pass `--template <path-or-url>` to choose another template, for example a checkout
of this repository. A custom template can run code, so Prism asks you to trust it;
`--trust-template` gives that trust without a prompt:

```bash
prism new --preset backend-only --project-name "My App" --dest ../my-app --template /path/to/prism --trust-template --yes
```

A local checkout uses its local template automatically.

Useful first commands after install:

```bash
prism --version
prism doctor
prism doctor --preset backend-mobile
prism presets
```

`prism presets` lists the generation presets, and under "Workflow presets" the knowledge root, a workflow-only workspace for apps in other repositories. `prism presets --json` returns the two lists separately.

`prism doctor` separates Prism core readiness from workflow and platform checks, so it
is the fastest way to see what is blocked versus what can wait.

Required to use generated task commands:

- [go-task](https://taskfile.dev/)

Required for shared tooling in generated projects:

- Node.js LTS
- `npm install -g @openapitools/openapi-generator-cli`

Required for common backend and container workflows:

- JDK 21
- Docker Desktop (the backend's integration tests start PostgreSQL with Testcontainers, and the local database runs in Docker Compose)

Required for iOS work on macOS:

- `brew install xcodegen`
- Xcode
- `gem install fastlane`

`go-task` and the platform generator CLIs remain external dependencies for generated
projects. They are not bundled with generated projects; use `prism doctor` to see
which optional tools are available.

## 3. Generate Your First Project With Prism

Run:

```bash
prism
```

Running bare `prism` opens the Prism home screen. Its choices depend on the folder you
run it in. From a plain folder you can:

- choose `New Project`
- choose `Doctor`
- choose `Browse Presets`
- choose `Validate Current Directory` (`Validate Template Repo` in this checkout)
- press `/` to open the command palette and filter commands directly

Inside a generated project, the home screen also offers the dashboard, validation and update.

![Prism home screen](media/prism-menu.png)

If you run `prism new` with no extra flags, Prism starts the guided interactive flow:

- shows the recommended presets, each an app list
- lets you choose a preset or advanced mode
- asks for missing project details
- uses interactive selectors for the apps to scaffold, and further apps (an ID, a stack, a path and whether to scaffold or only register them)
- defaults the destination folder to `workspaces/<project-slug>`
- shows a final review screen before generation

![Preset selection during guided project creation](media/prism-new-project.png)

You can also generate non-interactively with a recommended preset:

```bash
prism new --preset backend-mobile --project-name "My Mobile App" --dest ../my-mobile-app
prism validate ../my-mobile-app
```

You can also generate from an answers file that lists the apps ([questionnaire.md](questionnaire.md)):

```bash
prism new --answers my-platform.yml --dest ../my-platform
```

The Prism CLI is the main entry point for generation in this repository. It runs Copier once
for the workspace layer and once for each scaffolded app, each layer with its own answers file,
so the raw Copier commands are only a layer-level fallback underneath it.

Optional deeper context before choosing a non-standard path:

- read [questionnaire.md](questionnaire.md) if you want the full question surface and option-specific caveats
- read [current-status.md](current-status.md) for the verification behind each platform before evaluating a slice

## 4. Validate What You Generated

Start with the Prism CLI structural check:

```bash
prism validate /path/to/generated-project
```

Then, if the supporting tools are installed:

- run `task validate-api`
- run `task generate-clients`
- inspect the generated root `Taskfile.yml`
- inspect platform-specific docs and environment files

Platform-specific caution:

- for a `spring-backend` app, run `task db-up` and `task <app-id>:dev` to start it with the `local`
  Spring profile, sign in with `POST /api/dev-identity/token` and read `GET /api/me` (the app's
  `README.md` has the commands), then run `task <app-id>:test`. The dev identity is local development
  sign-in, not authentication: never enable the `local` profile on a shared environment, and replace it
  with your identity provider (the generated `security-auth` skill has the steps) before you expose the app
- for each web app, run `npm ci`, `npm run lint`, `npm run typecheck`, `npm test` and `npm run build`
  in its folder, then start a backend under its `local` profile and try the "Local development
  sign-in"; that sign-in is a development identity, not complete authentication, and hosting is yours
  to choose (see the `deployment` skill)
- for each Android app, run `./gradlew assembleDebug testDebugUnitTest` in its folder (JDK 21 and an Android SDK with the platform its `README.md` names), then start a backend under its `local` profile, run `adb reverse tcp:8080 tcp:8080` (`task <app-id>:reverse`) and try the "Local development sign-in" on an emulator or a USB device; that sign-in is a development identity, not complete authentication
- for each iOS app, on macOS run `task <app-id>:build` and `task <app-id>:test` (they generate the Xcode project with XcodeGen first), then start a backend under its `local` profile and try the "Local development sign-in" in the simulator; the dev identity works in the simulator only, because the backend serves it to loopback requests, and it is not complete authentication. The macOS CI job is the build proof, and validating locally on macOS comes before you treat the slice as build-proven

Do not assume every command, workflow, or platform combination has been fully hardened just
because the repository generated successfully.

For the generated workspace contract and current wiki queues, use the read-only status
surface:

```bash
prism status /path/to/generated-project --full
prism status /path/to/generated-project --full --json
prism doctor --workspace /path/to/generated-project
```

`status --full` includes the effective `SETTINGS.md` staleness setting, advisory review
counts, documented generation answers, and template provenance. It omits private Copier
metadata and unknown answer keys. `doctor --workspace` returns a validation failure when
the manifest, answers, or detected platform directories contain contract errors. Status and
doctor list the workspace's apps (ID, name, stack, repository, path, status and maturity); the
apps you list become the manifest's apps (`scaffolded` or `registered`), and `prism app list` shows the same table. [workspace-model.md](workspace-model.md)
explains apps and repositories and how `prism app add` registers another one.

If you are maintaining the Prism template repo itself, you can also run:

```bash
prism validate --kind template --template-mode contract .
```

## 5. Inspect The Generated Repository

Before treating the generated repo as production-ready, start with structural checks:

- confirm each scaffolded app's directory exists
- confirm `README.md`, `AGENTS.md`, and `knowledge/wiki/SCHEMA.md` exist
- inspect the generated root `Taskfile.yml`
- inspect `.github/workflows/` for the apps you scaffolded (one `<app-id>.yml` each)
- inspect the generated platform docs

Then move into the generated project workflow:

1. open the generated repository
2. initialize the wiki with:
   - Claude Code: `/setup-project`
   - Codex: `$setup-project`
   - Cursor: ask the agent to run `setup-project`
3. inspect `knowledge/wiki/SCHEMA.md` and `knowledge/wiki/LIFECYCLE.md`
4. run `feature-status` if you want an orientation report
5. add a first feature: create a dated folder such as
   `knowledge/intake/pending/2026-10-06-my-first-feature/`, put your brief in it as a
   Markdown file, and run `po-intake` on it (or `ingest` for notes that are not a feature
   request); the feature appears as a row of `knowledge/wiki/status-board.md`, and
   `knowledge/wiki/index.md` lists every page
6. use the read/query layer before mutating lifecycle state

The feature lifecycle has separate confirmation-gated actions. Use
`$po-specify F-XXX` in Codex or `/po-specify F-XXX` in Claude Code to read one
`raw` + `po` feature and prepare its complete structured draft. It carries
supported facts forward and keeps unknowns as owned questions. A well-structured
raw body may be verified and preserved; an incomplete one is authored before
the status changes. After factual completeness, use `po-handoff` for
`specified` + `po` -> `ready-for-design` + `designer`, then use `design-start`,
`design-handoff`, `dev-start`, and `dev-done` for the confirmed downstream
routes. Reopen shipped work with `feature-reopen F-XXX [specified|in-design|in-dev]`
after impact review. Each action reads one exact source pair and leaves the
feature, status board, and log unchanged when declined or cancelled.

The optional read-only preflight is:

```bash
prism wiki transition-preflight F-XXX /path/to/generated-project --action po-handoff --json
```

Use it only when its response explicitly identifies common envelope schema 1,
the transition-preflight command facts, capability version 2 with the requested
action's surface, transition version 1, and a consistent snapshot. A version
string alone does not prove that surface; missing or unsupported
capability falls back to direct wiki reads. The preflight and dashboard are
copy-only, and the agent must reread the source before any confirmed write. The
selected generated action file must contain its matching
`<!-- prism:<command>-contract:v1 -->` marker; the other surface is optional.
Refresh a selected file with a missing marker before using that action.

For a shipped feature, `dev-done` requires a current Delivery evidence row for
each declared app with verifiable implementation and test references and
release evidence or a delivery attestation (a commit or pull request alone does
not prove shipment). A confirmed reopen archives the previous evidence, removes it from
active readiness, and sets route-specific `revalidation` domains as described in
the generated `knowledge/wiki/LIFECYCLE.md`.

If you want the conceptual reason Prism works this way, read
[prism-model.md](prism-model.md) before going deeper into the generated workflow.

For the generated-project structure and safe-first commands, continue with
[generated-projects.md](generated-projects.md).

## 6. Update A Generated Project

Inside a generated repository:

```bash
prism update /path/to/generated-project
```

This is the Prism-managed update path. It expects the generated project to include
`.copier-answers.yml`, which Prism writes during `prism new`, and each scaffolded app's own
`<path>/.copier-answers.yml`.

Use updates only after reviewing template changes and only in a generated project that is
already under version control with a clean git working tree.

`prism update` works on an update branch (`prism-update-<template tag>`) and brings every layer to the same template
tag, one commit per layer: first the workspace layer, then each active scaffolded app from its own answers file.
Copier needs a clean tree for each update, so each layer is committed before the next. After each layer Prism
scans for `.rej` files and conflict markers (Copier exits 0 on a conflict) and reports per layer:

```text
workspace layer: updated, committed as d2149c3
app backend: updated, committed as 84480a7
app api-two: CONFLICT in 1 file(s), committed as 6565f95
    services/api-two/AGENTS.md
```

Without conflicts the branch stays checked out for you to review and merge (`git switch <original branch>` then
`git merge --ff-only prism-update-<tag>`); Prism never merges for you. When a layer conflicted, the update exits with 6
before merging, and the branch holds one commit per layer with the conflict as `<<<<<<<` markers: resolve them there,
commit, then merge. The manifest is merged field by field as before. Copier's `.rej` files (the hunks it could not apply)
are never committed: they stay in the working tree beside the conflict markers, for you to resolve and delete.

A scaffolded app whose own answers file is missing stops the update before anything changes. The message names three
ways out: restore the file from git, retire the app (`prism app retire <id>`), or drop its entry from
`prism.workspace.yml` (or set its `generation` to `registered`) when Prism no longer keeps its code current.

A retired app is left out of the update, but the workspace layer keeps rendering what it rendered for it: its service in
`docker-compose.yml` and its task include in `Taskfile.yml` stay until you remove them (with the app's code, when you
choose to). Retiring changes only the manifest entry; it deletes nothing.

`prism update` uses Copier's smart update when `.copier-answers.yml` records a remote
template source and a saved revision. A project generated from a local checkout records an
unversioned snapshot, so `prism update` stops with an error and asks for an explicit
recopy instead of guessing a baseline. To reapply the template explicitly:

```bash
prism update /path/to/generated-project --strategy recopy
```

Recopy also works on a branch, one commit per layer (`prism-recopy-<timestamp>`). It overwrites customized template
files and renders the manifest from the template again, but keeps the workspace's apps and repositories. Non-interactive recopy requires `--yes`.
Custom template sources require a separate trust confirmation or `--trust-template`;
`--yes` does not grant code-execution trust. Raw Copier generation saves
`.copier-answers.yml`, including version provenance when the source is versioned.

## 7. Raw Copier Fallbacks

Raw Copier renders one layer, chosen by the hidden question `prism_layer`. Use it for template development, not to generate a workspace.

The workspace layer from GitHub or from a local checkout (it has no apps unless you pass them):

```bash
copier copy --trust --defaults --data project_name="My Project" https://github.com/mo0rti/prism.git ../my-new-project
copier copy --trust --defaults --data project_name="My Project" . ../my-new-project
```

One app layer, into an existing workspace, with that app's own answers file:

```bash
copier copy --trust --defaults --answers-file services/api-two/.copier-answers.yml \
  --data prism_layer=spring-backend --data project_name="My Project" --data app_id=api-two --data app_path=services/api-two . ../my-new-project
```

The `--trust` flag is required because this template uses the `jinja2_time` Jinja
extension.

The Prism package already installs Copier and `jinja2-time`. Install those packages
separately only when using the raw Copier path without installing Prism:

```bash
python -m pip install copier jinja2-time
```

Use the raw Copier path when:

- you are contributing to the template and want the fastest low-level feedback loop on one layer
- you need to compare Prism CLI behavior with the underlying rendering path
- you are debugging Copier-specific generation behavior

## 8. What To Read Next

If you just generated a project:

1. [generated-projects.md](generated-projects.md)
2. [prism-model.md](prism-model.md)
3. [wiki-workflow.md](wiki-workflow.md)

If you are evaluating maturity before deeper adoption:

1. [current-status.md](current-status.md)
2. [wiki-validation.md](wiki-validation.md)

If you are maintaining the template:

1. [maintainer-workflow.md](maintainer-workflow.md)
2. [questionnaire.md](questionnaire.md)
