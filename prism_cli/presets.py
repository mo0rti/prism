"""Preset and answer helpers for the Prism CLI."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from prism_cli.app_model import GENERATION_SCAFFOLDED, apps_from_platforms


@dataclass(frozen=True)
class Preset:
    """A recommended start: an app list, plus any answers that are not about the apps."""

    slug: str
    label: str
    maturity: str
    summary: str
    # The apps `prism new` scaffolds, as manifest app entries with the default IDs.
    apps: tuple[dict[str, str], ...]
    answers: dict[str, Any] = field(default_factory=dict)
    notes: tuple[str, ...] = field(default_factory=tuple)


def _scaffolded(*app_ids: str) -> tuple[dict[str, str], ...]:
    """The default generated apps with these IDs, each scaffolded."""

    return tuple(apps_from_platforms(list(app_ids), generation=GENERATION_SCAFFOLDED))


PRESETS: tuple[Preset, ...] = (
    Preset(
        slug="backend-only",
        label="Backend Only",
        maturity="validated",
        summary="Repository shape and API contract inspection.",
        apps=_scaffolded("backend"),
    ),
    Preset(
        slug="backend-mobile",
        label="Backend + Mobile",
        maturity="partial",
        summary="Backend with Android and iOS clients; iOS requires macOS/Xcode validation.",
        apps=_scaffolded("backend", "mobile-android", "mobile-ios"),
    ),
    Preset(
        slug="backend-web",
        label="Backend + Web",
        maturity="partial",
        summary="Backend with one Next.js web app that signs in through the local development identity.",
        apps=_scaffolded("backend", "web"),
        notes=(
            "Add further web apps, for example an internal admin app, with `prism app add ID --stack nextjs-web --scaffold`.",
        ),
    ),
    Preset(
        slug="full",
        label="Full",
        maturity="partial",
        summary="Backend, web, Android and iOS apps, one of each stack; iOS requires macOS/Xcode validation.",
        apps=_scaffolded("backend", "web", "mobile-android", "mobile-ios"),
    ),
)

PRESET_BY_SLUG = {preset.slug: preset for preset in PRESETS}


@dataclass(frozen=True)
class WorkflowPreset:
    """A way to start a workflow-only workspace; it generates no application and has no answers."""

    slug: str
    label: str
    summary: str
    command: str
    notes: tuple[str, ...] = field(default_factory=tuple)


WORKFLOW_PRESETS: tuple[WorkflowPreset, ...] = (
    WorkflowPreset(
        slug="knowledge-root",
        label="Knowledge root",
        summary="A shared wiki for apps that live in other repositories. It generates no code and has no apps until you register them.",
        command="prism workflow install <path> --name <name> --knowledge-root",
        notes=(
            "Register each app of another repository with `prism app add ID --stack STACK --repository REPO --remote URL`.",
            "Map local checkouts of those repositories in the untracked prism.local.yml.",
        ),
    ),
)

DEFAULT_ANSWERS: dict[str, Any] = {
    "description": "A multi-platform application",
}


def get_preset(slug: str) -> Preset | None:
    return PRESET_BY_SLUG.get(slug)


def merge_answers(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    merged.update(override)
    return merged
