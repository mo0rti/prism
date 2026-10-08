"""Workflow roles on board grants and the role predicates of gated lifecycle actions.

A human grant holds a fixed set of roles; an agent grant holds none. A gated action names the roles its approver
must hold as a predicate: every role in ``all_of`` and, when ``any_of`` is not empty, at least one role in it. The
same predicate decides discovery, the proposal list, preview inspection, apply, recovery and repair.

`required_roles` is the one place the board asks which roles an action needs. The lifecycle registry answers it,
because some predicates depend on the feature (the design owner is `designer` while a scoped app has a UI and
`tech-lead` otherwise). An action it does not gate returns ``None``: any writable grant may apply it.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

ROLES: tuple[str, ...] = ("po", "designer", "tech-lead", "dev", "qa", "release")


class RoleError(ValueError):
    """A role list that cannot be stored on a grant; ``code`` is the board error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class RolePredicate:
    all_of: tuple[str, ...] = ()
    any_of: tuple[str, ...] = ()

    def holds(self, roles: Iterable[str]) -> bool:
        held = set(roles)
        if not held.issuperset(self.all_of):
            return False
        return not self.any_of or bool(held.intersection(self.any_of))

    def as_json(self) -> dict[str, list[str]]:
        return {"all_of": list(self.all_of), "any_of": list(self.any_of)}

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "RolePredicate":
        return cls(all_of=tuple(value.get("all_of") or ()), any_of=tuple(value.get("any_of") or ()))


def parse_roles(text: str | Iterable[str] | None, *, kind: str, writable: bool) -> tuple[str, ...]:
    """The sorted roles of a new grant, or a `RoleError` with the code the board reports."""

    if text is None:
        items: list[str] = []
    elif isinstance(text, str):
        items = [item.strip() for item in text.split(",") if item.strip()]
    else:
        items = [str(item).strip() for item in text if str(item).strip()]
    if not items:
        return ()
    unknown = [item for item in items if item not in ROLES]
    if unknown:
        raise RoleError("invalid_role", f"Unknown role `{unknown[0]}`. Roles: {', '.join(ROLES)}.")
    if len(set(items)) != len(items):
        raise RoleError("invalid_role", "A role is listed twice.")
    if kind == "agent":
        raise RoleError("agent_role_forbidden", "An agent grant holds no role; a human applies gated work in the board.")
    if not writable:
        raise RoleError("role_requires_write", "A role needs a writable grant (`--write`).")
    return tuple(sorted(items))


def required_roles(action: str, context: Mapping[str, Any] | None = None) -> RolePredicate | None:
    """The roles a human must hold to approve ``action`` in ``context``, or ``None`` when the action is not gated.

    The lifecycle registry implements this; until it does, no action is gated.
    """

    return None
