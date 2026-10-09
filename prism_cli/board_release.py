"""The release half of the board service: `release-done` and its variants, the bug release and the reopen routes (CONTRACTS 2.3 to 2.8, 5.3, 6.2).

`ReleaseActionsMixin` is mixed into `BoardService`. A `release-done` proposal writes one new release record and, with it,
the Release rows of the features it delivers, the Release rows and status of the bugs it ships, and the Release row of a
released feature that a bug fix reaches. Its variants write the record alone (rollback, redeploy) or return one feature to
development (`release-return-dev`). The reopen routes of a released feature (`reopen-spec`, `reopen-design`, `reopen-dev`)
archive its evidence. Each method validates against the pages before the write (`before`) and the pages the proposal carries
(`supplied`), raises the contract's error code for the first rule that fails and returns what the preview needs. The rules
themselves live in `release_rules.py`, which the read-only evaluator and lint share.
"""

from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from prism_cli.board_bugs import bs, is_bug_path
from prism_cli.board_qa import _quoted, raise_first
from prism_cli.qa_rules import (
    Problem,
    bug_gate_problems,
    coverage_problems,
    every_row,
    merged_app_revalidation,
    qa_fail_archive,
)
from prism_cli.release_rules import (
    BLOCKING_APP_DOMAINS,
    ReleasedApp,
    bug_release_inclusion_problems,
    check_bug_fix_row,
    check_feature_release_rows,
    check_record_page,
    contract_cited_by,
    record_front_matter_problems,
    record_row_problems,
    redeploy_problems,
    release_bug_blocking,
    rollback_problems,
    snapshot_problems,
    target_of,
)
from prism_cli.wiki_bugs import BugPage, verification_artifact
from prism_cli.wiki_model import (
    APP_REVALIDATION_DOMAINS,
    active_scope,
    app_stages,
    clean_cell,
    contract_page_citation,
    merge_revalidation,
    normalize_feature_id,
    parse_app_revalidation,
    parse_evidence_history,
    parse_markdown_text,
    parse_release_rows,
    parse_revalidation,
    read_feature_pages,
    stale_qa_rows,
    status_rank,
)
from prism_cli.wiki_releases import (
    KIND_REDEPLOY,
    KIND_RELEASE,
    KIND_ROLLBACK,
    RELEASE_FILE_PATTERN,
    ReleaseRecord,
    format_record_id,
    next_release_number,
    parse_record_rows,
    parse_snapshots,
    read_release_records,
    record_id_of_cell,
    record_kinds,
    record_sections,
    release_attempt_of,
)

RELEASE_SKILL = "release-done"
D4_RELEASE_ACTIONS = frozenset({"release-done", "release-return-dev", "release-rollback", "release-redeploy"})
D4_REOPEN_ACTIONS = frozenset({"reopen-spec", "reopen-design", "reopen-dev"})
RELEASE_PREFIX = "knowledge/wiki/releases/"
_LINKED_PREFIXES = ("knowledge/wiki/app-requirements/", "knowledge/wiki/api-contracts/")


def is_release_path(relative: str) -> bool:
    return relative.startswith(RELEASE_PREFIX)


def _blank(text: str) -> bool:
    return not text.strip() or text.strip().startswith("[")


def _says_nothing(text: str) -> bool:
    """A section that is empty, a template placeholder or a statement that there is nothing (`None.`)."""

    return _blank(text) or text.strip().rstrip(".").casefold() in {"none", "n/a", "not applicable", "nothing"}


class ReleaseActionsMixin:
    """The release actions of `BoardService`."""

    # -- reading ---------------------------------------------------------------------------------------------------------

    @property
    def _recovering(self) -> bool:
        """Whether this service is the scratch copy a recovery or repair rebuilds: the record keeps the number and the day it was previewed with."""

        return bool(getattr(self, "_recovery_candidate", False))

    def _disk_records(self) -> list[ReleaseRecord]:
        return read_release_records(self._wiki_path())  # type: ignore[attr-defined]

    def _d4_error(self, problem: Problem, path: str | None = None) -> "bs.BoardError":
        return bs.BoardError(problem.code, problem.message, 409, {**({"path": path} if path else {}), **dict(problem.details)})

    # -- the record ------------------------------------------------------------------------------------------------------

    def _d4_record(self, supplied: Mapping[str, str], before: Mapping[str, str | None]) -> dict[str, Any]:
        """The one new record a release proposal writes: its page checked, its number checked against the records on disk."""

        paths = [path for path in supplied if is_release_path(path)]
        if len(paths) != 1:
            raise bs.BoardError(
                "release_record_required",
                "A release proposal writes exactly one new release record under `knowledge/wiki/releases/`; this one writes "
                + (f"{len(paths)}: {', '.join(f'`{path}`' for path in sorted(paths)[:3])}." if paths else "none."),
                409,
                {"paths": bs._names(paths)},
            )
        path = paths[0]
        frontmatter, body = bs._parse_markdown(supplied[path], path)
        records = self._disk_records()
        name = PurePosixPath(path).name
        match = RELEASE_FILE_PATTERN.match(name)
        record_id = frontmatter.get("id")
        if before.get(path) is not None or any(record.page.path.name == name or (isinstance(record_id, str) and record.record_id == record_id) for record in records):
            raise bs.BoardError(
                "release_id_taken",
                f"`{record_id or name}` is already a release record, and a record is never rewritten. Take the next free number.",
                409,
                {"path": path},
            )
        today = None if self._recovering else date.today()
        raise_first(check_record_page(path, frontmatter, body, today=today, proposal=True), path)
        number = int(RELEASE_FILE_PATTERN.match(name).group("id")[4:]) if match else 0  # type: ignore[union-attr]
        expected = next_release_number(records)
        if not self._recovering and number != expected:
            raise bs.BoardError(
                "release_sequence_invalid",
                f"A release record takes the number after the highest one on disk: the next is `{format_record_id(expected)}`, not `{record_id}`.",
                409,
                {"path": path, "expected": format_record_id(expected)},
            )
        rows, row_problems = parse_record_rows(body)
        return {
            "path": path,
            "id": str(record_id),
            "frontmatter": frontmatter,
            "body": body,
            "records": records,
            "kinds": record_kinds(records),
            "rows": rows,
            "row_problems": row_problems,
        }

    def _d4_record_checks(self, record: Mapping[str, Any], kind: str) -> None:
        """The rows of the record, and its front matter, agree among themselves."""

        path = record["path"]
        raise_first(record_row_problems(record["rows"], kind, record["row_problems"]), path)
        raise_first(record_front_matter_problems(path, record["frontmatter"], record["rows"], kind), path)
        sections = record_sections(record["body"])
        if kind == KIND_ROLLBACK and _says_nothing(sections.get("Rollback", "")):
            raise bs.BoardError("release_record_invalid", f"`{path}`: a rollback record says in `## Rollback` what was rolled back and why.", 409, {"path": path})
        for item in {row.item for row in record["rows"]}:
            if not self._d4_item_exists(item):
                raise bs.BoardError("release_record_invalid", f"`{path}`: the Delivery table names `{item}`, which is not a feature or bug of this wiki.", 409, {"path": path, "item": item})

    def _d4_item_exists(self, item: str) -> bool:
        if item.startswith("F-"):
            return any(normalize_feature_id(feature.feature_id) == normalize_feature_id(item) for feature in read_feature_pages(self._wiki_path()))  # type: ignore[attr-defined]
        return any(bug.bug_id.casefold() == item.casefold() for bug in self._disk_bugs())  # type: ignore[attr-defined]

    def _d4_item_apps(self, item: str) -> list[str]:
        if item.startswith("F-"):
            for feature in read_feature_pages(self._wiki_path()):  # type: ignore[attr-defined]
                if normalize_feature_id(feature.feature_id) == normalize_feature_id(item):
                    return list(feature.apps)
            return []
        for bug in self._disk_bugs():  # type: ignore[attr-defined]
            if bug.bug_id.casefold() == item.casefold():
                return list(bug.apps)
        return []

    # -- the dispatcher --------------------------------------------------------------------------------------------------

    def _validate_release_done(
        self,
        supplied: Mapping[str, str],
        before: Mapping[str, str | None],
        changed_features: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Validate a `release-done` proposal: pick the action from the record and the pages it carries, check it and return the operation."""

        self._require_action_available("release-done")  # type: ignore[attr-defined]
        record = self._d4_record(supplied, before)
        frontmatter = record["frontmatter"]
        kinds = record["kinds"]
        feature_paths = [feature["path"] for feature in changed_features]
        bug_paths = [path for path in supplied if is_bug_path(path)]
        other = [path for path in supplied if path != record["path"] and path not in feature_paths and path not in bug_paths]
        if "rollback-of" in frontmatter:
            action = "release-rollback"
        elif not feature_paths and not bug_paths and not other:
            action = "release-redeploy"
        elif len(feature_paths) == 1 and not bug_paths and self._d4_appends_return_entry(feature_paths[0], supplied, before):
            action = "release-return-dev"
        else:
            action = "release-done"
        self._require_action_available(action)  # type: ignore[attr-defined]
        if action in {"release-rollback", "release-redeploy"}:
            if feature_paths or bug_paths or other:
                raise bs.BoardError(
                    "lifecycle_write_scope",
                    f"`{action}` writes the release record alone; the features and bugs it names keep their pages, because a feature or bug row records its own delivery.",
                    409,
                    {"paths": bs._names([*feature_paths, *bug_paths, *other])},
                )
            return self._d4_record_only(action, record)
        if action == "release-return-dev":
            return self._d4_release_return(record, supplied, before, changed_features[0])
        if other:
            raise bs.BoardError(
                "lifecycle_write_scope",
                "`release-done` writes the feature pages, the bug pages and the release record; no other page.",
                409,
                {"paths": bs._names(other)},
            )
        return self._d4_release(record, supplied, before, changed_features, bug_paths)

    def _d4_appends_return_entry(self, feature_path: str, supplied: Mapping[str, str], before: Mapping[str, str | None]) -> bool:
        old = parse_evidence_history(bs._parse_markdown(before[feature_path] or "", feature_path)[1])
        new = parse_evidence_history(bs._parse_markdown(supplied[feature_path], feature_path)[1])
        return len(new) > len(old) and new[-1].action == "release-return-dev"

    # -- rollback and redeploy (F21, F22) --------------------------------------------------------------------------------

    def _d4_record_only(self, action: str, record: Mapping[str, Any]) -> dict[str, Any]:
        frontmatter, path = record["frontmatter"], record["path"]
        records, kinds, rows = record["records"], record["kinds"], record["rows"]
        kind = KIND_ROLLBACK if action == "release-rollback" else KIND_REDEPLOY
        if kind == KIND_REDEPLOY:
            retry = frontmatter.get("retry-of")
            if not isinstance(retry, str):
                raise bs.BoardError(
                    "release_record_invalid",
                    f"`{path}` changes no feature or bug page, so it is a rollback (`rollback-of`) or a redeploy (`retry-of` the rollback or the failed redeploy it retries).",
                    409,
                    {"path": path},
                )
        self._d4_record_checks(record, kind)
        if parse_snapshots(record["body"])[0]:
            raise bs.BoardError("release_contract_snapshot_invalid", f"`{path}`: a {kind} record snapshots no contract.", 409, {"path": path})
        for row in rows:
            if row.app not in self._d4_item_apps(row.item):
                raise bs.BoardError("release_record_invalid", f"`{path}`: `{row.app}` is not an app of {row.item}.", 409, {"path": path, "item": row.item, "app": row.app})
        if kind == KIND_ROLLBACK:
            raise_first(rollback_problems(rollback_of=str(frontmatter["rollback-of"]), rows=rows, records=records, kinds=kinds), path)
        else:
            raise_first(redeploy_problems(retry_of=str(frontmatter["retry-of"]), rows=rows, records=records, kinds=kinds), path)
        return self._d4_operation(
            action,
            record["id"],
            None,
            None,
            f"The {kind} record {record['id']} matches its (app, target) bindings.",
            checks=[],
        )

    def _d4_operation(
        self,
        action: str,
        subject: str,
        source: Mapping[str, Any] | None,
        target: Mapping[str, Any] | None,
        message: str,
        *,
        checks: list[dict[str, Any]],
        classification: str = "ready",
        warnings: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        structure = {"code": "release-structure", "status": "pass", "message": message}
        all_checks = [structure, *checks]
        blockers = [item for item in all_checks if item.get("status") in {"blocked", "unknown", "review"}]
        return {
            "action": action,
            "feature_id": subject,
            "source": dict(source) if source is not None else None,
            "target": dict(target) if target is not None else None,
            "classification": classification if not blockers else (classification if classification != "ready" else "blocked"),
            "checks": all_checks,
            "blockers": blockers,
            "warnings": warnings or [],
            "produces_evidence": [],
            "separation_subjects": [],
        }

    # -- release-done (F18, F19) -----------------------------------------------------------------------------------------

    def _d4_release(
        self,
        record: Mapping[str, Any],
        supplied: Mapping[str, str],
        before: Mapping[str, str | None],
        changed_features: list[dict[str, Any]],
        bug_paths: list[str],
    ) -> dict[str, Any]:
        path = record["path"]
        records, kinds, rows = record["records"], record["kinds"], record["rows"]
        frontmatter = record["frontmatter"]
        record_id = record["id"]
        wiki = self._wiki_path()  # type: ignore[attr-defined]
        policy = self._read_policy()  # type: ignore[attr-defined]
        if not changed_features and not bug_paths:
            raise bs.BoardError(
                "release_apps_required",
                "A release proposal carries the feature page whose Release rows it settles, or the bug pages it ships; this one carries neither.",
                409,
                {"path": path},
            )
        self._d4_record_checks(record, KIND_RELEASE)
        retry = frontmatter.get("retry-of")
        if isinstance(retry, str):
            source = next((item for item in records if item.record_id == retry), None)
            if source is None or kinds.get(retry) != KIND_RELEASE or not any(row.outcome == "failed" for row in source.rows):
                raise bs.BoardError(
                    "release_record_invalid",
                    f"`{path}`: `retry-of: {retry}` names a release record with a failed delivery; a retry of a rollback is a redeploy.",
                    409,
                    {"path": path, "retry_of": retry},
                )

        bugs = self._bugs_with(supplied)  # type: ignore[attr-defined]
        bug_by_id = {bug.bug_id.casefold(): bug for bug in bugs}
        disk_bugs = {bug.bug_id.casefold(): bug for bug in self._disk_bugs()}  # type: ignore[attr-defined]

        # The rows the pages carry, per item, and the apps a bug fix reaches.
        expected: dict[tuple[str, str], tuple[str, str, int | None, str, str]] = {}
        snapshot_expected: dict[tuple[str, str], tuple[str, str | None]] = {}
        released_named: dict[str, list[ReleasedApp]] = {}
        fix_updates: dict[str, set[str]] = {}
        feature_outputs: list[dict[str, Any]] = []

        # Bugs first: they decide which released apps a feature page may update.
        bug_apps: dict[str, list[tuple[str, str, str, int, str, str]]] = {}
        bug_operations: dict[str, dict[str, Any]] = {}
        for relative in sorted(bug_paths):
            info = self._d4_bug(relative, supplied, before, record_id, records, kinds, policy)
            bug_apps[info["bug"].bug_id] = info["apps"]
            bug_operations[relative] = info
            for app, target, version, attempt, outcome, basis in info["apps"]:
                expected[(info["bug"].bug_id, app)] = (target, version, attempt, outcome, basis)

        included: dict[str, set[str]] = {}
        for bug_id, items in bug_apps.items():
            included[bug_id] = {item[0] for item in items}

        for feature in changed_features:
            relative = feature["path"]
            old_fm, new_fm = feature["before"], feature["after"]
            if old_fm is None:
                raise bs.BoardError("feature_not_found", "`release-done` settles the Release rows of existing features; it cannot create one.", 409, {"path": relative})
            pages = self._d3_pages(feature, supplied, before)  # type: ignore[attr-defined]
            feature_id = pages["feature_id"]
            scope, active = pages["scope"], pages["active"]
            old_evidence, new_evidence = pages["old_evidence"], pages["new_evidence"]
            stages = pages["stages"]
            fix_apps = self._d4_fix_apps(old_evidence, new_evidence, active)
            self._validate_lifecycle_write_scope("release-done", relative, before[relative] or "", supplied[relative], old_fm, new_fm)  # type: ignore[attr-defined]
            if fix_apps:
                fix_updates[feature_id] = fix_apps
            named, problems = check_feature_release_rows(
                feature_id=feature_id,
                old=old_evidence,
                new=new_evidence,
                stages=stages,
                active=active,
                policy=policy,
                attempt_of=lambda app, fid=feature_id: release_attempt_of(records, kinds, fid, app),
                record_id=record_id,
                fix_apps=fix_apps,
            )
            raise_first(problems, relative)
            if not named and not fix_apps:
                raise bs.BoardError(
                    "release_apps_required",
                    f"`release-done` names the apps it settles by changing their authoritative Release rows from `pending` or `failed` to `released` or `failed`; the proposed `{relative}` changes none.",
                    409,
                    {"path": relative},
                )
            if named:
                self._require_no_retired_app_in_progress(feature_id, old_fm)  # type: ignore[attr-defined]
                if old_fm.get("status") not in {"in-dev", "ready-for-qa", "in-qa", "ready-for-release"}:
                    raise bs.BoardError("unsupported_source_pair", f"Action `release-done` requires {feature_id} in development, QA or `ready-for-release`; it is `{old_fm.get('status')}`.", 409, {"path": relative})
                self._d4_feature_gates(pages, named, relative, supplied, bugs, included)
                released_named[feature_id] = named
                for item in named:
                    expected[(feature_id, item.app)] = (item.target, item.version, item.attempt, item.outcome, item.basis)
            elif old_fm.get("status") != new_fm.get("status") or old_fm.get("owner") != new_fm.get("owner"):
                raise bs.BoardError(
                    "app_stage_mismatch",
                    f"The proposed `{relative}` only updates the Release row of an app a bug fix reaches, so {feature_id} keeps its status and owner.",
                    409,
                    {"path": relative},
                )
            feature_outputs.append({"feature": feature, "pages": pages, "named": named, "fix_apps": fix_apps})
            # The contract each delivered row cites is snapshotted in the record.
            for app in [item.app for item in named] + sorted(fix_apps):
                cited = contract_cited_by(next(row.cells for row in old_evidence.delivery if row.app == app)) if old_evidence.delivery_row(app) else None
                if cited is not None:
                    snapshot_expected[(feature_id, app)] = (cited, self._d4_contract_text(feature, cited, supplied))

        # A bug fix reaches the feature app it ships for; the feature page updates its Release row.
        for relative, info in bug_operations.items():
            bug: BugPage = info["bug"]
            for app, target, version, attempt, outcome, basis in info["apps"]:
                self._d4_bug_feature_link(bug, app, outcome, version, record_id, supplied, before, released_named, fix_updates, feature_outputs, disk_bugs)

        for feature_id, apps in fix_updates.items():
            for app in sorted(apps):
                if not any(
                    bug.feature is not None
                    and normalize_feature_id(bug.feature) == normalize_feature_id(feature_id)
                    and any(item[0] == app and item[4] == "released" for item in bug_apps.get(bug.bug_id, []))
                    for info in bug_operations.values()
                    for bug in [info["bug"]]
                ):
                    raise bs.BoardError(
                        "release_row_invalid",
                        f"The Release row of `{app}` in {feature_id} is already released; it changes only when a bug of {feature_id} that lists `{app}` ships in this release.",
                        409,
                        {"feature_id": feature_id, "app": app},
                    )
        raise_first(self._d4_record_rows_problems(path, rows, expected), path)
        # Snapshots of the contracts the delivered rows cite.
        snapshots, snapshot_parse = parse_snapshots(record["body"])
        raise_first(snapshot_problems(snapshots, snapshot_parse, expected=snapshot_expected, path=path), path)
        self._d4_dependencies(supplied, {feature_id: {item.app for item in items} for feature_id, items in released_named.items()})

        # The evaluator judges each feature that settles a row, and the record's own structure.
        checks: list[dict[str, Any]] = []
        classification = "ready"
        first_source: dict[str, Any] | None = None
        first_target: dict[str, Any] | None = None
        subject = record_id
        for output in feature_outputs:
            if not output["named"]:
                continue
            feature = output["feature"]
            transition = self._evaluate_proposed_action(  # type: ignore[attr-defined]
                "release-done", supplied, feature, tuple(item.app for item in output["named"])
            )
            checks.extend(transition.get("checks", []))
            state = transition.get("classification", "unknown")
            if not transition.get("supported"):
                state = "unknown" if state == "ready" else state
            if state != "ready" and classification == "ready":
                classification = state
            if first_source is None:
                first_source = {"status": feature["before"].get("status"), "owner": feature["before"].get("owner")}
                first_target = {"status": feature["after"].get("status"), "owner": feature["after"].get("owner")}
                subject = str(feature["id"])
        if subject == record_id and bug_paths:
            subject = bs._parse_markdown(supplied[sorted(bug_paths)[0]], sorted(bug_paths)[0])[0].get("id") or record_id
        return self._d4_operation(
            "release-done",
            str(subject),
            first_source,
            first_target,
            f"The release record {record_id} matches the Release rows of {', '.join(sorted({item for item, _app in expected})) or 'its items'}.",
            checks=checks,
            classification=classification,
        )

    def _d4_record_rows_problems(self, path: str, rows: list, expected: Mapping[tuple[str, str], tuple[str, str, int | None, str, str]]) -> list[Problem]:
        """The Delivery rows of the record are exactly the rows the pages settle (`release_record_mismatch`)."""

        problems: list[Problem] = []
        actual = {(row.item, row.app): (row.target, row.version, row.attempt, row.outcome, row.basis) for row in rows}
        for key in sorted(set(expected) - set(actual)):
            problems.append(Problem("release_record_mismatch", f"`{path}`: the Delivery table has no row for {key[0]} and `{key[1]}`, which the proposal releases.", {"path": path, "item": key[0], "app": key[1]}))
        for key in sorted(set(actual) - set(expected)):
            problems.append(
                Problem("release_record_mismatch", f"`{path}`: the Delivery table has a row for {key[0]} and `{key[1]}`, which no page of the proposal releases.", {"path": path, "item": key[0], "app": key[1]})
            )
        for key in sorted(set(actual) & set(expected)):
            if actual[key] != expected[key]:
                problems.append(
                    Problem(
                        "release_record_mismatch",
                        f"`{path}`: the Delivery row of {key[0]} and `{key[1]}` says (target, version, attempt, outcome, basis) {actual[key]}; the Release row says {expected[key]}.",
                        {"path": path, "item": key[0], "app": key[1]},
                    )
                )
        return problems

    def _d4_contract_text(self, feature: Mapping[str, Any], citation: str, supplied: Mapping[str, str]) -> str | None:
        """The text of the contract page of the feature that has the citation."""

        for contract in sorted(self._feature_api_contract_paths(feature, supplied)):  # type: ignore[attr-defined]
            text = supplied.get(contract) or self._optional_text(self._safe_path(contract, allow_missing=True))  # type: ignore[attr-defined]
            if text is None:
                continue
            frontmatter, body = bs._parse_markdown(text, contract)
            if contract_page_citation(frontmatter, body) == citation:
                return text
        return None

    @staticmethod
    def _d4_fix_apps(old_evidence: Any, new_evidence: Any, active: list[str]) -> set[str]:
        """The apps whose released authoritative Release row the proposal changes: the apps a bug fix reaches."""

        changed: set[str] = set()
        for app in active:
            previous = old_evidence.authoritative_release(app)
            current = new_evidence.authoritative_release(app)
            if previous is not None and previous.outcome == "released" and (current is None or tuple(c.strip() for c in current.cells) != tuple(c.strip() for c in previous.cells)):
                changed.add(app)
        return changed

    # -- the gates of a feature that releases ----------------------------------------------------------------------------

    def _d4_feature_gates(
        self,
        pages: Mapping[str, Any],
        named: list[ReleasedApp],
        relative: str,
        supplied: Mapping[str, str],
        bugs: list[BugPage],
        included: Mapping[str, set[str]],
    ) -> None:
        feature_id = pages["feature_id"]
        apps = [item.app for item in named]
        released_apps = [item.app for item in named if item.outcome == "released"]
        old_fm, new_fm = pages["old_fm"], pages["new_fm"]
        # Revalidation: nothing may be pending for the feature, and the apps are verified (CONTRACTS 2.4).
        pending, errors = parse_revalidation(old_fm.get("revalidation"))
        old_domains, domain_errors = parse_app_revalidation(old_fm.get("app-revalidation"))
        blocked_domains = [domain for domain in pending]
        blocked_apps = {app: [domain for domain in old_domains.get(app, []) if domain in BLOCKING_APP_DOMAINS] for app in apps}
        blocked_apps = {app: items for app, items in blocked_apps.items() if items}
        if errors or domain_errors or blocked_domains or blocked_apps:
            raise bs.BoardError(
                "revalidation_required",
                "Pending revalidation blocks the release: "
                + "; ".join(
                    part
                    for part in (
                        f"feature domains {_quoted(blocked_domains)}" if blocked_domains else "",
                        *(f"`{app}`: {', '.join(items)}" for app, items in blocked_apps.items()),
                        *errors,
                        *domain_errors,
                    )
                    if part
                )
                + ".",
                409,
                {"path": relative, "feature": blocked_domains, "apps": sorted(blocked_apps)},
            )
        new_domains, new_errors = parse_app_revalidation(new_fm.get("app-revalidation"))
        wanted: dict[str, list[str]] = {}
        for app, domains in old_domains.items():
            kept = [domain for domain in domains if app not in released_apps or domain != "release"]
            if kept:
                wanted[app] = kept
        if new_errors or new_domains != wanted:
            raise bs.BoardError(
                "revalidation_scope",
                "release-done clears only the `release` domain of the apps it releases in `app-revalidation`; every other entry stays as it is.",
                409,
                {"path": relative, "apps": apps},
            )
        # QA still holds (CONTRACTS 4.4): a release delivers what QA verified.
        stale = [row for row, _reason in stale_qa_rows(pages["criteria"], pages["new_evidence"], pages["old_history"], skip_apps=[app for app in pages["active"] if app not in apps])]
        gaps: list[Problem] = []
        for app in apps:
            gaps.extend(coverage_problems(app, pages["criteria"], pages["new_evidence"], pages["old_history"]))
        if gaps or stale:
            first = gaps[0].message if gaps else f"The QA row `{stale[0].key}` is stale."
            raise bs.BoardError(
                "qa_evidence_stale",
                f"QA no longer covers what is released: {first} Verify the app again with qa-verify and qa-pass, or return it.",
                409,
                {"path": relative, "apps": apps},
            )
        raise_first(bug_gate_problems(bugs, feature_id=feature_id, named=apps, evidence=pages["old_evidence"], code_blocks="open_bug_blocks_release"), relative)
        raise_first(bug_release_inclusion_problems(bugs, feature_id=feature_id, named=apps, included=included), relative)
        self._assert_contract_bindings({"id": feature_id, "path": relative}, supplied, tuple(apps))  # type: ignore[attr-defined]
        self._d3_questions(pages, owner="release")  # type: ignore[attr-defined]
        self._assert_minimum_status("release-done", relative, supplied[relative], old_fm, new_fm)  # type: ignore[attr-defined]

    def _d4_dependencies(self, supplied: Mapping[str, str], apps_by_feature: Mapping[str, set[str]]) -> None:
        """The requirement of a released app depends only on released features and apps, counting those the same proposal releases (CONTRACTS 8.1)."""

        if not apps_by_feature:
            return
        from prism_cli.wiki_lint import lint_wiki

        wanted = {normalize_feature_id(feature_id): set(apps) for feature_id, apps in apps_by_feature.items()}
        with tempfile.TemporaryDirectory(prefix="prism-board-release-") as directory:
            candidate = Path(directory)
            self._build_candidate_root(candidate, supplied, [])  # type: ignore[attr-defined]
            result = lint_wiki(candidate)
            for diagnostic in result.diagnostics:
                if diagnostic.code != "cross-app-dependency" or normalize_feature_id(diagnostic.feature_id or "") not in wanted:
                    continue
                page = parse_markdown_text(Path(diagnostic.path), Path(diagnostic.path).read_text(encoding="utf-8")) if Path(diagnostic.path).is_file() else None
                app = page.frontmatter.get("app") if page is not None else None
                if isinstance(app, str) and app not in wanted[normalize_feature_id(diagnostic.feature_id or "")]:
                    continue
                raise bs.BoardError(
                    "dependency_not_released",
                    f"{diagnostic.message} A feature or app is released after the features and apps it depends on, or in the same release.",
                    409,
                    {"feature_id": diagnostic.feature_id, "app": app},
                )

    # -- bugs (B14) ------------------------------------------------------------------------------------------------------

    def _d4_bug(
        self,
        relative: str,
        supplied: Mapping[str, str],
        before: Mapping[str, str | None],
        record_id: str,
        records: list[ReleaseRecord],
        kinds: Mapping[str, str],
        policy: Mapping[str, Any],
    ) -> dict[str, Any]:
        """A bug page in a release proposal: its Release rows for the apps the record ships and, when every app is released, `released` + `none` (B14)."""

        if before.get(relative) is None:
            raise bs.BoardError("bug_not_found", f"`{relative}` does not exist: release-done ships existing bugs and never creates one.", 409, {"path": relative})
        old, old_body = bs._parse_markdown(before[relative] or "", relative)
        new, new_body = bs._parse_markdown(supplied[relative], relative)
        wiki = self._wiki_path()  # type: ignore[attr-defined]
        bug_path = wiki / "bugs" / PurePosixPath(relative).name
        old_bug = BugPage(parse_markdown_text(bug_path, before[relative] or ""))
        new_bug = BugPage(parse_markdown_text(bug_path, supplied[relative]))
        if (old.get("status"), old.get("owner")) != ("verified", "release"):
            raise bs.BoardError(
                "unsupported_source_pair",
                f"Action `bug-release` runs on a bug that is `verified` + `release`; `{relative}` is `{old.get('status')}` + `{old.get('owner')}`.",
                409,
                {"path": relative, "action": "bug-release", "status": old.get("status")},
            )
        changed = {key for key in set(old) | set(new) if old.get(key) != new.get(key)}
        if changed - {"status", "owner"}:
            raise bs.BoardError(
                "bug_frontmatter_scope",
                f"Action `bug-release` may change only `status` and `owner` in `{relative}`; it also changes {_quoted(sorted(changed - {'status', 'owner'}))}.",
                409,
                {"path": relative, "fields": sorted(changed - {"status", "owner"}), "allowed": ["owner", "status"]},
            )
        self._assert_only_body_sections_changed(old_body, new_body, {"Release"}, "lifecycle_body_scope", "Action `bug-release` may change only the `## Release` section of the bug page.")  # type: ignore[attr-defined]
        old_rows, _old_problems = parse_release_rows(old_body)
        new_rows, new_problems = parse_release_rows(new_body)
        if new_problems:
            raise bs.BoardError(new_problems[0].code, f"The `## Release` table in `{relative}` is not valid: " + " ".join(item.message for item in new_problems[:4]), 409, {"path": relative})
        old_cells = {tuple(c.strip() for c in row.cells) for row in old_rows}
        changed_rows = [row for row in new_rows if tuple(c.strip() for c in row.cells) not in old_cells]
        bug_id = new_bug.bug_id
        applied: list[tuple[str, str, str, int, str, str]] = []
        for row in changed_rows:
            if row.app not in new_bug.apps:
                raise bs.BoardError("undeclared_app_row", f"The Release row of `{row.app}` in `{relative}` names an app the bug does not list.", 409, {"path": relative, "app": row.app})
            if not row.authoritative:
                raise bs.BoardError("release_row_invalid", f"A bug has no staging Release rows; the row of `{row.app}` in `{relative}` has no attempt.", 409, {"path": relative, "app": row.app})
            previous = next((item for item in old_rows if item.app == row.app and item.authoritative), None)
            if previous is not None and previous.outcome == "released":
                raise bs.BoardError("app_stage_mismatch", f"{bug_id} is already released for `{row.app}`; it ships once per app.", 409, {"path": relative, "app": row.app})
            expected_attempt = release_attempt_of(records, kinds, bug_id, row.app)
            if row.attempt != expected_attempt:
                raise bs.BoardError(
                    "release_attempt_mismatch",
                    f"The Release row of `{row.app}` in `{relative}` is attempt release-{row.attempt}; the attempt this release makes is release-{expected_attempt}.",
                    409,
                    {"path": relative, "app": row.app, "expected": f"release-{expected_attempt}"},
                )
            if row.outcome not in {"released", "failed"}:
                raise bs.BoardError("release_row_invalid", f"A release writes the Release row of `{row.app}` as `released` or `failed`, not `{row.outcome}`.", 409, {"path": relative, "app": row.app})
            target = target_of(policy, row.app)
            if target is None:
                raise bs.BoardError("delivery_target_missing", f"`{row.app}` has no delivery target: declare one under `delivery-targets` in SETTINGS.md.", 409, {"path": relative, "app": row.app})
            if row.target != target:
                raise bs.BoardError(
                    "release_target_mismatch",
                    f"The Release row of `{row.app}` in `{relative}` names `{row.target}`; its delivery target is `{target}`.",
                    409,
                    {"path": relative, "app": row.app, "expected": target},
                )
            linked = self._feature_facts(new_bug.feature)  # type: ignore[attr-defined]
            wanted = verification_artifact(old_bug, row.app, linked["evidence"] if linked is not None else None)
            if wanted is None or row.version != wanted:
                raise bs.BoardError(
                    "release_version_not_verified",
                    f"The Release row of `{row.app}` in `{relative}` names `{row.version}`; {bug_id} was verified on `{wanted}`. A release delivers the verified artifact.",
                    409,
                    {"path": relative, "app": row.app, "expected": wanted},
                )
            if record_id_of_cell(row.record) != record_id:
                raise bs.BoardError(
                    "release_row_invalid",
                    f"The Record cell of `{row.app}` in `{relative}` is `{row.record}`; it links the record of this release, `[{record_id}](../releases/{record_id}.md)`.",
                    409,
                    {"path": relative, "app": row.app},
                )
            applied.append((row.app, row.target, row.version, row.attempt or 0, row.outcome, row.basis))
        removed = [row for row in old_rows if tuple(c.strip() for c in row.cells) not in {tuple(c.strip() for c in item.cells) for item in new_rows}]
        for row in removed:
            if not (row.authoritative and row.outcome == "failed" and any(item.app == row.app for item in changed_rows)):
                raise bs.BoardError("release_row_invalid", f"`bug-release` never removes the Release row of `{row.app}` in `{relative}` unless it replaces a failed attempt.", 409, {"path": relative, "app": row.app})
        if not applied:
            raise bs.BoardError("release_apps_required", f"`{relative}` changes no Release row: a bug in a release proposal ships for the apps whose row it writes.", 409, {"path": relative})
        # B14: `released` + `none` when every app of the bug has a released row; otherwise it stays `verified`.
        final = {row.app: row for row in new_rows if row.authoritative}
        all_released = all(final.get(app) is not None and final[app].outcome == "released" for app in new_bug.apps)
        expected_pair = ("released", "none") if all_released else ("verified", "release")
        if (new.get("status"), new.get("owner")) != expected_pair:
            raise bs.BoardError(
                "invalid_transition_target",
                f"{bug_id} is `{expected_pair[0]}` + `{expected_pair[1]}` after this release"
                + (" (every app of the bug is released)." if all_released else " (an app of the bug is not released: a partial failure leaves the bug `verified`, retried through release-done)."),
                409,
                {"path": relative, "expected": list(expected_pair)},
            )
        return {"bug": new_bug, "apps": applied, "path": relative, "released": all_released}

    def _d4_bug_feature_link(
        self,
        bug: BugPage,
        app: str,
        outcome: str,
        version: str,
        record_id: str,
        supplied: Mapping[str, str],
        before: Mapping[str, str | None],
        released_named: Mapping[str, list[ReleasedApp]],
        fix_updates: Mapping[str, set[str]],
        feature_outputs: list[dict[str, Any]],
        disk_bugs: Mapping[str, BugPage],
    ) -> None:
        """A bug ships with its feature's app, or alone for a `feature: none` bug or an app that is already released (`bug_release_requires_feature`)."""

        feature_id = bug.feature
        if feature_id is None:
            return
        facts = self._feature_facts(feature_id)  # type: ignore[attr-defined]
        if facts is None:
            raise bs.BoardError("bug_feature_missing", f"{bug.bug_id} names {feature_id}, which is not a feature of this wiki.", 409, {"bug": bug.bug_id})
        active = active_scope(facts["apps"], self._model)  # type: ignore[attr-defined]
        stage = app_stages(active, facts["evidence"]).get(app) if status_rank_in_dev(facts["status"]) else "in-dev"
        in_release = any(item.app == app for item in released_named.get(facts["id"], []))
        if stage == "released":
            if outcome != "released":
                return
            if app not in fix_updates.get(facts["id"], set()):
                raise bs.BoardError(
                    "release_row_invalid",
                    f"{bug.bug_id} fixes `{app}` of {facts['id']}, which is already released: the proposal also carries `{facts['path']}` with the Release row of `{app}` "
                    f"naming `[{record_id}](../releases/{record_id}.md)` and the version `{version}`.",
                    409,
                    {"bug": bug.bug_id, "app": app, "path": facts["path"]},
                )
            for output in feature_outputs:
                if output["pages"]["feature_id"] == facts["id"]:
                    raise_first(
                        check_bug_fix_row(
                            feature_id=facts["id"],
                            app=app,
                            old=output["pages"]["old_evidence"],
                            new=output["pages"]["new_evidence"],
                            version=version,
                            record_id=record_id,
                        ),
                        output["pages"]["path"],
                    )
            return
        if not in_release:
            raise bs.BoardError(
                "bug_release_requires_feature",
                f"{bug.bug_id} is linked to {facts['id']}, whose `{app}` is {stage or 'not delivered'}, not released. A bug ships with its feature: add {facts['id']} to the proposal "
                f"with the Release row of `{app}` (it must be `ready-for-release`), or release the bug after the feature app is released.",
                409,
                {"bug": bug.bug_id, "feature": facts["id"], "app": app, "stage": stage},
            )

    # -- release-return-dev (F20) ----------------------------------------------------------------------------------------

    def _d4_release_return(
        self,
        record: Mapping[str, Any],
        supplied: Mapping[str, str],
        before: Mapping[str, str | None],
        feature: Mapping[str, Any],
    ) -> dict[str, Any]:
        path = record["path"]
        records, kinds, rows = record["records"], record["kinds"], record["rows"]
        if "retry-of" in record["frontmatter"]:
            raise bs.BoardError("release_record_invalid", f"`{path}`: a release that returns the feature to development retries nothing.", 409, {"path": path})
        self._d4_record_checks(record, KIND_RELEASE)
        pages = self._d3_pages(feature, supplied, before)  # type: ignore[attr-defined]
        relative = pages["path"]
        feature_id = pages["feature_id"]
        old_fm, new_fm = pages["old_fm"], pages["new_fm"]
        others = [item for item in supplied if item not in {path, relative} and not item.startswith(_LINKED_PREFIXES)]
        if others:
            raise bs.BoardError("lifecycle_write_scope", "`release-return-dev` writes the record, the feature page and the requirement and contract pages it lowers; no other page.", 409, {"paths": bs._names(others)})
        self._validate_lifecycle_write_scope("release-return-dev", relative, before[relative] or "", supplied[relative], old_fm, new_fm)  # type: ignore[attr-defined]
        self._require_action_available("release-return-dev")  # type: ignore[attr-defined]
        history = pages["new_history"]
        entry = history[-1]
        named = tuple(dict.fromkeys(entry.affected_apps))
        scope = pages["scope"]
        if not named or not set(named) <= set(scope):
            raise bs.BoardError("reopen_app_scope", "The Evidence history entry of a release-return-dev names the apps it returns under `- Affected apps:`, apps of the feature's scope.", 409, {"path": relative})
        for app in named:
            stage = pages["stages"].get(app)
            if stage != "ready-for-release":
                raise bs.BoardError(
                    "app_stage_mismatch",
                    f"release-return-dev names apps at `ready-for-release`, but `{app}` is {stage or 'not active'}.",
                    409,
                    {"path": relative, "app": app, "stage": stage},
                )
        policy = self._read_policy()  # type: ignore[attr-defined]
        delivered = {row.app: clean_cell(row.artifact) for row in pages["old_evidence"].delivery}
        expected: dict[tuple[str, str], tuple[str, str, int | None, str, str]] = {}
        by_key = {(row.item, row.app): row for row in rows}
        if sorted(by_key) != sorted((feature_id, app) for app in named):
            raise bs.BoardError(
                "release_record_mismatch",
                f"`{path}`: a release that returns {feature_id} to development records the failed delivery of the apps it returns ({_quoted(named)}) and nothing else.",
                409,
                {"path": path},
            )
        for app in named:
            row = by_key[(feature_id, app)]
            target = target_of(policy, app)
            if target is None:
                raise bs.BoardError("delivery_target_missing", f"`{app}` has no delivery target: declare one under `delivery-targets` in SETTINGS.md.", 409, {"path": path, "app": app})
            attempt = release_attempt_of(records, kinds, feature_id, app)
            if (row.target, row.version, row.attempt, row.outcome) != (target, delivered.get(app), attempt, "failed"):
                raise bs.BoardError(
                    "release_record_mismatch",
                    f"`{path}`: the failed delivery of `{app}` is recorded as `failed` at `{target}` with the verified artifact `{delivered.get(app)}` in attempt release-{attempt}.",
                    409,
                    {"path": path, "app": app},
                )
            gaps = coverage_problems(app, pages["criteria"], pages["old_evidence"], pages["old_history"])
            if gaps:
                raise bs.BoardError("qa_evidence_stale", f"QA no longer covers `{app}`: {gaps[0].message}", 409, {"path": relative, "app": app})
        bugs = self._bugs_with(supplied)  # type: ignore[attr-defined]
        raise_first(release_bug_blocking(bugs, feature_id=feature_id, named=list(named)), relative)
        self._require_no_retired_app_in_progress(feature_id, old_fm)  # type: ignore[attr-defined]
        # The archive, the Evidence history entry and the front matter are those of qa-fail (CONTRACTS 2.7).
        archive, participants = qa_fail_archive(pages["old_evidence"], named, pages["stages"])
        self._validate_evidence_history(  # type: ignore[attr-defined]
            "release-return-dev",
            before[relative] or "",
            supplied[relative],
            old_fm,
            relative=relative,
            expected_archive=archive,
            require_entry=True,
            related=(supplied, before),
        )
        if sorted(entry.participants) != participants:
            raise bs.BoardError(
                "history_participants_mismatch",
                f"Evidence history lists as participants the apps that lose their Release row through an archived integration row: {_quoted(participants) or 'none'}.",
                409,
                {"path": relative, "expected": participants},
            )
        tracks = [item for item in entry.fields.get("Affected tracks", "").strip().strip("[]").lower().replace(",", " ").split() if item]
        if tracks != ["none"]:
            raise bs.BoardError("impact_review_required", "A release-return-dev affects no design track: write `none` under `- Affected tracks:`.", 409, {"label": "Affected tracks"})
        known = {bug.bug_id.casefold() for bug in bugs}
        unknown = [name for name in entry.names("Linked bugs") if name.casefold() not in known]
        if unknown:
            raise bs.BoardError("linked_bug_invalid", f"Linked bugs names {_quoted(unknown)}, which no bug page defines.", 409, {"path": relative, "bugs": unknown})
        self._d3_related(pages, "release-return-dev", named, supplied, before)  # type: ignore[attr-defined]
        old_domains, _errors = parse_app_revalidation(old_fm.get("app-revalidation"))
        new_domains, new_errors = parse_app_revalidation(new_fm.get("app-revalidation"))
        additions: dict[str, list[str]] = {app: list(APP_REVALIDATION_DOMAINS) for app in named}
        for app in participants:
            additions[app] = merge_revalidation(additions.get(app, []), ["qa", "release"], APP_REVALIDATION_DOMAINS)
        if new_errors or new_domains != merged_app_revalidation(old_domains, additions):
            raise bs.BoardError(
                "revalidation_required",
                "release-return-dev writes `app-revalidation` exactly: each returned app gains `implementation`, `tests`, `qa` and `release`"
                + (f", and {_quoted(participants)} (they lose a Release row) gain `qa` and `release`" if participants else "")
                + "; every other entry stays as it is.",
                409,
                {"path": relative, "apps": list(named)},
            )
        self._d4_dependencies(supplied, {feature_id: set(named)})
        self._assert_minimum_status("release-return-dev", relative, supplied[relative], old_fm, new_fm)  # type: ignore[attr-defined]
        if (new_fm.get("status"), new_fm.get("owner")) != ("in-dev", "dev"):
            raise bs.BoardError("invalid_transition_target", "Action `release-return-dev` has a fixed registered destination: `in-dev` + `dev`.", 409, {"path": relative})
        snapshot_expected: dict[tuple[str, str], tuple[str, str | None]] = {}
        for app in named:
            delivery = pages["old_evidence"].delivery_row(app)
            cited = contract_cited_by(delivery.cells) if delivery is not None else None
            if cited is not None:
                snapshot_expected[(feature_id, app)] = (cited, self._d4_contract_text(feature, cited, supplied))
        snapshots, snapshot_parse = parse_snapshots(record["body"])
        raise_first(snapshot_problems(snapshots, snapshot_parse, expected=snapshot_expected, path=path), path)
        return self._d4_operation(
            "release-return-dev",
            feature_id,
            {"status": old_fm.get("status"), "owner": old_fm.get("owner")},
            {"status": new_fm.get("status"), "owner": new_fm.get("owner")},
            f"The release record {record['id']} records the failed delivery of {', '.join(named)}, and {feature_id} goes back to development.",
            checks=[],
        )

    # -- the reopen routes of a released feature (F23, F24, F25) ---------------------------------------------------------

    def _d4_validate_reopen(
        self,
        action: str,
        feature: Mapping[str, Any],
        supplied: Mapping[str, str],
        before: Mapping[str, str | None],
    ) -> dict[str, Any]:
        pages = self._d3_pages(feature, supplied, before)  # type: ignore[attr-defined]
        path = pages["path"]
        old_fm = pages["old_fm"]
        if old_fm.get("status") != "released":
            raise bs.BoardError("unsupported_source_pair", f"Action `{action}` reopens a feature that is `released`; {pages['feature_id']} is `{old_fm.get('status')}`.", 409, {"path": path})
        history = pages["new_history"]
        if len(history) <= len(pages["old_history"]):
            raise bs.BoardError(
                "history_entry_required",
                f"{action} appends one Evidence history entry headed `### {date.today().isoformat()} - {action}` that archives the evidence it removes.",
                409,
                {"path": path, "action": action},
            )
        entry = history[-1]
        scope = pages["scope"]
        evidence = pages["old_evidence"]
        if action == "reopen-dev":
            return self._d4_reopen_dev(pages, entry, supplied, before)
        # reopen-spec and reopen-design archive every row of every app, released rows included (CONTRACTS 2.7).
        self._validate_evidence_history(  # type: ignore[attr-defined]
            action,
            before[path] or "",
            supplied[path],
            old_fm,
            relative=path,
            expected_archive=every_row(evidence),
            require_entry=True,
            related=(supplied, before),
        )
        if sorted(entry.affected_apps) != sorted(scope):
            raise bs.BoardError("reopen_app_scope", f"{action} sends the whole feature back: `- Affected apps:` lists every app of the scope ({_quoted(scope)}).", 409, {"path": path})
        if entry.participants:
            raise bs.BoardError("history_participants_mismatch", f"{action} archives every row, so no app is listed as a participant; write `none`.", 409, {"path": path})
        if entry.reaffirmed_rows:
            raise bs.BoardError("delivery_evidence_not_reaffirmed", f"{action} archives all the evidence; it reaffirms none. Write `none` under `- Reaffirmed evidence:`.", 409, {"path": path})
        bugs = self._bugs_with(supplied)  # type: ignore[attr-defined]
        known = {bug.bug_id.casefold() for bug in bugs}
        unknown = [name for name in entry.names("Linked bugs") if name.casefold() not in known]
        if unknown:
            raise bs.BoardError("linked_bug_invalid", f"Linked bugs names {_quoted(unknown)}, which no bug page defines.", 409, {"path": path, "bugs": unknown})
        self._d3_related(pages, action, tuple(scope), supplied, before)  # type: ignore[attr-defined]
        self._d3_return_front_matter(action, pages, entry)  # type: ignore[attr-defined]
        return {"named": tuple(scope), "produces": [], "separation": []}

    def _d4_reopen_dev(self, pages: Mapping[str, Any], entry: Any, supplied: Mapping[str, str], before: Mapping[str, str | None]) -> dict[str, Any]:
        """`reopen-dev`: the affected apps lose every row and need all four domains again; the others keep their rows, quoted under Reaffirmed evidence."""

        path = pages["path"]
        old_fm, new_fm = pages["old_fm"], pages["new_fm"]
        evidence = pages["old_evidence"]
        scope = pages["scope"]
        named = tuple(dict.fromkeys(entry.affected_apps))
        if not named or not set(named) <= set(scope):
            raise bs.BoardError("reopen_app_scope", "The Evidence history entry of a reopen-dev names the apps it reopens under `- Affected apps:`, apps of the feature's scope.", 409, {"path": path})
        wanted = set(named)
        archive: list[tuple[str, tuple[str, ...]]] = []
        archive.extend(("Delivery evidence", row.cells) for row in evidence.delivery if row.app in wanted)
        archive.extend(("QA verification", row.cells) for row in evidence.qa if wanted & set(row.apps))
        archive.extend(("Release", row.cells) for row in evidence.release if row.app in wanted)
        self._validate_evidence_history(  # type: ignore[attr-defined]
            "reopen-dev",
            before[path] or "",
            supplied[path],
            old_fm,
            relative=path,
            expected_archive=archive,
            require_entry=True,
            reaffirmable=True,
            related=(supplied, before),
        )
        remaining = [row for row in every_row(evidence) if row not in archive]
        reaffirmed = {_row_key(section, cells) for section, cells in entry.reaffirmed_rows}
        for section, cells in remaining:
            if _row_key(section, cells) not in reaffirmed:
                raise bs.BoardError(
                    "delivery_evidence_not_reaffirmed",
                    "reopen-dev keeps the rows of the apps it does not reopen only when it quotes them under `- Reaffirmed evidence:`, each verbatim with its section name. "
                    f"Missing: {section} | {' | '.join(cells)}",
                    409,
                    {"path": path, "label": "Reaffirmed evidence"},
                )
        if reaffirmed != {_row_key(section, cells) for section, cells in remaining}:
            raise bs.BoardError("delivery_evidence_not_reaffirmed", "Reaffirmed evidence quotes exactly the rows that stay active, and no other row.", 409, {"path": path, "label": "Reaffirmed evidence"})
        if entry.participants:
            raise bs.BoardError("history_participants_mismatch", "reopen-dev archives whole apps; write `none` under Participants.", 409, {"path": path})
        tracks = [item for item in entry.fields.get("Affected tracks", "").strip().strip("[]").lower().replace(",", " ").split() if item]
        if tracks != ["none"]:
            raise bs.BoardError("impact_review_required", "A reopen-dev affects no design track: write `none` under `- Affected tracks:`.", 409, {"label": "Affected tracks"})
        bugs = self._bugs_with(supplied)  # type: ignore[attr-defined]
        known = {bug.bug_id.casefold() for bug in bugs}
        unknown = [name for name in entry.names("Linked bugs") if name.casefold() not in known]
        if unknown:
            raise bs.BoardError("linked_bug_invalid", f"Linked bugs names {_quoted(unknown)}, which no bug page defines.", 409, {"path": path, "bugs": unknown})
        self._d3_related(pages, "reopen-dev", named, supplied, before)  # type: ignore[attr-defined]
        if new_fm.get("revalidation") != old_fm.get("revalidation"):
            raise bs.BoardError("revalidation_scope", "reopen-dev changes no feature-level `revalidation`; the apps it reopens get their domains in `app-revalidation`.", 409, {"path": path})
        old_domains, _errors = parse_app_revalidation(old_fm.get("app-revalidation"))
        new_domains, new_errors = parse_app_revalidation(new_fm.get("app-revalidation"))
        additions = {app: list(APP_REVALIDATION_DOMAINS) for app in named}
        if new_errors or new_domains != merged_app_revalidation(old_domains, additions):
            raise bs.BoardError(
                "revalidation_required",
                f"reopen-dev gives each reopened app ({_quoted(named)}) all four `app-revalidation` domains ({_quoted(APP_REVALIDATION_DOMAINS)}), merged with those still pending; every other entry stays.",
                409,
                {"path": path, "apps": list(named)},
            )
        if "design-tracks" in old_fm or "design-tracks" in new_fm:
            if old_fm.get("design-tracks") != new_fm.get("design-tracks") or old_fm.get("design-reaffirm") != new_fm.get("design-reaffirm"):
                raise bs.BoardError("track_scope", "reopen-dev leaves the design tracks as they are.", 409, {"path": path})
        self._assert_minimum_status("reopen-dev", path, supplied[path], old_fm, new_fm)  # type: ignore[attr-defined]
        return {"named": named, "produces": [], "separation": []}


def _row_key(section: str, cells: Any) -> str:
    return " ".join((section + " | " + " | ".join(cells)).lower().split())


def status_rank_in_dev(status: Any) -> bool:
    return status_rank(status) >= status_rank("in-dev")


def _without_apps(evidence: Any, apps: set[str]) -> Any:
    """The evidence with the Release rows of `apps` as they were before: those rows are judged by the bug-fix rule, not by the release rule."""

    from dataclasses import replace

    return replace(evidence, release=tuple(row for row in evidence.release if row.app not in apps))
