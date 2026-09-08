# Wiki Visualization

Prism's wiki visualization is an optional local read surface for a generated
workspace. It derives its facts from `knowledge/wiki/`, intake queues, the
workspace manifest and answers, and selected platform directories. The wiki
files remain the source of truth. The dashboard does not edit them.

## Try the TreasuryFlow demo

The repository includes a repeatable synthetic fixture for the TreasuryFlow
finance operations story: payout requests, manager approval, and finance-admin
settlement/history review. Build it into a new empty directory:

```text
python scripts/build-wiki-demo.py --destination <new-demo-directory> --stage all --today 2026-09-08 --json
```

The builder refuses an existing destination. It creates three capture-ready
stages:

| Stage | What it demonstrates |
|-------|----------------------|
| `fresh` | An empty wiki and Guide setup path before the advisory board is initialized |
| `intake` | A pending payout brief and a quarantined item visible in the intake queues |
| `populated` | Three features across `raw`, `in-dev`, and `done`, with platform requirements, designs, API contracts, personas, business rules, a decision, a review, an open question, and a canonical blocker |

The fixture is synthetic local documentation. It contains no production data,
observed project history, deployment evidence, compliance claim, or recorded
human review. The default platform story is backend, Android, and iOS, with
operator, manager, and finance-admin roles.

Open the populated stage after installing the local CLI:

```text
prism wiki graph <new-demo-directory>/populated --open
prism wiki graph <new-demo-directory>/populated --serve --port 8321
```

The `--open` command creates a one-off snapshot for the browser. `--serve`
keeps the dashboard live and refreshes when relevant source files change. Both
surfaces are read-only. The inspector exposes the source path for a selected
wiki node. Board intake cards identify their queue and item name; manifest and
answers inputs remain visible through workspace metadata and confidence
diagnostics.

## What the views mean

| View | Use it for |
|------|------------|
| Graph | Follow relationships between features, personas, rules, designs, API contracts, platform requirements, decisions, reviews, and platforms. Search and filters narrow the visible map; selecting a node opens its source context. |
| Board | Read feature work in lifecycle columns and see intake pending/quarantine visibility alongside workflow blockers. A first feature makes the brief and intake step complete; the guide does not reopen a completed step when the brief leaves the queue. |
| Platforms | Compare the selected platform's feature targets and platform requirement pages, including requirement status. |
| Guide | Understand setup, intake, and review state before navigating the graph. Completion is derived from current files and feature presence. |

The dashboard separates workflow blockers from page integrity. A pending
review or open question is a workflow obligation. A malformed page or stale
page is a source health diagnostic; stale or advisory warnings are not called
malformed pages.

## Snapshot, live state, and confidence

Graph facts are rebuilt from the current source files. The live server watches
the markdown pages consumed by the graph, manifest and Copier answers identity
inputs, queue entry names/types, selected platform directory presence, and the
calendar date used for staleness checks. A relevant change refreshes the data
endpoint and sends an update to connected browsers. A failed rebuild leaves the
last successful snapshot available and retries on the next polling or request
attempt.

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
prism wiki graph <workspace> --mermaid --view platform --platform backend
prism wiki show F-002 <workspace>
prism wiki blockers <workspace>
prism wiki platform backend <workspace>
```

The committed [seeded lifecycle Mermaid diagram](wiki-visualization-demo.mmd)
can be regenerated from a populated demo stage:

```text
prism wiki graph <new-demo-directory>/populated --mermaid --view lifecycle > docs/wiki-visualization-demo.mmd
```

Use a new destination when rebuilding the fixture, then inspect the generated
JSON or Mermaid output before replacing the committed diagram.

## Capture references and boundaries

The local acceptance captures are kept at:

- [Board dashboard capture](media/wiki-dashboard-board.png)
- [Graph dashboard capture](media/wiki-dashboard-graph.png)

Optional PNG/SVG graph export remains deferred. Public package installation or
release remains deferred as well; this guide describes the repository-local
CLI and synthetic demo only.
