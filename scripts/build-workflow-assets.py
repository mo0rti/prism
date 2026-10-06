#!/usr/bin/env python3
"""Build or verify the self-contained, pinned workflow-v1 package asset.

The asset also records the digests of earlier shipped versions of the files the
installer owns. A rebuild appends to that history and never drops an entry.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

import yaml
from jinja2 import Environment, StrictUndefined


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
ASSET_PATH = ROOT / "prism_cli" / "assets" / "workflow-v1.json"
SKILL_NAMES = (
    "ask",
    "audit-feature",
    "board-review",
    "design-clarify",
    "design-handoff",
    "design-intake",
    "design-start",
    "dev-clarify",
    "dev-done",
    "dev-start",
    "feature-reopen",
    "feature-status",
    "lint-wiki",
    "po-clarify",
    "po-handoff",
    "po-intake",
    "po-specify",
    "prep-sprint",
    "setup-project",
    "wiki-app",
    "wiki-blockers",
    "wiki-owner",
    "wiki-query",
    "wiki-show",
)

COMMON_REFERENCES = (
    "knowledge/wiki/CONNECTED.md",
    "knowledge/wiki/SCHEMA.md",
)
# Skills that read or change feature pages, the status and owner lifecycle or the
# advisory files also read the lifecycle protocol; the other skills keep the core only.
LIFECYCLE_REFERENCE = "knowledge/wiki/LIFECYCLE.md"
LIFECYCLE_SKILLS = frozenset(
    {
        "board-review",
        "design-clarify",
        "design-handoff",
        "design-intake",
        "design-start",
        "dev-clarify",
        "dev-done",
        "dev-start",
        "feature-reopen",
        "feature-status",
        "lint-wiki",
        "po-clarify",
        "po-handoff",
        "po-intake",
        "po-specify",
        "prep-sprint",
        "wiki-blockers",
    }
)
REFERENCE_GROUPS = {
    "intake": (
        "knowledge/intake/README.md",
        "knowledge/intake/pending/PO_BRIEF_TEMPLATE.md",
        "knowledge/intake/pending/DESIGN_HANDOFF_TEMPLATE.md",
    ),
    "features": ("knowledge/wiki/features/_FORMAT.md",),
    "design": ("knowledge/wiki/design/_FORMAT.md",),
    "requirements": ("knowledge/wiki/app-requirements/_FORMAT.md",),
    "api": ("knowledge/wiki/api-contracts/_FORMAT.md",),
    "business": ("knowledge/wiki/business-rules/_FORMAT.md",),
    "personas": ("knowledge/wiki/personas/_FORMAT.md",),
    "decisions": ("knowledge/wiki/decisions/_FORMAT.md",),
    "advisory": ("knowledge/wiki/advisory/_FORMAT.md",),
}
SKILL_REFERENCE_GROUPS = {
    "ask": ("features",),
    "audit-feature": ("features", "intake"),
    "board-review": ("features", "advisory"),
    "design-clarify": ("features", "design"),
    "design-handoff": ("features", "design", "requirements", "api"),
    "design-intake": ("intake", "features", "design"),
    "design-start": ("features",),
    "dev-clarify": ("features", "requirements"),
    "dev-done": ("features", "design", "requirements", "api"),
    "dev-start": ("features", "design", "requirements", "api"),
    "feature-reopen": ("features", "design", "requirements", "api"),
    "feature-status": ("features", "design", "requirements", "api", "business", "personas", "decisions", "advisory"),
    "lint-wiki": ("features", "design", "requirements", "api", "business", "personas", "decisions", "advisory"),
    "po-clarify": ("features",),
    "po-handoff": ("features", "advisory"),
    "po-intake": ("intake", "features", "business", "personas", "advisory"),
    "po-specify": ("features",),
    "prep-sprint": ("features", "requirements"),
    "setup-project": ("intake", "features", "business", "personas", "decisions", "advisory"),
    "wiki-app": ("features", "requirements"),
    "wiki-blockers": ("features", "design", "requirements", "api", "business", "personas", "decisions", "advisory"),
    "wiki-owner": ("features",),
    "wiki-query": ("features", "design", "requirements", "api", "business", "personas", "decisions", "advisory"),
    "wiki-show": ("features", "design", "requirements", "api", "business", "personas", "decisions", "advisory"),
}
WORKSPACE_STATE_FILES = {
    "knowledge/wiki/SETTINGS.md",
    "knowledge/wiki/WIKI_REPORT.md",
    "knowledge/wiki/index.md",
    "knowledge/wiki/log.md",
    "knowledge/wiki/advisory/BOARD.md",
    "knowledge/wiki/advisory/PROJECT_FOUNDATION.md",
}
_FRONTMATTER = re.compile(r"\A---\s*\r?\n(.*?)\r?\n---(?:\r?\n|\Z)", re.DOTALL)
_CONNECTED_SECTION = re.compile(r"(?m)^## Connected board workflow\s*\r?\n")
_NEXT_HEADING = re.compile(r"(?m)^## ")


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _read_template(relative_path: str) -> str:
    return (ROOT / "template" / Path(relative_path)).read_text(encoding="utf-8")


def _render_text(source: str, label: str, **context: Any) -> str:
    try:
        rendered = Environment(undefined=StrictUndefined, autoescape=False, keep_trailing_newline=True).from_string(source).render(**context)
    except Exception as exc:
        raise ValueError(f"Unable to render {label} without project-specific data: {exc}") from exc
    if "{{" in rendered or "{%" in rendered or "{#" in rendered:
        raise ValueError(f"Unresolved Jinja expression in packaged source {label}.")
    return rendered


def _render(relative_path: str) -> str:
    return _render_text(_read_template(relative_path), relative_path)


def _skill_metadata(content: str, expected_name: str, source_path: str) -> str:
    match = _FRONTMATTER.match(content)
    if not match:
        raise ValueError(f"Codex skill {source_path} is missing YAML frontmatter.")
    try:
        metadata = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        raise ValueError(f"Codex skill {source_path} has invalid frontmatter: {exc}") from exc
    if not isinstance(metadata, dict) or metadata.get("name") != expected_name:
        raise ValueError(f"Codex skill {source_path} must declare name {expected_name!r}.")
    description = metadata.get("description")
    if not isinstance(description, str) or not description.strip():
        raise ValueError(f"Codex skill {source_path} must declare a non-empty description.")
    return description.strip()


def _connected_pointers(agents: str, claude: str) -> tuple[str, str]:
    """The root pointer of a workflow workspace, and the one of a knowledge root.

    Both come from the one "Connected board workflow" section. Its
    ``knowledge_root`` condition adds the knowledge-root paragraph, so the two
    pointers cannot drift apart.
    """

    def extract(text: str, surface: str) -> str:
        heading = _CONNECTED_SECTION.search(text)
        if not heading:
            raise ValueError(f"{surface} root guidance is missing the Connected board workflow section.")
        next_heading = _NEXT_HEADING.search(text, heading.end())
        body = text[heading.end() : next_heading.start() if next_heading else len(text)].strip()
        return body

    agents_body = extract(agents, "Codex")
    claude_body = extract(claude, "Claude")
    if agents_body != claude_body:
        raise ValueError("Connected workflow pointers must match between template/AGENTS.md.jinja and template/CLAUDE.md.jinja.")
    pointers = [
        f"# Prism workspace guidance\n\n{_render_text(agents_body, 'the Connected board workflow section', **context)}\n"
        for context in ({}, {"knowledge_root": True})
    ]
    return pointers[0], pointers[1]


def _read_existing_asset() -> dict[str, Any] | None:
    """Read the checked-in asset so its digests of earlier shipped files can be carried forward."""

    if not ASSET_PATH.exists():
        return None
    try:
        existing = json.loads(ASSET_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Unable to read the existing workflow asset, whose digest history must not be lost: {exc}") from exc
    if not isinstance(existing, dict):
        raise ValueError("The existing workflow asset is not a JSON object, so its digest history cannot be kept.")
    return existing


def _digest_history(
    existing: dict[str, Any] | None,
    files_by_path: dict[str, dict[str, str]],
    pointer_variants: dict[str, dict[str, str]],
) -> dict[str, list[str]]:
    """Return every digest the installer treats as an unmodified earlier copy of a Prism-owned file.

    History is append-only: the earlier digests stay, and the content the
    existing asset carried joins them whenever the rebuilt content differs.
    """

    history: dict[str, list[str]] = {}

    def remember(path: str, digest: str) -> None:
        digests = history.setdefault(path, [])
        if digest not in digests:
            digests.append(digest)

    if existing is not None:
        recorded = existing.get("previous_digests", {})
        if not isinstance(recorded, dict):
            raise ValueError("The existing workflow asset has an invalid digest history.")
        for path, digests in recorded.items():
            if not isinstance(path, str) or not isinstance(digests, list) or any(not isinstance(item, str) for item in digests):
                raise ValueError(f"The existing workflow asset has an invalid digest history for {path!r}.")
            history.setdefault(path, [])
            for digest in digests:
                remember(path, digest)
        shipped_files = {
            item["path"]: item["content"]
            for item in existing.get("files", [])
            if isinstance(item, dict) and isinstance(item.get("path"), str) and isinstance(item.get("content"), str)
        }
        for path in existing.get("bootstrap_paths", []):
            content = shipped_files.get(path)
            if content is not None and (path not in files_by_path or _sha256(content) != files_by_path[path]["digest"]):
                remember(path, _sha256(content))
        # A root pointer has one shipped form per variant (workflow workspace, knowledge root).
        # Every form the existing asset carried joins the history unless it is still shipped.
        current_pointer_digests: dict[str, set[str]] = {}
        for variant in pointer_variants.values():
            for name, content in variant.items():
                current_pointer_digests.setdefault(name, set()).add(_sha256(content))
        for key in pointer_variants:
            shipped_pointers = existing.get(key)
            if isinstance(shipped_pointers, dict):
                for name, content in shipped_pointers.items():
                    if isinstance(content, str) and name in current_pointer_digests and _sha256(content) not in current_pointer_digests[name]:
                        remember(name, _sha256(content))
    return {path: history[path] for path in sorted(history)}


def build_asset() -> dict[str, Any]:
    from prism_cli.wiki_transitions import ACTION_SPECS

    files_by_path: dict[str, dict[str, str]] = {}

    def add_file(path: str, content: str) -> None:
        existing = files_by_path.get(path)
        item = {"path": path, "content": content, "digest": _sha256(content)}
        if existing is not None and existing != item:
            raise ValueError(f"Generated workflow asset has different contents for {path}.")
        files_by_path[path] = item

    action_map: dict[str, list[str]] = {}
    for spec in ACTION_SPECS:
        action_map.setdefault(spec.command, []).append(spec.action)

    skills: list[dict[str, Any]] = []
    for name in SKILL_NAMES:
        codex_source = f".agents/skills/{name}/SKILL.md.jinja"
        claude_source = f".claude/commands/{name}.md.jinja"
        codex_path = f".agents/skills/{name}/SKILL.md"
        claude_path = f".claude/commands/{name}.md"
        codex_content = _render(codex_source)
        claude_content = _render(claude_source)
        description = _skill_metadata(codex_content, name, codex_source)
        add_file(codex_path, codex_content)
        add_file(claude_path, claude_content)

        reference_paths = [*COMMON_REFERENCES, *((LIFECYCLE_REFERENCE,) if name in LIFECYCLE_SKILLS else ()), claude_path]
        for group in SKILL_REFERENCE_GROUPS[name]:
            reference_paths.extend(REFERENCE_GROUPS[group])
        reference_paths = list(dict.fromkeys(reference_paths))
        state_references = WORKSPACE_STATE_FILES.intersection(reference_paths)
        if state_references:
            raise ValueError(
                f"Workflow skill {name} must read current workspace state through the live service: {', '.join(sorted(state_references))}."
            )
        skills.append(
            {
                "name": name,
                "description": description,
                "instructions_path": codex_path,
                "reference_paths": reference_paths,
                "actions": action_map.get(name, []),
            }
        )

    bootstrap_paths: list[str] = []
    knowledge_root = ROOT / "template" / "knowledge"
    for source_path in sorted(knowledge_root.rglob("*"), key=lambda item: item.as_posix()):
        if source_path.is_symlink() or not source_path.is_file():
            continue
        relative = source_path.relative_to(knowledge_root).as_posix()
        workspace_path = f"knowledge/{relative}"
        content = source_path.read_text(encoding="utf-8")
        if source_path.name == ".gitkeep":
            content = ""
        add_file(workspace_path, content)
        bootstrap_paths.append(workspace_path)

    # The selected section is deliberately static even though the surrounding
    # root templates contain project-specific Copier expressions.
    agents_root = _read_template("AGENTS.md.jinja")
    claude_root = _read_template("CLAUDE.md.jinja")
    pointer, knowledge_root_pointer = _connected_pointers(agents_root, claude_root)
    guidance_pointers = {"AGENTS.md": pointer, "CLAUDE.md": pointer}
    knowledge_root_pointers = {"AGENTS.md": knowledge_root_pointer, "CLAUDE.md": knowledge_root_pointer}

    asset: dict[str, Any] = {
        "version": "1",
        "skills": skills,
        "files": [files_by_path[path] for path in sorted(files_by_path)],
        "bootstrap_paths": bootstrap_paths,
        "guidance_pointers": guidance_pointers,
        "knowledge_root_pointers": knowledge_root_pointers,
        "previous_digests": _digest_history(_read_existing_asset(), files_by_path, {"guidance_pointers": guidance_pointers, "knowledge_root_pointers": knowledge_root_pointers}),
    }
    canonical = json.dumps(asset, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    asset["asset_digest"] = hashlib.sha256(canonical).hexdigest()
    return asset


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if the checked-in asset differs from its maintained sources.")
    args = parser.parse_args()
    try:
        expected = json.dumps(build_asset(), ensure_ascii=False, indent=2) + "\n"
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"Workflow asset build failed: {exc}", file=sys.stderr)
        return 1

    if args.check:
        try:
            current = ASSET_PATH.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"Workflow asset is missing: {exc}", file=sys.stderr)
            return 1
        if current != expected:
            print("prism_cli/assets/workflow-v1.json is out of date; run scripts/build-workflow-assets.py.", file=sys.stderr)
            return 1
        print("PASS: workflow-v1.json matches maintained template skill and knowledge sources")
        return 0

    ASSET_PATH.parent.mkdir(parents=True, exist_ok=True)
    ASSET_PATH.write_text(expected, encoding="utf-8", newline="\n")
    print(f"Wrote {ASSET_PATH.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
