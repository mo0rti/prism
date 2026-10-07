"""The `spring-backend` slice and its fail-closed auth contract.

The pack generates one compiling slice (`GET /api/me`, the `users` table, the dev identity), and the full
backend sample is gone. These tests read the pack's sources for the guards that the pack's own Kotlin tests
prove at run time, and generate real workspaces through the CLI for the files around the slice. Building and
running the generated app is the job of `scripts/validate-template.ps1 -Mode backend-smoke` and the pack's CI.
"""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

import yaml
from jinja2 import Environment

from tests import real_temp  # noqa: F401
from tests.layered_support import generate_default_apps, read_yaml, run_cli, write_answers

REPO_ROOT = Path(__file__).resolve().parents[1]
PACK = REPO_ROOT / "packs" / "spring-backend"
APP = PACK / "{{ app_path }}"
SOURCES = APP / "src" / "main" / "kotlin" / "{{ app_package_path }}"
TESTS = APP / "src" / "test" / "kotlin" / "{{ app_package_path }}"
CONTRACT = REPO_ROOT / "template" / "shared" / "api-contracts" / "openapi.yml.jinja"

# What the retired full backend sample held and the template must not carry any more.
RETIRED_TOKENS = ("JWT_SECRET", "JWT_ACCESS_TOKEN_EXPIRY", "JWT_REFRESH_TOKEN_EXPIRY", "jjwt", "JwtTokenProvider", "JwtAuthenticationFilter", "OAuth2Config", "refresh_token_version")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def text_files(root: Path):
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix not in {".jar", ".png", ".webp", ".ico", ".ttf", ".otf", ".woff2"} and "node_modules" not in path.parts:
            try:
                yield path, path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue


class RetirementTests(unittest.TestCase):
    def test_the_full_backend_sample_is_gone(self) -> None:
        self.assertFalse((REPO_ROOT / "template" / "backend").exists())

    def test_the_workspace_layer_does_not_exclude_a_backend_folder(self) -> None:
        config = yaml.safe_load(read(REPO_ROOT / "copier.yml"))
        for entry in config["_exclude"]:
            self.assertNotIn("/backend", entry)

    def test_the_pack_and_the_workspace_files_carry_no_jwt_secret_or_oauth_provider(self) -> None:
        roots = [PACK, REPO_ROOT / "template" / "shared", REPO_ROOT / "template" / ".env.jinja", REPO_ROOT / "template" / ".env.example.jinja", REPO_ROOT / "template" / "docker-compose.yml.jinja"]
        offenders = []
        for root in roots:
            files = text_files(root) if root.is_dir() else [(root, read(root))]
            for path, text in files:
                for token in RETIRED_TOKENS:
                    if token in text:
                        offenders.append(f"{path.relative_to(REPO_ROOT).as_posix()}: {token}")
        self.assertEqual([], offenders)

    def test_the_env_files_hold_only_the_database_settings(self) -> None:
        for name in (".env.jinja", ".env.example.jinja"):
            text = read(REPO_ROOT / "template" / name)
            keys = re.findall(r"^([A-Z][A-Z0-9_]*)=", text, flags=re.MULTILINE)
            self.assertEqual(["DATABASE_NAME", "DATABASE_USERNAME", "DATABASE_PASSWORD"], keys, name)

    def test_the_azure_example_passes_an_issuer_and_no_signing_secret(self) -> None:
        folder = REPO_ROOT / "template-skills" / "deployment" / "references" / "azure"
        for name in ("06-deploy-backend.sh.jinja", "update-backend.sh.jinja", "app-secrets.env.example.jinja", "check-secrets.sh.jinja"):
            text = read(folder / name)
            self.assertNotIn("JWT_SECRET", text, name)
            self.assertNotIn("CLIENT_SECRET", text, name)
            self.assertNotIn("auth_methods", text, name)
        self.assertIn("SPRING_SECURITY_OAUTH2_RESOURCESERVER_JWT_ISSUER_URI=$IDENTITY_PROVIDER_ISSUER_URI", read(folder / "06-deploy-backend.sh.jinja"))


class ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        text = Environment(keep_trailing_newline=True).from_string(read(CONTRACT)).render(project_name="Contract Check", description="A contract check")
        cls.contract = yaml.safe_load(text)

    def test_the_contract_defines_exactly_the_slice_operations(self) -> None:
        self.assertEqual(["/api/dev-identity/jwks", "/api/dev-identity/token", "/api/me"], sorted(self.contract["paths"]))
        self.assertEqual(["get"], list(self.contract["paths"]["/api/dev-identity/jwks"]))
        self.assertEqual(["post"], list(self.contract["paths"]["/api/dev-identity/token"]))
        self.assertEqual(["get"], list(self.contract["paths"]["/api/me"]))

    def test_the_jwks_operation_is_dev_only_open_and_publishes_a_public_key_set(self) -> None:
        operation = self.contract["paths"]["/api/dev-identity/jwks"]["get"]
        self.assertIs(True, operation["x-prism-dev-only"])
        self.assertEqual([], operation["security"])
        self.assertIn("404", operation["responses"], "every other profile answers 404")
        self.assertIn("403", operation["responses"], "a request from outside the loopback interface is refused")
        schemas = self.contract["components"]["schemas"]
        self.assertEqual(["keys"], schemas["DevJwks"]["required"])
        for private in ("d", "p", "q", "dp", "dq", "qi"):
            self.assertNotIn(private, schemas["DevJwk"]["properties"], "the published key has no private member")

    def test_the_token_operation_is_marked_dev_only_and_needs_no_token(self) -> None:
        operation = self.contract["paths"]["/api/dev-identity/token"]["post"]
        self.assertIs(True, operation["x-prism-dev-only"])
        self.assertEqual([], operation["security"])
        self.assertIn("404", operation["responses"], "every other profile answers 404")
        self.assertIn("403", operation["responses"], "a request from outside the loopback interface is refused")

    def test_me_uses_the_default_bearer_security(self) -> None:
        self.assertNotIn("security", self.contract["paths"]["/api/me"]["get"])
        self.assertEqual([{"bearerAuth": []}], self.contract["security"])
        scheme = self.contract["components"]["securitySchemes"]["bearerAuth"]
        self.assertEqual({"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}, scheme)
        self.assertIn("401", self.contract["paths"]["/api/me"]["get"]["responses"])

    def test_every_reference_resolves(self) -> None:
        def references(node):
            if isinstance(node, dict):
                for key, value in node.items():
                    if key == "$ref":
                        yield value
                    else:
                        yield from references(value)
            elif isinstance(node, list):
                for item in node:
                    yield from references(item)

        for ref in references(self.contract):
            target = self.contract
            for part in ref.removeprefix("#/").split("/"):
                self.assertIn(part, target, ref)
                target = target[part]

    def test_no_operation_of_the_retired_sample_remains(self) -> None:
        text = read(CONTRACT)
        for retired in ("/auth/", "/transactions", "OAuthCallbackRequest", "OAuthTokenRequest", "RefreshTokenRequest", "auth_methods"):
            self.assertNotIn(retired, text)


class GuardSourceTests(unittest.TestCase):
    """The pack's sources keep each fail-closed guard; the pack's own Kotlin tests prove each one at run time."""

    def test_every_dev_identity_bean_exists_only_under_the_local_profile(self) -> None:
        for relative in (
            "bootstrap/DevIdentityConfig.kt.jinja",
            "bootstrap/DevIdentityGuard.kt.jinja",
            "modules/devidentity/controller/DevIdentityController.kt.jinja",
            "modules/devidentity/service/DevIdentityTokenService.kt.jinja",
            "modules/devidentity/service/DevIdentityJwksService.kt.jinja",
        ):
            with self.subTest(file=relative):
                self.assertIn('@Profile("local")', read(SOURCES / relative))

    def test_the_signing_key_is_generated_in_memory_and_never_written(self) -> None:
        config = read(SOURCES / "bootstrap" / "DevIdentityConfig.kt.jinja")
        self.assertIn("KeyPairGenerator", config)
        for forbidden in ("File(", "Files.", "FileOutputStream", "writeText", "@Value", "ClassPathResource", "getenv"):
            self.assertNotIn(forbidden, config, "the key is not read from or written to anything")

    def test_the_token_is_issued_by_the_dev_identity_with_a_capped_lifetime(self) -> None:
        self.assertIn('ISSUER = "prism-dev-identity"', read(SOURCES / "modules" / "devidentity" / "model" / "DevIdentity.kt.jinja"))
        service = read(SOURCES / "modules" / "devidentity" / "service" / "DevIdentityTokenService.kt.jinja")
        self.assertIn(".issuer(DevIdentity.ISSUER)", service)
        self.assertIn(".expiresAt(", service)
        properties = read(SOURCES / "bootstrap" / "properties" / "DevIdentityProperties.kt.jinja")
        self.assertIn("Duration.ofMinutes(15)", properties)
        self.assertIn("MAX_TOKEN_TTL", properties)
        self.assertIn("token-ttl: PT15M", read(APP / "src" / "main" / "resources" / "application.yml.jinja"))

    def test_the_resource_server_validates_jwts_and_fails_closed_without_a_provider(self) -> None:
        security = read(SOURCES / "bootstrap" / "SecurityConfig.kt.jinja")
        self.assertIn("oauth2ResourceServer", security)
        self.assertIn("RejectingJwtDecoder()", security)
        self.assertIn("anyRequest().authenticated()", security)
        build = read(APP / "build.gradle.kts.jinja")
        self.assertIn("spring-boot-starter-oauth2-resource-server", build)

    def test_startup_fails_next_to_a_configured_issuer(self) -> None:
        guard = read(SOURCES / "bootstrap" / "DevIdentityGuard.kt.jinja")
        self.assertIn("BeanFactoryPostProcessor", guard)
        self.assertIn("spring.security.oauth2.resourceserver.jwt.issuer-uri", guard)
        self.assertIn("check(configured.isEmpty())", guard)

    def test_the_token_route_accepts_loopback_requests_only(self) -> None:
        controller = read(SOURCES / "modules" / "devidentity" / "controller" / "DevIdentityController.kt.jinja")
        self.assertIn("LoopbackRequestPolicy.allows(", controller)
        self.assertIn("ForbiddenException(DevIdentityErrorCode.LOOPBACK_ONLY)", controller)
        policy = read(SOURCES / "modules" / "devidentity" / "service" / "LoopbackRequestPolicy.kt.jinja")
        self.assertIn("isLoopbackAddress", policy)
        self.assertIn("X-Forwarded-For", policy)

    def test_the_jwks_route_is_loopback_only_and_publishes_the_public_key_only(self) -> None:
        controller = read(SOURCES / "modules" / "devidentity" / "controller" / "DevIdentityController.kt.jinja")
        self.assertIn('@GetMapping("/jwks")', controller)
        self.assertEqual(2, controller.count("requireLoopback(servletRequest)"), "the token route and the JWKS route both check the loopback policy")
        service = read(SOURCES / "modules" / "devidentity" / "service" / "DevIdentityJwksService.kt.jinja")
        self.assertIn("toPublicJWK()", service)
        self.assertIn("toJSONObject(true)", service)
        for forbidden in ("toJSONObject()", "toJSONString()", "privateKey", "toRSAPrivateKey"):
            self.assertNotIn(forbidden, service, "only the public half of the key leaves the service")
        security = read(SOURCES / "bootstrap" / "SecurityConfig.kt.jinja")
        self.assertIn('requestMatchers(HttpMethod.GET, "/api/dev-identity/jwks").permitAll()', security)
        self.assertIn("anyRequest().authenticated()", security)

    def test_each_guard_has_its_test(self) -> None:
        expectations = {
            "DefaultProfileIntegrationTest.kt.jinja": ('post("/api/dev-identity/token")', "isNotFound", 'get("/api/dev-identity/jwks")', "the dev identity jwks route does not exist"),
            "LocalProfileIntegrationTest.kt.jinja": (
                'get("/api/me")',
                "LOOPBACK_ONLY",
                "a token signed by another key is rejected",
                "an expired token is rejected",
                "the jwks route publishes the public key and no private member",
                "the published key verifies a token the dev identity signs",
                "the jwks route refuses a request that did not come from the loopback interface",
                "the jwks route refuses a request through a proxy",
                "the jwks route refuses a request addressed to another host name",
            ),
            "DevIdentityStartupGuardTest.kt.jinja": ("startup fails when the local profile meets a configured issuer", "issuer-uri"),
            "modules/devidentity/LoopbackRequestPolicyTest.kt.jinja": ("a forwarding header means the request went through a proxy",),
            "modules/devidentity/DevIdentityTokenServiceTest.kt.jinja": ("prism-dev-identity",),
            "modules/users/UserServiceTest.kt.jinja": ("when another request creates the profile first",),
            "OpenApiContractTest.kt.jinja": ("x-prism-dev-only", "/api/dev-identity/jwks"),
        }
        for relative, needles in expectations.items():
            text = read(TESTS / relative)
            for needle in needles:
                with self.subTest(test=relative, needle=needle):
                    self.assertIn(needle, text)

    def test_the_integration_tests_use_testcontainers_and_no_in_memory_database(self) -> None:
        build = read(APP / "build.gradle.kts.jinja")
        self.assertIn("testcontainers-postgresql", build)
        self.assertNotIn("h2database", build)
        support = read(TESTS / "support" / "PostgresTestConfiguration.kt.jinja")
        self.assertIn("@ServiceConnection", support)
        self.assertIn("{{ versions.postgres }}", support)

    def test_the_compose_template_sets_no_default_profile_and_the_dev_task_sets_local(self) -> None:
        self.assertNotIn("SPRING_PROFILES_ACTIVE", read(REPO_ROOT / "template" / "docker-compose.yml.jinja"))
        taskfile = read(APP / "Taskfile.yml.jinja")
        self.assertEqual(1, taskfile.count("SPRING_PROFILES_ACTIVE: local"))
        run_section = taskfile.split("  run:")[1].split("  build:")[0]
        self.assertNotIn("SPRING_PROFILES_ACTIVE", run_section)

    def test_the_application_yml_activates_no_profile(self) -> None:
        text = read(APP / "src" / "main" / "resources" / "application.yml.jinja")
        self.assertNotIn("profiles:", text)
        self.assertNotIn("activate", text)


class GeneratedWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory(prefix="prism-slice-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        cls.single = generate_default_apps(cls.root / "single", ["backend"], cls.root, project_name="Slice App")
        answers = write_answers(
            cls.root / "double-answers.yml",
            {
                "project_name": "Slice App",
                "apps": [
                    {"id": "backend", "stack": "spring-backend", "name": "Spring Boot Backend", "generation": "scaffolded"},
                    {"id": "api-two", "stack": "spring-backend", "name": "Second API", "path": "services/api-two", "generation": "scaffolded"},
                ],
            },
        )
        code, out, err = run_cli("new", "--answers", str(answers), "--dest", str(cls.root / "double"), "--yes")
        if code != 0:
            raise AssertionError(out + err)
        cls.double = cls.root / "double"

    def package_root(self, workspace: Path, app_path: str, segment: str) -> Path:
        return workspace / app_path / "src" / "main" / "kotlin" / "com" / "example" / "sliceapp" / segment

    def test_the_slice_files_are_generated_under_the_apps_own_package(self) -> None:
        root = self.package_root(self.single, "backend", "backend")
        for relative in (
            "Application.kt",
            "bootstrap/SecurityConfig.kt",
            "bootstrap/DevIdentityConfig.kt",
            "bootstrap/DevIdentityGuard.kt",
            "modules/users/controller/MeController.kt",
            "modules/users/service/UserService.kt",
            "modules/users/repository/UserRepository.kt",
            "modules/users/model/User.kt",
            "modules/devidentity/controller/DevIdentityController.kt",
            "shared/exception/GlobalExceptionHandler.kt",
        ):
            self.assertTrue((root / relative).is_file(), relative)
        for retired in ("modules/health", "modules/auth", "modules/transactions", "bootstrap/security/JwtTokenProvider.kt"):
            self.assertFalse((root / retired).exists(), retired)
        self.assertTrue((self.single / "backend" / "src" / "main" / "resources" / "db" / "migration" / "V1__users.sql").is_file())
        self.assertEqual(["V1__users.sql"], sorted(path.name for path in (self.single / "backend" / "src" / "main" / "resources" / "db" / "migration").iterdir()))

    def test_the_package_declarations_match_the_directories(self) -> None:
        root = self.package_root(self.single, "backend", "backend")
        for path in sorted(root.rglob("*.kt")):
            declared = re.search(r"^package (\S+)", path.read_text(encoding="utf-8"), flags=re.MULTILINE)
            expected = "com.example.sliceapp.backend" + "".join("." + part for part in path.parent.relative_to(root).parts)
            self.assertEqual(expected, declared.group(1), path.name)

    def test_the_generated_contract_defines_the_slice_for_every_auth_answer(self) -> None:
        contract = read_yaml(self.single / "shared" / "api-contracts" / "openapi.yml")
        self.assertEqual(["/api/dev-identity/jwks", "/api/dev-identity/token", "/api/me"], sorted(contract["paths"]))
        self.assertIs(True, contract["paths"]["/api/dev-identity/token"]["post"]["x-prism-dev-only"])
        self.assertIs(True, contract["paths"]["/api/dev-identity/jwks"]["get"]["x-prism-dev-only"])

    def test_the_env_files_and_compose_carry_no_secret_and_no_profile(self) -> None:
        for name in (".env", ".env.example"):
            text = read(self.single / name)
            for token in ("JWT_", "GOOGLE_", "APPLE_", "FACEBOOK_", "MICROSOFT_"):
                self.assertNotIn(token, text, f"{name}: {token}")
            self.assertIn("DATABASE_PASSWORD=localdev", text)
        compose = read(self.single / "docker-compose.yml")
        self.assertNotIn("SPRING_PROFILES_ACTIVE", compose)
        self.assertNotIn("JWT_", compose)
        service = yaml.safe_load(compose)["services"]["backend"]
        self.assertEqual("jdbc:postgresql://db:5432/${DATABASE_NAME:-slice_app}", service["environment"]["DATABASE_URL"])

    def test_the_whole_generated_tree_holds_no_jwt_secret_or_unresolved_placeholder(self) -> None:
        for path, text in text_files(self.single):
            relative = path.relative_to(self.single).as_posix()
            if relative.startswith((".git/", "backend/gradle/")) or path.name == "gradlew":
                continue
            for token in RETIRED_TOKENS:
                self.assertNotIn(token, text, f"{relative}: {token}")
            if relative.startswith("backend/"):
                self.assertNotIn("{{ ", text, relative)  # a Go-template `{{.GRADLEW}}` of a Taskfile is fine
                self.assertNotIn("{%", text, relative)

    def test_the_apps_guidance_states_the_dev_identity_limits(self) -> None:
        readme = read(self.single / "backend" / "README.md")
        agents = read(self.single / "backend" / "AGENTS.md")
        cursor = read(self.single / ".cursor" / "rules" / "backend.mdc")
        self.assertIn("local development sign-in", readme)
        self.assertIn("@Profile(\"local\")", agents)
        self.assertIn("not authentication", agents)
        self.assertIn("never", readme.lower())
        self.assertIn("Testcontainers", readme)
        self.assertIn("Testcontainers", agents)
        self.assertIn("SPRING_PROFILES_ACTIVE=local", agents)
        self.assertIn("dev identity", cursor)
        self.assertEqual("@AGENTS.md", read(self.single / "backend" / "CLAUDE.md").splitlines()[0])

    def test_the_security_auth_skill_explains_the_replacement_and_cites_the_slice_by_path(self) -> None:
        for layer in (".claude", ".agents"):
            skill = read(self.single / layer / "skills" / "security-auth" / "SKILL.md")
            self.assertIn("Replacing The Dev Identity With A Real Identity Provider", skill)
            self.assertIn("## Slice files", skill)
            self.assertIn("Paths are inside the backend app's folder (`backend/`)", skill)
            self.assertIn("`src/main/kotlin/<package path>/bootstrap/SecurityConfig.kt`", skill)
            self.assertIn("SPRING_SECURITY_OAUTH2_RESOURCESERVER_JWT_ISSUER_URI", skill)
            self.assertNotIn("{%", skill)

    def test_two_backends_keep_their_own_schema_port_package_and_tasks_on_one_database(self) -> None:
        second = self.double / "services" / "api-two"
        first_yml = read(self.double / "backend" / "src" / "main" / "resources" / "application.yml")
        second_yml = read(second / "src" / "main" / "resources" / "application.yml")
        self.assertIn("${DATABASE_SCHEMA:backend}", first_yml)
        self.assertIn("${DATABASE_SCHEMA:api_two}", second_yml)
        self.assertIn("${PORT:8080}", first_yml)
        self.assertIn("${PORT:8081}", second_yml)
        self.assertTrue((second / "src" / "main" / "kotlin" / "com" / "example" / "sliceapp" / "apitwo" / "modules" / "users" / "controller" / "MeController.kt").is_file())
        compose = yaml.safe_load(read(self.double / "docker-compose.yml"))
        self.assertEqual(["backend", "api-two", "db"], list(compose["services"]))
        self.assertNotIn("SPRING_PROFILES_ACTIVE", read(self.double / "docker-compose.yml"))
        for taskfile in (self.double / "backend" / "Taskfile.yml", second / "Taskfile.yml"):
            data = yaml.safe_load(read(taskfile))
            self.assertEqual({"SPRING_PROFILES_ACTIVE": "local"}, data["tasks"]["dev"]["env"])
            self.assertNotIn("env", data["tasks"]["run"])
        root_tasks = yaml.safe_load(read(self.double / "Taskfile.yml"))["tasks"]
        self.assertEqual(["docker compose up -d db"], root_tasks["db-up"]["cmds"])
        # The contract test finds the shared contract at the right depth for each app.
        self.assertIn('Path.of("../shared/api-contracts/openapi.yml")', read(self.double / "backend" / "src" / "test" / "kotlin" / "com" / "example" / "sliceapp" / "backend" / "OpenApiContractTest.kt"))
        self.assertIn('Path.of("../../shared/api-contracts/openapi.yml")', read(second / "src" / "test" / "kotlin" / "com" / "example" / "sliceapp" / "apitwo" / "OpenApiContractTest.kt"))

    def test_the_workflow_builds_and_tests_without_a_secret(self) -> None:
        workflow = read(self.single / ".github" / "workflows" / "backend.yml")
        self.assertIn("./gradlew build", workflow)
        self.assertNotIn("secrets.", workflow)
        self.assertNotIn("environment:", workflow)
        data = yaml.safe_load(workflow)
        self.assertEqual({"contents": "read"}, data["permissions"])


if __name__ == "__main__":
    unittest.main()
