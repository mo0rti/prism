"""Access the workflow guidance pinned in the installed Prism package."""

from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
from importlib.resources import files
import hashlib
import json
import re
from typing import Any

_SHA256 = re.compile(r"[0-9a-f]{64}")


def _asset_name(version: str) -> str:
    if not isinstance(version, str) or not version.strip():
        raise ValueError("A workflow asset version is required.")
    if version != "1":
        raise ValueError(f"Unsupported Prism workflow asset version: {version!r}.")
    return f"workflow-v{version}.json"


@lru_cache(maxsize=4)
def _load(version: str) -> dict[str, Any]:
    name = _asset_name(version)
    try:
        source = files("prism_cli").joinpath("assets", name).read_text(encoding="utf-8")
        asset = json.loads(source)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Unable to load packaged workflow asset {name}: {exc}") from exc
    if not isinstance(asset, dict) or asset.get("version") != version:
        raise ValueError(f"Packaged workflow asset {name} has an invalid version header.")
    _validate_asset(asset, name)
    return asset


def _validate_asset(asset: dict[str, Any], name: str) -> None:
    files_by_path: dict[str, dict[str, str]] = {}
    source_files = asset.get("files")
    if not isinstance(source_files, list):
        raise ValueError(f"Packaged workflow asset {name} has no file table.")
    for item in source_files:
        if not isinstance(item, dict):
            raise ValueError(f"Packaged workflow asset {name} has an invalid file entry.")
        path, content, digest = item.get("path"), item.get("content"), item.get("digest")
        if (
            not isinstance(path, str)
            or not path
            or path.startswith("/")
            or "\\" in path
            or not isinstance(content, str)
            or not isinstance(digest, str)
            or hashlib.sha256(content.encode("utf-8")).hexdigest() != digest
            or path in files_by_path
        ):
            raise ValueError(f"Packaged workflow asset {name} has an invalid or duplicate file entry.")
        files_by_path[path] = item

    skills = asset.get("skills")
    if not isinstance(skills, list):
        raise ValueError(f"Packaged workflow asset {name} has no skill list.")
    skill_names: set[str] = set()
    for skill in skills:
        if not isinstance(skill, dict):
            raise ValueError(f"Packaged workflow asset {name} has an invalid skill entry.")
        skill_name = skill.get("name")
        instruction_path = skill.get("instructions_path")
        references = skill.get("reference_paths")
        if (
            not isinstance(skill_name, str)
            or not skill_name
            or skill_name in skill_names
            or not isinstance(skill.get("description"), str)
            or not skill["description"].strip()
            or not isinstance(instruction_path, str)
            or instruction_path not in files_by_path
            or not isinstance(references, list)
            or any(not isinstance(path, str) or path not in files_by_path for path in references)
            or not isinstance(skill.get("actions", []), list)
            or any(not isinstance(action, str) for action in skill.get("actions", []))
        ):
            raise ValueError(f"Packaged workflow asset {name} has incomplete or duplicate skill references.")
        skill_names.add(skill_name)

    bootstrap_paths = asset.get("bootstrap_paths")
    if (
        not isinstance(bootstrap_paths, list)
        or any(not isinstance(path, str) or path not in files_by_path for path in bootstrap_paths)
        or len(set(bootstrap_paths)) != len(bootstrap_paths)
    ):
        raise ValueError(f"Packaged workflow asset {name} has invalid bootstrap paths.")
    pointers = asset.get("guidance_pointers")
    if not isinstance(pointers, dict) or any(
        not isinstance(pointers.get(path), str) or not pointers[path].strip()
        for path in ("AGENTS.md", "CLAUDE.md")
    ):
        raise ValueError(f"Packaged workflow asset {name} has invalid root guidance pointers.")

    history = asset.get("previous_digests")
    if not isinstance(history, dict):
        raise ValueError(f"Packaged workflow asset {name} has no digest history for earlier shipped files.")
    for path, digests in history.items():
        if (
            not isinstance(path, str)
            or not path
            or path.startswith("/")
            or "\\" in path
            or not isinstance(digests, list)
            or len(set(digests)) != len(digests)
            or any(not isinstance(item, str) or _SHA256.fullmatch(item) is None for item in digests)
        ):
            raise ValueError(f"Packaged workflow asset {name} has an invalid digest history for {path!r}.")

    recorded_digest = asset.get("asset_digest")
    canonical_source = {key: value for key, value in asset.items() if key != "asset_digest"}
    actual_digest = hashlib.sha256(
        json.dumps(canonical_source, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if not isinstance(recorded_digest, str) or recorded_digest != actual_digest:
        raise ValueError(f"Packaged workflow asset {name} failed its canonical digest check.")


def asset_digest(version: str = "1") -> str:
    """Return the content digest used to pin standard guidance to a workspace."""

    digest = _load(version).get("asset_digest")
    if not isinstance(digest, str) or len(digest) != 64:
        raise ValueError(f"Packaged workflow asset version {version!r} has no valid content digest.")
    return digest


def list_skills(version: str = "1") -> list[dict[str, Any]]:
    """List the standard workflow skills available in a pinned asset version."""

    skills = _load(version).get("skills")
    if not isinstance(skills, list):
        raise ValueError(f"Packaged workflow asset version {version!r} has no skill list.")
    return [
        {
            "name": skill["name"],
            "version": version,
            "description": skill["description"],
            "actions": list(skill.get("actions", [])),
        }
        for skill in skills
    ]


def get_skill(name: str, version: str = "1") -> dict[str, Any]:
    """Return one complete canonical instruction and its packaged references."""

    asset = _load(version)
    skills = asset.get("skills")
    files_by_path = {
        item.get("path"): item
        for item in asset.get("files", [])
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    if isinstance(skills, list):
        for skill in skills:
            if not isinstance(skill, dict) or skill.get("name") != name:
                continue
            instruction_file = files_by_path.get(skill.get("instructions_path"))
            if not isinstance(instruction_file, dict):
                raise ValueError(f"Packaged workflow skill {name!r} has no instruction source.")
            references = []
            for path in skill.get("reference_paths", []):
                reference = files_by_path.get(path)
                if not isinstance(reference, dict):
                    raise ValueError(f"Packaged workflow skill {name!r} has a missing reference {path!r}.")
                references.append({key: reference[key] for key in ("path", "content", "digest")})
            return {
                "name": name,
                "version": version,
                "description": skill["description"],
                "instructions": instruction_file["content"],
                "references": deepcopy(references),
                "actions": list(skill.get("actions", [])),
            }
    raise ValueError(f"Unknown Prism workflow skill {name!r} in version {version!r}.")


def bootstrap_files(version: str = "1") -> list[dict[str, str]]:
    """Return the canonical non-application knowledge scaffold for adoption."""

    asset = _load(version)
    by_path = {
        item.get("path"): item
        for item in asset.get("files", [])
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    result: list[dict[str, str]] = []
    for path in asset.get("bootstrap_paths", []):
        item = by_path.get(path)
        if not isinstance(item, dict):
            raise ValueError(f"Packaged workflow asset is missing bootstrap file {path!r}.")
        result.append({key: item[key] for key in ("path", "content", "digest")})
    return deepcopy(result)


def guidance_pointer(name: str, version: str = "1") -> str:
    """Return the generated minimal root pointer for Codex or Claude Code."""

    if name not in ("AGENTS.md", "CLAUDE.md"):
        raise ValueError(f"Unsupported workflow guidance pointer {name!r}.")
    pointers = _load(version).get("guidance_pointers")
    value = pointers.get(name) if isinstance(pointers, dict) else None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Packaged workflow asset version {version!r} has no {name} pointer.")
    return value


def previous_digests(path: str, version: str = "1") -> tuple[str, ...]:
    """Return the SHA-256 digests of every earlier shipped content of one installer-managed file.

    The history covers the bootstrap files and the generated root pointers
    (`AGENTS.md`, `CLAUDE.md`). It lets an installer recognise an untouched copy
    of an earlier canonical version without network access.
    """

    history = _load(version).get("previous_digests")
    digests = history.get(path) if isinstance(history, dict) else None
    return tuple(digests) if isinstance(digests, list) else ()
