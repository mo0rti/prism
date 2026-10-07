#!/usr/bin/env python3
"""Print the pinned versions of one stack from packs/versions.yml.

The repository's workflows set up each pack's toolchain from these values, so a workflow never
repeats a version that ``packs/versions.yml`` pins. A job reads them into its step outputs:

    python scripts/read-pins.py android-compose >> "$GITHUB_OUTPUT"

and a later step uses ``${{ steps.<id>.outputs.jdk }}``. Every pin of the stack becomes one
``key=value`` line. Derived values are added where a toolchain action needs a composed string:

* ``android-compose``: ``android_packages``, the SDK packages of the app's ``compile_sdk`` platform
  and ``build_tools`` for ``android-actions/setup-android``.

``--get KEY`` prints one value alone. ``--check-xcode`` compares the installed Xcode
(``xcodebuild -version``) with the stack's ``xcode`` pin and fails when it is older, which is how the
macOS job proves the pinned baseline.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
VERSIONS = ROOT / "packs" / "versions.yml"


def load_pins(path: Path = VERSIONS) -> dict[str, dict[str, str]]:
    """Every stack's pins as strings (``21`` stays ``21``, ``0.10`` stays ``0.10``)."""

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {stack: {key: str(value) for key, value in pins.items()} for stack, pins in data.items()}


def derived_values(stack: str, pins: dict[str, str]) -> dict[str, str]:
    if stack == "android-compose":
        return {"android_packages": f"platform-tools platforms;android-{pins['compile_sdk']} build-tools;{pins['build_tools']}"}
    return {}


def stack_values(stack: str, pins_by_stack: dict[str, dict[str, str]]) -> dict[str, str]:
    if stack not in pins_by_stack:
        raise KeyError(f"No stack `{stack}` in packs/versions.yml. Stacks: {', '.join(sorted(pins_by_stack))}.")
    pins = pins_by_stack[stack]
    return {**pins, **derived_values(stack, pins)}


def version_tuple(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", text))


def installed_xcode(output: str) -> str | None:
    """The version in ``xcodebuild -version`` output (``Xcode 26.0.1``), or None."""

    match = re.search(r"^Xcode\s+(\d+(?:\.\d+)*)", output, re.MULTILINE)
    return match.group(1) if match else None


def xcode_satisfies(installed: str, pinned: str) -> bool:
    """Whether the installed Xcode is the pinned baseline or newer (missing parts count as zero)."""

    have, want = version_tuple(installed), version_tuple(pinned)
    length = max(len(have), len(want))
    return have + (0,) * (length - len(have)) >= want + (0,) * (length - len(want))


def check_xcode(pinned: str) -> int:
    try:
        result = subprocess.run(["xcodebuild", "-version"], capture_output=True, text=True, check=False)
    except OSError as error:
        print(f"xcodebuild is not available: {error}", file=sys.stderr)
        return 1
    version = installed_xcode(result.stdout)
    if result.returncode != 0 or version is None:
        print(f"Could not read the Xcode version: {(result.stdout + result.stderr).strip()}", file=sys.stderr)
        return 1
    if not xcode_satisfies(version, pinned):
        print(f"Xcode {version} is older than the pinned baseline {pinned} (packs/versions.yml).", file=sys.stderr)
        return 1
    print(f"Xcode {version} satisfies the pinned baseline {pinned}.", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stack", help="A stack of packs/versions.yml, such as nextjs-web.")
    parser.add_argument("--get", metavar="KEY", help="Print only this value.")
    parser.add_argument("--check-xcode", action="store_true", help="Fail when the installed Xcode is older than the stack's xcode pin.")
    parser.add_argument("--versions", type=Path, default=VERSIONS, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        values = stack_values(args.stack, load_pins(args.versions))
    except KeyError as error:
        print(error.args[0], file=sys.stderr)
        return 2
    if args.check_xcode:
        if "xcode" not in values:
            print(f"The stack {args.stack} has no xcode pin.", file=sys.stderr)
            return 2
        return check_xcode(values["xcode"])
    if args.get:
        if args.get not in values:
            print(f"The stack {args.stack} has no pin `{args.get}`.", file=sys.stderr)
            return 2
        sys.stdout.write(values[args.get] + "\n")
        return 0
    sys.stdout.write("".join(f"{key}={value}\n" for key, value in values.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
