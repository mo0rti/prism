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
```
