"""Test helpers for the approval flow: a workspace app with a UI, human grants that hold roles, and a gated apply.

A gated lifecycle action is proposed by an agent (or previewed by a human) and applied by a human who holds the roles it
needs, in a browser session, with the `review_revision` of what they read (CONTRACTS 1.3). Suites whose subject is another
behavior (operations, recovery, transports) use these helpers to take a lifecycle action through that flow.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from prism_cli.board_service import Actor, BoardService

ALL_ROLES = "po,designer,tech-lead,dev,qa,release"


def give_apps_a_ui(root: Path) -> None:
    """Declare that every app of the workspace has a UI, so the design owner of any scope is the designer."""

    path = root / "prism.workspace.yml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    for app in data.get("apps", []):
        app["capabilities"] = {"has-ui": True, "serves-api": True}
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def human_with_roles(service: BoardService, name: str, roles: str | None = ALL_ROLES, *, session: bool = True) -> Actor:
    """A writable human grant holding ``roles``; ``session`` is the browser-session branch that may approve."""

    grant = service.create_participant(name, "human", True, roles=roles)
    return service.authenticate(grant["token"], via_session=session)


def approve(service: BoardService, approver: Actor, preview: dict[str, Any], operation_id: str) -> dict[str, Any]:
    """Apply a gated preview as ``approver``: read it, then apply with its review revision and the acknowledgement."""

    review = service.get_preview(approver, preview["preview_id"])["approval"].get("review_revision")
    return service.apply(approver, preview["preview_id"], operation_id, review, True)


def apply_preview(service: BoardService, actor: Actor, preview: dict[str, Any], operation_id: str, *, approver: Actor | None = None) -> dict[str, Any]:
    """Apply a preview the way its kind needs: an ungated preview by ``actor``, a gated one by ``approver``."""

    if isinstance(preview.get("approval"), dict):
        return approve(service, approver or actor, preview, operation_id)
    return service.apply(actor, preview["preview_id"], operation_id)
