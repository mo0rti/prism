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
        slug="backend-android",
        label="Backend + Android",
        maturity="validated",
        summary="Strongest current application path.",
        answers={"platforms": ["backend", "mobile-android"]},
    ),
    Preset(
        slug="backend-user-web",
        label="Backend + User Web App",
        maturity="partial",
        summary="Focused web slice with build-validated scaffolding.",
        answers={"platforms": ["backend", "web-user-app"]},
        notes=("Cloudflare deployment still needs live-account validation.",),
    ),
    Preset(
        slug="backend-admin-portal",
        label="Backend + Admin Web Portal",
        maturity="partial",
        summary="Focused admin slice with current password-auth requirement.",
        # Keep these auth defaults aligned with copier.yml until manifest-driven preset sync lands.
        answers={
            "platforms": ["backend", "web-admin-portal"],
            "auth_methods": ["google", "password"],
        },
        notes=("Admin Web Portal currently requires password auth.",),
    ),
    Preset(
        slug="backend-user-web-admin",
        label="Backend + User Web App + Admin Web Portal",
        maturity="partial",
        summary="Initial combined web/admin setup.",
        # Keep these auth defaults aligned with copier.yml until manifest-driven preset sync lands.
        answers={
            "platforms": ["backend", "web-user-app", "web-admin-portal"],
            "auth_methods": ["google", "password"],
        },
        notes=("Admin Web Portal currently requires password auth.",),
    ),
    Preset(
        slug="backend-ios",
        label="Backend + iOS",
        maturity="partial",
        summary="Structural iOS slice that still needs local macOS validation.",
        answers={"platforms": ["backend", "mobile-ios"]},
        notes=("Validate locally on macOS before treating the slice as build-proven.",),
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
