# Wiki Visualization

Prism's wiki visualization is an optional local read surface for a generated
workspace. It derives its facts from `knowledge/wiki/`, intake queues, the
workspace manifest and answers, and the generated app directories. The wiki
files remain the source of truth. The dashboard does not edit them.

This page describes the dashboard that `prism wiki graph` serves and exports. It is
read-only and copy-only. The board that `prism board serve` serves shows the same
views and also performs `po-handoff`, `design-start` and `dev-start` after a human
confirms the exact changes; [shared-board.md](shared-board.md) describes it.

## Try the TreasuryFlow demo

The repository includes a repeatable synthetic fixture for the TreasuryFlow
finance operations story: payout requests, manager approval, and finance-admin
settlement/history review. Build it into a new empty directory:

```text
python scripts/build-wiki-demo.py --destination <new-demo-directory> --stage all --json
```

The builder refuses an existing destination. It creates three capture-ready
stages:

| Stage | What it demonstrates |
|-------|----------------------|
| `fresh` | An empty wiki and Guide setup path before the advisory board is initialized |
| `intake` | A pending payout brief and a quarantined item visible in the intake queues |
| `populated` | Three features across `raw`, `in-dev`, and `released`, with app requirements, designs, API contracts, personas, business rules, a decision, a review, an open question, and a canonical blocker |

The fixture is synthetic local documentation. It contains no production data,
observed project history, deployment evidence, compliance claim, or recorded
human review. The default platform story is backend, Android, and iOS, with
operator, manager, and finance-admin roles.

Open the populated stage after installing the local CLI:

```text
prism wiki graph <new-demo-directory>/populated --open
prism wiki graph <new-demo-directory>/populated --serve --port 8321
```

The `--open` and `--serve` commands run the same local server, keep dashboard data
in memory, and refresh when relevant source files change. Press Ctrl+C to stop.
Use `--html <path>` when you want to save a snapshot explicitly. All these
surfaces are read-only. The inspector exposes the source path for a selected
wiki node. Board intake cards identify their queue and item name; manifest and
answers inputs remain visible through workspace metadata and confidence
diagnostics.

## What the views mean

| View | Use it for |
|------|------------|
| Graph | Follow relationships between features, personas, rules, designs, API contracts, app requirements, decisions, reviews, and apps. Search and filters narrow the visible map; selecting a node opens its source context. |
| Board | Read feature work in lifecycle columns and see intake pending/quarantine visibility alongside workflow blockers. A first feature makes the brief and intake step complete; the guide does not reopen a completed step when the brief leaves the queue. |
| Apps | Compare the selected app's feature targets and app requirement pages, including requirement status. Each app's open bugs, open incidents, latest release and released features open their panels. |
| Bugs | Read the product's bugs as a board with a column per status (`open`, `in-fix`, `fixed`, `verified`, `released`, `closed`). A card shows the severity, a blocking badge, the apps, the owner, the feature (a link that opens its panel), the deferred and regression flags and, for a closed bug, its disposition (won't fix, a duplicate of another bug, promoted to a feature). A page that fails lint shows a warning, and one without a known status sits in an `invalid` column, which comes first; the count reads "12 bugs, 2 invalid". Filter by app, or show the open blocking bugs only (the chip counts them, as the **Open bugs** tile does). |
| Releases | Read the release history, the highest record number first. A record shows its date, kind (`release`, `retry`, `rollback`, `redeploy`), outcome, the features and bugs it names, a link to the record it retries or rolls back, a `current` mark when it is the latest record of an app and target and it released there (a record rolled back without a redeploy is not current), and its deliveries (item, app, target, version, outcome; the item is a link). Filter by app and target. |
| Incidents | Read the incidents grouped by status (`open`, `mitigated`, `resolved`). A card shows the severity, the apps, the impact line, "cause unknown" while it is, and links to its releases and follow-ups. |
| Guide | Understand setup, intake, and review state before navigating the graph. Completion is derived from current files and feature presence. |

A bug, a release record or an incident opens a panel like a feature does: a bug shows its summary and its fix, verification and release rows; a release shows its deliveries and its chain (the record it retries or rolls back and the records that retry or roll it back); an incident shows its impact, its timeline (with a note when more lines are on the page) and its releases and follow-ups. Every panel shows the page path with a copy button, and a link to another record opens that record's panel. A card opens its own page, found by its kind and path, and a link resolves within the kind its field names, by ID, to the first valid page of that kind: the Apps view's open bugs link only to bugs (also a bug that declares `F-001` or `custom`), a release's features only to features, its bugs only to bugs, and a field that can name a bug or a feature (an incident's follow-ups, a delivery row's item) tries the kind its ID prefix names first and then the other. Closing a panel returns focus to what opened it, also after a live update. A feature's panel lists the feature's bugs, with their status, and the release records that name it. The header shows **Open bugs** (with the blocking count) and **Open incidents**; each tile opens its view. The views are read-only, are drawn from `facts.bugs`, `facts.releases` and `facts.incidents` of the graph, and appear the same on the connected board, the legacy dashboard and the static export.

The dashboard separates workflow blockers from page integrity. A pending
review or open question is a workflow obligation. A malformed page is a source
health diagnostic; advisory warnings are not called malformed pages.

## The facts the views read

`prism wiki graph <workspace> --json`, the live server's `/data.json`, its stream and the static export carry one envelope.
Its `facts` hold the graph and what the views derive from the pages:

| Fact | Content |
|------|---------|
| `nodes`, `edges`, `dangling_references` | The graph: pages as nodes, evidence-carrying edges, and the links that resolve to no page. |
| `setup_state`, `intake` | The setup state and the pending and quarantined intake items. |
| `transition_capability`, `action_registry` | What the copy-only requests may offer, and the feature actions of the transition registry. |
| `app_operations` | The status board's Operations rows, one per app that has something to show. |
| `bugs` | One entry per bug page: its status, owner, severity, blocking flag, apps, feature, where it was found, its disposition if closed, a summary, and its Fix, Verification and Release rows. |
| `releases` | One entry per release record: its date, kind, outcome, features and bugs, the record it retries or rolls back, a summary, its Delivery rows, and whether it is current. |
| `incidents` | One entry per incident: its date, status, severity, apps, releases and follow-ups, an impact summary, whether the cause is known, and its Timeline. |

The three record lists are read by the code that lint and the status board use, so a value cannot differ between the page, the
status board and `prism wiki lint`. Each list is sorted by the record number, and a missing optional value is `null`:

- A bug's `status` and `owner` are the page's. A page that lint marks invalid (`bug-page-invalid`, `invalid-bug-status-owner`)
  stays in the list with `valid: false`, and a value it lacks or states outside its vocabulary is `null`. A bug, release record,
  incident or feature whose ID has a number of more than 18 digits is invalid in the same way, and a release record of that kind
  takes no part in `current`, the Operations row or the chronology.
- A release's `kind` is `release`, `retry` (a release that names the failed release it retries in `retry-of`), `rollback` or
  `redeploy`. The chronological release validator that lint and the board use decides it; a title never does. `current` is true
  when the record is the latest record of at least one app and target and it released there, by the rule the Operations row uses; a record rolled back without a redeploy is not current. A record
  that lint marks invalid (`release-record-invalid`) is listed with `valid: false`.
- An incident's `cause_known` is false while its Cause is empty or starts with `**Unknown:**`. A page that lint marks invalid
  (`incident-record-invalid`) is listed with `valid: false`.
- Text is plain, never HTML. A bug's or record's `summary` and an incident's `impact` are the first paragraph of the section,
  cut to 240 characters at a word boundary with an ellipsis. An incident's `timeline` lists its Timeline lines in page order,
  each cut to 200 characters; a long timeline keeps its last 20 lines and sets `timeline_truncated`.
- A path is relative to the workspace root and uses `/`.

The envelope carries every record. It is read by the data endpoint, the live stream and the static export, never by an MCP
tool, so the MCP result limit does not apply. `prism_cli/schemas/wiki-graph-v1.json` describes every fact.

## Transition requests are copy-only

The dashboard's transition controls prepare a source-valid request for
one unique feature. For `po-handoff`, the source fields are exactly
`status: specified` and `owner: po`, and its destination is
`status: ready-for-design` with `owner:` the design owner of the scope (`designer`, or `tech-lead` when no app has a UI). The other lifecycle actions
also have source-valid browser previews backed by generated agent instructions
and CLI preflight facts; the dashboard does not execute any of them. Raw
features use the separate `po-specify` action, which verifies or authors the
structured feature body before the confirmed `raw` + `po` to `specified` + `po`
transition.

On an eligible card, **Prepare request** (including **Prepare handoff** for
`po-handoff`) opens a source-backed preview. **Copy request** copies the request
text, and **Cancel** closes the preview. Dragging a card uses the same preview
shortcut. The dialog is a request preview, not an **Approve move** control: it
does not run an agent, approve a board review, change a local card, or mutate a
feature, index, or log file.

The preview identifies the feature path, observed status and owner, workspace
identity, snapshot time and fingerprint, destination, and the selected action's
observable checks. The agent must reread the current skill or command and source
files before acting. For `po-handoff`, a pending advisory review offers an
independent board review; declining it requires a non-blank reason that remains
a proposal until the agent's final handoff confirmation. After board review
changes, the agent rereads the source and reruns the checks. The PO handoff
factual checks cover a non-empty frontmatter `apps` list with a matching
non-empty `## App scope` entry for every declared app, one singular
`## User story` section, meaningful acceptance entries, and no open PO-owned
questions. Semantic quality and the final confirmation remain human or agent
responsibilities.

The Board columns are derived from the current source fields. When a human, agent,
or other authorized process changes those fields and the source is refreshed, the
Board can show the feature in a different column. The dashboard cannot prove who
made that change or whether a confirmation happened. The intended process is for
an agent to consume the copied request, reread the source and current skill, obtain
the required confirmation, and write the documented files before the next refresh.

Static exports and copied requests are relative to their capture time; the live
server can observe later source changes. A changed identity, path, status, owner,
advisory state, or fingerprint invalidates the preview and requires a fresh one.
Snapshot time is the first observation of a cached content fingerprint, not the
time of every later read. Unchanged content keeps that time; reverting content may
reuse its earlier time while cached. The bounded cache and fingerprint do not
replace the agent's fresh source checks.
Blocked or unknown checks leave **Copy request** unavailable; review the listed
evidence or repair the source and refresh. If the CLI preflight is missing,
unsupported, or does not explicitly identify its common envelope, command facts,
capability, and action, use direct file reads; a version string alone is not
evidence of that command. If the Clipboard API is unavailable or rejects the write,
the request remains selectable for manual copying and the UI reports that fallback.
The selected generated handoff file must contain its matching
`<!-- prism:<command>-contract:vN -->` marker (the version is part of it); a missing marker means that
surface has an older unsupported contract and needs to be refreshed before
copying a request. The other agent surface is optional. Blocked or unknown
checks leave **Copy request** unavailable and provide review/repair guidance.

The generated agent workflow supports exact feature-only actions. Each one reads one source
status and owner pair, and the dashboard prepares a request for the ones below. The full registry,
with the approver role of each action, is in [`ACTIONS.md`](../template/knowledge/wiki/ACTIONS.md).

| Action | Source | Destination |
|---|---|---|
| `po-specify` | `raw` + `po` | `specified` + `po` |
| `po-handoff` | `specified` + `po` | `ready-for-design` + the design owner |
| `design-start` | `ready-for-design` + the design owner | `in-design` + the design owner |
| `design-ui-done`, `tech-design-done` | `ready-for-design` or `in-design` + the design owner | `in-design` + the design owner |
| `design-handoff` | `ready-for-design` or `in-design` + the design owner | `ready-for-dev` + `dev` |
| `dev-start` | `ready-for-dev` + `dev` | `in-dev` + `dev` |
| `dev-done` | `ready-for-dev` or `in-dev` + `dev` | `in-dev` + `dev`, or `ready-for-qa` + `qa` once every app has delivered |
| `qa-verify`, `qa-pass`, `qa-fail` | `in-dev`, `ready-for-qa` or `in-qa` | the minimum of the app stages |
| `release-done` | `in-dev` up to `ready-for-release` | the minimum of the app stages, `released` + `none` once every app is released |
| `feature-reopen` | `released` + `none` (a reopen), or a feature in development or QA (a return) | `specified`, `in-design`, or `in-dev` by selected route |

`dev-done` records substantive, verifiable Implementation and Tests evidence for every app it
names. A confirmed `feature-reopen` archives prior active evidence in `## Evidence history`,
marks route-specific `revalidation` domains, and names affected requirement/API status changes
before downstream readiness can be re-established. The design tracks and the full
confirmation/write protocol are defined in the generated `knowledge/wiki/LIFECYCLE.md` and
`knowledge/wiki/ACTIONS.md`. Browser controls for these action previews are covered by the
browser tests. The controls remain copy-only and never execute the agent writes.

## Snapshot, live state, and confidence

Graph facts are rebuilt from the current source files. The live server watches
the markdown pages consumed by the graph, manifest and Copier answers identity
inputs, queue entry names/types, generated app directory presence, all
generated lifecycle capability files under `.agents/skills/` and
`.claude/commands/`, and the calendar date. This
includes the selected `po-handoff` skill/command used by the browser request. A
relevant change refreshes the data endpoint and sends an update to connected
browsers. A failed rebuild leaves the last successful snapshot available and
retries on the next polling or request attempt.

The dashboard shows confidence and diagnostics with the facts that produced
them. Treat confidence as a navigation aid: inspect the listed source and
diagnostic before making a workflow decision. The visual surface does not
claim that a command ran, a blocker was resolved, or a review happened.

## CLI fallback

The same read model is available without a browser:

```text
prism wiki graph <workspace> --json
prism wiki graph <workspace> --mermaid --view lifecycle
prism wiki graph <workspace> --mermaid --view ego --feature F-002
prism wiki graph <workspace> --mermaid --view app --app backend
prism wiki show F-002 <workspace>
prism wiki blockers <workspace>
prism wiki app backend <workspace>
```

The committed [seeded lifecycle Mermaid diagram](wiki-visualization-demo.mmd)
can be regenerated from a populated demo stage:

```text
prism wiki graph <new-demo-directory>/populated --mermaid --view lifecycle > docs/wiki-visualization-demo.mmd
```

Use a new destination when rebuilding the fixture, then inspect the generated
JSON or Mermaid output before replacing the committed diagram.

## Capture references and boundaries

The dashboard captures are kept at:

- [Board dashboard capture](media/wiki-dashboard-board.png)
- [Graph dashboard capture](media/wiki-dashboard-graph.png)

Optional PNG/SVG graph export remains deferred. Public package installation or
release remains deferred as well; this guide describes the repository-local
CLI and synthetic demo only.
