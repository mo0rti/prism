---
name: cursor-mobile-android
description: "Android (Kotlin, Jetpack Compose) app facts: stack, package structure, patterns and conventions."
layers: [cursor]
stacks: [android-compose]
cursor:
  file: mobile-android
  globs: "mobile-android/**"
---

# Android - Kotlin + Jetpack Compose (MVVM)

## Stack
- Kotlin, Jetpack Compose (BOM 2026.01.01), Hilt DI
- Retrofit 3 + kotlinx.serialization, OkHttp 4.12
- Room 2.8.4 (local DB), DataStore (token storage)
- Navigation Compose with type-safe routes
- Min SDK 29, Target SDK 36, Compile SDK 36

## Structure
```
app/src/main/kotlin/{{ package_identifier | replace('.', '/') }}/
  app/             -> App, MainActivity, MainActivityViewModel, AppRoot
  core/
    common/        -> AppResult
    launch/        -> LaunchUiState, LaunchDestination, LaunchPreferencesStorage
    session/       -> SessionManager (concrete class, auth state source)
    network/       -> ApiService, AuthInterceptor, TokenAuthenticator, NetworkMonitor
    datastore/     -> TokenStorage (DataStore)
    database/      -> AppDatabase, Converters (shared only)
    di/            -> NetworkModule, DatabaseModule, DispatcherModule, AppModule
    model/         -> User, Session (AuthState), Paging
  navigation/      -> Screen routes, NavGraph
  feature/welcome/ -> First-launch welcome slides (ui/ only)
  feature/*/
    domain/model/      -> Feature-specific domain models
    data/remote/dto/   -> @Serializable DTOs
    data/local/        -> Room Entity, DAO, Mappers (if feature needs persistence)
    data/repository/   -> Concrete repository classes (no interfaces)
    ui/                -> Route, Screen, ViewModel, components/
  designsystem/
    theme/         -> Color, Type, Shape, Dimensions, Theme
    text/          -> UiText
    components/    -> LoadingIndicator, ErrorView, StepNavigationButtons
```

## Patterns
- `@HiltViewModel` with `StateFlow<UiState>` (UiState sealed interface co-located in ViewModel file)
- Route/Screen split: Route = nav wiring + ViewModel; Screen = pure composable
- Repositories: concrete classes with `@Inject constructor`, injected by Hilt by type (no interfaces)
- Services and managers: concrete classes by default; no interface + impl pairs unless multiple implementations needed
- DI modules: NetworkModule, DatabaseModule, DispatcherModule, AppModule
- SessionManager exposes `StateFlow<AuthState>` for auth gating
- TokenAuthenticator handles 401 -> refresh -> retry automatically; it clears the session only when the backend rejects the refresh token (400, 401 or 403)
- Cleartext HTTP is allowed only in debug builds, for `10.0.2.2` and `localhost`, through `app/src/debug/`; release builds stay HTTPS-only
- Type-safe navigation via `@Serializable` sealed interface
- Dispatchers: `@IoDispatcher`, `@DefaultDispatcher`, `@MainDispatcher` qualifiers

## Conventions
- Feature-specific persistence in `feature/*/data/local/`, not `core/database/`
- DTOs in `data/remote/dto/`, domain models are framework-light (no @Serializable)
- No use cases by default - add `usecase/` only for non-trivial orchestration
- `AppResult<T>` avoids collision with `kotlin.Result`
- Tests: MockK + Turbine, mirror source structure
