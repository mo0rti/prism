# Token Refresh Patterns

Use this reference when a project needs silent token refresh instead of the default clear-tokens-and-return-to-login baseline.

## Core rule

- Keep refresh-and-retry orchestration at the transport boundary in `APIClient` or another dedicated auth transport helper.

## Simultaneous-401 race

- Multiple requests can fail with `401` at the same time.
- A naive implementation lets each failing request call `refreshToken()` independently.
- Correct behavior is one in-flight refresh operation that peer requests await before deciding whether to retry or fail.

## Concurrency shape

- Prefer actor-owned coordination for refresh state.
- Store the in-flight refresh task inside the coordinating actor so concurrent callers can await the same task result.
- Clear the in-flight state when the refresh succeeds or fails.

## Retry boundary

- Retry only after a successful refresh updates token storage.
- If refresh fails, clear tokens once, surface the unauthorized state, and let the app-level auth gate route back to login.
- Do not scatter retry loops across repositories or ViewModels.
