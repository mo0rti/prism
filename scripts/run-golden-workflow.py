#!/usr/bin/env python3
"""Run the ``run:`` steps of a golden app's own CI workflow, so repository CI executes exactly what a generated project's CI does.

    python scripts/run-golden-workflow.py web
    python scripts/run-golden-workflow.py mobile-ios --dry-run

``golden/.github/workflows/<app>.yml`` is the workflow Prism generates for the app. GitHub only runs
workflows under the repository's own ``.github/workflows``, so a repository job sets up the toolchain
(from ``packs/versions.yml``, through ``scripts/read-pins.py``) and calls this script for the rest:

* every ``run:`` step runs in order, in bash, in its working directory (the job's
  ``defaults.run.working-directory`` or the step's own), with the job and step ``env``;
* ``GITHUB_ENV`` and ``GITHUB_PATH`` written by a step apply to the next steps, as on a runner;
* a ``uses:`` step is not executed: checkout, the setup actions, the cache and the artifact upload belong to the
  repository job. A ``uses:`` of any other action is an error, so a pack workflow that gains an action cannot
  slip past the repository job unnoticed;
* an expression (``${{ ... }}``) in a ``run:`` step or ``env`` is an error, because this script evaluates none; the one
  form it resolves is ``${{ env.NAME }}`` as a whole ``working-directory``, from the workflow's and the job's ``env``
  (a pack workflow passes the app's path that way and never writes it into a script);
* a step's ``if`` may be ``always()``, ``success()`` or ``failure()``; any other condition is an error.

The script stops at the first failing step and exits non-zero, after the steps that must always run.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

import yaml

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "golden"
# Actions the repository job replaces: their setup is not part of the commands that prove the slice.
SETUP_ACTIONS = (
    "actions/checkout@",
    "actions/setup-java@",
    "actions/setup-node@",
    "actions/cache@",
    "actions/upload-artifact@",
    "astral-sh/setup-uv@",
    "android-actions/setup-android@",
)
CONDITIONS = {"always()", "success()", "failure()"}


def find_bash() -> str:
    """Git's bash on Windows (``bash`` on PATH may be the WSL launcher), else the one on PATH."""

    configured = os.environ.get("PRISM_BASH")
    if configured:
        return configured
    if os.name == "nt":
        for folder in (os.environ.get("ProgramFiles", ""), os.environ.get("ProgramFiles(x86)", "")):
            candidate = Path(folder) / "Git" / "bin" / "bash.exe"
            if folder and candidate.is_file():
                return str(candidate)
    found = shutil.which("bash")
    if found is None:
        raise SystemExit("bash is not available; set PRISM_BASH to its path.")
    return found


def load_job(workflow_path: Path, job_name: str | None) -> tuple[str, dict, dict]:
    document = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    jobs = document.get("jobs") or {}
    if job_name is None:
        if len(jobs) != 1:
            raise SystemExit(f"{workflow_path.name} has jobs {sorted(jobs)}; name one with --job.")
        job_name = next(iter(jobs))
    if job_name not in jobs:
        raise SystemExit(f"{workflow_path.name} has no job `{job_name}`.")
    return job_name, document, jobs[job_name]


def reject_expression(text: str, where: str) -> None:
    if "${{" in str(text):
        raise SystemExit(f"{where} uses an expression (${{{{ }}}}), which this script does not evaluate.")


ENV_EXPRESSION = re.compile(r"\$\{\{\s*env\.([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


def resolve_working_directory(value: str, environment: dict[str, str], where: str) -> str:
    """A working directory as written, or the value of the `env` variable that it names as a whole (`${{ env.NAME }}`)."""

    match = ENV_EXPRESSION.fullmatch(str(value).strip())
    if match is None:
        reject_expression(value, where)
        return str(value)
    if match.group(1) not in environment:
        raise SystemExit(f"{where} names the env `{match.group(1)}`, which the workflow does not define.")
    return environment[match.group(1)]


def check_uses(step: dict, index: int) -> None:
    uses = step["uses"]
    if not uses.startswith(SETUP_ACTIONS):
        raise SystemExit(
            f"Step {index} uses `{uses}`, which the repository job does not set up. Add it to the job that calls this script, then to SETUP_ACTIONS."
        )


def read_env_file(path: Path) -> dict[str, str]:
    """The variables of a ``GITHUB_ENV`` file: ``KEY=value`` lines and ``KEY<<DELIMITER`` blocks."""

    values: dict[str, str] = {}
    if not path.is_file():
        return values
    lines = path.read_text(encoding="utf-8").splitlines()
    position = 0
    while position < len(lines):
        line = lines[position]
        position += 1
        if "<<" in line and "=" not in line.split("<<", 1)[0]:
            key, delimiter = line.split("<<", 1)
            block: list[str] = []
            while position < len(lines) and lines[position] != delimiter:
                block.append(lines[position])
                position += 1
            position += 1
            values[key] = "\n".join(block)
        elif "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


def run_workflow(app: str, workspace: Path, job_name: str | None, dry_run: bool) -> int:
    workflow_path = workspace / ".github" / "workflows" / f"{app}.yml"
    if not workflow_path.is_file():
        raise SystemExit(f"{workflow_path} does not exist.")
    job_name, document, job = load_job(workflow_path, job_name)
    defaults = (job.get("defaults") or {}).get("run") or {}
    base_env = {**(document.get("env") or {}), **(job.get("env") or {})}
    for key, value in base_env.items():
        reject_expression(value, f"The env `{key}`")

    bash = None if dry_run else find_bash()
    workspace = workspace.resolve()
    failed = False
    results: list[str] = []
    with tempfile.TemporaryDirectory(prefix="prism-golden-ci-") as temporary:
        temporary_root = Path(temporary)
        env_file, path_file = temporary_root / "github_env", temporary_root / "github_path"
        environment = {key: str(value) for key, value in base_env.items()}
        for index, step in enumerate(job.get("steps") or [], start=1):
            name = step.get("name") or step.get("uses") or (step.get("run", "").strip().splitlines() or [""])[0]
            condition = step.get("if")
            if condition is not None and str(condition).strip() not in CONDITIONS:
                raise SystemExit(f"Step {index} ({name}) has the condition `{condition}`, which this script does not evaluate.")
            if "uses" in step:
                check_uses(step, index)
                print(f"[{index}] skipped, set up by the repository job: {step['uses']}", flush=True)
                continue
            if "run" not in step:
                raise SystemExit(f"Step {index} ({name}) has neither `uses` nor `run`.")
            reject_expression(step["run"], f"Step {index} ({name})")
            step_env = {key: str(value) for key, value in (step.get("env") or {}).items()}
            for key, value in step_env.items():
                reject_expression(value, f"The env `{key}` of step {index}")
            written = step.get("working-directory") or defaults.get("working-directory") or "."
            directory = workspace / resolve_working_directory(written, {**environment, **step_env}, f"The working directory of step {index} ({name})")
            shell = step.get("shell") or defaults.get("shell") or "bash"
            if shell != "bash":
                raise SystemExit(f"Step {index} ({name}) uses shell `{shell}`; only bash is supported.")
            should_run = (
                condition is None
                or str(condition).strip() == "always()"
                or (str(condition).strip() == "success()" and not failed)
                or (str(condition).strip() == "failure()" and failed)
            )
            if condition is None and failed:
                should_run = False
            if not should_run:
                print(f"[{index}] not run after a failure: {name}", flush=True)
                continue
            print(f"[{index}] {name}  (in {directory.relative_to(workspace).as_posix() or '.'})", flush=True)
            if dry_run:
                results.append(name)
                continue
            script = temporary_root / f"step-{index}.sh"
            script.write_text(step["run"], encoding="utf-8", newline="\n")
            process_env = {**os.environ, **environment, **step_env}
            process_env.update(
                GITHUB_ENV=str(env_file), GITHUB_PATH=str(path_file), GITHUB_WORKSPACE=str(workspace),
                RUNNER_TEMP=str(temporary_root), CI="true",
            )
            command = [bash, "--noprofile", "--norc", "-eo", "pipefail", str(script)]
            completed = subprocess.run(command, cwd=directory, env=process_env)
            environment.update(read_env_file(env_file))
            env_file.write_text("", encoding="utf-8")
            if path_file.is_file():
                added = [line for line in path_file.read_text(encoding="utf-8").splitlines() if line]
                if added:
                    environment["PATH"] = os.pathsep.join(added + [environment.get("PATH", os.environ.get("PATH", ""))])
                path_file.write_text("", encoding="utf-8")
            if completed.returncode != 0:
                print(f"::error::Step {index} ({name}) of {workflow_path.name} failed with exit code {completed.returncode}.", file=sys.stderr)
                failed = True
    if dry_run:
        print(f"{len(results)} run step(s) in {workflow_path.name}, job {job_name}.")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("app", help="The app ID of the golden workspace, such as web.")
    parser.add_argument("--workspace", type=Path, default=GOLDEN, help="The generated workspace (default: golden/).")
    parser.add_argument("--job", help="The job to run; needed only when the workflow has several.")
    parser.add_argument("--dry-run", action="store_true", help="List the steps that would run, and run none.")
    args = parser.parse_args(argv)
    return run_workflow(args.app, args.workspace, args.job, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
