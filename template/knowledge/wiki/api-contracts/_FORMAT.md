# API contract page format

Use this format for every file in `wiki/api-contracts/`. Filename: `F-XXX.md`.

```markdown
---
feature-id: F-XXX
version: 1
status: draft | agreed | implemented
---

## Endpoints
For each endpoint: method, path, request body, response body, error codes.

## Data models
Shared data shapes that backend produces and clients consume.

## Authentication requirements
Auth method, required scopes or roles.

## Notes
Design decisions, backwards-compatibility concerns.
- **Decided:** [a decision about this contract] ([ADR-001](../decisions/ADR-001-slug.md))
```

`design-handoff` creates this page at `status: agreed` when the feature's API surface
declares API work; `dev-done` moves it to `implemented`. List each endpoint as
`METHOD /path` and define only data models that the API surface or an endpoint names.
