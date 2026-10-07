---
name: deployment
description: Deploy the generated stacks. Worked examples for the backend container on Azure Container Apps and the web apps on Cloudflare Workers through OpenNext, plus notes on mobile store releases. Use when the user asks to deploy, host, release, add a deploy job to CI or choose a cloud. The cloud choice, secrets and deployment belong to the user and their agent.
---

# Deployment

This project does not choose a cloud, hold credentials or deploy anything. The generated CI builds and tests only. The `references/` folder of this skill holds the scripts and configuration of a worked example for one choice per stack. Treat them as a starting point to adapt, not as the project's deployment.

## Ownership

- The user and their agent own the cloud choice, the secrets and the deployment. Prism owns neither.
- Ask which hosting the user wants before running or copying anything. If it is not Azure Container Apps or Cloudflare, use the examples only as a pattern.
- Record the choice as a decision page once it is settled (`knowledge/wiki/decisions/`, format in its `_FORMAT.md`).
- Never run a script against a cloud account, create a secret or push an image without the user's explicit go-ahead for that account.
- Never commit a secret. Keep credential files out of git before creating them.

## What The Project Provides

- `backend/Dockerfile`: a multi-stage image that builds the Spring Boot jar with the Gradle wrapper, exposes the app's port and checks `/actuator/health`.
- `docker-compose.yml`: local development only, the backend apps with PostgreSQL. It sets no Spring profile and is not a production definition.
- Backend settings come from environment variables: `DATABASE_URL`, `DATABASE_USERNAME`, `DATABASE_PASSWORD` (or the `SPRING_DATASOURCE_*` equivalents; the app keeps its tables in its own database schema, named after its ID unless overridden) and `SPRING_SECURITY_OAUTH2_RESOURCESERVER_JWT_ISSUER_URI` for the identity provider. `.env.example` lists the local database values.
- The backend holds no JWT secret. Its `local` Spring profile enables a development identity and must never run in a deployed environment; replace it with your identity provider first (`security-auth` skill).
- Web apps that pass `npm ci`, `npm run lint`, `npm run typecheck`, `npm test` and `npm run build` with no hosting files. `API_BASE_URL` is their only runtime variable; each app's `.env.example` lists the local value.
- Mobile apps that CI builds and tests; they carry no release job and no signing material.
- Agent services that CI installs from `uv.lock`, lints, typechecks, tests and evaluates with the fake provider, with no Dockerfile and no hosting files. Their runtime settings are environment variables: `AGENT_OIDC_ISSUER` and `AGENT_OIDC_AUDIENCE` for the identity provider, `AGENT_BACKEND_BASE_URL` (https) for the backend, and, for the Claude provider, `AGENT_PROVIDER=claude` with `ANTHROPIC_API_KEY` taken from the host's secret store. A deployed service never runs with `AGENT_PROFILE=local`, and the service refuses to start when it has no identity configured.

## Backend: Azure Container Apps

Reference: `references/azure-setup.md` (the guide) and `references/azure/` (the scripts and config examples).

1. Confirm the subscription, region and environment (`prod`, `acc`, `dev`) with the user.
2. Copy `references/azure/` into the repository as `infra/azure/` and add the credential files to `.gitignore` (the guide lists them). The scripts find the repository root two folders above themselves, and they build the backend from `backend/`: adapt the path when the app lives elsewhere.
3. Copy `azure-config.env.example` to `azure-config.env` and `app-secrets.env.example` to `app-secrets.env`; the user fills in the values, including the identity provider's issuer and the audience of the API (the backend refuses to start with an issuer and no audience).
4. Run the numbered scripts in order, from `00-setup-resource-group.sh` to `07-show-deployment-info.sh`: resource group, container registry and log analytics, PostgreSQL Flexible Server, Container Apps environment, blob storage, image build and push, container app deploy, deployment info.
5. Verify with `curl https://<backend-url>/actuator/health`.
6. Redeploy with `update-backend.sh`: it rebuilds the image, pushes it and creates a new revision.

Other scripts: `add-custom-domain.sh`, `check-secrets.sh`, `show-database-credentials.sh`, `test-database-connection.sh`, `cleanup.sh` (deletes the whole resource group; confirm with the user first).

The database, its schema migrations and its production sizing are project decisions. The example provisions PostgreSQL because the local development service is PostgreSQL.

## Web: Cloudflare Workers Through OpenNext

Reference: `references/cloudflare-setup.md` (the guide) and `references/cloudflare/` (`wrangler` configuration, `open-next.config.ts` and local preview variables).

1. Confirm the Cloudflare account and the public URLs with the user.
2. For each web app, copy the OpenNext adapter and Wrangler files from `references/cloudflare/`, add the `@opennextjs/cloudflare`, `esbuild` and `wrangler` dev dependencies and the `build:cloudflare`, `preview` and `deploy` scripts, and ignore `.open-next/`, `.wrangler/` and `.dev.vars` (the guide has the exact lines).
3. Set `API_BASE_URL` in `wrangler.jsonc` to the deployed backend; the generated apps need no other variable and no secret of their own.
4. Run `npm run preview` for a local production check, then `npm run deploy` once the user approves.
5. The local development sign-in works only against a backend under its `local` profile. Before deploying a web app, replace it with the project's identity provider (see `security-auth`).

## Mobile: Store Releases

Reference: `references/mobile-store-release.md`. It describes a tag-triggered release job that builds and uploads each mobile app, and the signing secrets it needs. The user owns the store accounts and the signing material.

## CI Deploy Jobs

Generated workflows build and test only. To deploy from CI, add a job to the matching workflow with the example in the guide: it runs only on `main` (or a release tag), uses `environment: production`, and reports a warning instead of deploying while a secret is missing. Describe the secrets to set; never write their values.

## Verification

Report what was actually run and observed: the health check status, the deployed URL, the revision or Worker version. If a step needed an account or secret that was not available, say so and stop at that step.
