# Questionnaire

`prism new` collects the project identity and the app list. Copier does not ask about apps: the CLI collects the app list, from a preset, an answers file or the interactive flow, and gives each generation layer its answers ([workspace-model.md](workspace-model.md) describes the layers).

| Input | Description | Default |
|-------|-------------|---------|
| **Project name** | Human-readable name (e.g., `My Awesome App`) | *(required)* |
| **Project slug** | Lowercase slug for directories (e.g., `my-awesome-app`) | derived from name |
| **Package identifier** | Reverse-domain ID (e.g., `com.example.myawesomeapp`) | derived from slug |
| **Description** | One-line project description | `A multi-platform application` |
| **Apps** | The workspace's apps: each has an ID, a stack, a name, a path, an audience, a repository and whether Prism scaffolds it or only registers it | the preset's apps |

The agent integrations are not a question: every generated workspace carries guidance for Claude Code, Codex and Cursor from one source, and `prism workflow install` adds the workflow to an existing repository.

## Apps

An app is `{id, stack}` plus optional `name`, `path`, `audience`, `repository`, `remote`, `generation` and `backend`:

- `id` is a stable slug. `stack` comes from the registry: `spring-backend`, `nextjs-web`, `android-compose`, `ios-swiftui`, `python-agent-service` or `other`. The interactive flow's app list offers every stack that has a pack, the agent service included (`prism workflow install --app agent-service` takes it too); further apps, of any stack, follow in its "another app" step, an answers file lists them, and `prism app add` adds them later.
- `path` defaults to the stack's default path (`backend`, `mobile-android`, `mobile-ios`, `agent-service`), else the ID (`web` for the default web app). Each segment is lowercase letters, digits, `.`, `_` and `-`, starts with a letter or a digit and does not end with a dot (`apps/partner` and `services/api-two` are fine; `apps/$(id)`, `Apps/Web` and `apps/my app` are refused).
- `audience` is free text, for example `B2C` or `internal`. No gate reads it. For a `nextjs-web` app it is display text in the app's header and guidance, nothing more. The interactive flow asks for it, and `prism app add --audience` sets it.
- `generation` is `scaffolded` (Prism generates the code and `prism update` keeps it current) or `registered` (the manifest records it; the code lives elsewhere). An app of a generated stack in this repository defaults to `scaffolded`; an app in an external repository, or of the `other` stack, is always registered. An external app also names its repository's `remote`.

- `backend` names the backend app that a web, Android, iOS or agent-service app calls (an app of the `spring-backend` stack). Without it a generated client calls the first backend Prism scaffolded, and the CLI renders that backend's loopback address (`http://localhost:<its port>`) into every default of the client: its `.env.example`, its configuration, its Taskfile, its guidance and the `servers` of the shared contract. A client generated against the second backend points at the second backend's port. The interactive flow asks which backend each client calls when there are several, `prism app add --backend <app id>` sets it for a new app, and the app's `.copier-answers.yml` remembers the address (`backend_base_url`, a loopback URL, which you may edit when a backend moves).

A preset is an app list over the first four packs (the agent service is added to a preset's apps with one more entry, below), and `prism presets` (and `prism presets --json`) show each one's apps:

| Preset | Apps |
|--------|------|
| `backend-only` | `backend` |
| `backend-web` | `backend`, `web` |
| `backend-mobile` | `backend`, `mobile-android`, `mobile-ios` |
| `full` | `backend`, `web`, `mobile-android`, `mobile-ios` |

An answers file carries the same list, and a second web app is one more entry of the same stack:

```yaml
schema_version: 1
answers:
  project_name: My Platform
  apps:
    - {id: backend, stack: spring-backend}
    - {id: partner-api, stack: spring-backend, path: services/partner-api, audience: B2B}
    - {id: web, stack: nextjs-web, audience: B2C}
    - {id: admin, stack: nextjs-web, audience: internal}
    - {id: customer-android, stack: android-compose, repository: mobile, remote: "https://example.com/acme/mobile.git", path: apps/customer}
    - {id: agent-service, stack: python-agent-service}
```

`apps: []` generates the workspace layer alone, and `prism app add --scaffold` adds an app later. Leaving `apps` out is an error.

### What Prism derives for each scaffolded app

The CLI derives, validates and records these in the app's own answers file (`<path>/.copier-answers.yml`); a pack never reads a platform ID:

- `app_package_segment`: the ID without hyphens. It must pass the package-identifier rules (a letter first, no Kotlin or Java keyword) and be unique across every app of the workspace, so `my-app` and `myapp` collide.
- the package, directory path and module name: `<package_identifier>.<segment>`, its path, and the ID in PascalCase.
- the CI workflow name and `paths:` filters, scoped to the app's path.
- `port`: the first free port of the stack's range (`spring-backend` from 8080, `nextjs-web` from 3000, `python-agent-service` from 8200), chosen when the app is added and kept in its answers. Removing another app never moves it.
- `backend_base_url` (a client of a backend: a web, Android, iOS or agent-service app): the loopback address of the backend it calls, from that backend's port. It is a loopback URL by validation, because the development identity answers loopback requests only.
- the web package name, `<project_slug>-<app id>`, and the session cookie name, `<app id>_session` with hyphens as underscores: each web app has its own, because apps on `localhost` share one cookie jar whatever their port.

### Values that reach generated files

An app's ID, path, name and audience and the project's name and description end up in shell steps, YAML, Gradle, Xcode, npm and pyproject files, `.env` files and Markdown that agents read, so they are checked at every entry point (the manifest, `prism new`, `prism app add` and the validators of `copier.yml`, which cover a raw `copier copy`):

- an app **name**, an **audience** and the **project name** are one line of at most 80 letters, digits, spaces and the characters `. , - _ ( ) + / &`;
- the **description** is one line of at most 200 characters of the same set plus `' : ; ! ?`;
- a **path** follows the segment rule above, at most 200 characters, with no Windows device name (`con`, `nul`, `com1`, ...) as a segment.

The templates also serialize a value wherever it enters YAML (`| tojson`), and a pack workflow passes the app's path to its shell steps through one quoted environment variable (`APP_PATH`), never inline. A value that breaks a rule is refused with the rule in the message.

An app ID and path must not replace a file of the workspace layer: an ID such as `api-contracts` (a workspace workflow) or a path inside `docs/`, `knowledge/`, `shared/` or `.github/` is refused, and an app's own path must be empty or absent.

### Stacks and packs

| Stack | What `prism new` generates today |
|-------|----------------------------------|
| `spring-backend` | The `spring-backend` pack: a Spring Boot app with one tested slice (the local development identity and `GET /api/me` with a `users` table), a CI workflow, a Cursor rule and its own guidance, under the app's path |
| `nextjs-web` | The `nextjs-web` pack, once per web app: a Next.js app with a "Local development sign-in" route that keeps the dev-identity token in an httpOnly cookie, one page that shows `GET /api/me` through a client generated from the shared OpenAPI contract, Vitest and Testing Library tests, a committed `package-lock.json`, a CI workflow that runs `npm ci`, lint, typecheck, test and build, and a Cursor rule, under the app's path. Any number of web apps, each with its own port, package name and workflow |
| `android-compose` | The `android-compose` pack, once per Android app: a Kotlin and Jetpack Compose app with a "Local development sign-in" screen, a profile screen that shows `GET /api/me` through a hand-written Retrofit client checked against the shared OpenAPI contract, an in-memory session, JVM unit tests (state holders, client, contract and a Robolectric Compose test), the Gradle wrapper, a CI workflow that runs `assembleDebug` and `testDebugUnitTest`, and a Cursor rule, under the app's path. Any number of Android apps, each with its own application ID, namespace, package directories, Gradle project name and workflow |
| `ios-swiftui` | The `ios-swiftui` pack, once per scaffolded app at its own path: an XcodeGen project, a "Local development sign-in" and a profile screen, XCTest unit tests and one UI test, and the app's workflow and Cursor rule. Each app has its own module, target, scheme, Xcode project name and bundle identifier, derived from its ID |
| `python-agent-service` | The `python-agent-service` pack, once per agent service: a FastAPI app with `GET /api/health` and `POST /api/assist`, one agent turn through a provider interface (a deterministic fake and a Claude API adapter) with one read-only example tool that calls the backend's `GET /api/me` with the caller's token, bearer-token verification against the backend's JWKS with no shared secret (fail-closed at startup), the safety rules (untrusted data, an audit log with user and request IDs, a per-user budget, no cross-user data, a notice that it assists and does not advise), its own `openapi.yml`, a committed `uv.lock`, pytest tests, an evaluation harness with one example case, a CI workflow that runs lint, typecheck, tests and the fake-provider evaluation, and a Cursor rule, under the app's path |
| `other` | Registered only |

The backend and Android packs are verified locally, and a generated Android app builds its debug APK and passes its JVM tests locally and in CI; its sign-in against a running backend through `adb reverse` was checked by hand on an emulator. The iOS pack is verified only by the macOS CI job (XcodeGen, a simulator build and the tests), which passes against it; its sign-in works in the simulator only, because the backend serves the dev identity to loopback requests. A generated web app passes `npm ci`, lint, typecheck, its tests and the Next.js build locally and in CI, with a mocked backend; its sign-in against a running backend is checked by hand, and no hosting configuration is generated. A generated agent service passes `uv sync --locked`, ruff, mypy, its pytest tests and its fake-provider evaluation locally and in CI, and a real local run against a backend under its `local` profile answered `POST /api/assist` with the tool's `GET /api/me` result; its Claude adapter is tested against a stub only, so run the evaluation live with your own key before relying on it. [current-status.md](current-status.md) records the verification per platform.

## Current Notes Per Input

- `Package identifier`: every scaffolded app gets its own package under it, so two apps of one stack never share a package.
- Sign-in: the sign-in of a `spring-backend`, a `nextjs-web`, an `android-compose` or an `ios-swiftui` app is the local development identity, which Prism's auth contract defines, so no question asks for an authentication method. A `python-agent-service` accepts the backend's tokens and verifies them against the key the dev identity publishes (`GET /api/dev-identity/jwks`), or against a configured issuer. The real identity provider is yours to choose, and the generated `security-auth` skill explains the replacement.

## What The Questionnaire Does Not Ask

Prism owns project identity, the app list, the auth contract and the agent integrations. It does not ask for a database, a cloud provider, a web host or optional supporting services. The template makes one assumption for local development and leaves everything else to the user and their agent:

- A workspace with a backend app always comes with a `docker-compose.yml` that runs PostgreSQL as the development database and one service for each backend app, because a backend's integration tests and local sign-in need a database. It is a local development service, not a production definition. There is no cache or other supporting service.
- Cloud deployment is a skill. Every generated workspace carries a `deployment` skill in `.claude/skills/deployment/` and `.agents/skills/deployment/` with worked examples for the backend container on Azure Container Apps and the web apps on Cloudflare Workers through OpenNext, and notes on mobile store releases. The user and their agent own the cloud choice, the secrets and the deployment; the files are an example for one choice and are not copied into the project.
- Generated GitHub Actions build and test only.

An answers file or `--data` value for a question that no longer exists (`database`, `supporting_services`, `use_docker`, `cloud_provider`, `web_hosting`, `platforms`, `auth_methods`, `github_org`, `ios_module_name`, `package_path`) is rejected by `prism new` with an "Unknown answer(s)" error. Copier itself ignores such a value.

## Raw Copier

`copier.yml` has one hidden question, `prism_layer`, which chooses what Copier renders: `workspace` (the default) renders `template/`, and a stack with a pack renders `packs/<stack>/` for one app, with every path under `{{ app_path }}/`. The CLI always sets it. Running raw Copier renders one layer only, so use `prism new` to generate a workspace. The pinned versions every pack reads are in `packs/versions.yml`.

## Recommended First Selections

- **Backend only** for contract inspection and repository-shape validation
- **Backend + Mobile** for the Android and iOS client path; the iOS pack is built and tested by the macOS CI job
- **Backend + Web** to evaluate the web slice against the backend; add a second web app for another audience with `prism app add admin --stack nextjs-web --audience internal --scaffold`
- **Full** for one app of each of the four client and backend stacks
- **Backend + agent service** to evaluate the agent slice: list `agent-service` with the `python-agent-service` stack in an answers file next to `backend`
