# Questionnaire

Copier will walk you through these inputs:

| Question | Description | Default |
|----------|-------------|---------|
| **Project name** | Human-readable name (e.g., `My Awesome App`) | *(required)* |
| **Project slug** | Lowercase slug for directories (e.g., `my-awesome-app`) | derived from name |
| **Package identifier** | Reverse-domain ID (e.g., `com.example.myawesomeapp`) | derived from slug |
| **Description** | One-line project description | `A multi-platform application` |
| **Platforms** | Which platform slices to include (multi-select) | backend, web-user-app, web-admin-portal, mobile-android, mobile-ios |
| **Auth methods** | Google, Apple, Facebook, Microsoft, Password (multi-select) | Google, Password |
| **Database** | Which database to target | PostgreSQL |
| **Supporting services** | Optional backend-side supporting services | *(none selected)* |
| **Docker Compose** | Include local dev services? | yes |
| **Backend deployment** | Where backend services should be deployed | Azure |
| **Web deployment** | Where web applications should be deployed | Cloudflare via OpenNext |
| **GitHub org** | GitHub organization or username | *(empty)* |

## Current Notes Per Input

- `Platforms`: backend, Android, and iOS remain the more proven paths; `web-user-app` and `web-admin-portal` now generate initial setup and pass install/build/OpenNext/Wrangler dry-run checks, but they still need live Cloudflare deployment validation.
- `Auth methods`: Google and password are the safer defaults. Apple remains selectable but still needs more hardening.
- `Admin Web Portal`: currently requires `password` auth when selected.
- `User Web App`: currently requires at least one auth method when selected.
- `Database`, `Backend deployment`, and `Web deployment`: implemented as questionnaire inputs, with one available option each for now.
- `Supporting services`: Redis is optional and is modeled separately from the primary database choice.

## Recommended First Selections

- **Backend only** for contract inspection and repository-shape validation
- **Backend + Mobile** for the validated Android + iOS application path
- **Backend + Web** to evaluate the combined user-web and admin-portal setup
