"""The parallel test runner plans fixed shares, sets the git environment and reports the same tests as a serial run."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

from tests import real_temp  # noqa: F401
from tests.script_support import REPO_ROOT, load_script

run_tests = load_script("run-tests.py")


def fake_case(module: str, class_name: str, method: str = "test_it") -> unittest.TestCase:
    """A test case whose ID is ``<module>.<class_name>.<method>``, without a module of that name."""

    cls = type(class_name, (unittest.TestCase,), {method: lambda self: None, "__module__": module})
    return cls(method)


def cases_of(layout: dict[str, dict[str, int]]) -> list[unittest.TestCase]:
    return [
        fake_case(module, class_name, f"test_{number}")
        for module, classes in layout.items()
        for class_name, count in classes.items()
        for number in range(count)
    ]


class GitEnvironmentTests(unittest.TestCase):
    def test_both_settings_are_added_to_an_empty_environment(self) -> None:
        env: dict[str, str] = {}
        run_tests.apply_git_settings(env)
        self.assertEqual(
            {
                "GIT_CONFIG_COUNT": "2",
                "GIT_CONFIG_KEY_0": "gc.auto",
                "GIT_CONFIG_VALUE_0": "0",
                "GIT_CONFIG_KEY_1": "maintenance.auto",
                "GIT_CONFIG_VALUE_1": "false",
            },
            env,
        )

    def test_the_settings_follow_the_entries_that_are_already_there(self) -> None:
        env = {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.autocrlf", "GIT_CONFIG_VALUE_0": "false"}
        run_tests.apply_git_settings(env)
        self.assertEqual("3", env["GIT_CONFIG_COUNT"])
        self.assertEqual(("core.autocrlf", "false"), (env["GIT_CONFIG_KEY_0"], env["GIT_CONFIG_VALUE_0"]))
        self.assertEqual(("gc.auto", "0"), (env["GIT_CONFIG_KEY_1"], env["GIT_CONFIG_VALUE_1"]))
        self.assertEqual(("maintenance.auto", "false"), (env["GIT_CONFIG_KEY_2"], env["GIT_CONFIG_VALUE_2"]))

    def test_applying_the_settings_twice_changes_nothing(self) -> None:
        env: dict[str, str] = {}
        run_tests.apply_git_settings(env)
        before = dict(env)
        run_tests.apply_git_settings(env)
        self.assertEqual(before, env)

    def test_a_count_that_is_not_a_number_starts_the_list_again(self) -> None:
        env = {"GIT_CONFIG_COUNT": "many"}
        run_tests.apply_git_settings(env)
        self.assertEqual("2", env["GIT_CONFIG_COUNT"])


class PlanTests(unittest.TestCase):
    LAYOUT = {
        "test_small": {"SmallTests": 3},
        "test_big": {"AlphaTests": 4, "BetaTests": 4, "GammaTests": 4, "DeltaTests": 4},
        "test_unknown": {"NewTests": 10},
    }
    TIMINGS = {
        "test_small.SmallTests": 2.0,
        "test_big.AlphaTests": 100.0,
        "test_big.BetaTests": 60.0,
        "test_big.GammaTests": 50.0,
        "test_big.DeltaTests": 30.0,
    }

    def plan(self, target: float = 40.0) -> tuple[list[unittest.TestCase], list]:
        cases = cases_of(self.LAYOUT)
        return cases, run_tests.plan_units(cases, self.TIMINGS, target)

    def test_a_module_under_the_target_is_one_unit_and_every_test_is_in_exactly_one_unit(self) -> None:
        cases, units = self.plan()
        names = [unit.name for unit in units]
        self.assertIn("test_small", names)
        self.assertIn("test_unknown", names)
        self.assertEqual(list(range(len(cases))), sorted(index for unit in units for index in unit.indexes))

    def test_a_slow_module_is_split_into_units_of_whole_classes(self) -> None:
        cases, units = self.plan()
        parts = [unit for unit in units if unit.name.startswith("test_big (part ")]
        self.assertGreater(len(parts), 1)
        owners: dict[str, set[str]] = {}
        for unit in parts:
            for index in unit.indexes:
                owners.setdefault(run_tests.class_key(cases[index]), set()).add(unit.name)
        for key, names in owners.items():
            self.assertEqual(1, len(names), f"{key} is kept in one unit")
        self.assertEqual(4 * 4, sum(len(unit.indexes) for unit in parts))

    def test_the_ids_of_a_unit_are_those_of_its_cases_in_discovery_order(self) -> None:
        cases, units = self.plan()
        for unit in units:
            self.assertEqual(sorted(unit.indexes), unit.indexes)
            self.assertEqual([cases[index].id() for index in unit.indexes], unit.ids)

    def test_a_class_without_a_timing_is_weighted_by_its_test_count(self) -> None:
        _, units = self.plan()
        unknown = next(unit for unit in units if unit.name == "test_unknown")
        self.assertAlmostEqual(10 * run_tests.UNKNOWN_SECONDS_PER_TEST, unknown.weight)

    def test_the_slowest_unit_goes_first(self) -> None:
        _, units = self.plan()
        ordered = run_tests.order_longest_first(units)
        self.assertEqual(sorted((unit.weight for unit in units), reverse=True), [unit.weight for unit in ordered])

    def test_the_shards_are_disjoint_complete_and_balanced_and_do_not_depend_on_the_order_of_the_plan(self) -> None:
        _, units = self.plan()
        shares = [run_tests.shard_units(units, number, 3) for number in (1, 2, 3)]
        names = [unit.name for share in shares for unit in share]
        self.assertEqual(sorted(unit.name for unit in units), sorted(names))
        self.assertEqual(len(names), len(set(names)))
        reversed_shares = [run_tests.shard_units(list(reversed(units)), number, 3) for number in (1, 2, 3)]
        self.assertEqual([sorted(unit.name for unit in share) for share in shares], [sorted(unit.name for unit in share) for share in reversed_shares])
        loads = [sum(unit.weight for unit in share) for share in shares]
        self.assertLess(max(loads) - min(loads), max(unit.weight for unit in units))

    def test_one_shard_is_the_whole_plan(self) -> None:
        _, units = self.plan()
        self.assertEqual([unit.name for unit in units], [unit.name for unit in run_tests.shard_units(units, 1, 1)])

    def test_a_shard_argument_is_n_of_m(self) -> None:
        self.assertEqual((2, 3), run_tests.parse_shard("2/3"))
        for bad in ("0/3", "4/3", "x", "1-2", "1/"):
            with self.subTest(bad=bad), self.assertRaises(Exception):
                run_tests.parse_shard(bad)

    def test_names_select_a_module_a_class_or_a_test_but_not_a_longer_name(self) -> None:
        self.assertTrue(run_tests.selected("test_core.CoreTests.test_a", ["test_core"]))
        self.assertTrue(run_tests.selected("test_core.CoreTests.test_a", ["test_core.CoreTests"]))
        self.assertTrue(run_tests.selected("test_core.CoreTests.test_a", ["test_core.CoreTests.test_a"]))
        self.assertFalse(run_tests.selected("test_core_two.CoreTests.test_a", ["test_core"]))
        self.assertTrue(run_tests.selected("anything.at.all", []))


SAMPLE_PASSING = textwrap.dedent(
    """
    import os
    import shutil
    import subprocess
    import unittest


    class PassingTests(unittest.TestCase):
        def test_one(self) -> None:
            self.assertEqual(1, 1)

        def test_two(self) -> None:
            self.assertEqual(2, 2)

        @unittest.skip("skipped on purpose")
        def test_skipped(self) -> None:
            self.fail("not run")

        @unittest.skipUnless(shutil.which("git"), "git is needed")
        def test_git_processes_start_no_background_maintenance(self) -> None:
            for key, expected in (("gc.auto", "0"), ("maintenance.auto", "false")):
                shown = subprocess.run(["git", "config", "--get", key], capture_output=True, text=True, check=True).stdout.strip()
                self.assertEqual(expected, shown, key)
    """
)

SAMPLE_FAILING = textwrap.dedent(
    """
    import unittest


    class FailingTests(unittest.TestCase):
        def test_fails(self) -> None:
            self.assertEqual(1, 2)

        def test_errors(self) -> None:
            raise RuntimeError("boom")

        def test_passes(self) -> None:
            pass
    """
)


class RunnerProcessTests(unittest.TestCase):
    """The script runs a small suite through real worker processes."""

    def run_script(self, start_dir: Path, *arguments: str) -> subprocess.CompletedProcess:
        env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_CONFIG_")}
        return subprocess.run(
            [sys.executable, "-B", str(REPO_ROOT / "scripts" / "run-tests.py"), "--start-dir", str(start_dir), "--timings", str(start_dir / "none.json"), *arguments],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=300,
        )

    def serial_count(self, start_dir: Path) -> int:
        """The number of tests ``unittest discover`` finds, counted in its own process (the modules stay out of this one)."""

        result = subprocess.run(
            [sys.executable, "-B", "-m", "unittest", "discover", "-s", str(start_dir), "-t", str(start_dir)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=start_dir, timeout=300,
        )
        return int(result.stderr.split("Ran ", 1)[1].split(" ", 1)[0])

    def test_a_passing_suite_runs_every_test_once_and_exits_zero(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            start = Path(temporary)
            (start / "test_sample_one.py").write_text(SAMPLE_PASSING, encoding="utf-8")
            (start / "test_sample_two.py").write_text(SAMPLE_PASSING.replace("PassingTests", "OtherPassingTests"), encoding="utf-8")
            result = self.run_script(start, "--jobs", "2")
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("Ran 8 tests", result.stdout)
            self.assertIn("OK (skipped=2)", result.stdout)
            self.assertEqual(8, self.serial_count(start))

    def test_failures_and_errors_are_counted_named_and_make_the_exit_status_one(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            start = Path(temporary)
            (start / "test_sample_failing.py").write_text(SAMPLE_FAILING, encoding="utf-8")
            (start / "test_sample_passing.py").write_text(SAMPLE_PASSING, encoding="utf-8")
            result = self.run_script(start, "--jobs", "2")
            self.assertEqual(1, result.returncode, result.stdout + result.stderr)
            self.assertIn("Ran 7 tests", result.stdout)
            self.assertIn("FAILED (failures=1, errors=1, skipped=1)", result.stdout)
            self.assertIn("  FAIL: test_sample_failing.FailingTests.test_fails", result.stdout)
            self.assertIn("  ERROR: test_sample_failing.FailingTests.test_errors", result.stdout)
            self.assertIn("RuntimeError: boom", result.stdout)

    def test_a_name_runs_only_the_tests_under_it_and_two_shards_run_every_test_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            start = Path(temporary)
            (start / "test_sample_one.py").write_text(SAMPLE_PASSING, encoding="utf-8")
            (start / "test_sample_two.py").write_text(SAMPLE_PASSING.replace("PassingTests", "OtherPassingTests"), encoding="utf-8")
            named = self.run_script(start, "--jobs", "1", "test_sample_one.PassingTests.test_one")
            self.assertEqual(0, named.returncode, named.stdout + named.stderr)
            self.assertIn("Ran 1 tests", named.stdout)
            ran = 0
            for share in ("1/2", "2/2"):
                result = self.run_script(start, "--jobs", "1", "--shard", share)
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                ran += int(result.stdout.split("Ran ", 1)[1].split(" ", 1)[0])
            self.assertEqual(8, ran)

    def test_a_module_that_cannot_be_imported_fails_the_run(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            start = Path(temporary)
            (start / "test_sample_broken.py").write_text("raise ImportError('missing dependency')\n", encoding="utf-8")
            (start / "test_sample_passing.py").write_text(SAMPLE_PASSING, encoding="utf-8")
            result = self.run_script(start, "--jobs", "2")
            self.assertEqual(1, result.returncode, result.stdout + result.stderr)
            self.assertIn("ImportError: missing dependency", result.stdout)

    def test_the_timings_of_a_run_can_be_written_for_the_next_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            start = Path(temporary) / "suite"
            start.mkdir()
            (start / "test_sample_one.py").write_text(SAMPLE_PASSING, encoding="utf-8")
            written = Path(temporary) / "timings.json"
            result = self.run_script(start, "--jobs", "1", "--write-timings", str(written))
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertEqual({"test_sample_one.PassingTests"}, set(run_tests.load_timings(written)))


if __name__ == "__main__":
    unittest.main()
