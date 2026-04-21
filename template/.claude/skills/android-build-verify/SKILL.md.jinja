---
name: android-build-verify
description: Build and verification workflow for this Android app. Use when asked to compile, assemble, test, debug build failures, or choose the cheapest sufficient validation task for a change.
argument-hint: [scope-or-task]
disable-model-invocation: true
allowed-tools: Read, Grep, Glob, Bash(./gradlew *), Bash(gradlew.bat *)
---

# Android Build Verify

Use the smallest Gradle task that gives trustworthy feedback for the change.

## Request

$ARGUMENTS

## Default task selection

- `./gradlew compileDebugKotlin` (or `gradlew.bat` on Windows)
  - Use for most Kotlin, Compose, ViewModel, DI, and navigation edits.
- `./gradlew testDebugUnitTest`
  - Prefer when ViewModel, repository, session, mapper, or helper logic changes.
- `./gradlew compileDebugAndroidTestKotlin`
  - Add when screen APIs, Compose test fixtures, semantics-sensitive UI, or instrumentation-only dependencies change.
- `./gradlew lintDebug`
  - Add when resources, manifests, accessibility-sensitive UI, or platform configuration change.
- `./gradlew assembleDebug`
  - Add when resources, manifests, packaging, generated sources, or broader app integration may be affected.
- `./gradlew assembleRelease`
  - Add when release-only build logic, ProGuard or R8 rules, serialization DTOs, reflection targets, or dependency upgrades may affect shrinking or packaging.
- `./gradlew bundleRelease`
  - Add when validating the Play-distribution artifact path or matching the Fastlane and CI release flow matters.
- `./gradlew connectedDebugAndroidTest`
  - Use when a device or emulator is available and instrumentation coverage is relevant.
  - Prefer an API 36 phone emulator as the baseline local UI verification target.
  - Add an API 29 phone emulator spot-check when the change touches auth, insets, storage, or device behavior.

## Troubleshooting

- If Hilt or generated-code failures look stale after refactors, stop the Gradle daemon (`./gradlew --stop`), delete `app/build` and `.gradle` folders, and rebuild with `--no-build-cache --rerun-tasks`.
- If a release-only failure appears after compile or debug tasks pass, escalate to `assembleRelease` before editing keep rules blindly.
- If the change is UI-only but touches shared Compose code, prefer `compileDebugKotlin` first and then escalate to `assembleDebug` only if needed.

## Report clearly

- State exactly which tasks ran.
- State whether they passed or failed.
- If you skip a stronger verification step, say why.
