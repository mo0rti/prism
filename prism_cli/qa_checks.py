"""The checks the read-only transition evaluator reports for the QA actions (CONTRACTS 2.4).

The board service refuses a malformed proposal with the contract's error codes before a preview exists; these checks are what
the preflight and a preview show for a proposal that parses: whether the evidence it carries is there and covers what the
action verifies. They read the page the evaluator is given and the bug pages beside it, and nothing else.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from prism_cli.qa_rules import (
    QA_STAGES,
    Problem,
    bug_gate_problems,
    coverage_problems,
    qa_fail_support,
)
from prism_cli.wiki_bugs import read_bug_pages
from prism_cli.wiki_model import (
    FeaturePage,
    WorkspaceModel,
    active_scope,
    app_stages,
    parse_app_revalidation,
    parse_criteria,
    parse_evidence_history,
    read_feature_evidence,
)


def _check(code: str, status: str, message: str, path: Path) -> dict[str, Any]:
    return {"code": code, "status": status, "message": message, "path": str(path)}


def _wiki_root(feature: FeaturePage) -> Path:
    return feature.page.path.parent.parent


def _in_qa(feature: FeaturePage, model: WorkspaceModel, named: Sequence[str] | None) -> list[str]:
    """The apps a check reads: the named apps, or without a proposal every active app at `ready-for-qa` or `in-qa`."""

    if named is not None:
        return list(named)
    evidence = read_feature_evidence(feature.page.body)
    stages = app_stages(active_scope(feature.apps, model), evidence)
    return [app for app, stage in stages.items() if stage in QA_STAGES]


def _summary(problems: list[Problem]) -> str:
    return " ".join(item.message for item in problems[:4])


def qa_verify_checks(feature: FeaturePage, model: WorkspaceModel, named: Sequence[str] | None) -> list[dict[str, Any]]:
    """`qa-verify`: the proposal carries QA rows for the apps it names."""

    path = feature.page.path
    evidence = read_feature_evidence(feature.page.body)
    if named is None:
        return [_check("qa-evidence", "blocked", "No QA verification was supplied: the proposal adds one row for each app or integration it verifies.", path)]
    if not named:
        return [_check("qa-evidence", "blocked", "The proposal adds no QA row: add a row for each app or integration it verifies.", path)]
    missing = [app for app in named if not evidence.qa_rows_naming(app)]
    if missing:
        return [_check("qa-evidence", "blocked", "QA verification is missing for: " + ", ".join(f"`{app}`" for app in missing) + ".", path)]
    return [_check("qa-evidence", "pass", f"QA rows are present for {len(named)} app(s); an agent must verify the references.", path)]


def qa_pass_checks(feature: FeaturePage, model: WorkspaceModel, named: Sequence[str] | None) -> list[dict[str, Any]]:
    """`qa-pass`: QA coverage (CONTRACTS 4.4), the bug rule and the revalidation of the apps it passes."""

    path = feature.page.path
    apps = _in_qa(feature, model, named)
    if named is not None and not named:
        return [_check("qa-coverage", "blocked", "The proposal names no app: add a `pending` Release row for each app it passes.", path)]
    if not apps:
        return [_check("qa-coverage", "blocked", "No app is at `ready-for-qa` or `in-qa`.", path)]
    evidence = read_feature_evidence(feature.page.body)
    criteria = parse_criteria(feature.page.body, feature.feature_id)
    history = parse_evidence_history(feature.page.body)
    problems: list[Problem] = []
    for app in apps:
        problems.extend(coverage_problems(app, criteria, evidence, history))
    checks: list[dict[str, Any]] = []
    if problems:
        checks.append(_check("qa-coverage", "blocked", _summary(problems), path))
    else:
        checks.append(_check("qa-coverage", "pass", f"Every criterion of {', '.join(f'`{app}`' for app in apps)} is covered by a passing row on its current artifact.", path))
    bugs = read_bug_pages(_wiki_root(feature))
    bug_problems = bug_gate_problems(bugs, feature_id=feature.feature_id, named=apps, evidence=evidence)
    if bug_problems:
        checks.append(_check("open-bugs", "blocked", _summary(bug_problems), path))
    else:
        checks.append(_check("open-bugs", "pass", "No open bug of the feature blocks the apps it passes.", path))
    domains, errors = parse_app_revalidation(feature.page.frontmatter.get("app-revalidation"))
    if errors:
        checks.append(_check("app-revalidation-gate", "unknown", "; ".join(errors), path))
    else:
        pending = {app: [domain for domain in domains.get(app, []) if domain in {"implementation", "tests"}] for app in apps}
        pending = {app: items for app, items in pending.items() if items}
        if pending:
            listed = "; ".join(f"`{app}`: {', '.join(items)}" for app, items in pending.items())
            checks.append(_check("app-revalidation-gate", "blocked", f"Pending app revalidation blocks QA until the app is delivered again: {listed}.", path))
        else:
            checks.append(_check("app-revalidation-gate", "pass", "No pending implementation or tests revalidation blocks the apps it passes.", path))
    return checks


def qa_fail_checks(feature: FeaturePage, model: WorkspaceModel, named: Sequence[str] | None) -> list[dict[str, Any]]:
    """`qa-fail`: each app it names has a failing row in its current attempt, or a linked bug.

    The proposal's own page has already archived the failed rows, so the board service checks the support against the page
    before the write. Here a preflight without a proposal reports whether any app can fail QA now.
    """

    path = feature.page.path
    if named is not None:
        return [_check("qa-failure-support", "pass", f"The proposal fails {len(named)} app(s); the board checks the failure against the page before the write.", path)]
    evidence = read_feature_evidence(feature.page.body)
    history = parse_evidence_history(feature.page.body)
    stages = app_stages(active_scope(feature.apps, model), evidence)
    candidates = [app for app, stage in stages.items() if stage in {"ready-for-qa", "in-qa", "ready-for-release"}]
    bugs = read_bug_pages(_wiki_root(feature))
    linked = [bug.bug_id for bug in bugs if bug.feature is not None and bug.feature.casefold() == feature.feature_id.casefold()]
    supported = [
        app
        for app in candidates
        if not qa_fail_support(named=[app], evidence=evidence, history=history, bugs=bugs, linked=linked, feature_id=feature.feature_id)
    ]
    if supported:
        return [_check("qa-failure-support", "pass", f"{', '.join(f'`{app}`' for app in supported)} can fail QA: a failing row or a linked bug supports it.", path)]
    return [_check("qa-failure-support", "blocked", "No app has a `fail` or `blocked` QA row in its current attempt or a linked, non-deferred bug in `open`, `in-fix` or `fixed`.", path)]
