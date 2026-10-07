#!/usr/bin/env python3
"""Bring everything derived from packs/versions.yml up to date: the pack lockfiles, then golden/.

After a pin in ``packs/versions.yml`` moves (by hand or in a dependency-update pull request), run:

    python scripts/sync-golden.py                     # refresh both lockfiles, then regenerate golden/
    python scripts/sync-golden.py --base origin/main  # refresh only the lockfiles of stacks whose pins differ from that ref

* ``nextjs-web``: ``scripts/refresh-nextjs-web-lock.py`` rewrites the pack's ``package-lock.json.jinja`` (needs npm and the network);
* ``python-agent-service``: ``scripts/refresh-python-agent-service-lock.py`` rewrites its ``uv.lock.jinja`` (needs uv and the network);
* ``spring-backend`` and ``android-compose``: the Gradle wrapper's version comes from the pins when the files are generated, so
  regenerating ``golden/`` is all there is to do;
* ``scripts/build-golden.py`` regenerates ``golden/`` last, so it carries the new manifests and lockfiles.

The dependency-update pull requests run this in ``.github/workflows/dependency-sync.yml``, so one pull request
holds the pins, the lockfiles and ``golden/``.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
LOCK_SCRIPTS = {
    "nextjs-web": "refresh-nextjs-web-lock.py",
    "python-agent-service": "refresh-python-agent-service-lock.py",
}


def parse_pins(text: str) -> dict[str, dict[str, str]]:
    data = yaml.safe_load(text) or {}
    return {stack: {key: str(value) for key, value in (pins or {}).items()} for stack, pins in data.items()}


def changed_stacks(before: dict[str, dict[str, str]], after: dict[str, dict[str, str]]) -> list[str]:
    """The stacks whose pins differ, in the order of ``after`` (a stack that is new or gone counts as changed)."""

    names = list(after) + [stack for stack in before if stack not in after]
    return [stack for stack in names if before.get(stack) != after.get(stack)]


def pins_at(ref: str) -> dict[str, dict[str, str]] | None:
    result = subprocess.run(
        ["git", "show", f"{ref}:packs/versions.yml"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=False
    )
    return parse_pins(result.stdout) if result.returncode == 0 else None


def run(script: str, *arguments: str) -> None:
    print(f"== python scripts/{script} {' '.join(arguments)}".rstrip(), flush=True)
    result = subprocess.run([sys.executable, "-B", str(ROOT / "scripts" / script), *arguments], cwd=ROOT)
    if result.returncode != 0:
        raise SystemExit(f"scripts/{script} failed with exit code {result.returncode}.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", metavar="REF", help="Refresh only the lockfiles of stacks whose pins differ from packs/versions.yml at this git ref.")
    parser.add_argument("--golden-only", action="store_true", help="Skip the lockfiles and regenerate golden/ alone.")
    args = parser.parse_args(argv)

    stacks = list(LOCK_SCRIPTS)
    if args.golden_only:
        stacks = []
    elif args.base:
        before = pins_at(args.base)
        if before is None:
            print(f"Could not read packs/versions.yml at {args.base}; refreshing every lockfile.", flush=True)
        else:
            current = parse_pins((ROOT / "packs" / "versions.yml").read_text(encoding="utf-8"))
            moved = changed_stacks(before, current)
            stacks = [stack for stack in LOCK_SCRIPTS if stack in moved]
            print(f"Stacks whose pins differ from {args.base}: {', '.join(moved) or 'none'}.", flush=True)
    for stack in stacks:
        run(LOCK_SCRIPTS[stack])
    run("build-golden.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
