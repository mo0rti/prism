# Prism Model

Prism is a workflow and shared board for humans and agents. It carries product
intent from raw input through review, implementation, and delivery evidence.
Application templates are an optional starting point. The
[shared board guide](shared-board.md) covers adoption without generating an app.

## Short Version

Each Prism workspace combines:

- one shared workspace
- one shared product wiki under `knowledge/wiki/`
- one lifecycle that moves work from intake to design to development
- one advisory-board layer for domain-sensitive features

The practical idea is simple:

- `knowledge/intake/` stores raw human input and workflow state
- `knowledge/wiki/` stores structured product knowledge used by all agents
- `docs/` stores human-readable technical and operational reference material

If you only remember one thing, remember this:

- the wiki is the shared product source of truth

## The Problems Prism Solves

### Context broadcasting

Without a shared product memory, AI agents only know what is in the current prompt or
session. That leads to:

- repeated re-explanation
- inconsistent feature interpretation
- drift between platforms
- no compounding product knowledge

Prism solves this by making the wiki the shared source of truth.

### Team handoff

Product work usually crosses at least three roles:

- PO
- Designer
- Developer

Prism turns the wiki into the translation layer between those roles instead of relying on
ad hoc messages and local memory.

### Domain expertise

Some features carry business, psychological, cultural, or real-world risk that the core
team may miss. Prism addresses this with a project-specific advisory board that reviews
domain-sensitive features before development starts.

## Core Architecture

Prism has three layers:

### 1. Intake and translation

Raw PO and design artifacts land in `knowledge/intake/`.

The AI reads them, structures them, and proposes updates to the wiki.

### 2. Broadcast and persistence

The wiki is the shared coordination layer that every platform agent reads before
implementing.

### 3. Domain intelligence

The advisory board adds domain-specific review when product logic has consequences the
team should not reason about in isolation.

## Workspace Knowledge Model

Generated and adopted workspaces use this knowledge structure:

```text
knowledge/
  intake/
    pending/
    processed/
    quarantined/      # sources that contradict the wiki, with a CONFLICT.md each
    README.md
  wiki/
    advisory/
    api-contracts/
    business-rules/
    decisions/
    design/
    features/
    personas/
    app-requirements/
    topics/         # synthesis pages
    research/       # one question each, current answer and gaps
    plans/          # current status of one plan each
    direction.md    # current direction and principles
    roadmap.md      # what comes next
    index.md        # general index: one line per page, grouped by kind, no dates
    status-board.md # feature status board, no date columns
    log.md          # append-only log, the only home for history
    SCHEMA.md       # core wiki conventions, read before every wiki operation
    LIFECYCLE.md    # feature, board and advisory protocol, read for lifecycle operations
    SETTINGS.md
    WIKI_REPORT.md    # generated on demand by feature-status; gitignored
```

Important meanings:

- `pending/`, `processed/` and `quarantined/` hold raw sources as `YYYY-MM-DD-slug/` folders; a processed item has a `MANIFEST.md` and is immutable
- `quarantined/` holds a source that contradicts an existing page, with a `CONFLICT.md` (`status: open | resolved`) that gives both claims with their scope and links; the existing page stays untouched until a human resolves it
- `SETTINGS.md` holds project-level wiki behavior settings such as `wiki-stale-after-days`
- pages state the current state and carry no date about themselves; superseded content is replaced in place and rationale is a current fact; when something was written, decided, verified or amended is a `log.md` entry (`## YYYY-MM-DD <operation> | <subject>` with `paths`, `evidence` and `by` lines), while an ADR, an advisory review, each reopen-history entry and a processed intake item keep their own date as dated records, which are never rewritten
- claims on current-state pages carry one of five evidence labels (`**Decided:**`, `**Observed:**`, `**Proposed:**`, `**Assumed:**`, `**Unknown:**`), and a Decided or Observed claim links its evidence
- a decision is replaced by a new ADR with `supersedes: ADR-NNN`; the old ADR gets `status: superseded` and `superseded-by: ADR-MMM`
- `SCHEMA.md` and `LIFECYCLE.md` start with front matter `schema-version: 1`
- `WIKI_REPORT.md` is a generated orientation artifact, not a source-of-truth document

## Source Of Truth

The source of truth for what to build is the wiki, especially:

- `knowledge/wiki/index.md`
- `knowledge/wiki/status-board.md`
- `knowledge/wiki/features/`
- `knowledge/wiki/app-requirements/`
- `knowledge/wiki/business-rules/`
- `knowledge/wiki/api-contracts/`

Within generated repos, keep the API layers distinct:

- `knowledge/wiki/api-contracts/` captures wiki-layer API intent, decisions, and product context
- `shared/api-contracts/openapi.yml` is the implementation contract file that defines API shape and drives code generation

Generated summaries such as `WIKI_REPORT.md` help with orientation, but the underlying
wiki files always win if there is a disagreement.

## First-Time Setup

Every generated project has two startup phases:

### 1. Scaffold the repo

Use Copier to generate the project structure.

### 2. Initialize the wiki

Then open the generated project in your AI tool and run:

- Claude Code: `/setup-project`
- Codex: `$setup-project`
- Cursor: ask the agent to run `setup-project`

This setup flow:

1. confirms project identity
2. runs the domain-risk interview
3. proposes and confirms the advisory board
4. initializes the first wiki state

## Role Workflow Summary

### Product Owner

- drop raw notes into a dated folder, `knowledge/intake/pending/YYYY-MM-DD-slug/`
- run `po-intake`
- answer PO-owned open questions with `po-clarify`
- author a raw feature as a structured draft with `po-specify`
- move a verified feature forward with `po-handoff`

### Designer

- attach design artifacts with `design-intake`
- resolve design questions with `design-clarify`
- start confirmed work with `design-start`
- move the feature to dev readiness with `design-handoff`

### Developer

- inspect readiness with `prep-sprint`
- resolve dev-owned open questions with `dev-clarify`
- start confirmed implementation with `dev-start`
- read feature and app requirement context before implementing
- mark shipped work with `dev-done`

### Reopening shipped work

`feature-reopen F-XXX [specified|in-design|in-dev]` starts one impact-reviewed
revalidation route. It preserves the prior completion record, removes old active
delivery evidence from readiness, and marks only the affected domains and
requirements for fresh evidence. Reopening does not reset unrelated features or
shared API contracts.

### Shared coordination

- `feature-status` provides the pipeline view and refreshes `WIKI_REPORT.md`
- `lint-wiki` checks structural health
- `ask` routes questions to PO, Designer, or Developer
- `audit-feature` cross-checks a feature against source intake
- the wiki read/query layer provides targeted drill-down tools

Every write-capable lifecycle action is confirmation-gated and source-backed.
`po-specify` authors the required structured body from raw facts; `dev-done`
requires verifiable implementation and test references and release evidence or a
delivery attestation for every app in the feature's scope. The canonical action table, UI design exemption, active
revalidation, delivery evidence, and reopen history formats live in
`template/knowledge/wiki/LIFECYCLE.md`.

## Advisory Board Model

The advisory board is:

- project-specific
- defined during setup
- advisory rather than governing
- used for features with meaningful domain sensitivity

It is not:

- a required step for every feature
- generic architecture review
- automatic approval or rejection

Run board review for features with:

- real-world consequences outside the app
- vulnerable user groups
- domain-specific scoring or decision logic
- behavioral or psychological implications
- culturally sensitive assumptions
- core differentiating product behavior

## Enduring Rules

These rules are central to the Prism model.

### Confirm before writing intake-driven changes

For `setup-project`, `po-intake`, and `design-intake`, the agent should summarize the
planned write set and wait for confirmation before writing.

### Never silently overwrite on conflict

If new intake contradicts the current wiki, move the intake folder to
`knowledge/intake/quarantined/` with a `CONFLICT.md` that records both claims and their
scope, and leave the existing page untouched, instead of guessing.

### Use exact app IDs

Use:

- `backend`
- `mobile-android`
- `mobile-ios`
- `web-user-app`
- `web-admin-portal`

Do not invent aliases such as `ios`, `android`, or `web`.

### `index.md` indexes the wiki; `status-board.md` is the status board

`index.md` lists every page once, one line in the present tense, grouped by kind, and is the
first file an agent reads to find pages. `status-board.md` is the feature status board for
lifecycle coordination. The connected board maintains both next to `log.md`.

### Ingest is open to any role

`ingest` turns a pending intake folder into a topic, research page, plan, direction, roadmap,
persona, business rule, decision or feature, for any role; `po-intake` and `design-intake`
remain the entry points for features and design. See [wiki-workflow.md](wiki-workflow.md#ingest-any-role-any-page-kind).

### Board review must compound into the wiki

Board review is only useful if important questions, rules, and feature changes feed back
into the wiki instead of living only in a standalone review file.

## What To Read Next

- [generated-projects.md](generated-projects.md) for the generated-repo shape and safe-first commands
- [wiki-workflow.md](wiki-workflow.md) for the wiki lifecycle and read/query layer
- [ai-surfaces.md](ai-surfaces.md) for Claude/Codex packaging guidance
- [wiki-validation.md](wiki-validation.md) for current confidence boundaries
