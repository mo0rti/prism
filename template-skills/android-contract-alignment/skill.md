---
name: android-contract-alignment
description: "Contract alignment rules for the Android client: the DTOs, the Retrofit service, the ApiClient and the bearer token. Use when changing request or response shapes, endpoints or auth-boundary code in an Android app folder."
layers: [codex, claude-skill]
stacks: [android-compose]
codex:
  display_name: "Android Contract Alignment"
  short_description: "Keep the Android client equal to the OpenAPI contract"
  default_prompt: "Use @@invoke:android-contract-alignment@@ when changing Android API contracts or DTOs."
  implicit: true
claude-skill:
  user-invocable: false
---

# Android Contract Alignment

Use this skill when backend-facing Android code changes. The paths below are under `app/src/main/kotlin/<package path>/` of the app ({% for app in apps if app.stack == "android-compose" %}`{{ app.path }}/`{{ ", " if not loop.last }}{% endfor %}), where `<package path>` is the application ID written with slashes.

## Scope

- Own the request and response shapes, the Retrofit endpoints and the bearer-token wiring.
- Defer screen structure, the session and state rules to `@@invoke:android-conventions@@`.

## The client is hand-written and checked

The Android client is not generated. `shared/api-contracts/openapi.yml` is the source, and the client matches it in four places that change together (the slice files below).

## Slice files

Paths are inside the Android app's folder ({% for app in apps if app.stack == "android-compose" %}`{{ app.path }}/`{{ ", " if not loop.last }}{% endfor %}). `<package path>` is the app's application ID, `<package_identifier>.<app id without hyphens>`, written with slashes.

- `app/src/main/kotlin/<package path>/data/api/ApiService.kt`: one Retrofit method per operation, with the contract's method and path (`createDevToken` is `POST /api/dev-identity/token`, `getMe` is `GET /api/me`).
- `app/src/main/kotlin/<package path>/data/api/ApiModels.kt`: one `@Serializable` data class per schema, with the schema's property names. A property that is not `required` has a default.
- `app/src/main/kotlin/<package path>/data/api/ApiClient.kt` and `app/src/main/kotlin/<package path>/data/api/RetrofitApiClient.kt`: the interface the ViewModels use, and its mapping of statuses to `ApiError`.
- `app/src/test/kotlin/<package path>/data/api/ApiContractTest.kt`: reads the contract and fails when the routes `ApiService` calls, the fields of the DTOs or `getMe`'s bearer security differ from it. Extend it with every operation you add.

## DTO rules

- DTOs use `@Serializable` (kotlinx.serialization); do not use Gson or Moshi annotations.
- A DTO that carries a credential overrides `toString()` to hide it, as `DevTokenResponse` does.
- Map DTOs to UI models in the ViewModel only when the screen needs another shape; the slice shows `UserProfile` as it arrives.

## Retrofit and auth rules

- The base URL is `BuildConfig.API_BASE_URL`, set from `apiBaseUrl` in `gradle.properties` and passed to `createApiService` by `AppContainer`. Do not hardcode URLs.
- An operation that needs the bearer token takes it as an argument of the `ApiClient` method and sends `Authorization: Bearer <token>` (`getMe` does), because the contract's global security asks for it. An operation marked `security: []` sends none.
- `x-prism-dev-only` operations (`createDevToken`) exist only for local development; do not add a second dev-only call to the app without marking it in the contract.
- Never add an HTTP logging interceptor, and never log a header or a body that carries a token.
- Status handling lives in `RetrofitApiClient.call`: 401 is `Unauthorized`, 403 and 404 mean something specific only where the operation says so (the dev identity), IO errors are `Network` and unreadable bodies are `Unexpected`.

## Cross-Check Sources

- Use the OpenAPI spec in `shared/api-contracts/openapi.yml` as the primary source for endpoint shapes.
{% if "spring-backend" in stacks %}{% for app in apps if app.stack == "spring-backend" %}- Use the backend app `{{ app.path }}/` to confirm endpoint behavior when the spec is ambiguous.
{% endfor %}{% endif %}
## Validation

- Run `./gradlew testDebugUnitTest` (or `gradlew.bat testDebugUnitTest`) after contract changes: `ApiContractTest` and `RetrofitApiClientTest` run with it.
- Add a `RetrofitApiClientTest` case for each new status the client maps.
