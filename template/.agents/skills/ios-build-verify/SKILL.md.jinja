---
name: ios-build-verify
description: Build and verification workflow for the generated iOS app. Use when asked to compile, test, debug build failures, or choose the cheapest sufficient validation task for a change.
---

# iOS Build Verify

Use the smallest validation task that gives trustworthy feedback for the change.

## Request

$ARGUMENTS

## Default task selection

- `task mobile-ios:generate-project`
  - Use after `project.yml`, target or scheme changes, Swift Package additions, xcconfig or build-setting edits, entitlements, resource-bundle changes, or source-layout changes that affect XcodeGen output.
- `task mobile-ios:build`
  - Use for most Swift, SwiftUI, ViewModel, repository, DI, and navigation edits.
- `task mobile-ios:test-unit`
  - Prefer this when ViewModel or repository logic changes and no UI behavior is affected.
- `task mobile-ios:test`
  - Use when both unit and UI coverage are relevant, or when the change spans logic plus app flow behavior.
- `task mobile-ios:test-ui`
  - Use when screen structure, accessibility identifiers, auth gating, or app-launch behavior changes.
- `xcodebuild archive ...`
  - Escalate here when signing, Info.plist values, release build settings, or generated project structure may affect archive or release behavior.
- `bundle exec fastlane beta`
  - Use when validating the TestFlight release lane or debugging release automation after signing and CI release changes.
- Direct `xcodebuild ...`
  - Use only when debugging a specific Xcode build issue beyond the Taskfile wrappers.

## Troubleshooting

- If project-generation output looks stale, rerun `task mobile-ios:generate-project`, especially after structural XcodeGen changes.
- If Xcode build metadata looks stale, use a fresh DerivedData path when invoking `xcodebuild` directly.
- The generated UI suite is smoke-level by default; passing `task mobile-ios:test-ui` confirms launch, auth gating, and a small set of critical flows, not full screen coverage.
- If the change is UI-only but touches shared theme or common UI, prefer `task mobile-ios:build` first and escalate to UI tests when identifiers, flow structure, or launch/auth state changed.
- If you are not on Mac, explicitly list which verification steps were skipped, why they were skipped, and that real iOS validation is deferred to Mac CI or a Mac follow-up session.

## Report clearly

- State exactly which task or command ran.
- State whether it passed or failed.
- If you skip a stronger verification step, say why.
