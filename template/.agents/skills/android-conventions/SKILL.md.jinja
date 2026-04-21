---
name: android-conventions
description: Android repository rules for Kotlin, Compose, MVVM, Hilt, navigation, networking, strings, and documentation sync. Use when writing, refactoring, or reviewing code under `mobile-android/`, especially for architecture-sensitive changes.
---

# Android Conventions

Use this skill for repository-wide Android guardrails.

## Scope

- Apply these rules when changing code under `mobile-android/`.
- Defer multi-layer feature coordination to `$android-feature-delivery`.
- Defer backend-facing request and response shaping to `$android-contract-alignment`.
- Defer validation task selection to `$android-build-verify`.

## Core Rules

- Keep app code inside the single `:app` module unless a module split is explicitly requested.
- The current generated scaffold is Navigation 2-oriented: keep routes in `navigation/Screen.kt` and destination wiring in `navigation/NavGraph.kt` unless a scaffold migration is explicitly requested.
- Each destination follows Route/Screen split:
  - Route handles navigation wiring, lifecycle-aware state collection, and ViewModel coordination
  - Screen is a pure composable that receives state plus callbacks
- Follow MVVM per screen:
  - `uiState` uses `StateFlow`
  - one-off effects use `SharedFlow`
  - ViewModels expose explicit intent methods such as `onRefresh()` or `onSaveClicked()`
- Co-locate the screen's `UiState` type with the ViewModel file so state shape and intent handling evolve together.
- Observe `StateFlow` from Route or host composables with `collectAsStateWithLifecycle()`, not plain `collectAsState()`, unless a lower-level Compose API genuinely requires otherwise.
- Use `LaunchedEffect` for one-off UI effects such as navigation, snackbar triggers, and scroll reactions. Do not encode one-time navigation as a persistent success state that will retrigger on recomposition or back navigation.
- Repositories return `AppResult<T>` for fallible work; ViewModels map `AppResult.Error` into `UiText` before exposing error state.
- Keep repositories as concrete classes in `feature/*/data/repository/`; do not add repository interfaces or binding modules unless explicitly requested.
- Add Retrofit APIs in `feature/*/data/remote/api/` and provide them through the existing Hilt modules in `core/di/`.
- Use `SessionManager` for auth state and logout flows; keep token reads and refresh wiring inside `TokenStorage`, `AuthInterceptor`, and `TokenAuthenticator`.
- Put user-facing strings in `app/src/main/res/values/strings.xml`.
- Move reusable Compose components, modifiers, and drawing helpers into `designsystem/` instead of duplicating them in feature packages.
- Treat AGP, Kotlin, Compose BOM, Hilt, Room, and KSP version changes as coordinated toolchain work. Update `gradle/libs.versions.toml`, preserve KSP-first annotation processing, and re-run stronger verification when compatibility changes.

## Read Only What You Need

- `mobile-android/docs/architecture.md`
- `mobile-android/docs/build-and-environments.md`
- `mobile-android/docs/file-structure.md`
- `mobile-android/docs/networking-and-di.md`
- `mobile-android/docs/navigation-and-screens.md`
- `mobile-android/docs/design-system-and-theme.md`
- `mobile-android/docs/testing.md`
- `mobile-android/docs/conventions-and-workflow.md`

## Minimum Verification

- Run `./gradlew compileDebugKotlin` or `gradlew.bat compileDebugKotlin` after architecture-sensitive changes.
- Add a targeted test or stronger build step when navigation, networking, session, packaging, or resources change.
- If AGP, Kotlin, Compose BOM, or shrinker-related build configuration changes, escalate to release validation instead of stopping at debug-only tasks.
- If implementation changes docs-described behavior, update the relevant file in `mobile-android/docs/` in the same session.
