# Android App Guide - Prism Golden

## Tech Stack

- **Kotlin 2.3.10** and **Jetpack Compose** (BOM 2026.01.01) with Material 3, on the **Android Gradle Plugin 8.13.2** and **Gradle 8.14.3**, built with JDK 21
- **Retrofit 3.0.0**, **OkHttp 4.12.0** and **kotlinx.serialization** for the client of `shared/api-contracts/openapi.yml`
- **Lifecycle ViewModel** with `StateFlow`, wired by hand in `AppContainer` (no DI framework, no database)
- **JUnit 4.13.2**, **kotlinx-coroutines-test**, **MockWebServer** and **Robolectric 4.16** with the Compose test rule for the JVM tests
- Min SDK 29, target SDK 36, compile SDK 36

`packs/versions.yml` of the Prism template pins these versions; `gradle/libs.versions.toml` and `gradle/wrapper/gradle-wrapper.properties` follow it.

## Purpose

`mobile-android/` is an Android app. The pack generates the project structure, one compiling vertical slice and its tests, and no example business features. Application ID and namespace: `com.example.prismgolden.mobileandroid`.

## Project Structure

```text
mobile-android/
├── app/
│   └── src/
│       ├── main/kotlin/com/example/prismgolden/mobileandroid/
│       │   ├── App.kt, AppContainer.kt, MainActivity.kt
│       │   ├── ui/
│       │   │   ├── AppRoot.kt          # profile while signed in, sign-in otherwise
│       │   │   ├── signin/             # "Local development sign-in": Screen, Route, ViewModel
│       │   │   └── profile/            # GET /api/me: Screen, Route, ViewModel
│       │   ├── data/api/               # ApiService, ApiModels, ApiClient, RetrofitApiClient
│       │   ├── session/SessionStore.kt # the access token, in memory only
│       │   └── designsystem/           # AppTheme, Spacing, LoadingIndicator, ErrorView
│       ├── debug/                      # cleartext HTTP to localhost, debug builds only
│       └── test/                       # ViewModel, client, contract and Compose UI tests
├── gradle/                             # version catalog and wrapper
├── gradle.properties                   # apiBaseUrl
└── Taskfile.yml
```

## Run And Test

```bash
task mobile-android:build      # ./gradlew assembleDebug
task mobile-android:test       # ./gradlew testDebugUnitTest
task mobile-android:lint       # ./gradlew lintDebug
task mobile-android:reverse    # adb reverse tcp:8080 tcp:8080
task mobile-android:install    # ./gradlew installDebug
```

Gradle needs JDK 21 and an Android SDK with platform 36 (`ANDROID_HOME`, or `sdk.dir` in the git-ignored `local.properties`).

## Sign-in And Session

1. `SignInScreen` is labelled "Local development sign-in" and says it is not complete authentication. Its button calls `SignInViewModel.onSignInClick()`.
2. The ViewModel calls `ApiClient.createDevToken()`, the contract's `POST /api/dev-identity/token`, and opens the session with the returned token.
3. `AppRoot` shows `ProfileScreen` while the session is open. `ProfileViewModel` reads `GET /api/me` with `Authorization: Bearer <token>`.
4. A 401 closes the session and returns to the sign-in. Sign out closes it too.

`SessionStore` keeps the token in memory only: it is never written to disk, logged or put in `toString()`, and the client adds no HTTP logging interceptor. A new process starts signed out. The sign-in failures are told apart: the backend does not serve the dev identity (404), the request did not arrive from loopback (403), the backend is unreachable, or the answer was unexpected.

## Reaching The Local Backend

The backend serves the dev identity only under its `local` profile and only to requests from its own loopback interface. The app therefore calls `http://localhost:8080/` (`apiBaseUrl` in `gradle.properties`, the backend this app was generated for), and `adb reverse` forwards the device's `localhost:8080` to the host's:

| Target | What to do |
| --- | --- |
| Emulator | Start the backend with `task <backend-app-id>:dev`, run `task mobile-android:reverse`, run the app |
| USB device (or wireless debugging) | The same; `adb reverse` works over any adb connection |
| Another backend port | `task mobile-android:reverse BACKEND_PORT=<port>` and build with `-PapiBaseUrl=http://localhost:<port>/` |
| A device that only shares your network | The dev identity is not reachable, by design. Use USB, or replace the sign-in with a real identity provider |

`adb reverse` is lost when the device or the adb server restarts. `10.0.2.2` and LAN addresses reach the backend from a non-loopback address, so the backend refuses them; do not add them to the app's network security config and do not loosen the backend's guard. Debug builds allow cleartext HTTP to `localhost` (`app/src/debug/res/xml/network_security_config.xml`); release builds are HTTPS-only and refuse an `apiBaseUrl` that is not `https://`.

## Tests

- `SignInViewModelTest`, `ProfileViewModelTest`: both state holders against `support/FakeApiClient`, on `MainDispatcherRule`. Create a ViewModel in `@Before`, after the rule has replaced the main dispatcher.
- `RetrofitApiClientTest`: the real client against a MockWebServer: routes, the bearer header, status mapping and token redaction.
- `ApiContractTest`: the client's routes, the DTOs' fields and `getMe`'s bearer security against `shared/api-contracts/openapi.yml`. The build passes the contract's path as the `prism.apiContract` system property.
- `SignInScreenTest`: a Compose UI test under Robolectric. It checks that the screen carries the label "Local development sign-in".

A change is done when `./gradlew assembleDebug testDebugUnitTest` passes in this folder.

## Replacing The Dev Identity

Follow the `security-auth` skill for the backend side, then in this app: replace `ApiClient.createDevToken` and `SignInViewModel` with the provider's flow, keep the token in `SessionStore` (or encrypted storage you choose), change the "Local development sign-in" label and its test with the dev-identity call, and extend `ApiContractTest` for any operation you add to the contract.

## Related Docs

- [Architecture Overview](../../docs/architecture.md) for system-wide constraints
- [API Conventions](../../docs/api/conventions.md) for URL, error, and versioning rules
