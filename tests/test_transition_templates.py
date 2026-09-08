from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SURFACE_PATHS = {
    "codex": REPO_ROOT / "template" / ".agents" / "skills" / "po-handoff" / "SKILL.md.jinja",
    "claude": REPO_ROOT / "template" / ".claude" / "commands" / "po-handoff.md.jinja",
}
ACTION_SURFACE_PATHS = {
    "po-specify": {
        "codex": REPO_ROOT / "template" / ".agents" / "skills" / "po-specify" / "SKILL.md.jinja",
        "claude": REPO_ROOT / "template" / ".claude" / "commands" / "po-specify.md.jinja",
    },
    "po-handoff": SURFACE_PATHS,
    "design-start": {
        "codex": REPO_ROOT / "template" / ".agents" / "skills" / "design-start" / "SKILL.md.jinja",
        "claude": REPO_ROOT / "template" / ".claude" / "commands" / "design-start.md.jinja",
    },
    "design-handoff": {
        "codex": REPO_ROOT / "template" / ".agents" / "skills" / "design-handoff" / "SKILL.md.jinja",
        "claude": REPO_ROOT / "template" / ".claude" / "commands" / "design-handoff.md.jinja",
    },
    "dev-start": {
        "codex": REPO_ROOT / "template" / ".agents" / "skills" / "dev-start" / "SKILL.md.jinja",
        "claude": REPO_ROOT / "template" / ".claude" / "commands" / "dev-start.md.jinja",
    },
    "dev-done": {
        "codex": REPO_ROOT / "template" / ".agents" / "skills" / "dev-done" / "SKILL.md.jinja",
        "claude": REPO_ROOT / "template" / ".claude" / "commands" / "dev-done.md.jinja",
    },
    "feature-reopen": {
        "codex": REPO_ROOT / "template" / ".agents" / "skills" / "feature-reopen" / "SKILL.md.jinja",
        "claude": REPO_ROOT / "template" / ".claude" / "commands" / "feature-reopen.md.jinja",
    },
}
ACTION_TRANSITIONS = {
    "po-specify": ("raw", "po", "specified", "po"),
    "po-handoff": ("specified", "po", "ready-for-design", "designer"),
    "design-start": ("ready-for-design", "designer", "in-design", "designer"),
    "design-handoff": ("in-design", "designer", "ready-for-dev", "dev"),
    "dev-start": ("ready-for-dev", "dev", "in-dev", "dev"),
    "dev-done": ("in-dev", "dev", "done", "none"),
    "feature-reopen": ("done", "none", "specified", "po"),
}
CONTEXT_PATHS = (
    REPO_ROOT / "template" / "AGENTS.md.jinja",
    REPO_ROOT / "template" / "CLAUDE.md.jinja",
    REPO_ROOT / "template" / ".cursor" / "rules" / "wiki.mdc.jinja",
    REPO_ROOT / "template" / "docs" / "ai-agents.md.jinja",
)


class TransitionTemplateContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sources = {name: path.read_text(encoding="utf-8") for name, path in SURFACE_PATHS.items()}
        cls.action_sources = {
            action: {surface: path.read_text(encoding="utf-8") for surface, path in paths.items()}
            for action, paths in ACTION_SURFACE_PATHS.items()
        }

    def test_both_surfaces_describe_the_same_supported_action(self) -> None:
        for name, text in self.sources.items():
            with self.subTest(surface=name):
                self.assertIn("specified", text)
                self.assertIn("<!-- prism:po-handoff-contract:v1 -->", text)
                self.assertIn("owner: po", text)
                self.assertIn("ready-for-design", text)
                self.assertIn("owner: designer", text)
                self.assertIn("exactly one", text)
                self.assertIn("knowledge/wiki/features/[F-XXX]-[slug].md", text)
                self.assertIn("raw", text)
                self.assertIn("po-specify", text)
                self.assertIn("unsupported", text)
                self.assertNotIn("ready-for-dev form", text)

    def test_both_surfaces_preserve_preflight_capability_fallback(self) -> None:
        invocation = "prism wiki transition-preflight F-XXX [path] --action po-handoff --json"
        for name, text in self.sources.items():
            with self.subTest(surface=name):
                self.assertIn(invocation, text)
                self.assertRegex(text, r"common envelope\s+schema\s+version 1")
                self.assertIn("transition-preflight", text)
                self.assertRegex(text, r"graph\s+capability")
                self.assertIn("po-handoff", text)
                self.assertIn("version", text)
                self.assertIn("alone", text)
                self.assertIn("direct-file", text)
                self.assertIn("copy-only", text)
                for field in (
                    "schema_version == 1",
                    'command == "wiki transition-preflight"',
                    "facts.requested_action",
                    "facts.transition_capability.version",
                    "facts.transition_capability.snapshot.fingerprint",
                    "facts.transition_capability.snapshot",
                    "facts.transition.version",
                    "facts.transition.action",
                    "facts.transition.invocations",
                    "classification == \"ready\"",
                ):
                    self.assertIn(field, text)

    def test_preflight_copy_scope_preserves_handoff_write_authority(self) -> None:
        for name, text in self.sources.items():
            with self.subTest(surface=name):
                normalized = re.sub(r"\s+", " ", text)
                self.assertIn("The preflight is copy-only and never authorizes a write.", normalized)
                self.assertNotIn("This command is copy-only and cannot authorize a write.", normalized)
                self.assertIn("after explicit confirmation", normalized)
                self.assertRegex(normalized, r"(Write only after confirmation|final handoff confirmation)")
                self.assertIn("update the feature", normalized)

    def test_both_surfaces_require_source_reread_and_factual_completeness(self) -> None:
        required = (
            "reread",
            "fingerprint",
            "## User story",
            "meaningful",
            "frontmatter `platforms`",
            "## Platform scope",
            "open questions",
            "non-blank",
            "advisory-skip-reason",
        )
        for name, text in self.sources.items():
            with self.subTest(surface=name):
                for fragment in required:
                    self.assertIn(fragment, text)

    def test_confirmation_and_skip_proposal_precede_writes(self) -> None:
        for name, text in self.sources.items():
            with self.subTest(surface=name):
                normalized = re.sub(r"\s+", " ", text)
                confirmation = normalized.index("final handoff confirmation")
                self.assertLess(normalized.index("proposal"), confirmation)
                self.assertLess(confirmation, normalized.index("update the feature", confirmation))
                self.assertLess(normalized.index("reread"), confirmation)
                self.assertIn("declines", normalized)
                self.assertIn("no", normalized[normalized.index("declines") : normalized.index("declines") + 260].lower())
                self.assertIn("proposed", normalized)
                self.assertIn("current", normalized)
                self.assertIn("unchanged", normalized)

    def test_surface_invocation_usage_matches(self) -> None:
        self.assertIn("$po-handoff [F-XXX]", self.sources["codex"])
        self.assertIn("/po-handoff [F-XXX]", self.sources["claude"])
        self.assertIn("board-review F-XXX", self.sources["codex"])
        self.assertIn("board-review F-XXX", self.sources["claude"])

    def test_all_lifecycle_surfaces_have_matching_markers_guards_and_write_protocol(self) -> None:
        for action, surfaces in self.action_sources.items():
            source_status, source_owner, target_status, target_owner = ACTION_TRANSITIONS[action]
            command = "feature-reopen" if action == "feature-reopen" else action
            marker = f"<!-- prism:{command}-contract:v1 -->"
            for surface, text in surfaces.items():
                with self.subTest(action=action, surface=surface):
                    normalized = re.sub(r"\s+", " ", text).lower()
                    invocation = (
                        f"{'$' if surface == 'codex' else '/'}feature-reopen [F-XXX] [specified|in-design|in-dev]"
                        if action == "feature-reopen"
                        else f"{'$' if surface == 'codex' else '/'}{action} [F-XXX]"
                    )
                    for fragment in (
                        marker,
                        invocation,
                        source_status,
                        source_owner,
                        target_status,
                        target_owner,
                        "exact",
                        "reread",
                        "confirmation",
                        "write",
                        "cancel",
                        "partial",
                        "copy-only",
                    ):
                        self.assertIn(fragment.lower(), normalized)
                    self.assertIn("preflight", normalized)
                    self.assertIn("version 2", normalized)

            if action == "feature-reopen":
                combined = "\n".join(surfaces.values())
                for target in ("specified", "in-design", "in-dev", "reopen-spec", "reopen-design", "reopen-dev"):
                    self.assertIn(target, combined)

    def test_po_specify_authors_or_preserves_structured_body(self) -> None:
        required_sections = (
            "## Summary",
            "## User story",
            "## Acceptance criteria",
            "## Platform scope",
            "## Open questions",
            "## Design",
            "## Related features",
            "## API surface",
            "## Board review summary",
            "## Post-ship notes",
        )
        for surface, text in self.action_sources["po-specify"].items():
            with self.subTest(surface=surface):
                normalized = re.sub(r"\s+", " ", text).lower()
                for section in required_sections:
                    self.assertIn(section.lower(), normalized)
                for fragment in (
                    "supported facts",
                    "owned questions",
                    "body diff",
                    "metadata",
                    "already",
                    "preserve",
                    "unverified status-only",
                ):
                    self.assertIn(fragment.lower(), normalized)
                self.assertNotIn("stop and report that this action cannot perform a status-only promotion", normalized)
                self.assertNotIn("raw source does not already satisfy", normalized)

    def test_schema_defines_delivery_revalidation_and_reopen_contract(self) -> None:
        schema = (REPO_ROOT / "template" / "knowledge" / "wiki" / "SCHEMA.md").read_text(encoding="utf-8")
        feature_format = (REPO_ROOT / "template" / "knowledge" / "wiki" / "features" / "_FORMAT.md").read_text(encoding="utf-8")
        for text in (schema, feature_format):
            with self.subTest(document="schema" if text is schema else "feature-format"):
                for fragment in (
                    "revalidation",
                    "specification",
                    "implementation",
                    "tests",
                    "release",
                    "design: not-applicable",
                    "design-exemption-reason",
                    "## Delivery evidence",
                    "| Platform | Implementation | Tests | Release |",
                    "## Reopen history",
                    "Prior completion/release evidence",
                ):
                    self.assertIn(fragment, text)
        self.assertIn("After confirmation, reread", schema)
        self.assertIn("version 2", schema)
        self.assertIn("target_owner", schema)

    def test_context_surfaces_list_new_actions_without_cross_surface_requirement(self) -> None:
        for path in CONTEXT_PATHS:
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path):
                for action in ("po-specify", "design-start", "dev-start", "feature-reopen"):
                    self.assertIn(action, text)
                self.assertIn("selected", text)
                self.assertIn("optional", text)
                self.assertNotIn("Both generated handoff files", text)
                self.assertNotIn("must each contain", text)

    def test_contract_marker_is_scoped_to_selected_surface(self) -> None:
        self.assertIn("selected Codex skill", self.sources["codex"])
        self.assertIn("Claude command is an optional", self.sources["codex"])
        self.assertIn("selected Claude command", self.sources["claude"])
        self.assertIn("Codex skill is an optional", self.sources["claude"])

        for path in CONTEXT_PATHS:
            with self.subTest(path=path):
                text = path.read_text(encoding="utf-8")
                self.assertIn("selected", text)
                self.assertIn("optional", text)
                self.assertNotIn("Both generated handoff files", text)
                self.assertNotIn("must each contain", text)

    @unittest.skipUnless(shutil.which("copier"), "Copier is required for rendered template checks")
    def test_rendered_surfaces_have_no_template_residue(self) -> None:
        with tempfile.TemporaryDirectory(prefix="prism-transition-template-") as temp_dir:
            destination = Path(temp_dir) / "generated"
            result = subprocess.run(
                [
                    "copier",
                    "copy",
                    "--trust",
                    "--defaults",
                    "--data",
                    "project_name=Transition Contract",
                    "--data",
                    "project_slug=transition-contract",
                    "--data",
                    "platforms=[backend]",
                    "--data",
                    "auth_methods=[password]",
                    str(REPO_ROOT),
                    str(destination),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode:
                self.fail(f"Copier generation failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")

            for action, paths in ACTION_SURFACE_PATHS.items():
                command = "feature-reopen" if action == "feature-reopen" else action
                for surface in ("codex", "claude"):
                    path = (
                        destination / ".agents" / "skills" / command / "SKILL.md"
                        if surface == "codex"
                        else destination / ".claude" / "commands" / f"{command}.md"
                    )
                    with self.subTest(action=action, surface=surface):
                        rendered = path.read_text(encoding="utf-8")
                        self.assertNotIn("{{", rendered)
                        self.assertNotIn("{%", rendered)
                        self.assertIn(f"<!-- prism:{command}-contract:v1 -->", rendered)
                        self.assertIn("## ", rendered)
                        self.assertIn("confirmation", rendered)
            for path in (
                destination / "knowledge" / "wiki" / "SCHEMA.md",
                destination / "knowledge" / "wiki" / "features" / "_FORMAT.md",
                destination / "CONTEXT.md",
            ):
                with self.subTest(path=path):
                    rendered = path.read_text(encoding="utf-8")
                    self.assertNotIn("{{", rendered)
                    self.assertNotIn("{%", rendered)
                    self.assertIn("revalidation", rendered)
