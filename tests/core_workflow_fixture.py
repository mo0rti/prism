"""Build the smallest product-neutral workspace for core workflow acceptance."""

from __future__ import annotations

from pathlib import Path

from prism_cli.wiki_transitions import ACTION_SPECS
from tests.manifest_fixtures import manifest_text


FEATURE_ID = "F-001"
FEATURE_SLUG = "document-review"
FEATURE_PATH = Path("knowledge/wiki/features/F-001-document-review.md")
INTAKE_ITEM = Path("knowledge/intake/pending/document-review-brief/brief.md")
PROCESSED_INTAKE_ITEM = Path("knowledge/intake/processed/document-review-brief/brief.md")


def create_core_workflow_fixture(root: Path) -> Path:
    """Create a minimal intake workspace under an empty temporary directory.

    The fixture has Prism's existing manifest and wiki contract, one pending
    neutral document-review brief, and empty lifecycle instruction surfaces so
    the shared read-only preflight API can evaluate every registered action.
    It deliberately has no Copier answers or application scaffold/build.
    """

    root = root.expanduser().resolve()
    if root.exists() and any(root.iterdir()):
        raise FileExistsError(f"Refusing to populate non-empty fixture root: {root}")
    root.mkdir(parents=True, exist_ok=True)

    wiki_root = root / "knowledge" / "wiki"
    (wiki_root / "features").mkdir(parents=True)
    (wiki_root / "app-requirements").mkdir()
    (root / "knowledge" / "intake" / "pending").mkdir(parents=True)
    (root / "knowledge" / "intake" / "processed").mkdir()

    # Match the small schema placeholders used by existing query/lifecycle
    # tests; behavior under test still comes from the canonical parser and
    # transition rules applied to the feature pages below.
    (wiki_root / "SCHEMA.md").write_text(
        "---\nschema-version: 1\n---\n"
        "# Wiki schema fixture\n\n"
        "Feature and evidence fields follow the template wiki schema.\n",
        encoding="utf-8",
    )
    (wiki_root / "LIFECYCLE.md").write_text(
        "---\nschema-version: 1\n---\n"
        "# Wiki lifecycle fixture\n\n"
        "Feature lifecycle and evidence fields follow the template lifecycle protocol.\n",
        encoding="utf-8",
    )
    (wiki_root / "SETTINGS.md").write_text(
        "---\nwiki-stale-after-days: 365\n---\n", encoding="utf-8"
    )
    (wiki_root / "index.md").write_text(
        "# Feature Status Board\n\n"
        "| ID | Feature | Status | Owner | Board Review |\n"
        "|----|---------|--------|-------|--------------|\n",
        encoding="utf-8",
    )
    (root / "prism.workspace.yml").write_text(
        manifest_text("Document review", ["backend"], slug="document-review"),
        encoding="utf-8",
    )

    # Current workspace identity checks compare declared platforms to their
    # directories. An empty scope marker satisfies that contract without a
    # generated application scaffold.
    app_marker = root / "backend" / ".gitkeep"
    app_marker.parent.mkdir()
    app_marker.write_text("", encoding="utf-8")

    intake_path = root / INTAKE_ITEM
    intake_path.parent.mkdir(parents=True)
    intake_path.write_text(
        "# Document review brief\n\n"
        "Review a document, summarize its key points, and record the review outcome.\n",
        encoding="utf-8",
    )

    _write_action_surfaces(root)
    return root


def _write_action_surfaces(root: Path) -> None:
    """Supply the markers preflight reads, without copying product instructions."""

    written_commands: set[str] = set()
    for spec in ACTION_SPECS:
        if spec.command in written_commands:
            continue
        written_commands.add(spec.command)
        marker = f"prism:{spec.command}-contract:v1"
        for role, relative in (
            ("codex", Path(f".agents/skills/{spec.command}/SKILL.md")),
            ("claude", Path(f".claude/commands/{spec.command}.md")),
        ):
            invocation = f"${spec.command} F-XXX" if role == "codex" else f"/{spec.command} F-XXX"
            if spec.command == "feature-reopen":
                invocation = f"{invocation} [target-status]"
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"<!-- {marker} -->\n{invocation}\n", encoding="utf-8")
