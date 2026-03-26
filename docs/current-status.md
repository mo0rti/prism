# Current Status

## Template Maturity

| Area | Status | Notes |
|------|--------|-------|
| Template generation | Usable | `copier copy` works with the current questionnaire when required inputs are supplied. |
| Backend scaffold | Partial | Core backend files generate, but build-wrapper and lint/tooling hardening is still in progress. |
| User Web App scaffold | Partial | An initial Next.js slice now generates with routing, auth wiring, docs, and workflow/task setup, but it still needs broader validation across auth and deployment combinations. |
| Admin Web Portal scaffold | Partial | An initial Next.js admin slice now generates with dashboard/auth structure, docs, and workflow/task setup, but it is still early and needs more hardening. |
| Android scaffold | Partial | This remains one of the stronger application paths in the template. |
| iOS scaffold | Partial | Present, but naming and task-generation details still need validation. |
| Apple Sign-In | Experimental | Selectable, but not yet production-hardened. |
| Database choice | Current input | PostgreSQL is the only available choice today. |
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
- `platforms=[backend, mobile-ios]` only if you are prepared to validate iOS generation details locally

## Practical Validation Snapshot

The following checks were confirmed during the recent repository review and follow-up generation passes:

- `copier copy` works when required inputs such as `project_name` are provided
- a generated sample with `platforms=[backend, web-user-app, web-admin-portal]` produces coherent top-level directories for those slices, shared assets, docs, task wiring, and matching workflow files
- `web-user-app/` and `web-admin-portal/` now generate initial Next.js application structure, auth route handlers, docs, and platform Taskfiles
- generated backend output still needs build-wrapper and lint/tooling hardening

This is why the safest workflow is still explicit generation plus structural validation, not assumption-based adoption.

## Short Version

- Use this repository to generate and validate targeted sample repos.
- Treat backend + Android as the most practical evaluation path today.
- Treat user web app and admin web portal as real but still-hardening initial slices.
- Treat Apple Sign-In as experimental until it is scaffolded and validated end to end.
