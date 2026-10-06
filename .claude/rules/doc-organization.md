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

- **`template/docs/`** — Project-wide reference documentation (architecture, API conventions, deployment guides). For humans. Does NOT contain feature specs or advisory board config.
- **`template/knowledge/wiki/`** — AI-facing product wiki. Feature specs, app requirements, advisory board, design decisions. This is the source of truth for what to build.
- **`template/{platform}/docs/`** — Platform-specific technical docs of a full sample (architecture, file structure, networking, design system, etc.). Only relevant to that platform.
- **`packs/<stack>/{{ app_path }}/docs/`** — The technical docs of an app a pack generates, under the app's own path.

## Rules

- Entity docs (database models, migrations) belong in the backend pack's docs, `packs/spring-backend/{{ app_path }}/docs/` — they describe database implementation details.
- Deployment docs are the generated `deployment` skill, not template docs.
- Platform guides live inside their platform: `template/mobile-android/docs/guide.md.jinja` for a sample, `packs/<stack>/{{ app_path }}/docs/guide.md.jinja` for a pack, not `template/docs/`.
- **Feature specs for generated projects live in `knowledge/wiki/features/`** — this is the Prism wiki, the source of truth for what to build. Do not put feature specs in `template/docs/`.
- When adding docs for a new platform, create `template/{platform}/docs/` with at least a `guide.md.jinja`.

## Why This Matters

Sample docs are auto-excluded by copier.yml `_exclude` when that sample isn't generated, and a pack's docs exist only for the apps that scaffold it. Keeping docs inside the app's directory means no extra exclusion rules needed.
