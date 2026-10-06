# Questionnaire

Copier will walk you through these inputs:

| Question | Description | Default |
|----------|-------------|---------|
| **Project name** | Human-readable name (e.g., `My Awesome App`) | *(required)* |
| **Project slug** | Lowercase slug for directories (e.g., `my-awesome-app`) | derived from name |
| **Package identifier** | Reverse-domain ID (e.g., `com.example.myawesomeapp`) | derived from slug |
| **Description** | One-line project description | `A multi-platform application` |
| **Platforms** | Which platform slices to include (multi-select) | backend, web-user-app, web-admin-portal, mobile-android, mobile-ios |
| **Auth methods** | Username + Password plus optional Google, Apple, Facebook, or Microsoft sign-in | Google, Password |
| **GitHub org** | GitHub organization or username | *(empty)* |

## Current Notes Per Input

- `Platforms`: each selected platform becomes an app in `prism.workspace.yml` with the same ID, its stack and its default directory; `prism app add` registers more later ([workspace-model.md](workspace-model.md)). The backend, Android and web samples are verified locally. The iOS sample is verified only by the macOS CI job. `web-user-app` and `web-admin-portal` pass install, lint, typecheck, the auth check and the Next.js build locally; no hosting configuration is generated. [current-status.md](current-status.md) records the verification per platform.
- `Auth methods`: Username + Password is the baseline sign-in method in the current Prism model. OAuth providers are additive. Google is the secondary default; Apple Sign-In is selectable but experimental.

## What The Questionnaire Does Not Ask

Prism owns project identity, the app list, the auth contract and the agent integrations. It does not ask for a database, a cloud provider, a web host or optional supporting services. The template makes one assumption for local development and leaves everything else to the user and their agent:

- A backend app always comes with a `docker-compose.yml` that runs the backend and its PostgreSQL development database, because the backend's integration tests and local sign-in need a database. It is a local development service, not a production definition. There is no cache or other supporting service.
- Cloud deployment is a skill. Every generated workspace carries a `deployment` skill in `.claude/skills/deployment/` and `.agents/skills/deployment/` with worked examples for the backend container on Azure Container Apps and the web apps on Cloudflare Workers through OpenNext, and notes on mobile store releases. The user and their agent own the cloud choice, the secrets and the deployment; the files are an example for one choice and are not copied into the project.
- Generated GitHub Actions build and test only.

An answers file or `--data` value for a question that no longer exists (`database`, `supporting_services`, `use_docker`, `cloud_provider`, `web_hosting`) is rejected by `prism new` with an "Unknown answer(s)" error. Copier itself ignores such a value.

## Recommended First Selections

- **Backend only** for contract inspection and repository-shape validation
- **Backend + Mobile** for the Android and iOS client path; iOS needs macOS and Xcode validation
- **Backend + Web** to evaluate the combined user-web and admin-portal setup
