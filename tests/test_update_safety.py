"""`prism update` never writes through a link and never runs Copier with trust against an answers file it has not checked.

Recopy writes the saved answers of a layer to a file beside its answers file and runs Copier on it. That file is
created exclusively, in a directory that is checked first, and every answers file the update reads or writes is
confined to the workspace: a symlink, a junction or any other reparse point on the path is refused.

The update also runs Copier with `--trust` against each app layer's own answers file, so a layer must come from the
workspace's approved template source and carry the identity the manifest and the workspace give it.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from prism_cli import cli
from prism_cli.packs import layer_answers_problems, read_app_answers
from tests import real_temp  # noqa: F401
from tests.layered_support import commit_workspace, generate_workspace, git, read_yaml, run_cli, tag_template_change
from tests.test_layered_generation import API_TWO, BACKEND, PACK_AGENTS, WORKSPACE_DOCS, LayeredTestCase

VICTIM_TEXT = "the file of someone else\n"


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


if __name__ == "__main__":
    unittest.main()
