---
name: ios-contract-alignment
description: "Contract alignment rules for the iOS API client: models, endpoints, the token header and the dev identity. Use when adding or reviewing request or response shapes, API endpoints or auth-boundary code in the generated iOS apps."
---

# iOS Contract Alignment

Use this skill when backend-facing iOS code changes. Paths are relative to the iOS app's folder.

## Slice files

Paths are inside the iOS app's folder (`mobile-ios/`).

- `Sources/Networking/APIEndpoint.swift` - the path of each operation
- `Sources/Networking/APIClient.swift` - the `APIClient` protocol and `URLSessionAPIClient`
- `Sources/Models/Models.swift` - the request and response models
- `Sources/Info.plist` - carries `API_BASE_URL`
- `project.yml` - sets `API_BASE_URL` per build configuration
- `Tests/APIClientTests.swift` - covers request building and response reading

## Role boundary

- Own request and response shapes, endpoint paths, the API client and the auth-boundary wiring.
- Defer screen structure and general workflow to companion iOS skills.

## Rules

- `shared/api-contracts/openapi.yml` is the source of truth. The slice calls two operations, `createDevToken` (`POST /api/dev-identity/token`) and `getMe` (`GET /api/me`).
- The iOS client is hand-written and kept to the contract. Add an operation to the contract first, then its path to `Sources/Networking/APIEndpoint.swift`, its method to the `APIClient` protocol and `URLSessionAPIClient` in `Sources/Networking/APIClient.swift`, and its models to `Sources/Models/Models.swift`. Every path in `APIEndpoint.swift` must be one the contract defines.
- Request building and response reading are static functions of `URLSessionAPIClient` (`makeRequest`, `decode`), so `Tests/APIClientTests.swift` covers them without a network. Extend those tests with every operation you add.
- The base URL is `API_BASE_URL` from `Sources/Info.plist`, set per build configuration in `project.yml`; endpoint paths are the contract's full paths (`/api/me`), so the base URL has no path of its own.
- The bearer token goes into the `Authorization` header in `makeRequest` and nowhere else. Never log it, print it, put it in a URL or an error message.
- `getMe` uses the contract's global bearer security. A 401 ends the session: `ProfileViewModel` clears the token and returns to the sign-in. Add refresh-and-retry only with a real identity provider, in the transport boundary (`URLSessionAPIClient`), with one in-flight refresh that concurrent 401 responses await.
- The dev identity is `x-prism-dev-only` in the contract. Its 404 means the backend does not run its `local` profile, and its 403 means the request was not loopback. The app maps them to `APIError.devIdentityUnavailable` and `APIError.devIdentityRefused`, which tell the person what to do. Do not weaken the backend's loopback policy to make a device work.
- Keep client error flow consistent: `URLSessionAPIClient` maps transport and status failures to `APIError`, view models map errors into screen state, and views render that state.
- If the project starts using covered required-reason APIs or adds third-party SDKs that declare privacy usage, add `PrivacyInfo.xcprivacy` and keep it current rather than hiding that work inside feature code.

## Reference files

Load only the reference file the task needs:

- `references/privacy-manifest.md` for required-reason API categories, third-party SDK checks, and `PrivacyInfo.xcprivacy` update guidance

## Cross-check sources

- Use `shared/api-contracts/openapi.yml` as the primary source for endpoint shapes.
- Use the backend app's `modules/devidentity` and `modules/users` code to confirm behavior when the spec is ambiguous.
- Use `mobile-android/` to confirm parity expectations when iOS should mirror Android behavior.


## Validation

- Run `task <app-id>:test-unit` and `task <app-id>:build` on Mac after contract changes.
- Read the app's `AGENTS.md` when auth, token or session behavior changes.
