---
description: Documentation organization convention - project-wide vs platform-specific docs
paths:
  - "template/docs/**"
  - "packs/*/**/docs/**"
  - "packs/*/**/CLAUDE.md.jinja"
  - "packs/*/**/AGENTS.md.jinja"
---

# Documentation Organization

## Convention

- **`template/docs/`** — Project-wide reference documentation (architecture, API conventions, deployment guides). For humans. Does NOT contain feature specs or advisory board config.
- **`template/knowledge/wiki/`** — AI-facing product wiki. Feature specs, app requirements, advisory board, design decisions. This is the source of truth for what to build.
- **`packs/<stack>/{{ app_path }}/docs/`** — The technical docs of an app a pack generates, under the app's own path.

## Rules

- Entity docs (database models, migrations) belong in the backend pack's docs, `packs/spring-backend/{{ app_path }}/docs/` — they describe database implementation details.
- Deployment docs are the generated `deployment` skill, not template docs.
- Platform guides live inside their app: `packs/<stack>/{{ app_path }}/docs/guide.md.jinja`, not `template/docs/`.
- **Feature specs for generated projects live in `knowledge/wiki/features/`** — this is the Prism wiki, the source of truth for what to build. Do not put feature specs in `template/docs/`.
- When adding docs for a new platform, create `packs/<stack>/{{ app_path }}/docs/` with at least a `guide.md.jinja`.

## Why This Matters

A pack's docs exist only for the apps that scaffold it. Keeping docs inside the app's directory means no extra exclusion rules needed.
