"""The application factory.

Run it with `uvicorn app.main:create_app --factory`. The factory validates the configuration first and raises
`ConfigurationError` when the service would run unauthenticated or unsafely, so a bad configuration stops the
process before it listens. `create_app` takes injectable parts (a key provider, a model provider, an HTTP
transport, a clock) for tests and embedders; no setting selects any of them.
"""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, Response

from app.agent.service import AssistantService
from app.auth.keys import JwksKeyProvider, KeyProvider
from app.auth.startup import resolve_auth
from app.auth.verifier import TokenVerifier
from app.config import Settings
from app.errors import install_error_handlers
from app.providers.base import Provider
from app.providers.factory import build_provider
from app.routes import assist, health
from app.safety.audit import AuditLog, configure_audit_logging
from app.safety.budget import UserBudget
from app.tools.backend_profile import GetMyProfile
from app.tools.registry import ToolRegistry

REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{8,64}")


def create_app(
    settings: Settings | None = None,
    *,
    key_provider: KeyProvider | None = None,
    provider: Provider | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    audit: AuditLog | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> FastAPI:
    settings = settings or Settings()
    auth = resolve_auth(settings)
    provider = provider or build_provider(settings)
    if audit is None:
        configure_audit_logging()
        audit = AuditLog()

    # Under `local` the clients ignore proxy variables: a proxy in between would defeat the loopback guards.
    trust_env = not settings.is_local
    timeout = settings.backend_timeout_seconds
    jwks_client = httpx.AsyncClient(transport=transport, timeout=timeout, follow_redirects=False, trust_env=trust_env)
    backend = httpx.AsyncClient(
        base_url=settings.backend_base_url,
        transport=transport,
        timeout=timeout,
        follow_redirects=False,
        trust_env=trust_env,
    )
    keys = key_provider or JwksKeyProvider(
        client=jwks_client,
        jwks_uri=auth.jwks_uri,
        issuer=None if auth.jwks_uri else auth.issuer,
        clock=clock,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        await jwks_client.aclose()
        await backend.aclose()

    # No /docs, /redoc or /openapi.json: only /api/health is open. The contract is openapi.yml in the app's folder.
    app = FastAPI(title="Agent service", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.verifier = TokenVerifier(key_provider=keys, issuer=auth.issuer, audience=auth.audience)
    app.state.assistant = AssistantService(
        provider=provider,
        tools=ToolRegistry([GetMyProfile()]),
        backend=backend,
        budget=UserBudget(
            max_requests=settings.budget_requests,
            max_tokens=settings.budget_tokens,
            window_seconds=settings.budget_window_seconds,
            max_concurrent_turns=settings.budget_concurrent_turns,
            clock=clock,
        ),
        audit=audit,
        max_tool_calls=settings.max_tool_calls,
        output_token_cap=settings.claude_max_tokens,
    )
    install_error_handlers(app)

    @app.middleware("http")
    async def request_id(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        # A caller's own ID is kept only when it is plain; anything else could forge a log line.
        supplied = request.headers.get(REQUEST_ID_HEADER, "")
        request.state.request_id = supplied if _REQUEST_ID.fullmatch(supplied) else uuid.uuid4().hex
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request.state.request_id
        return response

    app.include_router(health.router)
    app.include_router(assist.router)
    return app
