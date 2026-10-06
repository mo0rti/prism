---
name: cursor-backend
description: "Spring Boot 4 (Kotlin) backend facts: stack, package structure, patterns and commands."
layers: [cursor]
platforms: [backend]
cursor:
  file: backend
  globs: "backend/**"
---

# Backend - Spring Boot 4 (Kotlin)

## Stack
- Spring Boot 4.0.x, Kotlin 2.2+, Java 21
- Spring Security OAuth2 Client + JWT
- Spring Data JPA + Flyway migrations
- Jackson 3.x, JUnit Jupiter 6
- Local development database: PostgreSQL (`docker-compose.yml`); hosting is the project owner's choice (see the `deployment` skill, `.agents/skills/deployment/SKILL.md`)

## Structure
```
src/main/kotlin/{{ package_identifier | replace('.', '/') }}/
  bootstrap/    -> SecurityConfig, WebConfig, OAuth2Config, OpenApiConfig
    security/   -> JwtTokenProvider, JwtAuthenticationFilter, ApiAuthenticationEntryPoint
  shared/       -> Cross-cutting: exceptions, models, audit
    audit/      -> AuditableEntity (@MappedSuperclass with timestamps)
    exception/  -> ApiException hierarchy + GlobalExceptionHandler
    model/      -> ApiErrorResponse, PagedResponse
  modules/      -> Feature modules
    auth/       -> controller/, dto/, model/, repository/, service/
    transactions/ -> controller/, dto/, model/, repository/, service/
```

## Patterns
- Controller -> Service -> Repository -> Entity
- DTOs in `dto/` package, entities in `model/` - never expose entities
- Entities extend `AuditableEntity` for automatic timestamps
- Global exception handler returns `ApiErrorResponse`
- Pagination via `Pageable` -> `PagedResponse<T>`
- All endpoints require JWT except the public auth endpoints (`/auth/register`, `/auth/login`, `/auth/refresh`, and the OAuth callback when enabled)
- A missing, malformed or expired access token gets 401; an authenticated user without permission gets 403
- Emails are compared without regard to case: `normalizedEmail()` lower-cases them for storage and lookups
- Flyway migrations in `src/main/resources/db/migration/`
- Tests use MockK for service logic and `@SpringBootTest` with MockMvc for security and request-path behavior

## Commands
- `./gradlew bootRun` or `task backend:run`
- `./gradlew test` or `task backend:test`
- `./gradlew build -x test` or `task backend:build`
