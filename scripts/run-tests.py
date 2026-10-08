#!/usr/bin/env python3
"""Run the Python test suite across worker processes and print one combined summary.

    python -B scripts/run-tests.py                       # every test in tests/, one worker per CPU
    python -B scripts/run-tests.py -j 4                  # four workers
    python -B scripts/run-tests.py test_core test_wiki   # only the tests under these module, class or test names
    python -B scripts/run-tests.py --shard 2/3           # the second of three fixed shares (CI splits a slow job this way)
    python -B scripts/run-tests.py --list --shard 1/2    # show the units and their weights without running them

The suite is the one ``python -B -m unittest discover -s tests`` finds: the same discovery, the same test IDs, the same
count. The runner only decides where each test runs. A test module is one unit; a module that is slower than the target
(``--target-seconds``) is split into units of whole test classes, so a class's fixtures are never separated from its
tests. Units go to the workers longest first, so the slowest module starts first and the short ones fill the gaps. The
expected duration of each class comes from ``scripts/test-timings.json``; a class without an entry is weighted by its
test count. ``--write-timings`` records the durations of a run to refresh that file.

Every worker is a fresh process that imports the whole suite the way the serial run does and then runs its units, so
each test sees the same imported modules as in a serial run. Each worker's standard output and error stay quiet unless a
unit fails (``--verbose`` shows them always).

Every git process a test starts gets ``gc.auto=0`` and ``maintenance.auto=false`` through ``GIT_CONFIG_COUNT`` and its
key and value variables, so no clone, Copier's included, can start a background gc that races with a test's cleanup.

The exit status is 0 when every test passed or was skipped and 1 when a test failed or errored, when the workers did not
run exactly the tests the discovery found, or when no test ran.
"""

from __future__ import annotations

import argparse
from collections import OrderedDict
import concurrent.futures
import contextlib
import io
import json
import multiprocessing
import os
from pathlib import Path
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_START_DIR = "tests"
TIMINGS_PATH = ROOT / "scripts" / "test-timings.json"
DEFAULT_TARGET_SECONDS = 40.0
UNKNOWN_SECONDS_PER_TEST = 0.05
GIT_SETTINGS = (("gc.auto", "0"), ("maintenance.auto", "false"))


# ---------------------------------------------------------------- the git environment


def apply_git_settings(env: "os._Environ[str] | dict[str, str]") -> None:
    """Add the settings of ``GIT_SETTINGS`` to ``env`` for every git process below it, keeping the entries already there."""

    try:
        count = max(int(env.get("GIT_CONFIG_COUNT") or "0"), 0)
    except ValueError:
        count = 0
    present = {(env.get(f"GIT_CONFIG_KEY_{index}"), env.get(f"GIT_CONFIG_VALUE_{index}")) for index in range(count)}
    for key, value in GIT_SETTINGS:
        if (key, value) in present:
            continue
        env[f"GIT_CONFIG_KEY_{count}"] = key
        env[f"GIT_CONFIG_VALUE_{count}"] = value
        count += 1
    env["GIT_CONFIG_COUNT"] = str(count)


# ---------------------------------------------------------------- discovery


def flatten(suite: unittest.TestSuite) -> list[unittest.TestCase]:
    cases: list[unittest.TestCase] = []
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            cases.extend(flatten(item))
        else:
            cases.append(item)
    return cases


def prepare_paths(start_dir: Path) -> None:
    for path in (str(ROOT), str(start_dir)):
        if path in sys.path:
            sys.path.remove(path)
        sys.path.insert(0, path)


def discover(start_dir: Path, pattern: str = "test*.py") -> list[unittest.TestCase]:
    """Every test case in the order ``unittest discover -s <start_dir>`` runs them."""

    prepare_paths(start_dir)
    return flatten(unittest.TestLoader().discover(str(start_dir), pattern=pattern, top_level_dir=str(start_dir)))


def class_key(case: unittest.TestCase) -> str:
    cls = type(case)
    return f"{cls.__module__}.{cls.__qualname__}"


def selected(case_id: str, patterns: list[str]) -> bool:
    return not patterns or any(case_id == pattern or case_id.startswith(pattern + ".") for pattern in patterns)


# ---------------------------------------------------------------- planning


class Unit:
    """Tests that run together in one worker, in discovery order."""

    def __init__(self, name: str, indexes: list[int], ids: list[str], weight: float) -> None:
        self.name = name
        self.indexes = indexes
        self.ids = ids
        self.weight = weight


def load_timings(path: Path) -> dict[str, float]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    classes = data.get("classes") if isinstance(data, dict) else None
    if not isinstance(classes, dict):
        return {}
    return {str(key): float(value) for key, value in classes.items() if isinstance(value, (int, float))}


def plan_units(
    cases: list[unittest.TestCase],
    timings: dict[str, float],
    target_seconds: float = DEFAULT_TARGET_SECONDS,
) -> list[Unit]:
    """One unit per module, or several units of whole classes for a module slower than 1.5 times the target.

    The plan depends only on the discovered tests, the timings and the target, so every shard of a CI job computes the same plan.
    """

    modules: "OrderedDict[str, OrderedDict[str, list[int]]]" = OrderedDict()
    for index, case in enumerate(cases):
        cls = type(case)
        modules.setdefault(cls.__module__, OrderedDict()).setdefault(class_key(case), []).append(index)

    def weight_of(key: str, indexes: list[int]) -> float:
        return timings.get(key, UNKNOWN_SECONDS_PER_TEST * len(indexes))

    units: list[Unit] = []
    for module, classes in modules.items():
        weights = {key: weight_of(key, indexes) for key, indexes in classes.items()}
        total = sum(weights.values())
        if total <= target_seconds * 1.5 or len(classes) == 1:
            groups = [list(classes)]
        else:
            count = min(len(classes), int(-(-total // target_seconds)))
            bins: list[tuple[float, list[str]]] = [(0.0, []) for _ in range(count)]
            for key in sorted(classes, key=lambda item: (-weights[item], item)):
                position = min(range(count), key=lambda number: (bins[number][0], number))
                load, members = bins[position]
                bins[position] = (load + weights[key], members + [key])
            groups = [members for _, members in bins if members]
            groups.sort(key=lambda members: min(classes[key][0] for key in members))
        for number, members in enumerate(groups, 1):
            indexes = sorted(index for key in members for index in classes[key])
            name = module if len(groups) == 1 else f"{module} (part {number}/{len(groups)})"
            units.append(Unit(name, indexes, [cases[index].id() for index in indexes], sum(weights[key] for key in members)))
    return units


def order_longest_first(units: list[Unit]) -> list[Unit]:
    return sorted(units, key=lambda unit: (-unit.weight, unit.name))


def shard_units(units: list[Unit], shard: int, shards: int) -> list[Unit]:
    """The units of the one-based ``shard`` of ``shards``: a fixed longest-first balance of the whole plan."""

    if shards == 1:
        return list(units)
    loads = [0.0] * shards
    members: list[list[Unit]] = [[] for _ in range(shards)]
    for unit in order_longest_first(units):
        position = min(range(shards), key=lambda number: (loads[number], number))
        loads[position] += unit.weight
        members[position].append(unit)
    return members[shard - 1]


# ---------------------------------------------------------------- one unit in a worker


class TimedResult(unittest.TestResult):
    """A result that keeps the time of each class: the time between two finished tests belongs to the later test's class."""

    def __init__(self) -> None:
        super().__init__()
        self.class_seconds: dict[str, float] = {}
        self._mark = time.perf_counter()

    def stopTest(self, test: unittest.TestCase) -> None:
        super().stopTest(test)
        now = time.perf_counter()
        key = class_key(test)
        self.class_seconds[key] = self.class_seconds.get(key, 0.0) + now - self._mark
        self._mark = now


_WORKER_CASES: list[unittest.TestCase] = []


def init_worker(start_dir: str, pattern: str) -> None:
    """Import the whole suite once, as the serial run does, and keep its cases for the units this worker gets."""

    global _WORKER_CASES
    os.chdir(ROOT)
    _WORKER_CASES = discover(Path(start_dir), pattern)


def run_unit(name: str, indexes: list[int], ids: list[str]) -> dict:
    cases = [_WORKER_CASES[index] if index < len(_WORKER_CASES) else None for index in indexes]
    found = [case.id() if case is not None else None for case in cases]
    if found != ids:
        raise RuntimeError(f"The worker found different tests than the planner for {name}; the discovery is not deterministic.")
    output = io.StringIO()
    result = TimedResult()
    started = time.perf_counter()
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
        suite = unittest.TestSuite()
        suite.addTests(cases)
        suite.run(result)
    return {
        "name": name,
        "ran": result.testsRun,
        "seconds": time.perf_counter() - started,
        "failures": [(test.id(), text) for test, text in result.failures],
        "errors": [(test.id(), text) for test, text in result.errors],
        "skipped": [(test.id(), reason) for test, reason in result.skipped],
        "expected_failures": len(result.expectedFailures),
        "unexpected_successes": [test.id() for test in result.unexpectedSuccesses],
        "class_seconds": result.class_seconds,
        "output": output.getvalue(),
    }


# ---------------------------------------------------------------- the combined run


class Totals:
    def __init__(self) -> None:
        self.ran = 0
        self.test_seconds = 0.0
        self.failures: list[tuple[str, str]] = []
        self.errors: list[tuple[str, str]] = []
        self.skipped: list[tuple[str, str]] = []
        self.expected_failures = 0
        self.unexpected_successes: list[str] = []
        self.class_seconds: dict[str, float] = {}
        self.lost_units: list[str] = []

    def add(self, unit_result: dict) -> None:
        self.ran += unit_result["ran"]
        self.test_seconds += unit_result["seconds"]
        self.failures += unit_result["failures"]
        self.errors += unit_result["errors"]
        self.skipped += unit_result["skipped"]
        self.expected_failures += unit_result["expected_failures"]
        self.unexpected_successes += unit_result["unexpected_successes"]
        for key, seconds in unit_result["class_seconds"].items():
            self.class_seconds[key] = self.class_seconds.get(key, 0.0) + seconds

    @property
    def failed(self) -> bool:
        return bool(self.failures or self.errors or self.unexpected_successes or self.lost_units)


def unit_status(unit_result: dict) -> str:
    if unit_result["failures"] or unit_result["errors"] or unit_result["unexpected_successes"]:
        return "FAILED"
    return "ok"


def run_units(units: list[Unit], jobs: int, start_dir: Path, pattern: str, verbose: bool) -> Totals:
    totals = Totals()
    if not units:
        return totals
    ordered = order_longest_first(units)
    workers = max(1, min(jobs, len(ordered)))
    context = multiprocessing.get_context("spawn")
    done = 0
    width = len(str(len(ordered)))
    with concurrent.futures.ProcessPoolExecutor(
        max_workers=workers, mp_context=context, initializer=init_worker, initargs=(str(start_dir), pattern)
    ) as pool:
        pending = {pool.submit(run_unit, unit.name, unit.indexes, unit.ids): unit for unit in ordered}
        try:
            for future in concurrent.futures.as_completed(pending):
                unit = pending[future]
                done += 1
                try:
                    unit_result = future.result()
                except concurrent.futures.process.BrokenProcessPool as error:
                    totals.lost_units.append(f"{unit.name}: a worker process died ({error})")
                    print(f"[{done:>{width}}/{len(ordered)}] {unit.name}: a worker process died", flush=True)
                    continue
                except Exception as error:  # noqa: BLE001 - report the unit and keep running the rest
                    totals.lost_units.append(f"{unit.name}: {type(error).__name__}: {error}")
                    print(f"[{done:>{width}}/{len(ordered)}] {unit.name}: {type(error).__name__}: {error}", flush=True)
                    continue
                totals.add(unit_result)
                print(
                    f"[{done:>{width}}/{len(ordered)}] {unit_result['seconds']:7.1f}s  {unit_result['ran']:>4} tests  {unit_status(unit_result):<6}  {unit.name}",
                    flush=True,
                )
                if unit_result["output"] and (verbose or unit_status(unit_result) == "FAILED"):
                    print(f"--- output of {unit.name} ---\n{unit_result['output'].rstrip()}\n--- end of output ---", flush=True)
        except concurrent.futures.process.BrokenProcessPool:
            pass
        for future, unit in pending.items():
            if not future.done():
                totals.lost_units.append(f"{unit.name}: never ran")
    return totals


def write_timings(path: Path, totals: Totals) -> None:
    classes = {key: round(seconds, 2) for key, seconds in sorted(totals.class_seconds.items())}
    path.write_text(json.dumps({"classes": classes}, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def report(totals: Totals, expected: int, wall_seconds: float, workers: int, verbose: bool) -> int:
    for label, entries in (("FAIL", totals.failures), ("ERROR", totals.errors)):
        for test_id, text in entries:
            print("=" * 70)
            print(f"{label}: {test_id}")
            print("-" * 70)
            print(text.rstrip())
            print()
    if verbose:
        for test_id, reason in totals.skipped:
            print(f"SKIP: {test_id}: {reason}")
    print("-" * 70)
    print(f"Ran {totals.ran} tests in {wall_seconds:.1f}s on {workers} workers ({totals.test_seconds:.1f}s of test time).")
    problems = []
    if totals.ran != expected:
        problems.append(f"the workers ran {totals.ran} tests but the discovery found {expected}")
    problems += totals.lost_units
    details = []
    if totals.failures:
        details.append(f"failures={len(totals.failures)}")
    if totals.errors:
        details.append(f"errors={len(totals.errors)}")
    if totals.skipped:
        details.append(f"skipped={len(totals.skipped)}")
    if totals.expected_failures:
        details.append(f"expected failures={totals.expected_failures}")
    if totals.unexpected_successes:
        details.append(f"unexpected successes={len(totals.unexpected_successes)}")
    suffix = f" ({', '.join(details)})" if details else ""
    failed = totals.failed or bool(problems) or totals.ran == 0
    print(f"{'FAILED' if failed else 'OK'}{suffix}")
    if failed:
        for test_id, _ in totals.failures:
            print(f"  FAIL: {test_id}")
        for test_id, _ in totals.errors:
            print(f"  ERROR: {test_id}")
        for test_id in totals.unexpected_successes:
            print(f"  UNEXPECTED SUCCESS: {test_id}")
        for problem in problems:
            print(f"  {problem}")
        if totals.ran == 0:
            print("  no test ran")
    return 1 if failed else 0


def parse_shard(text: str) -> tuple[int, int]:
    try:
        shard, shards = (int(part) for part in text.split("/"))
    except ValueError:
        raise argparse.ArgumentTypeError("use N/M, for example 2/3") from None
    if not 1 <= shard <= shards:
        raise argparse.ArgumentTypeError("N must be between 1 and M")
    return shard, shards


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("names", nargs="*", help="Run only the tests whose ID is, or starts with, one of these names (a module, a class or a test).")
    parser.add_argument("-j", "--jobs", type=int, default=os.cpu_count() or 1, help="Worker processes (default: the CPU count).")
    parser.add_argument("--shard", type=parse_shard, default=(1, 1), metavar="N/M", help="Run only share N of M of the units, as a fixed balance of the whole plan.")
    parser.add_argument("--start-dir", default=DEFAULT_START_DIR, help=f"The directory to discover tests in (default: {DEFAULT_START_DIR}).")
    parser.add_argument("--pattern", default="test*.py", help="The file pattern of test modules (default: test*.py).")
    parser.add_argument("--timings", type=Path, default=TIMINGS_PATH, help="The file with the expected seconds of each test class.")
    parser.add_argument("--target-seconds", type=float, default=DEFAULT_TARGET_SECONDS, help="Split a module slower than 1.5 times this into units of whole classes.")
    parser.add_argument("--write-timings", type=Path, metavar="PATH", help="Write the measured seconds of each class to this file after the run.")
    parser.add_argument("--list", action="store_true", help="Print the units of the plan (and this shard) and exit without running.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Also print every unit's output and the skipped tests.")
    args = parser.parse_args(argv)
    if args.jobs < 1:
        parser.error("--jobs must be at least 1")
    shard, shards = args.shard

    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError):
            stream.reconfigure(errors="replace")
    os.chdir(ROOT)
    apply_git_settings(os.environ)
    start_dir = (ROOT / args.start_dir).resolve() if not Path(args.start_dir).is_absolute() else Path(args.start_dir)

    cases = discover(start_dir, args.pattern)
    chosen = [case for case in cases if selected(case.id(), args.names)]
    if args.names and not chosen:
        print(f"No test matches {', '.join(args.names)}.", file=sys.stderr)
        return 1
    # Indexes stay those of the whole discovery: a worker finds its cases by the same numbers.
    wanted = {id(case) for case in chosen}
    plan = plan_units(cases, load_timings(args.timings), args.target_seconds)
    if args.names:
        trimmed: list[Unit] = []
        for unit in plan:
            keep = [(index, test_id) for index, test_id in zip(unit.indexes, unit.ids) if id(cases[index]) in wanted]
            if keep:
                weight = unit.weight * len(keep) / len(unit.indexes)
                trimmed.append(Unit(unit.name, [i for i, _ in keep], [t for _, t in keep], weight))
        plan = trimmed
    units = shard_units(plan, shard, shards)
    expected = sum(len(unit.indexes) for unit in units)
    label = f"shard {shard}/{shards}: " if shards > 1 else ""
    print(f"{label}{expected} of {len(cases)} tests in {len(units)} units; expected {sum(unit.weight for unit in units):.0f}s of test time.", flush=True)

    if args.list:
        for unit in order_longest_first(units):
            print(f"{unit.weight:8.1f}s  {len(unit.indexes):>5} tests  {unit.name}")
        return 0

    workers = max(1, min(args.jobs, len(units)))
    started = time.perf_counter()
    totals = run_units(units, args.jobs, start_dir, args.pattern, args.verbose)
    wall = time.perf_counter() - started
    status = report(totals, expected, wall, workers, args.verbose)
    if args.write_timings is not None:
        write_timings(args.write_timings, totals)
    return status


if __name__ == "__main__":
    sys.exit(main())
