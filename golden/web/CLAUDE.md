@AGENTS.md

## Claude Code skills

Project-specific Claude skills live in `.claude/skills/`; Claude Code loads them when the work matches. Detailed conventions are documented there.

- `web-conventions` - the slice, the generated client, the session cookie, tests and replacing the dev identity
- `deployment` - worked examples for deploying the web app (Cloudflare Workers through OpenNext); the user and their agent own the hosting choice and the deployment

## Web Claude Commands

- `/generate-clients` - regenerate API clients from the shared contract
