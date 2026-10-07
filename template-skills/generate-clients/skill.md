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

Reads `shared/api-contracts/openapi.yml` and generates typed client code for each platform: openapi-generator for the backend and the iOS app, and `openapi-typescript` for each web app. An Android app's client is hand-written, and its `ApiContractTest` fails when the client and the contract disagree.

## Workflow

1. Validate the contract with `task validate-api`.
2. Run `task generate-clients`.
3. Verify the generated output for the relevant platforms only:
{% for app in apps if app.stack == "spring-backend" %}- `task {{ app.id }}:build`
{% endfor %}{% for app in apps if app.stack == "nextjs-web" %}- `task {{ app.id }}:typecheck` and `task {{ app.id }}:test`
{% endfor %}{% for app in apps if app.stack == "android-compose" %}- `task {{ app.id }}:test` (its `ApiContractTest` checks the hand-written client against the contract)
{% endfor %}{% if "ios-swiftui" in stacks %}- `task mobile-ios:build` (Mac only)
{% endif %}
4. If generation or verification fails, report the first blocking error and stop before hand-editing generated code.

## Generated output

{% for app in apps if app.stack == "nextjs-web" %}- **TypeScript** ({{ app.id }}): `{{ app.path }}/lib/api/generated/schema.d.ts`, written by `openapi-typescript` (`task {{ app.id }}:generate-api`) and ignored by git
{% endfor %}{% for app in apps if app.stack == "android-compose" %}- **Kotlin** ({{ app.id }}): not generated; edit `{{ app.path }}/app/src/main/kotlin/{{ package_identifier | replace('.', '/') }}/{{ app.id | replace('-', '') }}/data/api/` by hand (`ApiService.kt`, `ApiModels.kt`) and extend `ApiContractTest`
{% endfor %}{% if "ios-swiftui" in stacks %}- **Swift** (iOS): `mobile-ios/{{ project_slug }}/Data/Network/Generated/`
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
