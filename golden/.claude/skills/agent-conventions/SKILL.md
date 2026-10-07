---
name: agent-conventions
description: "Conventions for the generated Python agent services: structure, the request flow, the provider interface, configuration, typing and commands. Use when writing, extending or reviewing code under an agent service folder. For adding a tool defer to add-tool, for the safety rules to agent-safety, for evaluation cases to add-evaluation-case."
user-invocable: false
---

# Agent Conventions

Apply these rules whenever you change an agent service of this workspace. Each agent service is one `python-agent-service` app generated from the same pack, so the paths below are relative to the app's folder: `agent-service/`.

The service **assists and never advises**: it answers questions about the signed-in user's own data through read-only tools. It is built on Python 3.12, FastAPI 0.142.2 and uv (pinned in `packs/versions.yml` of the Prism template).

## Slice files

The pack generates one vertical slice and no example business features. Paths are inside the agent service's folder:

- `app/main.py` - `create_app()`: validates the configuration (fail-closed), then wires the verifier, the provider, the tools, the budget and the routes. Run with `uvicorn app.main:create_app --factory`; there is no module-level app.
- `app/config.py` - `Settings`, the only reader of the environment (`AGENT_*`, and `ANTHROPIC_API_KEY` for the model key).
- `app/auth/startup.py` - the fail-closed identity rules; `app/auth/verifier.py` verifies bearer tokens; `app/auth/keys.py` fetches and caches the JWKS.
- `app/agent/turn.py` - one agent turn: the provider loop, the tool calls and their safety rules.
- `app/agent/service.py` - the per-request budget and tool context; `app/agent/prompts.py` - the constant system prompt.
- `app/providers/base.py` - the provider interface and the vendor-neutral message types; `app/providers/fake.py` is the deterministic implementation and `app/providers/claude.py` the Claude API adapter.
- `app/tools/base.py` - the tool base class and its context; `app/tools/backend_profile.py` is the example tool; `app/tools/registry.py` is the allow-list.
- `app/safety/` - the untrusted-data envelope, the budget, the audit log and the notice.
- `app/routes/assist.py` - `POST /api/assist`; `app/routes/health.py` - `GET /api/health`.
- `openapi.yml` - this service's own contract; `tests/test_contract.py` keeps it equal to the code.
- `tests/support.py` - signing keys, tokens, a fake backend and an app builder for tests.
- `pyproject.toml` and `uv.lock` - the exact dependencies and their lock.

## The request flow

1. `require_caller` verifies the bearer token (RS256, issuer, audience, expiry) against public keys. Bad token: `401`. Key source unreadable: `503`.
2. `AssistantService.answer` reserves the caller's budget (`429` when used up) and builds a `ToolContext` for this request only.
3. `run_turn` sends the constant system prompt and the question, wrapped as untrusted data, to the provider. A tool call runs through the registry with validated arguments; its result goes back wrapped as untrusted data.
4. The route returns the answer, the tool calls, the usage, the notice and the request ID.

## Rules

- **One `create_app` per process.** Never create a module-level app or read the environment at import time.
- **Settings only in `app/config.py`.** Add a field there with a default and a validation, document it in `.env.example`, and read it through `Settings`. A setting that disables authentication is never added; `tests/test_auth.py` fails if one appears.
- **A provider is an implementation of `Provider`.** Nothing outside `app/providers/claude.py` imports a vendor SDK. A new provider is one class and one branch of `app/providers/factory.py`; a missing key or model is a startup error, never a silent fallback to the fake.
- **The system prompt is a constant.** Per-request content (the question, tool results, the user's name) reaches the model only as untrusted data. Put new standing instructions in `app/agent/prompts.py` and keep the test that asserts every provider call receives exactly that text.
- **State lives in a request.** No module-level variable holds a question, a result or a token. The only shared state is the budget's counters, keyed by user.
- **Errors use the shared format** `{"code": "...", "message": "..."}` through `ApiError` (`app/errors.py`). A response never carries a stack trace, a token or a provider's raw error text.
- **Typing is strict.** `mypy` runs in strict mode over `app/`, `evals/` and `tests/`; do not silence an error with `Any` or `# type: ignore` without a comment that says why. `ruff format` owns formatting and line length.
- **Wire names are camelCase, Python names are snake_case.** `app/models.py` converts through an alias generator.
- **Change the contract and the code together.** Edit `openapi.yml` and the route in one change; `tests/test_contract.py` compares them. The tool's model of a backend profile must match `UserProfile` in `shared/api-contracts/openapi.yml`.
- **Versions come from `packs/versions.yml` of the Prism template.** Change dependencies in `pyproject.toml`, run `uv lock`, and commit both; CI installs with `uv sync --locked`.

## Tests and commands

- `task <app id>:test` runs pytest with no network and no key: the fake provider, a fake backend over `httpx.MockTransport` and keys generated per run. The `Provider`, `KeyProvider` and the HTTP transport are injected through `create_app(...)`; settings never select a test double.
- `task <app id>:lint`, `task <app id>:typecheck` and `task <app id>:eval` run ruff, mypy and the evaluation cases with the fake provider. CI runs all of them plus the tests.
- `task <app id>:dev` runs under `AGENT_PROFILE=local` on the app's port; the backend runs under its own `local` profile. The service verifies the backend dev identity's tokens against `GET /api/dev-identity/jwks`.

## Forbidden Patterns

- A global holding a user's question, a tool result or a token
- `os.environ` outside `app/config.py`
- A vendor SDK import outside `app/providers/claude.py`
- Logging a token, a question or a tool result
- A real model call in a unit test or in CI
