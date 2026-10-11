# Prism Model

Prism is a workflow and shared board for humans and agents. It carries a feature from a
business requirement through specification, design, implementation, QA and release to
operation. Every stage has an accountable role, a gate with bound evidence and a human who
approves it. Application templates are an optional starting point. The
[shared board guide](shared-board.md) covers adoption without generating an app.

## Short Version

Each Prism workspace combines:

- one shared workspace
- one shared product wiki under `knowledge/wiki/`
- one lifecycle that moves a feature from intake to release and keeps operation work visible
- six workflow roles that live on board grants
- one advisory-board layer for domain-sensitive features

The practical idea is simple:

- `knowledge/intake/` stores raw human input and workflow state
- `knowledge/wiki/` stores structured product knowledge used by all agents
- `docs/` stores human-readable technical and operational reference material

If you only remember two things, remember these:

- the wiki is the shared product source of truth
- agents propose, and a human who holds the role of the stage approves in the board

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

Product work crosses several roles: product owner, designer, tech lead, developer, QA and
release. Prism turns the wiki into the translation layer between those roles instead of
relying on ad hoc messages and local memory. A status names its owner role, and the board
refuses a stage change that a person without that role approves.

### Domain expertise

Some features carry business, psychological, cultural, or real-world risk that the core
team may miss. Prism addresses this with a project-specific advisory board that reviews
domain-sensitive features before development starts.

### Accountability

A feature that was finished in a chat has no evidence behind it. Prism binds evidence to the app, the
artifact version, the criterion revision, the environment and the attempt, records whether it
was checked or attested, and invalidates it when code, scope or requirements change. Releases
and incidents are dated records, so the wiki pages stay current-state pages.

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
    app-requirements/
    bugs/             # one current-state page per bug
    business-rules/
    decisions/
    design/           # UI design pages
    features/
    incidents/        # dated incident records
    personas/
    plans/            # current status of one plan each
    releases/         # dated release, rollback and redeploy records
    research/         # one question each, current answer and gaps
    technical-design/ # technical design page of a feature
    topics/           # synthesis pages
    direction.md      # current direction and principles
    roadmap.md        # what comes next
    index.md          # general index: one line per page, grouped by kind, no dates
    status-board.md   # features, bugs and apps in operation, no date columns
    log.md            # append-only log, the only home for history
    SCHEMA.md         # core wiki conventions, read before every wiki operation
    LIFECYCLE.md      # feature, board and advisory protocol, read for lifecycle operations
    ACTIONS.md        # lifecycle action registry and write scopes, read for lifecycle actions
    CONNECTED.md      # how a connected agent reads and submits work through the board
    SETTINGS.md
    WIKI_REPORT.md    # generated on demand by feature-status; gitignored
```

Important meanings:

- `pending/`, `processed/` and `quarantined/` hold raw sources as `YYYY-MM-DD-slug/` folders; a processed item has a `MANIFEST.md` and is immutable
- `quarantined/` holds a source that contradicts an existing page, with a `CONFLICT.md` (`status: open | resolved`) that gives both claims with their scope and links; the existing page stays untouched until a human resolves it
- `SETTINGS.md` holds project-level behavior settings: `wiki-stale-after-days`, `qa-separate-from-dev` and the `delivery-targets` of the apps
- pages state the current state and carry no date about themselves; superseded content is replaced in place and rationale is a current fact; when something was written, decided, verified or amended is a `log.md` entry (`## YYYY-MM-DD <operation> | <subject>` with `paths`, `evidence` and `by` lines), while an ADR, an advisory review, a release record, an incident, each Evidence history entry and a processed intake item keep their own date as dated records, which are never rewritten
- claims on current-state pages carry one of five evidence labels (`**Decided:**`, `**Observed:**`, `**Proposed:**`, `**Assumed:**`, `**Unknown:**`), and a Decided or Observed claim links its evidence
- a decision is replaced by a new ADR with `supersedes: ADR-NNN`; the old ADR gets `status: superseded` and `superseded-by: ADR-MMM`
- `SCHEMA.md`, `LIFECYCLE.md` and `ACTIONS.md` start with front matter `schema-version: 1`
- `WIKI_REPORT.md` is a generated orientation artifact, not a source-of-truth document

## Source Of Truth

The source of truth for what to build is the wiki, especially:

- `knowledge/wiki/index.md`
- `knowledge/wiki/status-board.md`
- `knowledge/wiki/features/`
- `knowledge/wiki/design/` and `knowledge/wiki/technical-design/`
- `knowledge/wiki/app-requirements/`
- `knowledge/wiki/business-rules/`
- `knowledge/wiki/api-contracts/`

Within generated repos, keep the API layers distinct:

- `knowledge/wiki/api-contracts/` captures the agreed API contract of a feature, with a digest that delivery evidence cites
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

Lifecycle work does not wait for setup. Until setup runs, the advisory board is not set up,
so `board-review` is unavailable and a feature that needs a review keeps
`advisory-review: pending`.

## Roles

Prism has six workflow roles: `po`, `designer`, `tech-lead`, `dev`, `qa` and `release`. A role
is a property of a board grant, not a field on a wiki page:

```text
prism board grant "Quinn" --kind human --write --role qa,release --path .
```

- A grant names a registered participant. It does not verify a person, and the board cannot
  tell whether the token holder is the person named.
- Only a writable human grant holds roles. An agent grant holds none: an agent proposes, and a
  human applies gated work in the board.
- Roles are fixed for the life of a grant. To change them, issue a new grant and revoke the old
  one with `prism board revoke`.
- A small team gives one person several roles. A larger team gives each person one.
- The board checks the role when it previews a human action, again when it applies it and again
  when it recovers an interrupted operation.

| Role | Accountable for |
|---|---|
| `po` | the specification, the PO handoff, removing an app from the scope after design, bug dispositions (`wont-fix`, `promoted`, deferral) and reopening a released feature to specification |
| `designer` | the UI design track, when an app in scope has a UI |
| `tech-lead` | the technical design track, and design when no app in scope has a UI |
| `dev` | implementation and delivery evidence, fixes, returns from implementation and reopening a released feature to development |
| `qa` | QA verification, passing or failing QA, the routes back from QA and bug verification |
| `release` | release records, failed deliveries, rollbacks, redeploys and the bugs a release ships |

## The Lifecycle

```text
raw → specified → ready-for-design → in-design → ready-for-dev → in-dev → ready-for-qa → in-qa → ready-for-release → released
```

| Status | Owner | Entered by | Approver role |
|---|---|---|---|
| `raw` | `po` | `po-intake` or `ingest` | none |
| `specified` | `po` | `po-specify` | `po` |
| `ready-for-design` | `designer`, or `tech-lead` when no active app has a UI | `po-handoff` | `po` |
| `in-design` | the same design owner | `design-start`, or the first design track action | the design owner |
| `ready-for-dev` | `dev` | `design-handoff` | the design owner |
| `in-dev` | `dev` | `dev-start`, or `dev-done` straight from `ready-for-dev` | `dev` |
| `ready-for-qa` | `qa` | `dev-done`, once every app has delivered | `dev` |
| `in-qa` | `qa` | `qa-verify`, whose first result opens the stage | `qa` |
| `ready-for-release` | `release` | `qa-pass`, once every app has passed | `qa` |
| `released` | `none` | `release-done`, once every app is released | `release` |

Capturing input is open to everyone: `po-intake`, `design-intake`, `ingest`, `ask` and the
clarify skills (`po-clarify`, `design-clarify`, `dev-clarify`) need no role. They never advance
a status.

### Intake and specification

The PO drops raw notes into a dated folder under `knowledge/intake/pending/` and runs
`po-intake`, which creates the feature as `raw` + `po`. `po-clarify` answers PO-owned
questions. `po-specify` authors the structured body from the raw facts: a summary, one user
story, acceptance criteria that each carry an ID (`AC-1`) and the apps that verify it, an app
scope per app, and open questions for the unknowns. `po-handoff` hands a specified feature to
design after checking that the specification is factually complete and the advisory review is
settled.

### Design: two tracks under one owner

The design owner is `designer` when any active app in scope has a UI (`has-ui` true or
unknown) and `tech-lead` otherwise. Design has two tracks, each `pending`, `done` or
`not-applicable`:

- the **UI track** is settled by `design-ui-done`: design pages that cover every app with a UI,
  or an exemption with a reason;
- the **technical track** is settled by `tech-design-done`: a technical design page (architecture
  impact, data model, security, non-functional needs, risks, decisions and a test strategy that
  names every acceptance criterion) and, for declared API work, the agreed API contract.

`design-handoff` needs both tracks settled and prepares one requirement page per app. A change
to a settled track's pages sets that track back to `pending` and lists the other track for
reaffirmation. The API contract is one page per feature; the human confirming its preview is the
agreement, and it carries a digest that delivery evidence cites.

### Implementation

`dev-start` is an optional pickup after the developer rereads the requirements and contracts.
`dev-clarify` answers dev-owned questions. `dev-done` records, for the apps it names, a
delivery evidence row: the artifact, the contract citation, the implementation and test
references, and whether the evidence was checked or attested. A feature moves to
`ready-for-qa` once every app has delivered. Work that turns out to be a specification or
design problem goes back with `dev-return-spec` or `dev-return-design`.

### QA

QA is independent of implementation. `qa-verify` records QA rows for an app, or for an
integration of two or more apps, against the delivered artifact, the criterion revisions, the
attempt and the environment, and opens bugs for the defects it finds. `qa-pass` passes the
apps it names and needs every applicable criterion verified and no blocking bug. `qa-fail` sends
apps back to development and archives their evidence in Evidence history. `qa-return-spec` and
`qa-return-design` send the whole feature back to the PO or to design.

### Release

Prism deploys nothing; a release is a record of a delivery that happened. Each app declares one
delivery target in `SETTINGS.md` (`deployment`, `store`, `artifact` or `other`, with stack
defaults). `release-done` settles the Release row of the apps it releases, ships the verified
bugs of those apps and writes one dated record, `releases/REL-XXX.md`, with the target, the
version, the attempt and the outcome, and a verbatim snapshot of each cited API contract. A
failed delivery goes back to development with `release-return-dev`. `release-rollback` and
`release-redeploy` add records that say a delivery was rolled back or delivered again.
`released` means delivered to the target, not currently available: the latest record for an app
and target says what is known.

### Per-app progress

A feature's status from `in-dev` on is the minimum over the stages of its active apps. Each
app's rows in Delivery evidence, QA verification and Release carry its own state, so the backend
can be released while mobile is still in QA. `released` needs every app. Lint reports a status
that differs from the minimum and a status that needs a row an app lacks.

### Reopening and returns

- A feature is sent back before it ships with a return action: `dev-return-spec`,
  `dev-return-design`, `qa-fail`, `qa-return-spec`, `qa-return-design` or `release-return-dev`.
  Each archives the affected evidence rows verbatim in the feature's `## Evidence history`,
  never deletes them, and sets the revalidation domains that need fresh evidence.
- A released feature is reopened with `feature-reopen F-XXX [specified|in-design|in-dev]`.
  Reopening to development archives only the apps that change.
- A spec or design change on a feature with a released app goes in a new feature, and an
  implementation defect in a bug (`partial_release_requires_new_feature`).

### Operation and maintenance

- **Bugs** are pages in `knowledge/wiki/bugs/`. A bug moves `open`, `in-fix`, `fixed`, `verified`,
  `released`, or is `closed` with a reason (`wont-fix`, `duplicate` or `promoted`). `bug-update`
  moves it; `qa-verify`, `qa-pass`, `qa-fail` and `ingest` create it; `release-done` ships it. A
  bug that blocks an app stops its `qa-pass` and its release. A bug whose fix changes agreed
  requirements or contracts is promoted to a feature.
- **Incidents** are dated records in `knowledge/wiki/incidents/`, written through `ingest`, with
  the impact, timeline, cause, mitigation, resolution and follow-up bugs or features. There is no
  separate incident engine and no incident action.
- **Runbooks.** Every generated app ships `docs/runbook.md` with what its stack makes known and
  `**Unknown:**` items for hosting. An app in an external repository records a runbook link in
  its manifest entry.
- **The status board** shows the features with their tracks, app stages and open bugs, every open
  bug, and one row per app in operation with its released features, latest release, open bugs and
  open incidents.

## Approval: Agents Propose, Humans Approve

An action is **gated** when the registry names the roles its approver must hold. Every action
that advances a status, a design track or an app stage is gated. A gated action is approved once, in
the board; an ungated write is confirmed once, in the agent host. Prism has no second approval step.

1. An agent calls `preview_skill`. A gated preview waits in the board's proposal list. The agent
   cannot apply, recover or decline it (`approval_required`).
2. A human who holds the required roles opens **Proposals** in the board header, reviews the
   evidence and the exact changes, acknowledges the review and chooses **Approve and apply**, or
   declines with a reason. Approval is accepted only in a browser board session.
3. The log entry names the approver, the roles they held and the agent they approved.

Three actions are human-direct, with no agent proposal: `po-handoff`, `design-start` and
`dev-start`. The human previews and applies them in the board, by dragging the card or using
its action control. An agent that needs one asks the human to complete it there.

An ungated write never advances a status, a track or an app stage: capturing intake, answering a
question, recording a verification in the log. Any writable grant applies it, after the human
confirms the preview in the agent host.

The workspace setting `qa-separate-from-dev: true` makes the board refuse a QA approval from
the grant that produced, recovered or repaired the evidence it verifies. It separates grants,
not proven people. [SECURITY.md](../SECURITY.md#roles-and-gated-approval) states what the roles
and the approval do and do not protect.

Without the connected board, in the direct-file workflow, no role is enforced and lint checks
structure only.

## Role Workflow Summary

### Product Owner

- drop raw notes into a dated folder, `knowledge/intake/pending/YYYY-MM-DD-slug/`
- run `po-intake`
- answer PO-owned open questions with `po-clarify`
- author a raw feature as a structured draft with `po-specify`
- move a verified feature forward with `po-handoff`
- decide bug dispositions (`wont-fix`, `promoted`, deferral) with `bug-update`

### Designer and tech lead

- attach design artifacts with `design-intake`
- resolve design questions with `design-clarify`
- start confirmed work with `design-start`
- settle the UI track with `design-ui-done` (designer) and the technical track with
  `tech-design-done` (tech lead)
- move the feature to dev readiness with `design-handoff`

### Developer

- inspect readiness with `prep-sprint`
- resolve dev-owned open questions with `dev-clarify`
- start confirmed implementation with `dev-start`
- read feature and app requirement context before implementing
- record delivery with `dev-done`
- fix bugs with `bug-update`

### QA

- record verification with `qa-verify`
- pass or fail apps with `qa-pass` and `qa-fail`
- send a feature back with `feature-reopen` (`qa-return-spec`, `qa-return-design`)
- verify bug fixes with `bug-update`

### Release

- record releases, failed deliveries, rollbacks and redeploys with `release-done`

### Shared coordination

- `feature-status` provides the pipeline view and refreshes `WIKI_REPORT.md`
- `lint-wiki` checks structural health
- `ask` routes questions to the owner role
- `audit-feature` cross-checks a feature against source intake
- the wiki read/query layer provides targeted drill-down tools

Every write-capable lifecycle action is source-backed and shown as an exact preview before it
writes. `dev-done` requires verifiable implementation and test references for every app it
names. The canonical action table lives in `template/knowledge/wiki/ACTIONS.md`; the design
tracks, the evidence tables, the revalidation domains and the Evidence history format live in
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

### Confirm before writing

For `setup-project`, `po-intake`, and `design-intake`, the agent should summarize the
planned write set and wait for confirmation before writing. On the connected board the preview
is where the human confirms.

### Never silently overwrite on conflict

If new intake contradicts the current wiki, move the intake folder to
`knowledge/intake/quarantined/` with a `CONFLICT.md` that records both claims and their
scope, and leave the existing page untouched, instead of guessing.

### Use exact app IDs

Use the app IDs that `prism.workspace.yml` declares. A default generated workspace has:

- `backend`
- `mobile-android`
- `mobile-ios`
- `web`

Do not invent aliases such as `ios` or `android`.

### `index.md` indexes the wiki; `status-board.md` is the status board

`index.md` lists every page once, one line in the present tense, grouped by kind, and is the
first file an agent reads to find pages. `status-board.md` is the status board for
lifecycle coordination. The connected board maintains both next to `log.md`.

### Ingest is open to any role

`ingest` turns a pending intake folder into a topic, research page, plan, direction, roadmap,
persona, business rule, decision, feature, bug or incident, for any role; `po-intake` and
`design-intake` remain the entry points for features and design. See
[wiki-workflow.md](wiki-workflow.md#ingest-any-role-any-page-kind).

### Board review must compound into the wiki

Board review is only useful if important questions, rules, and feature changes feed back
into the wiki instead of living only in a standalone review file.

## What To Read Next

- [generated-projects.md](generated-projects.md) for the generated-repo shape and safe-first commands
- [wiki-workflow.md](wiki-workflow.md) for the wiki lifecycle and read/query layer
- [shared-board.md](shared-board.md) for grants, roles, proposals and the MCP tools
- [ai-surfaces.md](ai-surfaces.md) for Claude/Codex packaging guidance
- [wiki-validation.md](wiki-validation.md) for current confidence boundaries
