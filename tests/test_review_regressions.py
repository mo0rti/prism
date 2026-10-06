"""Regression cases from the independent repository review."""

import argparse
import contextlib
import io
import os
from pathlib import Path
import shutil
import socket
import tempfile
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

from prism_cli import cli, ui
from prism_cli.graph_server import serve_graph
from prism_cli.render import render_or_print_wiki_query
from prism_cli.wiki_lint import lint_wiki
from copier import run_copy
from tests import real_temp  # noqa: F401


FIXTURE = Path(__file__).parent / "fixtures" / "wiki_contract" / "healthy"


class ReviewRegressions(unittest.TestCase):
    def test_identifier_validation_rejects_uncompilable_names(self):
        base = {"project_name": "Demo", "apps": [{"id": "backend", "stack": "spring-backend"}], "auth_methods": ["password"]}
        for bad in ({"project_name": "2048 Game"}, {"project_slug": "two--hyphens"},
                    {"package_identifier": "com.2048.app"}, {"package_identifier": "com.class.app"},
                    {"ios_module_name": "2048Game"}, {"project_slug": 2048}):
            with self.subTest(bad=bad):
                self.assertTrue(cli.validate_answers({**base, **bad})[0])
        self.assertEqual([], cli.validate_answers({**base, "project_slug": "game-2048", "package_identifier": "com.example.game2048"})[0])

    def test_raw_copier_enforces_the_questionnaire_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "template-source"
            (source / "template").mkdir(parents=True)
            (source / "packs").mkdir()
            shutil.copyfile(Path(__file__).parents[1] / "copier.yml", source / "copier.yml")
            shutil.copyfile(Path(__file__).parents[1] / "packs" / "versions.yml", source / "packs" / "versions.yml")
            cases = [
                ({"project_name": "2048 Game"}, "Project slug must start"),
                ({"project_slug": "bad--slug"}, "Project slug must start"),
                ({"package_identifier": "com.2048.app"}, "Package identifier must"),
                ({"package_identifier": "com.class.app"}, "cannot be Kotlin or Java keywords"),
                ({"ios_module_name": "2048Game"}, "valid Swift identifier"),
            ]
            for index, (bad, message) in enumerate(cases):
                with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, message):
                    run_copy(str(source), str(root / f"invalid-{index}"), data={"project_name": "Demo", "auth_methods": ["password"], **bad}, defaults=True, unsafe=True, quiet=True)
            run_copy(str(source), str(root / "valid"), data={"project_name": "2048 Game", "project_slug": "game-2048", "auth_methods": ["password"]}, defaults=True, unsafe=True, quiet=True)

    def test_custom_template_trust_is_explicit(self):
        with patch("sys.stdin.isatty", return_value=False), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertFalse(cli.ensure_template_trust("https://example.test/template.git"))
            self.assertTrue(cli.ensure_template_trust("https://example.test/template.git", explicitly_trusted=True))
            args = cli.build_parser().parse_args(["new", "--yes", "--template", "https://example.test/template.git"])
            self.assertFalse(args.trust_template, "--yes must not authorize custom code execution")
        with patch("sys.stdin.isatty", return_value=True), patch.object(cli, "confirm", return_value=False) as confirm, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertFalse(cli.ensure_template_trust("gh:someone/custom"))
            confirm.assert_called_once_with("Trust this template to execute code?", default=False)

    def test_remote_template_shortcuts_preserve_provenance(self):
        for source in ("gh:owner/repo", "gl:owner/repo", "git@host:owner/repo.git", "user@host:repo", "https://example.test/repo.git"):
            with self.subTest(source=source):
                self.assertEqual(source, cli.normalize_template_path(source))
                self.assertTrue(cli.supports_versioned_update(source))

    def test_query_exit_contract_in_both_output_modes(self):
        cases = [
            ("wiki show", {"feature": None}, 3),
            ("wiki show", {"feature": {"id": "F-001"}}, 0),
            ("wiki search", {"matches": []}, 0),
            ("wiki transition-preflight", {"transition": {"classification": "blocked", "supported": True}}, 3),
            ("wiki transition-preflight", {"transition": {"classification": "unknown", "supported": False}}, 3),
            ("wiki transition-preflight", {"transition": {"classification": "ready", "supported": True}}, 0),
        ]
        for json_mode in (False, True):
            for command, facts, expected in cases:
                with self.subTest(command=command, facts=facts, json=json_mode), contextlib.redirect_stdout(io.StringIO()), patch("prism_cli.render.show_command_intro"):
                    self.assertEqual(expected, render_or_print_wiki_query(argparse.Namespace(json=json_mode), "Test", {"command": command, "facts": facts}))

    def test_command_palette_accepts_j_and_k_in_search_text(self):
        options = [ui.SelectOption("wrong", "unrelated"), ui.SelectOption("project", "Project workspace")]
        stream = io.StringIO()
        with patch("sys.stdin.isatty", return_value=True), patch("sys.stdout", stream), patch.object(stream, "isatty", return_value=True), patch.object(ui, "_read_key", side_effect=[*"project", "space", *"workspace", "enter"]):
            self.assertEqual("project", ui.interactive_command_palette("Commands", options))
        self.assertIn("project workspace", stream.getvalue())

    @unittest.skipIf(os.name == "nt", "POSIX terminal behavior; exercised in Linux/macOS CI")
    def test_posix_lone_escape_returns_without_another_byte(self):
        import pty
        import termios

        master, slave = pty.openpty()
        process = subprocess.Popen([sys.executable, "-u", "-c", "from prism_cli.ui import _read_key; print(_read_key())"], stdin=slave, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic() + 5
            while termios.tcgetattr(slave)[3] & termios.ICANON:
                if time.monotonic() >= deadline:
                    self.fail("Reader did not enter raw terminal mode")
                time.sleep(0.01)
            os.write(master, b"\x1b")
            output, errors = process.communicate(timeout=2)
            self.assertEqual(0, process.returncode, errors.decode())
            self.assertEqual(b"escape", output.strip())
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()
            os.close(master)
            os.close(slave)

    def test_duplicate_and_orphan_requirements_are_lint_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "workspace"
            shutil.copytree(FIXTURE.with_name("partial"), root)
            requirements = root / "knowledge/wiki/app-requirements"
            source = next(requirements.glob("*.md"))
            (requirements / "duplicate.md").write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
            text = source.read_text(encoding="utf-8")
            import re
            text = re.sub(r"feature-id:.*", "feature-id: F-999", text)
            (requirements / "orphan.md").write_text(text, encoding="utf-8")
            errors = {item.code for item in lint_wiki(root).diagnostics if item.severity == "error"}
            self.assertIn("duplicate-app-requirement", errors)
            self.assertIn("orphan-app-requirement", errors)

    def test_busy_dashboard_port_returns_a_useful_failure(self):
        with socket.socket() as occupied, patch("webbrowser.open") as browser, contextlib.redirect_stderr(io.StringIO()) as output:
            occupied.bind(("127.0.0.1", 0))
            occupied.listen()
            self.assertEqual(4, serve_graph(FIXTURE, occupied.getsockname()[1]))
            self.assertIn("Choose another --port", output.getvalue())
            browser.assert_not_called()

    def test_advanced_flow_asks_only_for_identity_apps_and_auth(self):
        # The last empty answer ends the list of further apps.
        with patch.object(cli, "prompt_text", side_effect=["Demo", "Description", "com.example.demo", "", ""]), patch.object(cli, "prompt_multiselect", side_effect=[["backend"], ["password"]]) as multiselect, contextlib.redirect_stdout(io.StringIO()):
            answers = cli.prompt_advanced_answers()
        self.assertEqual(2, multiselect.call_count)
        self.assertEqual(
            {"project_name", "description", "package_identifier", "github_org", "apps", "auth_methods"},
            set(answers),
        )
        self.assertEqual([("backend", "spring-backend", "scaffolded")], [(app["id"], app["stack"], app["generation"]) for app in answers["apps"]])

    def test_advanced_flow_asks_for_the_audience_of_a_default_web_app(self):
        texts = ["Demo", "Description", "com.example.demo", "", "B2C", ""]
        with patch.object(cli, "prompt_text", side_effect=texts), patch.object(cli, "prompt_multiselect", side_effect=[["backend", "web"], ["password"]]), contextlib.redirect_stdout(io.StringIO()):
            answers = cli.prompt_advanced_answers()
        entries = {app["id"]: app for app in answers["apps"]}
        self.assertEqual(("nextjs-web", "B2C", "scaffolded"), (entries["web"]["stack"], entries["web"]["audience"], entries["web"]["generation"]))
        self.assertNotIn("audience", entries["backend"], "only a web app is asked for its audience here")

    def test_advanced_flow_asks_for_further_apps_with_a_stack_a_path_and_scaffold_or_register(self):
        texts = ["Demo", "Description", "com.example.demo", "", "api-two", "Second API", "workspace", "services/api-two", "B2B", ""]
        selections = [["backend"], ["spring-backend"], ["password"]]
        with patch.object(cli, "prompt_text", side_effect=texts), patch.object(cli, "prompt_multiselect", side_effect=selections), patch.object(cli, "confirm", return_value=True), contextlib.redirect_stdout(io.StringIO()):
            answers = cli.prompt_advanced_answers()
        self.assertEqual(["backend", "api-two"], [app["id"] for app in answers["apps"]])
        self.assertEqual(
            {"id": "api-two", "stack": "spring-backend", "name": "Second API", "path": "services/api-two", "audience": "B2B", "generation": "scaffolded"},
            answers["apps"][1],
        )

    def test_open_uses_memory_server_without_creating_a_snapshot(self):
        args = cli.build_parser().parse_args(["wiki", "graph", str(FIXTURE), "--open", "--port", "18322"])
        with patch("prism_cli.graph_server.serve_graph", return_value=0) as serve, patch("tempfile.mkdtemp") as temp:
            self.assertEqual(0, cli.cmd_wiki_graph(args))
            serve.assert_called_once_with(FIXTURE.resolve(), 18322)
            temp.assert_not_called()

    def test_installed_default_passes_matching_release_tag(self):
        with tempfile.TemporaryDirectory() as directory:
            command = ["new", "--preset", "backend-only", "--project-name", "Demo", "--dest", str(Path(directory)/"new"), "--yes"]
            for custom in ([], ["--template", cli.DEFAULT_TEMPLATE_URL]):
                with self.subTest(custom=custom), patch.object(cli, "default_template_reference", return_value=cli.DEFAULT_TEMPLATE_URL), patch.object(cli, "run_copier", return_value=0) as copier, contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(0, cli.main(command+custom))
                    self.assertEqual(None if custom else f"v{cli.__version__}", copier.call_args.kwargs["vcs_ref"])
