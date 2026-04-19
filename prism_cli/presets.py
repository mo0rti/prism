"""Preset and answer helpers for the Prism CLI."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Preset:
    slug: str
    label: str
    maturity: str
    summary: str
    answers: dict[str, Any]
    notes: tuple[str, ...] = field(default_factory=tuple)


PRESETS: tuple[Preset, ...] = (
    Preset(
        slug="backend-only",
        label="Backend Only",
        maturity="validated",
        summary="Repository shape and API contract inspection.",
        answers={"platforms": ["backend"]},
    ),
    Preset(
        slug="backend-mobile",
        label="Backend + Mobile",
        maturity="validated",
        summary="Validated mobile application path with both Android and iOS clients.",
        answers={"platforms": ["backend", "mobile-android", "mobile-ios"]},
    ),
    Preset(
        slug="backend-web",
        label="Backend + Web",
        maturity="partial",
        summary="Combined user-web and admin-portal setup with current web caveats.",
        # Keep these auth defaults aligned with copier.yml until manifest-driven preset sync lands.
        answers={
            "platforms": ["backend", "web-user-app", "web-admin-portal"],
            "auth_methods": ["google", "password"],
        },
        notes=(
            "Cloudflare deployment still needs live-account validation.",
            "Admin Web Portal currently requires password auth.",
        ),
    ),
)

PRESET_BY_SLUG = {preset.slug: preset for preset in PRESETS}

ALL_PLATFORM_CHOICES: tuple[tuple[str, str], ...] = (
    ("backend", "Spring Boot Backend"),
    ("web-user-app", "User-Facing Web App"),
    ("web-admin-portal", "Admin Web Portal"),
    ("mobile-android", "Android (Kotlin/Compose)"),
    ("mobile-ios", "iOS (Swift/SwiftUI)"),
)

ALL_AUTH_CHOICES: tuple[tuple[str, str], ...] = (
    ("google", "Google OAuth"),
    ("apple", "Apple Sign-In"),
    ("facebook", "Facebook Login"),
    ("microsoft", "Microsoft Account"),
    ("password", "Username + Password"),
)

DEFAULT_ANSWERS: dict[str, Any] = {
    "description": "A multi-platform application",
    "auth_methods": ["google", "password"],
    "database": "postgres",
    "use_docker": True,
    "cloud_provider": "azure",
    "web_hosting": "cloudflare",
    "github_org": "",
}


def get_preset(slug: str) -> Preset | None:
    return PRESET_BY_SLUG.get(slug)


def merge_answers(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    merged.update(override)
    return merged
