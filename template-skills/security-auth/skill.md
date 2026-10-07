---
name: security-auth
description: "Backend security and authentication conventions for this Spring Boot project. Use when changing public versus authenticated routes, JWT validation, current-user access, the local development identity, replacing it with a real identity provider, or security-related configuration of a backend app."
layers: [codex, claude-skill]
codex:
  display_name: "Security & Auth"
  short_description: "Guard backend routes and the dev identity"
  default_prompt: "Use @@invoke:security-auth@@ to handle backend route security, the local dev identity, JWT validation, or the switch to a real identity provider."
  implicit: true
---

# Security & Authentication

Use this skill for backend auth exposure, JWT validation, the local development identity and the security-boundary decisions around them.

## Role Boundary

- Use this skill for public/private route decisions, JWT validation, the dev identity, replacing it with an identity provider, and current-user access.
::: only claude-skill
- Use `authorization-rules` for method-level authorization, ownership checks, and business-policy access decisions inside authenticated flows.
:::
- Use `@@invoke:spring-boot-conventions@@` for general controller and service structure.
- Use `@@invoke:error-handling@@` for auth-related exception codes and API error responses.
::: only codex
- Use `@@invoke:endpoint@@` when the task spans contract, DTO, controller, and persistence changes.
:::

## Who Owns What

Prism owns the auth **contract**: `shared/api-contracts/openapi.yml` defines `POST /api/dev-identity/token` and `GET /api/dev-identity/jwks` (both tagged `x-prism-dev-only`) and `GET /api/me`, and the backend slice implements them. The JWKS route publishes the dev identity's public key, so another local service, such as the `python-agent-service` stack, verifies the tokens with no shared secret. The user and their agent own the **real identity provider**, the authorization policy, the secrets and the deployment. The generated backend is a bearer-token resource server; it never stores passwords, runs OAuth flows or issues production tokens.

## Slice files

Paths are inside the backend app's folder{% for app in apps if app.stack == "spring-backend" %}{{ " (" if loop.first else ", " }}`{{ app.path }}/`{{ ")" if loop.last }}{% endfor %}. `<package path>` is the app's package, `<package_identifier>.<app id without hyphens>`, written with slashes. The contract is `shared/api-contracts/openapi.yml` at the workspace root.

- `src/main/kotlin/<package path>/bootstrap/SecurityConfig.kt` - filter chain, route exposure, which decoder validates tokens
- `src/main/kotlin/<package path>/bootstrap/security/ApiAuthenticationEntryPoint.kt` - 401 reply in the shared error format
- `src/main/kotlin/<package path>/bootstrap/security/RejectingJwtDecoder.kt` - the decoder of an app with no identity provider
- `src/main/kotlin/<package path>/bootstrap/security/AudienceValidator.kt` - requires this API's audience in every token of a real provider
- `src/main/kotlin/<package path>/bootstrap/AudienceGuard.kt` - the startup guard that refuses a provider configured without an audience
- `src/main/kotlin/<package path>/bootstrap/DevIdentityConfig.kt` - the dev identity beans (profile `local`)
- `src/main/kotlin/<package path>/bootstrap/DevIdentityGuard.kt` - the startup guard that refuses `local` together with an issuer
- `src/main/kotlin/<package path>/bootstrap/properties/DevIdentityProperties.kt` - the dev identity's properties
- `src/main/kotlin/<package path>/modules/devidentity/controller/DevIdentityController.kt` - the token route and the JWKS route
- `src/main/kotlin/<package path>/modules/devidentity/service/DevIdentityJwksService.kt` - the public key set; only the public half leaves the service
- `src/main/kotlin/<package path>/modules/devidentity/service/DevIdentityTokenService.kt` - issues the token
- `src/main/kotlin/<package path>/modules/devidentity/service/LoopbackRequestPolicy.kt` - accepts loopback requests only
- `src/main/kotlin/<package path>/modules/users/controller/MeController.kt` - `GET /api/me`
- `src/main/kotlin/<package path>/modules/users/service/UserService.kt` - the first-call profile creation
- `src/main/resources/application.yml` - datasource, schema, `prism.dev-identity.token-ttl`

## Current Security Model

- Stateless: `SessionCreationPolicy.STATELESS`, no cookies, CSRF disabled because only bearer tokens authenticate.
- Open routes: `/actuator/health`, `POST /api/dev-identity/token` and `GET /api/dev-identity/jwks`. Everything else needs a valid bearer JWT. Keep public matchers explicit, never widened to `/api/**`.
- The two dev-identity routes are open to the filter chain in every profile so that the default profile answers them with 404; the controller exists only under `local` and refuses non-loopback requests itself.
- One `JwtDecoder` validates tokens, chosen in `SecurityConfig`: the `local` profile's decoder, else the one Spring Boot builds from `spring.security.oauth2.resourceserver.jwt.*`, else `RejectingJwtDecoder`, which rejects every token (fail closed).
- Missing, malformed, expired or foreign tokens get 401 from `ApiAuthenticationEntryPoint`; an authenticated caller without permission gets 403.
- `GET /api/me` reads the token's `sub`, `email` and `name` claims through `MeController` and `UserService`, which creates the `users` row on first use.
- Method-security annotations are not enabled by default.
::: only claude-skill
- When business authorization grows beyond route exposure, enable and model it intentionally through `authorization-rules` rather than widening route rules alone.
:::

## The Dev Identity Is Local Development Sign-In, Not Authentication

Never present it, or build a feature on it, as complete authentication. Its guards, each with a test, must stay:

| Guard | Test |
| --- | --- |
| The token route, the JWKS route and their beans exist only under `@Profile("local")`; every other profile answers 404 | `DefaultProfileIntegrationTest` |
| The token is a JWT with `iss=prism-dev-identity` and a short lifetime (15 minutes, at most one hour) | `DevIdentityTokenServiceTest`, `LocalProfileIntegrationTest` |
| The signing key is an RSA key generated in memory at startup, never written to disk; no JWT secret exists in the repository | `DevIdentityTokenServiceTest`, `LocalProfileIntegrationTest` (a token from another key is rejected) |
| Both routes answer loopback requests only: the peer address and the server name are loopback and no forwarding header is present | `LoopbackRequestPolicyTest`, `LocalProfileIntegrationTest` |
| The JWKS carries the public key only, never a private member | `LocalProfileIntegrationTest` |
| Startup fails when `local` is active together with a configured identity provider | `DevIdentityStartupGuardTest` |
| The generated `docker-compose.yml` sets no profile; docs and the `dev` task set `local` explicitly | - |

Never enable `local` on a shared or deployed environment. Never weaken a guard to make a test pass.

## Replacing The Dev Identity With A Real Identity Provider

The provider is the user's choice. Record it as a decision page (`knowledge/wiki/decisions/`) before changing code, then:

1. **Configure the resource server.** Set the provider's issuer through the environment, never in a file with the `local` profile: `SPRING_SECURITY_OAUTH2_RESOURCESERVER_JWT_ISSUER_URI` (or `spring.security.oauth2.resourceserver.jwt.issuer-uri`; `jwk-set-uri` also works). Spring Boot then builds the decoder, and `SecurityConfig` picks it up with no change. The provider's client secrets stay with the provider and in the deployment's secret store, not in this repository.
2. **Set the audience.** Boot checks the issuer and the expiry, not who the token is for, so the app requires this API's audience too: set `SPRING_SECURITY_OAUTH2_RESOURCESERVER_JWT_AUDIENCES` (or `spring.security.oauth2.resourceserver.jwt.audiences`, comma-separated) to the audience your provider puts in the access tokens of this API. `bootstrap/AudienceGuard.kt` stops startup when a provider is configured without one, and `bootstrap/security/AudienceValidator.kt` makes `SecurityConfig` reject a token whose `aud` is missing or names another API. The agent service of the workspace takes the same value from `AGENT_OIDC_AUDIENCE` (and its issuer from `AGENT_OIDC_ISSUER`), so one provider setup serves both.

3. **Map the claims.** `MeController` builds `IdentityClaims` from `sub`, `email` and `name`; change the names to what the provider's access token carries. If it carries no email, call the provider's userinfo endpoint from a service, outside any database transaction. Map roles or scopes with a `JwtAuthenticationConverter` and model authorization with `authorization-rules`.
4. **Remove the dev identity.** Delete `bootstrap/DevIdentityConfig.kt`, `bootstrap/DevIdentityGuard.kt`, `bootstrap/properties/DevIdentityProperties.kt`, `modules/devidentity/`, the `POST /api/dev-identity/token` and `GET /api/dev-identity/jwks` permit rules in `SecurityConfig`, `prism.dev-identity` in `application.yml` and the `dev` task's `local` profile. Remove `/api/dev-identity/token` and `/api/dev-identity/jwks` from `shared/api-contracts/openapi.yml` and update `OpenApiContractTest`. Any other local service that verifies the dev identity's tokens, such as an agent service, switches to the provider's issuer in the same change. Replace `LocalProfileIntegrationTest` with tests that send tokens built by a test-only key and decoder (add `spring-security-test` and use its `jwt()` request post-processor with `MockMvc`). Keep `DefaultProfileIntegrationTest`'s check that a token from an unknown issuer is rejected.
5. **Update the clients.** Web and mobile apps label their sign-in "Local development sign-in" while the dev identity exists. Switch them to the provider's flow in the same change, with their own `security-auth` equivalents.
6. **Verify.** A request with no token, an expired token, a token from another issuer and a token with the wrong audience each get 401; a valid token reads `/api/me`.

## Rules

- Keep public matchers explicit; update `SecurityConfig` whenever endpoint exposure changes.
- Use `@AuthenticationPrincipal jwt: Jwt` in controllers; reach for `SecurityContextHolder` only where controller injection is not practical.
- Keep secrets in environment-backed configuration, never hardcoded Kotlin values or checked-in files.
- Bind security settings with typed `@ConfigurationProperties` under `bootstrap/properties/`.
- Align route security with `shared/api-contracts/openapi.yml`.
- Do not wrap outbound calls to the identity provider in long-lived database transactions.
- Do not log tokens.

## Minimum Verification

- Re-check unauthenticated access to any route whose matcher changed.
- Re-check that the token route and the JWKS route answer 404 without the `local` profile.
- Re-check that the dev-identity guards above still have their tests.
- Update the OpenAPI contract if endpoint security changed.
