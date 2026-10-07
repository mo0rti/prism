---
name: android-build-verify
description: "Choose the cheapest trustworthy Gradle validation for Android changes. Use when asked to compile, assemble, test, debug build failures, or decide which Android verification task should run after edits in an Android app folder."
layers: [codex, claude-skill]
stacks: [android-compose]
codex:
  display_name: "Android Build Verify"
  short_description: "Pick the right Android Gradle validation step"
  default_prompt: "Use @@invoke:android-build-verify@@ to choose the right Android validation task for this change."
  implicit: false
claude-skill:
  argument-hint: "[scope-or-task]"
  disable-model-invocation: true
  allowed-tools: "Read, Grep, Glob, Bash(./gradlew *), Bash(gradlew.bat *)"
---

# Android Build Verify

Use the smallest Gradle task that gives trustworthy feedback for the Android change. Run Gradle from the app's folder ({% for app in apps if app.stack == "android-compose" %}`{{ app.path }}/`{{ ", " if not loop.last }}{% endfor %}) on JDK {{ pack_versions["android-compose"].jdk }} with an Android SDK that has platform {{ pack_versions["android-compose"].compile_sdk }}.

::: only claude-skill
## Request

$ARGUMENTS

:::
## Default Task Selection

- `./gradlew testDebugUnitTest` or `gradlew.bat testDebugUnitTest`
  - The default for most edits: it compiles the app and runs the ViewModel, client, contract and Compose UI tests, all on the JVM.
- `./gradlew assembleDebug testDebugUnitTest`
  - What CI runs and what closes a change: add `assembleDebug` when resources, manifests, packaging or dependencies may be affected.
- `./gradlew compileDebugKotlin` or `gradlew.bat compileDebugKotlin`
  - The fastest compile check for Kotlin and Compose edits while iterating.
- `./gradlew lintDebug` or `gradlew.bat lintDebug`
  - Add when resources, manifests, accessibility-sensitive UI or platform configuration change.
- `./gradlew assembleRelease` or `gradlew.bat assembleRelease`
  - Add when release-only build logic changes. It needs `-PapiBaseUrl=https://...`, because a release build refuses a cleartext base URL. Signing and store upload belong to the project owner (see the `deployment` skill's mobile note).
- `./gradlew installDebug` with `adb reverse`
  - Use when a device or emulator is available and the change affects the running app: run `task <app-id>:reverse` first so the app reaches the local backend at `localhost`.

## Troubleshooting

- A failure that looks stale after dependency or plugin changes: stop the Gradle daemon (`./gradlew --stop`), remove `app/build` and `.gradle`, and rebuild with `--no-build-cache --rerun-tasks`.
- `SDK location not found`: set `ANDROID_HOME` or `sdk.dir` in the git-ignored `local.properties`.
- `ApiContractTest` fails: the client and `shared/api-contracts/openapi.yml` disagree; change them together (see `@@invoke:android-contract-alignment@@`).
- The sign-in reports an unreachable backend or a loopback refusal: the backend runs under its `local` profile and `adb reverse` is set; do not change the base URL to `10.0.2.2`.

## Report Clearly

- State exactly which tasks ran.
- State whether they passed or failed.
- If you skip a stronger verification step, say why.
