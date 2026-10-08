#!/usr/bin/env python3
"""Fail on a known security advisory of high or critical severity in a pack's locked dependencies.

    python scripts/audit-gate.py npm golden/web --stack nextjs-web
    python scripts/audit-gate.py uv golden/agent-service --stack python-agent-service

``npm`` reads the app's ``package-lock.json`` with ``npm audit`` and ``uv`` reads ``uv.lock`` with
``uv audit`` (both ask the advisory database over the network). A finding passes only when
``packs/audit-allowlist.yml`` lists its advisory for the stack, with the advisory link and the reason
(a test enforces both). An allowed finding is printed with its link; an allow-list entry that no
longer matches a finding is reported so that it gets removed. Nothing is hidden silently.

The gate fails closed. An ``npm audit`` that exits with anything but 0 (clean) or 1 (findings), that returns a
report without the expected structure, or whose exit status and report disagree (a failure with no finding, a
clean exit with a finding) is an operational error, never "no unlisted advisory". The report's totals must equal its
entries (``metadata.vulnerabilities`` against ``vulnerabilities``), each entry and advisory must carry the fields the
gate reports, and every package an entry is vulnerable through must be an entry of the report. ``uv audit`` is held to the same exit statuses.
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


ADVISORY_FIELDS = ("name", "severity", "url", "title")


def npm_entries_problem(vulnerabilities: dict, declared: dict, returncode: int, level: str) -> str | None:
    """Why the entries of an ``npm audit`` report disagree with its own totals or lack a required field, or ``None``.

    Every entry names its severity and a list of ``via`` items, and every advisory (a ``via`` object) names the package,
    severity, link and title that the gate reports. The ``metadata.vulnerabilities`` counts are one per entry and severity,
    so they must equal the entries present: a report that declares a high vulnerability with no entry for it, or the other
    way round, is not a complete audit. A clean exit (0) with an entry at or above the level disagrees with npm's own rule.
    A ``via`` item that is a package name must name an entry of the report: an entry that is vulnerable through a package
    the report does not list has a chain the gate cannot follow, so its severity and advisory are unknown.
    """

    actual = {severity: 0 for severity in SEVERITIES}
    for name, entry in vulnerabilities.items():
        severity = entry.get("severity")
        if severity not in SEVERITIES:
            return f"npm audit lists `{name}` without a valid severity."
        actual[severity] += 1
        for via in entry.get("via", []):
            if isinstance(via, dict):
                missing = [field for field in ADVISORY_FIELDS if not isinstance(via.get(field), str) or not via[field]]
                if missing or via["severity"] not in SEVERITIES:
                    return f"npm audit lists an advisory of `{name}` without {', '.join(missing) or 'a valid severity'}."
            elif not isinstance(via, str):
                return f"npm audit lists a `via` item of `{name}` that is neither an advisory nor a package name."
    counts = {**actual, **({"total": len(vulnerabilities)} if "total" in declared else {})}
    for severity, present in counts.items():
        count = declared.get(severity, 0)
        if not isinstance(count, int) or isinstance(count, bool):
            return f"npm audit's metadata gives no number for {severity} vulnerabilities."
        if count != present:
            return f"npm audit's metadata declares {count} {severity} vulnerability(ies), but its report lists {present}."
    if returncode == 0 and any(actual[severity] for severity in SEVERITIES[SEVERITIES.index(level):]):
        return f"npm audit exited with status 0, but its report lists vulnerabilities of severity {level} or above."
    for name, entry in vulnerabilities.items():
        for via in entry.get("via", []):
            if isinstance(via, str) and via not in vulnerabilities:
                return f"npm audit lists `{name}` as vulnerable through `{via}`, which its report has no entry for, so the advisory chain is incomplete."
    return None


def npm_report_problem(report: object, returncode: int, level: str) -> str | None:
    """Why an ``npm audit --json`` result cannot be trusted as an audit, or ``None`` when it can."""

    if returncode not in (0, 1):
        return f"npm audit exited with status {returncode}, which is neither a clean audit (0) nor findings (1)."
    if not isinstance(report, dict):
        return "npm audit did not return a JSON object."
    if "error" in report and "vulnerabilities" not in report:
        return f"npm audit failed: {json.dumps(report['error'])[:1500]}"
    vulnerabilities = report.get("vulnerabilities")
    metadata = report.get("metadata")
    if (
        report.get("auditReportVersion") != 2
        or not isinstance(vulnerabilities, dict)
        or not isinstance(metadata, dict)
        or not isinstance(metadata.get("vulnerabilities"), dict)
        or not all(isinstance(entry, dict) and isinstance(entry.get("via", []), list) for entry in vulnerabilities.values())
    ):
        return "npm audit returned a report without the expected structure (auditReportVersion 2 with vulnerabilities and metadata)."
    entry_problem = npm_entries_problem(vulnerabilities, metadata["vulnerabilities"], returncode, level)
    if entry_problem is not None:
        return entry_problem
    findings = npm_findings(report, level)
    if returncode == 1 and not findings:
        return f"npm audit exited with status 1, but its report lists no advisory of severity {level} or above."
    if returncode == 0 and findings:
        return f"npm audit exited with status 0, but its report lists {len(findings)} advisory(ies) of severity {level} or above."
    return None


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
    problem = npm_report_problem(report, result.returncode, level)
    if problem is not None:
        print(f"::error::{problem} The audit did not run, so nothing is reported as clean. {(result.stderr or '')[-500:]}", file=sys.stderr)
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
    if result.returncode == 0:
        return 0
    if result.returncode == 1:
        print("uv audit reported a finding (exit 1). Move the pin in packs/versions.yml to a fixed version and run scripts/sync-golden.py.", file=sys.stderr)
        return 1
    print(f"::error::uv audit exited with status {result.returncode}, which is neither a clean audit (0) nor findings (1). The audit did not run, so nothing is reported as clean.", file=sys.stderr)
    return result.returncode if result.returncode > 0 else 1


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
