---
name: web-conventions
description: "Conventions for the generated Next.js web apps: the sign-in and profile slice, the generated API client, the session cookie, tests and commands. Use when writing, extending or reviewing code under a web app folder, or when replacing the local development sign-in."
layers: [codex, claude-skill]
stacks: [nextjs-web]
codex:
  display_name: "Web Conventions"
  short_description: "Apply the Next.js slice conventions and its test setup"
  default_prompt: "Use @@invoke:web-conventions@@ when changing a web app of this project."
  implicit: true
claude-skill:
  user-invocable: false
---

# Web Conventions

Apply these rules whenever you change a web app of this workspace. Each web app is one `nextjs-web` app generated from the same pack, so the paths below are relative to the app's folder: {% for app in apps if app.stack == "nextjs-web" %}`{{ app.path }}/`{{ ", " if not loop.last }}{% endfor %}.

## Slice files

The pack generates one vertical slice and no example business features. Paths are inside the web app's folder:

- `app/sign-in/page.tsx` is the page labelled "Local development sign-in".
- `app/api/session/route.ts` is the route handler. `POST` asks the backend's local development identity for a token and keeps it in an httpOnly cookie; `DELETE` removes the cookie. Neither returns the token.
- `app/page.tsx` shows the signed-in user's profile from `GET /api/me`.
- `lib/api/client.ts` is the typed client of the shared OpenAPI contract.
- `lib/auth/session.ts` holds the cookie name and options.
- `lib/app-info.ts` holds the app's display name and `audience`. The audience is display text only: no route, check or permission reads it, and a label never enforces authorization. A separate app is the answer when audiences differ in deployment or security boundary.
- `tests/` holds the Vitest unit and component tests of all of the above.

## Rules

- Pages and layouts are Server Components. Use `"use client"` only for a form or button that needs it (`components/sign-in-form.tsx`, `components/sign-out-button.tsx`).
- The browser never calls the backend. Pages and route handlers call it from the server through the generated client, with the token from the session cookie.
- Never hand-write a fetch to a contract path. Add the operation to `shared/api-contracts/openapi.yml`, run `npm run generate:api` (or `task generate-clients` from the root), and call it through `createApiClient` in `lib/api/client.ts`. A path or field the contract lacks fails the typecheck. `lib/api/generated/` is generated and ignored by git.
- Keep the token in the httpOnly session cookie. Never put it in `localStorage`, a response body or a client component. Sign-in and sign-out reject requests from another origin.
- Read configuration on the server from `process.env`. `API_BASE_URL` is the only variable the slice reads; keep real values out of git.
- Versions come from `packs/versions.yml` of the Prism template. Do not add a dependency on a different major version of a pinned package; `package-lock.json` is committed and CI installs with `npm ci`.

## The local development sign-in

The sign-in is the contract's `POST /api/dev-identity/token`, which the backend serves only under its `local` profile and to loopback requests. It is not complete authentication and the app must never present it as such.

To replace it with the project's identity provider, follow `@@invoke:security-auth@@` for the backend side, then in each web app:

1. Replace the body of `POST` in `app/api/session/route.ts` (or add the provider's callback route) so it obtains a token from the provider, and keep the httpOnly cookie handling in `lib/auth/session.ts`.
2. Change `app/sign-in/page.tsx` and `components/sign-in-form.tsx` to the provider's sign-in, and remove the "Local development sign-in" label with the dev-identity call.
3. Update the tests in `tests/session-route.test.ts` and `tests/sign-in-page.test.tsx` to the new flow. They are the executable description of what the cookie must do.

## Tests and commands

- `npm test` runs Vitest with Testing Library (jsdom for components, `// @vitest-environment node` for route handlers). A route handler is tested by calling its exported function with a `Request`; a server page is tested by awaiting it and rendering the result with the session and API client mocked, as `tests/profile-page.test.tsx` does.
- A change is done when `npm run lint`, `npm run typecheck`, `npm test` and `npm run build` pass in the app's folder. The root `task lint` and `task test` run them for every web app.
- Update the app's `docs/guide.md` and `AGENTS.md` when the structure changes.
