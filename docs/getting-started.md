# Getting Started

This page is the safest first-run path for evaluating Prism.

If you want a fast summary:

1. install the generation prerequisites
2. skim [questionnaire.md](questionnaire.md)
3. generate a focused sample with the Prism CLI or raw Copier
4. inspect the generated repo shape
5. run `setup-project` inside the generated project
6. validate the slices you care about before treating them as settled

## 1. Choose Your Starting Path

Use the smallest path that answers your question.

Recommended first evaluation paths:

- **Backend only** for repository shape and contract inspection
- **Backend + Android** for the strongest current application path
- **Backend + User Web App** or **Backend + Admin Web Portal** for focused web evaluation
- **Backend + User Web App + Admin Web Portal** to inspect the initial web/admin setup together
- **Backend + iOS** only if you are prepared to validate iOS details locally on macOS

For current maturity notes behind those recommendations, read
[current-status.md](current-status.md).

## 2. Install What You Need

Start with the minimum required to generate a project, then add the rest based on the
workflow you plan to exercise.

Required to generate a project:

- Python 3.10+
- `pip install copier`
- optional but recommended during CLI incubation: `pip install -e .`

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

`copier`, `go-task`, and the generator CLIs are external dependencies. They are not bundled
with this repository or with generated projects.

## 3. Skim The Questionnaire First

Before generating, skim [questionnaire.md](questionnaire.md) for:

- available platform combinations
- auth-method caveats
- current maturity notes
- the safest initial combinations to try first

This saves time if you are evaluating a path that is still partial or experimental.

## 4. Generate A Project

### Generate with the incubating Prism CLI

From a local checkout of this template repo:

```bash
pip install -e .
prism
```

Running bare `prism` now opens the Prism home screen, where you can choose
commands like `New Project`, `Doctor`, `Validate`, and `Presets`.

From that home screen, press `/` to open the command palette and filter Prism
commands directly.

If you run `prism new` with no extra flags, Prism starts the guided interactive flow:

- shows the recommended presets
- lets you choose a preset or advanced mode
- asks for the missing project details
- uses an interactive multiselect for platform and auth choices
- defaults the destination folder to `generated`
- shows a final review screen before generation

You can also generate non-interactively with a recommended preset:

```bash
prism new --preset backend-android --project-name "My Mobile App" --dest ../my-mobile-app
prism validate ../my-mobile-app
```

The CLI is currently the incubating front door for Prism generation inside this
repository. Raw Copier commands remain the lower-level fallback and the
authoritative rendering path underneath the CLI.

### Generate directly from GitHub

```bash
copier copy --trust https://github.com/mo0rti/prism.git ../my-new-project
```

The `--trust` flag is required because this template uses the `jinja2_time` Jinja
extension.

### Generate from a local checkout

If you are contributing to the template itself, generating from a local checkout is the
fastest feedback loop:

```bash
copier copy --trust . ../my-new-project
```

## 5. Use Focused Sample Variants

Backend-only sample:

```bash
copier copy --trust --defaults \
  --data "project_name=My Backend App" \
  --data "platforms=[backend]" \
  . ../my-backend-app
```

Backend plus Android sample:

```bash
copier copy --trust --defaults \
  --data "project_name=My Mobile App" \
  --data "platforms=[backend, mobile-android]" \
  . ../my-mobile-app
```

Backend plus initial web/admin setup sample:

```bash
copier copy --trust --defaults \
  --data "project_name=My Web App" \
  --data "platforms=[backend, web-user-app, web-admin-portal]" \
  . ../my-web-app
```

Use focused samples instead of starting with the largest possible combination unless your
goal is specifically combination testing.

## 6. Inspect What Was Generated

Before treating the generated repo as production-ready, start with structural checks:

- confirm the selected platform directories actually exist
- confirm `CONTEXT.md` and `knowledge/wiki/SCHEMA.md` exist
- inspect the generated root `Taskfile.yml` for references to missing modules
- inspect the generated `README.md` and platform docs
- inspect `.github/workflows/` for the slices you selected

Then move into the generated project workflow:

1. open the generated repository
2. initialize the wiki with:
   - Claude Code: `/setup-project`
   - Codex: `$setup-project`
   - Cursor: ask the agent to run `setup-project`
3. inspect `knowledge/wiki/SCHEMA.md` and the generated project `README.md`
4. run `feature-status` if you want a generated orientation summary
5. use the read/query commands before mutating lifecycle state

For the generated-project structure and command surface, continue with
[generated-projects.md](generated-projects.md).

## 7. Validate The Generated Repo

Shared validation checks:

- run `prism validate /path/to/generated-project` for a first structural pass
- validate the API contract with `task validate-api` if `go-task` is installed
- generate clients with `task generate-clients` if the OpenAPI generator is installed
- inspect the generated root `Taskfile.yml`
- inspect platform-specific docs and environment files

Platform-specific caution:

- for `web-user-app` and `web-admin-portal`, inspect Next.js routes, auth handlers, and
  OpenNext/Wrangler config before treating the setup as settled
- for `mobile-ios`, validate locally on macOS before treating the slice as build-proven

Do not assume every command, workflow, or platform combination has been fully hardened just
because the repository generated successfully.

If you are maintaining the template repo itself, you can also run:

```bash
prism validate --kind template --template-mode contract .
```

This wraps the existing template validation script with a Prism CLI entry point.

## 8. Update An Existing Generated Project

Inside a generated repository:

```bash
prism update /path/to/generated-project
```

This is the safer Prism-managed update path. It expects the generated project to include
`.copier-answers.yml`, which Prism now writes during `prism new`.

Use updates only after reviewing template changes and only in a generated project that is
already under version control with a clean git working tree.

During local incubation, Prism may fall back to a Copier `recopy` strategy because the
template repo is not yet version-tagged for a full `copier update` flow. If you need to
force that path explicitly:

```bash
prism update /path/to/generated-project --strategy recopy
```

## 9. What To Read Next

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
