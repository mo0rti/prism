#!/usr/bin/env python3
"""Fail on a known security advisory of high or critical severity in a pack's locked dependencies.

    python scripts/audit-gate.py npm golden/web --stack nextjs-web
    python scripts/audit-gate.py uv golden/agent-service --stack python-agent-service

``npm`` reads the app's ``package-lock.json`` with ``npm audit`` and ``uv`` reads ``uv.lock`` with
``uv audit`` (both ask the advisory database over the network). A finding passes only when
``packs/audit-allowlist.yml`` lists its advisory for the stack, with the advisory link and the reason
(a test enforces both). An allowed finding is printed with its link; an allow-list entry that no
longer matches a finding is reported so that it gets removed. Nothing is hidden silently.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST = ROOT / "packs" / "audit-allowlist.yml"
SEVERITIES = ("info", "low", "moderate", "high", "critical")
ADVISORY_ID = re.compile(r"(GHSA-[0-9a-z]{4}-[0-9a-z]{4}-[0-9a-z]{4}|PYSEC-\d+-\d+|CVE-\d+-\d+)", re.IGNORECASE)


def normalize_id(advisory: str) -> str:
    """GHSA identifiers are ``GHSA-`` and lower-case groups; the others are upper case."""

    advisory = advisory.strip()
    if advisory.lower().startswith("ghsa-"):
        return "GHSA-" + advisory[5:].lower()
    return advisory.upper()


def load_allowlist(path: Path, stack: str) -> list[dict[str, str]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return list(data.get(stack) or [])


def npm_findings(report: dict, level: str = "high") -> list[dict[str, str]]:
    """The advisories of severity ``level`` or above in an ``npm audit --json`` report, one per advisory.

    A vulnerable package that is only vulnerable through another (``via`` is a name) carries no advisory of
    its own: the advisory is reported once, on the package it is about.
    """

    minimum = SEVERITIES.index(level)
    found: dict[str, dict[str, str]] = {}
    for name, entry in (report.get("vulnerabilities") or {}).items():
        for via in entry.get("via", []):
            if not isinstance(via, dict):
                continue
            severity = via.get("severity", "")
            if severity not in SEVERITIES or SEVERITIES.index(severity) < minimum:
                continue
            url = via.get("url", "")
            match = ADVISORY_ID.search(url)
            advisory = normalize_id(match.group(1)) if match else str(via.get("source", url))
            found.setdefault(
                advisory,
                {
                    "advisory": advisory,
                    "package": via.get("name", name),
                    "severity": severity,
                    "title": via.get("title", ""),
                    "url": url,
                },
            )
    return sorted(found.values(), key=lambda finding: finding["advisory"])


def classify(findings: list[dict[str, str]], allowed: list[dict[str, str]]) -> tuple[list[dict], list[dict], list[dict]]:
    """Blocked findings, allowed findings and allow-list entries that matched nothing."""

    allowed_ids = {normalize_id(entry["advisory"]) for entry in allowed}
    blocked = [finding for finding in findings if normalize_id(finding["advisory"]) not in allowed_ids]
    accepted = [finding for finding in findings if normalize_id(finding["advisory"]) in allowed_ids]
    seen = {normalize_id(finding["advisory"]) for finding in findings}
    stale = [entry for entry in allowed if normalize_id(entry["advisory"]) not in seen]
    return blocked, accepted, stale


def run_npm(directory: Path, stack: str, allowlist: Path, level: str) -> int:
    npm = shutil.which("npm")
    if npm is None:
        print("npm is not on PATH.", file=sys.stderr)
        return 1
    if not (directory / "package-lock.json").is_file():
        print(f"{directory} has no package-lock.json to audit.", file=sys.stderr)
        return 1
    result = subprocess.run(
        [npm, "audit", f"--audit-level={level}", "--json"],
        cwd=directory,
        capture_output=True,
        text=True,
        errors="replace",
    )
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"npm audit returned no report (exit {result.returncode}): {(result.stdout + result.stderr)[-1500:]}", file=sys.stderr)
        return 1
    if "error" in report and "vulnerabilities" not in report:
        print(f"npm audit failed: {json.dumps(report['error'])[:1500]}", file=sys.stderr)
        return 1
    findings = npm_findings(report, level)
    allowed = load_allowlist(allowlist, stack)
    blocked, accepted, stale = classify(findings, allowed)
    totals = (report.get("metadata") or {}).get("vulnerabilities", {})
    print(f"npm audit of {directory.resolve().name} (level {level}): {totals}")
    for finding in accepted:
        print(f"allowed: {finding['advisory']} {finding['package']} ({finding['severity']}) {finding['url']}")
    for entry in stale:
        print(f"warning: the allow-list entry {entry['advisory']} for {stack} matches no finding; remove it from {allowlist.name}.")
    for finding in blocked:
        print(f"::error::{finding['advisory']} in {finding['package']} ({finding['severity']}): {finding['title']} {finding['url']}")
    if blocked:
        print(f"{len(blocked)} advisory(ies) of severity {level} or above are not in {allowlist.name}. Move the pin in packs/versions.yml to a fixed version and run scripts/sync-golden.py.", file=sys.stderr)
        return 1
    print("No unlisted advisory.")
    return 0


def run_uv(directory: Path, stack: str, allowlist: Path) -> int:
    uv = shutil.which("uv")
    if uv is None:
        print("uv is not on PATH.", file=sys.stderr)
        return 1
    if not (directory / "uv.lock").is_file():
        print(f"{directory} has no uv.lock to audit.", file=sys.stderr)
        return 1
    allowed = load_allowlist(allowlist, stack)
    command = [uv, "audit", "--locked", "--preview-features", "audit-command"]
    for entry in allowed:
        command += ["--ignore", entry["advisory"]]
    for entry in allowed:
        print(f"allowed: {entry['advisory']} {entry['package']} {entry['url']}")
    result = subprocess.run(command, cwd=directory, text=True, errors="replace")
    if result.returncode != 0:
        print(f"uv audit reported a finding (exit {result.returncode}). Move the pin in packs/versions.yml to a fixed version and run scripts/sync-golden.py.", file=sys.stderr)
    return result.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("tool", choices=("npm", "uv"))
    parser.add_argument("directory", type=Path, help="The app folder that holds the lockfile.")
    parser.add_argument("--stack", required=True, help="The stack whose allow-list entries apply.")
    parser.add_argument("--allowlist", type=Path, default=ALLOWLIST, help=argparse.SUPPRESS)
    parser.add_argument("--level", choices=SEVERITIES, default="high", help="The lowest severity that fails (npm only; uv audit fails on any finding).")
    args = parser.parse_args(argv)
    if args.tool == "npm":
        return run_npm(args.directory, args.stack, args.allowlist, args.level)
    return run_uv(args.directory, args.stack, args.allowlist)


if __name__ == "__main__":
    sys.exit(main())
