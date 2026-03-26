# Remediation Plan

Date: 2026-03-26

## Purpose

This plan now serves as a post-remediation status and next-steps document.

It started as the execution plan for the issues confirmed in `REPOSITORY_REVIEW.md`. The major structural remediation work from that plan has now been completed in this pass.

## Current Status Snapshot

| Area | Status | Notes |
|------|--------|-------|
| Questionnaire visibility and maturity wording | Complete | Repo docs and questionnaire wording are explicit about current availability and maturity. |
| Initial web/admin scaffold existence | Complete for current scope | `web-user-app` and `web-admin-portal` generate real slices with tasks, docs, workflows, and app structure. |
| PostgreSQL contract normalization | Complete | The earlier `postgres` vs `postgresql` mismatch is not an active issue. |
| Backend self-contained build path | Complete for structural generation | Wrapper assets, task wiring, and Docker references are now aligned. |
| iOS-safe identifier model | Complete for structural generation | `ios_module_name` is wired through the iOS slice and validates with spaced project names. |
| Config and Azure deployment alignment | Complete for the current contract | JWT expiry naming and provider variable wiring were aligned across env and Azure files. |
| Reduced-platform docs and AI-context hygiene | Complete for the validated cases | Shared docs and generated AI context are more conditional and scope-aware. |
| Automated template validation | Complete | `scripts/validate-template.ps1` and CI now enforce the main generation matrix. |
| Apple auth coherence | Open | Apple remains experimental at the runtime level. |
| Focused web/admin execution validation | Open | Structural generation is validated, but broader build/typecheck/runtime verification is still pending. |
| Local iOS execution validation | Open | Structural generation is validated, but Mac/Xcode build verification is still pending. |

## Completed In This Pass

### 1. Backend buildability and wrapper completeness

Completed work:

- added backend Gradle wrapper assets to the template
- fixed backend Taskfile rendering so Copier and Go Task templates coexist correctly
- removed the stale `ktlintCheck` contract from backend tasking
- removed Unix-only image-name logic from backend tasking

### 2. iOS-safe naming and identifier wiring

Completed work:

- wired `ios_module_name` through targets, schemes, Fastlane references, Swift app naming, and test imports
- kept `project_slug` for filesystem paths only
- validated the `project_name=Review App` generation case

### 3. Auth, env, and deployment alignment

Completed work:

- added Apple env variables to generated root env output when Apple is intentionally selected
- aligned Azure secrets/deploy files with `JWT_ACCESS_TOKEN_EXPIRY` and `JWT_REFRESH_TOKEN_EXPIRY`
- aligned Facebook provider variable naming with the current backend contract
- fixed OpenAPI callback generation so Apple-only OAuth selection still emits a coherent callback path
- removed Apple from the default auth-method selection so experimental auth is no longer the default path

### 4. Reduced-platform docs and AI context cleanup

Completed work:

- made shared feature docs more conditional on selected platforms
- removed several over-broad platform claims from generated AGENTS/docs
- aligned auth-provider examples in generated entity docs with the selected auth methods

### 5. Automated validation

Completed work:

- added `scripts/validate-template.ps1`
- added `.github/workflows/template-validation.yml`
- validated:
  - `platforms=[backend]` with explicit Apple coverage
  - `platforms=[backend, web-user-app, web-admin-portal]`
  - `platforms=[backend, mobile-android]`
  - `platforms=[backend, mobile-ios]` with a spaced project name

## Remaining Workstreams

## Workstream A: Apple Auth Runtime Hardening

### Goal

Bring Apple Sign-In from "selectable but experimental" closer to a coherent implementation, or narrow its availability further.

### Actions

1. Rework `template/backend/src/main/kotlin/{{package_path}}/modules/auth/service/OAuth2UserService.kt.jinja` so Apple client-secret handling is not placeholder logic.
2. Review the generated backend auth flow end to end for Apple:
   - provider config
   - callback handling
   - token exchange assumptions
   - user creation/update flow
3. Keep Apple explicitly experimental until that runtime path is fully verified.
4. If hardening is not immediate, consider additional questionnaire or doc guardrails beyond removing Apple from the default auth selection.

### Acceptance Criteria

- Apple-selected projects no longer rely on TODO-style backend runtime logic
- generated Apple auth behavior is coherent across runtime, env, and contract
- maturity wording remains honest

## Workstream B: Web/Admin Execution Validation

### Goal

Move web/admin from structurally validated output to more execution-validated output.

### Actions

1. Generate a fresh `backend + web-user-app + web-admin-portal` sample.
2. Run the smallest practical verification for that sample:
   - dependency install
   - lint
   - typecheck
   - build
3. Record the results in `docs/current-status.md`.
4. Add any repeatable checks worth enforcing to `scripts/validate-template.ps1` or follow-on CI jobs.

### Acceptance Criteria

- web/admin maturity claims are backed by an actual recorded execution pass
- current-status docs describe validated behavior, not just intended structure

## Workstream C: Local iOS Execution Validation

### Goal

Confirm that the structurally fixed iOS output also behaves correctly in local Apple tooling.

### Actions

1. Generate a fresh `backend + mobile-ios` sample with a spaced project name.
2. Run local Mac/Xcode checks:
   - project generation if needed
   - scheme/build verification
   - test execution
3. Record the results in `docs/current-status.md`.

### Acceptance Criteria

- the generated iOS sample builds with the expected scheme/module names
- the current-status docs reflect actual local validation results

## Out Of Scope For This Phase

1. Adding new database providers beyond PostgreSQL.
2. Adding new backend cloud providers beyond Azure.
3. Adding new web hosting providers beyond Cloudflare/OpenNext.
4. Expanding the questionnaire surface further before the current surface is better execution-validated.

## Short Next-Step List

1. Harden or further gate Apple Sign-In.
2. Run execution-level validation for the generated web/admin sample.
3. Run local Mac/Xcode validation for the generated iOS sample.
4. Keep the validation script current as the template contract evolves.
