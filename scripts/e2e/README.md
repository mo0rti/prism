# End-to-end journey

`journey.py` runs one feature through the whole Prism lifecycle with real agent hosts (Claude Code and Codex) and a headless browser against a disposable board, then writes one comparable report. The feature goes from intake to release, through a QA failure with its bug, a failed release attempt and its retry, an incident, and a reopen. An agent only proposes an action the board gates; a human grant that holds exactly the roles the action needs approves it in the board. The only cost of a run is the participants' tokens. Failure diagnosis is a separate step done from the saved transcripts; the script never re-runs a failed step and never coaches an agent.

## Run it

Run from the repository root with a Python that has Playwright (`pip install -e ".[e2e]"`):

```
python -B scripts/e2e/journey.py --tier smoke --out <dir>
python -B scripts/e2e/journey.py --tier full  --out <dir>
python -B scripts/e2e/journey.py --tier smoke --out <dir> --steps dev-clarify,dev-done
python -B scripts/e2e/journey.py --tier smoke --out <dir> --steps tech-design-done,design-handoff --fixtures scripts/e2e/fixtures-api-work
```

| Option | Meaning |
| --- | --- |
| `--tier smoke\|full` | Models and effort for both hosts (below). Required. |
| `--out <dir>` | Report, transcripts and logs go here. The folder must not hold an earlier run. Required. |
| `--steps a,b,...` | A subset of the steps, in any order; the script runs them in lifecycle order and seeds the state each one needs. Default: every step. |
| `--hosts claude,codex` | Hosts that may run agent steps. A step whose fixed host is not listed runs on the first listed host. |
| `--wheel <path>` | Install this wheel instead of building one from the current tree. |
| `--keep-work` | Keep `<out>/work/` (virtual environment, workspace, wheel) after the run. |
| `--timeout <seconds>` | Timeout per host run. Default 600. |
| `--fixtures <dir>` | A fixture set overlaid on the default fixtures and prompts (below). Default: the `PRISM_E2E_FIXTURES` variable, else the default set alone. |

Requirements:

- Claude Code and Codex installed and signed in. The script uses the npm package's `claude.exe` (the `claude.cmd` shim cuts multi-line prompts) and `codex.exe`, found next to the npm shims; `PRISM_E2E_CLAUDE` and `PRISM_E2E_CODEX` override the search.
- Playwright for the Python that runs the script. `PRISM_BROWSER_E2E_EXECUTABLE` selects an existing Chromium, as in `tests/browser`; without it Playwright's bundled browser runs.
- `uv` is used to build and install the wheel when it is on PATH; otherwise `pip`.
- Network access for the hosts and for installing the wheel's dependencies.

The exit code is 0 when every selected step passed and the token scan is clean, 1 otherwise, and 130 after Ctrl+C.

## Tiers

Every launch sets the model and effort explicitly. The report reads what actually ran from the hosts' own records and fails a step whose model or effort differs.

| Tier | Claude Code | Codex | Use |
| --- | --- | --- | --- |
| `smoke` | `claude-haiku-5-5`, medium | `gpt-6-luna`, medium | A cheap check after each change. Weaker models expose guidance regressions first, so a failed step is a finding, not noise. |
| `full` | `claude-sonnet-5-5`, medium | `gpt-6.1-sol`, medium | Before a release. |

Cost comes from the hosts' own reports. A gated agent step is one host run (the preview); an ungated one is two (preview and apply). The journey has 20 agent steps, ten on each host: 14 gated steps with one host run each and six ungated steps with two, so 26 host runs, plus the browser. The report records the actual tokens, cost and time of every step and a total for each host. A host run takes 1 to 6 minutes.

## Steps

The steps run in this order. Agent steps alternate between the two hosts by this fixed table.

- **Ungated agent steps** (six) are two host runs: a preview run (stop at the preview and report its ID) and an apply run (apply that preview under a new operation ID). The agent applies its own preview.
- **Gated agent steps** (fourteen) are one host run: the agent previews, stops and reports the preview ID. The runner then approves the proposal in the board as the human grant that holds exactly the roles in the table (next section). The board refuses an agent's own apply of a gated preview, so no agent apply run exists for them.
- **Direct human steps** (three) are the board's direct human actions. They run in the browser, signed in as the grant that holds their roles, through `tests/browser/board_page.py`.

| # | Step | Actor | Approved or applied by (roles) | State after the step |
| --- | --- | --- | --- | --- |
| 1 | `po-intake` | Claude | the agent (ungated) | `raw`, owner `po`; the pending brief moved to processed |
| 2 | `ask` | Codex | the agent (ungated) | one more question, routed to the product owner |
| 3 | `po-clarify` | Claude | the agent (ungated) | no open product-owner question |
| 4 | `po-specify` | Codex | `po` | `specified`, `po` |
| 5 | `po-handoff` | browser | `po` | `ready-for-design`, `tech-lead` |
| 6 | `design-start` | browser | `tech-lead` | `in-design`, `tech-lead`; `design-tracks` initialized (UI track `not-applicable` for the backend-only scope, technical track `pending`) |
| 7 | `design-clarify` | Claude | the agent (ungated) | no open designer question |
| 8 | `tech-design-done` | Codex | `tech-lead` | `in-design`, `tech-lead`; the technical track `done` with its technical design page (and the agreed API contract when the feature declares API work) |
| 9 | `design-handoff` | Claude | `tech-lead` | `ready-for-dev`, `dev`; the requirement page of the backend app generated (the developer's question stays open) |
| 10 | `dev-clarify` | Codex | the agent (ungated) | no open developer question; the answer is a new acceptance criterion and a requirement, because the App scope is locked from `ready-for-dev` on |
| 11 | `dev-start` | browser | `dev` | `in-dev`, `dev` |
| 12 | `dev-done` | Claude | `dev` | `ready-for-qa`, `qa`; delivery evidence of `commit:3f9c2ab`, the requirement `done` |
| 13 | `qa-verify` | Codex | `qa` | `in-qa`, `qa`; the first attempt `qa-1` passes every criterion but the one about the comments not shown, which fails; the bug BUG-001 is open |
| 14 | `qa-fail` | Claude | `qa` | `in-dev`, `dev`; the delivery and QA rows archived in `## Evidence history`, the requirement `in-progress` |
| 15 | `bug-start` | Codex | `dev` | BUG-001 `in-fix` |
| 16 | `bug-fixed` | Claude | `dev` | BUG-001 `fixed`, owner `qa`, with its Fix row for `commit:5d7a1e4` |
| 17 | `dev-redeliver` | Codex | `dev` | `ready-for-qa`, `qa`; delivery evidence of `commit:5d7a1e4` |
| 18 | `bug-verify` | Claude | `qa` | BUG-001 `verified`, owner `release`, with a passing Verification row on the delivered artifact |
| 19 | `qa-pass` | Codex | `qa` | `ready-for-release`, `release`; a passing second attempt `qa-2` that cites every criterion, and a pending Release row |
| 20 | `release-done` | Claude | `release` | still `ready-for-release`; the first attempt fails: record `REL-001` (outcome `failed`, with BUG-001) and a `failed` Release row on the feature and the bug |
| 21 | `release-retry` | Codex | `release` | `released`, `none`; the retry is `release-2`, record `REL-002` (`retry-of: REL-001`), BUG-001 `released` |
| 22 | `ingest-incident` | Claude | the agent (ungated) | the pending incident report processed into the open incident `INC-001` for `REL-002`, with an unknown cause |
| 23 | `feature-reopen` | Codex | `dev` | `in-dev`, `dev`; the delivery, QA and Release rows archived in `## Evidence history` (`reopen-dev`); both release records stay |

Prompts are fixed text in `prompts/`: one file per agent step plus `apply.txt`, which only the six ungated steps use. They are short, name no host or model, and ask the agent to follow the board's guidance. Where a skill asks the agent to show its interpretation and wait (the two ingest steps), the prompt confirms the interpretation in advance. The three clarify prompts hold an `{answers}` placeholder that the script fills at run time (below); the `ingest-incident` prompt holds an `{intake_folder}` placeholder for the name of its pending folder (below); every other prompt is sent as written. Under the retry rule, an agent may retry a rejected proposal inside its run; the script adds nothing.

## The approval step

The board lets only a human whose grant holds the action's roles apply a gated action, in a browser session. The run therefore creates one writable human grant for each role set the steps need, holding exactly those roles: `human-po`, `human-tech-lead`, `human-dev`, `human-qa` and `human-release`. An agent grant never holds a role.

For a gated agent step the runner does this after the agent's preview run:

1. It signs in to the board as the step's grant, typing the token into the board's token form (it signs out and in again when another grant's session is open).
2. It opens Proposals, finds the proposal by the preview ID the agent reported (read from the board's own list), opens it with Review, ticks the review acknowledgement and presses Approve and apply. It saves the review text and the dialog afterwards in `transcripts/NN-step.approval.json`.
3. It reads the operation back through the board's HTTP API with the approver's token and checks the receipt, never what the agent said:
   - `applied_by_role_holder`: the actor is a human, is the grant the table names and holds exactly the step's roles;
   - `proposed_by_agent`: the proposer is the agent grant of the step's host;
   - `approval_roles_as_expected`: the board required exactly the step's roles.

A direct human step is applied from the card action as the same kind of grant and passes `applied_by_role_holder`. The report lists who approved or applied each step with the roles, the route and the operation in its Approvals section.

## Answers at run time

An agent writes its own question set, so the clarify steps (`po-clarify`, `design-clarify`, `dev-clarify`) do not answer fixed questions. Before the preview run the script reads the feature page, takes the open questions owned by the step's role (`po`, `designer`, `dev`) and fills the prompt's `{answers}` placeholder with one line per question: its number, its text and the owner's answer.

- A question whose topic is scripted gets the scripted answer. The scripted topics and their answers are in `prism_e2e/answers.py`: for the product owner, finished-review eligibility, export access and comment ownership, the header, comment order, no comments, format and channel, overflow and language; for the designer, the summary's layout and arrangement and the export control's location; for the developer, delivery and generation, generation constraints and failures, review data and eligibility, and the app that presents the export control. A topic matches by words in the question text; the first matching topic of that role wins.
- The decisions permit export only after the reviewer records approved, changes requested or rejected, and include only that reviewer's comments. The backend generates the PDF on request in its existing stack, returns it as a download in the same response and stores no generated file. Generation is limited to 5 seconds and a PDF of at most 1 MiB; failure returns an error with no partial download. The tech-lead prompt supplies these technical decisions and a test strategy covering each criterion at unit and service level, for both fixture sets.
- Any other open question gets its role's fixed fallback as the owner's own reply. The developer is told, `The technical design page settles this; build it as that page says.` The product owner and designer are told, `Out of scope for this release: the feature does not include it.` Each fallback adds a note to the step result naming the step, question number and question text before the host launches, so it remains visible even if the step fails. The prompt asks the agent to paste each answer exactly as written into that question's row and to change only the sections the skill allows, so every answer stays traceable to its question and the agent invents nothing.
- A role with no open question gets a line saying there is nothing to answer.
- The prompt that was sent is saved under `transcripts/` (`NN-step.preview.prompt.txt`) with the filled answers.

The checks do not change: `no_open_po_questions`, `no_open_designer_questions` and `no_open_dev_questions` still require that no open question of the role is left after the apply.

## Subsets and seeding

A step runs on the state its predecessor leaves. `--steps` therefore seeds that state from recorded fixtures (`fixtures/<step>/`, the files each step writes) whenever the predecessor is not the step that ran last. `--steps dev-clarify,dev-done` seeds the state after `design-handoff`, runs `dev-clarify`, seeds the state after `dev-start`, and runs `dev-done`. Seeding rebuilds the journey files of the workspace and the feature's row in the status board, with the Bugs and Operations tables, then runs `prism wiki lint`; a seeded state that lint rejects fails the steps that depend on it. A step that fails marks the steps that depend on it as skipped; a later seed clears the dependency. The input of an ingest step (`po-intake`, `ingest-incident`) is copied into the pending intake folder right before the step runs, from the file its fixtures hold under the processed path. The incident report is dated on the day of `REL-002`: before `ingest-incident` runs, the script reads the `date` of `knowledge/wiki/releases/REL-002.md` in the workspace (a live run writes it with the day of the run), names the pending folder `<day>-release-incident`, puts that day in the report's `Reported by support on <day>.` line, and derives the processed folder, the permitted move, the expected manifest path, the `intake_moved` check and the prompt's folder from the same day (`workspace.intake_folder`). The times in the report stay relative to the release. With the fixture `REL-002`, dated 2026-10-09, the folder and the text are the fixtures' own.

## Fixture sets

`fixtures/` is the default set: a backend-only feature whose API surface says `None.`, so no API contract page exists. `--fixtures <dir>` (or `PRISM_E2E_FIXTURES`) names a set that overlays it. A set holds `<step>/` folders in the layout of `fixtures/` and, optionally, `prompts/<step>.txt` files. Within a step a set's file replaces the default file with the same path; a step or a prompt the set does not hold comes from the default set. The report names the set. Every step has fixtures: the files its proposal writes, as the board holds them afterwards. The last step's fixtures serve the tests; no step seeds from them.

`fixtures-api-work/` is the second set: the feature's API surface declares one endpoint, so from `po-specify` on every state carries that text, and the states from `tech-design-done` on hold the contract page (`agreed`; `implemented` after each `dev-done`, `agreed` again after `qa-fail` and the reopen; the Delivery evidence cites it and the release records hold a snapshot of it) and the requirement page that links it. Its prompts tell `po-specify` to record the endpoint, `dev-clarify` to leave the API surface alone and `dev-done` and `dev-redeliver` to cite and mark the contract. Start a run with it at `po-specify` or later: the earlier steps keep the default states and prompts. After `tech-design-done` the journey also checks that the contract page exists at `agreed`, and after `design-handoff` that the requirement page links it. Every set holds the technical design page from `tech-design-done` on.

The board refuses `qa-fail` of a feature whose API contract is `implemented`: its candidate lint reports `delivered-api-contract`, which the return routes ignore and `qa-fail` does not. A run with the API-work set therefore stops at `qa-fail` and skips the steps after it until the board accepts that proposal. The fixtures after `qa-fail` are authored and replay once it does.

The unit tests validate both sets against the step table, the question tables, the narrative of the QA, bug, release and incident steps and the result checks. `python -B -m unittest tests.test_e2e_fixtures` (from the repository root) lints every state of both sets and replays the whole journey on the real board service: each agent step previews the proposal its fixtures hold, a gated preview is refused to its own agent and to every human grant that lacks the step's roles, and the grant that holds exactly the roles approves it. The files the board writes must equal the fixtures. The same replay runs the API-work set through the first QA attempt, and to the end once the board accepts `qa-fail` of an implemented contract.

## Checks

After every apply the script checks, through the board's HTTP API and the workspace files, never through what the agent said:

- the operation receipt reads `applied`;
- who applied it: a human grant that holds exactly the step's roles, and for a gated step the agent grant of the host as the proposer;
- the feature page and its status board row show the expected stage and owner;
- `prism wiki lint` reports no error (the design handoff leaves the developer's open question as the one expected `unresolved-open-questions` error);
- step-specific facts:
  - `po-intake`: the intake folder moved. `ask`: one question added and routed to the product owner. The clarify steps: no open question left for the owner who clarified.
  - `tech-design-done`: both design tracks settled, the technical design page, and for API work the agreed contract. `design-handoff`: the requirement page generated, and for API work linking the contract.
  - `dev-done` and `dev-redeliver`: one active Delivery evidence row for the expected commit, the requirement `done`, and for API work the contract `implemented` and cited.
  - `qa-verify`: passing and failing QA rows of `qa-1`, the failing one being the criterion about the comments not shown, and BUG-001 open, owned by `dev` and linked to the feature. `qa-fail`: no active evidence row, an Evidence history entry that links BUG-001, the requirement `in-progress`, and for API work the contract `agreed`.
  - `bug-start`, `bug-fixed`, `bug-verify`: BUG-001's status and owner, its Fix row, and its passing Verification row on the delivered artifact.
  - `qa-pass`: every active QA row passes on `qa-2` for the delivered artifact and together they cite every criterion; one pending Release row for `release-1`.
  - `release-done`: the record `REL-001` is `failed` and names BUG-001, the Release rows of the feature and of the bug read `release-1`, `failed`, BUG-001 stays `verified`, and there is no second record. `release-retry`: `REL-002` is `released` and retries `REL-001`, the Release rows read `release-2`, BUG-001 is `released`, and `REL-001` still records the failure.
  - `ingest-incident`: INC-001 is open for `REL-002` and the backend app, its cause starts with `Unknown:`, the intake folder moved with a manifest, the Operations table lists the incident, and no other bug page exists.
  - `feature-reopen`: the `reopen-dev` entry in the Evidence history, no active evidence row, and both release records still present;
- the host's records name the configured model and effort.

An agent step also fails when the host times out or exits non-zero, when no preview was produced, when the agent applied during the preview run, or when it reported no preview ID that its own calls returned. On a gated step, an apply the board refused with `approval_required` wrote nothing: the step goes on to the approval, notes the attempt and does not count as a first-attempt success. A gated step fails when the proposal is not in the approver's Proposals list or the board refuses the approval; an ungated step fails when its apply run did not apply.

## Report

`<out>/report.md` and `report.json` hold, per step: host, model and effort as recorded by the host (Claude Code's session file; Codex's rollout `turn_context`), preview attempts, first-attempt success, the error codes of rejected previews and of other tools, the apply result, the checks, elapsed time, and token usage and cost where the host reports it. For a gated or direct human step they also hold the approval: the human grant, its roles, the route and the operation. A totals section groups by host and tier. The report also records the product version, the wheel's SHA-256, the host versions and the seeded states.

- `transcripts/`: sanitized host output (`NN-step.preview.<host>.stdout.jsonl` and `.apply.`), stderr, prompts, final messages, metadata, `NN-step.approval.json` for approved steps (the proposal's list entry, the review text, the dialog afterwards) and `NN-step.human.json` for direct human steps (preview and applied dialog text, the exact writes).
- `logs/`: setup commands (grants shown without tokens, with their roles), board output and browser worker output.
- `screenshots/`: a page screenshot after a failed browser step or approval.

## Token safety, limits and cleanup

- The human and agent grants are created in this run. Tokens live only in process memory and in the environment of the one process that needs each: an agent token in `PRISM_BOARD_TOKEN` for its host, and the human tokens as one JSON object in `PRISM_E2E_TOKENS` for the browser worker, which types a token into the board's own form and nowhere else. The hosts read their token through an MCP configuration that references the variable. Every saved text passes through an exact-match redaction, and before the run ends every saved file is scanned for each token. A hit fails the run and the file is redacted in place.
- The user's Claude Code and Codex configuration is not changed. Claude Code runs with `--strict-mcp-config` and no built-in tools; Codex gets its board server through `-c` overrides.
- Each host run has a timeout. On timeout, on Ctrl+C or on any failure, the board, the hosts and the browser worker are stopped and their process trees killed. The working folder is deleted unless `--keep-work` is set.

## Unit tests

The tests need no host, network or browser:

```
python -B -m unittest discover -s scripts/e2e/tests
```

They cover step selection, the role table and the seeding plan, the fixtures and the second fixture set against the step table and the story of the QA, bug, release and incident steps, the status board views the seeding rebuilds, the result checks of every step on its own fixtures, the approval step with the host launches, the board and the browser replaced (who approves, which receipt fields are checked, a refused approval, an ungated step, the dependency rules), the browser's proposal lookup and session switching, how the tokens reach the browser worker, report building, the token scan, transcript parsing, host command lines, the prompts and their agreement with the fixtures, the run-time answers for a recorded and for a different question set, the text decoding of `scripts/check-installed-cli.py` and process handling. `python -B -m unittest discover -s tests` does not collect them; `tests/test_e2e_fixtures.py` replays the fixtures on the real board.
