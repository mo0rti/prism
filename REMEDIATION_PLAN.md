# Remediation Plan

Date: 2026-03-26

## Purpose

This document turns the repository review into an execution plan.

It reflects the current product direction:

- keep future-facing options visible in the Copier questionnaire
- keep `web-user-app`, `web-admin-portal`, and Apple Sign-In present as platform options
- keep `database`, backend deployment, and web deployment as explicit inputs even when only one concrete choice is currently available
- remove misleading language such as "hardcoded"
- make the template honest about what is implemented today, what is partial, and what is still planned

The immediate goal is not to reduce the questionnaire surface.
The immediate goal is to make the questionnaire, generated output, docs, and runtime behavior agree with each other.

## 1. Product Model for This Remediation

This remediation treats template options in three maturity bands:

1. Implemented
   - works today and should be validated as a supported path
2. Partial or experimental
   - may be selectable, but docs and generated output must clearly describe the current limitations
3. Planned or TODO
   - may remain visible in the questionnaire and roadmap, but must not generate dangling references, false promises, or broken wiring

The key rule is:

If an option is offered to the user, the generated project must remain coherent.

That does not mean every option must be fully implemented today.
It does mean the template must represent the option honestly.

## 2. Core Objectives

1. Stop generating broken or misleading projects.
2. Preserve future-facing questionnaire inputs and roadmap options.
3. Distinguish implemented, partial, and planned features clearly.
4. Fix backend build and database correctness.
5. Fix iOS generation correctness.
6. Align configuration, docs, shared contracts, and runtime behavior.
7. Add automated verification so regressions are caught early.

## 3. Guiding Principles

1. Preserve option surfaces that are part of the intended product model.
2. Do not describe single-choice inputs as "hardcoded".
3. Roadmap options must never create missing-path references or broken default output.
4. Generated outputs are the product and must be tested as such.
5. Documentation must state current maturity, not just future intent.
6. Validation must distinguish:
   - supported build paths today
   - planned paths that are represented honestly but not fully implemented

## 4. Scope for This Remediation

### In scope

- Copier questionnaire structure and wording
- visible inputs for:
  - `platforms`
  - `auth_methods`
  - `database`
  - backend deployment/cloud provider
  - web deployment/hosting provider
- generated root task wiring
- generated docs and AI context
- backend build, config, migrations, and auth/config correctness
- iOS naming, project generation, and task generation correctness
- shared OpenAPI and env/config alignment
- repository-level smoke testing
- explicit support/maturity language for implemented, partial, and planned options

### Out of scope for now

- fully implementing `web-user-app`
- fully implementing `web-admin-portal`
- adding new concrete database providers beyond PostgreSQL
- adding new backend cloud providers beyond Azure
- adding new web hosting providers beyond Cloudflare
- fully production-hardening every partial auth flow in this same pass unless directly required for contract honesty

## 5. Priority Order

The fixes should happen in this order:

1. Questionnaire and documentation contract realignment
2. Backend correctness and buildability
3. iOS generation correctness
4. Config and auth contract cleanup
5. Planned-option output hygiene
6. Template validation harness
7. CI hardening and release gate

This order matters.

If the questionnaire contract and documentation remain unclear, deeper implementation fixes will still leave the repo confusing.

## 6. Workstreams

## Workstream A: Questionnaire and Option Model

### Goal

Preserve future-facing options while making their current maturity explicit.

### Problems being fixed

- some remediation ideas assumed roadmap options should be removed
- single-choice inputs are hidden with `when: false`
- docs describe some inputs as effectively fixed instead of user-selected
- there is no clear maturity vocabulary for implemented vs partial vs planned options

### Actions

1. Keep `web-user-app` and `web-admin-portal` visible in the `platforms` questionnaire.
2. Keep Apple Sign-In visible in `auth_methods`.
3. Make `database` a visible choice question with PostgreSQL as the currently available option.
4. Make backend deployment/cloud provider a visible choice question with Azure as the currently available option.
5. Make web deployment/hosting a visible choice question with Cloudflare as the currently available option.
6. Add repository documentation that explicitly distinguishes:
   - implemented today
   - partial or experimental
   - planned or TODO
7. Decide how default selections should behave, with one hard rule:
   - defaults must not generate a broken project

### Files to touch

- `copier.yml`
- `README.md`
- `PLAN.md`
- `AGENTS.md`
- `CLAUDE.md`
- generated root docs and context templates

### Acceptance criteria

- Copier walks users through all intended high-level decisions.
- `database`, backend deployment, and web deployment appear as explicit questions.
- No top-level doc uses "hardcoded" framing for those inputs.
- The repo has a clear maturity model for implemented, partial, and planned options.

## Workstream B: Generated Output Contract for Planned and Partial Options

### Goal

Ensure that selectable options never produce incoherent output.

### Problems being fixed

- selected roadmap options can lead to references to missing directories
- planned platforms leak into tasks, workflows, docs, and AI context as if they were complete
- partial features can read as production-ready

### Actions

1. Audit what happens when `web-user-app` or `web-admin-portal` is selected.
2. For any offered but unfinished option, choose one of these patterns:
   - generate a minimal placeholder slice that is explicit about TODO status
   - or omit operational wiring while clearly documenting that the option is planned
3. Ensure root `Taskfile.yml`, workflows, generated docs, and AI context never reference files that are absent.
4. Ensure partial features are labeled as partial or experimental wherever they appear.
5. Ensure planned options remain visible without pretending they are complete.

### Files to touch

- `template/Taskfile.yml.jinja`
- `template/README.md.jinja`
- `template/CLAUDE.md.jinja`
- `template/AGENTS.md.jinja`
- `template/.github/workflows/*`
- `template/docs/*`
- `template/_templates/*`
- `_exclude` rules if needed

### Acceptance criteria

- Selecting any offered option does not create missing-path references.
- Generated docs and AI context describe planned options honestly.
- Roadmap visibility is preserved without breaking generated repos.

## Workstream C: Backend Build and Runtime Correctness

### Goal

Make the backend-generated project self-contained and reliable.

### Problems being fixed

- missing backend Gradle wrapper files
- lint task references tooling that is not configured
- some task and Docker assumptions are not cross-platform-safe
- database naming and runtime configuration need tightening

### Actions

1. Add backend Gradle wrapper files to the template:
   - `gradlew`
   - `gradlew.bat`
   - wrapper jar if required
2. Standardize the current backend database implementation on PostgreSQL while keeping `database` as a visible questionnaire choice with one available option today.
3. Align Docker, Taskfile, and backend docs around a working wrapper path.
4. Fix lint configuration:
   - either add ktlint properly
   - or remove `ktlintCheck` from tasks and docs
5. Remove Unix-only assumptions from backend task commands that claim to be cross-platform.
6. Verify the generated backend can build through its own documented path.

### Files to touch

- `template/backend/build.gradle.kts.jinja`
- `template/backend/Taskfile.yml`
- `template/backend/Dockerfile.jinja`
- `template/backend/gradle/wrapper/*`
- `template/backend/gradlew`
- `template/backend/gradlew.bat`
- `template/backend/src/main/resources/application.yml.jinja`
- `template/backend/src/main/resources/db/migration/V1__init.sql.jinja`
- backend docs

### Acceptance criteria

- Generated backend output contains a working Gradle wrapper.
- Backend build works through the documented wrapper path.
- PostgreSQL is the current concrete database implementation across questionnaire, docs, and runtime config.
- Lint commands either work or are removed.

## Workstream D: iOS Generation Correctness

### Goal

Make the generated iOS project syntactically valid and operationally consistent.

### Problems being fixed

- `project_slug` is reused where Swift-safe naming is required
- generated iOS `Taskfile.yml` contains unresolved placeholders
- XcodeGen, Fastlane, and task naming can drift

### Actions

1. Introduce a dedicated iOS-safe/module-safe identifier.
2. Keep `project_slug` for filesystem and package naming.
3. Use the iOS-safe identifier for:
   - target name
   - scheme name
   - `@testable import`
   - Swift app type name
4. Fix nested templating in `template/mobile-ios/Taskfile.yml`.
5. Align XcodeGen, Fastlane, and task commands around the same naming rules.
6. Add a validation case using a project name with spaces or hyphens.

### Suggested naming split

- `project_slug`: filesystem-safe, kebab-case if desired
- `ios_module_name`: Swift/Xcode-safe, no hyphens, PascalCase or identifier-safe variant

### Files to touch

- `copier.yml`
- `template/mobile-ios/project.yml.jinja`
- `template/mobile-ios/Taskfile.yml`
- `template/mobile-ios/{{project_slug}}/App.swift.jinja`
- `template/mobile-ios/{{project_slug}}Tests/LoginViewModelTests.swift.jinja`
- `template/mobile-ios/{{project_slug}}Tests/ExampleListViewModelTests.swift.jinja`
- `template/mobile-ios/fastlane/Fastfile.jinja`
- iOS docs and generated AI context if needed

### Acceptance criteria

- Generated iOS code contains no invalid Swift identifiers for common project names.
- Generated iOS `Taskfile.yml` contains no unresolved template placeholders.
- XcodeGen target name, scheme name, Fastlane project name, and test imports are aligned.

## Workstream E: Config and Auth Contract Cleanup

### Goal

Align environment variables, runtime config, shared contracts, and actual auth behavior while preserving future-facing auth options.

### Problems being fixed

- `.env.example` does not match runtime config keys
- auth provider contract is broader than the selected implementation
- Apple auth remains visible but its current implementation maturity is unclear

### Actions

1. Align `.env.example` with runtime config exactly.
2. Standardize env var names across:
   - `.env.example`
   - Spring config
   - deployment scripts
   - docs
3. Make provider enums in OpenAPI conditional on selected auth methods.
4. Keep Apple Sign-In selectable, but classify it honestly based on actual implementation maturity.
5. Update docs to state whether Apple is:
   - implemented
   - experimental
   - or planned for further hardening

### Files to touch

- `template/.env.example.jinja`
- `template/backend/src/main/resources/application.yml.jinja`
- `template/shared/api-contracts/openapi.yml.jinja`
- backend auth code and docs
- generated root docs

### Acceptance criteria

- All auth and JWT env vars line up across template, runtime, and docs.
- OpenAPI only advertises auth providers selected for that generated project.
- Apple remains visible as an option, but its maturity level is explicit.

## Workstream F: Documentation and AI Context Cleanup

### Goal

Make the repository and generated docs trustworthy without erasing roadmap intent.

### Problems being fixed

- some docs still frame choices as fixed or "hardcoded"
- roadmap options are not clearly separated from implemented support
- generated AI context can over-instruct contributors toward unfinished paths

### Actions

1. Replace "hardcoded" wording with language such as:
   - currently available option
   - current deployment target
   - current database choice
2. Add a concise maturity/status matrix to top-level docs.
3. Update generated docs so selected options are described with their current maturity.
4. Update generated AI context so it:
   - understands roadmap options
   - does not assume unfinished slices already exist
5. Ensure platform-specific docs are included only when they make sense for the selected output.

### Files to touch

- `README.md`
- `AGENTS.md`
- `CLAUDE.md`
- `template/README.md.jinja`
- `template/AGENTS.md.jinja`
- `template/CLAUDE.md.jinja`
- `template/docs/*`

### Acceptance criteria

- Repository docs describe choices as user inputs, not fixed constants.
- Generated docs are honest about implemented, partial, and planned areas.
- AI context no longer overstates unfinished platform support.

## Workstream G: Template Validation and CI Hardening

### Goal

Make it hard to reintroduce questionnaire drift or broken generated output.

### Problems being fixed

- the repo does not sufficiently test generated project correctness
- roadmap options and supported build paths are not validated differently
- generation regressions can slip in silently

### Actions

1. Add a repeatable validation script for local and CI use.
2. Separate validation into two categories:
   - supported build matrix
   - roadmap/partial contract sanity
3. Supported build matrix should include at least:
   - backend-only
   - backend + Android
   - backend + iOS
   - default generation if default is intended to be supported today
4. Contract sanity checks should include:
   - unresolved placeholder scan
   - root task wiring sanity
   - no references to absent paths
   - planned options labeled honestly
5. Add a CI workflow dedicated to template validation.

### Suggested implementation

- `scripts/validate-template.ps1`
- optional `scripts/validate-template.sh`
- CI workflow for validation matrix and placeholder checks

### Acceptance criteria

- A single command validates the supported template variants.
- The validation script fails on unresolved placeholders and broken task wiring.
- CI blocks regressions in questionnaire contract and generated outputs.

## 7. Decision Points That Should Be Made Early

These decisions should not drag out:

1. What should happen when `web-user-app` or `web-admin-portal` is selected before full implementation?
   - Recommended: generate coherent placeholders or clearly omit operational wiring without dangling references
2. Should default selection include planned platforms?
   - Recommended: only if the default generated repo remains coherent and intentional
3. What is the current Apple support classification?
   - Recommended: keep selectable, but label explicitly if experimental or partial
4. Should ktlint be added or removed?
   - Recommended: decide once and align tasks, docs, and build scripts immediately

## 8. Definition of Done

This remediation should be considered complete only when all of the following are true:

1. Copier preserves the intended future-facing option surface.
2. Users are asked about database, backend deployment, and web deployment explicitly.
3. Repository and generated docs distinguish implemented, partial, and planned options clearly.
4. Backend-generated output is self-contained and buildable via its documented path.
5. iOS-generated output is syntactically valid for normal project names.
6. `.env.example`, runtime config, deployment scripts, and docs agree.
7. Selected auth providers are reflected accurately in generated OpenAPI.
8. Planned or partial options do not create dangling references in generated projects.
9. CI validates generated outputs and prevents regression.

## 9. What Not to Do During This Phase

1. Do not remove future-facing options just to make the questionnaire simpler.
2. Do not leave offered options undocumented or ambiguously labeled.
3. Do not describe current single-choice inputs as immutable implementation facts.
4. Do not rely on manual `copier copy` runs alone as proof of template health.

## 10. First Concrete Task List

If work starts immediately, this is the first practical batch:

1. Update `copier.yml` so `database`, backend deployment, and web deployment are visible questionnaire inputs.
2. Remove "hardcoded" wording from root docs and generated docs.
3. Add explicit maturity language for:
   - `web-user-app`
   - `web-admin-portal`
   - Apple Sign-In
4. Fix backend Gradle wrapper and backend task/build hygiene.
5. Fix iOS identifier generation and `template/mobile-ios/Taskfile.yml`.
6. Align `.env.example`, backend runtime config, and deployment scripts.
7. Make generated OpenAPI provider enums reflect selected auth methods.
8. Audit generated root tasks, workflows, docs, and AI context for missing-path references.
9. Add template validation scripts.
10. Wire validation into CI.
