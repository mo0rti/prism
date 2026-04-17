# iOS Navigation Architecture

Use this reference for route ownership, app-level navigation structure, and when to use stacks, sheets, tabs, or split views.

## Ownership

- `Navigation/Route.swift` owns route definitions.
- `Navigation/AppRouter.swift` owns top-level auth gating and app-entry flow selection.
- Feature screens and shared UI should not invent separate global router abstractions by default.

## Default baseline

- Use `NavigationStack` for most iPhone-first flows.
- Keep route values explicit and type-safe.
- Use sheets for contained tasks that should not deepen the primary back stack.
- Use tabs only for stable top-level product areas.

## Multi-column guidance

- `NavigationSplitView` is an opt-in pattern for iPad or regular-width information-dense flows.
- Do not use it by default for simple phone-first CRUD, auth, or detail navigation.

## Auth boundary

- Top-level auth gating belongs in `AppRouter`.
- When auth state becomes invalid, the default baseline is to return the app to login flow rather than inventing per-screen fallback behavior.
- The app-level auth gate should react to token clearing and drive the transition back to login. Do not make individual feature screens own unauthorized routing.
- Keep stable accessibility identifiers on top-level screens and auth-boundary controls so XCUITests can observe router-driven transitions.

## Deep links and restoration

- Add deep-link and restoration logic only when the product needs it.
- Keep state predictable and close to the route surface.
- Do not add a coordinator layer solely to support future possibilities.
