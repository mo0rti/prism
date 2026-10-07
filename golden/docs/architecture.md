# Architecture Overview - Prism Golden

## System Description

The reference workspace that Prism's CI regenerates and builds, one app of each stack

## Platform Map

| Platform | Tech Stack | Hosting | Purpose |
|----------|-----------|---------|---------|
| Backend | Spring Boot, Kotlin, Java 21 | Project owner's choice (see the `deployment` skill) | REST API and business logic (backend/) |
| Web | Next.js 16.4.0, React 19.3.0, TypeScript 5.9.3 | Project owner's choice (see the `deployment` skill) | Web app for B2C (web/) |
| Android App | Kotlin 2.3.10, Jetpack Compose, Retrofit 3.0.0 | Project owner's choice (see the `deployment` skill) | Android app (mobile-android/) |
| iOS App | Swift 6.0, SwiftUI, iOS 17.0+, XcodeGen | App Store | Native iOS app (mobile-ios/) |
| Agent Service | Python 3.12, FastAPI 0.142.2, uv | Project owner's choice (see the `deployment` skill) | AI agent service: assists with the signed-in user's own data through read-only tools and never advises (agent-service/) |
| Database | PostgreSQL 16 | Local development in Docker Compose; hosting is the project owner's choice | Data persistence |

## Architecture Pattern


### Mobile: MVVM (Model-View-ViewModel)

Android and iOS follow the same MVVM idea. The iOS slice is thin, so its view models call the API client directly; add a repository layer when a feature needs one:

```
View (UI)  ->  ViewModel (State + Logic)  ->  Repository  ->  Data Source (API/Local)
```

| Layer | Android | iOS |
|-------|---------|-----|
| View | `@Composable` functions | SwiftUI `View` structs |
| ViewModel | `ViewModel` + `StateFlow<UiState>` | `@MainActor @Observable` + a state enum |
| Repository | `ApiClient` interface + `RetrofitApiClient` | None in the slice |
| API Client | Retrofit + OkHttp + Kotlinx Serialization, hand-written and checked against the contract | `URLSessionAPIClient` over URLSession + `async/await` |
| Local Storage | In-memory session (nothing persisted) | In-memory token; Keychain for a real identity provider |
| DI | Hand-wired `AppContainer` | Protocols passed by initializer from `RootView` |


### API Contract

Single source of truth: [shared/api-contracts/openapi.yml](../shared/api-contracts/openapi.yml)

API clients are **generated** from this spec where a generator is configured; the Android and iOS clients are hand-written and kept to the spec. Never manually edit generated client code. Run `task generate-clients` after any spec change. An Android app's `ApiContractTest` fails when its client and the spec disagree.

### Authentication

Prism owns the auth contract; the real identity provider, the authorization policy and the secrets are yours. The contract (`POST /api/dev-identity/token`, tagged `x-prism-dev-only`, and `GET /api/me`) is in the OpenAPI spec.

A backend app is an OAuth2 resource server: it validates bearer JWTs and holds no signing secret. For local development it also ships a **local development identity**:

1. Under the `local` Spring profile only, `POST /api/dev-identity/token` signs a short-lived JWT (`iss=prism-dev-identity`) for a loopback request, with an RSA key generated in memory at startup
2. The client keeps the token (web apps in an HttpOnly cookie) and sends it as `Authorization: Bearer <token>`
3. `GET /api/me` returns the profile of the token's subject, creating it on the first call

The dev identity is local development sign-in, never complete authentication. Every other profile answers its token route with 404, startup fails when `local` meets a configured identity provider, and `docker-compose.yml` sets no profile. Replace it with your identity provider before any shared deployment; the `security-auth` skill has the steps. A web app's browser code never calls the backend: its server asks for the token, sets the cookie and attaches the bearer header.

### Design Tokens

Shared visual language: [shared/design-tokens/tokens.json](../shared/design-tokens/tokens.json)

Colors, spacing, typography, and border-radius values that each platform's theme files mirror. No script reads the file, so update the platform theme files when it changes.

## Key Conventions

1. **API contract first** - define endpoints in OpenAPI before implementing
2. **Documentation first** - create feature/entity docs before coding
3. **Feature modules** - backend domains live under `modules/<domain>/`
4. **Consistent naming** - docs, contract, and code should refer to the same feature names (for example, `users`)
5. **Never edit generated code** - modify the OpenAPI spec and regenerate

## Related Docs

- [API Conventions](api/conventions.md) for path versioning, auth headers, and error payloads
- [Backend Guide](../backend/docs/guide.md) for package layout and coding conventions
- [Agent Service Guide](../agent-service/docs/guide.md) for the agent turn, providers, identity and safety rules
- [Agent Instructions](../AGENTS.md) for the rules every AI agent follows, command surfaces and workflow expectations
