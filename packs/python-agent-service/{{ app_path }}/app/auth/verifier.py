"""Bearer token verification: signature, issuer, audience and expiry, against public keys only."""

from __future__ import annotations

import logging
from typing import Any

import jwt

from app.auth.caller import AuthenticationError, Caller, IdentityUnavailableError
from app.auth.keys import KeyProvider, KeySourceError, UnknownKeyError

logger = logging.getLogger("agent.auth")

# Only an asymmetric algorithm is accepted: a token can never be "verified" with a key it names itself,
# and `none` and the HMAC family are rejected before any key is looked up.
ALLOWED_ALGORITHMS = ("RS256",)
MAX_TOKEN_LENGTH = 8192
CLOCK_SKEW_SECONDS = 60


class TokenVerifier:
    def __init__(self, *, key_provider: KeyProvider, issuer: str, audience: str | None) -> None:
        self._keys = key_provider
        self._issuer = issuer
        self._audience = audience

    async def verify(self, token: str) -> Caller:
        """The caller a valid token identifies. Raises `AuthenticationError` or `IdentityUnavailableError`."""

        if not token or len(token) > MAX_TOKEN_LENGTH:
            raise AuthenticationError("Invalid token")
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as error:
            raise AuthenticationError("Invalid token") from error
        if header.get("alg") not in ALLOWED_ALGORITHMS:
            raise AuthenticationError("Invalid token")
        kid = header.get("kid")
        try:
            key = await self._keys.key_for(kid if isinstance(kid, str) else None)
        except UnknownKeyError as error:
            raise AuthenticationError("Invalid token") from error
        except KeySourceError as error:
            logger.warning("The verification keys are unavailable: %s", error)
            raise IdentityUnavailableError("The identity keys are unavailable") from error
        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                key,
                algorithms=list(ALLOWED_ALGORITHMS),
                issuer=self._issuer,
                audience=self._audience,
                leeway=CLOCK_SKEW_SECONDS,
                options={"require": ["exp", "iss", "sub"], "verify_aud": self._audience is not None},
            )
        except jwt.PyJWTError as error:
            # The reason (expired, wrong issuer, bad signature) stays in the log; the caller only learns it failed.
            logger.info("A bearer token was rejected: %s", type(error).__name__)
            raise AuthenticationError("Invalid token") from error
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject.strip():
            raise AuthenticationError("Invalid token")
        return Caller(
            subject=subject,
            issuer=self._issuer,
            email=_text(claims.get("email")),
            name=_text(claims.get("name")),
            token=token,
        )


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None
