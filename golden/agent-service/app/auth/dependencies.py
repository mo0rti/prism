"""The FastAPI dependency every protected route declares: it returns the verified caller or answers 401."""

from __future__ import annotations

from fastapi import Request

from app.auth.caller import AuthenticationError, Caller, IdentityUnavailableError
from app.auth.keys import is_loopback_host
from app.auth.verifier import TokenVerifier
from app.errors import ApiError, unauthorized


def bearer_token(request: Request) -> str:
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise unauthorized()
    return token.strip()


def require_local_peer(request: Request) -> None:
    """Under the `local` profile, only a caller on this machine is answered.

    The local development identity is for this machine only, so a service that runs under it and is reachable
    from elsewhere (a changed bind address, a tunnel) must not answer a remote caller, even one that holds a
    token. The peer is the address of the TCP connection, never a header the caller can set.
    """

    settings = request.app.state.settings
    if settings.is_local and not is_loopback_host(request.client.host if request.client else None):
        raise ApiError(403, "LOCAL_ONLY", "The local development identity answers requests from this machine only")


async def require_caller(request: Request) -> Caller:
    require_local_peer(request)
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
