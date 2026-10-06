---
name: generate-clients
description: "Regenerate typed API clients from `shared/api-contracts/openapi.yml` after contract changes. Use when endpoints, schemas, enums, auth payloads, or API conventions change and downstream generated clients must stay in sync."
layers: [codex, command]
codex:
  display_name: "Generate API Clients"
  short_description: "Regenerate typed clients from OpenAPI"
  default_prompt: "Use @@invoke:generate-clients@@ to regenerate typed API clients after OpenAPI changes."
  implicit: true
---

# Generate API Clients

Generate typed API clients from the OpenAPI specification.

Use this skill after changing the OpenAPI contract or anything derived from it.

::: only codex
This skill intentionally allows implicit invocation because it is deterministic code
generation and verification, not a product-wiki lifecycle state transition.
:::

## What this does

Reads `shared/api-contracts/openapi.yml` and generates typed client code for each platform using openapi-generator.

## Workflow

1. Validate the contract with `task validate-api`.
2. Run `task generate-clients`.
3. Verify the generated output for the relevant platforms only:
{% for app in apps if app.stack == "spring-backend" %}- `task {{ app.id }}:build`
{% endfor %}{% if "web-user-app" in app_ids %}- `task web-user-app:build`
{% endif %}{% if "web-admin-portal" in app_ids %}- `task web-admin-portal:build`
{% endif %}{% if "android-compose" in stacks %}- `task mobile-android:build`
{% endif %}{% if "ios-swiftui" in stacks %}- `task mobile-ios:build` (Mac only)
{% endif %}
4. If generation or verification fails, report the first blocking error and stop before hand-editing generated code.

## Generated output

{% if "web-user-app" in app_ids or "web-admin-portal" in app_ids %}- **TypeScript** (web-user-app + web-admin-portal): `web-user-app/src/lib/api/generated/`, `web-admin-portal/src/lib/api/generated/`
{% endif %}{% if "android-compose" in stacks %}- **Kotlin** (Android): `mobile-android/app/src/main/kotlin/.../data/remote/generated/`
{% endif %}{% if "ios-swiftui" in stacks %}- **Swift** (iOS): `mobile-ios/{{ project_slug }}/Data/Network/Generated/`
{% endif %}
## When to run

- After adding or modifying endpoints in `openapi.yml`
- After changing request/response schemas
::: only command
- After running `@@invoke:add-endpoint@@`
:::

## Output

- The platforms whose clients were regenerated
- Whether validation and build verification passed
- Any manual follow-up still required
