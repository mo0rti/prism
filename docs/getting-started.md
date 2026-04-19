# Getting Started

This page is the safest first-run path for trying Prism.

If you only want the shortest route:

1. install Prism locally from this repo
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
- **Backend + Android** for the strongest current application path
- **Backend + User Web App** or **Backend + Admin Web Portal** for focused web evaluation
- **Backend + User Web App + Admin Web Portal** if you want to inspect the initial web/admin setup together
- **Backend + iOS** only if you are prepared to validate iOS details locally on macOS

For the maturity notes behind those recommendations, read
[current-status.md](current-status.md).

## 2. Install Prism And Its Prerequisites

Start with the minimum needed to generate a project, then add the rest based on the
workflow you want to exercise.

Required to generate a project:

- Python 3.10+
- `pip install copier`
- `pip install -e .`

Useful first commands after install:

```bash
prism doctor
prism presets
```

Required to use generated task commands:

- [go-task](https://taskfile.dev/)

Required for shared tooling in generated projects:

- Node.js LTS
- `npm install -g @openapitools/openapi-generator-cli`
- `npm install -g hygen`

Required for common backend and container workflows:

- JDK 21
- Docker Desktop

Required for iOS work on macOS:

- `brew install xcodegen`
- Xcode
- `gem install fastlane`

`copier`, `go-task`, and the generator CLIs are external dependencies. They are not
bundled with this repository or with generated projects.

## 3. Generate Your First Project With Prism

From a local checkout of this repository:

```bash
prism
```

Running bare `prism` opens the Prism home screen. From there you can:

- choose `New Project`
- choose `Doctor`
- choose `Validate`
- choose `Presets`
- press `/` to open the command palette and filter commands directly

If you run `prism new` with no extra flags, Prism starts the guided interactive flow:

- shows the recommended presets
- lets you choose a preset or advanced mode
- asks for missing project details
- uses interactive selectors for platform and auth choices
- defaults the destination folder to `generated`
- shows a final review screen before generation

You can also generate non-interactively with a recommended preset:

```bash
prism new --preset backend-android --project-name "My Mobile App" --dest ../my-mobile-app
prism validate ../my-mobile-app
```

The Prism CLI is now the main entry point for generation in this repository. Raw Copier
commands remain the lower-level fallback underneath it.

Optional deeper context before choosing a non-standard path:

- read [questionnaire.md](questionnaire.md) if you want the full question surface and option-specific caveats
- read [current-status.md](current-status.md) if you want the latest maturity guidance before evaluating a partial slice

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

- for `web-user-app` and `web-admin-portal`, inspect Next.js routes, auth handlers, and
  OpenNext/Wrangler config before treating the setup as settled
- for `mobile-ios`, validate locally on macOS before treating the slice as build-proven

Do not assume every command, workflow, or platform combination has been fully hardened just
because the repository generated successfully.

If you are maintaining the Prism template repo itself, you can also run:

```bash
prism validate --kind template --template-mode contract .
```

## 5. Inspect The Generated Repository

Before treating the generated repo as production-ready, start with structural checks:

- confirm the selected platform directories exist
- confirm `README.md`, `CONTEXT.md`, and `knowledge/wiki/SCHEMA.md` exist
- inspect the generated root `Taskfile.yml`
- inspect `.github/workflows/` for the slices you selected
- inspect the generated platform docs

Then move into the generated project workflow:

1. open the generated repository
2. initialize the wiki with:
   - Claude Code: `/setup-project`
   - Codex: `$setup-project`
   - Cursor: ask the agent to run `setup-project`
3. inspect `knowledge/wiki/SCHEMA.md`
4. run `feature-status` if you want an orientation report
5. use the read/query layer before mutating lifecycle state

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
`.copier-answers.yml`, which Prism writes during `prism new`.

Use updates only after reviewing template changes and only in a generated project that is
already under version control with a clean git working tree.

During local incubation, Prism may fall back to a Copier `recopy` strategy because the
template repo is not yet version-tagged for a full `copier update` flow. If you need to
force that path:

```bash
prism update /path/to/generated-project --strategy recopy
```

## 7. Raw Copier Fallbacks

If you need to bypass the Prism CLI and generate directly:

Generate from GitHub:

```bash
copier copy --trust https://github.com/mo0rti/prism.git ../my-new-project
```

Generate from a local checkout:

```bash
copier copy --trust . ../my-new-project
```

The `--trust` flag is required because this template uses the `jinja2_time` Jinja
extension.

Use the raw Copier path when:

- you are contributing to the template and want the fastest low-level feedback loop
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
