# Android App

Android App is an Android app of Prism Golden. Prism's `android-compose` pack generated it at `mobile-android/` with one working slice: a "Local development sign-in" screen and a profile screen that shows the signed-in user from `GET /api/me`. Application ID: `com.example.prismgolden.mobileandroid`.

## Run it

You need JDK 21, an Android SDK with platform 36 (`ANDROID_HOME`, or `sdk.dir` in the git-ignored `local.properties`) and a backend that serves `shared/api-contracts/openapi.yml`. With the `spring-backend` pack, start the backend under its `local` profile (`task db-up`, then `task <backend-app-id>:dev`, which is `task backend:dev` for the default app). Then, with an emulator running or a device connected over USB:

```bash
cd mobile-android
adb reverse tcp:8080 tcp:8080     # or: task mobile-android:reverse
./gradlew installDebug            # or: task mobile-android:install
```

Open the app, use "Local development sign-in", and the profile screen shows what the backend returns for `GET /api/me`.

### Why `adb reverse`

The backend's development identity answers requests from its own loopback interface only. The emulator's alias for the host (`10.0.2.2`) and a LAN address arrive from another address, so the backend refuses them, and it must stay that way. `adb reverse` makes `localhost:8080` on the device or emulator reach `localhost:8080` on your machine, which the backend sees as loopback. The app's default `apiBaseUrl` (`gradle.properties`) is `http://localhost:8080/`.

- Run `adb reverse` again after the emulator, the device or the adb server restarts.
- For a backend on another port, run `task mobile-android:reverse BACKEND_PORT=8081` and build with `-PapiBaseUrl=http://localhost:8081/` (the value must end with a slash).
- A device that only shares your network cannot reach the dev identity. Use USB or wireless debugging with `adb reverse`.

## Check it

```bash
./gradlew assembleDebug testDebugUnitTest
./gradlew lintDebug
```

The unit tests run on the JVM and need no emulator: both ViewModels against a fake client, the Retrofit client against a MockWebServer, the client against the shared contract, and a Compose UI test of the sign-in screen (Robolectric). CI runs `assembleDebug` and `testDebugUnitTest` on a clean runner (`.github/workflows/mobile-android.yml`).

## The slice

| File (under `app/src/main/kotlin/com/example/prismgolden/mobileandroid/`) | What it does |
| --- | --- |
| `ui/signin/SignInScreen.kt`, `SignInRoute.kt`, `SignInViewModel.kt` | The screen labelled "Local development sign-in", and the sign-in through `createDevToken` |
| `ui/profile/ProfileScreen.kt`, `ProfileRoute.kt`, `ProfileViewModel.kt` | The profile read from `GET /api/me` (`getMe`) |
| `ui/AppRoot.kt` | The profile while a session is open, the sign-in otherwise |
| `data/api/ApiService.kt`, `ApiModels.kt`, `ApiClient.kt`, `RetrofitApiClient.kt` | The client of the shared contract |
| `session/SessionStore.kt` | The access token, in memory only |
| `AppContainer.kt`, `App.kt`, `MainActivity.kt` | Hand-wired dependencies and the host activity |
| `designsystem/` | `AppTheme`, `Spacing`, `LoadingIndicator`, `ErrorView` |

## What the dev identity is, and is not

- The backend offers `POST /api/dev-identity/token` only under its `local` profile and to loopback requests. Elsewhere it answers 404, and the sign-in here reports that the backend has no local development sign-in.
- The token lives in memory only. The app never logs it, writes it to disk or shows it, and a new process starts signed out. A rejected token returns to the sign-in.
- It is **not complete authentication**: it proves nothing about who the person is. Replace it with your identity provider before anything ships. The real provider, the authorization policy, the secrets and the release signing are yours; the `android-conventions`, `security-auth` and `deployment` skills describe the replacement and the release notes.
- Debug builds allow cleartext HTTP to `localhost` only. A release build is HTTPS-only and refuses an `apiBaseUrl` that is not `https://`.

## Versions

AGP, Kotlin, Gradle, the Compose BOM and the test tooling are pinned in `packs/versions.yml` of the Prism template; `gradle/libs.versions.toml` and the wrapper properties follow those pins.
