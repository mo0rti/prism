---
name: cursor-api-conventions
description: "The OpenAPI contract rules for shared/api-contracts: file location, naming, pagination, error format, authentication and HTTP methods."
layers: [cursor]
cursor:
  file: api-conventions
  globs: "shared/api-contracts/**"
---

# API Conventions

## OpenAPI Spec
- Location: `shared/api-contracts/openapi.yml`
- Version: OpenAPI 3.1
- Generate clients: `task generate-clients`

## Naming
- Paths: plural nouns, kebab-case when a name has several words (`/user-profiles`), under `/api/`
- JSON fields: camelCase (`createdAt`, `totalElements`)
- Path params: camelCase (`{userId}`)

## Pagination
All list endpoints use query params `page` (0-based) and `size` (default 20).
Response wraps items in:
```json
{
  "content": [...],
  "page": 0,
  "size": 20,
  "totalElements": 100,
  "totalPages": 5
}
```

## Error Format
```json
{
  "code": "NOT_FOUND",
  "message": "Resource not found",
  "details": null
}
```
`details` is an optional object, for example the field and reason of a validation error.

## Auth
- Public endpoints: `/actuator/health` and `POST /api/dev-identity/token` (dev only, `x-prism-dev-only`); `GET /api/me` needs a token
- All other endpoints require `Authorization: Bearer {token}`
- 401 for missing/invalid token, 403 for insufficient permissions

## HTTP Methods
- GET: read (200)
- POST: create (201)
- PUT: full update (200)
- PATCH: partial update (200)
- DELETE: remove (204)
