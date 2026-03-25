# Entity: [Name]

## Description
Brief description of what this entity represents in the system.

## Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | UUID | Yes | Primary key |
| createdAt | DateTime | Yes | Record creation timestamp |
| updatedAt | DateTime | Yes | Last update timestamp |

## Relationships

- **belongs to** [OtherEntity](other-entity.md) - description of relationship
- **has many** [AnotherEntity](another-entity.md) - description of relationship

## Validation Rules

- Field constraints, format requirements, business rules

## Business Logic

- Key behaviors, state transitions, computed fields

## Database

- **Table name**: `table_name`
- **Indexes**: list any important indexes
- **Migration**: `V{N}__description.sql`

## API Representation

```json
{
  "id": "uuid",
  "createdAt": "2024-01-01T00:00:00Z",
  "updatedAt": "2024-01-01T00:00:00Z"
}
```
