---
name: ios-conventions
description: "Conventions for the generated iOS apps: the sign-in and profile slice, MVVM with Swift 6 concurrency, the API client, the in-memory token, and replacing the local development sign-in. Use when writing, extending or reviewing code under an iOS app folder."
user-invocable: false
---

# iOS Conventions

Apply these rules whenever you change an iOS app of this workspace. Each iOS app is one `ios-swiftui` app generated from the same pack, so the paths below are relative to the app's folder: `mobile-ios/`.

## Role boundary

- Use this skill for the slice and for cross-feature conventions.
- Keep feature orchestration in `ios-feature-delivery`.
- Keep contract and client decisions in `ios-contract-alignment`.
- Keep UI patterns in `swiftui-design-system`, tests in `ios-testing` and build selection in `ios-build-verify`.

## Slice files

The pack generates one vertical slice and no example business features. Paths are inside the iOS app's folder (`mobile-ios/`).

- `Sources/SignIn/SignInView.swift` is the screen labelled "Local development sign-in", and `Sources/SignIn/SignInViewModel.swift` is its state.
- `Sources/Profile/ProfileView.swift` shows the signed-in user's profile from `GET /api/me`, and `Sources/Profile/ProfileViewModel.swift` is its state.
- `Sources/Networking/APIClient.swift` is the client of the two contract operations. `Sources/Networking/APIEndpoint.swift` lists their paths.
- `Sources/Session/TokenStore.swift` keeps the token in memory. `Sources/Session/SessionModel.swift` says whether a person is signed in.
- `Sources/RootView.swift` is the composition root and chooses the screen from the session.
- `Sources/AppInfo.swift` holds the app's display name and `audience`. The audience is display text only: no screen, check or permission reads it, and a label never enforces authorization. A separate app is the answer when audiences differ in deployment or security boundary.
- `Tests/` and `UITests/` hold the unit tests of the view models and the client, and the UI test of the sign-in screen.

## Rules

- Follow MVVM: one `@MainActor @Observable` view model per screen, a view that only renders it, and dependencies passed in by initializer as protocols (`any APIClient`, `any TokenStore`).
- Every backend call goes through `APIClient`. Never create a raw `URLSession` call in a view or view model.
- Types that cross actors are `Sendable` value types. Do not add `@unchecked Sendable` or `nonisolated` workarounds without a reason stated in the change.
- Create each long-lived view model once, in the owner's `init` held in `@State` as `RootView` does, never in a view's `body`.
- The token lives in memory in the `TokenStore`. Never log it, print it, put it in a URL, `UserDefaults`, a file or an error message.
- Keep stable accessibility identifiers (`signin.title`, `signin.submit`, `profile.sign-out`, ...) on screen titles and critical controls: the UI test depends on them.
- Put a new screen in its own folder under `Sources/`, with its view and view model, and add a test for the view model.
- `project.yml` is the source of the Xcode project. Run `xcodegen generate` after structural changes (targets, schemes, build settings, packages, entitlements, resources). `API_BASE_URL` is a build setting there: Debug is the local backend, and Release is empty until you set your deployed backend.
- Versions (Swift, Xcode, the iOS deployment target) come from `packs/versions.yml` of the Prism template. Do not move them by hand.

## The local development sign-in

The sign-in is the contract's `POST /api/dev-identity/token`, which the backend serves only under its `local` profile and only to loopback requests. It is not complete authentication and the app must never present it as such.

It works in the simulator only. The simulator shares the Mac's network stack, so the loopback address in the Debug `API_BASE_URL` of `project.yml` (the backend the app was generated for; `http://localhost:8080` for the first backend) reaches a backend on the Mac as loopback. A physical device is not loopback: the backend answers 403, and the app says a physical device cannot use the dev identity. A device build needs the project's identity provider.

To replace it, follow `security-auth` for the backend side, then in each iOS app:

1. Replace the body of `signIn()` in `Sources/SignIn/SignInViewModel.swift` (and the `createDevToken` call in `Sources/Networking/APIClient.swift`) with the provider's flow, for example `ASWebAuthenticationSession` for an OAuth code flow.
2. Change `Sources/SignIn/SignInView.swift` to the provider's sign-in and remove the "Local development sign-in" label and the dev-identity call.
3. Add a Keychain-backed `TokenStore` in `Sources/Session/TokenStore.swift` and create it in `RootView.init` in place of `InMemoryTokenStore`.
4. Update `Tests/SignInViewModelTests.swift` and `UITests/SignInUITests.swift` to the new flow. They are the executable description of what the sign-in must do.
5. Set the Release `API_BASE_URL` in `project.yml` to the deployed backend (HTTPS) and review App Transport Security in `Sources/Info.plist`.

## Reference files

Load only the reference file the task needs:

- `references/swift6-observation-and-di.md` for `@MainActor`, Observation, `@Bindable`, dependency injection and view model ownership

## Read when needed

- `AGENTS.md` and `docs/guide.md` of the app

## Minimum verification

- Run `task <app-id>:build` on Mac after architecture-sensitive changes, and `task <app-id>:test-unit` after view model changes.
- If you are not on Mac, report which iOS verification steps were skipped, why, and that real validation is deferred to the macOS CI job of the app.
- If a change alters behavior the app's `AGENTS.md` or `docs/guide.md` describes, update it in the same session.
