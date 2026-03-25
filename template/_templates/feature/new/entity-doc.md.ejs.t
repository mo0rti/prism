---
to: "<%= entity ? 'backend/docs/entities/' + h.changeCase.param(entity) + '.md' : null %>"
---
# Entity: <%= h.changeCase.pascal(entity) %>

Part of the **<%= h.changeCase.title(name) %>** feature.

## Fields

| Field | Type | Nullable | Default | Constraints |
|-------|------|----------|---------|-------------|
| id | Long/UUID | No | auto | Primary key |
| createdAt | Instant | No | now | Immutable |
| updatedAt | Instant | No | now | Auto-updated |
| _TODO_ | | | | |

## Relationships

- _TODO: Define relationships (e.g., belongs to User, has many Reviews)_

## Indexes

- Primary key on `id`
- _TODO: Add indexes for common queries_

## Validation Rules

- _TODO: Define validation rules_

## Business Rules

- _TODO: Define business rules for this entity_
