# Questionnaire

`prism new` collects these inputs. Copier does not ask about apps: the CLI collects the app list, from a preset, an answers file or the interactive flow, and gives each generation layer its answers ([workspace-model.md](workspace-model.md) describes the layers).

| Input | Description | Default |
|-------|-------------|---------|
| **Project name** | Human-readable name (e.g., `My Awesome App`) | *(required)* |
| **Project slug** | Lowercase slug for directories (e.g., `my-awesome-app`) | derived from name |
| **Package identifier** | Reverse-domain ID (e.g., `com.example.myawesomeapp`) | derived from slug |
| **Description** | One-line project description | `A multi-platform application` |
| **Apps** | The workspace's apps: each has an ID, a stack, a name, a path, an audience, a repository and whether Prism scaffolds it or only registers it | the preset's apps |
| **Auth methods** | Username + Password plus optional Google, Apple, Facebook, or Microsoft sign-in | Google, Password |
| **GitHub org** | GitHub organization or username | *(empty)* |

## Apps

An app is `{id, stack}` plus optional `name`, `path`, `audience`, `repository`, `remote` and `generation`:

- `id` is a stable slug. `stack` comes from the registry: `spring-backend`, `nextjs-web`, `android-compose`, `ios-swiftui` or `other`.
- `path` defaults to the stack's default path (`backend`, `mobile-android`, `mobile-ios`), else the ID.
- `generation` is `scaffolded` (Prism generates the code and `prism update` keeps it current) or `registered` (the manifest records it; the code lives elsewhere). An app of a generated stack in this repository defaults to `scaffolded`; an app in an external repository, or of the `other` stack, is always registered. An external app also names its repository's `remote`.

A preset is an app list: `backend-only` is `backend`; `backend-mobile` is `backend`, `mobile-android` and `mobile-ios`; `backend-web` is `backend`, `web-user-app` and `web-admin-portal`. An answers file carries the same list:

```yaml
schema_version: 1
answers:
  project_name: My Platform
  apps:
    - {id: backend, stack: spring-backend}
    - {id: partner-api, stack: spring-backend, path: services/partner-api, audience: B2B}
    - {id: customer-android, stack: android-compose, repository: mobile, remote: "https://example.com/acme/mobile.git", path: apps/customer}
```

`apps: []` generates the workspace layer alone, and `prism app add --scaffold` adds an app later. Leaving `apps` out is an error.

### What Prism derives for each scaffolded app

The CLI derives, validates and records these in the app's own answers file (`<path>/.copier-answers.yml`); a pack never reads a platform ID:

- `app_package_segment`: the ID without hyphens. It must pass the package-identifier rules (a letter first, no Kotlin or Java keyword) and be unique across every app of the workspace, so `my-app` and `myapp` collide.
- the package, directory path and module name: `<package_identifier>.<segment>`, its path, and the ID in PascalCase.
- the CI workflow name and `paths:` filters, scoped to the app's path.
- `port`: the first free port of the stack's range (`spring-backend` from 8080), chosen when the app is added and kept in its answers. Removing another app never moves it.

An app ID and path must not replace a file of the workspace layer: an ID such as `api-contracts` (a workspace workflow) or a path inside `docs/`, `knowledge/`, `shared/` or `.github/` is refused, and an app's own path must be empty or absent.

### Stacks and packs

| Stack | What `prism new` generates today |
|-------|----------------------------------|
| `spring-backend` | The `spring-backend` pack: a Spring Boot app with a health endpoint, a context test, a CI workflow and a Cursor rule, under the app's path |
| `nextjs-web`, `android-compose`, `ios-swiftui` | The full sample, rendered by the workspace layer, only for the default apps (`web-user-app` and `web-admin-portal`, `mobile-android`, `mobile-ios`) at their default paths; another app of these stacks can only be registered until the stack's pack exists |
| `other` | Registered only |

The backend, Android and web samples are verified locally. The iOS sample is verified only by the macOS CI job. `web-user-app` and `web-admin-portal` pass install, lint, typecheck, the auth check and the Next.js build locally; no hosting configuration is generated. [current-status.md](current-status.md) records the verification per platform.

## Current Notes Per Input

- `Auth methods`: Username + Password is the baseline sign-in method in the current Prism model. OAuth providers are additive. Google is the secondary default; Apple Sign-In is selectable but experimental.
- `Package identifier`: every scaffolded app gets its own package under it, so two apps of one stack never share a package.

## What The Questionnaire Does Not Ask

Prism owns project identity, the app list, the auth contract and the agent integrations. It does not ask for a database, a cloud provider, a web host or optional supporting services. The template makes one assumption for local development and leaves everything else to the user and their agent:

- A workspace with a backend app always comes with a `docker-compose.yml` that runs PostgreSQL as the development database and one service for each backend app, because a backend's integration tests and local sign-in need a database. It is a local development service, not a production definition. There is no cache or other supporting service.
- Cloud deployment is a skill. Every generated workspace carries a `deployment` skill in `.claude/skills/deployment/` and `.agents/skills/deployment/` with worked examples for the backend container on Azure Container Apps and the web apps on Cloudflare Workers through OpenNext, and notes on mobile store releases. The user and their agent own the cloud choice, the secrets and the deployment; the files are an example for one choice and are not copied into the project.
- Generated GitHub Actions build and test only.

An answers file or `--data` value for a question that no longer exists (`database`, `supporting_services`, `use_docker`, `cloud_provider`, `web_hosting`, `platforms`) is rejected by `prism new` with an "Unknown answer(s)" error. Copier itself ignores such a value.

## Raw Copier

`copier.yml` has one hidden question, `prism_layer`, which chooses what Copier renders: `workspace` (the default) renders `template/`, and a stack with a pack renders `packs/<stack>/` for one app, with every path under `{{ app_path }}/`. The CLI always sets it. Running raw Copier renders one layer only, so use `prism new` to generate a workspace. The pinned versions every pack reads are in `packs/versions.yml`.

## Recommended First Selections

- **Backend only** for contract inspection and repository-shape validation
- **Backend + Mobile** for the Android and iOS client path; iOS needs macOS and Xcode validation
- **Backend + Web** to evaluate the combined user-web and admin-portal setup
