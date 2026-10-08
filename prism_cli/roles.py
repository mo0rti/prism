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

    The lifecycle registry (``prism_cli.wiki_transitions.ACTION_SPECS``) answers it, for every registered action whether or
    not its work package has landed; availability is ``ActionSpec.enabled``, not a role matter. An action the registry does
    not know returns ``None``.

    The design owner ``D`` of a predicate (``designer`` when an active scoped app has a UI or an unknown one, otherwise
    ``tech-lead``) resolves from the scope the context names. The context keys, all optional:

    * ``design_owner``: ``"designer"`` or ``"tech-lead"``, already resolved; it wins over the keys below.
    * ``model``: the ``WorkspaceModel`` of the board, or ``root``: the workspace path, from which the model is read.
    * ``apps``: the app IDs of the feature's scope, as the preview sees them. The design owner needs the app model on top
      of them (``model``, ``root`` or ``design_owner``); a context with only ``action``, ``feature_path`` and ``apps``
      cannot resolve it, and a predicate that names the design owner then accepts either design role (``any_of``
      ``designer``, ``tech-lead``). The write still hands the feature to the design owner of its scope.
    * ``status``: the feature's current status. ``scope-edit`` is ``None`` (ungated) below ``ready-for-dev`` and gated for
      ``po`` from there on; without it the action is gated.
    * ``completes``: the design tracks a ``design-handoff`` completes (``ui``, ``technical``); each adds its role.
    * ``disposition``: ``duplicate`` makes ``bug-close`` need ``qa`` instead of ``po``.
    * ``original_action``: for ``operation-repair``, the action of the abandoned operation, whose predicate then applies.

    Keys the lookup does not use (``action``, ``feature_path``) are ignored.
    """

    from prism_cli.wiki_transitions import lookup_action

    spec = lookup_action(action) if isinstance(action, str) else None
    if spec is None:
        return None
    return spec.role_predicate(context)
