# Backend Entities

Use this directory to understand the persisted domain model of Backend.

## Entity Docs

- [User](user.md) - the profile of a signed-in user, created on the first call to `GET /api/me`

## Notes

- `_template.md` is the authoring template for adding entity docs
- entity docs should stay aligned with JPA models, migrations, DTO exposure, and OpenAPI

## Related Docs

- [Guide](../guide.md) for structure and conventions
- [Architecture Overview](../../../docs/architecture.md) for system-level boundaries
- [API Conventions](../../../docs/api/conventions.md) for public contract and error rules
