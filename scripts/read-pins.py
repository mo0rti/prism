#!/usr/bin/env python3
"""Print the pinned versions of one stack from packs/versions.yml.

The repository's workflows set up each pack's toolchain from these values, so a workflow never
repeats a version that ``packs/versions.yml`` pins. A job reads them into its step outputs:

    python scripts/read-pins.py android-compose >> "$GITHUB_OUTPUT"

and a later step uses ``${{ steps.<id>.outputs.jdk }}``. Every pin of the stack becomes one
``key=value`` line. Derived values are added where a toolchain action needs a composed string:

* ``android-compose``: ``android_packages``, the SDK packages of the app's ``compile_sdk`` platform
  and ``build_tools`` for ``android-actions/setup-android``.

``--get KEY`` prints one value alone. ``--select-xcode`` prints the developer directory of the installed
Xcode that matches the stack's ``xcode`` pin (a runner image holds several side by side), for ``DEVELOPER_DIR``.
``--check-xcode`` compares the Xcode in use (``xcodebuild -version``) with the pin and fails unless it is that
version: the pin ``26.0`` accepts ``26.0`` and its patch releases and refuses ``26.1`` and ``27.0``, which is
how the macOS job proves the pinned baseline.
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


def xcode_matches(installed: str, pinned: str) -> bool:
    """Whether the installed Xcode is the pinned version: the pin's own components match, and a patch release counts.

    ``26.0`` matches ``26.0`` and ``26.0.1``; it does not match ``26.1`` or ``27.0``. Missing parts count as zero.
    """

    have, want = version_tuple(installed), version_tuple(pinned)
    have = have + (0,) * (len(want) - len(have))
    return have[: len(want)] == want


def find_xcode(pinned: str, applications: Path = Path("/Applications")) -> Path | None:
    """The developer directory of the Xcode in ``applications`` that matches the pin, the latest patch release first, or None.

    A runner image keeps each Xcode as ``Xcode_<version>.app`` beside the others.
    """

    pattern = re.compile(r"Xcode_(\d+(?:\.\d+)*)\.app")
    found: list[tuple[tuple[int, ...], Path]] = []
    if applications.is_dir():
        for entry in applications.iterdir():
            match = pattern.fullmatch(entry.name)
            if match and xcode_matches(match.group(1), pinned):
                found.append((version_tuple(match.group(1)), entry))
    if not found:
        return None
    return max(found, key=lambda item: item[0])[1] / "Contents" / "Developer"


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
    if not xcode_matches(version, pinned):
        print(f"Xcode {version} is not the pinned baseline {pinned} (packs/versions.yml).", file=sys.stderr)
        return 1
    print(f"Xcode {version} is the pinned baseline {pinned}.", file=sys.stderr)
    return 0


def select_xcode(pinned: str) -> int:
    developer_dir = find_xcode(pinned)
    if developer_dir is None:
        print(f"No Xcode {pinned} (packs/versions.yml) is installed in /Applications.", file=sys.stderr)
        return 1
    sys.stdout.write(f"{developer_dir}\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stack", help="A stack of packs/versions.yml, such as nextjs-web.")
    parser.add_argument("--get", metavar="KEY", help="Print only this value.")
    parser.add_argument("--check-xcode", action="store_true", help="Fail unless the Xcode in use is the stack's xcode pin (its patch releases included).")
    parser.add_argument("--select-xcode", action="store_true", help="Print the developer directory of the installed Xcode that matches the stack's xcode pin.")
    parser.add_argument("--versions", type=Path, default=VERSIONS, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        values = stack_values(args.stack, load_pins(args.versions))
    except KeyError as error:
        print(error.args[0], file=sys.stderr)
        return 2
    if args.check_xcode or args.select_xcode:
        if "xcode" not in values:
            print(f"The stack {args.stack} has no xcode pin.", file=sys.stderr)
            return 2
        return check_xcode(values["xcode"]) if args.check_xcode else select_xcode(values["xcode"])
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
