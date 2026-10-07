# iOS App Guide - Prism Golden

## Tech Stack

- **Swift 6.0** with strict concurrency, **SwiftUI** and Observation, for **iOS 17.0+**
- **Xcode 26.0** and **XcodeGen**: `project.yml` is the source of the Xcode project
- **URLSession** for the client of `shared/api-contracts/openapi.yml`
- **XCTest** for the unit tests and the UI test

`packs/versions.yml` of the Prism template pins the Swift, Xcode and deployment-target versions; `project.yml` follows it.

## Purpose

`mobile-ios/` is an iOS app. The pack generates the project structure, one compiling vertical slice and its tests, and no example business features. The audience sets display text only: no screen, check or permission reads it.

## Project Structure

```text
mobile-ios/
├── project.yml                   # XcodeGen: targets, scheme, build settings, API_BASE_URL
├── Sources/
│   ├── App.swift                 # @main
│   ├── RootView.swift            # composition root; sign-in or profile
│   ├── AppInfo.swift             # display name and audience from Info.plist
│   ├── Info.plist                # the Release build's; Plists/Info.Debug.plist adds the local-networking exception
│   ├── SignIn/                   # "Local development sign-in"
│   ├── Profile/                  # GET /api/me
│   ├── Networking/               # APIClient, APIEndpoint, APIURL, APIError
│   ├── Session/                  # SessionModel, TokenStore (in memory)
│   └── Models/                   # DevTokenRequest, DevTokenResponse, UserProfile
├── Tests/                        # view model and client tests, FakeAPIClient
├── UITests/                      # the sign-in screen UI test
├── fastlane/                     # TestFlight lane; CI does not release
└── scripts/select-simulator.sh   # simulator selection for the tasks
```

## Run And Test

```bash
task mobile-ios:generate-project    # xcodegen generate
task mobile-ios:build
task mobile-ios:test                # unit tests and the UI test
task mobile-ios:test-unit
task mobile-ios:test-ui
```

The tasks run on Mac only. `SIMULATOR_NAME` picks the device; without it the newest available iPhone simulator runs. Start a backend under its `local` profile to sign in from the app.

## Sign-in And Session

1. The sign-in screen sends `POST /api/dev-identity/token` with the optional email and display name.
2. The view model keeps the returned token in the in-memory `TokenStore` and tells `SessionModel` that a person is signed in, so `RootView` shows the profile screen.
3. The profile screen calls `GET /api/me` with the token as a bearer header. A 401 clears the token and returns to the sign-in with a notice.
4. "Sign out" clears the token.

The backend serves the dev identity only under its `local` profile and only to loopback requests. The simulator reaches a backend on the Mac as `localhost`, which is loopback; a physical device is not loopback and is refused. It is not complete authentication: replace it with your identity provider before anything ships (see the `ios-conventions` and `security-auth` skills).

## Related Docs

- [Architecture Overview](../../docs/architecture.md) for system-wide constraints
- [API Conventions](../../docs/api/conventions.md) for URL, error, and versioning rules
