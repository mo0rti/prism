"""Step selection, the host table and the seeding plan."""

from pathlib import Path
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prism_e2e import config  # noqa: E402
from prism_e2e.config import Action  # noqa: E402


class ParseTests(unittest.TestCase):
    def test_no_selection_means_every_step_in_canonical_order(self):
        self.assertEqual(config.parse_steps(None), list(config.STEP_IDS))
        self.assertEqual(config.parse_steps(""), list(config.STEP_IDS))

    def test_selection_is_sorted_into_canonical_order_without_duplicates(self):
        self.assertEqual(config.parse_steps("dev-done, dev-clarify,dev-done"), ["dev-clarify", "dev-done"])

    def test_unknown_step_is_rejected_with_the_valid_names(self):
        with self.assertRaises(config.ConfigError) as caught:
            config.parse_steps("po-intake,nope")
        self.assertIn("nope", str(caught.exception))
        self.assertIn("dev-done", str(caught.exception))

    def test_hosts(self):
        self.assertEqual(config.parse_hosts(None), ["claude", "codex"])
        self.assertEqual(config.parse_hosts("codex"), ["codex"])
        self.assertEqual(config.parse_hosts("codex,codex,claude"), ["codex", "claude"])
        with self.assertRaises(config.ConfigError):
            config.parse_hosts("gemini")
        with self.assertRaises(config.ConfigError):
            config.parse_hosts(",")


class FixtureSetResolutionTests(unittest.TestCase):
    def folder(self, *names, prompts=()):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        for name in names:
            (root / name).mkdir()
        if prompts:
            (root / "prompts").mkdir()
            for name in prompts:
                (root / "prompts" / f"{name}.txt").write_text("text", encoding="utf-8")
        return root

    def test_no_value_and_no_variable_mean_the_default_set_alone(self):
        self.assertIsNone(config.resolve_fixture_set(None, {}))
        self.assertIsNone(config.resolve_fixture_set("", {config.FIXTURES_ENV: "   "}))

    def test_the_variable_applies_when_the_option_is_absent_and_the_option_wins(self):
        first = self.folder("dev-done")
        second = self.folder("po-specify", prompts=("po-specify",))
        self.assertEqual(config.resolve_fixture_set(None, {config.FIXTURES_ENV: str(first)}), first.resolve())
        self.assertEqual(config.resolve_fixture_set(second, {config.FIXTURES_ENV: str(first)}), second.resolve())

    def test_the_shipped_api_work_set_is_valid(self):
        self.assertEqual(config.resolve_fixture_set(config.API_WORK_FIXTURES_DIR, {}), config.API_WORK_FIXTURES_DIR.resolve())

    def test_a_missing_folder_an_empty_folder_and_stray_folders_are_rejected(self):
        with self.assertRaises(config.ConfigError) as missing:
            config.resolve_fixture_set(Path("no-such-fixture-set-folder"), {})
        self.assertIn("is not a folder", str(missing.exception))
        with self.assertRaises(config.ConfigError) as empty:
            config.resolve_fixture_set(self.folder(), {})
        self.assertIn("holds no step folder", str(empty.exception))
        with self.assertRaises(config.ConfigError) as stray:
            config.resolve_fixture_set(self.folder("dev-done", "dev-donee"), {})
        self.assertIn("dev-donee", str(stray.exception))
        self.assertIn("dev-done", str(stray.exception), "the message names the valid steps")

    def test_a_prompt_must_belong_to_an_agent_step(self):
        for name in ("po-handoff", "no-such-step"):
            with self.subTest(prompt=name), self.assertRaises(config.ConfigError) as caught:
                config.resolve_fixture_set(self.folder("dev-done", prompts=(name,)), {})
            self.assertIn(name, str(caught.exception))


class TableTests(unittest.TestCase):
    def test_the_eleven_lifecycle_steps(self):
        self.assertEqual(
            config.STEP_IDS,
            ("po-intake", "ask", "po-clarify", "po-specify", "po-handoff", "design-start", "design-clarify",
             "design-handoff", "dev-clarify", "dev-start", "dev-done"),
        )

    def test_only_the_three_direct_human_actions_run_in_the_browser(self):
        human = [step.id for step in config.STEPS if step.is_human]
        self.assertEqual(human, ["po-handoff", "design-start", "dev-start"])
        self.assertEqual(set(config.HUMAN_ACTION_LABELS), set(human))

    def test_agent_steps_alternate_between_the_hosts(self):
        hosts = [step.host for step in config.STEPS if not step.is_human]
        self.assertTrue(all(first != second for first, second in zip(hosts, hosts[1:])), hosts)

    def test_host_for_falls_back_to_the_first_enabled_host(self):
        ask = config.STEPS_BY_ID["ask"]  # fixed to codex
        self.assertEqual(config.host_for(ask, ["claude", "codex"]), "codex")
        self.assertEqual(config.host_for(ask, ["claude"]), "claude")
        self.assertIsNone(config.host_for(config.STEPS_BY_ID["dev-start"], ["claude"]))

    def test_tiers_name_explicit_models_for_both_hosts(self):
        self.assertEqual(config.TIERS["smoke"]["claude"].model, "claude-haiku-4-5")
        self.assertEqual(config.TIERS["smoke"]["codex"].model, "gpt-6-luna")
        self.assertEqual(config.TIERS["full"]["claude"], config.HostModel("claude-sonnet-5-5", "medium"))
        self.assertEqual(config.TIERS["full"]["codex"], config.HostModel("gpt-6.1-sol", "medium"))
        self.assertIn(config.TIERS["smoke"]["codex"].effort, ("low", "medium"))


class PlanTests(unittest.TestCase):
    def test_every_step_needs_no_seeding(self):
        actions = config.plan_actions(list(config.STEP_IDS))
        self.assertEqual(actions, [Action("run", step) for step in config.STEP_IDS])

    def test_a_selection_from_the_start_needs_no_seeding(self):
        self.assertEqual(config.plan_actions(["po-intake", "ask"]), [Action("run", "po-intake"), Action("run", "ask")])

    def test_a_late_subset_seeds_the_state_before_its_first_step(self):
        self.assertEqual(
            config.plan_actions(["dev-clarify", "dev-done"]),
            [Action("seed", "design-handoff"), Action("run", "dev-clarify"), Action("seed", "dev-start"), Action("run", "dev-done")],
        )

    def test_adjacent_steps_run_on_each_others_state(self):
        self.assertEqual(
            config.plan_actions(["dev-start", "dev-done"]),
            [Action("seed", "dev-clarify"), Action("run", "dev-start"), Action("run", "dev-done")],
        )

    def test_a_gap_in_the_middle_is_seeded(self):
        self.assertEqual(
            config.plan_actions(["po-intake", "dev-done"]),
            [Action("run", "po-intake"), Action("seed", "dev-start"), Action("run", "dev-done")],
        )

    def test_the_second_step_seeds_the_first(self):
        self.assertEqual(config.plan_actions(["ask"]), [Action("seed", "po-intake"), Action("run", "ask")])

    def test_the_last_step_seeds_the_one_before_it(self):
        self.assertEqual(config.plan_actions(["dev-done"]), [Action("seed", "dev-start"), Action("run", "dev-done")])


if __name__ == "__main__":
    unittest.main()
