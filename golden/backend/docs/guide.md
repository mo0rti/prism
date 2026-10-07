# Backend Guide - Prism Golden

## Tech Stack

- **Spring Boot 4.0.1** on **Kotlin 2.2.0**, **Java 21**, built with Gradle 8.14.3
- **Spring Security** as an OAuth2 resource server (bearer JWT), **Spring Data JPA** with **Flyway** migrations on **PostgreSQL**
- **Jackson 3.x** for JSON serialization
- **JUnit Jupiter 6**, **MockK** and **Testcontainers** for testing

`packs/versions.yml` of the Prism template pins these versions; the files of this app read them from there.

## Project Structure

```
backend/src/main/kotlin/com/example/prismgolden/backend/
├── BackendApplication.kt   # @SpringBootApplication entry point
├── bootstrap/
│   ├── SecurityConfig.kt                # every route needs a bearer JWT, except health and the two dev-identity routes
│   ├── DevIdentityConfig.kt             # local profile: in-memory signing key, JWT encoder and decoder
│   ├── DevIdentityGuard.kt              # local profile: startup fails next to a real identity provider
│   ├── properties/                      # configuration properties
│   └── security/                        # 401 entry point, the decoder of an app with no provider
├── modules/
│   ├── users/                           # GET /api/me: controller, dto, model, repository, service
│   └── devidentity/                     # POST /api/dev-identity/token and GET /api/dev-identity/jwks (local only)
└── shared/                              # audit, error, exception, model
```

Resources: `src/main/resources/application.yml` and the Flyway migrations in `db/migration/`.

## Run And Test

```bash
task db-up                  # at the repository root: the workspace's PostgreSQL
task backend:dev       # SPRING_PROFILES_ACTIVE=local ./gradlew bootRun, on port 8080
task backend:run       # ./gradlew bootRun with no profile
task backend:build     # ./gradlew build -x test
task backend:test      # ./gradlew test (needs Docker for Testcontainers)
task backend:lint      # ./gradlew check -x test
```

The package is `com.example.prismgolden.backend`. Configuration lives in `src/main/resources/application.yml`: the server port comes from `PORT` (default 8080), the database from `DATABASE_URL`, `DATABASE_USERNAME`, `DATABASE_PASSWORD` and `DATABASE_SCHEMA` (defaults match the workspace's `docker-compose.yml`).

## Identity

The slice signs in through a **local development identity** under the `local` profile, and validates JWTs as a resource server in every profile.

- `local`: `DevIdentityConfig` generates an RSA key in memory; `POST /api/dev-identity/token` signs a 15-minute token (`iss=prism-dev-identity`) for loopback requests. `GET /api/dev-identity/jwks` publishes the public key (no private member) so another local service, such as an agent service, verifies the tokens with no shared secret. `GET /api/me` accepts only those tokens. `DevIdentityGuard` stops startup when an identity provider is also configured.
- no profile: the token and JWKS routes do not exist (404). With `spring.security.oauth2.resourceserver.jwt.issuer-uri` and `spring.security.oauth2.resourceserver.jwt.audiences` (the audience of this API) set, Spring Boot validates your provider's tokens and the app also requires the audience (startup fails with an issuer and no audience; a token with a missing or foreign `aud` gets 401); with nothing set, `RejectingJwtDecoder` rejects every token.
- `GET /api/me` reads the token's `sub`, `email` and `name` claims. `UserService` creates the `users` row on the first call, so it keeps working unchanged with a real provider.

The dev identity is not authentication. The `security-auth` skill describes how to replace it.

## Persistence

Migrations are Flyway files `V<n>__<name>.sql` in `src/main/resources/db/migration/`; Hibernate only validates the schema (`ddl-auto: validate`). Tables live in the app's own schema (`DATABASE_SCHEMA`, default `backend`), so several backends can share one database. The database, its schema design and its hosting are yours to decide.

## Related Docs

- [Architecture Overview](../../docs/architecture.md) for system-wide constraints
- [API Conventions](../../docs/api/conventions.md) for URL, error, and versioning rules
- [Entities](entities/README.md) for the persisted domain model
