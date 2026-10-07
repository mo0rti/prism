# iOS App

iOS App is an iOS app of Prism Golden. Prism's `ios-swiftui` pack generated it at `mobile-ios/` with one working slice: a "Local development sign-in" and a screen that shows the signed-in user from `GET /api/me`.

## Run it

You need a Mac with Xcode 26.6 (CI builds with exactly that version; a newer one usually works locally), [XcodeGen](https://github.com/yonaskolb/XcodeGen) (`brew install xcodegen`) and a backend that serves `shared/api-contracts/openapi.yml`. With the `spring-backend` pack, start the backend under its `local` profile (`task db-up`, then `task <backend-app-id>:dev`, which is `task backend:dev` for the default app), then:

```bash
cd mobile-ios
xcodegen generate                 # creates MobileIos.xcodeproj from project.yml
open MobileIos.xcodeproj    # run the MobileIos scheme on an iPhone simulator
```

Use "Local development sign-in", and the profile screen shows what the backend returns for `GET /api/me`.

## Check it

```bash
task mobile-ios:build
task mobile-ios:test        # unit tests and the sign-in UI test
```

CI runs the same steps on a macOS runner (`.github/workflows/mobile-ios.yml`): it generates the project with XcodeGen, builds for a simulator and runs the tests. That macOS run is what proves the app builds; Windows and Linux cannot build it.

## The slice

| File | What it does |
| --- | --- |
| `Sources/SignIn/SignInView.swift`, `Sources/SignIn/SignInViewModel.swift` | The screen labelled "Local development sign-in" |
| `Sources/Profile/ProfileView.swift`, `Sources/Profile/ProfileViewModel.swift` | The profile read from `GET /api/me` |
| `Sources/Networking/APIClient.swift`, `Sources/Networking/APIEndpoint.swift` | The client of the two contract operations and their paths |
| `Sources/Session/TokenStore.swift`, `Sources/Session/SessionModel.swift` | The in-memory token and the signed-in state |
| `Sources/RootView.swift` | Wires the client, the token store and the view models; shows the sign-in or the profile |
| `Tests/` | Unit tests of both view models and the client, with a fake client |
| `UITests/SignInUITests.swift` | The UI test of the sign-in screen |
| `project.yml` | The XcodeGen definition: targets, scheme, bundle identifier `com.example.prismgolden.mobileios` and `API_BASE_URL` |

## What the dev identity is, and is not

- The backend offers `POST /api/dev-identity/token` only under its `local` profile and only to requests from its own machine. Elsewhere it answers 404, and the sign-in here reports that the backend has no local development sign-in.
- **It works in the simulator only.** The simulator shares the Mac's network, so `http://localhost:8080` reaches a backend on the Mac as loopback. A physical device reaches the Mac over the network, is not loopback, and gets a 403 that the app explains. A device build needs your identity provider.
- The token lives in memory only and is never logged; the Keychain is the place for a real provider's tokens.
- It is **not complete authentication**: it proves nothing about who the person is. Replace it with your identity provider before anything ships. The real provider, the authorization policy, the secrets and the release are yours; the `ios-conventions`, `ios-contract-alignment` and `security-auth` skills describe the replacement.
- `audience` is display text. No screen, check or permission reads it, and a label never enforces authorization. Use a separate app when audiences differ in deployment or security boundary.

## Versions and the backend address

Swift, Xcode and the iOS deployment target are pinned in `packs/versions.yml` of the Prism template, and `project.yml` follows those pins. `API_BASE_URL` is a build setting in `project.yml`: Debug is `http://localhost:8080` (the backend this app was generated for), and Release is empty until you set your deployed backend (HTTPS).
