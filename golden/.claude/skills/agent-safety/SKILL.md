---
name: agent-safety
description: "Safety rules of a generated Python agent service: assist and never advise, untrusted data, read-only tools with the user's own token, audit logging, a per-user budget, no cross-user data, no API key in files, and fail-closed authentication. Use when changing prompts, tools, authentication, budgets or the response notice, or when adapting the service to a domain."
user-invocable: false
---

# Agent Safety

These rules hold for every change to an agent service. Each is enforced in one place and has a test; keep both. Never weaken a rule or its test to make something pass.

Paths are inside the agent service's folder (`agent-service/`).

## Slice files

- `app/safety/notice.py` - the notice every response carries.
- `app/agent/prompts.py` - the constant system prompt, which states the same boundary to the model.
- `app/safety/untrusted.py` - the only builder of the untrusted-data envelope.
- `app/agent/turn.py` - validates and runs tool calls, wraps results as data, logs each call.
- `app/safety/audit.py` - the audit log of tool calls; `app/safety/budget.py` - the per-user budget.
- `app/agent/service.py` - the per-request context and the budget check.
- `app/auth/startup.py` - the fail-closed identity rules; `app/auth/verifier.py` - token verification.
- `app/tools/registry.py` - the allow-list that refuses a tool that changes data.
- `app/config.py` - the settings, with the model key read from the environment only.
- `tests/test_agent_turn.py` and `tests/test_auth.py` - the tests that pin these rules.

## The rules, where they hold, and what proves them

| Rule | Enforced in | Proved by |
| --- | --- | --- |
| **Assist, never advise.** Every response says so, and the model is told so | `app/safety/notice.py`, `app/routes/assist.py`, `app/agent/prompts.py` | `test_the_response_says_the_service_assists_and_does_not_advise...` |
| **Untrusted data is never instructions.** The question and every tool result travel in envelopes whose content is JSON-escaped so it cannot close them; the system prompt is a constant | `app/safety/untrusted.py`, `app/agent/turn.py` | `test_the_system_prompt_is_a_constant_and_the_question_and_results_travel_as_data`, `test_an_envelope_cannot_be_closed_from_inside` |
| **Tools only read, with the caller's own token.** The registry is an allow-list; the model picks no URL, header or user; arguments are validated | `app/tools/`, `app/agent/turn.py` | `test_a_model_that_asks_for_an_unregistered_tool...`, `test_tool_arguments_are_validated...`, `test_the_registry_refuses_a_tool_that_changes_data` |
| **Every tool call is logged with the user and request IDs**, never a token, a value or a result | `app/safety/audit.py` | `test_every_tool_call_is_logged_with_user_and_request_ids...` |
| **A per-user budget** of requests and tokens, in memory, with a clear `429` and `Retry-After` | `app/safety/budget.py`, `app/agent/service.py` | `test_the_request_budget_is_enforced_per_user...`, `test_the_token_budget_stops_a_user...` |
| **No cross-user data.** A context exists for one request; no global holds a question, a result or a token | `app/agent/service.py` | `test_one_users_data_never_enters_another_users_request` |
| **No API key in any file.** The key is `ANTHROPIC_API_KEY` in the environment; it is never shown, and a missing key is a startup error | `app/config.py`, `app/providers/factory.py` | `test_the_key_is_read_from_the_environment_and_never_shown`, `test_a_claude_provider_without_a_key_fails_startup...` |
| **Fail-closed authentication.** No identity configured, or `local` next to a real issuer, or `local` with a non-loopback backend: startup fails. There is no dev-identity endpoint and no off switch | `app/auth/startup.py` | `tests/test_auth.py` (startup tests, `test_no_setting_turns_authentication_off`) |

## Adapt the notice to your domain

The notice and the prompt are generic on purpose. Make them say what your product's boundary is, in both places, in one change:

1. `NOTICE` in `app/safety/notice.py`: name the kind of advice the service does not give. A portfolio tracker says that it explains the user's own holdings and does not give investment advice or personal buy, sell or allocation recommendations; a health product says it does not give medical advice.
2. The "You assist; you do not advise" rule in `app/agent/prompts.py`: name the same boundary and the refusal behaviour, such as declining a recommendation, saying why and offering to explain the user's own data.
3. `tests/test_agent_turn.py`: update the assertion on the notice's wording.
4. `evals/cases/`: add refusal cases for the questions your users will ask (see `add-evaluation-case`) and run them live before release; the fake provider cannot prove a model's refusals.

A generic notice is not a substitute for the legal review your domain needs; the project owner decides what the product may say.

## When you change something

- **A new tool:** `add-tool`. It must read only, take no user or URL from the model and use `context.backend_headers()`.
- **A new provider:** one `Provider` class and a branch in `app/providers/factory.py`. It must receive the constant system prompt and the envelopes unchanged, report token usage, and raise `ProviderError` with a message that holds no secret.
- **The real identity provider:** set `AGENT_OIDC_ISSUER` and `AGENT_OIDC_AUDIENCE` (and `AGENT_OIDC_JWKS_URI` if discovery is not available). Keep the audience check. Remove the `local` profile from every shared or deployed environment. When the backend replaces its dev identity (see `security-auth`), the service switches to the same issuer in the same change.
- **A shared budget store:** the budget is per process. Behind several replicas, move `UserBudget` to a shared store with the same interface before relying on a global limit.
- **Logging:** log IDs, names, outcomes and durations. Never log a token, an argument value, a question or a tool result.

## Never

- Add a setting, a header or an environment variable that skips token verification
- Accept a token without an audience check against a real issuer
- Put user or tool content into the system prompt, or build an envelope by hand
- Let a tool write, or let the agent confirm its own preview
- Commit a key, or read one from a file of the repository
- Keep per-user content on the service between requests
