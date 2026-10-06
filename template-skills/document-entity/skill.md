---
name: document-entity
description: "Document a backend data entity in `backend/docs/entities/`. Use when adding a new entity doc or materially updating an existing one with fields, relationships, validation rules, business logic, and database notes."
layers: [codex, command]
codex:
  display_name: "Document Entity"
  short_description: "Create or update backend entity documentation"
  default_prompt: "Use @@invoke:document-entity@@ to create or update a backend/docs/entities page and keep architecture and feature docs aligned."
  implicit: false
---

Document a data entity for {{ project_name }}.

Use this skill to create or update one backend entity documentation page.

## Usage

`@@invoke:document-entity@@`

If the entity name and fields are not already provided, ask the user for them first.

## Workflow

1. Ask for the entity name and fields if they were not provided
2. **Create or update the entity doc**: create `backend/docs/entities/{entity-name}.md` using the template at `backend/docs/entities/_template.md`. Fill in:
   - entity name and description
   - all fields with types, constraints, and defaults
   - relationships to other entities
   - validation rules and business logic
   - database notes and indexes
3. **Update the architecture doc**: if this is a new entity, add it to the entity list in `docs/architecture.md`
4. **Review existing features**: check `knowledge/wiki/features/` for feature pages that reference the entity
5. If feature-page updates appear necessary, show them as a separate proposed follow-up and wait for confirmation before writing those wiki changes

## Template reference

See `backend/docs/entities/_template.md` for the expected format. Key sections:

- **Fields**: name, type, nullable, default, constraints
- **Relationships**: foreign keys, one-to-many, many-to-many
- **Indexes**: performance-critical queries
- **Business Rules**: validation, computed fields, lifecycle hooks

## Rules

- write-capable skill
- ask for missing entity details instead of inventing them
- use the entity template structure unless the project already has an established variant
- if feature pages need updates, keep them aligned with the documented entity shape but confirm those wiki writes separately
- do not silently skip architecture updates for new entities

## Output behavior

Return:

- entity name and target doc path
- whether the entity doc was created or updated
- architecture doc changes if any
- any proposed or applied feature-page updates to stay aligned

## Error and stop conditions

- if the entity name is missing, ask for it before writing
- if the field list is incomplete, ask for clarification instead of inventing schema details
