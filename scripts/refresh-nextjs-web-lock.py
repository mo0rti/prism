#!/usr/bin/env python3
"""Rewrite the committed package-lock.json of the nextjs-web pack from packs/versions.yml.

The pack's ``package.json.jinja`` reads every dependency version from ``packs/versions.yml``, and its
``package-lock.json.jinja`` records the resolved tree so that ``npm ci`` installs the same packages on
every machine. After a pin changes, run this script to refresh the lock; a test fails while the lock
disagrees with the pins. It needs ``npm`` and network access to the npm registry, and writes only the lock.

    python scripts/refresh-nextjs-web-lock.py
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import yaml
from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[1]
PACK_APP = ROOT / "packs" / "nextjs-web" / "{{ app_path }}"
PACKAGE_TEMPLATE = PACK_APP / "package.json.jinja"
LOCK_TEMPLATE = PACK_APP / "package-lock.json.jinja"
NAME_MARK = "__PRISM_PROJECT__-__PRISM_APP__"
NAME_EXPRESSION = "{{ project_slug }}-{{ app_id }}"


def render_package_json() -> str:
    """The pack's package.json for a placeholder app, with the pinned versions."""

    versions = yaml.safe_load((ROOT / "packs" / "versions.yml").read_text(encoding="utf-8"))["nextjs-web"]
    template = Environment(keep_trailing_newline=True).from_string(PACKAGE_TEMPLATE.read_text(encoding="utf-8"))
    return template.render(
        versions=versions,
        project_slug="__PRISM_PROJECT__",
        app_id="__PRISM_APP__",
        app_path="web",
        port=3000,
    )


def main() -> int:
    npm = shutil.which("npm")
    if npm is None:
        print("npm is not on PATH.", file=sys.stderr)
        return 1
    with tempfile.TemporaryDirectory() as temporary:
        work = Path(temporary)
        (work / "package.json").write_text(render_package_json(), encoding="utf-8", newline="\n")
        result = subprocess.run(
            [npm, "install", "--package-lock-only", "--ignore-scripts", "--no-audit", "--no-fund"],
            cwd=work,
            capture_output=True,
            text=True,
            errors="replace",
        )
        if result.returncode != 0:
            print((result.stdout + result.stderr)[-2000:], file=sys.stderr)
            return result.returncode
        lock = json.loads((work / "package-lock.json").read_text(encoding="utf-8"))

    text = json.dumps(lock, indent=2, ensure_ascii=False) + "\n"
    if NAME_MARK not in text:
        print("The lock does not name the placeholder app; the template and this script disagree.", file=sys.stderr)
        return 1
    for forbidden in ("{{", "{%", "{#"):
        if forbidden in text:
            print(f"The lock contains `{forbidden}`, which Copier would read as Jinja.", file=sys.stderr)
            return 1
    text = text.replace(NAME_MARK, NAME_EXPRESSION)
    LOCK_TEMPLATE.write_text(text, encoding="utf-8", newline="\n")
    print(f"Wrote {LOCK_TEMPLATE.relative_to(ROOT).as_posix()} for {len(lock.get('packages', {})) - 1} packages.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
