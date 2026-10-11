# Wiki Workflow

This page explains how the generated-project product wiki works, how the read/query layer
fits into it, and how to interpret `WIKI_REPORT.md`.

If you are new to Prism, read this page in this order:

1. understand the wiki and source-of-truth boundary
2. follow the role flow that matches your work
3. use the command reference examples for deeper drill-down

## Core Idea

The wiki is the shared source of truth for product intent in generated Prism projects.

The most important directories are:

- `knowledge/wiki/features/`
- `knowledge/wiki/design/` and `knowledge/wiki/technical-design/`
- `knowledge/wiki/app-requirements/`
- `knowledge/wiki/business-rules/`
- `knowledge/wiki/api-contracts/`
- `knowledge/wiki/bugs/`, `knowledge/wiki/releases/` and `knowledge/wiki/incidents/`
- `knowledge/wiki/advisory/`
- `knowledge/wiki/topics/`, `research/` and `plans/`, and the pages `direction.md` and `roadmap.md`

`knowledge/wiki/index.md` lists every page, one line each; `knowledge/wiki/status-board.md`
is the status board of the features, the bugs and the apps in operation. The lifecycle
operations create and refine that state. The read/query operations help agents and humans
navigate it.

## Page Kinds

Each kind has a format in the `_FORMAT.md` of its folder; `SCHEMA.md` lists them and defines
the formats of `direction.md` and `roadmap.md`. Two groups of kinds exist.

**The lifecycle pages** carry a feature, a bug or an operation through the stages:

| Kind | Where | Holds |
|---|---|---|
| Feature | `features/F-XXX-[slug].md` | The specification, the evidence tables (Delivery evidence, QA verification, Release) and the Evidence history of one feature. Its front matter carries `status`, `owner`, `apps`, the design tracks and the revalidation domains. |
| Design page | `design/F-XXX-[slug].md` | The UI design of a feature, for the apps with a UI. It belongs to the UI track. |
| Technical design | `technical-design/F-XXX-[slug].md` | Architecture impact per app, data model and migrations, security and privacy, non-functional needs, risks, decisions, the API contract link and the test strategy that names every acceptance criterion. It belongs to the technical track. |
| App requirements | `app-requirements/F-XXX-[app-id].md` | What one app builds for one feature, with its dependencies. One page per app of the scope. |
| API contract | `api-contracts/F-XXX.md` | The agreed API shape of a feature, with a version and a digest that delivery evidence cites. |
| Bug | `bugs/BUG-XXX-[slug].md` | One defect, with its severity, whether it blocks, the apps and feature it affects, and its Fix, Verification and Release rows. A current-state page. |
| Release record | `releases/REL-XXX.md` | One release, rollback or redeploy: the features and bugs delivered, per app the target, version, attempt and outcome, and a verbatim snapshot of each cited API contract. A dated record. |
| Incident | `incidents/INC-XXX-[slug].md` | One incident: impact, timeline, cause, mitigation, resolution and follow-up bugs or features. A dated record, written through `ingest`. |
| Decision | `decisions/ADR-XXX-[slug].md` | One architecture decision. A dated record. |
| Business rule, persona | `business-rules/`, `personas/` | Invariants and constraints; customer segments and user types. |
| Advisory | `advisory/` | The advisory board and its reviews. |

**The general knowledge pages** sit beside the pipeline:

| Kind | Where | Holds |
|---|---|---|
| Topic | `topics/[slug].md` | A synthesis of what several sources and pages say about one subject. |
| Research | `research/[slug].md` | The current answer to one question, and the gaps that remain. |
| Plan | `plans/[slug].md` | The current status of one plan: goal, status, next steps, blockers. It keeps no history. |
| Direction | `direction.md` | The current direction and the principles behind it. |
| Roadmap | `roadmap.md` | What comes next. A date about the world, such as a launch date, may appear in it. |

A topic, research page, plan, direction or roadmap page starts with front matter that carries
`kind` (the kind of its folder), `sources` (a list of the processed intake items, records or
URLs it rests on) and, for a topic, research page or plan, a `title` and a `status` (topic:
`draft` or `current`; research: `open` or `concluded`; plan: `proposed`, `active`, `paused`,
`done` or `dropped`). A page carries no date about itself and labels its claims with the
evidence labels below. `prism wiki lint` checks the front matter of each kind: for example
`invalid-topic-kind`, `invalid-plan-status`, `missing-research-frontmatter` and
`invalid-roadmap-sources`. The lifecycle lint codes are listed under
[Lifecycle lint codes](#lifecycle-lint-codes).

## The Standard Files

Four files at the top of `knowledge/wiki/` carry the rules. `SCHEMA.md`, `LIFECYCLE.md` and
`ACTIONS.md` start with the front matter `schema-version: 1`, and each file is small enough for one
`read_workspace` page.

| File | Holds | Read for |
|---|---|---|
| `SCHEMA.md` | The directory structure, the page kinds, the evidence labels, links and sources, records and decision supersession, raw sources and conflict quarantine, the `index.md`, `status-board.md` and `log.md` conventions, freshness, and the canonical blocker categories. | Every wiki operation |
| `LIFECYCLE.md` | The feature page format, the statuses and owners, the design owner and the design tracks, the API contract, delivery, QA, release and reopening rules, the evidence tables and Evidence history, and the advisory file formats. | Every feature, board or advisory operation |
| `ACTIONS.md` | The registry of lifecycle actions with their source and destination, approver role and write scope, the common action protocol, and the specification and PO handoff contracts. | Every lifecycle action |
| `CONNECTED.md` | How a connected agent reads the board's tools, previews, applies, recovers and retries. Prism owns this file; `prism workflow install` and `prism workflow upgrade` never overwrite a copy that differs. | Any work through the MCP connection |

`SETTINGS.md` holds the project settings, and each page folder's `_FORMAT.md` holds the format
of its kind. A skill reads the files its action needs, so an agent does not load the whole
rulebook for every request.

## The Index And The Status Board

`index.md` is the general index: one line per page, grouped by kind, in the present tense. A generated workspace also lists the pages of its template-owned `docs/` folder under "Project docs", one line each, linked as `../../docs/<page>.md`; lint checks those lines like the others.

```markdown
## Topics
- [Payment flows](topics/payment-flows.md): Payments settle within one business day.
```

Every page of the wiki has exactly one line, including `SCHEMA.md` and `status-board.md`
(`_FORMAT.md` files, `index.md`, `log.md` and `WIKI_REPORT.md` are not pages). A changed
page's line is replaced in place; the index has no dates and no narrative. The connected
board writes the line of each page it writes, from the page's title and the first
sentence of its summary; a skill that writes files directly maintains the lines itself.
Agents read the index first to find the pages a task needs, and `prism wiki search` reads
it before it opens any page.

`status-board.md` is the status board, a dedicated view of three tables. Every row is merged
by its key, so unrelated rows survive a concurrent write and a row that changed after a
preview is a conflict.

```markdown
| ID | Feature | Status | Owner | Board Review | Design tracks | App stages | Open bugs |
|----|---------|--------|-------|--------------|---------------|------------|-----------|
| F-001 | User login | in-dev | dev | not-needed | ui: done; technical: done | api: ready-for-qa; web: in-dev | BUG-002 |

## Bugs

| ID | Bug | Status | Owner | Apps | Feature | Blocking |
|----|-----|--------|-------|------|---------|----------|
| BUG-002 | Login fails offline | open | dev | web | F-001 | yes |

## Operations

| App | Delivery target | Released features | Latest release | Latest attempt outcome | Open bugs | Open incidents |
|-----|-----------------|-------------------|----------------|------------------------|-----------|----------------|
| api | production | F-003 | REL-004 | rolled-back | — | INC-001 |
```

- The **feature table** has one row per feature. `Design tracks` is `ui: <state>; technical:
  <state>` once the feature has tracks and `—` before. `App stages` lists the stage of each
  active app from `in-dev` on. `Open bugs` lists the bugs of the feature that are neither
  `released` nor `closed`.
- **Bugs** has one row per bug that is neither `released` nor `closed`; `Blocking` is `yes` or `no`.
- **Operations** has one row per app that has something to show: its released features, the
  highest-numbered release record that names it with that record's outcome for it (`released`,
  `failed` or `rolled-back`), and its open bugs and incidents. `Delivery target` is the app's
  target from `SETTINGS.md` when the row was last written.

`prism wiki lint` reports a feature with no row, a row with no feature and a row that
disagrees with the pages (`status-board-frontmatter-drift`).

## Source-of-Truth Boundary

The most important rule is simple:

- the wiki files are the source of truth
- `WIKI_REPORT.md` is only an orientation layer
- read/query commands assemble context, but they do not replace the underlying files

If `WIKI_REPORT.md` disagrees with the underlying wiki files, the wiki files win.

## Current State And History

Wiki pages state what is true now. No page carries a date about itself: feature,
persona, business-rule, design, app-requirement and API-contract pages have no
`introduced`, `last-updated` or similar field, and `index.md` and `status-board.md` have no date column. A
date about the world, such as an effective date or a deadline, is a domain fact and
may appear in a page.

Records keep their own date, because the date is part of what they record: an ADR
(`date`), an advisory review (`reviewed`), a release record (`date`), an incident (`date`, the
day it began), each entry under a feature's or a bug's `## Evidence history` (headed
`### YYYY-MM-DD - <action>`) and a processed intake item (its `YYYY-MM-DD-slug` folder name).
A record is never rewritten, except where its format allows it: an ADR's status fields, and an
incident's status, appended Timeline lines and added follow-ups. A source or a decision that
changes a fact replaces the superseded content on the page in place; rationale is
stated as a current fact.

When something was written, decided, verified or amended is recorded in
`knowledge/wiki/log.md`, which is append-only and the only home for history. Every
entry has the same shape:

```text
## 2026-10-06 po-handoff | F-001
- paths: knowledge/wiki/features/F-001-review-summary-export.md, knowledge/wiki/status-board.md
- evidence: knowledge/intake/processed/2026-10-01-review-summary
- by: Claude Code (confirmed by Riley)
Handed to design after the board review.
```

`paths` lists the changed paths, `evidence` links to the evidence and never copies
it, and `by` names who made the change. One optional line of plain text, at most one
sentence, may follow. The board service writes its entries in this format; its
`evidence` is the board preview, and it keeps the actor and a preview marker as HTML
comments inside the entry. `SCHEMA.md` defines the format.

`prism wiki lint` reports:

| Code | Severity | Meaning |
|---|---|---|
| `history-date-on-page` | error | A history-date field (`introduced`, `last-updated`, `created`, `updated`, `date-updated` and similar) in the front matter of a current-state page. The message points to `log.md`. |
| `malformed-log-entry` | warning | A `log.md` entry that is not in the format. Lint reports it and never rewrites the log. |
| `missing-schema-version` | error | `SCHEMA.md`, `LIFECYCLE.md` or `ACTIONS.md` without the front matter `schema-version: 1`. |
| `unlinked-claim` | warning | A `**Decided:**` or `**Observed:**` item that links no evidence. |
| `unknown-evidence-label` | warning | A bold run-in label such as `**Note:**` that is none of the five evidence labels. |
| `supersession-mismatch` | error | The `supersedes` and `superseded-by` links of two ADRs disagree, or one is missing, or `status: superseded` and `superseded-by` do not go together. |
| `superseded-decision-cited` | warning | A current-state page links an ADR that a newer ADR supersedes. |
| `processed-source-without-manifest` | warning | A processed intake item without a `MANIFEST.md`. |
| `unresolved-conflict` | warning | A quarantined `CONFLICT.md` with `status: open`. The message links the file. A non-empty quarantine is not a gate. |
| `malformed-conflict` | error | A quarantined item without a `CONFLICT.md`, or one that does not follow the format. |
| `missing-index-entry` | warning | A wiki page with no line in `index.md`. It names the page and never blocks a lifecycle action. |
| `orphan-index-entry` | warning | An `index.md` line whose target is not a page of the wiki, or a "Project docs" line whose `docs/` page does not exist. |
| `duplicate-index-entry` | warning | A page, or a project doc, with more than one line in `index.md`. |
| `malformed-index` | error | `index.md` cannot be read. |
| `malformed-status-board` | error | `status-board.md` cannot be read or has no feature table. |
| `feature-missing-from-status-board` | error | A feature page with no row in `status-board.md`. |
| `status-board-missing-feature` | error | A `status-board.md` row with no feature page. |
| `status-board-frontmatter-drift` | error | A feature row's status, owner, board review, design tracks, app stages or open bugs differ from the feature's pages, or a Bugs or Operations row differs from the bug, incident and release pages. The `Delivery target` cell is not compared. |
| `broken-link` | error | A relative Markdown link or a `sources` entry that does not resolve to an existing file or folder, that leaves the workspace, or is a malformed or undeclared `repo:` link, or a `repo:` link whose target is missing from a resolved checkout. The finding names the page, the link and the line. |
| `broken-anchor` | warning | A `#heading` anchor that no heading of its target page gives. |
| `external-repository-unresolved` | warning | A `repo:<repository-id>/<path>` link into an external repository that has no checkout in `prism.local.yml`. One per repository, however many links point into it; its links are skipped. |
| `stale-page` | warning | A current-state page whose last `verify` entry in `log.md` is older than `wiki-stale-after-days`. |
| `never-verified` | information | A current-state page that no `verify` entry in `log.md` lists. Only `prism wiki lint` and its JSON report it. |
| `missing-<kind>-frontmatter`, `missing-<kind>-kind`, `invalid-<kind>-kind`, `invalid-<kind>-title`, `missing-<kind>-status`, `invalid-<kind>-status`, `invalid-<kind>-sources` | error | The front matter of a topic, research page, plan, direction or roadmap page (`<kind>` is `topic`, `research`, `plan`, `direction` or `roadmap`). |

Lint is mechanical: it checks the form of labels, links and records and never judges
whether evidence supports a claim or whether two claims contradict each other.
Detecting a contradiction is the ingest skill's job.

### Lifecycle lint codes

The codes below belong to the lifecycle pages. Every one is an error unless the table says
otherwise. [Troubleshooting](troubleshooting.md#lint-reports-a-lifecycle-finding) gives the fix for each.

**Status, owner and scope**

| Code | Meaning |
|---|---|
| `invalid-feature-status`, `invalid-feature-owner`, `invalid-status-owner-pairing` | A status or owner outside the sets (`raw` to `released`; `po`, `designer`, `tech-lead`, `dev`, `qa`, `release`, `none`), or a pair the lifecycle does not allow, such as `released` with an owner other than `none`. |
| `unsupported-feature-field`, `unsupported-design-field` | A front matter field the page kind does not carry. |
| `feature-status-not-minimum` | From `in-dev` on, the status differs from the lowest stage over the active apps. |
| `app-row-missing` | The status needs an evidence row that an app lacks. |
| `app-row-ahead-of-status` | A feature before `in-dev` already holds evidence rows; evidence starts at `in-dev`. |
| `app-row-out-of-order` | An app has a row whose prerequisite is missing: a QA row for an app with no delivery evidence, or a `pending` or `failed` Release row without QA coverage. |
| `undeclared-app-row`, `duplicate-app-row` | An evidence row names an app the feature does not list, or an app has more than one authoritative row. |
| `invalid-evidence-row` | A cell of an evidence row has the wrong form: an artifact reference, a basis other than `checked` or `attested`, a missing field. |
| `no-active-app-in-scope` | Every app of the feature is retired. |
| `app-retired-in-scope` | A feature before `released` lists a retired app. |
| `api-surface-without-api-app` | The API surface declares API work and no active app in scope serves an API. |
| `unknown-app-id` | A feature, requirement or design page names an app the workspace does not declare. |
| `pending-revalidation` | A released feature still lists revalidation domains. |

**Acceptance criteria and evidence**

| Code | Meaning |
|---|---|
| `app-without-criteria` | An app in scope is named by no acceptance criterion. |
| `duplicate-criterion-id`, `invalid-applies-to`, `criterion-high-water-invalid` | A criterion ID used twice, a criterion that applies to an app outside the scope, or an ID above `criteria-high-water`. |
| `stale-qa-evidence` | A QA row cites a criterion revision, an artifact or an attempt that is no longer current. |
| `stale-delivery-evidence` | A delivery row cites an API contract that is not the current one. |

**Design**

| Code | Meaning |
|---|---|
| `design-tracks-missing`, `design-tracks-invalid` | From `in-design` on, `design-tracks` is absent or has a value other than `pending`, `done` or `not-applicable`. |
| `design-track-pending` | From `ready-for-dev` on, a track is not settled or `design-reaffirm` is not empty. |
| `design-coverage-incomplete` | The UI track is `done` and no design page covers an app with a UI. |
| `ui-exemption-reason-required` | The UI track is `not-applicable` without a `ui-reason`. |
| `technical-track-required` | The technical track is `not-applicable` while the API surface declares API work. |
| `missing-technical-design`, `technical-design-feature-mismatch` | The technical track is `done` and the feature has no technical design page, or it has more than one or one that names another feature. |
| `test-strategy-incomplete` | The Test strategy of the technical design does not name every acceptance criterion. |
| `api-contract-required`, `api-contract-not-ready`, `delivered-api-contract` | The technical track is `done` with declared API work and no contract, the contract is still a `draft` from `ready-for-dev` on, or it is not `implemented` after every app delivered. |
| `missing-app-requirements`, `pending-board-review`, `unresolved-open-questions` | From `ready-for-dev` on: an app has no requirement page, the advisory review is still `pending`, or a `po`, `designer`, `tech-lead` or `dev` question is open. |
| `done-app-requirement`, `done-advisory-actions` | A released feature has a requirement page that is not `done`, or its advisory review has unchecked required actions. |

**Bugs**

| Code | Meaning |
|---|---|
| `bug-page-invalid` | A bug page has a wrong file name, front matter or section. |
| `invalid-bug-status-owner` | A bug status paired with an owner it does not allow (`open` with `dev`, `fixed` with `qa`, `verified` with `release`). |
| `bug-close-reason-required` | A closed bug without a `close-reason` of `wont-fix: <reason>`, `duplicate` or `promoted`. |
| `duplicate-target-invalid` | The bug a duplicate points to is missing, closed, deferred when it should not be, or does not cover the duplicate. |
| `promoted-bug-unreopened` | A bug promoted to a feature that does not list the bug in `sources` or under Linked bugs. |
| `bug-feature-missing` | A bug names a feature that has no page. |
| `open-bug-blocks-qa` | A bug blocks an app that has a `pending` or `failed` Release row. |

**Release and dependencies**

| Code | Meaning |
|---|---|
| `release-record-invalid` | A release record has malformed front matter, Delivery rows, Rollback section or contract snapshot. |
| `release-row-record-mismatch` | The Release row of a feature or bug disagrees with the record it links on target, version or outcome, or links no record. |
| `cross-app-dependency` | An app requirement depends on a feature or app that is not yet `released`. |
| `dependency-cycle` | Requirement pages or features that wait for each other. |

**Operations and settings**

| Code | Meaning |
|---|---|
| `incident-record-invalid` | An incident page does not follow the format, or names a release record that does not exist. |
| `incident-follow-up-missing` | A follow-up of an incident names no bug or feature page (warning). |
| `invalid-workflow-policy` | `qa-separate-from-dev` in `SETTINGS.md` is neither `true` nor `false`. |
| `invalid-delivery-target` | A `delivery-targets` entry names an unknown app, a kind outside `deployment`, `store`, `artifact` and `other`, or a malformed environment list. |
| `invalid-app-runbook` | An app in this repository declares a `runbook` (its runbook is `<path>/docs/runbook.md`), or an external app's `runbook` is not an https link. |

### Links and sources

Every relative Markdown link in a page and every `sources` entry must resolve. Lint resolves a
link from the page it is written in to a file or folder of the workspace, and reports one that does
not as `broken-link`, with the page, the link and the line. Links in code blocks and inline code,
URLs, images and absolute paths are not checked, and no URL is fetched. A `#heading` anchor is
checked against the headings of its target and is `broken-anchor` when none gives it.

A feature's `sources` entries are workspace paths. A persona, topic, research page, plan,
`direction.md` or `roadmap.md` lists `sources` and a business rule one `source`; these may be URLs or
free text, so only an entry that is a `knowledge/` path (or a `repo:` link) is checked, and a path in the
pending intake queue names the processed path to list instead. Only a broken link to a page of the wiki
gates a lifecycle action, as it always has; the other link findings never block.

A file or folder in an app's external repository is linked as `repo:<repository-id>/<path>`, in a body
link or in `sources`:

```markdown
- **Observed:** The partner app signs in on one screen ([Login](repo:mobile-apps/apps/partner/Login.kt)).
```

`<repository-id>` is a repository of `prism.workspace.yml`, and `workspace` means this repository. Lint
finds the checkout in the untracked `prism.local.yml` ([the workspace model](workspace-model.md#repositories-and-prismlocalyml)).
Without an entry for the repository it reports one `external-repository-unresolved` warning for that
repository and skips its links. With a checkout, a path that is not there is `broken-link`. Lint only asks
whether the path exists: it never reads a file in the checkout, never follows a symlink inside it and never
writes there.

### Freshness and verification

Pages carry no date, so freshness comes from `log.md`. A verification is a log entry whose operation is
`verify`; the pages on its `paths` line were checked against their sources on the entry's date. For each
current-state page, lint takes the latest `verify` entry that lists it. It reports `stale-page` (warning)
when that entry is older than `wiki-stale-after-days` and `never-verified` (information) when there is none,
so an overdue page is not confused with a page that nobody has checked. Records (ADRs and advisory
reviews), `log.md`, `index.md`, `status-board.md`, the schema files and generated files are exempt.
Freshness only asks for a review: it never changes a status and never blocks a lifecycle action or a board
write.

```text
prism wiki verify knowledge/wiki/topics/pricing.md roadmap.md --evidence https://example.com/pricing --by Riley
```

The command appends one entry and changes nothing else:

```text
## 2026-10-06 verify | pricing.md, roadmap.md
- paths: knowledge/wiki/topics/pricing.md, knowledge/wiki/roadmap.md
- evidence: https://example.com/pricing
- by: Riley
```

A page is named from the workspace root or from the wiki (`topics/pricing.md`). The command refuses a path
outside `knowledge/wiki`, a page that does not exist and a page that is not a current-state page, and
writes nothing when it refuses any of them. It appends the way the board does: it rejects a symlink or
reparse point on the path, swaps the log in atomically only while it is unchanged, and reads it again when
another writer got in between. Through the connected board, the `verify-pages` skill records the same entry:
the agent names the pages it read in `read_revisions`, each with the digest `read_workspace` returned, and a
human confirms the preview. Applying is refused as stale when a verified page changed after the preview.

### Evidence labels

A claim on a feature, persona, business-rule, design, app-requirement, API-contract, topic,
research, plan, direction or roadmap page starts with a bold run-in label: `**Decided:**`, `**Observed:**`, `**Proposed:**`,
`**Assumed:**` or `**Unknown:**`.

```markdown
- **Observed:** Reviewers keep outcomes in informal notes ([review brief](../../intake/processed/2026-10-06-review-brief/brief.md)).
- **Assumed:** A review covers exactly one document.
```

A Decided or Observed claim links its evidence: a processed intake item, a record or a URL.
A feature's `## Open questions` table is its Unknown form. When a later source changes a
claim, the item is replaced in place and the log entry lists the changed paths and the new
evidence.

### Decisions and supersession

An ADR is a record. A decision is replaced by a new ADR, in one operation: the new ADR has
`supersedes: ADR-NNN`; the old ADR gets `status: superseded` and `superseded-by: ADR-MMM`
and its body stays unchanged; every current-state page that relied on the old decision is
updated to link the new one; one log entry lists the paths. The user confirms the operation
before it writes. Through the connected board, `ingest` creates the new ADR and changes only
the status fields of the old one; it never rewrites a feature, persona or business rule, so
those pages are updated by their own operation, and lint lists each one that still links the
old ADR as `superseded-decision-cited`.

### Raw sources and conflicts

A raw source is a folder `knowledge/intake/pending/YYYY-MM-DD-slug/`; the date is the day
it was captured. `po-intake`, `design-intake` and `ingest` move it, under the same name, to
`knowledge/intake/processed/YYYY-MM-DD-slug/` with a `MANIFEST.md`. A processed item is
immutable: new or corrected material is a new dated folder. Agent review packets and agent
outputs are archived the same way (see `knowledge/intake/README.md` in a generated
workspace).

When an incoming source contradicts an existing page, the ingest skill moves the folder to
`knowledge/intake/quarantined/YYYY-MM-DD-slug/` and writes a `CONFLICT.md` there:

```markdown
---
status: open
---

# Conflict: payout cadence

## Existing claim
- **Claim:** The page says payouts settle once per day.
- **Scope:** Checkout payouts for the web app.
- **Evidence:** [F-001](../../../wiki/features/F-001-checkout.md)

## Incoming claim
- **Claim:** The note says payouts settle twice per day.
- **Scope:** Checkout payouts for the web app.
- **Evidence:** [notes.md](notes.md)
```

The existing page is not touched. A human decides, makes the chosen edit to the page,
sets `status: resolved` and adds a `## Resolution` section that links the changed pages.
The resolved record stays in `quarantined/`.

## Ingest: Any Role, Any Page Kind

`po-intake` and `design-intake` stay the role-specific entry points for feature requests and
design handoffs. `ingest` is the general operation: any role can run it on a pending folder,
and it can write any page kind: a topic, research page, plan, `direction.md`, `roadmap.md`,
persona, business rule, decision, technical design page, new feature, bug or incident record.

1. It reads `index.md`, finds the pages the source touches and reads them.
2. It compares every claim with those pages. A contradiction is quarantined with a
   `CONFLICT.md` and nothing else is written.
3. It shows an interpretation summary and waits for the user's confirmation (on the connected
   board, together with the preview).
4. It writes the pages. A topic, research page, plan, direction or roadmap page is created, or
   replaced in place when it exists. A persona, business rule, decision, feature or bug is
   created and never rewritten; a new feature follows the `po-intake` rules (`status: raw`,
   `owner: po`, the five required sections), and a new bug is `open` + `dev` with empty
   evidence sections. A new decision may supersede an older one. A technical design page is
   created, or replaced in place while the feature's technical track is `pending` or the feature
   has no tracks yet. An incident record is created, or updated within its format: a status
   step, appended Timeline lines, added follow-ups and releases, and, until it is `resolved`, a
   filled Cause, Mitigation, Resolution and Follow-ups.
5. The board adds or replaces the index line of every page, adds the status board row of a
   new feature, updates the Bugs and Operations tables and appends the log entry.
6. The folder moves to `processed/` with a `MANIFEST.md` that lists every page by its full
   relative path and, where it has one, its canonical ID.

The connected board validates this as `po-intake` does, and adds the rules for the new kinds
(see the rejected-proposals table in [shared-board.md](shared-board.md)). `ingest` cannot write
design, requirement, API-contract, release or advisory pages, settle a design track or change a
bug; `tech-design-done` and `bug-update` do that.

## Feature Lifecycle Actions

Lifecycle actions are named, feature-only workflows. Each resolves one exact feature path,
reads the current source and linked context, prepares a complete proposal with the exact
write set, and writes only after the right person confirms it. The registry in
[`ACTIONS.md`](../template/knowledge/wiki/ACTIONS.md) is the source of truth; `D` is the
design owner of the scope (`designer` when an active app has a UI, otherwise `tech-lead`).

| Action | Source | Destination | Approver role |
|---|---|---|---|
| `po-specify` | `raw` + `po` | `specified` + `po` | `po` |
| `po-handoff` | `specified` + `po` | `ready-for-design` + `D` | `po` |
| `design-start` | `ready-for-design` + `D` | `in-design` + `D` | `D` |
| `design-ui-done` | `ready-for-design` or `in-design` + `D` | `in-design` + `D` | `designer` |
| `tech-design-done` | `ready-for-design` or `in-design` + `D` | `in-design` + `D` | `tech-lead` |
| `design-handoff` | `ready-for-design` or `in-design` + `D` | `ready-for-dev` + `dev` | `D`, plus `designer` or `tech-lead` for a track it settles |
| `dev-start` | `ready-for-dev` + `dev` | `in-dev` + `dev` | `dev` |
| `dev-done` | `ready-for-dev` or `in-dev` + `dev` | the minimum of the app stages: `in-dev` + `dev`, or `ready-for-qa` + `qa` | `dev` |
| `dev-return-spec`, `dev-return-design` | `ready-for-dev` or `in-dev` + `dev` | `specified` + `po`, or `in-design` + `D` | `dev` |
| `qa-verify` | `in-dev`, `ready-for-qa` or `in-qa` | the minimum of the app stages | `qa` |
| `qa-pass` | as `qa-verify` | the minimum of the app stages: `ready-for-release` + `release` once every app has passed | `qa` |
| `qa-fail` | as `qa-verify`, or `ready-for-release` | `in-dev` + `dev` | `qa` |
| `qa-return-spec`, `qa-return-design` | as `qa-fail` | `specified` + `po`, or `in-design` + `D` | `qa` |
| `release-done` | `in-dev` up to `ready-for-release` | the minimum of the app stages: `released` + `none` once every app is released | `release` |
| `release-return-dev` | as `release-done` | `in-dev` + `dev` | `release` |
| `release-rollback`, `release-redeploy` | `in-dev` up to `released` | unchanged | `release` |
| `reopen-spec`, `reopen-design`, `reopen-dev` | `released` + `none` | `specified` + `po`, `in-design` + `D`, or `in-dev` + `dev` | `po`, `D`, `dev` |
| `scope-edit` | `ready-for-dev` up to `released` | the minimum of the app stages after the edit | `po` |

`bug-update` moves one bug page and has its own table in
[`bugs/_FORMAT.md`](../template/knowledge/wiki/bugs/_FORMAT.md). Each gated action needs a human
who holds the approver role; see [Approval](#approval).

### Specification and design

`po-specify` reads the raw body and authors the required structured sections, carrying
supported facts forward and keeping unknowns as explicit questions owned by `po`, `designer`,
`tech-lead` or `dev`. Every acceptance criterion gets an ID (`AC-1`) and the apps that verify
it (`[backend, web]`, or `[integration: backend, web]` for a criterion that two apps verify
together). It must show the body rather than performing a status-only write. `po-handoff` is
the stricter specified-to-design handoff and checks the factual Summary, User story, acceptance
criteria, matching app scope, PO questions and the advisory outcome.

Design has two tracks, `ui` and `technical`, each `pending`, `done` or `not-applicable`:

- `design-ui-done` settles the UI track: design pages whose `apps` together cover every active
  app with a UI, or `not-applicable` with a `ui-reason`. Only the designer's explicit exemption
  makes the track `not-applicable` for an app whose `has-ui` is `unknown`.
- `tech-design-done` settles the technical track: a technical design page with every section
  filled and a Test strategy that names every criterion ID, and, when the API surface declares
  API work, the agreed API contract `api-contracts/F-XXX.md`. The contract is written only from
  the API surface, and the person confirming the preview is the agreement. A track is
  `not-applicable` only with a `technical-reason` and no declared API work.
- `design-handoff` needs both tracks settled and `design-reaffirm` empty, leaves exactly one
  requirement page per app, and may settle a track in the same confirmation.
- A change to the pages of a settled track sets that track back to `pending` and lists the
  other settled track in `design-reaffirm`. From `ready-for-dev` on, the track pages are locked.

### Implementation and QA

`dev-done` records, for each app it names, one `## Delivery evidence` row:
`App | Artifact | Contract | Implementation | Tests | Basis`. The artifact is `version:`,
`build:`, `image:`, `package:` or `commit:` with its form; the contract is `none` or
`F-XXX@v<version>:c1:<digest>`; implementation and tests are substantive references; the basis
is `checked` when the agent verified the references and `attested` when the approving human
vouches for them. A reference the agent cannot check is `attested`, never invented. The feature
moves to `ready-for-qa` once every active app has a row.

`qa-verify` records `## QA verification` rows,
`Row | Criteria | Method | Artifact | Environment | Attempt | Result | Evidence | Basis`: one row
per app, or one `integration:app+app` row for the criteria that two apps verify together. A row
cites each criterion with its revision (`AC-1@v1:<digest>`), the delivered artifact, the
attempt (`qa-<n>`) and an environment (`local`, `ci` or an environment of the app's delivery
target). `qa-pass` passes the apps it names when every criterion that lists them has a passing
row on the current artifact in the current attempt, and no blocking bug remains. It adds a
`pending` Release row per app and can carry the missing QA rows, so a clean run is one approval.
`qa-fail` sends the named apps back to development; their delivery, QA and Release rows move to
Evidence history and the attempt advances.

### Release

`release-done` settles the Release row of each app it releases (`released` or `failed`), ships
the verified bugs of those apps and writes one release record. A row is
`App | Target | Version | Attempt | Outcome | Record | Basis`: the target comes from
`delivery-targets` in `SETTINGS.md`, the version is the artifact QA verified, the attempt is
`release-<n>`, and the record links `releases/REL-XXX.md`. A release is refused while a bug
blocks the app, while QA no longer covers it, or while a feature it depends on is not released
or in the same release. A failed delivery goes back with `release-return-dev`. `release-rollback`
binds to the current delivery of an app and target (the highest-numbered record with a
`released` row for it), and `release-redeploy` retries a rollback or a failed redeploy; each adds
a record and changes no page. A staging row (an environment of the target, attempt `—`) is
informational and never counts for a stage.

### Bugs

`bug-update` performs one action on one bug page: triage, scope, start, fixed, verified,
reverify, reject, close, defer or reopen. The roles are `dev` for fixing, `qa` for verifying,
rejecting and closing a duplicate, and `po` for `wont-fix`, `promoted` and deferral. A bug is
`released` only inside `release-done`. A fix cannot be recorded while an app of the bug's
feature is in its QA cycle: the app returns first with `qa-fail`, citing the bug. A bug whose
fix changes agreed requirements or contracts is closed `promoted` and continues as a feature.

### Returns, reopening and scope

- A return or a reopen appends exactly one `## Evidence history` entry
  (`### YYYY-MM-DD - <action>`), copies each removed row verbatim under `- Archived evidence:`,
  lowers the requirement pages and the contract it names, and sets `revalidation` (feature
  domains `specification`, `design`, `technical-design`) and `app-revalidation` (per app
  `implementation`, `tests`, `qa`, `release`). A domain is cleared only by fresh evidence in the
  same write.
- `feature-reopen F-XXX [specified|in-design|in-dev]` selects the route from the state of the
  feature: from `released` the three routes are reopens; with an app in QA, `specified` and
  `in-design` are the QA returns; otherwise they are the returns from implementation. It is not a
  generic status setter. `in-dev` is valid only from `released`, and reopens only the apps that
  change.
- A feature with a released app cannot go back to specification or design
  (`partial_release_requires_new_feature`): a changed requirement or contract goes in a new
  feature, and an implementation defect in a bug.
- `feature-scope` edits the `apps` list and the App scope section together. Before
  `ready-for-dev` it is an ordinary write; from `ready-for-dev` on it is `scope-edit`, which
  only removes apps, derives the new criteria and archives the removed app's rows. Adding an app
  there is refused (`scope_stage_unavailable`): return the feature to design.

The complete protocol and formats are in
[`knowledge/wiki/LIFECYCLE.md`](../template/knowledge/wiki/LIFECYCLE.md), and the action registry in
[`knowledge/wiki/ACTIONS.md`](../template/knowledge/wiki/ACTIONS.md).

### Approval

An agent proposes a gated action with `preview_skill`; it waits in the board's proposal list;
a human who holds the approver role reviews the exact changes and approves or declines it in
the browser board. `po-handoff`, `design-start` and `dev-start` are human-direct: the human
previews and applies them in the board without an agent. The board checks the role at preview,
at apply and at recovery. [Shared board](shared-board.md#roles-proposals-and-approval) describes
the flow, and [the model](prism-model.md#approval-agents-propose-humans-approve) the reasons.

## `WIKI_REPORT.md`

`knowledge/wiki/WIKI_REPORT.md` is a generated orientation summary.

It is:

- generated on demand
- written only by `feature-status`
- read-only
- ignored from version control in generated projects
- useful for quick orientation before deeper reading

It is not:

- the source of truth
- a hand-maintained document
- a replacement for `index.md`, `status-board.md` or feature pages

## `SETTINGS.md`

`knowledge/wiki/SETTINGS.md` is the canonical home for project-level wiki behavior
settings and for the workflow policy. All keys live in its front matter:

```markdown
---
wiki-stale-after-days: 14
qa-separate-from-dev: false
delivery-targets:
  backend: { kind: deployment, target: production, environments: [staging] }
---
```

- `wiki-stale-after-days` is the number of days a verification stays fresh. Commands that use
  it fall back cleanly to `14` if the file is missing, the key is missing, or the value is
  malformed. Freshness is derived from `log.md`, never from a date on the page (see
  [Freshness and verification](#freshness-and-verification)), and `status` reports the setting.
- `qa-separate-from-dev` is `true` or `false` (absent means `false`). When `true`, the board
  refuses a QA approval from a grant that produced, recovered or repaired the evidence it
  verifies. It separates grants, not proven people. Any other value is
  `invalid-workflow-policy`, and a gated action that reads the policy is refused until it is
  fixed (`invalid_policy`). The board never writes this file.
- `delivery-targets` maps an app ID to `{ kind, target, environments }`. `kind` is
  `deployment`, `store`, `artifact` or `other`; what an entry leaves out comes from the app's
  stack (`deployment` and `production` for `spring-backend`, `nextjs-web` and
  `python-agent-service`, `store` and `play-store` for `android-compose`, `store` and
  `app-store` for `ios-swiftui`). An `other` app declares its own. Changing a target affects
  only future releases.

Source integrity errors, including a broken link to a wiki page, and action-specific
prerequisites gate lifecycle requests; freshness findings, broken `sources` entries, broken
anchors and external links never do.

## Start Here By Role

An action that advances a status needs a board grant with the role of the stage
(`prism board grant NAME --kind human --write --role qa`). The flows below name the skill
each role runs; a gated skill is proposed by the agent and approved by that person in the board.

### If you are a Product Owner

Typical flow:

1. place raw notes in a dated folder, `knowledge/intake/pending/YYYY-MM-DD-slug/`
2. run `po-intake`
3. review the generated feature pages and open questions
4. use `po-clarify` to answer PO-owned questions
5. use `po-specify` on a raw feature page to author its structured draft
6. use `po-handoff` in the board when the feature is ready for design
7. decide bug dispositions (`wont-fix`, `promoted`, deferral) with `bug-update`

Helpful read/query commands:

- `feature-status` for the full lifecycle board
- `wiki-show F-XXX` for one feature
- `wiki-owner po` for PO-owned open work
- `wiki-blockers` when a feature seems stuck

### If you are a Designer or Tech Lead

Typical flow:

1. inspect the feature with `wiki-show F-XXX`
2. attach design artifacts with `design-intake`
3. resolve open design questions with `design-clarify`
4. start work with `design-start` in the board after the PO handoff
5. settle the UI track with `design-ui-done` (designer) and the technical track with
   `tech-design-done` (tech lead)
6. use `design-handoff` when both tracks are settled and the feature is ready for development

Helpful read/query commands:

- `wiki-owner designer` or `wiki-owner tech-lead`
- `wiki-app <app-id>`
- `wiki-query "text"` for targeted product context search

### If you are a Developer

Typical flow:

1. read `WIKI_REPORT.md` when present, or run `feature-status`
2. run `prep-sprint` to see what is actually ready
3. use `wiki-show F-XXX` to assemble focused implementation context
4. read app requirements, the technical design and the API contract before implementation
5. use `dev-clarify` to answer dev-owned open questions, which block `dev-start`
6. use `dev-start` in the board to take confirmed ready-for-dev work
7. use `dev-done` for each app whose artifact, implementation and tests are delivered
8. use `feature-reopen` with a return route when the specification or the design turns out to be wrong
9. fix bugs with `bug-update`

Helpful read/query commands:

- `wiki-blockers`
- `wiki-owner dev`
- `wiki-app <app-id>`
- `wiki-query "text"`

### If you are QA

Typical flow:

1. run `wiki-owner qa` for the features at `ready-for-qa` or `in-qa` and the bugs at `fixed`
2. read the acceptance criteria and the Test strategy of the technical design
3. record results with `qa-verify`, one row per app or integration, against the delivered artifact
4. file the defects you find as bugs in the same proposal
5. use `qa-pass` when every applicable criterion is verified and no bug blocks the app
6. use `qa-fail` to send an app back to development, or `feature-reopen` (`specified` or
   `in-design`) to send the whole feature back
7. verify fixes with `bug-update`

### If you are Release

Typical flow:

1. run `wiki-owner release` for the features at `ready-for-release` and the bugs at `verified`
2. deliver the artifact QA verified to the app's delivery target
3. record the outcome with `release-done`, which writes the release record
4. use `release-return-dev` when the delivery failed and needs development
5. use `release-rollback` and `release-redeploy` to record a rollback and a new delivery

### Operation

- an incident report goes through `ingest` into `knowledge/wiki/incidents/`; its follow-ups are bugs or features
- a defect report goes through `ingest` into `knowledge/wiki/bugs/`
- the Operations table of `status-board.md` shows, per app, the released features, the latest
  release record and its outcome, the open bugs and the open incidents

## Orientation and Read/Query Commands

The current wiki usability layer includes:

- `feature-status`
- `prep-sprint`
- `lint-wiki`
- `wiki-show`
- `wiki-blockers`
- `wiki-query`
- `wiki-owner`
- `wiki-app`

General workflow:

1. Read `WIKI_REPORT.md` first when present.
2. If it is absent, run `feature-status`.
3. Use the read/query commands for focused drill-down.
4. Use the lifecycle commands when you are actually changing project state.

## `feature-status`

Purpose:

- show the full feature pipeline
- refresh `WIKI_REPORT.md`

It is the only command that writes `WIKI_REPORT.md`.

It should produce:

- pipeline grouped by lifecycle stage, with the stage of each app of a feature from `in-dev` on
- open questions by owner
- the bugs that are neither `released` nor `closed`
- blocker snapshot
- `WIKI_REPORT.md` with:
  - project summary
  - lifecycle stage counts
  - advisory review snapshot
  - open questions by owner
  - blocker snapshot
  - recently changed wiki pages
  - structural health pointer to `lint-wiki`
  - suggested next actions

## `prep-sprint`

Purpose:

- give a developer-focused readiness view across the wiki

It is read-only. It should use `WIKI_REPORT.md` when present for fast orientation, then
confirm readiness from the underlying wiki files.

## `lint-wiki`

Purpose:

- inspect the wiki for structural issues and blocker categories

It:

- reports deterministic wiki diagnostics in the response by default, including broken links and sources, `stale-page` and `never-verified`
- writes a dated lint report to the wiki directory (`knowledge/wiki/lint-YYYY-MM-DD.md`) only when explicitly requested
- appends to `knowledge/wiki/log.md` only when explicitly requested
- never writes or refreshes `WIKI_REPORT.md`

If `WIKI_REPORT.md` is missing or stale, `lint-wiki` should tell the user to rerun
`feature-status`.

## `wiki-show`

Purpose:

- assemble a focused feature context bundle for one feature

Example:

```text
Feature: F-012 - Saved Checkout
Status: ready-for-dev
Owner: dev
Advisory review: done

Summary:
Customers can reuse a saved shipping address and payment preference during checkout.

Open questions:
- Designer: What does the invalid saved address state look like? [open]
- Dev: Should guest checkout support saved addresses later? [resolved: no, account only]

Linked context:
- Design: knowledge/wiki/design/F-012-saved-checkout.md
- API contract: knowledge/wiki/api-contracts/F-012.md
- Board review: knowledge/wiki/advisory/F-012-review.md
- Business rules:
  - BR-004-checkout-address-validation.md
  - BR-011-payment-method-eligibility.md

App requirements:
- backend: in-progress
- mobile-ios: pending
- mobile-android: pending
- web: pending

Current blockers:
- api-contract-not-ready: mobile-ios app requirements depend on the API contract status changing from draft to agreed
- design-track-pending: the UI design track is pending; the design pages do not define the expired payment-method state

Suggested next action:
Run design-clarify or update the design page before active implementation begins.
```

Missing-feature example:

```text
Feature: F-099
Status: error

Problem:
No feature file matching F-099 was found in knowledge/wiki/features/.

Next step:
Check the feature ID or run feature-status to inspect the current board.
```

Partial-state example:

```text
Feature: F-012 - Saved Checkout
Status: partial
Owner: dev
Advisory review: done

Summary:
Feature file found, but linked implementation context is incomplete.

Missing linked context:
- No design page found
- No app requirements found for mobile-ios

Next step:
Create the missing linked files before treating this feature as fully implementation-ready.
```

## `wiki-blockers`

Purpose:

- compute the current blockers across the wiki using the canonical blocker vocabulary

Canonical blocker categories:

- `pending-board-review`
- `design-track-pending`
- `missing-app-requirements`
- `unresolved-open-questions`
- `api-contract-not-ready`
- `cross-app-dependency`
- `feature-status-not-minimum`
- `app-row-missing`
- `stale-qa-evidence`
- `stale-delivery-evidence`
- `open-bug-blocks-qa`

Example:

```text
Blockers summary:
- 2 pending board review
- 1 pending design track
- 3 missing app requirements
- 2 unresolved open questions

Blocked features:

F-009 - Subscription Pause
- Category: pending-board-review
- Status: ready-for-design
- Why blocked: advisory-review is still pending
- Next step: run board-review F-009 or explicitly skip with a documented reason

F-012 - Saved Checkout
- Category: missing-app-requirements
- Status: ready-for-dev
- Why blocked: no app requirements page exists for mobile-ios
- Next step: generate or write the missing app requirement before implementation continues
```

No-blockers state:

```text
Blockers summary:
- 0 pending board review
- 0 pending design track
- 0 missing app requirements
- 0 unresolved open questions

Blocked features:

No current blockers found.
```

Malformed-page example:

```text
Blockers summary:

Problem:
One or more wiki pages are malformed, so blockers could not be computed reliably.

Malformed pages:
- knowledge/wiki/features/F-099-broken.md

Next step:
Repair the malformed pages, then rerun wiki-blockers.
```

## `wiki-query`

Purpose:

- search across the wiki for relevant pages using retrieval-assisted synthesis

It is not a numeric-ranking search engine. It should:

- read `index.md` first: the index lines that contain the query name their pages, and those
  pages come first (`prism wiki search` reports them with their `index_line`, and
  `index_match_count` counts them)
- then search the wiki files
- group candidates by match class
- return a compact typed result set

Example:

```text
Query: offline checkout

Candidate matches:

1. F-012 - Saved Checkout
   Type: feature
   Status: ready-for-dev
   Match class: title/heading match
   Relevant sections:
   - Summary
   - Open questions
   - API surface

2. BR-004 - Checkout Address Validation
   Type: business-rule
   Related feature: F-012
   Match class: body-text match
   Relevant sections:
   - Rule
   - Rationale
```

If the result set is too broad, it should return a refinement prompt instead of pretending
the results are coherent.

No-results example:

```text
Query: offline checkout

No matches found.

Next step:
Try a broader term, a feature ID, or run feature-status to inspect current feature names.
```

Broad-query example:

```text
Query: auth

Too many broad matches to summarize reliably in one response.

Suggested refinement:
- /wiki-query "password auth"
- /wiki-query "OAuth callback"
- /wiki-query "login flow"
```

## `wiki-owner`

Purpose:

- show pending work, open questions and bugs for one owner role

Supported values:

- `po`
- `designer`
- `tech-lead`
- `dev`
- `qa`
- `release`
- `none`

Example:

```text
Owner view: designer

Open questions:
- F-012 - What does the invalid saved address state look like?
- F-014 - What is the empty state for alert history?

Waiting on designer:
- F-012 - Saved Checkout [ready-for-design]
- F-014 - Nutrition Goal Alerts [in-design]

Bugs:
- none

Suggested next actions:
- Run design-intake for F-012
- Resolve open questions on F-014 before design-handoff
```

Invalid-owner example:

```text
Owner view: ops

Problem:
`ops` is not a supported owner value.

Supported values:
- po
- designer
- tech-lead
- dev
- qa
- release
- none
```

## `verify-pages`

Purpose:

- record that current-state pages were checked against their sources

It:

- compares each page's labeled claims with its sources, and verifies only pages that are still true
- appends one `verify` entry to `knowledge/wiki/log.md`, through the board's `preview_skill` and `apply`, with `prism wiki verify`, or by hand in the log format
- never edits a page, an index line or a status board row, and never changes a status or an owner

## `wiki-app`

Purpose:

- show the active and ready features affecting one app

Supported identifiers (the app IDs of the workspace; a default generated workspace has these):

- `backend`
- `mobile-android`
- `mobile-ios`
- `web`

Example:

```text
App view: mobile-ios

Active features:

F-012 - Saved Checkout
- Feature status: ready-for-dev
- Advisory review: done
- App requirement: pending
- API contract: agreed
- Blockers:
  - Design does not define expired payment-method handling

F-014 - Nutrition Goal Alerts
- Feature status: in-design
- Advisory review: pending
- App requirement: not created
- API contract: not applicable
- Blockers:
  - Board review still pending
  - No app requirements page yet
```

Invalid-app example:

```text
App view: ios

Problem:
`ios` is not an app of this workspace.

Supported identifiers (the app IDs of the workspace; a default generated workspace has these):
- backend
- mobile-android
- mobile-ios
- web
```

## Related Docs

- [prism-model.md](prism-model.md)
- [ai-surfaces.md](ai-surfaces.md)
- [wiki-validation.md](wiki-validation.md)
- [generated-projects.md](generated-projects.md)

## CLI result codes

`wiki show` returns exit code 3 when the feature is missing.
`wiki transition-preflight` returns 0 for a supported, ready transition and 3
for blocked or unknown results, in both human and JSON modes. Empty searches
remain successful with exit code 0. These commands only inspect state.
