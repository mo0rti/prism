---
name: ios-build-verify
description: Build and verification workflow for the generated iOS apps. Use when asked to compile, test, debug build failures, or choose the cheapest sufficient validation task for a change.
---

# iOS Build Verify

Use the smallest validation task that gives trustworthy feedback for the change. The tasks run on Mac only; the iOS apps of this workspace are `mobile-ios` (`mobile-ios/`), and each task is named `task <app-id>:<task>`.

## Request

$ARGUMENTS

## Default task selection

- `task <app-id>:generate-project`
  - Use after `project.yml`, target or scheme changes, Swift Package additions, build-setting edits, entitlements, resource changes, or source-layout changes that affect XcodeGen output. The build and test tasks run it first.
- `task <app-id>:build`
  - Use for most Swift, SwiftUI, view model, networking and session edits.
- `task <app-id>:test-unit`
  - Prefer this when view model or client logic changes and no UI behavior is affected.
- `task <app-id>:test`
  - Use when both unit and UI coverage are relevant, or when the change spans logic plus screen behavior.
- `task <app-id>:test-ui`
  - Use when screen structure, accessibility identifiers or the launch screen changes.
- `xcodebuild archive ...`
  - Escalate here when signing, Info.plist values, release build settings, or generated project structure may affect archive or release behavior.
- `bundle exec fastlane beta` (in the app folder)
  - Use when validating the TestFlight lane or debugging release automation after signing and CI release changes.
- Direct `xcodebuild ...`
  - Use only when debugging a specific Xcode build issue beyond the Taskfile wrappers.

## Troubleshooting

- If project-generation output looks stale, rerun `task <app-id>:generate-project`, especially after structural `project.yml` changes.
- If Xcode build metadata looks stale, use a fresh DerivedData path when invoking `xcodebuild` directly.
- Build and test tasks run on `SIMULATOR_NAME` when it is set and on the newest available iPhone simulator otherwise. Set it when a task reports a simulator lookup error or you need a specific device.
- The generated UI suite is one smoke test of the sign-in screen. Passing `task <app-id>:test-ui` confirms launch and the sign-in controls, not the sign-in against a backend.
- If the change is UI-only, prefer `task <app-id>:build` first and escalate to the UI test when identifiers or screen structure changed.
- If you are not on Mac, explicitly list which verification steps were skipped, why, and that real iOS validation is deferred to the macOS CI job of the app or a Mac follow-up session.

## Report clearly

- State exactly which task or command ran.
- State whether it passed or failed.
- If you skip a stronger verification step, say why.
