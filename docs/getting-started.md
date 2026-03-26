# Getting Started

## 1. Install Prerequisites

Start with the minimum required to generate a project, then install the rest based on the workflow you want to use.

Required to generate a project:

- Python 3.10+ with `pip install copier`

Required to use generated task commands:

- [go-task](https://taskfile.dev/)

Required for shared tooling in generated projects:

- Node.js LTS
- `npm install -g @openapitools/openapi-generator-cli`
- `npm install -g hygen`

Required for platform-specific build paths:

- JDK 21
- Docker Desktop

For iOS work on macOS:

- `brew install xcodegen`
- Xcode
- `gem install fastlane`

`copier`, `go-task`, and the generator CLIs are external dependencies. They are not bundled with this repository or with generated projects.

## 2. Review The Questionnaire

Before generating, skim [questionnaire.md](questionnaire.md) for the current inputs, defaults, and maturity notes.

## 3. Generate Directly From GitHub

```bash
copier copy --trust https://github.com/mo0rti/Template.git ../my-new-project
```

The `--trust` flag is required because this template uses the `jinja2_time` Jinja extension.

## 4. Generate From A Local Checkout

If you are contributing to the template itself, generating from a local checkout is the fastest feedback loop:

```bash
copier copy --trust . ../my-new-project
```

## 5. Generate Sample Projects Non-Interactively

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

## 6. Update An Existing Generated Project

Inside a generated repository:

```bash
cd /path/to/generated-project
copier update --trust
```

Use this only after reviewing template changes and only in a generated project that is already under version control.

## 7. Validate What Was Generated

Start with structural checks before treating the generated repo as production-ready:

- confirm the selected platform directories actually exist
- inspect the generated root `Taskfile.yml` for references to missing modules
- inspect the generated `README.md` and platform docs
- inspect `.github/workflows/` for the slices you selected
- validate the API contract with `task validate-api` if you have `go-task` installed
- generate clients with `task generate-clients` if you have the OpenAPI generator installed
- for `web-user-app` and `web-admin-portal`, inspect the generated Next.js routes, auth handlers, and OpenNext/Wrangler config before treating the setup as settled

Do not assume `task lint`, `task test`, or every multi-platform selection is validated for every combination yet.

## 8. Start Inside The Generated Project

Generated projects do include their own `README.md`, but the safest practical flow right now is:

1. confirm the selected platform directories exist
2. copy `.env.example` to `.env`
3. inspect the generated root `Taskfile.yml` and generated `README.md`
4. run `task validate-api` and `task generate-clients` if `go-task` and the OpenAPI generator are installed
5. validate platform-specific build, install, and run commands before treating them as settled workflow

For now, treat backend-only, backend + Android, and focused web/admin samples as the best first evaluation paths.
