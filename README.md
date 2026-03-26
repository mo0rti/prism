# Multi-Platform Project Template

A [Copier](https://copier.readthedocs.io/) template for scaffolding a multi-platform monorepo with:

- **Backend**: Spring Boot 4 (Kotlin 2.2+, Java 21)
- **User Web App**: Next.js + TypeScript
- **Admin Web Portal**: Next.js + TypeScript
- **Android**: Kotlin + Jetpack Compose (MVVM)
- **iOS**: Swift + SwiftUI (MVVM)

This repository is the template itself, not a generated project.

## Current Status

| Area | Status | Notes |
|------|--------|-------|
| Template generation | Usable | `copier copy` works with the current questionnaire. |
| Backend scaffold | Partial | Core structure is present, but backend wrapper/lint hardening is still in progress. |
| User web app scaffold | Partial | A real Next.js slice now generates, but it still needs broader validation across auth/deploy combinations. |
| Admin portal scaffold | Partial | A real Next.js admin slice now generates, but it is still early and needs more hardening. |
| Android scaffold | Partial | Still one of the stronger application paths in the template. |
| iOS scaffold | Partial | Present, but generation and naming details still need validation. |
| Apple Sign-In | Experimental | Visible and wired in places, but not yet production-hardened. |
| Database choice | Current input | PostgreSQL is the only available choice today. |
| Backend deployment choice | Current input | Azure is the only available choice today. |
| Web deployment choice | Current input | Cloudflare via OpenNext is the only available choice today. |

The template is now capable of generating `user-web-app/` and `admin-web-portal/`, but those slices should still be treated as active hardening work rather than fully proven production starters.

## Questionnaire

Copier asks for:

| Question | Current contract |
|----------|------------------|
| Project name | Required human-readable project name |
| Project slug | Derived from name, editable |
| Package identifier | Reverse-domain ID, editable |
| Description | One-line summary |
| Platforms | `backend`, `user-web-app`, `admin-web-portal`, `android`, `ios` |
| Auth methods | `google`, `apple`, `facebook`, `microsoft`, `password` |
| Database | PostgreSQL |
| Docker Compose | yes / no |
| Backend deployment | Azure |
| Web deployment | Cloudflare via OpenNext |
| GitHub org | Optional |

Notes:

- `user-web-app` is the end-user-facing web experience.
- `admin-web-portal` is the internal/admin management surface.
- `password` auth is required when `admin-web-portal` is selected.
- At least one auth method is required when `user-web-app` is selected.

## Quick Start

Generate from GitHub:

```bash
copier copy --trust https://github.com/mo0rti/Template.git ../my-new-project
```

Generate from a local checkout:

```bash
copier copy --trust . ../my-new-project
```

Generate a focused sample:

```bash
copier copy --trust --defaults \
  --data "project_name=Sample App" \
  --data "platforms=[backend, user-web-app, admin-web-portal]" \
  . ../sample-app
```

Update an existing generated project:

```bash
cd /path/to/generated-project
copier update --trust
```

## Recommended Validation

After template changes:

1. Run `copier copy` for the platform combinations you touched.
2. Confirm the selected directories exist in the generated output.
3. Inspect the generated root `Taskfile.yml` for missing includes.
4. Inspect the generated `README.md` and platform docs.
5. Run platform-specific install/build checks where practical.

Recommended sample combinations:

- `platforms=[backend]`
- `platforms=[backend, android]`
- `platforms=[backend, ios]`
- `platforms=[backend, user-web-app]`
- `platforms=[backend, admin-web-portal]`
- `platforms=[backend, user-web-app, admin-web-portal]`

## Generated Output

Today the template can generate:

- `backend/`
- `user-web-app/`
- `admin-web-portal/`
- `android/`
- `ios/`
- `shared/`
- `docs/`
- `.github/workflows/`
- `_templates/`
- generated AI context files such as `AGENTS.md` and `CLAUDE.md`

Current workflow templates include:

- `api-contracts.yml`
- `backend.yml`
- `android.yml`
- `ios.yml`
- `user-web-app.yml`
- `admin-web-portal.yml`

## Template Structure

```text
copier.yml
template/
  .claude/
  .codex/
  .cursor/
  .github/
  _templates/
  backend/
  user-web-app/
  admin-web-portal/
  android/
  ios/
  shared/
  docs/
  README.md.jinja
  Taskfile.yml.jinja
  AGENTS.md.jinja
  CLAUDE.md.jinja
README.md
AGENTS.md
CLAUDE.md
PLAN.md
```

## Maintainer Notes

- Keep roadmap-facing options honest about whether they are implemented, partial, experimental, or planned.
- Test generated output after changing `copier.yml`, task wiring, workflow templates, or platform directories.
- Prefer explicit platform names in docs and tasks: `user-web-app` and `admin-web-portal`.
- Keep generated docs aligned with the real platform maturity.

## Related Files

- `PLAN.md` for architecture direction and longer-term decisions
- `REPOSITORY_REVIEW.md` for the recent repository review
- `REMEDIATION_PLAN.md` for the stabilization plan
- `copier.yml` for the questionnaire contract
- `template/README.md.jinja` for the generated-project starting guide
