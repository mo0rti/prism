"""Who is calling: the identity a verified bearer token carries, and the errors verification can end in."""

from __future__ import annotations

from dataclasses import dataclass, field


class AuthenticationError(Exception):
    """The token is missing, malformed, expired, from another issuer or not signed by a trusted key. Answered with 401."""


class IdentityUnavailableError(Exception):
    """The key source could not be reached, so no token can be judged. Answered with 503; the service fails closed."""


@dataclass(frozen=True)
class Caller:
    """The signed-in user of one request.

    `token` is the caller's own bearer token. Tools forward it to the backend so the agent sees exactly what
    its user can see. It is never logged and never placed in a model prompt.
    """

    subject: str
    issuer: str
    email: str | None = None
    name: str | None = None
    token: str = field(default="", repr=False)

    @property
    def user_id(self) -> str:
        """The stable user key: the issuer and the subject, so users of two issuers never collide."""

        return f"{self.issuer}|{self.subject}"
