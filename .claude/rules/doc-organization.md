---
description: Documentation organization convention - project-wide vs platform-specific docs
paths:
  - "template/docs/**"
  - "template/*/docs/**"
  - "template/*/CLAUDE.md.jinja"
  - "template/*/AGENTS.md.jinja"
---

# Documentation Organization

## Convention

- **`template/docs/`** — Project-wide documentation (features, API conventions, advisory board, architecture). Relevant to all platforms.
- **`template/{platform}/docs/`** — Platform-specific technical docs (architecture, file structure, networking, design system, etc.). Only relevant to that platform.

## Rules

- Entity docs (database models, migrations) belong in `template/backend/docs/entities/` — they describe database implementation details.
- Deployment docs (Azure setup, infra) belong in `template/backend/docs/` — tied to backend infrastructure.
- Platform guides live inside their platform: `template/mobile-android/docs/guide.md.jinja`, not `template/docs/`.
- Feature docs stay in `template/docs/features/` — features span multiple platforms.
- When adding docs for a new platform, create `template/{platform}/docs/` with at least a `guide.md.jinja`.

## Why This Matters

Platform-specific docs are auto-excluded by copier.yml `_exclude` when that platform isn't selected. Keeping them inside the platform directory means no extra exclusion rules needed.
