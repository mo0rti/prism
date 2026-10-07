# Agent Service Guide - Prism Golden

## Tech Stack

- **Python 3.12** with **FastAPI 0.142.2**, served by **uvicorn 0.54.0**, dependencies locked by **uv** (0.11.26)
- **Pydantic 2.13.5** and **pydantic-settings 2.15.0** for models and configuration
- **PyJWT 2.15.1** for token verification, **httpx 0.28.1** for the JWKS and backend calls
- **anthropic 1.11.0**, Anthropic's official SDK, behind the Claude provider only
- **pytest 9.1.1**, **ruff 0.16.10** and **mypy 2.4.0** (strict)

FastAPI is the framework because the service is async I/O between a caller, a model and a backend, and its models double as the request and response contract. `packs/versions.yml` of the Prism template pins these versions; the files of this app read them from there.

## Project Structure

```
agent-service/
├── pyproject.toml, uv.lock      # dependencies (exact versions) and the lock
├── openapi.yml                  # this service's own contract
├── app/
│   ├── main.py                  # create_app(): fail-closed startup and wiring
│   ├── config.py                # Settings from the environment (AGENT_*, ANTHROPIC_API_KEY)
│   ├── errors.py, models.py     # the error format; request and response bodies (camelCase)
│   ├── auth/                    # keys.py, verifier.py, startup.py, dependencies.py
│   ├── agent/                   # turn.py, service.py, prompts.py
│   ├── providers/               # base.py, fake.py, claude.py, factory.py
│   ├── tools/                   # base.py, registry.py, backend_profile.py
│   ├── safety/                  # untrusted.py, budget.py, audit.py, notice.py
│   └── routes/                  # health.py, assist.py
├── tests/                       # pytest suites; support.py has the keys, tokens and a fake backend
└── evals/                       # cases/*.toml and run.py
```

## The request flow

1. `require_caller` (`app/auth/dependencies.py`) reads the bearer token and `TokenVerifier` checks the signature (RS256 only), issuer, audience and expiry against public keys. A bad token is `401`; an unreadable key source is `503`.
2. `AssistantService.answer` (`app/agent/service.py`) counts the request against the caller's budget (`429` when used up) and builds a `ToolContext` for this request only.
3. `run_turn` (`app/agent/turn.py`) sends the constant system prompt and the question, wrapped as untrusted data, to the provider. When the model calls a tool, the registry runs it with validated arguments and the result goes back wrapped as untrusted data. Each call is logged with the user and request IDs.
4. The turn ends with the model's text. The service records the tokens used, and the route adds the notice and the request ID.

## Identity

- `AGENT_PROFILE=local`: tokens of the backend's local development identity, verified against the public key at `GET /api/dev-identity/jwks`. The backend URL must be a loopback URL.
- Otherwise `AGENT_OIDC_ISSUER` and `AGENT_OIDC_AUDIENCE` (and optionally `AGENT_OIDC_JWKS_URI`) name a real provider.
- `resolve_auth` in `app/auth/startup.py` holds every startup rule. `JwksKeyProvider` caches keys, refreshes for an unknown key ID at most once per cooldown and serves no key when the key source is unreadable.

## Providers

`Provider.complete(system, messages, tools)` returns text, tool calls and usage. `FakeProvider` is deterministic and records what it received, which is how tests prove what a model would have seen. `ClaudeProvider` translates to the Messages API, takes the model from `AGENT_CLAUDE_MODEL` and the key from `ANTHROPIC_API_KEY`, and echoes the model's own content blocks on tool turns.

## Contract

The service owns `openapi.yml` because it serves operations the backend does not, and a client of the backend's shared contract should not depend on an optional service. `tests/test_contract.py` keeps the contract and the code equal, and checks that the tool's model of a profile matches the shared contract's `UserProfile`.

## Related Docs

- [Architecture Overview](../../docs/architecture.md) for system-wide constraints
- [API Conventions](../../docs/api/conventions.md) for URL, error, and versioning rules
