"""The template asks only for project identity, the app list, auth and the GitHub owner.

Deployment is a skill, not generated project files: a generated workspace carries no
`infra/`, no Wrangler or OpenNext files and no deploy job, and it carries the `deployment`
skill in both agent layers. Generation runs the real Copier against a copy of the working tree.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

from prism_cli import cli
from prism_cli.presets import PRESETS
from tests import real_temp  # noqa: F401

REPO_ROOT = Path(__file__).resolve().parents[1]
REMOVED_QUESTIONS = ("database", "supporting_services", "use_docker", "cloud_provider", "web_hosting")
SKILL_LAYERS = (".claude/skills/deployment", ".agents/skills/deployment")
DEPLOYMENT_FILE_NAMES = {"wrangler.jsonc", "open-next.config.ts", ".dev.vars.example", "azure-setup.md", "cloudflare-setup.md"}


def generate(destination: Path, platforms: list[str], extra_data: dict[str, str] | None = None) -> Path:
    data = {
        "project_name": "Scope Check",
        "platforms": "[" + ", ".join(platforms) + "]",
        "auth_methods": "[google, apple, facebook, microsoft, password]",
        **(extra_data or {}),
    }
    with cli.staged_template_path(str(REPO_ROOT)) as template:
        command = [sys.executable, "-m", "copier", "copy", "--trust", "--defaults"]
        for key, value in data.items():
            command.extend(["--data", f"{key}={value}"])
        command.extend([str(template), str(destination)])
        result = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise AssertionError(f"Copier failed for {platforms}:\n{result.stderr[-2000:]}")
    return destination


def relative_files(root: Path) -> list[str]:
    return sorted(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file())


class QuestionnaireTests(unittest.TestCase):
    def test_the_questionnaire_has_no_removed_question(self) -> None:
        config = yaml.safe_load((REPO_ROOT / "copier.yml").read_text(encoding="utf-8"))
        questions = [key for key in config if not key.startswith("_")]
        for removed in REMOVED_QUESTIONS:
            self.assertNotIn(removed, questions)
        self.assertEqual(
            ["project_name", "project_slug", "package_identifier", "description", "package_path", "ios_module_name", "platforms", "auth_methods", "github_org"],
            questions,
        )

    def test_no_question_default_or_preset_carries_a_removed_answer(self) -> None:
        from prism_cli.presets import DEFAULT_ANSWERS

        for removed in REMOVED_QUESTIONS:
            self.assertNotIn(removed, DEFAULT_ANSWERS)
            for preset in PRESETS:
                self.assertNotIn(removed, preset.answers)

    def test_template_conditions_do_not_read_a_removed_answer(self) -> None:
        pattern = re.compile(r"(\{%|\{\{)[^}]*\b(" + "|".join(REMOVED_QUESTIONS) + r")\b")
        offenders = []
        for path in [REPO_ROOT / "copier.yml", *sorted((REPO_ROOT / "template").rglob("*"))]:
            if not path.is_file() or path.suffix in {".jar", ".png", ".webp", ".ttf", ".otf", ".woff2"}:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if pattern.search(text):
                offenders.append(path.relative_to(REPO_ROOT).as_posix())
        self.assertEqual([], offenders)


class GeneratedWorkspaceTests(unittest.TestCase):
    """Each preset's workspace, plus the web-only and mobile-only shapes, generated once."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory(prefix="prism-scope-")
        cls.addClassCleanup(cls.temp.cleanup)
        root = Path(cls.temp.name)
        cls.platform_sets = {preset.slug: list(preset.answers["platforms"]) for preset in PRESETS}
        cls.platform_sets["web-only"] = ["web-user-app", "web-admin-portal"]
        cls.platform_sets["mobile-only"] = ["mobile-android", "mobile-ios"]
        cls.workspaces = {name: generate(root / name, platforms) for name, platforms in cls.platform_sets.items()}

    def test_no_workspace_carries_infra_or_hosting_files(self) -> None:
        for name, root in self.workspaces.items():
            with self.subTest(workspace=name):
                self.assertFalse((root / "infra").exists())
                self.assertFalse((root / "docs" / "deployment" / "cloudflare-setup.md").exists())
                self.assertFalse((root / "backend" / "docs" / "azure-setup.md").exists())
                for relative in relative_files(root):
                    if relative.startswith(SKILL_LAYERS):
                        continue
                    self.assertNotIn(Path(relative).name, DEPLOYMENT_FILE_NAMES, relative)
                    self.assertNotIn(".open-next", relative)

    def test_web_apps_do_not_depend_on_the_hosting_adapter(self) -> None:
        for name in ("backend-web", "web-only"):
            for app in ("web-user-app", "web-admin-portal"):
                with self.subTest(workspace=name, app=app):
                    package = json.loads((self.workspaces[name] / app / "package.json").read_text(encoding="utf-8"))
                    dependencies = {**package.get("dependencies", {}), **package.get("devDependencies", {})}
                    for hosting_package in ("@opennextjs/cloudflare", "wrangler", "esbuild"):
                        self.assertNotIn(hosting_package, dependencies)
                    for script in ("build:cloudflare", "preview", "deploy"):
                        self.assertNotIn(script, package["scripts"])
                    taskfile = (self.workspaces[name] / app / "Taskfile.yml").read_text(encoding="utf-8")
                    self.assertNotIn("cloudflare", taskfile.lower())
                    self.assertNotIn("deploy", taskfile)

    def test_generated_workflows_build_and_test_only(self) -> None:
        for name, root in self.workspaces.items():
            for workflow in sorted((root / ".github" / "workflows").glob("*.yml")):
                with self.subTest(workspace=name, workflow=workflow.name):
                    text = workflow.read_text(encoding="utf-8")
                    data = yaml.safe_load(text)
                    triggers = data.get("on", data.get(True))
                    self.assertNotIn("tags", triggers.get("push", {}))
                    for job_name, job in data["jobs"].items():
                        self.assertNotIn("deploy", job_name.lower())
                        self.assertNotIn("release", job_name.lower())
                        self.assertNotIn("environment", job)
                    self.assertNotIn("secrets.", text)
                    self.assertNotIn("wrangler", text)
                    self.assertNotIn("azure", text.lower())
                    self.assertNotIn("fastlane", text.lower())

    def test_docker_compose_is_present_exactly_when_a_backend_app_is(self) -> None:
        for name, root in self.workspaces.items():
            with self.subTest(workspace=name):
                has_backend = (root / "backend").is_dir()
                self.assertEqual("backend" in self.platform_sets[name], has_backend)
                self.assertEqual(has_backend, (root / "docker-compose.yml").is_file())
        compose = yaml.safe_load((self.workspaces["backend-only"] / "docker-compose.yml").read_text(encoding="utf-8"))
        self.assertEqual({"backend", "db"}, set(compose["services"]))
        self.assertIn("postgres", compose["services"]["db"]["image"])
        self.assertEqual({"pgdata": None}, compose["volumes"])

    def test_no_redis_support_is_generated(self) -> None:
        for name, root in self.workspaces.items():
            for relative in relative_files(root):
                if relative.startswith(SKILL_LAYERS) or relative.endswith((".jar", ".png", ".webp")):
                    continue
                with self.subTest(workspace=name, file=relative):
                    self.assertNotIn("redis", (root / relative).read_text(encoding="utf-8", errors="ignore").lower())

    def test_every_workspace_carries_the_deployment_skill_in_both_layers(self) -> None:
        for name, root in self.workspaces.items():
            for layer in SKILL_LAYERS:
                with self.subTest(workspace=name, layer=layer):
                    skill = (root / layer / "SKILL.md").read_text(encoding="utf-8")
                    self.assertTrue(skill.startswith("---\nname: deployment\n"))
                    self.assertIn("belong to the user and their agent", skill)
                    self.assertIn("worked example", skill)
        for name, root in self.workspaces.items():
            self.assertTrue((root / ".agents" / "skills" / "deployment" / "agents" / "openai.yaml").is_file())
            self.assertFalse((root / ".claude" / "skills" / "deployment" / "agents").exists())

    def test_skill_references_follow_the_apps_present(self) -> None:
        expectations = {
            "backend-only": {"azure", "azure-setup.md"},
            "backend-web": {"azure", "azure-setup.md", "cloudflare", "cloudflare-setup.md"},
            "backend-mobile": {"azure", "azure-setup.md", "mobile-store-release.md"},
            "web-only": {"cloudflare", "cloudflare-setup.md"},
            "mobile-only": {"mobile-store-release.md"},
        }
        for name, expected in expectations.items():
            for layer in SKILL_LAYERS:
                with self.subTest(workspace=name, layer=layer):
                    references = self.workspaces[name] / layer / "references"
                    self.assertEqual(expected, {child.name for child in references.iterdir()})

    def test_the_two_layers_hold_the_same_references(self) -> None:
        for name, root in self.workspaces.items():
            with self.subTest(workspace=name):
                claude = root / ".claude" / "skills" / "deployment"
                codex = root / ".agents" / "skills" / "deployment"
                claude_files = [f for f in relative_files(claude) if not f.startswith("agents/")]
                codex_files = [f for f in relative_files(codex) if not f.startswith("agents/")]
                self.assertEqual(claude_files, codex_files)
                for relative in claude_files:
                    self.assertEqual((claude / relative).read_bytes(), (codex / relative).read_bytes(), relative)

    def test_the_azure_example_is_rendered_for_the_project_and_keeps_its_scripts(self) -> None:
        references = self.workspaces["backend-web"] / ".claude" / "skills" / "deployment" / "references"
        scripts = sorted(path.name for path in (references / "azure").iterdir())
        self.assertEqual(
            [
                "00-setup-resource-group.sh", "01-setup-foundation.sh", "02-setup-database.sh", "03-setup-container-apps-env.sh",
                "04-setup-storage.sh", "05-build-and-push-images.sh", "06-deploy-backend.sh", "07-show-deployment-info.sh",
                "add-custom-domain.sh", "app-secrets.env.example", "azure-config.env.example", "check-secrets.sh", "cleanup.sh",
                "load-env-config.sh", "show-database-credentials.sh", "test-database-connection.sh", "update-backend.sh",
            ],
            scripts,
        )
        deploy = (references / "azure" / "06-deploy-backend.sh").read_text(encoding="utf-8")
        self.assertIn("JWT_ACCESS_TOKEN_EXPIRY=${JWT_ACCESS_TOKEN_EXPIRY:-3600}", deploy)
        self.assertIn("FACEBOOK_CLIENT_SECRET=secretref:facebook-client-secret", deploy)
        self.assertNotIn("{{", deploy)
        self.assertNotIn("{%", deploy)
        self.assertNotIn(b"\r\n", (references / "azure" / "06-deploy-backend.sh").read_bytes())
        wrangler = (references / "cloudflare" / "wrangler.web-user-app.jsonc").read_text(encoding="utf-8")
        self.assertIn('"name": "scope-check-web-user-app"', wrangler)
        self.assertTrue((references / "cloudflare" / "open-next.config.ts").is_file())

    def test_the_manifest_records_none_of_the_removed_answers(self) -> None:
        for name, root in self.workspaces.items():
            with self.subTest(workspace=name):
                manifest = yaml.safe_load((root / "prism.workspace.yml").read_text(encoding="utf-8"))
                answers = yaml.safe_load((root / ".copier-answers.yml").read_text(encoding="utf-8"))
                for removed in REMOVED_QUESTIONS:
                    self.assertNotIn(removed, manifest["project"])
                    self.assertNotIn(removed, answers)


class RemovedAnswerHandlingTests(unittest.TestCase):
    def test_copier_ignores_a_data_value_for_a_removed_question(self) -> None:
        """Copier accepts unknown `--data` keys and renders as if they were absent; Prism's own CLI rejects them."""

        with tempfile.TemporaryDirectory(prefix="prism-scope-ignored-") as temp_dir:
            root = Path(temp_dir)
            plain = generate(root / "plain", ["backend"])
            extra = generate(
                root / "extra",
                ["backend"],
                {"database": "mysql", "supporting_services": "[redis]", "use_docker": "false", "cloud_provider": "aws", "web_hosting": "vercel"},
            )
            self.assertEqual(relative_files(plain), relative_files(extra))
            for relative in ("docker-compose.yml", "backend/Dockerfile", ".env.example"):
                self.assertEqual((plain / relative).read_text(encoding="utf-8"), (extra / relative).read_text(encoding="utf-8"), relative)
            manifests = [yaml.safe_load((root_ / "prism.workspace.yml").read_text(encoding="utf-8")) for root_ in (plain, extra)]
            self.assertEqual(manifests[0]["project"], manifests[1]["project"])
            self.assertEqual(manifests[0]["apps"], manifests[1]["apps"])
            answers = yaml.safe_load((extra / ".copier-answers.yml").read_text(encoding="utf-8"))
            for removed in REMOVED_QUESTIONS:
                self.assertNotIn(removed, answers)


if __name__ == "__main__":
    unittest.main()
