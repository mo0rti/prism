# iOS App Runbook - Prism Golden

What an operator needs to know about this iOS app. The sections under "Known from the code" come from the generated code and stay true until the code changes. Prism deploys nothing, so everything about distribution is an **Unknown:** item until the team records it here. Replace each item with the fact when it is decided.

## Known from the code

### Health

- The app is a client with no server of its own, so it has no health endpoint. It depends on the backend that serves `shared/api-contracts/openapi.yml`; when the app shows errors, check the backend's health first.
- The sign-in explains a `403` from the backend: the development identity answers loopback requests only, so it works in the simulator and not on a physical device.

### Logs

- In the simulator or on a device, read the log in Xcode's console or with Console.app. The app never logs the access token.
- The pack configures no crash reporting and no analytics.

### Configuration

| Setting | Meaning |
|---|---|
| `API_BASE_URL` (build setting in `project.yml`) | The backend's base URL. Debug is `http://localhost:8080`. Release is empty until the team sets its deployed backend, which must be HTTPS. |

Bundle identifier: `com.example.prismgolden.mobileios`.

### Run it locally

```bash
cd mobile-ios
xcodegen generate                       # creates MobileIos.xcodeproj from project.yml
open MobileIos.xcodeproj    # run the MobileIos scheme on an iPhone simulator
```

### Release artifact

- `fastlane test` runs the tests; `fastlane beta` builds and uploads to TestFlight, and reads its signing and App Store Connect credentials from the environment (`ASC_KEY_ID`, `ASC_ISSUER_ID`, `ASC_KEY_CONTENT` and the `match` setup).
- `.github/workflows/mobile-ios.yml` builds for a simulator and runs the tests on a macOS runner on every change. Only that run proves the app builds.

## Unknown

- **Unknown:** Where builds are published (TestFlight, the App Store, another channel) and who publishes them.
- **Unknown:** Where the `match` certificates repository and the App Store Connect key are kept, and who can use them.
- **Unknown:** How to withdraw or replace a bad release, and how long App Store review takes.
- **Unknown:** How crashes and errors reach the team, and who is alerted.
- **Unknown:** The production `API_BASE_URL`.
- **Unknown:** The oldest app version the backend still supports.
- **Unknown:** Who is on call for this app and how to reach them.
