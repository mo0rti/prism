---
name: spring-boot-conventions
description: Spring Boot 4 and Kotlin conventions for this backend. Use when writing or reviewing controllers, services, DTOs, or module structure under `backend/`. For JPA, security/auth, or API error semantics, defer to the more specialized project skills.
---

# Spring Boot Conventions

Use this skill for repository-wide backend structure and layer rules.

## Role Boundary

- Use this skill for general module, controller, service, and DTO conventions.
- Use `$security-auth` for route exposure, JWT handling, and auth behavior.
- Use `$error-handling` for exception taxonomy and API error responses.

## Module Structure

Each domain module lives under `modules/<domain>/` with subpackages such as:

```text
modules/<domain>/
  controller/
  dto/
  model/
  repository/
  service/
```

Not every module needs every subpackage, but keep dependencies one-way:

- `controller` depends on `service`
- `service` depends on `model` and `repository`
- `model` stays free of web and DTO dependencies
- controllers never call repositories directly

## Controller Rules

- Keep endpoints under `/api/v1/`.
- Return `ResponseEntity<T>` from controller methods.
- Add `@Operation(summary = ...)` on each endpoint.
- Add `@Tag(name = ...)` at the class level for grouping.
- Use `UUID` path variables for entity identifiers.

## Service Rules

- Use `@Transactional` on writes and `@Transactional(readOnly = true)` on reads.
- Keep database transactions narrow; do not hold them open across outbound HTTP, OAuth, or other network calls.
- Convert between entities and DTOs in the service or a dedicated mapper, never in controllers.
- Throw domain-specific exceptions and let the global exception layer map them to HTTP responses.
- Avoid self-invocation of transactional methods in the same class.
- Do not rely on `@Transactional` on private methods; Spring proxy-based transaction management will not intercept them.

## DTO Rules

- Keep DTOs in `dto/`.
- Keep each DTO class in its own Kotlin file so type ownership, reuse, navigation, and refactoring remain predictable as modules grow.
- Never serialize entities directly to JSON.
- Use separate request and response DTOs when shapes differ.
- Prefer summary DTOs for list views and fuller DTOs for detail views.

## Mapper Rules

- Default to manual Kotlin mapping functions for pure entity/DTO transformations.
- Prefer top-level extension functions in a dedicated mapper file when no collaborators are required.
- Keep mappers pure: no repository access, permission checks, state transitions, or other business rules.
- Use a Spring-managed mapper class only when mapping genuinely needs injected collaborators.
- Preserve domain enums in response DTOs when the API contract owns those enums; do not flatten them to raw strings without a concrete contract reason.

## Internal Model Rules

- Put reusable non-entity domain value objects and normalized integration models in `model/` unless a dedicated subpackage makes the boundary clearer.
- Do not treat `service/` as a catch-all for helper data classes.
- Use explicit names such as `*Profile`, `*Details`, or `*State` for internal models so they are not confused with API DTOs or persistence entities.

## Configuration Rules

- Prefer typed `@ConfigurationProperties` classes for medium-to-large backend configuration.
- Group config classes under a dedicated package such as `bootstrap/properties/`.
- Keep environment-backed configuration out of controllers and services except through injected typed config objects.
- Reserve `@Value` for small one-off wiring cases; do not scatter repeated property keys across the codebase.

## File Organization Rules

- Keep each entity, enum, and reusable value object in its own Kotlin file.
- Do not group multiple DTO classes in a single `*Dtos.kt` file.
- Do not keep reusable enums inside an entity file; place them in dedicated files under `model/`.

## Forbidden Patterns

- `entity -> DTO` imports
- `controller -> repository` imports
- `runBlocking` in MVC controllers
- Jackson annotations on JPA entities
