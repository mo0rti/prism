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
| **Database** | Which database to target | PostgreSQL |
| **Supporting services** | Optional backend-side supporting services | *(none selected)* |
| **Docker Compose** | Include local dev services? | yes |
| **Backend deployment** | Where backend services should be deployed | Azure |
| **Web deployment** | Where web applications should be deployed | Cloudflare via OpenNext |
| **GitHub org** | GitHub organization or username | *(empty)* |

## Current Notes Per Input

- `Platforms`: each selected platform becomes an app in `prism.workspace.yml` with the same ID, its stack and its default directory; `prism app add` registers more later ([workspace-model.md](workspace-model.md)). The backend, Android and web samples are verified locally. The iOS sample is verified only by the macOS CI job. `web-user-app` and `web-admin-portal` pass install, lint, typecheck, the auth check and the Next.js and OpenNext builds locally, the `web-smoke` CI job adds a Wrangler dry run, and live Cloudflare deployment is unverified. [current-status.md](current-status.md) records the verification per platform.
- `Auth methods`: Username + Password is the baseline sign-in method in the current Prism model. OAuth providers are additive. Google is the secondary default; Apple Sign-In is selectable but experimental.
- `Database`, `Backend deployment`, and `Web deployment`: implemented as questionnaire inputs, with one available option each.
- `Supporting services`: Redis is optional and is modeled separately from the primary database choice.

## Recommended First Selections

- **Backend only** for contract inspection and repository-shape validation
- **Backend + Mobile** for the Android and iOS client path; iOS needs macOS and Xcode validation
- **Backend + Web** to evaluate the combined user-web and admin-portal setup
