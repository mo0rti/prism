"""The template asks only for project identity, the app list, auth and the GitHub owner.

Deployment is a skill, not generated project files: a generated workspace carries no
`infra/`, no Wrangler or OpenNext files and no deploy job, and it carries the `deployment`
skill in both agent layers. Generation runs the Prism CLI, which runs the real Copier against a
copy of the working tree: the workspace layer and each scaffolded app's pack.
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
from tests.layered_support import generate_default_apps

REPO_ROOT = Path(__file__).resolve().parents[1]
REMOVED_QUESTIONS = (
    "database",
    "supporting_services",
    "use_docker",
    "cloud_provider",
    "web_hosting",
    "auth_methods",
    "github_org",
    "ios_module_name",
    "package_path",
    "app_ids",
)
SKILL_LAYERS = (".claude/skills/deployment", ".agents/skills/deployment")
DEPLOYMENT_FILE_NAMES = {"wrangler.jsonc", "open-next.config.ts", ".dev.vars.example", "azure-setup.md", "cloudflare-setup.md"}


# A second nextjs-web app, for the workspaces that carry two web apps.
ADMIN_APP = {"id": "admin", "name": "Admin App", "stack": "nextjs-web", "repository": "workspace", "path": "admin", "audience": "internal", "generation": "scaffolded"}


def generate(destination: Path, apps: list[str]) -> Path:
    """A workspace of the default apps with these IDs (and `admin`, a second web app), generated through the CLI."""

    defaults = [app for app in apps if app != ADMIN_APP["id"]]
    extra = [ADMIN_APP] if ADMIN_APP["id"] in apps else []
    return generate_default_apps(destination, defaults, destination.parent, extra_apps=extra)


def generate_raw_workspace_layer(destination: Path, extra_data: dict[str, str] | None = None) -> Path:
    """The workspace layer of a one-backend workspace through raw Copier, with extra `--data` values."""

    data = {
        "project_name": "Scope Check",
        "stacks": "[spring-backend]",
        "apps": '[{"id": "backend", "name": "Backend", "stack": "spring-backend", "path": "backend", "audience": "", "port": 8080}]',
        **(extra_data or {}),
    }
    with cli.staged_template_path(str(REPO_ROOT)) as template:
        command = [sys.executable, "-m", "copier", "copy", "--trust", "--defaults"]
        for key, value in data.items():
            command.extend(["--data", f"{key}={value}"])
        command.extend([str(template), str(destination)])
        result = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise AssertionError(f"Copier failed:\n{result.stderr[-2000:]}")
    return destination


def relative_files(root: Path) -> list[str]:
    return sorted(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file())


class QuestionnaireTests(unittest.TestCase):
    def test_the_questionnaire_has_no_removed_question(self) -> None:
        config = yaml.safe_load((REPO_ROOT / "copier.yml").read_text(encoding="utf-8"))
        questions = [key for key in config if not key.startswith("_")]
        for removed in REMOVED_QUESTIONS:
            self.assertNotIn(removed, questions)
        self.assertNotIn("platforms", questions)
        self.assertEqual(
            [
                "prism_layer", "project_name", "project_slug", "reserved_identifiers", "package_identifier",
                "description", "stacks", "apps", "pack_versions", "versions",
                "app_id", "app_name", "app_path", "audience", "port", "backend_base_url", "backend_port", "app_package_segment", "app_package", "app_package_path",
                "app_module_name", "ci_workflow_name", "ci_paths",
            ],
            questions,
        )

    def test_no_question_default_or_preset_carries_a_removed_answer(self) -> None:
        from prism_cli.presets import DEFAULT_ANSWERS

        for removed in REMOVED_QUESTIONS:
            self.assertNotIn(removed, DEFAULT_ANSWERS)
            for preset in PRESETS:
                for app in preset.apps:
                    self.assertNotIn(removed, app)

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
        cls.platform_sets = {preset.slug: [app["id"] for app in preset.apps] for preset in PRESETS}
        cls.platform_sets["web-only"] = ["web", "admin"]
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
            for app in [item for item in self.platform_sets[name] if item in ("web", "admin")]:
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
            "full": {"azure", "azure-setup.md", "cloudflare", "cloudflare-setup.md", "mobile-store-release.md"},
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
        self.assertIn("SPRING_SECURITY_OAUTH2_RESOURCESERVER_JWT_ISSUER_URI=$IDENTITY_PROVIDER_ISSUER_URI", deploy)
        self.assertNotIn("JWT_SECRET", deploy)
        self.assertNotIn("CLIENT_SECRET", deploy)
        self.assertNotIn("{{", deploy)
        self.assertNotIn("{%", deploy)
        self.assertNotIn(b"\r\n", (references / "azure" / "06-deploy-backend.sh").read_bytes())
        wrangler = (references / "cloudflare" / "wrangler.jsonc").read_text(encoding="utf-8")
        self.assertIn('"name": "scope-check-<app-id>"', wrangler)
        self.assertIn('"API_BASE_URL": "https://api.scope-check.com"', wrangler)
        self.assertNotIn("AUTH_", wrangler, "the slice's web apps read no AUTH_ variable")
        self.assertTrue((references / "cloudflare" / "open-next.config.ts").is_file())
        self.assertTrue((references / "cloudflare" / "dev.vars.example").is_file())

    def test_the_cloudflare_guide_lists_every_web_app_and_matches_the_pack(self) -> None:
        guide = (self.workspaces["web-only"] / ".claude" / "skills" / "deployment" / "references" / "cloudflare-setup.md").read_text(encoding="utf-8")
        self.assertIn("| Web App | `web` | `scope-check-web` |", guide)
        self.assertIn("| Admin App | `admin` | `scope-check-admin` |", guide)
        self.assertNotIn("AUTH_", guide)
        self.assertNotIn("NextAuth", guide)
        # The guide's build steps are the pack's scripts: the guide adds the adapter, not a change to the app's own scripts.
        package = json.loads((self.workspaces["web-only"] / "web" / "package.json").read_text(encoding="utf-8"))
        self.assertIn('"clean"', guide)
        self.assertIn("clean", package["scripts"])
        self.assertIn('"@opennextjs/cloudflare"', guide)

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
            plain = generate_raw_workspace_layer(root / "plain")
            extra = generate_raw_workspace_layer(
                root / "extra",
                {"database": "mysql", "supporting_services": "[redis]", "use_docker": "false", "cloud_provider": "aws", "web_hosting": "vercel"},
            )
            self.assertEqual(relative_files(plain), relative_files(extra))
            for relative in ("docker-compose.yml", ".env.example"):
                self.assertEqual((plain / relative).read_text(encoding="utf-8"), (extra / relative).read_text(encoding="utf-8"), relative)
            manifests = [yaml.safe_load((root_ / "prism.workspace.yml").read_text(encoding="utf-8")) for root_ in (plain, extra)]
            self.assertEqual(manifests[0]["project"], manifests[1]["project"])
            self.assertNotIn("apps", manifests[0], "the workspace layer renders no apps; the CLI records them")
            answers = yaml.safe_load((extra / ".copier-answers.yml").read_text(encoding="utf-8"))
            for removed in REMOVED_QUESTIONS:
                self.assertNotIn(removed, answers)


if __name__ == "__main__":
    unittest.main()
