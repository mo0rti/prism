---
name: android-contract-alignment
description: "Backend contract alignment rules for Android DTOs, enums, Retrofit APIs, and auth. Use when changing request or response shapes, Retrofit endpoints, mappers, or auth-boundary code under `mobile-android/`."
layers: [codex, claude-skill]
platforms: [mobile-android]
codex:
  display_name: "Android Contract Alignment"
  short_description: "Keep Android DTOs and APIs aligned"
  default_prompt: "Use @@invoke:android-contract-alignment@@ when changing Android API contracts or DTOs."
  implicit: true
claude-skill:
  user-invocable: false
---

# Android Contract Alignment

Use this skill when backend-facing Android code changes.

## Scope

- Own request and response shapes, enums, Retrofit endpoints, and auth-related contract wiring.
- Defer screen structure, design-system reuse, and general repository workflow to `@@invoke:android-conventions@@`.

## DTO and Enum Rules

- Keep DTOs in `feature/*/data/remote/dto/` when the payload is feature-specific.
- Keep shared DTOs in `core/model/` when multiple features consume the same shape.
- DTOs use `@Serializable` (Kotlinx Serialization) - do not use Gson or Moshi annotations.
- Domain models in `feature/*/domain/` are framework-light (no serialization annotations).
- Map DTOs to domain models in the repository layer, not in ViewModels.

## Retrofit and Service Rules

- Retrofit API interfaces live in `feature/*/data/remote/api/` or `core/network/`.
- API base URL comes from `BuildConfig.API_BASE_URL` through `NetworkModule` in `core/di/`; do not hardcode URLs.
- Auth headers come from `AuthInterceptor` reading `TokenStorage`; do not add ad hoc token plumbing in features.
- Token refresh is handled by `TokenAuthenticator` (OkHttp Authenticator), and a rejected refresh token (400, 401 or 403) falls back to `SessionManager.onLogout()`, while timeouts, I/O errors and 5xx keep the session. Features do not handle 401s directly.

## Cross-Check Sources

- Use the OpenAPI spec in `shared/api-contracts/openapi.yml` as the primary source for endpoint shapes.
{% if "backend" in platforms %}- Use the backend in `backend/` to confirm endpoint behavior when the spec is ambiguous.
{% endif %}
## Validation

- Run `./gradlew compileDebugKotlin` or `gradlew.bat compileDebugKotlin` after contract changes.
- Add targeted tests when mapper or repository logic changes.
