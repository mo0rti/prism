---
name: android-conventions
description: Android repository rules for Kotlin, Compose, MVVM, Hilt, navigation, networking, strings, and documentation sync. Use when writing or reviewing app code, especially for architecture-sensitive changes.
user-invocable: false
---

# Android Conventions

Apply these rules whenever you change Android app code in this repository.

## Role boundary

- Use this skill for repository-wide guardrails that apply across features.
- Keep feature sequencing in `android-feature-delivery`, backend-facing contract details in `android-contract-alignment`, shared Compose guidance in `compose-design-system`, and task selection in `android-build-verify`.

## Core rules

- Keep app code inside the single `:app` module unless a module split is explicitly requested.
- The current generated scaffold is Navigation 2-oriented: keep routes in `navigation/Screen.kt` and destination wiring in `navigation/NavGraph.kt` unless a scaffold migration is explicitly requested.
- Each destination follows Route/Screen split:
  - Route handles navigation wiring, lifecycle-aware state collection, and ViewModel coordination.
  - Screen is a pure composable that receives state plus callbacks.
- Follow MVVM per screen:
  - `uiState: StateFlow<...>`
  - one-off events or effects via `SharedFlow`
  - explicit ViewModel intent methods such as `onRefresh()` or `onSaveClicked()`
- Co-locate the screen's `UiState` type with the ViewModel file so state shape and intent handling evolve together.
- Observe `StateFlow` from Route or host composables with `collectAsStateWithLifecycle()`, not plain `collectAsState()`, unless a lower-level Compose API genuinely requires otherwise.
- Use `LaunchedEffect` for one-off UI effects such as navigation, snackbar triggers, and scroll reactions. Do not encode one-time navigation as a persistent success state that will retrigger on recomposition or back navigation.
- Repositories return `AppResult<T>` for fallible work, and ViewModels map `AppResult.Error` into `UiText` before exposing error state.
- Keep repositories as concrete classes in `feature/*/data/repository/`. Do not introduce repository interfaces or a repository binding module unless explicitly requested.
- Add Retrofit APIs in `feature/*/data/remote/api/` and provide them from the existing Hilt modules under `core/di/`.
- Use `SessionManager` for auth state and logout flows; keep token reads and refresh wiring inside `TokenStorage`, `AuthInterceptor`, and `TokenAuthenticator`.
- Put user-facing strings in `app/src/main/res/values/strings.xml`.
- Move reusable Compose components, modifiers, and drawing helpers into `designsystem/` instead of duplicating them in features.
- Treat AGP, Kotlin, Compose BOM, Hilt, Room, and KSP version changes as coordinated toolchain work. Update `gradle/libs.versions.toml`, preserve KSP-first annotation processing, and re-run stronger verification when compatibility changes.

## Read these docs only when needed

- `mobile-android/docs/architecture.md` for layer rules and repository conventions
- `mobile-android/docs/build-and-environments.md` for Gradle tasks, SDK levels, and toolchain expectations
- `mobile-android/docs/file-structure.md` for package locations
- `mobile-android/docs/networking-and-di.md` for Retrofit, auth, and DI wiring
- `mobile-android/docs/navigation-and-screens.md` for route and host patterns
- `mobile-android/docs/design-system-and-theme.md` for shared Compose components
- `mobile-android/docs/testing.md` for unit test, instrumentation test, and Hilt Android testing patterns
- `mobile-android/docs/conventions-and-workflow.md` for strings, workflow, and doc-sync rules

## Minimum verification

- Run `./gradlew compileDebugKotlin` (or `gradlew.bat` on Windows) after architecture-sensitive changes.
- Add a targeted test or build task when navigation, networking, session, packaging, or resources change.
- If AGP, Kotlin, Compose BOM, or shrinker-related build configuration changes, escalate to release validation instead of stopping at debug-only tasks.
- If implementation changes docs-described behavior, update the relevant file in `mobile-android/docs/` in the same session.
