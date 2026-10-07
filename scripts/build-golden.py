#!/usr/bin/env python3
"""Regenerate the golden workspace of the repository, or verify that it is current.

``golden/`` is a workspace that ``prism new`` generates from ``scripts/golden-answers.yml``: one app
of each generated stack (backend, web, Android, iOS and the agent service). It is committed so that
a change of a pack, of the workspace layer or of ``packs/versions.yml`` shows up as a diff of what a
generated project contains, and so that CI builds and tests the slices of that committed copy.

    python scripts/build-golden.py           # regenerate golden/
    python scripts/build-golden.py --check   # fail when golden/ differs from a fresh generation

The output is deterministic. The project identity is fixed by the answers file; the three values
that differ per run or per machine are replaced by constants (the generation time, the board identity, and the template
source in the manifest and in each ``.copier-answers.yml``); line endings are LF, so a checkout with
CRLF (Windows, or ``gradlew.bat``'s ``eol=crlf`` attribute) compares equal; and the local ``.env``
(ignored by the workspace and never committed) is not part of it. Files are compared and written in
sorted order, and a file that is already current is left untouched. What building or testing a golden app leaves behind (files that git ignores and does not track, such as ``node_modules``) is neither compared nor removed.
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prism_cli.cli import DEFAULT_TEMPLATE_URL  # noqa: E402

GOLDEN = ROOT / "golden"
ANSWERS = ROOT / "scripts" / "golden-answers.yml"
FIXED_TIME = "1970-01-01T00:00:00+00:00"
# The board identity `prism new` generates for the workflow pin; a fixed, well-formed UUID keeps the output deterministic.
FIXED_BOARD_ID = "00000000-0000-4000-8000-000000000000"
# Never part of the golden workspace: the local environment file is ignored by the workspace itself.
LOCAL_ONLY_FILES = {".env"}
# Folders that building or testing a golden app leaves behind. They are skipped when comparing, so a
# local build does not fail the check, and a generated file under one of these names is refused.
BUILD_OUTPUT_DIRS = {
    "node_modules", ".next", ".gradle", ".kotlin", "build", ".venv", "__pycache__",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".idea", "DerivedData",
}


def is_binary(data: bytes) -> bool:
    return b"\0" in data


def to_lf(data: bytes) -> bytes:
    return data if is_binary(data) else data.replace(b"\r\n", b"\n")


def replace_once(text: str, pattern: str, replacement: str, label: str) -> str:
    result, count = re.subn(pattern, lambda _match: replacement, text, count=0, flags=re.MULTILINE)
    if count != 1:
        raise SystemExit(f"Expected exactly one `{label}` line, found {count}. The generated file changed shape; update scripts/build-golden.py.")
    return result


def normalize(relative: str, data: bytes) -> bytes:
    """The bytes of one generated file as golden/ stores them."""

    data = to_lf(data)
    name = relative.rsplit("/", 1)[-1]
    if name == ".copier-answers.yml":
        text = replace_once(data.decode("utf-8"), r"^_src_path: .*$", f"_src_path: {DEFAULT_TEMPLATE_URL}", "_src_path")
        return text.encode("utf-8")
    if relative == "prism.workspace.yml":
        text = data.decode("utf-8")
        text = replace_once(text, r"^  template_source: .*$", f"  template_source: {DEFAULT_TEMPLATE_URL}", "template_source")
        text = replace_once(text, r"^  generated_at: .*$", f"  generated_at: '{FIXED_TIME}'", "generated_at")
        text = replace_once(text, r"^  board_id: .*$", f"  board_id: {FIXED_BOARD_ID}", "board_id")
        return text.encode("utf-8")
    return data


def generate(destination: Path) -> None:
    """Run ``prism new`` for the answers file, from this checkout's working tree."""

    environment = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONIOENCODING="utf-8", NO_COLOR="1")
    result = subprocess.run(
        [sys.executable, "-B", "-m", "prism_cli", "new", "--answers", str(ANSWERS), "--dest", str(destination), "--template", str(ROOT), "--yes"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        sys.stderr.write((result.stdout + result.stderr)[-4000:])
        raise SystemExit(f"`prism new` failed with exit code {result.returncode}.")


def collect_generated(root: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if relative in LOCAL_ONLY_FILES:
            continue
        hidden = BUILD_OUTPUT_DIRS.intersection(relative.split("/")[:-1])
        if hidden:
            raise SystemExit(f"The generated file {relative} sits under {sorted(hidden)[0]}/, which the golden check skips; rename the folder or change BUILD_OUTPUT_DIRS.")
        files[relative] = normalize(relative, path.read_bytes())
    return files


def run_git(arguments: list[str], data: bytes = b"") -> bytes | None:
    """Output of a git command run in the repository, or None when git or the repository is unavailable."""

    try:
        result = subprocess.run(["git", *arguments], cwd=ROOT, input=data, capture_output=True, check=False)
    except OSError:
        return None
    return result.stdout if result.returncode in (0, 1) else None


def untracked_ignored() -> set[str]:
    """Files under golden/ that git ignores and does not track: what building or testing a golden app leaves behind."""

    output = run_git(["ls-files", "-z", "--others", "--ignored", "--exclude-standard", "--", GOLDEN.name])
    prefix = GOLDEN.name + "/"
    return {name[len(prefix):] for name in (output or b"").decode("utf-8").split("\0") if name.startswith(prefix)}


def git_ignored(relative_paths: list[str]) -> list[str]:
    """Of these paths of the golden workspace, the ones this repository's .gitignore files would keep out of a commit."""

    data = b"".join(f"{GOLDEN.name}/{path}\0".encode("utf-8") for path in relative_paths)
    output = run_git(["check-ignore", "--no-index", "--stdin", "-z"], data)
    prefix = GOLDEN.name + "/"
    return sorted(name[len(prefix):] for name in (output or b"").decode("utf-8").split("\0") if name.startswith(prefix))


def collect_existing(root: Path, skip: frozenset[str] | set[str] = frozenset()) -> dict[str, bytes]:
    """The files of a committed workspace, without the build output folders and the ``skip`` paths."""

    files: dict[str, bytes] = {}
    if not root.is_dir():
        return files
    for current, directories, names in os.walk(root):
        directories[:] = sorted(name for name in directories if name not in BUILD_OUTPUT_DIRS)
        for name in sorted(names):
            path = Path(current) / name
            relative = path.relative_to(root).as_posix()
            if relative not in skip:
                files[relative] = to_lf(path.read_bytes())
    return files


def differences(generated: dict[str, bytes], existing: dict[str, bytes]) -> tuple[list[str], list[str], list[str]]:
    """Files that golden/ lacks, files it has that nothing generates, and files whose content differs."""

    missing = sorted(set(generated) - set(existing))
    extra = sorted(set(existing) - set(generated))
    changed = sorted(name for name in set(generated) & set(existing) if generated[name] != existing[name])
    return missing, extra, changed


def guard_machine_values(generated: dict[str, bytes], temporary: Path) -> None:
    """A path of this machine in the output would make the check pass here and fail elsewhere."""

    needles = {str(temporary), temporary.as_posix(), str(ROOT), ROOT.as_posix()}
    needles = {needle.encode("utf-8") for needle in needles if needle}
    for name, data in generated.items():
        if is_binary(data):
            continue
        for needle in needles:
            if needle in data:
                raise SystemExit(f"{name} contains a path of this machine ({needle.decode()}); the golden workspace must not.")


def write(generated: dict[str, bytes], root: Path, skip: set[str] | frozenset[str] = frozenset()) -> tuple[int, int, int]:
    existing = collect_existing(root, skip)
    missing, extra, changed = differences(generated, existing)
    for name in extra:
        (root / name).unlink()
    for name in sorted(missing + changed):
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(generated[name])
    # Drop folders that the removed files emptied, deepest first. Build output folders are left alone.
    if root.is_dir():
        for current, directories, _names in os.walk(root, topdown=False):
            path = Path(current)
            if path != root and not any(path.iterdir()) and path.name not in BUILD_OUTPUT_DIRS:
                path.rmdir()
    return len(missing), len(changed), len(extra)


def copy_modes(source_root: Path, generated: dict[str, bytes], target_root: Path) -> None:
    """Keep the executable bit of generated scripts (POSIX only; git records it in the index)."""

    if os.name != "posix":
        return
    for name in generated:
        source = source_root / name
        if source.is_file() and os.access(source, os.X_OK):
            target = target_root / name
            target.chmod(target.stat().st_mode | 0o111)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="Fail when golden/ differs from a fresh generation; write nothing.")
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory(prefix="prism-golden-", ignore_cleanup_errors=True) as temporary:
        temporary_root = Path(temporary)
        workspace = temporary_root / "workspace"
        generate(workspace)
        generated = collect_generated(workspace)
        guard_machine_values(generated, temporary_root)
        hidden = git_ignored(sorted(generated))
        if hidden:
            raise SystemExit(f"git would not commit {hidden[0]} (and {len(hidden) - 1} more): a .gitignore covers it, so a clone would lack it.")
        leftovers = untracked_ignored()

        if args.check:
            missing, extra, changed = differences(generated, collect_existing(GOLDEN, leftovers))
            if not (missing or extra or changed):
                print(f"golden/ is current ({len(generated)} files).")
                return 0
            print("golden/ is out of date. Run `python scripts/build-golden.py` and commit the result.", file=sys.stderr)
            for label, names in (("missing", missing), ("not generated any more", extra), ("changed", changed)):
                for name in names[:40]:
                    print(f"  {label}: {name}", file=sys.stderr)
                if len(names) > 40:
                    print(f"  ... and {len(names) - 40} more {label}", file=sys.stderr)
            return 1

        added, changed, removed = write(generated, GOLDEN, leftovers)
        copy_modes(workspace, generated, GOLDEN)
        print(f"golden/ regenerated: {len(generated)} files ({added} added, {changed} changed, {removed} removed).")
        return 0


if __name__ == "__main__":
    sys.exit(main())
