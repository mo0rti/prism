"""The pack pipeline's decisions: derived identifiers, their validation, ports, the version pins and the layer questions."""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

import yaml

from prism_cli import packs
from prism_cli.app_model import GENERATION_REGISTERED, GENERATION_SCAFFOLDED, STACKS
from prism_cli.packs import (
    PACK_STACKS,
    allocate_port,
    app_module_name,
    app_package_segment,
    assign_ports,
    pack_answers,
    parse_app_list,
    scaffold_collisions,
    scaffoldable_stacks,
    taken_ports,
    validate_scaffold,
    workspace_data,
)
from tests import real_temp  # noqa: F401

REPO_ROOT = Path(__file__).resolve().parents[1]
PROJECT = {"project_name": "Demo", "project_slug": "demo", "package_identifier": "com.example.demo"}


def scaffolded(app_id: str, stack: str = "spring-backend", path: str | None = None) -> dict[str, str]:
    return {"id": app_id, "name": app_id, "stack": stack, "repository": "workspace", "path": path or app_id, "generation": GENERATION_SCAFFOLDED}


class DerivedIdentifierTests(unittest.TestCase):
    def test_the_package_segment_is_the_app_id_without_hyphens(self) -> None:
        self.assertEqual("backend", app_package_segment("backend"))
        self.assertEqual("apitwo", app_package_segment("api-two"))
        self.assertEqual("a1b", app_package_segment("a1-b"))

    def test_the_module_name_is_the_app_id_in_pascal_case(self) -> None:
        self.assertEqual("Backend", app_module_name("backend"))
        self.assertEqual("ApiTwo", app_module_name("api-two"))
        self.assertEqual("Api2", app_module_name("api2"))

    def test_the_pack_answers_carry_every_derived_value_the_cli_computes(self) -> None:
        app = {"id": "api-two", "name": "Second API", "stack": "spring-backend", "path": "services/api-two/", "audience": "B2B"}
        answers = pack_answers(PROJECT, app, port=8081)
        self.assertEqual(
            {
                "prism_layer": "spring-backend",
                "project_name": "Demo",
                "project_slug": "demo",
                "package_identifier": "com.example.demo",
                "app_id": "api-two",
                "app_name": "Second API",
                "app_path": "services/api-two",
                "audience": "B2B",
                "port": 8081,
                "app_package_segment": "apitwo",
                "app_package": "com.example.demo.apitwo",
                "app_package_path": "com/example/demo/apitwo",
                "app_module_name": "ApiTwo",
                "ci_workflow_name": "Second API CI",
                "ci_paths": ["services/api-two/**", "shared/api-contracts/**", ".github/workflows/api-two.yml"],
            },
            answers,
        )

    def test_an_app_without_a_server_has_port_zero_and_no_audience_is_empty(self) -> None:
        answers = pack_answers(PROJECT, {"id": "x", "stack": "spring-backend", "path": "x"}, port=None)
        self.assertEqual(0, answers["port"])
        self.assertEqual("", answers["audience"])

    def test_the_workspace_layer_gets_the_stacks_and_the_scaffolded_apps_only(self) -> None:
        apps = [scaffolded("backend"), {**scaffolded("partner", "android-compose"), "generation": GENERATION_REGISTERED}, scaffolded("api-two", path="services/api-two")]
        data = workspace_data(PROJECT, apps, {"backend": 8080, "api-two": 8081})
        self.assertEqual("workspace", data["prism_layer"])
        self.assertEqual(["spring-backend"], data["stacks"])
        self.assertEqual(["backend", "api-two"], [entry["id"] for entry in data["apps"]])
        self.assertEqual([8080, 8081], [entry["port"] for entry in data["apps"]])


class ValidationTests(unittest.TestCase):
    def test_a_keyword_package_segment_is_rejected(self) -> None:
        for keyword in ("class", "new", "package", "default"):
            with self.subTest(keyword=keyword):
                errors = validate_scaffold([scaffolded(keyword)])
                self.assertTrue(any("package segment" in message and keyword in message for message in errors), errors)

    def test_a_hyphen_collision_between_two_apps_is_rejected(self) -> None:
        errors = validate_scaffold([scaffolded("my-app"), scaffolded("myapp")])
        self.assertTrue(any("`my-app` and `myapp` would share the package segment `myapp`" in message for message in errors), errors)

    def test_the_collision_check_covers_apps_that_are_only_registered(self) -> None:
        registered = {**scaffolded("my-app", "other"), "generation": GENERATION_REGISTERED}
        errors = validate_scaffold([registered, scaffolded("myapp")])
        self.assertTrue(any("share the package segment" in message for message in errors), errors)

    def test_distinct_ids_and_paths_are_accepted(self) -> None:
        self.assertEqual([], validate_scaffold([scaffolded("backend"), scaffolded("api-two", path="services/api-two")]))

    def test_an_id_that_would_replace_a_workspace_file_is_rejected(self) -> None:
        for reserved in ("api-contracts", "api-conventions", "advisory-review"):
            with self.subTest(app=reserved):
                errors = validate_scaffold([scaffolded(reserved)])
                self.assertTrue(any("workflow or Cursor rule" in message for message in errors), errors)

    def test_web_is_an_ordinary_app_id_because_the_workspace_layer_has_no_web_rule(self) -> None:
        self.assertEqual([], validate_scaffold([scaffolded("web", "nextjs-web")]))

    def test_a_path_inside_a_folder_of_the_workspace_layer_is_rejected(self) -> None:
        for path in ("docs/api", ".github/apps", "knowledge", "shared/x"):
            with self.subTest(path=path):
                errors = validate_scaffold([scaffolded("api", path=path)])
                self.assertTrue(any("belongs to the workspace" in message for message in errors), errors)

    def test_a_stack_without_a_pack_cannot_be_scaffolded(self) -> None:
        errors = validate_scaffold([scaffolded("tool", "other")])
        self.assertTrue(any("cannot be scaffolded" in message for message in errors), errors)

    def test_any_number_of_android_compose_apps_scaffold_at_any_path(self) -> None:
        apps = [scaffolded("mobile-android", "android-compose", "mobile-android"), scaffolded("partner-android", "android-compose", "apps/partner")]
        self.assertEqual([], validate_scaffold(apps))
        errors = validate_scaffold([scaffolded("my-android", "android-compose"), scaffolded("myandroid", "android-compose")])
        self.assertTrue(any("share the package segment" in message for message in errors), errors)
        errors = validate_scaffold([scaffolded("tool", "android-compose", "docs/android")])
        self.assertTrue(any("belongs to the workspace" in message for message in errors), errors)

    def test_any_number_of_nextjs_web_apps_scaffold_at_any_path(self) -> None:
        apps = [scaffolded("web", "nextjs-web"), scaffolded("admin", "nextjs-web"), scaffolded("partner-portal", "nextjs-web", "apps/partner")]
        self.assertEqual([], validate_scaffold(apps))
        # Two apps of one stack differ only in their identifiers: the hyphen collision is still caught.
        errors = validate_scaffold([scaffolded("my-web", "nextjs-web"), scaffolded("myweb", "nextjs-web")])
        self.assertTrue(any("share the package segment" in message for message in errors), errors)

    def test_any_number_of_ios_swiftui_apps_scaffold_at_any_path(self) -> None:
        apps = [scaffolded("mobile-ios", "ios-swiftui"), scaffolded("partner-ios", "ios-swiftui", "apps/partner-ios"), scaffolded("kiosk", "ios-swiftui", "apps/kiosk")]
        self.assertEqual([], validate_scaffold(apps))
        errors = validate_scaffold([scaffolded("my-ios", "ios-swiftui"), scaffolded("myios", "ios-swiftui")])
        self.assertTrue(any("share the package segment" in message for message in errors), errors)

    def test_only_limits_the_scaffold_checks_to_the_new_app(self) -> None:
        apps = [scaffolded("backend"), scaffolded("tool", "other")]
        self.assertEqual([], validate_scaffold(apps, only=["backend"]))
        self.assertTrue(validate_scaffold(apps, only=["tool"]))

    def test_an_existing_path_or_file_of_the_pack_blocks_the_scaffold(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = scaffolded("api-two", path="services/api-two")
            self.assertEqual([], scaffold_collisions(root, app))
            (root / "services" / "api-two").mkdir(parents=True)
            self.assertEqual([], scaffold_collisions(root, app), "an empty path is fine")
            (root / "services" / "api-two" / "x.txt").write_text("x", encoding="utf-8")
            (root / ".github" / "workflows").mkdir(parents=True)
            (root / ".github" / "workflows" / "api-two.yml").write_text("x", encoding="utf-8")
            problems = scaffold_collisions(root, app)
            self.assertEqual(2, len(problems), problems)
            self.assertTrue(any("already holds files" in message for message in problems))
            self.assertTrue(any("api-two.yml" in message for message in problems))


class AppListTests(unittest.TestCase):
    def test_defaults_name_path_repository_and_generation(self) -> None:
        entries, repositories, errors = parse_app_list([{"id": "backend", "stack": "spring-backend"}, {"id": "partner", "stack": "android-compose", "path": "apps/partner"}])
        self.assertEqual([], errors)
        self.assertEqual([], repositories)
        self.assertEqual(
            [
                {"id": "backend", "name": "backend", "stack": "spring-backend", "repository": "workspace", "path": "backend", "generation": "scaffolded"},
                {"id": "partner", "name": "partner", "stack": "android-compose", "repository": "workspace", "path": "apps/partner", "generation": "scaffolded"},
            ],
            entries,
        )

    def test_an_external_or_other_app_is_registered_never_scaffolded(self) -> None:
        entries, repositories, errors = parse_app_list(
            [
                {"id": "customer-android", "stack": "android-compose", "repository": "mobile", "remote": "https://example.com/acme/mobile.git", "path": "apps/customer"},
                {"id": "tool", "stack": "other"},
            ]
        )
        self.assertEqual([("tool", "other")], [(entry["id"], entry["stack"]) for entry in entries if entry["id"] == "tool"])
        self.assertEqual(["registered", "registered"], [entry["generation"] for entry in entries])
        self.assertEqual([{"id": "mobile", "remote": "https://example.com/acme/mobile.git"}], repositories)
        self.assertTrue(any("undeclared-app-capability" in message for message in errors), errors)

    def test_errors_name_the_item(self) -> None:
        cases = (
            ("a string", "must be a list"),
            ([{"id": "Bad_ID", "stack": "spring-backend"}], "needs an `id` that is a slug"),
            ([{"id": "x", "stack": "cobol"}], "needs a `stack` from the registry"),
            ([{"id": "x", "stack": "spring-backend", "color": "red"}], "unknown field(s): color"),
            ([{"id": "x", "stack": "spring-backend", "remote": "https://example.com/x.git"}], "lives in this repository"),
            ([{"id": "x", "stack": "spring-backend", "repository": "elsewhere"}], "give its `remote`"),
            ([{"id": "x", "stack": "spring-backend"}, {"id": "x", "stack": "spring-backend", "path": "y"}], "duplicate-app-id"),
            ([{"id": "x", "stack": "spring-backend", "generation": "magic"}], "invalid-app-generation"),
            ([{"id": "x", "stack": "other", "generation": "scaffolded", "capabilities": {}}], "unknown field(s): capabilities"),
            ([{"id": "x", "stack": "spring-backend", "path": "../x"}], "invalid-app-path"),
            ([{"id": "x", "stack": "spring-backend", "path": "x"}, {"id": "y", "stack": "spring-backend", "path": "x/y"}], "app-path-conflict"),
        )
        for raw, expected in cases:
            with self.subTest(expected=expected):
                _entries, _repositories, errors = parse_app_list(raw)
                self.assertTrue(any(expected in message for message in errors), errors)

    def test_no_list_is_an_empty_list_of_apps(self) -> None:
        self.assertEqual(([], [], []), parse_app_list(None))
        self.assertEqual(([], [], []), parse_app_list([]))


class PortTests(unittest.TestCase):
    def test_the_first_free_port_of_the_stacks_range_is_chosen(self) -> None:
        self.assertEqual(8080, allocate_port("spring-backend", []))
        self.assertEqual(8081, allocate_port("spring-backend", [8080]))
        self.assertEqual(8081, allocate_port("spring-backend", [8080, 8082]), "a gap left by a removed app is reused")
        self.assertEqual(3000, allocate_port("nextjs-web", [8080]))

    def test_a_stack_without_a_server_has_no_port(self) -> None:
        self.assertIsNone(allocate_port("android-compose", []))
        self.assertIsNone(allocate_port("other", []))

    def test_an_exhausted_range_is_an_error(self) -> None:
        first, last = STACKS["spring-backend"].port_range
        with self.assertRaisesRegex(ValueError, "Every port"):
            allocate_port("spring-backend", range(first, last + 1))

    def test_the_cli_assigns_each_scaffolded_backend_the_next_port(self) -> None:
        apps = [scaffolded("backend"), scaffolded("api-two"), {**scaffolded("partner", "android-compose"), "generation": GENERATION_SCAFFOLDED}]
        self.assertEqual({"backend": 8080, "api-two": 8081}, assign_ports(apps))
        self.assertEqual({"backend": 8081, "api-two": 8082}, assign_ports(apps, taken=[8080]))

    def test_a_remembered_port_never_shifts_when_another_app_is_removed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for app_id, port in (("backend", 8080), ("api-two", 8081), ("api-three", 8082)):
                folder = root / app_id
                folder.mkdir()
                (folder / ".copier-answers.yml").write_text(yaml.safe_dump({"port": port, "_src_path": "x"}), encoding="utf-8")
            apps = [scaffolded("backend"), scaffolded("api-two"), scaffolded("api-three")]
            self.assertEqual({8080, 8081, 8082}, taken_ports(root, apps))
            # api-two is removed: the others keep their ports, and the next new app takes the freed one.
            remaining = [apps[0], apps[2]]
            self.assertEqual({8080, 8082}, taken_ports(root, remaining))
            self.assertEqual(8081, allocate_port("spring-backend", taken_ports(root, remaining)))

    def test_a_missing_or_unreadable_answers_file_holds_no_port(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "backend").mkdir()
            (root / "backend" / ".copier-answers.yml").write_text("[unclosed", encoding="utf-8")
            self.assertEqual(set(), taken_ports(root, [scaffolded("backend"), scaffolded("api-two")]))


class NoFullSampleTests(unittest.TestCase):
    def test_every_generated_stack_has_a_pack_and_no_full_sample_remains(self) -> None:
        self.assertEqual(("spring-backend", "nextjs-web", "android-compose", "ios-swiftui", "python-agent-service"), PACK_STACKS)
        self.assertEqual(PACK_STACKS, scaffoldable_stacks())
        self.assertFalse(hasattr(packs, "full_sample_apps"))
        self.assertEqual([], [name for name in vars(packs) if name.endswith("_FULL_SAMPLE")])
        for stack in PACK_STACKS:
            self.assertTrue((REPO_ROOT / "packs" / stack).is_dir(), stack)
        for sample in ("backend", "web-user-app", "web-admin-portal", "mobile-android", "mobile-ios"):
            self.assertFalse((REPO_ROOT / "template" / sample).exists(), sample)


def hard_coded_versions(pack_root: Path, pins: dict[str, str]) -> list[str]:
    """The pinned versions that a pack file repeats instead of reading: ``file: key=value`` for each."""

    found: list[str] = []
    for path in sorted(pack_root.rglob("*")):
        if not path.is_file() or path.name.startswith(("package-lock.json", "uv.lock")):
            continue  # a lockfile records every resolved version; its agreement with the pins has its own test
        data = path.read_bytes()
        if b"\0" in data:
            continue
        text = data.decode("utf-8", errors="ignore")
        for key, value in pins.items():
            if re.search(r"(?<![0-9.])" + re.escape(value) + r"(?![0-9.])", text):
                found.append(f"{path.relative_to(pack_root).as_posix()}: {key}={value}")
    return found


class VersionPinTests(unittest.TestCase):
    def versions(self) -> dict[str, dict[str, str]]:
        data = yaml.safe_load((REPO_ROOT / "packs" / "versions.yml").read_text(encoding="utf-8"))
        return {stack: {key: str(value) for key, value in pins.items()} for stack, pins in data.items()}

    def test_versions_yml_pins_exactly_the_stacks_that_have_a_pack(self) -> None:
        self.assertEqual(sorted(PACK_STACKS), sorted(self.versions()))
        for stack in PACK_STACKS:
            self.assertTrue((REPO_ROOT / "packs" / stack).is_dir())

    def test_no_pack_file_repeats_a_version_that_versions_yml_pins(self) -> None:
        for stack, pins in self.versions().items():
            with self.subTest(stack=stack):
                self.assertEqual([], hard_coded_versions(REPO_ROOT / "packs" / stack, pins))

    def test_the_pin_check_flags_a_hard_coded_version_and_accepts_a_templated_one(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            pack = Path(temporary)
            (pack / "build.gradle.kts.jinja").write_text('id("org.springframework.boot") version "{{ versions.spring_boot }}"\njava 21\n', encoding="utf-8")
            pins = {"spring_boot": "4.0.1", "java": "21"}
            self.assertEqual(["build.gradle.kts.jinja: java=21"], hard_coded_versions(pack, pins))
            (pack / "settings.gradle.kts").write_text('plugin version "4.0.1"\n', encoding="utf-8")
            self.assertIn("settings.gradle.kts: spring_boot=4.0.1", hard_coded_versions(pack, pins))
            (pack / "build.gradle.kts.jinja").write_text("2021 and 8.14.3 and 4.0.10\n", encoding="utf-8")
            (pack / "settings.gradle.kts").unlink()
            self.assertEqual([], hard_coded_versions(pack, pins), "a version inside a longer number is not the pin")
            (pack / "package-lock.json.jinja").write_text('{"version": "4.0.1", "node": ">=21"}\n', encoding="utf-8")
            self.assertEqual([], hard_coded_versions(pack, pins), "a lockfile repeats the pins by design")
            (pack / "uv.lock.jinja").write_text('requires-python = ">=21"\nversion = "4.0.1"\n', encoding="utf-8")
            self.assertEqual([], hard_coded_versions(pack, pins), "a uv lockfile repeats the pins by design")

    def test_the_packs_read_versions_through_the_versions_question(self) -> None:
        text = (REPO_ROOT / "copier.yml").read_text(encoding="utf-8")
        self.assertIn("{% include 'packs/versions.yml' %}", text)
        for stack in PACK_STACKS:
            pack_text = "\n".join(
                path.read_text(encoding="utf-8", errors="ignore") for path in (REPO_ROOT / "packs" / stack).rglob("*.jinja")
            )
            self.assertIn("{{ versions.", pack_text)


class LayerQuestionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = yaml.safe_load((REPO_ROOT / "copier.yml").read_text(encoding="utf-8"))

    def test_the_layer_question_offers_the_workspace_and_every_pack(self) -> None:
        self.assertEqual(["workspace", *PACK_STACKS], self.config["prism_layer"]["choices"])
        self.assertEqual("workspace", self.config["prism_layer"]["default"])

    def test_the_subdirectory_is_templated_from_the_layer(self) -> None:
        self.assertEqual("{{ 'template' if prism_layer == 'workspace' else 'packs/' ~ prism_layer }}", self.config["_subdirectory"])

    def test_every_question_belongs_to_a_layer(self) -> None:
        both = {"prism_layer", "project_name", "project_slug", "package_identifier", "reserved_identifiers", "pack_versions", "versions"}
        for name, details in self.config.items():
            if name.startswith("_") or name in both:
                continue
            with self.subTest(question=name):
                self.assertIn("when", details, f"`{name}` must say which layer asks it")
                if details["when"] is False:
                    continue  # derived, never asked
                guard = str(details["when"])
                self.assertTrue("prism_layer" in guard, f"`{name}` is guarded by `{guard}`")

    def test_there_is_no_platforms_question_and_every_platform_condition_is_gone(self) -> None:
        self.assertNotIn("platforms", self.config)
        text = (REPO_ROOT / "copier.yml").read_text(encoding="utf-8")
        self.assertNotRegex(text, r"in platforms\b")

    def test_every_exclusion_applies_to_the_workspace_layer_only(self) -> None:
        for entry in self.config["_exclude"]:
            with self.subTest(entry=entry[:60]):
                self.assertIn("prism_layer == 'workspace'", entry)

    def test_the_reserved_identifiers_match_the_cli(self) -> None:
        listed = yaml.safe_load(self.config["reserved_identifiers"]["default"])
        self.assertEqual(sorted(packs.RESERVED_IDENTIFIERS), sorted(listed))

    def test_the_app_layer_questions_derive_the_values_the_cli_computes(self) -> None:
        from copier import run_copy

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            (source / "packs").mkdir(parents=True)
            (source / "template").mkdir()
            (source / "packs" / "spring-backend").mkdir()
            (source / "copier.yml").write_bytes((REPO_ROOT / "copier.yml").read_bytes())
            (source / "packs" / "versions.yml").write_bytes((REPO_ROOT / "packs" / "versions.yml").read_bytes())
            (source / "packs" / "spring-backend" / "{{ _copier_conf.answers_file }}.jinja").write_bytes(
                (REPO_ROOT / "packs" / "spring-backend" / "{{ _copier_conf.answers_file }}.jinja").read_bytes()
            )
            destination = root / "out"
            run_copy(
                str(source),
                str(destination),
                data={"prism_layer": "spring-backend", "project_name": "Demo", "project_slug": "demo", "app_id": "api-two", "app_path": "services/api-two"},
                defaults=True,
                unsafe=True,
                quiet=True,
            )
            from_copier = yaml.safe_load((destination / ".copier-answers.yml").read_text(encoding="utf-8"))
        from_cli = pack_answers(
            {"project_name": "Demo", "project_slug": "demo", "package_identifier": "com.example.demo"},
            {"id": "api-two", "stack": "spring-backend", "path": "services/api-two"},
            port=None,
        )
        for key in ("app_package_segment", "app_package", "app_package_path", "app_module_name", "ci_workflow_name", "ci_paths", "app_name", "audience", "port"):
            with self.subTest(answer=key):
                self.assertEqual(from_cli[key], from_copier[key])

    def test_raw_copier_enforces_the_app_identifier_validation(self) -> None:
        from copier import run_copy

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            (source / "packs" / "spring-backend").mkdir(parents=True)
            (source / "template").mkdir()
            (source / "copier.yml").write_bytes((REPO_ROOT / "copier.yml").read_bytes())
            (source / "packs" / "versions.yml").write_bytes((REPO_ROOT / "packs" / "versions.yml").read_bytes())
            base = {"prism_layer": "spring-backend", "project_name": "Demo", "project_slug": "demo", "app_id": "api"}
            cases = (
                ({"app_id": "Bad_Id"}, "App ID must start"),
                ({"app_id": "class"}, "cannot be a Kotlin or Java keyword"),
                ({"app_path": "../x"}, "App path must be a relative path"),
                ({"app_path": "/abs"}, "App path must be a relative path"),
                ({"app_path": "a//b"}, "App path must be a relative path"),
            )
            for index, (bad, message) in enumerate(cases):
                with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, message):
                    run_copy(str(source), str(root / f"invalid-{index}"), data={**base, **bad}, defaults=True, unsafe=True, quiet=True)



class WorkspaceDataFromManifestTests(unittest.TestCase):
    """`prism update` and `prism app add --scaffold` give the workspace layer the app list the manifest decides."""

    def test_the_data_lists_every_scaffolded_app_even_a_retired_one_with_its_remembered_port(self) -> None:
        from prism_cli import cli

        manifest = {
            "schema_version": 2,
            "apps": [
                {**scaffolded("backend"), "status": "retired"},
                scaffolded("web", "nextjs-web"),
                {"id": "partner", "stack": "android-compose", "repository": "workspace", "path": "apps/partner"},
            ],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "prism.workspace.yml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
            (root / "backend").mkdir()
            (root / "backend" / ".copier-answers.yml").write_text(yaml.safe_dump({"port": 8085, "_src_path": "x"}), encoding="utf-8")
            data = cli.workspace_layer_data_from_manifest(root)
        self.assertEqual(["nextjs-web", "spring-backend"], data["stacks"])
        self.assertEqual([("backend", 8085), ("web", 0)], [(entry["id"], entry["port"]) for entry in data["apps"]])
        self.assertEqual({"id", "name", "stack", "path", "audience", "port"}, set(data["apps"][0]))


if __name__ == "__main__":
    unittest.main()
