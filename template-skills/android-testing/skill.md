---
name: android-testing
description: "Android testing patterns for ViewModels, repositories, Compose UI, and Hilt-aware instrumentation. Use when adding or updating tests under `app/src/test/` or `app/src/androidTest/`, or when deciding the right Android test shape for a change."
layers: [codex, claude-skill]
platforms: [mobile-android]
codex:
  display_name: "Android Testing"
  short_description: "Choose and write the right Android tests"
  default_prompt: "Use @@invoke:android-testing@@ when adding or refining Android unit or instrumentation tests."
  implicit: false
claude-skill:
  disable-model-invocation: true
---

# Android Testing

Use this skill when Android work needs test coverage, test refactors, or test-shape decisions.

## Role boundary

- Own test authoring patterns for unit tests and instrumentation or Compose UI tests.
- Defer production architecture rules to `@@invoke:android-conventions@@`.
- Defer Gradle task selection to `@@invoke:android-build-verify@@`.
- Defer shared UI behavior rules to `@@invoke:compose-design-system@@`.

## Unit-test rules

- Prefer unit tests for ViewModel state, repository mapping, session behavior, and helper logic.
- Use `runTest` with an explicit `TestCoroutineScheduler` when coroutine ordering matters.
- Prefer `UnconfinedTestDispatcher` or `StandardTestDispatcher` injected through dispatcher qualifiers instead of real dispatchers.
- Assert `StateFlow` and one-off effects with Turbine when stream behavior matters.
- Keep unit tests under `app/src/test/` and mirror the source package structure where practical.

## Compose UI and instrumentation rules

- Use `createAndroidComposeRule<MainActivity>()` for screen-level Compose tests that need the real activity and navigation host.
- Keep instrumentation tests focused on screen state, routing, accessibility surfaces, and critical user flows rather than duplicating unit-test logic.
- Preserve stable semantics and test tags or content descriptions that important UI tests depend on.
- Keep instrumentation tests under `app/src/androidTest/`.

## Hilt-aware instrumentation

- The template supports Hilt Android testing for instrumentation tests.
- Use `@HiltAndroidTest` plus `HiltAndroidRule` when a UI test needs DI overrides or fake bindings.
- Use `@UninstallModules` only when a test genuinely needs to replace app bindings; prefer simple fake inputs when DI overrides are unnecessary.

## Picking the right test

- If the change is ViewModel, repository, mapper, or session logic: add or update a unit test first.
- If the change is Compose UI behavior, auth gating, navigation wiring, or screen semantics: add or update an instrumentation or Compose UI test when the behavior is not already covered.
- If both logic and UI are touched, prefer a unit test for the logic plus the smallest instrumentation smoke test that protects the user flow.

## Validation

- Use `@@invoke:android-build-verify@@` to choose the smallest trustworthy Gradle task after editing tests.
