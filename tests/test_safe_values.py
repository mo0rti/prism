"""The shared rule for user values that reach generated code, configuration and CI."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

import yaml
from jinja2 import Environment

from prism_cli import safe_values
from prism_cli.safe_values import description_problem, label_problem, path_segments_problem

REPO_ROOT = Path(__file__).resolve().parents[1]

HOSTILE_VALUES = {
    "command substitution": "apps/$(id)",
    "backticks": "apps/`id`",
    "semicolon": "apps/a;rm -rf x",
    "pipe": "apps/a|b",
    "ampersand": "apps/a&b",
    "quote": 'apps/a"b',
    "single quote": "apps/a'b",
    "newline": "apps/a\nb",
    "trailing newline": "apps/a\n",
    "space": "apps/a b",
    "yaml break": "apps/a: #b",
    "expression": "apps/${{ secrets.X }}",
    "glob": "apps/*",
    "uppercase": "Apps/Web",
    "leading dot": "apps/.hidden",
    "trailing dot": "apps/web.",
    "dollar": "apps/$HOME",
    "device name": "apps/con",
    "tilde": "~/web",
}


class PathSegmentTests(unittest.TestCase):
    def test_safe_segments_pass(self) -> None:
        for path in ("web", "apps/web", "services/api-two", "a.b/c_d", "v1.2/x", "0abc"):
            with self.subTest(path):
                self.assertIsNone(path_segments_problem(path.split("/")))

    def test_hostile_paths_are_refused(self) -> None:
        for label, path in HOSTILE_VALUES.items():
            with self.subTest(label):
                self.assertIsNotNone(path_segments_problem(path.split("/")))

    def test_the_copier_validator_uses_the_same_pattern(self) -> None:
        validator = yaml.safe_load((REPO_ROOT / "copier.yml").read_text(encoding="utf-8"))["app_path"]["validator"]
        self.assertIn(safe_values.PATH_SEGMENT_PATTERN.pattern, validator)


class LabelTests(unittest.TestCase):
    def test_plain_names_pass(self) -> None:
        for value in ("Admin App", "Partner Portal (EU)", "Kundenportal Zürich", "app+1", "A.B, C-D_E", "Android (Kotlin/Compose)", "R&D iOS"):
            with self.subTest(value):
                self.assertIsNone(label_problem(value))
                self.assertIsNone(description_problem(value))

    def test_hostile_labels_are_refused(self) -> None:
        hostile = ('a"b', "a'b", "a`b`", "$(id)", "a\nb", "a\n", "a: #b", "a;b", "a|b", "a<b>", "{{ x }}", "a\\b", "a%b", "a‮b", " lead", "trail ", "x" * 81)
        for value in hostile:
            with self.subTest(value):
                self.assertIsNotNone(label_problem(value))

    def test_a_description_may_hold_sentence_punctuation_but_never_markup_or_quotes(self) -> None:
        self.assertIsNone(description_problem("The customer's portal: web, mobile & API! Ready?"))
        for value in ('say "hi"', "a`b`", "$(id)", "a\nb", "<b>", "{{ x }}", "a\\b", "a#b", "x" * 201):
            with self.subTest(value):
                self.assertIsNotNone(description_problem(value))

    def test_a_non_string_is_refused(self) -> None:
        self.assertIsNotNone(label_problem(5))
        self.assertIsNotNone(description_problem(None))


class CopierValidatorsTests(unittest.TestCase):
    """`copier.yml` validates the same values when someone runs Copier without the CLI: its validators accept and refuse what this module does."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.config = yaml.safe_load((REPO_ROOT / "copier.yml").read_text(encoding="utf-8"))
        cls.environment = Environment()

        def regex_search(value: str, pattern: str) -> str:
            match = re.search(pattern, value)
            return match.group(0) if match else ""

        cls.environment.filters["regex_search"] = regex_search

    def refusal(self, question: str, **values: str) -> bool:
        """Whether the question's Copier validator reports an error for these answers."""

        text = self.environment.from_string(self.config[question]["validator"]).render(**values)
        return bool(text.strip())

    def test_every_user_value_has_a_validator(self) -> None:
        for name in ("project_name", "description", "app_id", "app_name", "app_path", "audience", "project_slug", "package_identifier"):
            with self.subTest(name):
                self.assertIn("validator", self.config[name])

    def test_labels_agree_with_the_python_rule(self) -> None:
        values = ["Admin App", "Android (Kotlin/Compose)", "Kundenportal Zürich", " lead", "trail ", 'a"b', "a'b", "$(id)", "a\nb", "a\nb\n", "a: #b", "a;b", "{{ x }}", "a\\b", "x" * 81, "x" * 80]
        for question in ("app_name", "project_name", "audience"):
            for value in values:
                with self.subTest(question=question, value=value):
                    self.assertEqual(label_problem(value) is not None, self.refusal(question, **{question: value}))
        self.assertTrue(self.refusal("app_name", app_name=""), "a name is required")
        self.assertFalse(self.refusal("audience", audience=""), "an audience may be empty")

    def test_descriptions_agree_with_the_python_rule(self) -> None:
        values = ("A multi-platform application", "The customer's portal: web, mobile & API!", 'say "hi"', "a`b`", "$(id)", "a\nb", "<b>", "a\\b", "a#b", "x" * 201, "x" * 200)
        for value in values:
            with self.subTest(value):
                self.assertEqual(description_problem(value) is not None, self.refusal("description", description=value))

    def test_app_paths_agree_with_the_python_rule(self) -> None:
        for label, path in HOSTILE_VALUES.items():
            if label in {"device name", "glob"}:
                continue  # the Python rule adds the device-name check; `*` is refused by both, but the glob case is covered below
            with self.subTest(label):
                self.assertTrue(self.refusal("app_path", app_path=path), path)
        self.assertTrue(self.refusal("app_path", app_path="apps/*"))
        for path in ("web", "apps/web", "services/api-two", "a.b/c_d", "v1.2/x"):
            with self.subTest(path):
                self.assertFalse(self.refusal("app_path", app_path=path), path)


if __name__ == "__main__":
    unittest.main()
