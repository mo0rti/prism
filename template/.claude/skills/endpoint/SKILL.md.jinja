---
name: endpoint
description: Guide for creating a new REST API endpoint in the backend
disable-model-invocation: true
argument-hint: "[endpoint description]"
---

Create a new REST API endpoint for $ARGUMENTS.

Steps:

1. **Determine the module** - identify which domain module under `modules/<domain>/` this belongs to. If the module doesn't exist, create the full package structure (controller, dto, model, repository, service).
2. **Create or update the controller** in `<domain>/controller/` - follow `@RestController`, `@RequestMapping("/api/v1/<domain>")`, `@Tag`, `@Operation` conventions.
3. **Create request/response DTOs** in `<domain>/dto/` - data classes, separate request from response when shapes differ.
4. **Create or update the service** in `<domain>/service/` - `@Transactional` for writes, `@Transactional(readOnly = true)` for reads. Throw `ApiException` subclasses for errors.
5. **Create entity and repository** if new data storage is needed - follow `jpa-kotlin-patterns` skill for entity structure.
6. **Create Flyway migration** if new database tables/columns are needed - follow `database-migrations` skill conventions.
7. **Update OpenAPI spec** - add the endpoint to `shared/api-contracts/openapi.yml`.
8. **Consider**: security (public vs authenticated), validation (`@Valid`), pagination for list endpoints.

Follow the project's spring-boot-conventions, security-auth, and error-handling skills for patterns.
