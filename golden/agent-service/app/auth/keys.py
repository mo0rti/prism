"""Where the verification keys come from: a JWKS document, fetched over HTTP and cached.

The service holds no secret. It verifies tokens with public keys only:
- under the `local` profile, the key the backend's dev identity publishes at `/api/dev-identity/jwks`;
- otherwise, the keys of the configured identity provider (its JWKS location, or the one its OpenID
  discovery document names).
"""

from __future__ import annotations

import asyncio
import ipaddress
import time
from collections.abc import Callable, Mapping
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx
import jwt
from jwt import PyJWK

# JWK members that only a private key has (RFC 7518). A published key set that carries one is refused.
PRIVATE_MEMBERS = frozenset({"d", "p", "q", "dp", "dq", "qi", "oth", "k"})
MAX_DOCUMENT_BYTES = 1_000_000


class KeySourceError(Exception):
    """The key source could not be read or is not a public key set."""


class UnknownKeyError(Exception):
    """No trusted key matches the token's `kid`."""


class KeyProvider(Protocol):
    async def key_for(self, kid: str | None) -> PyJWK:
        """The public key for a token's `kid`. Raises `UnknownKeyError` or `KeySourceError`."""
        ...


def parse_jwks(document: object) -> list[PyJWK]:
    """The RSA signing keys of a JWKS document. A key set with a private member is refused whole."""

    if not isinstance(document, dict) or not isinstance(document.get("keys"), list):
        raise KeySourceError("The key source did not return a JSON Web Key Set")
    keys: list[PyJWK] = []
    for item in document["keys"]:
        if not isinstance(item, dict):
            continue
        if PRIVATE_MEMBERS & item.keys():
            raise KeySourceError("The key source published a private key; refusing the whole key set")
        if item.get("kty") != "RSA" or item.get("use") not in (None, "sig"):
            continue
        try:
            keys.append(PyJWK.from_dict(item))
        except jwt.PyJWTError:
            continue
    return keys


class StaticKeyProvider:
    """A fixed set of keys. Tests and embedders use it; no configuration setting selects it."""

    def __init__(self, keys: list[PyJWK]) -> None:
        self._keys = keys

    async def key_for(self, kid: str | None) -> PyJWK:
        return select_key(self._keys, kid)


def select_key(keys: list[PyJWK], kid: str | None) -> PyJWK:
    if kid is not None:
        for key in keys:
            if key.key_id == kid:
                return key
        raise UnknownKeyError("No trusted key has the token's key ID")
    # A token with no `kid` is verified only when exactly one key could have signed it.
    if len(keys) == 1:
        return keys[0]
    raise UnknownKeyError("The token names no key ID and the key set holds more than one key")


def is_loopback_host(host: str | None) -> bool:
    if not host:
        return False
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def require_secure_url(value: str, name: str) -> str:
    """The URL when it is https, or http to a loopback host. Anything else would send a token or trust a key in clear text."""

    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError(f"{name} must be an absolute http(s) URL")
    if parts.username or parts.password:
        raise ValueError(f"{name} must not carry credentials")
    if parts.scheme == "http" and not is_loopback_host(parts.hostname):
        raise ValueError(f"{name} must use https unless it points at this machine")
    return value


class JwksKeyProvider:
    """Fetches a JWKS document and caches its keys.

    A token with an unknown `kid` triggers one refresh, then at most one more per `min_refresh_seconds`, so a
    stream of forged key IDs cannot turn the service into a request amplifier. Keys expire after `ttl_seconds`.
    When the document cannot be read, no key is served: the service fails closed.
    """

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        jwks_uri: str | None,
        issuer: str | None = None,
        ttl_seconds: float = 300.0,
        min_refresh_seconds: float = 10.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if jwks_uri is None and not issuer:
            raise ValueError("A key provider needs a JWKS location or an issuer to discover it from")
        self._client = client
        self._jwks_uri = jwks_uri
        self._issuer = issuer
        self._ttl = ttl_seconds
        self._min_refresh = min_refresh_seconds
        self._clock = clock
        self._lock = asyncio.Lock()
        self._keys: list[PyJWK] = []
        self._fetched_at: float | None = None
        self._last_attempt: float | None = None
        self._last_failed = False

    async def key_for(self, kid: str | None) -> PyJWK:
        key = self._cached(kid)
        if key is not None:
            return key
        async with self._lock:
            key = self._cached(kid)  # another request may have refreshed while this one waited
            if key is not None:
                return key
            if self._may_refresh():
                await self._refresh()
                key = self._cached(kid)
                if key is not None:
                    return key
            elif self._last_failed:
                raise KeySourceError("The key source is unavailable")
        raise UnknownKeyError("No trusted key has the token's key ID")

    def _cached(self, kid: str | None) -> PyJWK | None:
        now = self._clock()
        if self._fetched_at is None or now - self._fetched_at >= self._ttl:
            return None
        try:
            return select_key(self._keys, kid)
        except UnknownKeyError:
            return None

    def _may_refresh(self) -> bool:
        return self._last_attempt is None or self._clock() - self._last_attempt >= self._min_refresh

    async def _refresh(self) -> None:
        self._last_attempt = self._clock()
        try:
            uri = self._jwks_uri or await self._discover()
            keys = parse_jwks(await self._get_json(uri))
        except KeySourceError:
            self._last_failed = True
            raise
        self._keys = keys
        self._fetched_at = self._clock()
        self._last_failed = False

    async def _discover(self) -> str:
        assert self._issuer is not None
        document = await self._get_json(self._issuer.rstrip("/") + "/.well-known/openid-configuration")
        if not isinstance(document, Mapping) or document.get("issuer") != self._issuer:
            raise KeySourceError("The discovery document does not belong to the configured issuer")
        uri = document.get("jwks_uri")
        if not isinstance(uri, str):
            raise KeySourceError("The discovery document names no jwks_uri")
        try:
            return require_secure_url(uri, "The discovered jwks_uri")
        except ValueError as error:
            raise KeySourceError(str(error)) from error

    async def _get_json(self, uri: str) -> Any:
        try:
            response = await self._client.get(uri, headers={"Accept": "application/json"})
            response.raise_for_status()
            if len(response.content) > MAX_DOCUMENT_BYTES:
                raise KeySourceError("The key source answered with an oversized document")
            return response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise KeySourceError(f"The key source could not be read ({type(error).__name__})") from error
