# Web Runbook - Prism Golden

What an operator needs to know about this web app. The sections under "Known from the code" come from the generated code and stay true until the code changes. Prism deploys nothing, so everything about hosting is an **Unknown:** item until the team records it here. Replace each item with the fact when it is decided.

## Known from the code

### Health

- The app has no health route. Whether it is up is whether `GET /` answers: the page redirects to the sign-in while no session cookie is set. The profile page shows an error when the backend does not answer.
- The app depends on the backend that serves `shared/api-contracts/openapi.yml`. When the web app misbehaves, check the backend's health first.

### Logs

- `next dev` and `next start` write to standard output and standard error. The pack configures no log file, no log shipper and no error reporting.
- The sign-in route handler (`app/api/session/route.ts`) calls the backend server-side and names the cause of a failure: the local development sign-in runs only with `npm run dev` (404 in a production build), the request is not from this app or this machine (403), or the backend is unreachable or issued no token (502).

### Configuration

| Variable | Meaning |
|---|---|
| `API_BASE_URL` | The base URL of the backend. Set in `.env.local` locally (see `.env.example`); generated for http://localhost:8080. |

The session is an httpOnly cookie that holds the backend's token. The browser never calls the backend itself.

### Run it locally

```bash
cd web
cp .env.example .env.local
npm ci
npm run dev                 # http://localhost:3000
```

`npm run build` then `npm start` serves a production build on `127.0.0.1:3000`.

### Release artifact

- `npm run build` produces the `.next` output. The pack ships no `Dockerfile` and no hosting configuration.
- `.github/workflows/web.yml` installs, lints, type-checks, tests and builds on every change. It deploys nothing.

## Unknown

- **Unknown:** Where the app runs (platform, region) and how the production build is served; `npm start` binds to loopback only.
- **Unknown:** How a release reaches that place, and who does it.
- **Unknown:** How to roll back a release, and how long it takes.
- **Unknown:** Where the logs are collected, how uptime is watched and who is alerted.
- **Unknown:** The production value of `API_BASE_URL` and how the app reaches the backend.
- **Unknown:** The production sign-in: the local development sign-in is replaced by the team's identity provider.
- **Unknown:** Who is on call for this app and how to reach them.
