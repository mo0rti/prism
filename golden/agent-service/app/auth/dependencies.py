"""The FastAPI dependency every protected route declares: it returns the verified caller or answers 401."""

from __future__ import annotations

from fastapi import Request

from app.auth.caller import AuthenticationError, Caller, IdentityUnavailableError
from app.auth.verifier import TokenVerifier
from app.errors import ApiError, unauthorized


def bearer_token(request: Request) -> str:
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise unauthorized()
    return token.strip()


async def require_caller(request: Request) -> Caller:
    token = bearer_token(request)
    verifier: TokenVerifier = request.app.state.verifier
    try:
        caller = await verifier.verify(token)
    except AuthenticationError as error:
        raise unauthorized("Invalid or expired token") from error
    except IdentityUnavailableError as error:
        raise ApiError(503, "IDENTITY_UNAVAILABLE", "The identity service is unavailable; try again later") from error
    request.state.caller = caller
    return caller
