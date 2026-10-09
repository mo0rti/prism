"""The checks the read-only transition evaluator reports for the release actions (CONTRACTS 2.4).

The board service refuses a malformed release proposal with the contract's error codes before a preview exists; these checks are
what the preflight and a preview show for a proposal that parses: whether the apps can be released now, which target they go to
and whether QA, the bugs and the pending revalidation allow it. They read the feature page the evaluator is given, the bug and
requirement pages beside it and `SETTINGS.md`, and nothing else.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from prism_cli.qa_rules import Problem, bug_gate_problems, coverage_problems
from prism_cli.release_rules import BLOCKING_APP_DOMAINS, bug_release_inclusion_problems, target_of
from prism_cli.wiki_bugs import read_bug_pages
from prism_cli.wiki_model import (
    FeaturePage,
    WorkspaceModel,
    active_scope,
    app_stages,
    parse_app_revalidation,
    parse_criteria,
    parse_evidence_history,
    parse_revalidation,
    read_feature_evidence,
    read_wiki_settings,
)

RELEASE_STAGE = "ready-for-release"


def _check(code: str, status: str, message: str, path: Path) -> dict[str, Any]:
    return {"code": code, "status": status, "message": message, "path": str(path)}


def _wiki_root(feature: FeaturePage) -> Path:
    return feature.page.path.parent.parent


def _summary(problems: list[Problem]) -> str:
    return " ".join(item.message for item in problems[:4])


def releasable_apps(feature: FeaturePage, model: WorkspaceModel, named: Sequence[str] | None) -> list[str]:
    """The apps a check reads: the named apps, or without a proposal every active app at `ready-for-release`."""

    if named is not None:
        return list(named)
    evidence = read_feature_evidence(feature.page.body)
    stages = app_stages(active_scope(feature.apps, model), evidence)
    return [app for app, stage in stages.items() if stage == RELEASE_STAGE]


def release_done_checks(feature: FeaturePage, model: WorkspaceModel, named: Sequence[str] | None) -> list[dict[str, Any]]:
    """`release-done`: the apps are ready, their target resolves, QA still covers them, no bug blocks them and nothing is pending."""

    path = feature.page.path
    apps = releasable_apps(feature, model, named)
    if named is not None and not named:
        return [_check("release-apps", "blocked", "The proposal names no app: settle the authoritative Release row of each app it releases.", path)]
    if not apps:
        return [_check("release-apps", "blocked", f"No app is at `{RELEASE_STAGE}`: `qa-pass` writes the pending Release row that a release settles.", path)]
    evidence = read_feature_evidence(feature.page.body)
    criteria = parse_criteria(feature.page.body, feature.feature_id)
    history = parse_evidence_history(feature.page.body)
    checks: list[dict[str, Any]] = [
        _check("release-apps", "pass", f"{', '.join(f'`{app}`' for app in apps)} {'is' if len(apps) == 1 else 'are'} ready to release.", path)
    ]
    policy = read_wiki_settings(_wiki_root(feature), model).policy
    delivery_targets = {app: target_of(policy, app) for app in apps}
    missing = [app for app, target in delivery_targets.items() if target is None]
    if missing:
        checks.append(
            _check(
                "release-target",
                "blocked",
                "No delivery target resolves for " + ", ".join(f"`{app}`" for app in missing) + ": declare one under `delivery-targets` in SETTINGS.md (an app of the `other` stack must).",
                path,
            )
        )
    else:
        checks.append(_check("release-target", "pass", "Each app resolves a delivery target: " + ", ".join(f"`{app}` to `{target}`" for app, target in delivery_targets.items()) + ".", path))
    gaps: list[Problem] = []
    for app in apps:
        gaps.extend(coverage_problems(app, criteria, evidence, history))
    if gaps:
        checks.append(_check("qa-coverage", "blocked", _summary(gaps), path))
    else:
        checks.append(_check("qa-coverage", "pass", "QA still covers every criterion of the apps on their delivered artifacts.", path))
    bugs = read_bug_pages(_wiki_root(feature))
    problems = bug_gate_problems(bugs, feature_id=feature.feature_id, named=apps, evidence=evidence, code_blocks="open_bug_blocks_release")
    if problems:
        checks.append(_check("open-bugs", "blocked", _summary(problems), path))
    else:
        checks.append(_check("open-bugs", "pass", "No open bug of the feature blocks the apps.", path))
    pending, errors = parse_revalidation(feature.page.frontmatter.get("revalidation"))
    domains, domain_errors = parse_app_revalidation(feature.page.frontmatter.get("app-revalidation"))
    if errors or domain_errors:
        checks.append(_check("revalidation", "unknown", "; ".join([*errors, *domain_errors]), path))
    else:
        blocked_apps = {app: [domain for domain in domains.get(app, []) if domain in BLOCKING_APP_DOMAINS] for app in apps}
        blocked_apps = {app: items for app, items in blocked_apps.items() if items}
        if pending or blocked_apps:
            parts = ([f"feature domains {', '.join(pending)}"] if pending else []) + [f"`{app}`: {', '.join(items)}" for app, items in blocked_apps.items()]
            checks.append(_check("revalidation", "blocked", "Pending revalidation blocks the release: " + "; ".join(parts) + ".", path))
        else:
            checks.append(_check("revalidation", "pass", "No pending revalidation blocks the apps; their `release` domain clears when they are released.", path))
    return checks


def release_inclusion_checks(feature: FeaturePage, model: WorkspaceModel, named: Sequence[str] | None, included: dict[str, set[str]] | None) -> list[dict[str, Any]]:
    """Every verified bug of the feature and a released app ships with it (`verified_bug_not_included`)."""

    path = feature.page.path
    apps = releasable_apps(feature, model, named)
    bugs = read_bug_pages(_wiki_root(feature))
    verified = [bug for bug in bugs if bug.status == "verified" and bug.feature is not None and bug.feature.casefold() == feature.feature_id.casefold() and any(app in bug.apps for app in apps)]
    if not verified:
        return []
    if included is None:
        return [_check("verified-bugs", "pass", "Verified bugs of the feature ship with the apps they list: " + ", ".join(f"`{bug.bug_id}`" for bug in verified) + ".", path)]
    problems = bug_release_inclusion_problems(bugs, feature_id=feature.feature_id, named=apps, included=included)
    if problems:
        return [_check("verified-bugs", "blocked", _summary(problems), path)]
    return [_check("verified-bugs", "pass", "Every verified bug of the feature ships with the apps it lists.", path)]


def release_return_checks(feature: FeaturePage, model: WorkspaceModel) -> list[dict[str, Any]]:
    """`release-return-dev`: an app is `ready-for-release`, so a release can fail and send it back."""

    apps = releasable_apps(feature, model, None)
    path = feature.page.path
    if not apps:
        return [_check("release-apps", "blocked", f"No app is at `{RELEASE_STAGE}`: only a delivery that failed to release returns to development.", path)]
    return [_check("release-apps", "pass", f"{', '.join(f'`{app}`' for app in apps)} can return to development after a failed delivery.", path)]
