---
name: ios-feature-delivery
description: Cross-layer feature orchestration for the generated iOS apps. Use when a task spans multiple layers and needs scoped planning, companion-skill selection, validation and documentation updates across models, networking, view models, SwiftUI screens and tests.
---

# iOS Feature Delivery

Use this skill to coordinate non-trivial feature work that crosses layers.

## Role boundary

- Use this skill as the delivery checklist and orchestration layer for multi-step work.
- Pull in companion skills for detailed rules instead of restating repository, contract, UI or verification conventions here.

## Slice files

The slice is the pattern to follow. Paths are inside the iOS app's folder (`mobile-ios/`).

- `Sources/SignIn/SignInView.swift` and `Sources/SignIn/SignInViewModel.swift` - a screen and its view model
- `Sources/Profile/ProfileView.swift` and `Sources/Profile/ProfileViewModel.swift` - a screen that reads through the client
- `Sources/Networking/APIClient.swift` - the client a new operation extends
- `Sources/RootView.swift` - the composition root, where a new screen is wired

## Request

$ARGUMENTS

## 1. Research the current shape

- Inspect the surrounding code in the app's `Sources/`: the sign-in and profile screens are the pattern to follow.
- Read the app's `AGENTS.md` and `docs/guide.md` first.
- Reuse nearby patterns before inventing a new one.

## 2. Verify contracts

- Cross-check `shared/api-contracts/openapi.yml` when endpoints, models or enums are involved.
- Cross-check the backend app when behavior or response semantics need confirmation.
- Cross-check `mobile-android/` when product parity or UX intent matters.


## 3. Map affected layers

Cover only the layers the feature truly needs:

- Models (`Sources/Models/`)
- API endpoints and the client (`Sources/Networking/`)
- View model state and intent methods
- SwiftUI screens
- Session and composition in `Sources/RootView.swift`
- Tests (`Tests/`, `UITests/`) and the app's docs

## 4. Use the right companion skills

- Use `$ios-conventions` for the slice, MVVM, concurrency and structure rules.
- Use `$ios-contract-alignment` for endpoint, model, `APIClient` and auth-boundary decisions.
- Use `$swiftui-design-system` for UI patterns, accessibility and Dynamic Type.
- Use `$ios-testing` for unit tests with the fake client and for UI tests.
- Use `$ios-build-verify` to choose the smallest trustworthy validation.

## 5. Execute and close out

- Implement only the layers the feature actually touches.
- If view model or client logic is added or changed, add at least one targeted test and confirm it passes with `task <app-id>:test-unit` on Mac before close-out. Escalate to `task <app-id>:test` when the change also affects screen behavior.
- If UI behavior is added or changed, confirm accessibility labels, traits, touch targets and stable identifiers are still correct before close-out.
- If storage, file access, user defaults or a new third-party SDK is introduced, review the privacy manifest guidance and add `PrivacyInfo.xcprivacy` when the project starts using covered APIs.
- If `project.yml` structure may be affected, rerun `task <app-id>:generate-project` before close-out.
- If actors, `@Observable` view models or async/await boundaries are touched, confirm no `@unchecked Sendable` or `nonisolated` workaround was introduced without explicit justification.
- Run at least `task <app-id>:build` on Mac, plus stronger targeted verification when the change crosses logic or integration boundaries.
- Update any affected docs in the same session.
