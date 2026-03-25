---
name: platform-builder
description: Guide the implementation of a new platform template (web, admin) following established patterns from completed platforms. Triggers when building Phase 3B or 3C.
---

# Platform Builder

When implementing a new platform template, follow the patterns established by completed platforms and the specification in PLAN.md.

## How to Execute

1. **Read the spec** — Load the relevant Phase 3 section from `PLAN.md` for the target platform.

2. **Study reference platforms** — Read completed platform templates to understand patterns:
   - `template/backend/` — Spring Boot patterns, Jinja usage, CLAUDE.md structure
   - `template/android/` — MVVM patterns, feature structure, Hilt DI
   - `template/ios/` — MVVM patterns mirroring Android, SwiftUI conventions

3. **Create the platform directory** — Build `template/{platform}/` with all files listed in the PLAN.md spec. For each file:
   - Add `.jinja` suffix if it contains any Jinja2 expressions
   - Use `{{ project_name }}`, `{{ project_slug }}`, `{{ package_identifier }}` for project identity
   - Use `{% if "provider" in auth_methods %}` for conditional auth provider code
   - Cloud provider (Azure) and web hosting (Cloudflare) are hardcoded — no conditionals needed

4. **Create platform AI context** — Create `CLAUDE.md.jinja` and `AGENTS.md.jinja` for the platform following the style of existing platform context files.

5. **Update cross-cutting files**:
   - `template/Taskfile.yml.jinja` — add platform tasks
   - `template/CLAUDE.md.jinja` — add to architecture map
   - `template/AGENTS.md.jinja` — mirror changes
   - `template/.cursor/rules/{platform}.mdc.jinja` — add platform rule
   - `template/.github/workflows/{platform}.yml.jinja` — add CI/CD workflow
   - `template/_templates/` — add Hygen generators if applicable

6. **Update copier.yml** if needed — no changes typically needed since platforms are already defined.

7. **Update PLAN.md** — Mark the phase as Done in Build Progress.

## When to Trigger

- User asks to build or implement a platform template (especially web or admin)
- User references Phase 3B or Phase 3C
- User says "let's build the web template" or similar
