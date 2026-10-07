# Generate API Clients

Generate typed API clients from the OpenAPI specification.

Use this skill after changing the OpenAPI contract or anything derived from it.

## What this does

Reads `shared/api-contracts/openapi.yml` and generates typed client code for each platform: openapi-generator for the backend, and `openapi-typescript` for each web app. The Android and iOS clients are hand-written: an Android app's `ApiContractTest` fails when its client and the contract disagree, and an iOS app's client is kept to the contract with `/ios-contract-alignment`.

## Workflow

1. Validate the contract with `task validate-api`.
2. Run `task generate-clients`.
3. Verify the generated output for the relevant platforms only:
- `task backend:build`
- `task web:typecheck` and `task web:test`
- `task mobile-android:test` (its `ApiContractTest` checks the hand-written client against the contract)
- `task mobile-ios:build` (Mac only)

4. If generation or verification fails, report the first blocking error and stop before hand-editing generated code.

## Generated output

- **TypeScript** (web): `web/lib/api/generated/schema.d.ts`, written by `openapi-typescript` (`task web:generate-api`) and ignored by git
- **Kotlin** (mobile-android): not generated; edit `mobile-android/app/src/main/kotlin/com/example/prismgolden/mobileandroid/data/api/` by hand (`ApiService.kt`, `ApiModels.kt`) and extend `ApiContractTest`
- **Swift** (mobile-ios): no generated client. `mobile-ios/Sources/Networking/` is hand-written and kept to the contract with `/ios-contract-alignment`

## When to run

- After adding or modifying endpoints in `openapi.yml`
- After changing request/response schemas
- After running `/add-endpoint`

## Output

- The platforms whose clients were regenerated
- Whether validation and build verification passed
- Any manual follow-up still required
