# Repository Review

Date: 2026-03-26

## Purpose

This document refreshes the earlier repository review against the current state of the template repo.

It now reflects both:

- the initial re-review of the repository as it existed at the start of this pass
- the remediation work completed during this pass

## Review Method

This pass included:

- reading the current root docs and maintainer guidance
- reviewing `copier.yml` and the current template layout under `template/`
- checking the specific files implicated by the earlier review
- generating fresh sample projects with:
  - `platforms=[backend]` and explicit `auth_methods=[google, apple, password]`
  - `platforms=[backend, web-user-app, web-admin-portal]`
  - `platforms=[backend, mobile-android]`
  - `platforms=[backend, mobile-ios]` with `project_name=Review App`
- running `./scripts/validate-template.ps1`

This pass focused on template correctness and structural coherence. It did not run full package installation or full platform builds for every slice.

## Executive Verdict

The repository is in a meaningfully stronger state than it was at the start of this review.

The major structural issues identified in the older reports have now been addressed:

- backend generation now ships the Gradle wrapper and coherent Taskfile/Docker wiring
- iOS generation now uses `ios_module_name` for Swift/Xcode-safe identifiers
- Azure/env/OpenAPI wiring is aligned with the current backend token model
- reduced-platform docs and generated AI context are more scope-aware
- automated template validation now exists and runs in CI

The main material gap that still remains is Apple Sign-In runtime hardening:

- Apple remains selectable, but experimental
- it is no longer part of the default auth selection
- the backend Apple client-secret path is still not production-ready

Broader end-to-end build validation for web/admin and local Mac/Xcode validation for iOS are still recommended.

## Status Of Earlier Observations

| Earlier observation | Current status | Current assessment |
|---------------------|----------------|--------------------|
| Web platform options existed without real slices | Resolved | `web-user-app/` and `web-admin-portal/` now generate real initial slices with routes, auth handlers, docs, taskfiles, and workflows. |
| iOS generation broke on common project names | Resolved | `ios_module_name` is now wired through the iOS slice for targets, schemes, Swift identifiers, Fastlane, and test imports. |
| `postgres` vs `postgresql` mismatch broke backend dependencies | Resolved | Backend build/config still consistently generate PostgreSQL support. |
| Backend wrapper/tooling path was broken | Resolved | Backend output now includes wrapper assets, static verification uses `check -x test`, and the tasking path is coherent. |
| Apple auth was incomplete and overly advertised | Partially valid | Apple is now safer from a template-contract perspective, but the runtime implementation is still experimental. |
| Root env example drifted from runtime config | Resolved for the current contract | Root env, Azure secrets, and deploy scripts now align with access/refresh expiry naming and current provider vars. |
| Reduced-platform generation leaked irrelevant content | Largely resolved | Filesystem leakage had already improved, and shared docs/agent context are now substantially cleaner for reduced-platform output. |
| Template validation was too manual | Resolved | `scripts/validate-template.ps1` and `.github/workflows/template-validation.yml` now cover the main generation matrix. |

## What Improved During This Pass

### 1. Backend output is now self-contained through its documented path

The template now ships:

- `template/backend/gradlew`
- `template/backend/gradlew.bat`
- `template/backend/gradle/wrapper/gradle-wrapper.jar`

The backend Taskfile was also corrected so it:

- renders through Copier correctly
- uses cross-platform wrapper references
- stops advertising `ktlintCheck` without a matching Gradle setup

### 2. iOS generation now handles common project names correctly

The iOS slice now uses:

- `project_slug` for filesystem-safe paths
- `ios_module_name` for Xcode targets, schemes, Swift identifiers, test imports, and related generated references

Generating `project_name=Review App` now yields:

- filesystem paths such as `mobile-ios/review-app/`
- module and scheme names such as `ReviewApp`

### 3. Config, deployment, and auth-contract drift improved materially

This pass aligned:

- root `.env.example`
- Azure secret examples and deploy scripts
- OpenAPI OAuth callback generation
- provider naming in generated docs and configuration files

Apple-specific env vars now generate when Apple is intentionally selected, and stale `JWT_EXPIRATION_MS` wiring was removed from the Azure path.

### 4. Reduced-platform guidance is more honest

Generated shared docs and AI context now avoid several earlier over-claims about absent slices.

Backend-only generation no longer presents web/admin/mobile work as if it were already part of the selected project scope.

### 5. The repo now has automated generation validation

The repository now includes:

- `scripts/validate-template.ps1`
- `.github/workflows/template-validation.yml`

The validation script checks at least:

- backend-only generation
- backend + web-user-app + web-admin-portal generation
- backend + mobile-android generation
- backend + mobile-ios generation with a spaced project name

## Current Findings

### Finding 1

- Severity: High
- Area: Apple Sign-In runtime maturity
- Files:
  - `template/backend/src/main/kotlin/{{package_path}}/modules/auth/service/OAuth2UserService.kt.jinja`
  - `copier.yml`
  - `docs/questionnaire.md`
- Problem:
  - Apple Sign-In is still not implemented coherently enough to treat as production-ready scaffolding.
  - The backend Apple client-secret path still contains TODO-style logic and is not hardened.
  - The template contract is safer now because Apple is no longer part of the default auth selection, but the selectable Apple path is still experimental.
- Why it matters:
  - This is now the main remaining correctness gap between questionnaire surface area and implementation maturity.

### Finding 2

- Severity: Medium
- Area: Validation depth beyond structure
- Files:
  - `scripts/validate-template.ps1`
  - `docs/current-status.md`
  - `docs/maintainer-workflow.md`
- Problem:
  - The repository now has a solid structural generation check, but this pass still did not run full npm/Gradle/Xcode build workflows for every validated slice.
  - Web/admin and iOS especially still need broader execution-level validation to move from "good structural scaffold" toward "dependable starter."
- Why it matters:
  - Structural validation is a major improvement, but it is not the same as full runtime/build confidence.

## Overall Assessment

### What is currently credible

- the overall product direction
- the questionnaire surface and maturity framing at the repo-doc level
- the existence of concrete backend, Android, iOS, web-user-app, and web-admin-portal template slices
- backend generation through its documented wrapper-based path
- iOS generation for common project names
- reduced-platform scope hygiene in generated docs and AI context
- the repo's new regression-prevention baseline

### What still needs caution

- Apple auth as a selectable path
- broader end-to-end validation for web/admin output
- local Mac/Xcode verification for generated iOS projects

## Recommended Next Moves

1. Either harden Apple Sign-In properly in the backend runtime or gate it even more aggressively until that work is complete.
2. Run focused end-to-end verification for generated web/admin repos and record the results in `docs/current-status.md`.
3. Run local Mac/Xcode validation for the generated iOS sample and document the outcome.
4. Keep expanding the validation script whenever a new template contract becomes important enough to enforce automatically.
