# Repository Review

Date: 2026-03-25

## Purpose

This document captures a critical review of the repository in its current state. It is intended to be a working source for follow-up improvements, cleanup, verification, and contract correction.

This review was based on:

- reading the top-level repository documentation and configuration
- inspecting the repository structure and representative source files
- comparing documentation claims against actual template implementation
- generating sample projects with `copier copy` to validate what the template actually produces
- running lightweight verification where practical in the current environment

This is a template repository review, so the bar is higher than for a normal application repo: the template must be correct, coherent, and trustworthy before teams build on it.

## Scope Clarification

As of 2026-03-26, the intended product direction is:

- keep future-facing options visible in the Copier questionnaire
- keep `web-user-app` and `web-admin-portal` present as platform options
- keep Apple Sign-In present as an auth option
- keep `database`, backend deployment/cloud provider, and web deployment/hosting as explicit user inputs even if only one concrete option is currently available
- avoid language such as "hardcoded" when the real state is "currently available choice"

That changes the interpretation of several findings.

The problem is not that roadmap options exist.
The problem is that the repository does not yet model them clearly enough as:

- implemented
- partial or experimental
- planned or TODO

So for this document, the main focus is:

- whether selectable options generate coherent output
- whether docs and AI context describe option maturity honestly
- whether supported build paths actually work
- whether planned paths avoid broken references and false promises

## 1. Executive Verdict

The repository direction is reasonable, but the template contract is not trustworthy enough yet.

The biggest risks are:

- roadmap options are visible but not consistently represented as planned or partial
- some generated defaults are broken or misleading
- configuration drifts between docs, template inputs, generated outputs, and runtime code
- generated projects are not validated rigorously enough

There are credible implementation slices, especially on Android and parts of the backend, but the repo still behaves more like an ambitious architecture package than a reliable scaffolding system.

## 2. Review Method

### Files and areas reviewed

- top-level docs: `README.md`, `PLAN.md`, `AGENTS.md`, `CLAUDE.md`
- template configuration: `copier.yml`
- root generated-project orchestration: `template/Taskfile.yml.jinja`, `template/.env.example.jinja`, `template/README.md.jinja`
- backend template: Gradle config, Taskfile, Dockerfile, config, auth, example module, exceptions, tests
- Android template: Gradle config, DI, network, auth/session, viewmodels, tests
- iOS template: XcodeGen project, Taskfile, app bootstrap, networking, repositories, viewmodels, tests
- shared contract/template docs: OpenAPI, design docs, deployment docs
- GitHub Actions workflows
- in-project Hygen generators

### Generated sample projects used during review

Two sample generated projects were created locally to validate actual template output:

- full/default generation
- backend-only generation

These were used to confirm whether the template promises match what `copier copy` actually produces.

### What was validated

- file generation and resulting repository shape
- root task wiring
- generated backend build inputs
- generated iOS naming/output correctness
- Android unit test viability
- documentation drift in reduced-platform outputs

## 3. Critical Findings

### Finding 1

- Severity: Critical
- Area: Product Contract / Developer Experience / Template Integrity
- Location:
  - `README.md`
  - `copier.yml`
  - `template/Taskfile.yml.jinja`
  - `template/.github/workflows/web-user-app.yml.jinja`
  - `template/.github/workflows/web-admin-portal.yml.jinja`
- Problem:
  - Keeping `web-user-app` and `web-admin-portal` visible as platform options is acceptable.
  - What is not acceptable is offering them without a coherent output model.
  - The questionnaire can expose those options, but selected output must not reference missing directories or act as if the implementation already exists.
  - Today the repo still mixes roadmap visibility with active wiring.
- Evidence:
  - `README.md` presented the user web app and admin web portal as real deliverables without clearly describing their maturity.
  - `copier.yml` includes `web-user-app` and `web-admin-portal` in `platforms` choices and defaults.
  - `template/Taskfile.yml.jinja` includes `web-user-app` and `web-admin-portal` taskfiles.
  - `template/.github/workflows/web-user-app.yml.jinja` and `web-admin-portal.yml.jinja` assume real projects exist.
  - Earlier review runs found root task wiring for the web-facing slices before the concrete template directories existed.
- Why it matters:
  - The problem is not "unfinished work exists".
  - The problem is "unfinished work is selectable without a coherent generated result".
  - That makes the template feel larger than it really is and breaks trust immediately.
- Recommended fix:
  - Keep `web-user-app` and `web-admin-portal` visible in the questionnaire if they are part of the product roadmap.
  - But ensure the generated output does one of the following consistently:
    - creates explicit placeholder slices
    - or omits operational wiring while labeling those platforms as planned
  - Update docs, workflows, tasks, and AI context to reflect actual maturity.

### Finding 2

- Severity: Critical
- Area: iOS / Build Correctness / DX
- Location:
  - `copier.yml`
  - `template/mobile-ios/project.yml.jinja`
  - `template/mobile-ios/{{project_slug}}/App.swift.jinja`
  - `template/mobile-ios/{{project_slug}}Tests/LoginViewModelTests.swift.jinja`
  - `template/mobile-ios/Taskfile.yml`
- Problem:
  - The default slug format uses hyphens.
  - The iOS template uses `project_slug` directly for Swift module names, target names, test imports, and type names.
  - That produces invalid Swift for common project names.
  - The generated iOS Taskfile also still contains unresolved inner template placeholders after generation.
- Evidence:
  - `copier.yml` default slug format derives kebab-case names.
  - `template/mobile-ios/project.yml.jinja` uses `{{ project_slug }}` as the target and scheme.
  - `template/mobile-ios/{{project_slug}}/App.swift.jinja` defines `struct {{ project_slug | capitalize }}App`.
  - `template/mobile-ios/{{project_slug}}Tests/LoginViewModelTests.swift.jinja` uses `@testable import {{ project_slug }}`.
  - In a generated sample with project name `Review App`, the output included:
    - `struct Review-appApp: App`
    - `@testable import review-app`
  - The generated `mobile-ios/Taskfile.yml` still contained:
    - `{{project_name}}`
    - `{{project_slug}}`
- Why it matters:
  - The default iOS output is broken before any product work starts.
  - This is not a missing feature; this is a default generation correctness bug.
- Recommended fix:
  - Introduce a separate sanitized Swift/Xcode identifier, e.g. `ios_module_name`.
  - Never use the public slug directly as a Swift module or type identifier.
  - Fix the nested templating in `template/mobile-ios/Taskfile.yml`.
  - Add generation tests using project names with spaces and hyphens.

### Finding 3

- Severity: High
- Area: Backend / Configuration / Reliability
- Location:
  - `copier.yml`
  - `template/backend/build.gradle.kts.jinja`
  - `template/backend/src/main/resources/application.yml.jinja`
  - `template/backend/src/main/resources/db/migration/V1__init.sql.jinja`
- Problem:
  - The database option naming is inconsistent:
    - `copier.yml` uses `postgres`
    - backend Gradle and backend `application.yml` branch on `postgresql`
  - That means the default Postgres project does not include the Postgres JDBC driver or Flyway Postgres module.
  - The migration file is also PostgreSQL-shaped, so the template contract is effectively single-database today even if not modeled cleanly.
- Evidence:
  - `copier.yml` defines `postgres`.
  - `template/backend/build.gradle.kts.jinja` checks for `database == "postgresql"`.
  - `template/backend/src/main/resources/application.yml.jinja` also checks for `postgresql`.
  - The generated backend-only sample omitted the JDBC driver while still generating a Postgres JDBC URL.
  - `V1__init.sql.jinja` uses `UUID` column types directly.
- Why it matters:
  - A visible database question is fine even with one current option.
  - The current problem is that the one available option is not wired consistently.
- Recommended fix:
  - Normalize the PostgreSQL value across all template files.
  - Keep `database` as a visible question with PostgreSQL as the current available choice.
  - Add smoke tests for the PostgreSQL-supported path.

### Finding 4

- Severity: High
- Area: Build Tooling / Cross-Platform DX
- Location:
  - `template/backend/Taskfile.yml`
  - `template/backend/Dockerfile.jinja`
  - `template/backend/build.gradle.kts.jinja`
- Problem:
  - The backend template assumes `gradlew` and `gradlew.bat` exist.
  - The Dockerfile copies them.
  - The task runner calls them.
  - But the backend template does not include either wrapper file.
  - The backend lint task calls `ktlintCheck`, but no ktlint plugin is configured.
  - The backend Docker build task uses Unix shell tools despite the repo's cross-platform positioning.
- Evidence:
  - `template/backend/Dockerfile.jinja` copies `gradlew gradlew.bat`.
  - `template/backend/Taskfile.yml` resolves `GRADLEW` to those wrapper files.
  - Generated backend output did not contain `gradlew` or `gradlew.bat`.
  - `template/backend/Taskfile.yml` calls `ktlintCheck`.
  - `template/backend/build.gradle.kts.jinja` does not apply ktlint.
- Why it matters:
  - The documented backend workflow is false today.
  - Docker builds and task commands can fail immediately.
- Recommended fix:
  - Commit backend Gradle wrapper files into the template.
  - Either configure ktlint or stop advertising it.
  - Remove Unix-only assumptions from cross-platform tasks.

### Finding 5

- Severity: High
- Area: Security / Auth Integrity / Contract Honesty
- Location:
  - `template/backend/src/main/kotlin/{{package_path}}/modules/auth/service/OAuth2UserService.kt.jinja`
  - `template/shared/api-contracts/openapi.yml.jinja`
- Problem:
  - Apple auth is currently incomplete and unsafe, but the maturity level is not explicit enough.
  - The shared API contract also advertises OAuth providers too broadly when generated auth selections are narrower.
- Evidence:
  - `OAuth2UserService.kt.jinja` includes:
    - TODO for Apple client secret generation
    - warning comment that production should verify signature
    - `return ""` from `generateAppleClientSecret()`
  - `openapi.yml.jinja` defines:
    - `enum: [google, apple, facebook, microsoft]`
    - regardless of which providers were selected
- Why it matters:
  - Keeping Apple visible in the questionnaire is acceptable.
  - Presenting an incomplete implementation as if it were reusable production scaffolding is not.
- Recommended fix:
  - Keep Apple as a selectable option if that matches the roadmap.
  - Mark it explicitly as experimental or partial until properly hardened.
  - Make the provider enum conditional on selected auth methods.
  - Use proper provider verification libraries or a hardened implementation before calling it production-ready.

### Finding 6

- Severity: Medium
- Area: Configuration Drift / Onboarding
- Location:
  - `template/.env.example.jinja`
  - `template/backend/src/main/resources/application.yml.jinja`
- Problem:
  - The env example does not match the keys actually used by the runtime.
- Evidence:
  - `.env.example.jinja` defines `JWT_EXPIRATION_MS`
  - backend config uses `JWT_ACCESS_TOKEN_EXPIRY` and `JWT_REFRESH_TOKEN_EXPIRY`
  - `.env.example.jinja` defines `APPLE_PRIVATE_KEY_PATH`
  - backend config expects `APPLE_PRIVATE_KEY`
  - `.env.example.jinja` uses `FACEBOOK_APP_ID` / `FACEBOOK_APP_SECRET`
  - backend config expects `FACEBOOK_CLIENT_ID` / `FACEBOOK_CLIENT_SECRET`
- Why it matters:
  - This creates immediate onboarding confusion.
  - Teams will waste time debugging the template instead of building product code.
- Recommended fix:
  - Generate `.env.example` directly from the keys the runtime actually consumes.
  - Treat env examples as executable contract documentation, not informal notes.

### Finding 7

- Severity: Medium
- Area: Modularity / Scope Isolation / Documentation
- Location:
  - `copier.yml`
  - generated backend-only output
  - `template/docs/web-guide.md.jinja`
  - `template/docs/deployment/cloudflare-setup.md.jinja`
  - `_templates/page/new/prompt.js`
  - generated `AGENTS.md`
- Problem:
  - Platform selection does not isolate platform-specific content cleanly enough.
  - Backend-only output still includes web/docs/generator noise.
  - Roadmap visibility and reduced-platform hygiene are not being treated separately.
- Evidence:
  - Backend-only generated project still contained:
    - `docs/web-guide.md`
    - `docs/deployment/cloudflare-setup.md`
    - `_templates/page/new/prompt.js`
    - `AGENTS.md` instructions telling contributors to implement backend -> web-user-app -> web-admin-portal -> Android -> iOS
- Why it matters:
  - Generated repos become noisy and misleading.
  - The repo does not yet distinguish:
    - selected output content
    - roadmap documentation
- Recommended fix:
  - Keep roadmap options visible at the repository contract level.
  - But ensure reduced-platform generated repos only contain the assets relevant to their selected scope.
  - Audit docs, generators, workflows, and AI context for the same issue.

### Finding 8

- Severity: Medium
- Area: Testing / Verification Strategy
- Location:
  - template repo overall
  - backend tests
  - Android tests
  - generated project verification story
- Problem:
  - The repo tests some application-level logic but does not sufficiently test generated project correctness.
  - It also does not distinguish supported build paths from roadmap/contract sanity checks.
- Evidence:
  - There is no visible matrix verification that:
    - generates common project variants
    - builds supported variants
    - validates planned variants for coherent output
  - During review:
    - generated Android unit tests passed
    - generated backend wrapper path was broken
    - generated iOS output was invalid by default
- Why it matters:
  - This repository's highest-risk surface is template generation, not just application logic.
- Recommended fix:
  - Add repository-level smoke tests that run `copier copy` across key combinations.
  - Validate supported build paths separately from roadmap-output sanity.
  - Fail CI on generated-output drift and broken defaults.

## 4. Architecture Assessment

### What is coherent

- The high-level direction makes sense:
  - monorepo
  - API-first with OpenAPI
  - shared docs and design tokens
  - consistent mobile MVVM intent
  - AI-agent context layered into generated projects
  - questionnaire designed for future expansion

### What is not coherent

- The questionnaire surface and implementation maturity are not aligned.
- Roadmap options are visible, but their generated behavior is not modeled clearly enough.
- Platform boundaries are leaky across:
  - docs
  - workflows
  - task wiring
  - generators
  - AI context
- Configuration values are not consistently propagated from questionnaire to runtime/build outputs.

### Scalability and maintainability assessment

At the architecture-document level, the design is scalable enough.

At the implementation level, it is not maintainable yet because:

- the system has too many false integration points
- reduced-platform generation does not stay reduced
- roadmap options are not represented with clear maturity
- core template choices are not validated end-to-end

This means the repo is scaling its complexity faster than its reliability.

## 5. Code Quality Assessment

### Strengths

- Backend code is generally readable and conventional.
- Android code is structured cleanly enough to follow.
- Naming inside local feature slices is mostly understandable.
- The code avoids some unnecessary abstraction in places where many templates would overdo it.

### Weaknesses

- The biggest problem is not ugly code; it is misleading code and misleading wiring.
- Several areas read like reusable production scaffolding but are actually placeholder-grade:
  - Apple auth
  - backend build/lint setup
  - iOS generation details
- Naming consistency breaks down in critical infrastructure seams:
  - `postgres` vs `postgresql`
  - JWT env vars
  - OAuth env var names
  - slug vs module name vs scheme name
- Cross-platform claims are not backed by cross-platform-safe task implementations.

## 6. Documentation vs Reality

### Documentation that overstates reality

- User-web-app/web-admin-portal/platform roadmap intent is not clearly separated from implemented support.
- Generated root docs and AI context can still imply those platforms are ready to work on immediately.
- Some docs describe choices as fixed implementation facts rather than current available options.

### Documentation that conflicts with implementation

- Windows-first backend development is described via wrapper usage, but backend wrappers are missing.
- `database` is modeled like a choice, but the implementation is effectively PostgreSQL-only today.
- iOS is presented as Mac-buildable once generated, but default generation can produce invalid Swift/module identifiers.
- Platform-specific docs are supposed to be excluded by platform, but backend-only generation still includes web/cloudflare documentation.

### Documentation quality overall

There is a lot of documentation, but much of it still behaves like roadmap material rather than trustworthy operational documentation.

That is dangerous in a template repo because generated documentation is treated as truth by future contributors.

## 7. Testing Assessment

### What is tested reasonably well

- Backend service-level flows:
  - auth registration/login/refresh basics
  - example CRUD permission basics
- Android unit-test surface:
  - sign-in viewmodel behavior
  - example list viewmodel behavior
  - basic token-auth edge cases

### What is not tested well

- generated project correctness
- common platform combinations
- backend controller/security integration
- end-to-end auth flow correctness
- real iOS build viability
- root task orchestration correctness
- workflow/path accuracy
- roadmap-option output sanity

### Biggest confidence gaps

1. Default generated project validity
2. Reduced-platform generation correctness
3. Build-tooling completeness
4. Provider/auth configuration correctness
5. Documentation truthfulness after generation

## 8. Security Assessment

### High-risk issues

- Apple auth implementation is not production-ready and should not be treated as such.
- Android token storage is plaintext DataStore with only a warning comment.

### Medium-risk issues

- Security-sensitive configuration naming drift increases the chance of misconfigured deployments.
- Auth contract and enabled providers are not aligned.

### Additional note

The issue here is less "obvious exploitable bug in a shipped app" and more "unsafe scaffolding that future teams may trust too much."

That is still serious.

## 9. Performance and Scalability Risks

### Performance risks

- The main repo-level performance risk is not runtime speed; it is maintenance drag.
- Template complexity is already outpacing implemented and verified support.

### Scalability concerns

- Every new platform or generator added to this repo multiplies failure modes.
- Without strong generated-output CI, this repo will accumulate silent breakage quickly.
- The current architecture will not scale well unless option maturity and validation are made much more explicit.

## 10. Hidden Fragility

These are the parts most likely to break or mislead contributors:

- root task orchestration
- iOS naming and placeholder expansion
- backend database selection
- backend lint/build assumptions
- platform-specific docs leaking into reduced-platform projects
- AI context assuming roadmap slices are already real
- CI workflows for modules that are not generated

## 11. Top Technical Debt

Ordered by urgency:

1. Roadmap options are not modeled cleanly as implemented, partial, or planned
2. Broken iOS default generation
3. Backend database/build configuration drift
4. Demo-grade auth code presented as reusable scaffolding
5. Missing repository-level generated-project smoke tests

## 12. What Should Change First

If the repo were being improved over the next two weeks, this is the recommended order:

### 1. Clarify the template contract

Make the repository honest about selectable options and their maturity.

That means:

- keep roadmap options visible where they are part of the intended product surface
- keep `database`, backend deployment, and web deployment as explicit user choices
- remove "hardcoded" framing
- define what is implemented, partial, and planned

### 2. Fix broken supported paths

- add backend Gradle wrapper files
- fix `postgres` vs `postgresql`
- make lint real or remove it
- fix iOS identifier generation and Taskfile templating

### 3. Make planned and partial paths coherent

- if `web-user-app` or `web-admin-portal` is selectable, generated output must not point to missing directories
- if Apple is selectable, its current maturity must be explicit
- generated docs and AI context must reflect the same model

### 4. Add template smoke testing

At minimum, automatically generate and validate:

- backend-only
- backend + Android
- backend + iOS
- default generation if default output is intended to be usable today

Each generated variant should prove the paths it claims to support.

### 5. Fix conditional output hygiene

- docs
- generators
- workflows
- AI context

All of those need to respect selected platforms and selected maturity, not just source directories.

## 13. Final Brutal Summary

This repo still over-promises relative to what it verifies.

The Android slice looks the most believable. Parts of the backend are serviceable. The overall template is not trustworthy yet because:

- roadmap options are visible but not modeled cleanly
- backend defaults are misconfigured
- iOS is broken by default
- docs and generated context still blur roadmap and operational truth

The right fix is not to erase roadmap options automatically.
The right fix is to preserve them while making generated output, docs, and verification honest about what works today and what is still planned.

Until that contract is made explicit and tested automatically, this template is more likely to create cleanup work than accelerate a real project.

## 14. Appendix: Key Evidence Summary

### A. Questionnaire surface vs generated output

- `README.md` presents all five platforms as supported.
- `copier.yml` defaults to all five platforms.
- `template/Taskfile.yml.jinja` wires all five into root tasks.
- At the time of the original review, there was no concrete `template/web-user-app/` slice yet.
- At the time of the original review, there was no concrete `template/web-admin-portal/` slice yet.

This is not evidence that roadmap options must be removed.
It is evidence that selectable roadmap options currently lack a coherent output model.

### B. Backend generation correctness problems

- database value mismatch:
  - `postgres` in questionnaire
  - `postgresql` in backend build/config branches
- missing backend Gradle wrapper files
- `ktlintCheck` advertised without ktlint setup
- current database implementation is effectively PostgreSQL-only

### C. iOS generation correctness problems

- default slug reused as:
  - target name
  - scheme name
  - Swift import/module name
  - Swift app type name
- unresolved nested template placeholders remain in generated `mobile-ios/Taskfile.yml`

### D. Reduced-platform generation leakage

Backend-only generation still included:

- user web app guide
- Cloudflare deployment doc
- page generator targeting web-user-app/web-admin-portal
- AI instructions referencing implementation across all platforms

### E. Verification observations

- Android generated tests passed in local review
- backend documented wrapper path was not usable
- generated full/default project root task wiring referenced non-existent modules
- generated iOS code was invalid by default for a normal project name
