# Tech design done - settle the technical track of one feature

<!-- prism:tech-design-done-contract:v1 -->

Use this skill when the technical design of a feature is complete. It sets one track, `technical`,
in the feature's `design-tracks`, and it is the action that authors the API contract. It does not
hand the feature to development: `/design-handoff` does that once both tracks are settled.

## Usage

`/tech-design-done [F-XXX] [not-applicable]`

## Supported action

`ready-for-design` or `in-design` + the design owner -> `in-design` + the design owner (`designer`
while an active app in scope has a UI, otherwise `tech-lead`)

Resolve exactly one `knowledge/wiki/features/[F-XXX]-[slug].md` source file. A missing, invalid,
ambiguous, or different source pair is a stop condition, and so is a feature that lists a retired
app (`app-retired-in-scope`). From `ready-for-design` this action also starts design and writes the
initial `design-tracks`. A connected board approves it only for a participant who holds the
`tech-lead` role.

The action is open only while the technical track is `pending`, absent, or listed in
`design-reaffirm`. A track that is `done` or `not-applicable` is changed with
`/design-clarify`, which sets it back to `pending` when it changes the technical design
page.

## Read-only preflight

When available, use:

```text
prism wiki transition-preflight F-XXX [path] --action tech-design-done --json
```

Accept it only with common envelope schema 1, command facts, capability version 3 and an
action-specific `tech-design-done` surface, transition version 2, target owner the design owner, and
a consistent snapshot. The Prism version alone does not prove support. If any required fact, schema,
action, capability, or snapshot is missing or fails, fall back to direct-file checks. The preflight
is copy-only and never authorizes a write.

## The track

Read `knowledge/wiki/SCHEMA.md`, `knowledge/wiki/LIFECYCLE.md`, `knowledge/wiki/ACTIONS.md`, `status-board.md`, the complete
feature, its technical design page, API contract and requirement pages, the decisions in
`knowledge/wiki/decisions/`, linked context, and the apps in `prism.workspace.yml`.

- **`done`**: a complete technical design page `knowledge/wiki/technical-design/F-XXX-[slug].md`
  (`technical-design-incomplete` otherwise) whose Test strategy names every acceptance criterion ID of
  the feature (`test-strategy-incomplete` otherwise). When the `## API surface` declares API work, the
  feature also has an `agreed` API contract (below), and an active app in scope serves an API
  (`api-surface-without-api-app` otherwise).
- **`not-applicable`**: a non-blank `technical-reason`, and no API work declared in the `## API surface`
  (`technical-track-required` otherwise). `/tech-design-done F-XXX not-applicable` proposes it.
- **Open questions**: an open question owned by `tech-lead` blocks the action. Resolve it with
  `/design-clarify` first. An active `specification` domain in `revalidation` blocks it too.

## The technical design page

The page is a current-state page, one for the feature, with the front matter `feature-id`, `title`,
`apps` (every app of the scope) and `decisions` (ADR IDs, or an empty list), and the sections in
`knowledge/wiki/technical-design/_FORMAT.md`: Summary, Architecture impact (a table of App, Modules,
Change with a row for every app), Data model and migrations, Security and privacy, Non-functional
requirements, Risks, Decisions, API contract and Test strategy (a table of Criterion, Applies to,
Method, Level, Notes with a row for every criterion ID). Start from the architecture of the apps and the
decisions that exist; never invent a decision the sources do not support.

## The API contract

The contract `knowledge/wiki/api-contracts/F-XXX.md` is created here, never by another action and never
by hand. The user who confirms this action agrees it.

- Create it only when `## API surface` declares API work and the feature has no contract yet. It starts
  at `version: 1`, `status: agreed`, with the sections `## Endpoints`, `## Data models`,
  `## Authentication requirements` and `## Notes`. List each endpoint as `METHOD /path`, use the paths the
  API surface names, and define only data models that the API surface or a listed endpoint names. An API
  surface too vague to write from needs `/ask` and `/po-clarify` first.
- Revise it only while the feature is in design: raise `version` by one, change the body, keep
  `status: agreed`. A changed body without a version bump is `contract_revision_required`. While another
  feature that links the contract has an app between `ready-for-dev` and `ready-for-release`, the
  revision is refused (`shared_contract_in_use`); that feature returns first.
- Link the page from the technical design page and from each requirement's `## API contract reference`.
- Delivery evidence cites the contract as `F-XXX@v<version>:c1:<digest>`; the board reports the
  version, digest and citation beside the contract page when it reads it.

## Writes

Show the observed fields, the proposed destination and every write, then wait for confirmation.

- Feature front matter: `design-tracks.technical` set to `done`, or to `not-applicable` with
  `technical-reason` (the other track and its reason stay as they are), `design-reaffirm`, and, from
  `ready-for-design`, `status: in-design`. When `design-tracks` is absent, write both keys together:
  `ui` as the first design action sets it (`pending`, or `not-applicable` with the reason
  `No app in scope has a UI.` when every active app has `has-ui: false`), `technical` as this action
  sets it, `design-reaffirm: []`.
- `design-reaffirm`: remove `technical` from it. When this action changes the technical design page or
  the contract of a track that was `done`, add `ui` to it if the UI track is `done`. A run with no page
  change only removes the entry.
- The technical design page, the API contract when it is authored or revised, and the feature's
  `## Design` section (link the technical design page). No other section changes.
- The feature's row in `status-board.md`, the `index.md` line of each page you write, and a `log.md`
  entry in the log format that the wiki schema defines.

Reread the source and context immediately before confirmation and once again after it. The
preflight and any copied request are copy-only and never authorize a write. Decline or cancel means
no write. If a multi-file write is partial, report the exact observed state and require fresh
recovery; no transaction is implied.

## Rules

- write-capable skill
- sets the `technical` track only: the UI track's keys, state, reason and design pages stay unchanged (`track_scope`)
- the board checks that a design is complete and traceable, not that it is adequate: the tech lead
  confirms the design itself
- write current-state pages: replace superseded content in place, state rationale as a current fact and keep history in `log.md` and the records; mark each claim `**Decided:**`, `**Observed:**`, `**Proposed:**` or `**Assumed:**` (gaps stay in the Open questions table) and link the evidence of every Decided and Observed claim: the processed intake item, a record or a URL (see Evidence labels in the wiki schema)

## Output behavior

Return:

- the observed track state and the proposed one
- the technical design page and the criteria its Test strategy covers
- the API contract created or revised, with its version, or the reason none is needed
- the proposed `design-reaffirm`
- the pages and files the action writes, after confirmation

## Error and stop conditions

- if the feature file does not exist or its source pair is not supported, return a clean stop
- if the technical track is not open, or a prerequisite is unmet, list it and stop without writing
- if the user does not confirm, stop without writing
