"""The bug half of the board service: the bug page validator and `bug-update` (CONTRACTS 2.8, 6.2).

`BugActionsMixin` is mixed into `BoardService`. It reads the service's helpers (`_read_text`, `_safe_path`, `_read_policy`,
`_model`, `_app_ids`) and the module-level helpers of `board_service` through `bs`, which resolves them when a method runs,
because `board_service` imports this module before it defines them.

A `bug-update` proposal changes one existing bug page. The action is read from the change (the status step, or the field
that moved), each action may change only the front matter keys and sections of its row (`bug_frontmatter_scope`), and the
prerequisites of the row are checked against the linked feature and the other bugs on disk.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping

from prism_cli.qa_rules import environments_of
from prism_cli.wiki_bugs import (
    BUG_FILE_PATTERN,
    BUG_FRONTMATTER_FIELDS,
    BUG_ID_PATTERN,
    BUG_OWNER_BY_STATUS,
    BUG_REQUIRED_FIELDS,
    BUG_SCOPE_FIELDS,
    BUG_SECTIONS,
    BUG_SEVERITIES,
    BUG_STATUS_ORDER,
    CLOSE_DISPOSITIONS,
    FEATURE_ID_PATTERN,
    BugPage,
    bugs_by_id,
    duplicate_target_problem,
    feature_cites_bug,
    parse_fix_rows,
    parse_verification_rows,
    read_bug_pages,
    verification_artifact,
)
from prism_cli.wiki_model import (
    _ENVIRONMENT_TOKEN,
    HISTORY_HEADING,
    active_scope,
    app_stages,
    bug_qa_attempt,
    evidence_generation,
    normalize_feature_id,
    parse_evidence_history,
    parse_markdown_text,
    read_feature_evidence,
    read_feature_pages,
    row_digest,
    section_text,
    status_rank,
)


class _BoardServiceModule:
    """The `board_service` module, imported on first use (it imports this module while it loads)."""

    def __getattr__(self, name: str) -> Any:
        from prism_cli import board_service

        return getattr(board_service, name)


bs = _BoardServiceModule()

# The front matter keys each bug action may change (CONTRACTS 2.8). `bug-close` adds the key of its disposition.
BUG_ACTION_KEYS: dict[str, frozenset[str]] = {
    "bug-triage": frozenset({"severity", "blocking"}),
    "bug-scope": frozenset(BUG_SCOPE_FIELDS) | {"status", "owner"},
    "bug-start": frozenset({"status", "owner"}),
    "bug-fixed": frozenset({"status", "owner"}),
    "bug-verify": frozenset({"status", "owner"}),
    "bug-reverify": frozenset(),
    "bug-reject": frozenset({"status", "owner"}),
    "bug-close": frozenset({"status", "owner", "close-reason"}),
    "bug-defer": frozenset({"deferred-reason"}),
    "bug-reopen": frozenset({"status", "owner", "close-reason"}),
}
BUG_ACTION_SECTIONS: dict[str, frozenset[str]] = {
    "bug-triage": frozenset(),
    "bug-scope": frozenset({"Fix", "Verification", "Evidence history"}),
    "bug-start": frozenset(),
    "bug-fixed": frozenset({"Fix"}),
    "bug-verify": frozenset({"Verification"}),
    "bug-reverify": frozenset({"Verification", "Evidence history"}),
    "bug-reject": frozenset({"Fix", "Verification", "Evidence history"}),
    "bug-close": frozenset(),
    "bug-defer": frozenset(),
    "bug-reopen": frozenset({"Fix", "Verification", "Release", "Evidence history"}),
}
_CLOSE_KEYS = {"wont-fix": frozenset(), "duplicate": frozenset({"duplicate-of"}), "promoted": frozenset({"promoted-to"})}
BUG_DIRECTORY_PREFIX = "knowledge/wiki/bugs/"
_EMPTY_LINE = re.compile(r"^\s*(?:<!--.*?-->\s*)?$")


def is_bug_path(relative: str) -> bool:
    return relative.startswith(BUG_DIRECTORY_PREFIX)


def _quoted(values: Iterable[str]) -> str:
    return ", ".join(f"`{value}`" for value in values)


def _blank(text: str) -> bool:
    """Whether a section holds no content: only whitespace and HTML comments."""

    return not re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL).strip()


class BugActionsMixin:
    """Bug page validation and `bug-update` for `BoardService`."""

    # -- reading ---------------------------------------------------------------------------------------------------------

    def _wiki_path(self) -> Path:
        return self.root / "knowledge" / "wiki"  # type: ignore[attr-defined]

    def _disk_bugs(self) -> list[BugPage]:
        return read_bug_pages(self._wiki_path())

    def _bugs_with(self, supplied: Mapping[str, str]) -> list[BugPage]:
        """The bug pages as they would be once the proposal applies: the pages on disk, the proposal's pages in their place."""

        wiki = self._wiki_path()
        pages: dict[str, BugPage] = {}
        for bug in self._disk_bugs():
            pages[bug.page.path.name] = bug
        for relative, content in supplied.items():
            if is_bug_path(relative):
                path = wiki / "bugs" / PurePosixPath(relative).name
                pages[path.name] = BugPage(parse_markdown_text(path, content))
        return [pages[name] for name in sorted(pages)]

    def _feature_facts(self, feature_id: str | None) -> dict[str, Any] | None:
        """The linked feature as it is on disk, or ``None`` when the bug links none or the page does not exist."""

        if feature_id is None:
            return None
        wanted = normalize_feature_id(feature_id)
        for feature in read_feature_pages(self._wiki_path()):
            if normalize_feature_id(feature.feature_id) == wanted:
                evidence = read_feature_evidence(feature.page.body)
                return {
                    "feature": feature,
                    "id": feature.feature_id,
                    "status": feature.status,
                    "apps": feature.apps,
                    "frontmatter": feature.page.frontmatter,
                    "body": feature.page.body,
                    "evidence": evidence,
                    "path": feature.page.path.relative_to(self.root).as_posix(),  # type: ignore[attr-defined]
                }
        return None

    def _feature_stages(self, facts: Mapping[str, Any]) -> dict[str, str]:
        """The stage of each active app of a feature; before `in-dev` every app counts as `in-dev` (CONTRACTS 2.8, B5)."""

        active = active_scope(facts["apps"], self._model)  # type: ignore[attr-defined]
        if status_rank(facts["status"]) < status_rank("in-dev"):
            return {app: "in-dev" for app in active}
        return app_stages(active, facts["evidence"])

    def _bug_required_paths(self, skill: str, supplied: Mapping[str, str], before: Mapping[str, str | None]) -> set[str]:
        """The pages a proposal that writes a bug must have read: every bug page (ids and duplicates) and the linked feature."""

        if skill != "bug-update" and not any(is_bug_path(path) for path in supplied):
            return set()
        paths = {bug.page.path.relative_to(self.root).as_posix() for bug in self._disk_bugs()}  # type: ignore[attr-defined]
        for relative, content in supplied.items():
            if not is_bug_path(relative):
                continue
            for text in (before.get(relative), content):
                if text is None:
                    continue
                try:
                    linked = bs._parse_markdown(text, relative)[0].get("feature")
                except bs.BoardError:
                    continue
                facts = self._feature_facts(linked) if isinstance(linked, str) and linked != "none" else None
                if facts is not None:
                    paths.add(facts["path"])
        return paths

    # -- the page validator -----------------------------------------------------------------------------------------------

    def _validate_bug_page(self, relative: str, content: str, before_text: str | None, supplied: Mapping[str, str]) -> None:
        """The shape of a bug page; for a new page also the creation invariants (CONTRACTS 6.2, B1).

        Evidence rows are not parsed here: the action that writes them reports their problems with its own code.
        """

        frontmatter, body = bs._parse_markdown(content, relative)
        new = before_text is None
        creation = "bug_creation_invalid" if new else "invalid_bug"
        unknown = sorted(set(frontmatter) - set(BUG_FRONTMATTER_FIELDS))
        if unknown:
            raise bs.BoardError(
                "invalid_bug",
                f"Bug page `{relative}` carries only {_quoted(BUG_FRONTMATTER_FIELDS)}; remove {_quoted(unknown)}.",
                409,
                {"path": relative, "fields": unknown},
            )
        missing = [key for key in BUG_REQUIRED_FIELDS if key not in frontmatter]
        if missing:
            raise bs.BoardError("invalid_bug", f"Bug page `{relative}` needs the front matter field(s) {_quoted(missing)}.", 409, {"path": relative, "fields": missing})
        bug_id = frontmatter["id"]
        name = PurePosixPath(relative).name
        match = BUG_FILE_PATTERN.match(name)
        if not isinstance(bug_id, str) or not BUG_ID_PATTERN.match(bug_id) or match is None or match.group(1).casefold() != bug_id.casefold():
            raise bs.BoardError(
                "invalid_bug",
                f"Bug page `{relative}` needs `id: BUG-<n>` and the file name `BUG-<n>-<slug>.md` with the same number and a lowercase hyphenated slug.",
                409,
                {"path": relative},
            )
        text_fields = {"title": frontmatter["title"], "found-in": frontmatter["found-in"], "environment": frontmatter["environment"]}
        blank = [key for key, value in text_fields.items() if not isinstance(value, str) or not value.strip()]
        if blank:
            raise bs.BoardError("invalid_bug", f"Bug page `{relative}`: {_quoted(blank)} must be nonblank text.", 409, {"path": relative, "fields": blank})
        if not _ENVIRONMENT_TOKEN.match(str(frontmatter["environment"]).strip()):
            raise bs.BoardError("invalid_bug", f"Bug page `{relative}`: `environment` is a short name such as `staging`.", 409, {"path": relative})
        status, owner = frontmatter["status"], frontmatter["owner"]
        if status not in BUG_STATUS_ORDER or owner != BUG_OWNER_BY_STATUS.get(status):
            raise bs.BoardError(
                "invalid_bug",
                f"Bug page `{relative}`: `status` is one of {_quoted(BUG_STATUS_ORDER)} and its owner follows it "
                + ", ".join(f"`{key}` + `{value}`" for key, value in BUG_OWNER_BY_STATUS.items())
                + ".",
                409,
                {"path": relative, "status": status, "owner": owner},
            )
        if frontmatter["severity"] not in BUG_SEVERITIES or not isinstance(frontmatter["blocking"], bool):
            raise bs.BoardError(
                "invalid_bug", f"Bug page `{relative}`: `severity` is one of {_quoted(BUG_SEVERITIES)} and `blocking` is `true` or `false`.", 409, {"path": relative}
            )
        apps = frontmatter["apps"]
        known = {app.id for app in self._model.apps} if self._model is not None else set(self._app_ids)  # type: ignore[attr-defined]
        if not isinstance(apps, list) or not apps or any(not isinstance(item, str) for item in apps) or len(set(apps)) != len(apps) or any(item not in known for item in apps):
            raise bs.BoardError(
                creation,
                f"Bug page `{relative}`: `apps` is a non-empty list of distinct apps of this workspace ({_quoted(sorted(known)) or 'none'}).",
                409,
                {"path": relative, "board_apps": sorted(known)[:20]},
            )
        feature = frontmatter["feature"]
        if not isinstance(feature, str) or not (FEATURE_ID_PATTERN.match(feature) or feature == "none"):
            raise bs.BoardError("invalid_bug", f"Bug page `{relative}`: `feature` is a feature ID such as `F-001`, or `none`.", 409, {"path": relative})
        sources = frontmatter["sources"]
        if not isinstance(sources, list) or any(not isinstance(item, str) for item in sources):
            raise bs.BoardError("invalid_bug", f"Bug page `{relative}`: `sources` is a list of strings.", 409, {"path": relative})
        for key, pattern in (("duplicate-of", BUG_ID_PATTERN), ("regression-of", BUG_ID_PATTERN), ("promoted-to", FEATURE_ID_PATTERN)):
            if key in frontmatter and (not isinstance(frontmatter[key], str) or not pattern.match(frontmatter[key])):
                raise bs.BoardError("invalid_bug", f"Bug page `{relative}`: `{key}` must be an ID of the form {'BUG-001' if pattern is BUG_ID_PATTERN else 'F-001'}.", 409, {"path": relative})
        for key in ("deferred-reason", "close-reason"):
            if key in frontmatter and (not isinstance(frontmatter[key], str) or not frontmatter[key].strip()):
                raise bs.BoardError("invalid_bug", f"Bug page `{relative}`: `{key}` is nonblank text when it is set.", 409, {"path": relative})
        absent = [heading for heading in BUG_SECTIONS if not re.search(rf"(?im)^##\s+{re.escape(heading)}\s*#*\s*$", body)]
        if absent:
            raise bs.BoardError("invalid_bug", f"Bug page `{relative}` needs the section(s) {_quoted(f'## {heading}' for heading in absent)}.", 409, {"path": relative, "sections": absent})
        if not section_text(body, "Summary").strip():
            raise bs.BoardError("invalid_bug", f"Bug page `{relative}` has an empty `## Summary`.", 409, {"path": relative})
        bs._validate_no_placeholders(body, relative)
        if new:
            self._validate_new_bug(relative, frontmatter, body, supplied)

    def _validate_new_bug(self, relative: str, frontmatter: Mapping[str, Any], body: str, supplied: Mapping[str, str]) -> None:
        """The creation invariants of a new bug (CONTRACTS 6.2): it is `open` + `dev`, carries no disposition and no evidence."""

        problems: list[str] = []
        if frontmatter["status"] != "open" or frontmatter["owner"] != "dev":
            problems.append("a new bug is `open` + `dev`")
        extra = [key for key in ("deferred-reason", "close-reason", "duplicate-of", "promoted-to") if key in frontmatter]
        if extra:
            problems.append(f"a new bug has none of {_quoted(extra)}")
        filled = [heading for heading in ("Fix", "Verification", "Release", "Evidence history") if not _blank(section_text(body, heading))]
        if filled:
            problems.append(f"the section(s) {_quoted(filled)} are empty on a new bug")
        if problems:
            raise bs.BoardError(
                "bug_creation_invalid",
                f"`{relative}` is not a valid new bug: {'; '.join(problems)}. A bug is created `open` + `dev` with empty Fix, Verification, Release and Evidence history sections.",
                409,
                {"path": relative},
            )
        bug_id = str(frontmatter["id"])
        taken = [bug for bug in self._disk_bugs() if bug.bug_id.casefold() == bug_id.casefold()]
        twins = [
            path
            for path, text in supplied.items()
            if path != relative and is_bug_path(path) and str(bs._parse_markdown(text, path)[0].get("id", "")).casefold() == bug_id.casefold()
        ]
        if taken or twins:
            raise bs.BoardError(
                "bug_id_taken",
                f"`{bug_id}` is already used by `{(taken[0].page.path.relative_to(self.root).as_posix() if taken else twins[0])}`; take the next free bug number.",  # type: ignore[attr-defined]
                409,
                {"bug_id": bug_id},
            )
        self._validate_bug_links(relative, frontmatter, creation=True, supplied=supplied)

    def _validate_bug_links(self, relative: str, frontmatter: Mapping[str, Any], *, creation: bool, supplied: Mapping[str, str] = {}) -> None:
        """The feature a bug names exists and lists the bug's apps (`bug_feature_missing`, `bug_apps_outside_feature`)."""

        code_prefix = "bug_creation_invalid" if creation else None
        feature = frontmatter.get("feature")
        if isinstance(feature, str) and feature != "none":
            facts = self._feature_facts(feature)
            if facts is None:
                raise bs.BoardError(code_prefix or "bug_feature_missing", f"`{relative}` names {feature}, which is not a feature of this wiki. Use `feature: none` for a bug with no feature.", 409, {"path": relative, "feature": feature})
            outside = [app for app in frontmatter.get("apps", []) if app not in facts["apps"]]
            if outside:
                raise bs.BoardError(
                    code_prefix or "bug_apps_outside_feature",
                    f"`{relative}` lists {_quoted(outside)}, which {feature} does not list ({_quoted(facts['apps'])}).",
                    409,
                    {"path": relative, "feature": feature, "apps": outside},
                )
        regression = frontmatter.get("regression-of")
        if creation and isinstance(regression, str):
            known = {bug.bug_id.casefold() for bug in self._bugs_with(supplied)}
            if regression.casefold() not in known:
                raise bs.BoardError("bug_creation_invalid", f"`regression-of: {regression}` names no bug of this wiki.", 409, {"path": relative})

    # -- bug-update -------------------------------------------------------------------------------------------------------

    @staticmethod
    def _bug_action(old: Mapping[str, Any], new: Mapping[str, Any], old_body: str, new_body: str) -> str | None:
        """The bug action a change performs: the status step, or the field that moved while the status stays."""

        old_status, new_status = old.get("status"), new.get("status")
        changed = {key for key in set(old) | set(new) if old.get(key) != new.get(key)}
        if new_status != old_status:
            if new_status == "released":
                raise bs.BoardError(
                    "bug_release_via_release_done",
                    "A bug becomes `released` only inside release-done, which writes its Release row and the release record; bug-update cannot set it.",
                    409,
                )
            if new_status == "closed":
                return "bug-close"
            if old_status == "closed":
                return "bug-reopen"
            step = (old_status, new_status)
            if step == ("open", "in-fix"):
                return "bug-start"
            if step == ("in-fix", "fixed"):
                return "bug-fixed"
            if step == ("fixed", "verified"):
                return "bug-verify"
            if new_status == "in-fix" and old_status in {"fixed", "verified"}:
                return "bug-scope" if changed & set(BUG_SCOPE_FIELDS) else "bug-reject"
            return None
        if changed & set(BUG_SCOPE_FIELDS):
            return "bug-scope"
        if "deferred-reason" in changed:
            return "bug-defer"
        if changed & {"severity", "blocking"}:
            return "bug-triage"
        if section_text(old_body, "Verification") != section_text(new_body, "Verification"):
            return "bug-reverify"
        return None

    def _validate_bug_update(
        self,
        supplied: Mapping[str, str],
        before: Mapping[str, str | None],
    ) -> dict[str, Any]:
        """Validate a `bug-update` proposal and return the operation: its action, checks and the evidence it produces or verifies."""

        paths = [path for path in supplied if is_bug_path(path)]
        if len(paths) != 1 or len(supplied) != 1:
            raise bs.BoardError(
                "one_bug_required",
                "bug-update changes exactly one existing bug page per preview and writes nothing else.",
                409,
                {"paths": bs._names(supplied)},
            )
        relative = paths[0]
        if before.get(relative) is None:
            raise bs.BoardError("bug_not_found", f"`{relative}` does not exist: a bug is created by qa-verify, qa-pass, qa-fail or ingest, never by bug-update.", 409, {"path": relative})
        old, old_body = bs._parse_markdown(before[relative] or "", relative)
        new, new_body = bs._parse_markdown(supplied[relative], relative)
        if str(old.get("id")).casefold() != str(new.get("id")).casefold():
            raise bs.BoardError("bug_frontmatter_scope", f"A bug keeps its `id`; `{relative}` changes it.", 409, {"path": relative, "fields": ["id"]})
        action = self._bug_action(old, new, old_body, new_body)
        if action is None:
            raise bs.BoardError(
                "lifecycle_action_required",
                f"`{relative}` does not change the bug in a way bug-update performs: move its status one step "
                "(open to in-fix, in-fix to fixed, fixed to verified), close or reopen it, or change one of the fields a row allows "
                f"(severity or blocking; apps, feature, title, found-in, environment or sources; deferred-reason; a new Verification row).",
                409,
                {"path": relative},
            )
        spec = bs.lookup_action(action)
        self._require_action_available(action)  # type: ignore[attr-defined]
        disposition = None
        allowed_keys = set(BUG_ACTION_KEYS[action])
        if action == "bug-close":
            reason = new.get("close-reason")
            disposition = str(reason).split(":", 1)[0].strip().lower() if isinstance(reason, str) else None
            if disposition not in CLOSE_DISPOSITIONS:
                raise bs.BoardError(
                    "bug_close_reason_required",
                    "A closure records `close-reason`: `wont-fix: <reason>`, `duplicate` (with `duplicate-of`) or `promoted` (with `promoted-to`).",
                    409,
                    {"path": relative},
                )
            allowed_keys |= _CLOSE_KEYS[disposition]
        old_pair = (old.get("status"), old.get("owner"))
        sources = spec.sources
        if old_pair not in sources:
            raise bs.BoardError(
                "unsupported_source_pair",
                f"Action `{action}` runs on a bug that is " + " or ".join(f"`{status}` + `{owner}`" for status, owner in sources) + f"; `{relative}` is `{old_pair[0]}` + `{old_pair[1]}`.",
                409,
                {"path": relative, "action": action, "status": old_pair[0]},
            )
        if action == "bug-reopen" and BugPage(parse_markdown_text(self._wiki_path() / "bugs" / PurePosixPath(relative).name, before[relative] or "")).disposition != "wont-fix":
            other = old.get("close-reason") or "a closure"
            raise bs.BoardError(
                "unsupported_source_pair",
                f"Only a bug closed `wont-fix` reopens; {old.get('id')} is closed as `{other}`. A recurrence is a new bug with `regression-of: {old.get('id')}`.",
                409,
                {"path": relative},
            )
        changed = {key for key in set(old) | set(new) if old.get(key) != new.get(key)}
        outside = changed - allowed_keys
        if outside:
            raise bs.BoardError(
                "bug_frontmatter_scope",
                f"Action `{action}` cannot change {_quoted(sorted(outside))} in `{relative}`; it may change only {_quoted(sorted(allowed_keys)) or 'no front matter'}. Restore the other fields to their current values.",
                409,
                {"path": relative, "fields": sorted(outside), "allowed": sorted(allowed_keys)},
            )
        sections = BUG_ACTION_SECTIONS[action]
        if sections:
            self._assert_only_body_sections_changed(old_body, new_body, set(sections), "lifecycle_body_scope", f"Action `{action}` may change only the sections {_quoted(sorted(sections))} of the bug page.")  # type: ignore[attr-defined]
        elif old_body != new_body:
            self._assert_only_body_sections_changed(old_body, new_body, set(), "lifecycle_body_scope", f"Action `{action}` changes only front matter on the bug page.")  # type: ignore[attr-defined]
            raise bs.BoardError("lifecycle_body_scope", f"Action `{action}` changes only front matter on the bug page.", 409)
        target_status, target_owner = spec.target_status, spec.target_owner
        if target_status not in {None, "unchanged"} and (new.get("status"), new.get("owner")) != (target_status, target_owner):
            raise bs.BoardError("invalid_transition_target", f"Action `{action}` moves a bug to `{target_status}` + `{target_owner}`.", 409, {"path": relative})
        if target_status == "unchanged" and (new.get("status"), new.get("owner")) != old_pair and action != "bug-scope":
            raise bs.BoardError("bug_frontmatter_scope", f"Action `{action}` leaves the status and owner as they are.", 409, {"path": relative, "fields": ["status", "owner"]})

        context = {
            "relative": relative,
            "old": old,
            "new": new,
            "old_body": old_body,
            "new_body": new_body,
            "old_text": before[relative] or "",
            "new_text": supplied[relative],
            "old_bug": BugPage(parse_markdown_text(self._wiki_path() / "bugs" / PurePosixPath(relative).name, before[relative] or "")),
            "new_bug": BugPage(parse_markdown_text(self._wiki_path() / "bugs" / PurePosixPath(relative).name, supplied[relative])),
            "supplied": supplied,
        }
        validator = getattr(self, "_bug_" + action.split("-", 1)[1].replace("-", "_"))
        produces, subjects = validator(context)
        bug_id = str(new["id"])
        check = {"code": "bug-update-structure", "status": "pass", "message": f"The `{action}` change of {bug_id} matches its row of the bug table."}
        operation: dict[str, Any] = {
            "action": action,
            "feature_id": bug_id,
            "source": {"status": old.get("status"), "owner": old.get("owner")},
            "target": {"status": new.get("status"), "owner": new.get("owner")},
            "classification": "ready",
            "checks": [check],
            "blockers": [],
            "warnings": [],
            "produces_evidence": produces,
            "separation_subjects": subjects,
        }
        if disposition is not None:
            operation["disposition"] = disposition
        return operation

    # -- the rows of the bug table ---------------------------------------------------------------------------------------

    def _incoming_duplicates(self, context: Mapping[str, Any]) -> None:
        """A change to a canonical bug keeps every duplicate closed against it valid (`duplicate_target_invalid`)."""

        new_bug: BugPage = context["new_bug"]
        index = bugs_by_id(self._bugs_with(context["supplied"]))
        index[new_bug.bug_id.casefold()] = new_bug
        for duplicate in index.values():
            if duplicate.status == "closed" and duplicate.disposition == "duplicate" and (duplicate.duplicate_of or "").casefold() == new_bug.bug_id.casefold():
                problem = duplicate_target_problem(duplicate, index)
                if problem is not None:
                    raise bs.BoardError(
                        "duplicate_target_invalid",
                        f"`{duplicate.bug_id}` is closed as a duplicate of `{new_bug.bug_id}`, which would no longer qualify: {problem}. "
                        "Resolve the canonical bug, or have the product owner close it with an explicit disposition.",
                        409,
                        {"bug": duplicate.bug_id, "canonical": new_bug.bug_id},
                    )

    def _bug_triage(self, context: Mapping[str, Any]) -> tuple[list, list]:
        new = context["new"]
        if new.get("blocking") is True and "deferred-reason" in new:
            raise bs.BoardError("bug_not_deferrable", "A blocking bug cannot be deferred; remove the deferral first.", 409, {"path": context["relative"]})
        self._incoming_duplicates(context)
        return [], []

    def _bug_scope(self, context: Mapping[str, Any]) -> tuple[list, list]:
        relative = context["relative"]
        old, new = context["old"], context["new"]
        self._validate_bug_links(relative, new, creation=False)
        scope_changed = any(old.get(key) != new.get(key) for key in ("apps", "feature"))
        reset = old.get("status") in {"fixed", "verified"} and new.get("status") == "in-fix"
        if old.get("status") in {"fixed", "verified"} and scope_changed and not reset:
            raise bs.BoardError(
                "bug_frontmatter_scope",
                f"`{relative}` is {old.get('status')}: changing its apps or feature resets it to `in-fix` + `dev` and archives its Fix and Verification rows in Evidence history.",
                409,
                {"path": relative, "fields": ["status", "owner"]},
            )
        if reset and not scope_changed:
            raise bs.BoardError("bug_frontmatter_scope", "A bug resets to `in-fix` only when its apps or feature change.", 409, {"path": relative})
        if reset:
            if (new.get("status"), new.get("owner")) != ("in-fix", "dev"):
                raise bs.BoardError("invalid_transition_target", "A scope change that resets a bug moves it to `in-fix` + `dev`.", 409, {"path": relative})
            old_fix = parse_fix_rows(context["old_body"])[0]
            old_verification = parse_verification_rows(context["old_body"])[0]
            expected = [("Fix", row.cells) for row in old_fix] + [("Verification", row.cells) for row in old_verification]
            self._validate_bug_history("bug-scope", context, expected, new_active_empty=("Fix", "Verification"))
        elif context["new_body"] != context["old_body"]:
            raise bs.BoardError("lifecycle_body_scope", "A scope change that leaves the bug in its status changes no section.", 409, {"path": relative})
        self._incoming_duplicates(context)
        return [], []

    def _bug_start(self, context: Mapping[str, Any]) -> tuple[list, list]:
        if context["old_bug"].deferred:
            raise bs.BoardError("bug_deferred", f"{context['old_bug'].bug_id} is deferred; undefer it before work starts.", 409, {"path": context["relative"]})
        return [], []

    def _bug_fixed(self, context: Mapping[str, Any]) -> tuple[list, list]:
        relative = context["relative"]
        bug: BugPage = context["new_bug"]
        rows, problems = parse_fix_rows(context["new_body"])
        if problems:
            raise bs.BoardError(problems[0].code, f"The `## Fix` table in `{relative}` is not valid: " + " ".join(item.message for item in problems[:4]), 409, {"path": relative})
        missing = [app for app in bug.apps if all(row.app != app for row in rows)]
        extra = [row.app for row in rows if row.app not in bug.apps]
        counts = [row.app for row in rows]
        if missing or extra or len(set(counts)) != len(counts):
            raise bs.BoardError(
                "bug_fix_evidence_required",
                f"A fixed bug has one Fix row for each of its apps ({_quoted(bug.apps)}) and no other: "
                + ("; ".join(part for part in (f"missing {_quoted(missing)}" if missing else "", f"not the bug's apps {_quoted(extra)}" if extra else "", "an app appears twice" if len(set(counts)) != len(counts) else "") if part))
                + ". Columns: `| App | Artifact | Implementation | Tests | Basis |`.",
                409,
                {"path": relative, "apps": bug.apps},
            )
        facts = self._feature_facts(bug.feature)
        if facts is not None:
            stages = self._feature_stages(facts)
            late = [f"`{app}` is {stages[app]}" for app in bug.apps if app in stages and stages[app] not in {"in-dev", "released"}]
            if late:
                raise bs.BoardError(
                    "feature_in_qa_cycle",
                    f"{facts['id']} is in its QA cycle ({'; '.join(late)}), so a fix cannot be recorded against its apps now. Run qa-fail on the app first (a qa-fail may cite this bug), then fix.",
                    409,
                    {"path": relative, "feature": facts["id"]},
                )
        history = parse_evidence_history(context["new_body"])
        produces = [
            {"kind": "fix", "item_id": bug.bug_id, "app": row.app, "generation": evidence_generation(history, "Fix", row.app), "row_digest": row_digest(row.cells)}
            for row in rows
        ]
        return produces, []

    def _verification_expected(self, bug: BugPage, app: str) -> str | None:
        facts = self._feature_facts(bug.feature)
        return verification_artifact(bug, app, facts["evidence"] if facts is not None else None)

    def _check_verification_rows(self, context: Mapping[str, Any], *, attempt: int) -> list:
        """The Verification rows of `bug-verify` and `bug-reverify`: one passing row per bug app on the verification artifact."""

        relative = context["relative"]
        bug: BugPage = context["new_bug"]
        rows, problems = parse_verification_rows(context["new_body"])
        if problems:
            raise bs.BoardError(problems[0].code, f"The `## Verification` table in `{relative}` is not valid: " + " ".join(item.message for item in problems[:4]), 409, {"path": relative})
        policy = self._read_policy()  # type: ignore[attr-defined]
        missing: list[str] = []
        for app in bug.apps:
            wanted = self._verification_expected(bug, app)
            match = [row for row in rows if row.app == app and row.result == "pass" and row.artifact == wanted]
            if wanted is None or len(match) != 1:
                missing.append(f"`{app}` (on `{wanted}`)")
        extra = [row.app for row in rows if row.app not in bug.apps or row.result != "pass"]
        if missing or extra or len(rows) != len(bug.apps):
            raise bs.BoardError(
                "bug_verification_required",
                f"{bug.bug_id} needs one passing Verification row per app, on the verification artifact: missing {', '.join(missing) or 'none'}"
                + (f"; rows to remove: {_quoted(extra)}" if extra else "")
                + ". Columns: `| App | Method | Artifact | Environment | Attempt | Result | Evidence | Basis |`.",
                409,
                {"path": relative},
            )
        for row in rows:
            if row.attempt != attempt:
                raise bs.BoardError("qa_attempt_mismatch", f"The Verification row of `{row.app}` is in attempt qa-{row.attempt}; the current attempt is qa-{attempt}.", 409, {"path": relative})
            if row.environment not in environments_of(policy, row.app):
                raise bs.BoardError(
                    "environment_unknown",
                    f"The environment `{row.environment}` of the Verification row of `{row.app}` is not `local`, `ci` or an environment of its delivery target ({_quoted(sorted(environments_of(policy, row.app)))}).",
                    409,
                    {"path": relative},
                )
        return rows

    def _fix_subjects(self, bug: BugPage, body: str) -> list[dict[str, Any]]:
        """The Fix rows a verification must be separated from: one subject per bug app (CONTRACTS 1.6)."""

        history = parse_evidence_history(body)
        return [
            {"kind": "fix", "item_id": bug.bug_id, "app": row.app, "generation": evidence_generation(history, "Fix", row.app), "row_digest": row_digest(row.cells)}
            for row in parse_fix_rows(body)[0]
            if row.app in bug.apps
        ]

    def _bug_verify(self, context: Mapping[str, Any]) -> tuple[list, list]:
        bug: BugPage = context["new_bug"]
        self._check_verification_rows(context, attempt=bug_qa_attempt(parse_evidence_history(context["old_body"])))
        return [], self._fix_subjects(bug, context["new_body"])

    def _bug_reverify(self, context: Mapping[str, Any]) -> tuple[list, list]:
        bug: BugPage = context["new_bug"]
        old_rows = parse_verification_rows(context["old_body"])[0]
        expected = [("Verification", row.cells) for row in old_rows]
        if not expected:
            raise bs.BoardError("bug_verification_required", f"{bug.bug_id} has no Verification row to verify again.", 409, {"path": context["relative"]})
        self._validate_bug_history("bug-reverify", context, expected)
        self._check_verification_rows(context, attempt=bug_qa_attempt(parse_evidence_history(context["new_body"])))
        return [], self._fix_subjects(bug, context["new_body"])

    def _bug_reject(self, context: Mapping[str, Any]) -> tuple[list, list]:
        relative = context["relative"]
        bug: BugPage = context["old_bug"]
        old_fix = parse_fix_rows(context["old_body"])[0]
        old_verification = parse_verification_rows(context["old_body"])[0]
        expected = [("Fix", row.cells) for row in old_fix] + [("Verification", row.cells) for row in old_verification]
        entry = self._validate_bug_history("bug-reject", context, expected, new_active_empty=("Fix", "Verification"), extra_verification=True)
        attempt = bug_qa_attempt(parse_evidence_history(context["old_body"]))
        old_cells = {tuple(cell.strip() for cell in row.cells) for row in old_verification}
        failing = [
            cells for section, cells in entry.archived_rows
            if section == "Verification" and tuple(cell.strip() for cell in cells) not in old_cells
        ]
        if not failing:
            raise bs.BoardError(
                "evidence_not_archived",
                f"A rejection writes the failing Verification row and archives it in the same write: add it under `- Archived evidence:` as `| Verification | <app> | <method> | <artifact> | <environment> | qa-{attempt} | fail | <evidence> | <basis> |` ({bug.bug_id}).",
                409,
                {"path": relative},
            )
        rows = parse_verification_rows("## Verification\n| App | Method | Artifact | Environment | Attempt | Result | Evidence | Basis |\n|---|---|---|---|---|---|---|---|\n" + "\n".join(f"| {' | '.join(cells)} |" for cells in failing))
        if rows[1]:
            raise bs.BoardError(rows[1][0].code, "The failing Verification row is not valid: " + " ".join(item.message for item in rows[1][:3]), 409, {"path": relative})
        for row in rows[0]:
            if row.result not in {"fail", "blocked"} or row.app not in bug.apps or row.attempt != attempt:
                raise bs.BoardError(
                    "bug_verification_required",
                    f"The failing row of a rejection names an app of {bug.bug_id} with result `fail` or `blocked` in the current attempt qa-{attempt}.",
                    409,
                    {"path": relative},
                )
        return [], []

    def _bug_close(self, context: Mapping[str, Any]) -> tuple[list, list]:
        relative = context["relative"]
        old, new = context["old"], context["new"]
        reason = str(new.get("close-reason"))
        disposition = reason.split(":", 1)[0].strip().lower()
        status = old.get("status")
        if disposition == "wont-fix":
            text = reason.split(":", 1)[1].strip() if ":" in reason else ""
            if not text:
                raise bs.BoardError("bug_close_reason_required", "A `wont-fix` closure needs a reason: `close-reason: wont-fix: <reason>`.", 409, {"path": relative})
        elif disposition == "duplicate":
            if status == "verified":
                raise bs.BoardError("unsupported_source_pair", "A verified bug is closed `wont-fix` or `promoted`; a duplicate closure runs on an open, in-fix or fixed bug.", 409, {"path": relative})
            index = bugs_by_id(self._bugs_with(context["supplied"]))
            problem = duplicate_target_problem(context["new_bug"], index)
            if problem is not None:
                raise bs.BoardError(
                    "duplicate_target_invalid",
                    f"`duplicate-of: {new.get('duplicate-of')}` is not valid: {problem}. The canonical bug exists, is not closed, has the same feature and covers the apps, and is not deferred for a blocking duplicate.",
                    409,
                    {"path": relative},
                )
        else:
            target = new.get("promoted-to")
            facts = self._feature_facts(str(target)) if target else None
            bug = context["new_bug"]
            if facts is None or facts["status"] == "released" or not feature_cites_bug(
                facts["frontmatter"], facts["body"], relative, bug.bug_id
            ):
                raise bs.BoardError(
                    "bug_promotion_unreopened",
                    f"`promoted-to: {target}` must name a feature that is not released and lists `{relative}` in its `sources` or {bug.bug_id} under Linked bugs in its latest Evidence history entry. "
                    "Create the feature with ingest (citing the bug page) or reopen it first.",
                    409,
                    {"path": relative, "feature": target},
                )
        return [], []

    def _bug_defer(self, context: Mapping[str, Any]) -> tuple[list, list]:
        relative = context["relative"]
        old, new = context["old"], context["new"]
        if "deferred-reason" in new:
            if old.get("blocking") is True or new.get("blocking") is True:
                raise bs.BoardError("bug_not_deferrable", f"{new.get('id')} is blocking; a blocking bug cannot be deferred. Triage it to `blocking: false` first (while it is open).", 409, {"path": relative})
            if not isinstance(new.get("deferred-reason"), str) or not new["deferred-reason"].strip():
                raise bs.BoardError("bug_not_deferrable", "A deferral records its reason in `deferred-reason`.", 409, {"path": relative})
        elif "deferred-reason" not in old:
            raise bs.BoardError("bug_not_deferrable", "There is no deferral to remove.", 409, {"path": relative})
        self._incoming_duplicates(context)
        return [], []

    def _bug_reopen(self, context: Mapping[str, Any]) -> tuple[list, list]:
        relative = context["relative"]
        old, new = context["old"], context["new"]
        old_bug: BugPage = context["old_bug"]
        if old_bug.disposition != "wont-fix":
            raise bs.BoardError(
                "unsupported_source_pair",
                f"Only a bug closed `wont-fix` reopens; {old_bug.bug_id} is closed as `{old_bug.disposition}`. A recurrence is a new bug with `regression-of: {old_bug.bug_id}`.",
                409,
                {"path": relative},
            )
        released = [app for app in old_bug.apps if any(row.app == app and row.outcome == "released" for row in _release_rows(context["old_body"]))]
        if released:
            raise bs.BoardError(
                "bug_reopen_after_release",
                f"{old_bug.bug_id} has a released Release row for {_quoted(released)}; a recurrence is a new bug with `regression-of: {old_bug.bug_id}`.",
                409,
                {"path": relative, "apps": released},
            )
        if "close-reason" in new:
            raise bs.BoardError("bug_frontmatter_scope", "Reopening removes `close-reason`.", 409, {"path": relative, "fields": ["close-reason"]})
        expected = (
            [("Fix", row.cells) for row in parse_fix_rows(context["old_body"])[0]]
            + [("Verification", row.cells) for row in parse_verification_rows(context["old_body"])[0]]
            + [("Release", row.cells) for row in _release_rows(context["old_body"])]
        )
        self._validate_bug_history("bug-reopen", context, expected, new_active_empty=("Fix", "Verification", "Release"), require_entry=bool(expected))
        return [], []

    # -- Evidence history of a bug ---------------------------------------------------------------------------------------

    def _validate_bug_history(
        self,
        action: str,
        context: Mapping[str, Any],
        expected: list[tuple[str, tuple[str, ...]]],
        *,
        new_active_empty: Iterable[str] = (),
        extra_verification: bool = False,
        require_entry: bool = True,
    ) -> Any:
        """The Evidence history entry of a bug write that archives rows: one entry, headed with the day and the action.

        The entry copies each archived row verbatim under `- Archived evidence:`, prefixed by its section name; the rows the
        action archives leave their tables in the same write. `extra_verification` lets a rejection archive the failing row
        it writes besides the rows already active. Returns the entry.
        """

        relative = context["relative"]
        old_history = section_text(context["old_body"], "Evidence history")
        new_history = section_text(context["new_body"], "Evidence history")
        if not new_history.startswith(old_history):
            raise bs.BoardError("history_not_append_only", "Evidence history must preserve all previous entries and append one new entry.", 409, {"path": relative})
        addition = new_history[len(old_history):]
        today = date.today().isoformat()
        if not addition.strip():
            if require_entry:
                raise bs.BoardError(
                    "history_entry_required",
                    f"Evidence history needs one new entry headed `### {today} - {action}` that archives the evidence this write removes.",
                    409,
                    {"path": relative, "action": action},
                )
            return None
        headings = [(match.group(1), match.group(2)) for line in addition.splitlines() if (match := HISTORY_HEADING.match(line.strip()))]
        if len(headings) != 1 or headings[0] != (today, action):
            raise bs.BoardError(
                "history_entry_required",
                f"This write appends exactly one Evidence history entry, headed `### {today} - {action}` (the preview day and the action).",
                409,
                {"path": relative, "action": action},
            )
        entry = parse_evidence_history(context["new_body"])[-1]
        reason = entry.fields.get("Reason", "").strip()
        if len(reason) < 8:
            raise bs.BoardError("impact_review_required", "Evidence history must include a `- Reason:` bullet with substantive text.", 409, {"label": "Reason"})
        bug_apps = {*context["old_bug"].apps, *context["new_bug"].apps}
        if not entry.affected_apps or not set(entry.affected_apps) <= bug_apps:
            raise bs.BoardError("reopen_app_scope", "Evidence history must name affected app IDs from the bug's apps under `- Affected apps:`.", 409, {"path": relative})

        def key(section: str, cells: Iterable[str]) -> str:
            return bs._normalized_table_text(section + " | " + " | ".join(cells))

        active_before = {
            key(section, cells)
            for section, cells in (
                *(("Fix", row.cells) for row in parse_fix_rows(context["old_body"])[0]),
                *(("Verification", row.cells) for row in parse_verification_rows(context["old_body"])[0]),
                *(("Release", row.cells) for row in _release_rows(context["old_body"])),
            )
        }
        active_after = {
            key(section, cells)
            for section, cells in (
                *(("Fix", row.cells) for row in parse_fix_rows(context["new_body"])[0]),
                *(("Verification", row.cells) for row in parse_verification_rows(context["new_body"])[0]),
                *(("Release", row.cells) for row in _release_rows(context["new_body"])),
            )
        }
        archived = {key(section, cells): (section, cells) for section, cells in entry.archived_rows}
        for section, cells in expected:
            if key(section, cells) not in archived:
                raise bs.BoardError(
                    "evidence_not_archived",
                    f"Evidence history must copy each archived row verbatim under `- Archived evidence:`, prefixed by its section name. Missing: {bs._clip(bs._row_line(section, cells), 300)}",
                    409,
                    {"path": relative, "label": "Archived evidence"},
                )
        for item, (section, cells) in archived.items():
            if item in active_after:
                raise bs.BoardError("evidence_still_active", f"The row {bs._clip(bs._row_line(section, cells), 200)} is archived and still active.", 409, {"path": relative})
            expected_keys = {key(name, row) for name, row in expected}
            if item not in expected_keys and not (extra_verification and section == "Verification"):
                raise bs.BoardError(
                    "evidence_not_archived",
                    f"Archived evidence lists a row that `{action}` does not archive: {bs._clip(bs._row_line(section, cells), 200)}",
                    409,
                    {"path": relative},
                )
        removed = active_before - active_after
        for item in removed:
            if item not in archived:
                raise bs.BoardError("evidence_not_archived", "A row leaves its table without being archived in Evidence history.", 409, {"path": relative})
        for section in new_active_empty:
            rows = {"Fix": parse_fix_rows, "Verification": parse_verification_rows}.get(section)
            remaining = rows(context["new_body"])[0] if rows is not None else _release_rows(context["new_body"])
            if remaining:
                raise bs.BoardError("evidence_still_active", f"After `{action}` the `## {section}` table holds no row; its rows are archived in Evidence history.", 409, {"path": relative})
        return entry


def _release_rows(body: str) -> list:
    from prism_cli.wiki_model import parse_release_rows

    return parse_release_rows(body)[0]
