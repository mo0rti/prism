# Platform requirements page format

Use this format for every file in `wiki/platform-requirements/`. Filename: `F-XXX-[platform].md`.

```markdown
---
feature-id: F-XXX
platform: backend | mobile-android | mobile-ios | web-user-app | web-admin-portal
status: pending | in-progress | done
---

## What to build
Specific, actionable description of what this platform must implement.
Written for the AI agent working in this platform's directory.

## Technical constraints
Platform-specific constraints, existing patterns to follow, library choices.

## Design reference
Link to design/F-XXX-[slug].md for UI platforms. Not applicable for backend.

## API contract reference
Link to api-contracts/F-XXX.md. List endpoints or data shapes this platform consumes/produces.

## Acceptance criteria
Platform-specific done conditions.

## Dependencies
Other feature IDs or platform-requirement files that must complete first.
```
