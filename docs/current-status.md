# Current Status

## Template Maturity

| Area | Status | Notes |
|------|--------|-------|
| Template generation | Validated | `./scripts/validate-template.ps1` now checks backend-only, backend + web/admin, backend + Android, and backend + iOS generation. |
| Backend scaffold | Partial | Generated backend repos now include the Gradle wrapper and coherent task/Docker wiring, but this pass did not re-run a full Gradle build. |
| User Web App scaffold | Partial | Generated user web repos now pass `npm install`, `npm run lint`, `npm run typecheck`, `npm run build`, `npm run build:cloudflare`, and `wrangler deploy --dry-run`, but live Cloudflare deployment still needs real-account validation. |
| Admin Web Portal scaffold | Partial | Generated admin web repos now pass `npm install`, `npm run lint`, `npm run typecheck`, `npm run build`, `npm run build:cloudflare`, and `wrangler deploy --dry-run`, but live Cloudflare deployment still needs real-account validation. |
| Android scaffold | Partial | This remains one of the stronger application paths in the template and is included in the validation matrix. |
| iOS scaffold | Partial | Common-name generation now validates correctly, but Mac/Xcode build verification still needs to happen locally. |
| Apple Sign-In | Experimental | Selectable, but not yet production-hardened. |
| Template validation automation | Present | `scripts/validate-template.ps1` and `.github/workflows/template-validation.yml` now include generated web build and Wrangler dry-run smoke tests in addition to the existing generation checks. |
| Database choice | Current input | PostgreSQL is the only available choice today. |
| Supporting services | Current input | Redis is optional and now modeled separately from the primary database choice. |
| Backend deployment choice | Current input | Azure is the only available choice today. |
| Web deployment choice | Current input | Cloudflare via OpenNext is the only available choice today. |

If you need a fully validated all-platform starter today, this repository is not there yet.

## What This Repo Is For

- Teams evaluating the template direction before adopting it
- Maintainers improving the scaffold itself
- Contributors generating sample repos for specific platform combinations

If your goal is to inspect, improve, and validate the scaffold, this repo is ready for that workflow.

## Recommended Evaluation Paths

- `platforms=[backend]` for contract inspection and repository-shape validation
- `platforms=[backend, mobile-android]` for the strongest current application path
- `platforms=[backend, web-user-app]` or `platforms=[backend, web-admin-portal]` for focused web-slice evaluation
- `platforms=[backend, web-user-app, web-admin-portal]` to validate the initial web/admin setup together
- `platforms=[backend, mobile-ios]` for structural validation of the iOS slice, followed by local Mac/Xcode verification

## Practical Validation Snapshot

The following checks were confirmed during the recent repository review and follow-up generation passes:

- `copier copy` works when required inputs such as `project_name` are provided
- `./scripts/validate-template.ps1` now reproduces the maintainer validation pass in one command, including generated web install/build/OpenNext/Wrangler smoke tests when Node is available
- generated backend output now includes wrapper files and consistent Taskfile/Docker references
- a generated sample with `platforms=[backend, web-user-app, web-admin-portal]` produces coherent top-level directories for those slices, shared assets, docs, task wiring, and matching workflow files
- `web-user-app/` and `web-admin-portal/` now generate initial Next.js application structure, auth route handlers, Workers/OpenNext config, docs, and platform Taskfiles
- generated web samples now complete `npm run build:cloudflare` and `wrangler deploy --dry-run` successfully
- a generated `platforms=[backend, mobile-ios]` sample with `project_name=Review App` now produces iOS-safe target, scheme, and Swift module names

This is why the safest workflow is still explicit generation plus structural validation, not assumption-based adoption.

## Short Version

- Use this repository to generate and validate targeted sample repos.
- Use `./scripts/validate-template.ps1` after template edits instead of relying on manual spot checks.
- Treat backend + Android as the most practical evaluation path today.
- Treat user web app and admin web portal as real, build-validated, but still-hardening initial slices until live Cloudflare deployment is revalidated.
- Treat Apple Sign-In as experimental until it is scaffolded and validated end to end.
