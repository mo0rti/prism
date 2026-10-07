#!/usr/bin/env python3
"""Fail unless the named workflows have a successful run for a commit, so a broken slice cannot be released.

    python scripts/check-ci-green.py --commit "$SHA" --workflow template-validation.yml --workflow cli-validation.yml

The release workflow calls this for the tagged commit before it builds anything. Template Validation builds
and tests the golden app of every pack (and a generated workspace of each); CLI Validation runs the Python
tests, which include the golden check. For each workflow the newest run for the commit decides:

* it succeeded: pass;
* it is still queued or running: wait for it (up to ``--wait-minutes``), then judge it;
* it failed, was cancelled or timed out: fail, with the run's link;
* there is no run for the commit (the path filters of a workflow can skip a commit): fail, and say how to start one
  (``gh workflow run <workflow> --ref <tag>``).

The runs are read with the GitHub CLI (``gh run list``), which needs ``GH_TOKEN`` and ``actions: read``.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from typing import Callable

COMPLETED = "completed"


def newest_first(runs: list[dict]) -> list[dict]:
    return sorted(runs, key=lambda run: run.get("createdAt", ""), reverse=True)


def evaluate(runs: list[dict]) -> tuple[str, str]:
    """``("ok" | "pending" | "failed" | "missing", detail)`` for the runs of one workflow at one commit."""

    if not runs:
        return "missing", "no run for this commit"
    latest = newest_first(runs)[0]
    link = latest.get("url", "")
    if latest.get("status") != COMPLETED:
        return "pending", f"the newest run is {latest.get('status', 'unknown')} {link}".strip()
    if latest.get("conclusion") == "success":
        return "ok", f"the newest run succeeded {link}".strip()
    return "failed", f"the newest run ended with {latest.get('conclusion') or 'no conclusion'} {link}".strip()


def list_runs(workflow: str, commit: str, repository: str | None) -> list[dict]:
    command = ["gh", "run", "list", "--workflow", workflow, "--commit", commit, "--limit", "50", "--json", "status,conclusion,createdAt,url,event"]
    if repository:
        command += ["--repo", repository]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=False)
    if result.returncode != 0:
        raise RuntimeError(f"gh run list failed for {workflow}: {(result.stdout + result.stderr).strip()[-500:]}")
    return json.loads(result.stdout or "[]")


def check(
    workflows: list[str],
    commit: str,
    repository: str | None,
    wait_minutes: float,
    fetch: Callable[[str, str, str | None], list[dict]] = list_runs,
    sleep: Callable[[float], None] = time.sleep,
    interval_seconds: float = 60.0,
    clock: Callable[[], float] = time.monotonic,
) -> int:
    deadline = clock() + wait_minutes * 60
    failures: list[str] = []
    for workflow in workflows:
        while True:
            state, detail = evaluate(fetch(workflow, commit, repository))
            if state != "pending" or clock() >= deadline:
                break
            print(f"{workflow}: {detail}; checking again in {int(interval_seconds)} seconds.", flush=True)
            sleep(interval_seconds)
        if state == "ok":
            print(f"{workflow}: {detail}")
            continue
        if state == "pending":
            detail = f"{detail}; it did not finish within {wait_minutes:g} minutes"
        if state == "missing":
            detail += f". Start one with `gh workflow run {workflow} --ref <tag>` and release again once it passes"
        failures.append(f"{workflow}: {detail}")
    for failure in failures:
        print(f"::error::{failure}")
    if failures:
        print(f"CI is not green for {commit}; nothing is released.", file=sys.stderr)
        return 1
    print(f"CI is green for {commit}.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--commit", required=True, help="The full SHA of the commit that is released.")
    parser.add_argument("--workflow", action="append", required=True, help="A workflow file name; repeat for each one that must be green.")
    parser.add_argument("--repo", help="OWNER/NAME (default: the repository of the checkout).")
    parser.add_argument("--wait-minutes", type=float, default=120.0, help="How long to wait for a run that is still going.")
    args = parser.parse_args(argv)
    try:
        return check(args.workflow, args.commit, args.repo, args.wait_minutes)
    except RuntimeError as error:
        print(f"::error::{error}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
