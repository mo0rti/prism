"""The QA half of the board service: `qa-verify`, `qa-pass`, `qa-fail` and the routes back from QA (CONTRACTS 2.3 to 2.7).

`QaActionsMixin` is mixed into `BoardService`. Each `_d3_*` method validates one action against the page before the write
(`before`) and the page the proposal carries (`supplied`), raises the contract's error code for the first rule that fails, and
returns what the preview needs: the apps the action names, the evidence rows it produces and the rows a verification must
be separated from. The rules themselves live in `prism_cli/qa_rules.py`, which the read-only evaluator shares.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any, Mapping

from prism_cli.board_bugs import bs, is_bug_path
from prism_cli.qa_rules import (
    QA_FAIL_STAGES,
    Problem,
    bug_gate_problems,
    check_qa_pass_release_rows,
    check_qa_rows,
    coverage_problems,
    every_row,
    merged_app_revalidation,
    qa_fail_archive,
    qa_fail_support,
    qa_row_changes,
    release_attempt_for,
)
from prism_cli.wiki_model import (
    APP_REVALIDATION_DOMAINS,
    FEATURE_REVALIDATION_DOMAINS,
    active_scope,
    app_stage,
    app_stages,
    evidence_generation,
    merge_revalidation,
    parse_app_revalidation,
    parse_criteria,
    parse_evidence_history,
    parse_open_question_rows,
    parse_revalidation,
    read_feature_evidence,
    row_digest,
)

D3_ACTIONS = frozenset({"qa-verify", "qa-pass", "qa-fail", "qa-return-spec", "qa-return-design"})
D3_QA_ACTIONS = frozenset({"qa-verify", "qa-pass"})
D3_RETURN_ACTIONS = frozenset({"qa-return-spec", "qa-return-design"})


def _quoted(values: Any) -> str:
    return ", ".join(f"`{value}`" for value in values)


def raise_first(problems: list[Problem], path: str) -> None:
    """Raise the first refusal of a rule check as a board error."""

    if problems:
        first = problems[0]
        extra = f" ({len(problems) - 1} more: {', '.join(item.code for item in problems[1:4])})" if len(problems) > 1 else ""
        raise bs.BoardError(first.code, first.message + extra, 409, {"path": path, **dict(first.details)})


class QaActionsMixin:
    """The QA actions of `BoardService`."""

    # -- common reading ---------------------------------------------------------------------------------------------------

    def _d3_pages(self, target_feature: Mapping[str, Any], supplied: Mapping[str, str], before: Mapping[str, str | None]) -> dict[str, Any]:
        """The page before and after the write, with the rows, criteria and history both carry."""

        path = target_feature["path"]
        old_fm, old_body = bs._parse_markdown(before[path] or "", path)
        new_fm, new_body = bs._parse_markdown(supplied[path], path)
        feature_id = str(new_fm["id"])
        scope = bs._scope_of(new_fm) or []
        active = active_scope(scope, self._model)  # type: ignore[attr-defined]
        old_evidence = read_feature_evidence(old_body)
        return {
            "path": path,
            "feature_id": feature_id,
            "old_fm": old_fm,
            "new_fm": new_fm,
            "old_body": old_body,
            "new_body": new_body,
            "scope": scope,
            "active": active,
            "old_evidence": old_evidence,
            "new_evidence": read_feature_evidence(new_body),
            "criteria": parse_criteria(new_body, feature_id),
            "old_history": parse_evidence_history(old_body),
            "new_history": parse_evidence_history(new_body),
            "stages": app_stages(active, old_evidence),
        }

    def _d3_validate(
        self,
        action: str,
        target_feature: Mapping[str, Any],
        supplied: Mapping[str, str],
        before: Mapping[str, str | None],
    ) -> dict[str, Any]:
        """Validate the D3 action `action` and return `named`, `produces` and `separation`."""

        pages = self._d3_pages(target_feature, supplied, before)
        self._d3_new_bug_pages(action, pages, supplied, before)
        if action == "qa-verify":
            return self._d3_qa_verify(pages, supplied, before)
        if action == "qa-pass":
            return self._d3_qa_pass(pages, supplied, before)
        if action == "qa-fail":
            return self._d3_qa_fail(pages, supplied, before)
        return self._d3_return(action, pages, supplied, before)

    # -- bugs created by a QA action (B1) --------------------------------------------------------------------------------

    def _d3_new_bug_pages(self, action: str, pages: Mapping[str, Any], supplied: Mapping[str, str], before: Mapping[str, str | None]) -> None:
        bug_paths = [path for path in supplied if is_bug_path(path)]
        if action in D3_RETURN_ACTIONS and bug_paths:
            raise bs.BoardError("lifecycle_write_scope", f"Action `{action}` writes no bug page.", 409, {"paths": bs._names(bug_paths)})
        for path in bug_paths:
            if before.get(path) is not None:
                raise bs.BoardError(
                    "lifecycle_write_scope",
                    f"Action `{action}` creates bug pages and never rewrites one; `{path}` already exists (use bug-update).",
                    409,
                    {"path": path},
                )
            frontmatter = bs._parse_markdown(supplied[path], path)[0]
            feature = frontmatter.get("feature")
            if feature not in {pages["feature_id"], "none"}:
                raise bs.BoardError(
                    "bug_creation_invalid",
                    f"A bug found while testing {pages['feature_id']} is linked to {pages['feature_id']} or to no feature (`feature: none`); `{path}` names `{feature}`.",
                    409,
                    {"path": path},
                )

    # -- open questions (qa rows) ------------------------------------------------------------------------------------------

    def _d3_questions(self, pages: Mapping[str, Any]) -> None:
        """A QA action may resolve the questions the `qa` owner holds and changes nothing else in the table."""

        relative = pages["path"]
        old_rows, old_errors = parse_open_question_rows(pages["old_body"])
        new_rows, new_errors = parse_open_question_rows(pages["new_body"])
        if old_errors or new_errors:
            raise bs.BoardError("invalid_open_questions", "; ".join(old_errors + new_errors), 409)
        new_by_number = {row["number"]: row for row in new_rows}
        if len(new_by_number) != len(new_rows) or {row["number"] for row in new_rows} - {row["number"] for row in old_rows}:
            raise bs.BoardError("lifecycle_body_scope", "A QA action resolves the open questions of the `qa` owner; it adds no question.", 409, {"path": relative})
        for row in old_rows:
            updated = new_by_number.get(row["number"])
            if updated is None or updated["question"] != row["question"] or updated["owner"] != row["owner"]:
                raise bs.BoardError("question_deleted_or_changed", f"Question {row['number']} on `{relative}` must be preserved with the same text and owner.", 409)
            if updated["status"] == row["status"]:
                continue
            if row["status"] != "open":
                raise bs.BoardError("question_status_change", f"Previously resolved question {row['number']} must be preserved unchanged.", 409)
            if row["owner"] != "qa":
                raise bs.BoardError("question_owner_mismatch", f"A QA action resolves only `qa`-owned questions; question {row['number']} belongs to `{row['owner']}`.", 409)
            if not updated["status"].startswith("resolved:") or not updated["status"][len("resolved:"):].strip():
                raise bs.BoardError("answer_required", f"Question {row['number']} needs a substantive resolved answer.", 409)

    # -- qa-verify (F12) ---------------------------------------------------------------------------------------------------

    def _d3_rows(self, pages: Mapping[str, Any], supplied: Mapping[str, str]) -> list:
        """The refusals for the QA rows a proposal writes, with the bugs it creates counted."""

        path = pages["path"]
        problems = check_qa_rows(
            old=pages["old_evidence"],
            new=pages["new_evidence"],
            criteria=pages["criteria"],
            history=pages["old_history"],
            scope=pages["scope"],
            active=pages["active"],
            policy=self._read_policy(),  # type: ignore[attr-defined]
        )
        raise_first(problems, path)
        return qa_row_changes(pages["old_evidence"].qa, pages["new_evidence"].qa)[0]

    def _d3_qa_verify(self, pages: Mapping[str, Any], supplied: Mapping[str, str], before: Mapping[str, str | None]) -> dict[str, Any]:
        path = pages["path"]
        added = self._d3_rows(pages, supplied)
        if not added:
            raise bs.BoardError(
                "qa_evidence_required",
                f"qa-verify adds QA verification: the proposed `{path}` has no new or replaced row in its `## QA verification` table. "
                "Add one row per app or integration you verified, in the column order `| Row | Criteria | Method | Artifact | Environment | Attempt | Result | Evidence | Basis |`.",
                409,
                {"path": path, "table_columns": ["Row", "Criteria", "Method", "Artifact", "Environment", "Attempt", "Result", "Evidence", "Basis"]},
            )
        self._d3_questions(pages)
        named = tuple(sorted({app for row in added for app in row.apps}))
        return {"named": named, "produces": [], "separation": []}

    # -- qa-pass (F13, F14) ------------------------------------------------------------------------------------------------

    def _d3_qa_pass(self, pages: Mapping[str, Any], supplied: Mapping[str, str], before: Mapping[str, str | None]) -> dict[str, Any]:
        path = pages["path"]
        self._d3_rows(pages, supplied)
        policy = self._read_policy()  # type: ignore[attr-defined]
        wiki_root = self._wiki_path()  # type: ignore[attr-defined]
        named, problems = check_qa_pass_release_rows(
            old=pages["old_evidence"],
            new=pages["new_evidence"],
            stages=pages["stages"],
            active=pages["active"],
            policy=policy,
            attempt_of=lambda app: release_attempt_for(wiki_root, pages["feature_id"], app),
        )
        raise_first(problems, path)
        if not named:
            raise bs.BoardError(
                "qa_pass_apps_required",
                f"qa-pass names the apps it passes by adding a `pending` Release row for each: `| <app> | — | <delivered artifact> | release-<n> | pending | — | — |`. "
                f"The proposed `{path}` adds none.",
                409,
                {"path": path},
            )
        gaps: list[Problem] = []
        for app in named:
            gaps.extend(coverage_problems(app, pages["criteria"], pages["new_evidence"], pages["old_history"]))
        raise_first(gaps, path)
        bugs = self._bugs_with(supplied)  # type: ignore[attr-defined]
        raise_first(bug_gate_problems(bugs, feature_id=pages["feature_id"], named=named, evidence=pages["new_evidence"]), path)
        self._d3_questions(pages)
        old_domains, _errors = parse_app_revalidation(pages["old_fm"].get("app-revalidation"))
        new_domains, new_errors = parse_app_revalidation(pages["new_fm"].get("app-revalidation"))
        expected: dict[str, list[str]] = {}
        for app, domains in old_domains.items():
            kept = [domain for domain in domains if app not in named or domain != "qa"]
            if kept:
                expected[app] = kept
        if new_errors or new_domains != expected:
            raise bs.BoardError(
                "revalidation_scope",
                "qa-pass clears only the `qa` domain of the apps it passes in `app-revalidation`; every other entry stays as it is.",
                409,
                {"path": path, "apps": list(named)},
            )
        history = pages["old_history"]
        delivery = pages["old_evidence"]
        subjects = []
        for app in named:
            row = delivery.delivery_row(app)
            if row is not None:
                subjects.append(
                    {
                        "kind": "delivery",
                        "item_id": pages["feature_id"],
                        "app": app,
                        "generation": evidence_generation(history, "Delivery evidence", app),
                        "row_digest": row_digest(row.cells),
                    }
                )
        return {"named": named, "produces": [], "separation": subjects}

    # -- qa-fail (F15) -----------------------------------------------------------------------------------------------------

    def _d3_expected_pages(self, pages: Mapping[str, Any], action: str, named: tuple[str, ...], supplied: Mapping[str, str]) -> dict[str, str]:
        """The linked pages a write that sends apps back must change, with the status each takes (CONTRACTS 2.5, 2.7).

        A requirement page of a returned app that is `done` becomes `in-progress`; an API contract that is `implemented`
        becomes `agreed`, and on a route to `specified` every contract that is not a draft becomes `draft`.
        """

        feature_id = pages["feature_id"]
        expected: dict[str, str] = {}
        for requirement in sorted(self._wiki_path().glob("app-requirements/*.md")):  # type: ignore[attr-defined]
            if requirement.name.startswith("_"):
                continue
            relative = requirement.relative_to(self.root).as_posix()  # type: ignore[attr-defined]
            frontmatter = bs._parse_markdown(self._read_text(requirement), relative)[0]  # type: ignore[attr-defined]
            if str(frontmatter.get("feature-id", "")).casefold() == feature_id.casefold() and frontmatter.get("app") in named and frontmatter.get("status") == "done":
                expected[relative] = "in-progress"
        for contract in sorted(self._feature_api_contract_paths({"id": feature_id, "path": pages["path"]}, supplied)):  # type: ignore[attr-defined]
            text = self._optional_text(self._safe_path(contract, allow_missing=True))  # type: ignore[attr-defined]
            if text is None:
                continue
            status = bs._parse_markdown(text, contract)[0].get("status")
            if action == "qa-return-spec" and status in {"agreed", "implemented"}:
                expected[contract] = "draft"
            elif status == "implemented":
                expected[contract] = "agreed"
        return expected

    def _d3_related(self, pages: Mapping[str, Any], action: str, named: tuple[str, ...], supplied: Mapping[str, str], before: Mapping[str, str | None]) -> None:
        """The requirement and API pages the write changes are exactly the expected ones, and only their `status` moves."""

        feature_id = pages["feature_id"]
        related = {path for path in supplied if path.startswith(("knowledge/wiki/app-requirements/", "knowledge/wiki/api-contracts/"))}
        expected = self._d3_expected_pages(pages, action, named, supplied)
        if related != set(expected):
            missing = sorted(set(expected) - related)
            unexpected = sorted(related - set(expected))
            raise bs.BoardError(
                "lifecycle_write_scope",
                f"`{action}` changes the status of exactly these linked pages: "
                + "; ".join(f"`{path}` to `{status}`" for path, status in sorted(expected.items()))
                + (f". Missing from the proposal: {_quoted(missing)}" if missing else "")
                + (f". Not changed by this action: {_quoted(unexpected)}" if unexpected else "")
                + ".",
                409,
                {"paths": bs._names(related ^ set(expected))},
            )
        for relative in sorted(related):
            original = before.get(relative)
            if original is None:
                raise bs.BoardError("linked_page_not_found", f"Action `{action}` can update only existing linked artifact `{relative}`.", 409)
            old_fm, old_body = bs._parse_markdown(original, relative)
            new_fm, new_body = bs._parse_markdown(supplied[relative], relative)
            if str(new_fm.get("feature-id", "")).casefold() != feature_id.casefold() and not relative.startswith("knowledge/wiki/api-contracts/"):
                raise bs.BoardError("feature_context_mismatch", f"Linked artifact `{relative}` does not belong to {feature_id}.", 409)
            if new_fm.get("status") != expected[relative]:
                raise bs.BoardError(
                    "reopen_invalidation_mismatch",
                    f"`{action}` sets the status of `{relative}` to `{expected[relative]}`; it is `{new_fm.get('status')}`.",
                    409,
                    {"path": relative, "from": old_fm.get("status"), "to": expected[relative]},
                )
            if {k: v for k, v in old_fm.items() if k != "status"} != {k: v for k, v in new_fm.items() if k != "status"} or old_body != new_body:
                raise bs.BoardError(
                    "linked_page_scope",
                    f"`{action}` may change only the `status` of a linked requirement or API contract, but `{relative}` also changes its text or other fields. Restore everything except `status` to the current text.",
                    409,
                    {"path": relative},
                )

    def _d3_qa_fail(self, pages: Mapping[str, Any], supplied: Mapping[str, str], before: Mapping[str, str | None]) -> dict[str, Any]:
        path = pages["path"]
        history = pages["new_history"]
        if len(history) <= len(pages["old_history"]):
            raise bs.BoardError(
                "history_entry_required",
                f"qa-fail appends one Evidence history entry headed `### {bs.date.today().isoformat()} - qa-fail` that archives the rows it removes.",
                409,
                {"path": path, "action": "qa-fail"},
            )
        entry = history[-1]
        named = tuple(dict.fromkeys(entry.affected_apps))
        scope = pages["scope"]
        if not named or not set(named) <= set(scope):
            raise bs.BoardError("reopen_app_scope", "The Evidence history entry of a qa-fail names the apps it fails under `- Affected apps:`, apps of the feature's scope.", 409, {"path": path})
        for app in named:
            stage = pages["stages"].get(app)
            if stage not in QA_FAIL_STAGES:
                raise bs.BoardError(
                    "app_stage_mismatch",
                    f"qa-fail names apps at `ready-for-qa`, `in-qa` or `ready-for-release`, but `{app}` is {stage or 'not active'}"
                    + (" (a shipped app changes through a bug fix or a reopen)." if stage == "released" else "."),
                    409,
                    {"path": path, "app": app, "stage": stage},
                )
        archive, participants = qa_fail_archive(pages["old_evidence"], named, pages["stages"])
        self._validate_evidence_history(  # type: ignore[attr-defined]
            "qa-fail",
            before[path] or "",
            supplied[path],
            pages["old_fm"],
            relative=path,
            expected_archive=archive,
            require_entry=True,
            related=(supplied, before),
        )
        if sorted(entry.participants) != participants:
            raise bs.BoardError(
                "history_participants_mismatch",
                f"Evidence history lists as participants the apps that lose their Release row through an archived integration row: {_quoted(participants) or 'none'}.",
                409,
                {"path": path, "expected": participants},
            )
        tracks = [item for item in entry.fields.get("Affected tracks", "").strip().strip("[]").lower().replace(",", " ").split() if item]
        if tracks != ["none"]:
            raise bs.BoardError("impact_review_required", "A qa-fail affects no design track: write `none` under `- Affected tracks:`.", 409, {"label": "Affected tracks"})
        bugs = self._bugs_with(supplied)  # type: ignore[attr-defined]
        known = {bug.bug_id.casefold() for bug in bugs}
        linked = entry.names("Linked bugs")
        unknown = [name for name in linked if name.casefold() not in known]
        if unknown:
            raise bs.BoardError("linked_bug_invalid", f"Linked bugs names {_quoted(unknown)}, which no bug page defines.", 409, {"path": path, "bugs": unknown})
        raise_first(
            qa_fail_support(
                named=named,
                evidence=pages["old_evidence"],
                history=pages["old_history"],
                bugs=bugs,
                linked=linked,
                feature_id=pages["feature_id"],
            ),
            path,
        )
        self._d3_related(pages, "qa-fail", named, supplied, before)
        # Per-app revalidation: each failed app re-verifies everything; a participant that loses its Release row re-verifies QA and release.
        old_domains, _errors = parse_app_revalidation(pages["old_fm"].get("app-revalidation"))
        new_domains, new_errors = parse_app_revalidation(pages["new_fm"].get("app-revalidation"))
        additions: dict[str, list[str]] = {app: list(APP_REVALIDATION_DOMAINS) for app in named}
        for app in participants:
            additions[app] = merge_revalidation(additions.get(app, []), ["qa", "release"], APP_REVALIDATION_DOMAINS)
        expected = merged_app_revalidation(old_domains, additions)
        if new_errors or new_domains != expected:
            raise bs.BoardError(
                "revalidation_required",
                "qa-fail writes `app-revalidation` exactly: each failed app gains `implementation`, `tests`, `qa` and `release`"
                + (f", and {_quoted(participants)} (they lose a Release row) gain `qa` and `release`" if participants else "")
                + "; every other entry stays as it is.",
                409,
                {"path": path, "apps": list(named)},
            )
        return {"named": named, "produces": [], "separation": []}

    # -- the routes back from QA (F16, F17) -------------------------------------------------------------------------------

    def _d3_return(self, action: str, pages: Mapping[str, Any], supplied: Mapping[str, str], before: Mapping[str, str | None]) -> dict[str, Any]:
        path = pages["path"]
        old_fm, new_fm = pages["old_fm"], pages["new_fm"]
        evidence = pages["old_evidence"]
        scope = pages["scope"]
        stages_all = {app: app_stage(app, evidence) for app in scope}
        released = [app for app, stage in stages_all.items() if stage == "released"]
        if released:
            raise bs.BoardError(
                "partial_release_requires_new_feature",
                f"{pages['feature_id']} has released app(s) {_quoted(released)}. A changed requirement or contract goes in a new feature, and an implementation defect in a bug; "
                "this feature cannot go back to specification or design.",
                409,
                {"path": path, "apps": released},
            )
        if old_fm.get("status") == "in-dev" and not any(stage in QA_FAIL_STAGES for app, stage in pages["stages"].items()):
            raise bs.BoardError(
                "app_stage_mismatch",
                f"{pages['feature_id']} is in development and no app has reached QA, so it returns with dev-return-* rather than {action}.",
                409,
                {"path": path},
            )
        history = pages["new_history"]
        if len(history) <= len(pages["old_history"]):
            raise bs.BoardError(
                "history_entry_required",
                f"{action} appends one Evidence history entry headed `### {bs.date.today().isoformat()} - {action}` that archives every evidence row.",
                409,
                {"path": path, "action": action},
            )
        entry = history[-1]
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
        bugs = self._bugs_with(supplied)  # type: ignore[attr-defined]
        known = {bug.bug_id.casefold() for bug in bugs}
        unknown = [name for name in entry.names("Linked bugs") if name.casefold() not in known]
        if unknown:
            raise bs.BoardError("linked_bug_invalid", f"Linked bugs names {_quoted(unknown)}, which no bug page defines.", 409, {"path": path, "bugs": unknown})
        self._d3_related(pages, action, tuple(scope), supplied, before)
        self._d3_return_front_matter(action, pages, entry)
        return {"named": tuple(scope), "produces": [], "separation": []}

    def _d3_return_front_matter(self, action: str, pages: Mapping[str, Any], entry: Any) -> None:
        """`revalidation`, `app-revalidation`, `design-tracks` and `design-reaffirm` after a return (CONTRACTS 2.6, 3.1, 3.2)."""

        path = pages["path"]
        old_fm, new_fm = pages["old_fm"], pages["new_fm"]
        added = FEATURE_REVALIDATION_DOMAINS if action == "qa-return-spec" else FEATURE_REVALIDATION_DOMAINS[1:]
        old_pending, errors = parse_revalidation(old_fm.get("revalidation"))
        if errors:
            raise bs.BoardError("invalid_revalidation", "; ".join(errors), 409)
        expected = merge_revalidation(old_pending, added, FEATURE_REVALIDATION_DOMAINS)
        if new_fm.get("revalidation") != expected:
            raise bs.BoardError(
                "revalidation_required",
                f"{action} writes `revalidation: [{', '.join(expected)}]`: the domains it sets, in canonical order, merged with those still pending.",
                409,
                {"path": path},
            )
        old_apps, _errors = parse_app_revalidation(old_fm.get("app-revalidation"))
        new_apps, new_errors = parse_app_revalidation(new_fm.get("app-revalidation"))
        wanted = merged_app_revalidation(old_apps, {app: list(APP_REVALIDATION_DOMAINS) for app in pages["scope"]})
        if new_errors or new_apps != wanted:
            raise bs.BoardError(
                "revalidation_required",
                f"{action} gives every app all four `app-revalidation` domains (`implementation`, `tests`, `qa`, `release`), merged with those still pending.",
                409,
                {"path": path},
            )
        # The design tracks follow the one track model of the board (`DesignTracks`, `parse_design_tracks`): the same rule resets
        # them after a return from development and after a return from QA.
        self._validate_return_tracks(action, path, old_fm, new_fm, pages["scope"], entry)  # type: ignore[attr-defined]
