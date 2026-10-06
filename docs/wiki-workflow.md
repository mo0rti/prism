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
- `knowledge/wiki/design/`
- `knowledge/wiki/app-requirements/`
- `knowledge/wiki/business-rules/`
- `knowledge/wiki/api-contracts/`
- `knowledge/wiki/advisory/`
- `knowledge/wiki/topics/`, `research/` and `plans/`, and the pages `direction.md` and `roadmap.md`

`knowledge/wiki/index.md` lists every page, one line each; `knowledge/wiki/status-board.md`
is the feature status board. The lifecycle operations create and refine that state. The
read/query operations help agents and humans navigate it.

## Page Kinds

The wiki has homes for general knowledge beside the feature pipeline. Each kind has a
format that `SCHEMA.md` defines, and the three folders also carry a `_FORMAT.md`.

| Kind | Where | Holds |
|---|---|---|
| Topic | `topics/[slug].md` | A synthesis of what several sources and pages say about one subject. |
| Research | `research/[slug].md` | The current answer to one question, and the gaps that remain. |
| Plan | `plans/[slug].md` | The current status of one plan: goal, status, next steps, blockers. It keeps no history. |
| Direction | `direction.md` | The current direction and the principles behind it. |
| Roadmap | `roadmap.md` | What comes next. A date about the world, such as a launch date, may appear in it. |

Every one starts with front matter that carries `kind` (the kind of its folder), `sources`
(a list of the processed intake items, records or URLs it rests on) and, for a topic,
research page or plan, a `title` and a `status` (topic: `draft` or `current`; research:
`open` or `concluded`; plan: `proposed`, `active`, `paused`, `done` or `dropped`). A page
carries no date about itself and labels its claims with the evidence labels below.
`prism wiki lint` checks the front matter of each kind: for example `invalid-topic-kind`,
`invalid-plan-status`, `missing-research-frontmatter` and `invalid-roadmap-sources`.

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

`status-board.md` is the feature status board, a dedicated view with the columns
`| ID | Feature | Status | Owner | Board Review |`. The board merges its rows with the same
guarantees as before: unrelated rows survive a concurrent write, and a row that changed
after a preview is a conflict.

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
(`date`), an advisory review (`reviewed`), each entry under a feature's
`## Reopen history` and a processed intake item (its `YYYY-MM-DD-slug` folder name). A
record is never rewritten, except for its status fields. A source or a decision that
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
| `missing-schema-version` | error | `SCHEMA.md` or `LIFECYCLE.md` without the front matter `schema-version: 1`. |
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
| `malformed-status-board` | error | `status-board.md` cannot be read or has no status table. |
| `feature-missing-from-status-board` | error | A feature page with no row in `status-board.md`. |
| `status-board-missing-feature` | error | A `status-board.md` row with no feature page. |
| `status-board-frontmatter-drift` | error | A row's status, owner or board review differs from the feature's front matter. |
| `broken-link` | error | A relative Markdown link or a `sources` entry that does not resolve to an existing file or folder, that leaves the workspace, or is a malformed or undeclared `repo:` link, or a `repo:` link whose target is missing from a resolved checkout. The finding names the page, the link and the line. |
| `broken-anchor` | warning | A `#heading` anchor that no heading of its target page gives. |
| `external-repository-unresolved` | warning | A `repo:<repository-id>/<path>` link into an external repository that has no checkout in `prism.local.yml`. One per repository, however many links point into it; its links are skipped. |
| `stale-page` | warning | A current-state page whose last `verify` entry in `log.md` is older than `wiki-stale-after-days`. |
| `never-verified` | information | A current-state page that no `verify` entry in `log.md` lists. Only `prism wiki lint` and its JSON report it. |
| `missing-<kind>-frontmatter`, `missing-<kind>-kind`, `invalid-<kind>-kind`, `invalid-<kind>-title`, `missing-<kind>-status`, `invalid-<kind>-status`, `invalid-<kind>-sources` | error | The front matter of a topic, research page, plan, direction or roadmap page (`<kind>` is `topic`, `research`, `plan`, `direction` or `roadmap`). |

Lint is mechanical: it checks the form of labels, links and records and never judges
whether evidence supports a claim or whether two claims contradict each other.
Detecting a contradiction is the ingest skill's job.

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
persona, business rule, decision or new feature.

1. It reads `index.md`, finds the pages the source touches and reads them.
2. It compares every claim with those pages. A contradiction is quarantined with a
   `CONFLICT.md` and nothing else is written.
3. It shows an interpretation summary and waits for the user's confirmation.
4. It writes the pages. A topic, research page, plan, direction or roadmap page is created, or
   replaced in place when it exists. A persona, business rule, decision or feature is created
   and never rewritten; a new feature follows the `po-intake` rules (`status: raw`,
   `owner: po`, the five required sections). A new decision may supersede an older one.
5. The board adds or replaces the index line of every page, adds the status board row of a
   new feature and appends the log entry.
6. The folder moves to `processed/` with a `MANIFEST.md` that lists every page by its full
   relative path and, where it has one, its canonical ID.

The connected board validates this as `po-intake` does, and adds the rules for the new kinds
(see the rejected-proposals table in [shared-board.md](shared-board.md)).

## Feature Lifecycle Actions

Lifecycle actions are named, feature-only workflows. They resolve one exact
feature path, read the current source and linked context, prepare a complete
proposal, and write only after the user confirms the full write set.

| Action | Source | Destination |
|---|---|---|
| `po-specify` | `raw` + `po` | `specified` + `po` |
| `po-handoff` | `specified` + `po` | `ready-for-design` + `designer` |
| `design-start` | `ready-for-design` + `designer` | `in-design` + `designer` |
| `design-handoff` | `in-design` + `designer` | `ready-for-dev` + `dev` |
| `dev-start` | `ready-for-dev` + `dev` | `in-dev` + `dev` |
| `dev-done` | `in-dev` + `dev` | `done` + `none` |
| `reopen-spec` | `done` + `none` | `specified` + `po` |
| `reopen-design` | `done` + `none` | `in-design` + `designer` |
| `reopen-dev` | `done` + `none` | `in-dev` + `dev` |

Use `feature-reopen F-XXX [specified|in-design|in-dev]` to select one reopen
route. It is not a generic status setter. `po-specify` reads the raw body and
authors the required structured sections, carrying supported facts forward and
keeping unknowns as explicit questions owned by `po`, `designer`, or `dev`. If
the raw body is already structured, it may be verified and preserved; otherwise
the missing sections are authored. It must show and confirm the body rather than
performing an unverified status-only write. `po-handoff` remains the stricter
specified-to-design handoff and checks factual Summary, User story, acceptance
criteria, matching app scope, PO questions, and advisory outcome.

`design-handoff` requires design evidence for apps with a UI (`has-ui`) unless the feature
frontmatter has `design: not-applicable` and a nonblank
`design-exemption-reason`, with the user's explicit confirmation in the final
handoff preview. Non-UI features do not need a design page or exemption. When the
feature's API surface declares API work and no API contract covers it yet,
`design-handoff` also creates `api-contracts/F-XXX.md` at `agreed`, written only from
that API surface; the person confirming the handoff preview is the agreement. A
`revalidation` list records domains invalidated by a confirmed reopen;
downstream actions treat those domains as active until fresh evidence is
verified and explicitly cleared.

`dev-done` means shipped for every declared app. The feature must have one
substantive, verifiable `## Delivery evidence` row per declared app with
Implementation and Tests references and a `Release` cell that is release
evidence (`release:`, `tag:` or `deployment:` and a URL or record path) or a
delivery attestation (`attested by <Name>:` and a URL or path), plus complete
applicable requirements and API contracts. A commit or pull request proves
which code changed, not that it shipped. File presence and lint alone are not shipment
evidence. A partial app remains `in-dev`.

Reopen previews record the reason, impact, route, affected apps/artifacts,
and prior completion/release evidence. Confirmation appends that record to
`## Reopen history`, removes prior active Delivery evidence so it cannot satisfy
a future Done check, sets route-specific revalidation domains, and names exact
affected requirement/API status invalidations. Unaffected evidence is preserved
only when explicitly reaffirmed. Shared API contracts are never reset in bulk.
The complete protocol and formats are in
[`knowledge/wiki/LIFECYCLE.md`](../template/knowledge/wiki/LIFECYCLE.md).

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
settings.

The setting:

```markdown
---
wiki-stale-after-days: 14
---

# Wiki Settings

Project-level settings for wiki read/query behavior.
```

Commands that use this setting must fall back cleanly to `14` if the file is missing, the
key is missing, or the value is malformed.

`wiki-stale-after-days` is the number of days a verification stays fresh; freshness is derived from
`log.md`, never from a date on the page (see [Freshness and verification](#freshness-and-verification)),
and `status` reports the setting. Source integrity errors, including a broken link to a wiki page, and
action-specific prerequisites gate lifecycle requests; freshness findings, broken `sources` entries,
broken anchors and external links never do.

## Start Here By Role

### If you are a Product Owner

Typical flow:

1. place raw notes in a dated folder, `knowledge/intake/pending/YYYY-MM-DD-slug/`
2. run `po-intake`
3. review the generated feature pages and open questions
4. use `po-clarify` to answer PO-owned questions
5. use `po-specify` on a raw feature page to author its structured draft
6. use `po-handoff` when the feature is ready for design

Helpful read/query commands:

- `feature-status` for the full lifecycle board
- `wiki-show F-XXX` for one feature
- `wiki-owner po` for PO-owned open work
- `wiki-blockers` when a feature seems stuck

### If you are a Designer

Typical flow:

1. inspect the feature with `wiki-show F-XXX`
2. attach design artifacts with `design-intake`
3. resolve open design questions with `design-clarify`
4. start work with `design-start` after the PO handoff
5. confirm app implications in the wiki
6. use `design-handoff` when the feature is ready for development

Helpful read/query commands:

- `wiki-owner designer`
- `wiki-app <app-id>`
- `wiki-query "text"` for targeted product context search

### If you are a Developer

Typical flow:

1. read `WIKI_REPORT.md` when present, or run `feature-status`
2. run `prep-sprint` to see what is actually ready
3. use `wiki-show F-XXX` to assemble focused implementation context
4. read app requirements before implementation
5. use `dev-clarify` to answer dev-owned open questions, which block `dev-start`
6. use `dev-start` to take confirmed ready-for-dev work
7. use `dev-done` only when implementation is truly complete and shipped
8. use `feature-reopen` after impact review when shipped work needs revalidation

Helpful read/query commands:

- `wiki-blockers`
- `wiki-app <app-id>`
- `wiki-query "text"`

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

- pipeline grouped by lifecycle stage
- open questions by owner
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
- web-user-app: pending

Current blockers:
- api-contract-not-ready: mobile-ios app requirements depend on the API contract status changing from draft to agreed
- missing-design: design page does not define the expired payment-method state

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
- `missing-design`
- `missing-app-requirements`
- `unresolved-open-questions`
- `api-contract-not-ready`
- `cross-app-dependency`

Example:

```text
Blockers summary:
- 2 pending board review
- 1 missing design
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
- 0 missing design
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

- show pending work and open questions for one owner role

Supported values:

- `po`
- `designer`
- `dev`
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

Suggested next actions:
- Run design-intake for F-012
- Resolve open questions on F-014 before design-handoff
```

Invalid-owner example:

```text
Owner view: qa

Problem:
`qa` is not a supported owner value.

Supported values:
- po
- designer
- dev
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
- `web-user-app`
- `web-admin-portal`

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
- web-user-app
- web-admin-portal
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
