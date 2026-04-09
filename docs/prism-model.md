# Prism Model

Prism is the workflow and coordination model embedded in this template.

It is not just a generated code scaffold. It is a way to carry product intent from raw
input to implementation across multiple AI-assisted roles and platform slices.

## What Prism Is

Each generated project combines:

- one monorepo
- one shared product wiki under `knowledge/wiki/`
- one lifecycle that moves work from intake to design to development
- one advisory-board layer for domain-sensitive features

The key split is:

- `knowledge/intake/` stores raw human input and workflow state
- `knowledge/wiki/` stores structured product knowledge used by all agents
- `docs/` stores human-readable technical and operational reference material

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

Prism has three layers.

### Intake and translation

Raw PO and design artifacts land in `knowledge/intake/`.

The AI reads them, structures them, and proposes updates to the wiki.

### Broadcast and persistence

The wiki is the shared coordination layer that every platform agent reads before
implementing.

### Domain intelligence

The advisory board adds domain-specific review when product logic has consequences the
team should not reason about in isolation.

## Generated Project Model

Generated projects use this knowledge structure:

```text
knowledge/
  intake/
    pending/
    processed/
    quarantined/      # conflict-resolution state for intake that cannot be applied safely
    README.md
  wiki/
    advisory/
    api-contracts/
    business-rules/
    decisions/
    design/
    features/
    personas/
    platform-requirements/
    index.md
    log.md
    SCHEMA.md
    SETTINGS.md
    WIKI_REPORT.md    # generated on demand by feature-status; gitignored
```

Important meanings:

- `quarantined/` is the conflict-resolution state for intake that cannot be applied safely
- `SETTINGS.md` holds project-level wiki behavior settings such as `wiki-stale-after-days`
- `WIKI_REPORT.md` is a generated orientation artifact, not a source-of-truth document

## Source of Truth

The source of truth for what to build is the wiki, especially:

- `knowledge/wiki/index.md`
- `knowledge/wiki/features/`
- `knowledge/wiki/platform-requirements/`
- `knowledge/wiki/business-rules/`
- `knowledge/wiki/api-contracts/`

Generated summaries such as `WIKI_REPORT.md` help with orientation, but the underlying
wiki files always win if there is a disagreement.

## First-Time Setup

Every generated project has two startup phases.

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

- drop raw notes into `knowledge/intake/pending/`
- run `po-intake`
- answer PO-owned open questions with `po-clarify`
- move a feature forward with `po-handoff`

### Designer

- attach design artifacts with `design-intake`
- resolve design questions with `design-clarify`
- move the feature to dev readiness with `design-handoff`

### Developer

- inspect readiness with `prep-sprint`
- read feature and platform requirement context before implementing
- mark shipped work with `dev-done`

### Shared coordination

- `feature-status` provides the pipeline view and refreshes `WIKI_REPORT.md`
- `lint-wiki` checks structural health
- `ask` routes questions to PO, Designer, or Developer
- `audit-feature` cross-checks a feature against source intake
- the wiki read/query layer provides targeted drill-down tools

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

If new intake conflicts with the current wiki, move the intake folder to
`knowledge/intake/quarantined/` with an explanation instead of guessing.

### Use exact platform IDs

Use:

- `backend`
- `mobile-android`
- `mobile-ios`
- `web-user-app`
- `web-admin-portal`

Do not invent aliases such as `ios`, `android`, or `web`.

### `index.md` is a status board

`index.md` is for lifecycle coordination, not flat wiki-page listing.

### Board review must compound into the wiki

Board review is only useful if important questions, rules, and feature changes feed back
into the wiki instead of living only in a standalone review file.

## Related Docs

- [generated-projects.md](generated-projects.md)
- [wiki-workflow.md](wiki-workflow.md)
- [ai-surfaces.md](ai-surfaces.md)
- [wiki-validation.md](wiki-validation.md)
