# Web Guide - Prism Golden

## Tech Stack

- **Next.js 16.4.0** (App Router) on **React 19.3.0**, **TypeScript 5.9.3** and Node 22
- **openapi-typescript** and **openapi-fetch** for the client of `shared/api-contracts/openapi.yml`
- **Vitest 5.0.3** with Testing Library for unit and component tests
- **ESLint** with the Next.js configuration

`packs/versions.yml` of the Prism template pins these versions; `package.json` and the committed `package-lock.json` follow it.

## Purpose

`web/` is a web app for B2C. The pack generates the project structure, one compiling vertical slice and its tests, and no example business features. The audience sets display text only: no route, check or permission reads it.

## Project Structure

```text
web/
├── app/
│   ├── layout.tsx              # Header with the display name and audience
│   ├── page.tsx                # GET /api/me
│   ├── sign-in/page.tsx        # "Local development sign-in"
│   └── api/session/route.ts    # POST signs in (httpOnly cookie), DELETE signs out
├── components/                 # Sign-in form, sign-out button, profile card
├── lib/
│   ├── api/                    # client.ts (contract client), config.ts, generated/ (git-ignored types)
│   ├── auth/session.ts         # Session cookie name and options
│   └── app-info.ts             # Display name and audience
└── tests/                      # Vitest tests
```

## Run And Test

```bash
task web:install    # npm ci
task web:dev        # npm run dev, on port 3000
task web:lint       # npm run lint
task web:typecheck  # npm run typecheck
task web:test       # npm test
task web:build      # npm run build
task web:generate-api
```

Copy `.env.example` to `.env.local` first. `API_BASE_URL` is the backend's address and the only runtime variable.

## Sign-in And Session

1. The sign-in page posts the form to `POST /api/session`.
2. The route handler calls the backend's `POST /api/dev-identity/token` with the generated client and stores the token in the `web_session` cookie: httpOnly, `SameSite=Lax`, `Secure` on HTTPS. The route relays a caller into an identity that exists for this machine only, so it answers only when `LOCAL_DEV_SIGNIN=1` (`.env.development`, which `next dev` loads and `next build` and `next start` do not), only to a request that carries this app's own `Origin`, and only to a request from this machine; the dev server and `npm start` listen on 127.0.0.1 only.
3. `app/page.tsx` reads the cookie on the server and calls `GET /api/me` with the token. A missing cookie or a 401 sends the visitor to the sign-in.
4. `DELETE /api/session` expires the cookie; it needs the same `Origin` header.

The backend serves the dev identity only under its `local` profile and to loopback requests. It is not complete authentication: replace it with your identity provider before anything ships (see the `web-conventions` and `security-auth` skills).

## Related Docs

- [Architecture Overview](../../docs/architecture.md) for system-wide constraints
- [API Conventions](../../docs/api/conventions.md) for URL, error, and versioning rules
