"""Graph facts over the Prism wiki: nodes, evidence-carrying edges, and renderers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from prism_cli.status import detect_setup_state, list_queue_items
from prism_cli.wiki_lint import WIKI_BLOCKER_CODES, lint_wiki
from prism_cli.wiki_links import NON_PAGE_FILENAMES, markdown_files, page_references_feature
from prism_cli.wiki_model import (
    VALID_PLATFORM_IDS,
    parse_open_question_rows,
    read_feature_pages,
    read_markdown_page,
    read_platform_requirement_pages,
)
from prism_cli.wiki_query import build_envelope


LIFECYCLE_STAGES = ["raw", "specified", "ready-for-design", "in-design", "ready-for-dev", "in-dev", "done"]

NODE_TYPES = {
    "feature",
    "persona",
    "business-rule",
    "design",
    "platform-requirement",
    "api-contract",
    "decision",
    "advisory-review",
    "platform",
}

EDGE_KINDS = {
    "targets",
    "has-requirement",
    "has-design",
    "has-contract",
    "has-review",
    "constrained-by",
    "serves",
    "related",
    "links-to",
}

_ID_DIRECTORIES = {
    "persona": ("personas", "persona"),
    "business-rule": ("business-rules", "rule"),
    "decision": ("decisions", "decision"),
}
_PATH_ID_DIRECTORIES = {
    "design": ("design", "design"),
    "api-contract": ("api-contracts", "api"),
    "advisory-review": ("advisory", "review"),
}

RELATED_SECTION_PATTERN = re.compile(r"^##\s+related features\s*$", re.IGNORECASE)
FEATURE_ID_PATTERN = re.compile(r"\bF-\d+\b")
MARKDOWN_LINK_PATTERN = re.compile(r"\[[^\]]*\]\(([^)#\s]+\.md)\)")


@dataclass(frozen=True)
class GraphNode:
    id: str
    type: str
    title: str
    path: str | None
    status: str | None = None
    owner: str | None = None
    advisory_review: str | None = None
    health: str = "ok"
    open_questions: tuple[tuple[str, str, str, str], ...] | None = None  # (number, question, owner, status)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"id": self.id, "type": self.type, "title": self.title, "path": self.path, "health": self.health}
        if self.status is not None:
            data["status"] = self.status
        if self.owner is not None:
            data["owner"] = self.owner
        if self.advisory_review is not None:
            data["advisory_review"] = self.advisory_review
        if self.open_questions is not None:
            data["open_questions"] = [
                {"number": number, "question": question, "owner": owner, "status": status}
                for number, question, owner, status in self.open_questions
            ]
        return data


@dataclass(frozen=True)
class GraphEdge:
    source: str
    target: str
    kind: str
    evidence: str

    def to_dict(self) -> dict[str, str]:
        return {"source": self.source, "target": self.target, "kind": self.kind, "evidence": self.evidence}


def build_graph(root: Path) -> dict[str, Any]:
    workspace_root = root.expanduser().resolve()
    wiki_root = workspace_root / "knowledge" / "wiki"
    lint_result = lint_wiki(workspace_root)

    nodes, pages_by_id, path_to_id = _collect_nodes(wiki_root)
    edges, dangling = _collect_edges(wiki_root, nodes, pages_by_id, path_to_id)

    edged_platforms = {edge.target for edge in edges if edge.target.startswith("platform:")}
    nodes = {
        node_id: node
        for node_id, node in nodes.items()
        if node.type != "platform" or node_id in edged_platforms
    }
    edges = [edge for edge in edges if edge.source in nodes and edge.target in nodes]

    # Blocker diagnostics describe workflow state, not page integrity — they
    # surface as blocker badges, never as node health.
    health_by_path: dict[str, str] = {}
    for diagnostic in lint_result.diagnostics:
        if diagnostic.code in WIKI_BLOCKER_CODES:
            continue
        current = health_by_path.get(diagnostic.path)
        if diagnostic.severity == "error" or current == "error":
            health_by_path[diagnostic.path] = "error"
        elif current != "error":
            health_by_path[diagnostic.path] = "warning"

    healthy_nodes = [
        GraphNode(
            id=node.id,
            type=node.type,
            title=node.title,
            path=node.path,
            status=node.status,
            owner=node.owner,
            advisory_review=node.advisory_review,
            health=health_by_path.get(node.path or "", "ok"),
            open_questions=node.open_questions,
        )
        for node in nodes.values()
    ]

    sorted_nodes = sorted(healthy_nodes, key=lambda node: (node.type, node.id))
    sorted_edges = sorted(set(edges), key=lambda edge: (edge.source, edge.target, edge.kind))

    intake_root = workspace_root / "knowledge" / "intake"
    facts = {
        "node_count": len(sorted_nodes),
        "edge_count": len(sorted_edges),
        "nodes": [node.to_dict() for node in sorted_nodes],
        "edges": [edge.to_dict() for edge in sorted_edges],
        "dangling_references": dangling,
        "setup_state": detect_setup_state(workspace_root, lint_result),
        "intake": {
            "pending": list_queue_items(intake_root / "pending"),
            "quarantined": list_queue_items(intake_root / "quarantined"),
        },
    }
    sources = [str(wiki_root)] + sorted(node.path for node in sorted_nodes if node.path)
    return build_envelope(workspace_root, "wiki graph", lint_result.diagnostics, facts, sources)


def _collect_nodes(wiki_root: Path) -> tuple[dict[str, GraphNode], dict[str, Any], dict[str, str]]:
    nodes: dict[str, GraphNode] = {}
    pages_by_id: dict[str, Any] = {}
    path_to_id: dict[str, str] = {}

    for feature in read_feature_pages(wiki_root):
        question_rows, _question_errors = parse_open_question_rows(feature.page.body)
        node = GraphNode(
            id=feature.feature_id,
            type="feature",
            title=feature.title,
            path=str(feature.page.path),
            status=feature.status,
            owner=feature.owner,
            advisory_review=feature.advisory_review,
            open_questions=tuple(
                (row["number"], row["question"], row["owner"], row["status"]) for row in question_rows
            ),
        )
        nodes[node.id] = node
        pages_by_id[node.id] = feature
        path_to_id[str(feature.page.path)] = node.id

    for node_type, (directory, prefix) in _ID_DIRECTORIES.items():
        for path in markdown_files(wiki_root / directory):
            if path.name in NON_PAGE_FILENAMES:
                continue
            page = read_markdown_page(path)
            raw_id = page.frontmatter.get("id")
            node_id = raw_id if isinstance(raw_id, str) else f"{prefix}:{path.stem}"
            title = page.frontmatter.get("title") or page.frontmatter.get("name")
            status = page.frontmatter.get("status")
            node = GraphNode(
                id=node_id,
                type=node_type,
                title=title if isinstance(title, str) else path.stem,
                path=str(path),
                status=status if isinstance(status, str) else None,
            )
            nodes[node.id] = node
            pages_by_id[node.id] = page
            path_to_id[str(path)] = node.id

    for node_type, (directory, prefix) in _PATH_ID_DIRECTORIES.items():
        for path in markdown_files(wiki_root / directory):
            if path.name in NON_PAGE_FILENAMES:
                continue
            page = read_markdown_page(path)
            node_id = f"{prefix}:{path.stem}"
            title = page.frontmatter.get("title")
            status = page.frontmatter.get("status")
            node = GraphNode(
                id=node_id,
                type=node_type,
                title=title if isinstance(title, str) else path.stem,
                path=str(path),
                status=status if isinstance(status, str) else None,
            )
            nodes[node.id] = node
            pages_by_id[node.id] = page
            path_to_id[str(path)] = node.id

    for requirement in read_platform_requirement_pages(wiki_root):
        path = requirement.page.path
        node_id = f"preq:{path.stem}"
        node = GraphNode(
            id=node_id,
            type="platform-requirement",
            title=path.stem,
            path=str(path),
            status=requirement.status,
        )
        nodes[node.id] = node
        pages_by_id[node.id] = requirement
        path_to_id[str(path)] = node.id

    for platform_id in sorted(VALID_PLATFORM_IDS):
        node_id = f"platform:{platform_id}"
        nodes[node_id] = GraphNode(id=node_id, type="platform", title=platform_id, path=None)

    return nodes, pages_by_id, path_to_id


def _collect_edges(
    wiki_root: Path,
    nodes: dict[str, GraphNode],
    pages_by_id: dict[str, Any],
    path_to_id: dict[str, str],
) -> tuple[list[GraphEdge], list[dict[str, str]]]:
    edges: list[GraphEdge] = []
    dangling: list[dict[str, str]] = []
    feature_ids = [node_id for node_id, node in nodes.items() if node.type == "feature"]

    def add(source: str, target: str, kind: str, evidence: str) -> None:
        if source == target:
            return
        edges.append(GraphEdge(source=source, target=target, kind=kind, evidence=evidence))

    for feature_id in feature_ids:
        feature = pages_by_id[feature_id]
        for platform_id in feature.platforms:
            if platform_id in VALID_PLATFORM_IDS:
                add(feature_id, f"platform:{platform_id}", "targets", "frontmatter-platforms")
        related_section = _section_text(feature.page.body, RELATED_SECTION_PATTERN)
        for match in FEATURE_ID_PATTERN.findall(related_section):
            if match == feature_id:
                continue
            if match in nodes:
                add(feature_id, match, "related", "related-features-section")
            else:
                dangling.append({"from": feature_id, "reference": match, "path": str(feature.page.path)})

    attachment_rules = {
        "design": "has-design",
        "api-contract": "has-contract",
        "advisory-review": "has-review",
        "platform-requirement": "has-requirement",
    }
    for node_id, node in nodes.items():
        kind = attachment_rules.get(node.type)
        if kind is None or node.path is None:
            continue
        page = pages_by_id.get(node_id)
        frontmatter = getattr(page, "frontmatter", None)
        if frontmatter is None and hasattr(page, "page"):
            frontmatter = page.page.frontmatter
        feature_ref = frontmatter.get("feature-id") if isinstance(frontmatter, dict) else None
        filename = Path(node.path).name
        if isinstance(feature_ref, str) and feature_ref in nodes:
            add(feature_ref, node_id, kind, "frontmatter-feature-id")
            continue
        if isinstance(feature_ref, str):
            dangling.append({"from": node_id, "reference": feature_ref, "path": node.path})
        prefix_match = FEATURE_ID_PATTERN.match(filename)
        if prefix_match and prefix_match.group(0) in nodes:
            add(prefix_match.group(0), node_id, kind, "filename-prefix")

    for node_id, node in nodes.items():
        if node.type not in ("business-rule", "persona") or node.path is None:
            continue
        page = pages_by_id[node_id]
        for feature_id in feature_ids:
            if page_references_feature(page.frontmatter, page.body, Path(node.path).name, feature_id):
                if node.type == "business-rule":
                    add(feature_id, node_id, "constrained-by", "body-reference")
                else:
                    add(node_id, feature_id, "serves", "body-reference")

    specific_pairs = {(edge.source, edge.target) for edge in edges}
    specific_pairs.update((edge.target, edge.source) for edge in edges)
    for node_id, node in nodes.items():
        if node.path is None:
            continue
        page = pages_by_id[node_id]
        body = page.body if hasattr(page, "body") else page.page.body
        for raw_target in MARKDOWN_LINK_PATTERN.findall(body):
            resolved = _resolve_link(Path(node.path).parent, raw_target, wiki_root)
            if resolved is None:
                continue
            target_id = path_to_id.get(resolved)
            if target_id is None:
                dangling.append({"from": node_id, "reference": raw_target, "path": node.path})
                continue
            if target_id == node_id or (node_id, target_id) in specific_pairs:
                continue
            edges.append(GraphEdge(source=node_id, target=target_id, kind="links-to", evidence="markdown-link"))

    return edges, dangling


def _section_text(body: str, heading_pattern: re.Pattern[str]) -> str:
    lines = body.splitlines()
    collected: list[str] = []
    in_section = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            if in_section:
                break
            in_section = bool(heading_pattern.match(stripped))
            continue
        if in_section:
            collected.append(line)
    return "\n".join(collected)


def _resolve_link(base_dir: Path, raw_target: str, wiki_root: Path) -> str | None:
    try:
        resolved = (base_dir / raw_target).resolve()
    except (OSError, ValueError):
        return None
    try:
        resolved.relative_to(wiki_root.resolve())
    except ValueError:
        return None
    return str(resolved)


# ---------------------------------------------------------------------------
# Mermaid rendering


def render_mermaid(envelope: dict[str, Any], view: str, feature_id: str | None = None, platform_id: str | None = None) -> str:
    nodes = envelope["facts"]["nodes"]
    edges = envelope["facts"]["edges"]
    blocked_ids = {fact.get("feature_id") for fact in envelope.get("blocker_facts", []) if fact.get("feature_id")}

    if view == "lifecycle":
        return _mermaid_lifecycle(nodes, blocked_ids)
    if view == "ego":
        return _mermaid_ego(nodes, edges, feature_id or "")
    if view == "platform":
        return _mermaid_platform(nodes, edges, platform_id or "")
    raise ValueError(f"Unknown mermaid view: {view}")


def _mermaid_id(node_id: str) -> str:
    return "n_" + re.sub(r"[^A-Za-z0-9_]", "_", node_id)


def _mermaid_label(text: str) -> str:
    """Sanitize one label fragment. Join fragments with _mermaid_multiline, never embed <br/> here."""
    cleaned = text.replace('"', "#quot;").replace("`", "").replace("|", "/").replace("<", "").replace(">", "")
    return cleaned.strip()


def _mermaid_multiline(*fragments: str) -> str:
    return "<br/>".join(_mermaid_label(fragment) for fragment in fragments if fragment)


_STAGE_CLASS = {
    "raw": "po",
    "specified": "po",
    "ready-for-design": "design",
    "in-design": "design",
    "ready-for-dev": "dev",
    "in-dev": "dev",
    "done": "done",
}


def _mermaid_lifecycle(nodes: list[dict[str, Any]], blocked_ids: set[str]) -> str:
    lines = ["flowchart LR"]
    class_lines: list[str] = []
    for stage in LIFECYCLE_STAGES:
        stage_features = [node for node in nodes if node["type"] == "feature" and node.get("status") == stage]
        if not stage_features:
            continue
        stage_id = "s_" + re.sub(r"[^A-Za-z0-9_]", "_", stage)
        lines.append(f'  subgraph {stage_id}["{_mermaid_label(stage)}"]')
        for node in stage_features:
            node_ref = _mermaid_id(node["id"])
            label = _mermaid_multiline(node["id"], str(node["title"]))
            lines.append(f'    {node_ref}["{label}"]')
            if node.get("health") != "ok":
                class_lines.append(f"  class {node_ref} broken")
            elif node["id"] in blocked_ids:
                class_lines.append(f"  class {node_ref} blocked")
            else:
                class_lines.append(f"  class {node_ref} {_STAGE_CLASS[stage]}")
        lines.append("  end")
    lines.extend(class_lines)
    lines.extend(
        [
            "  classDef po fill:#9ec5f4,stroke:#256abf,color:#0b0b0b",
            "  classDef design fill:#f5cf7e,stroke:#8a5c00,color:#0b0b0b",
            "  classDef dev fill:#7cd7b2,stroke:#0f7a55,color:#0b0b0b",
            "  classDef done fill:#8fd08f,stroke:#008300,color:#0b0b0b",
            "  classDef blocked fill:#fcfcfb,stroke:#d03b3b,stroke-width:3px,color:#0b0b0b",
            "  classDef broken fill:#fcfcfb,stroke:#898781,stroke-dasharray:6 4,color:#52514e",
        ]
    )
    return "\n".join(lines)


def _mermaid_ego(nodes: list[dict[str, Any]], edges: list[dict[str, Any]], feature_id: str) -> str:
    node_map = {node["id"]: node for node in nodes}
    center = node_map.get(feature_id)
    if center is None:
        return f'flowchart TD\n  missing["No feature page found for {_mermaid_label(feature_id)}"]'
    lines = ["flowchart TD"]
    center_ref = _mermaid_id(feature_id)
    center_label = _mermaid_multiline(feature_id, str(center["title"]))
    lines.append(f'  {center_ref}["{center_label}"]:::center')
    seen = {feature_id}
    for edge in edges:
        if feature_id not in (edge["source"], edge["target"]):
            continue
        other_id = edge["target"] if edge["source"] == feature_id else edge["source"]
        other = node_map.get(other_id)
        if other is None:
            continue
        other_ref = _mermaid_id(other_id)
        if other_id not in seen:
            label = _mermaid_multiline(other["type"], str(other["title"]))
            lines.append(f'  {other_ref}["{label}"]')
            seen.add(other_id)
        source_ref = _mermaid_id(edge["source"])
        target_ref = _mermaid_id(edge["target"])
        lines.append(f"  {source_ref} -->|{_mermaid_label(edge['kind'])}| {target_ref}")
    lines.append("  classDef center fill:#3987e5,stroke:#104281,color:#ffffff")
    return "\n".join(lines)


def _mermaid_platform(nodes: list[dict[str, Any]], edges: list[dict[str, Any]], platform_id: str) -> str:
    platform_node_id = f"platform:{platform_id}"
    node_map = {node["id"]: node for node in nodes}
    lines = ["flowchart LR"]
    platform_ref = _mermaid_id(platform_node_id)
    lines.append(f'  {platform_ref}(["{_mermaid_label(platform_id)}"]):::platform')
    for edge in edges:
        if edge["kind"] == "targets" and edge["target"] == platform_node_id:
            feature = node_map.get(edge["source"])
            if feature is None:
                continue
            feature_ref = _mermaid_id(feature["id"])
            label = _mermaid_multiline(feature["id"], str(feature["title"]), feature.get("status") or "")
            lines.append(f'  {feature_ref}["{label}"]')
            lines.append(f"  {feature_ref} --> {platform_ref}")
            for requirement_edge in edges:
                if requirement_edge["kind"] == "has-requirement" and requirement_edge["source"] == feature["id"]:
                    requirement = node_map.get(requirement_edge["target"])
                    if requirement is None or platform_id not in requirement["id"]:
                        continue
                    requirement_ref = _mermaid_id(requirement["id"])
                    status = requirement.get("status") or "unknown"
                    requirement_label = _mermaid_multiline("requirement", status)
                    lines.append(f'  {requirement_ref}["{requirement_label}"]')
                    lines.append(f"  {feature_ref} -.-> {requirement_ref}")
    lines.append("  classDef platform fill:#eb6834,stroke:#8f3a17,color:#ffffff")
    return "\n".join(lines)
