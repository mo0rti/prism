#!/usr/bin/env python3
"""Rewrite the committed uv.lock of the python-agent-service pack from packs/versions.yml.

The pack's ``pyproject.toml.jinja`` reads every dependency version from ``packs/versions.yml``, and its
``uv.lock.jinja`` records the resolved tree so that ``uv sync --locked`` installs the same packages on every
machine. After a pin changes, run this script to refresh the lock; a test fails while the lock disagrees with
the pins. It needs ``uv`` and network access to the Python package index, and writes only the lock.

    python scripts/refresh-python-agent-service-lock.py
"""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import yaml
from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[1]
PACK_APP = ROOT / "packs" / "python-agent-service" / "{{ app_path }}"
PYPROJECT_TEMPLATE = PACK_APP / "pyproject.toml.jinja"
LOCK_TEMPLATE = PACK_APP / "uv.lock.jinja"
# A name uv writes into the lock unchanged: lowercase letters, digits and a hyphen.
PROJECT_MARK = "prismprojectmark"
APP_MARK = "prismappmark"
NAME_MARK = f"{PROJECT_MARK}-{APP_MARK}"
NAME_EXPRESSION = "{{ project_slug }}-{{ app_id }}"


def render_pyproject() -> str:
    """The pack's pyproject.toml for a placeholder app, with the pinned versions."""

    versions = yaml.safe_load((ROOT / "packs" / "versions.yml").read_text(encoding="utf-8"))["python-agent-service"]
    template = Environment(keep_trailing_newline=True).from_string(PYPROJECT_TEMPLATE.read_text(encoding="utf-8"))
    return template.render(
        versions=versions,
        project_slug=PROJECT_MARK,
        app_id=APP_MARK,
        app_name="App",
        project_name="Project",
    )


def main() -> int:
    uv = shutil.which("uv")
    if uv is None:
        print("uv is not on PATH.", file=sys.stderr)
        return 1
    with tempfile.TemporaryDirectory() as temporary:
        work = Path(temporary)
        (work / "pyproject.toml").write_text(render_pyproject(), encoding="utf-8", newline="\n")
        result = subprocess.run([uv, "lock"], cwd=work, capture_output=True, text=True, errors="replace")
        if result.returncode != 0:
            print((result.stdout + result.stderr)[-2000:], file=sys.stderr)
            return result.returncode
        text = (work / "uv.lock").read_text(encoding="utf-8").replace("\r\n", "\n")

    if NAME_MARK not in text:
        print("The lock does not name the placeholder app; the template and this script disagree.", file=sys.stderr)
        return 1
    for forbidden in ("{{", "{%", "{#"):
        if forbidden in text:
            print(f"The lock contains `{forbidden}`, which Copier would read as Jinja.", file=sys.stderr)
            return 1
    LOCK_TEMPLATE.write_text(text.replace(NAME_MARK, NAME_EXPRESSION), encoding="utf-8", newline="\n")
    print(f"Wrote {LOCK_TEMPLATE.relative_to(ROOT).as_posix()} for {text.count('[[package]]') - 1} packages.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
