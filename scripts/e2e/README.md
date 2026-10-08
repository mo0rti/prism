# End-to-end journey

`journey.py` runs the Prism lifecycle with real agent hosts (Claude Code and Codex) and a headless browser against a disposable board, then writes one comparable report. The only cost of a run is the participants' tokens. Failure diagnosis is a separate step done from the saved transcripts; the script never re-runs a failed step and never coaches an agent.

## Run it

Run from the repository root with a Python that has Playwright (`pip install -e ".[e2e]"`):

```
python -B scripts/e2e/journey.py --tier smoke --out <dir>
python -B scripts/e2e/journey.py --tier full  --out <dir>
python -B scripts/e2e/journey.py --tier smoke --out <dir> --steps dev-clarify,dev-done
python -B scripts/e2e/journey.py --tier smoke --out <dir> --steps design-handoff,dev-start --fixtures scripts/e2e/fixtures-api-work
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
| `smoke` | `claude-haiku-4-5` (no effort setting; its session records carry none) | `gpt-6-luna`, medium | A cheap check after each change. Weaker models expose guidance regressions first, so a failed step is a finding, not noise. |
| `full` | `claude-sonnet-5-5`, medium | `gpt-6.1-sol`, medium | Before a release. |

Rough cost, from the hosts' own reports: a smoke agent step (preview run plus apply run) used about 0.15 to 0.25 USD of Claude Haiku, and about 0.8 to 1.5 million input tokens of Codex Luna (mostly cached; 4,000 to 12,000 output tokens). Codex reports tokens but no cost. A complete smoke journey has five Claude steps and four Codex steps, so about 1 USD of Claude and about 5 million Codex input tokens. The full tier runs the same steps on larger models; its report records the actual tokens and cost. A host run takes 1 to 6 minutes, so a complete run takes about 30 to 45 minutes.

## Steps

The steps run in this order. Agent steps alternate between the two hosts by this fixed table. Each agent step is two host runs: a preview run (stop at the preview and report its ID) and an apply run (apply that preview under a new operation ID). The three human steps are the board's direct human actions and run in the browser through `tests/browser/board_page.py`.

| # | Step | Actor | State after the step |
| --- | --- | --- | --- |
| 1 | `po-intake` | Claude | `raw`, owner `po`; the pending brief moved to processed |
| 2 | `ask` | Codex | one more question, routed to the product owner |
| 3 | `po-clarify` | Claude | no open product-owner question |
| 4 | `po-specify` | Codex | `specified`, `po` |
| 5 | `po-handoff` | browser | `ready-for-design`, `tech-lead` |
| 6 | `design-start` | browser | `in-design`, `tech-lead` |
| 7 | `design-clarify` | Claude | no open designer question |
| 8 | `design-handoff` | Codex | `ready-for-dev`, `dev` (the developer's question stays open) |
| 9 | `dev-clarify` | Claude | no open developer question |
| 10 | `dev-start` | browser | `in-dev`, `dev` |
| 11 | `dev-done` | Codex | `ready-for-qa`, `qa`, delivery evidence recorded |

Prompts are fixed text in `prompts/`: one file per agent step plus `apply.txt`. They are short, name no host or model, and ask the agent to follow the board's guidance. The three clarify prompts hold an `{answers}` placeholder that the script fills at run time (below); every other prompt is sent as written. Under the retry rule, an agent may retry a rejected proposal inside its run; the script adds nothing.

## Answers at run time

An agent writes its own question set, so the clarify steps (`po-clarify`, `design-clarify`, `dev-clarify`) do not answer fixed questions. Before the preview run the script reads the feature page, takes the open questions owned by the step's role (`po`, `designer`, `dev`) and fills the prompt's `{answers}` placeholder with one line per question: its number, its text and the owner's answer.

- A question whose topic is scripted gets the scripted answer. The scripted topics and their answers are in `prism_e2e/answers.py`: for the product owner the format and channel, comments that overflow one page, date or version and languages; for the designer the export control and the summary's look; for the developer the app that presents the export control. A topic matches by words in the question text.
- Any other open question of the role gets the role's fixed fallback decision, `Not needed for this release; decide later.`, as the owner's own reply. The prompt asks the agent to paste each answer exactly as written into that question's row and to change only the sections the skill allows, so every answer stays traceable to its question and the agent invents nothing.
- A role with no open question gets a line saying there is nothing to answer.
- The prompt that was sent is saved under `transcripts/` (`NN-step.preview.prompt.txt`) with the filled answers.

The checks do not change: `no_open_po_questions`, `no_open_designer_questions` and `no_open_dev_questions` still require that no open question of the role is left after the apply.

## Subsets and seeding

A step runs on the state its predecessor leaves. `--steps` therefore seeds that state from recorded fixtures (`fixtures/<step>/`, the files each step writes) whenever the predecessor is not the step that ran last. `--steps dev-clarify,dev-done` seeds the state after `design-handoff`, runs `dev-clarify`, seeds the state after `dev-start`, and runs `dev-done`. Seeding rebuilds the journey files of the workspace and the feature's row in the status board, then runs `prism wiki lint`; a seeded state that lint rejects fails the steps that depend on it. A step that fails marks the steps that depend on it as skipped; a later seed clears the dependency.

## Fixture sets

`fixtures/` is the default set: a backend-only feature whose API surface says `None.`, so no API contract page exists. `--fixtures <dir>` (or `PRISM_E2E_FIXTURES`) names a set that overlays it. A set holds `<step>/` folders in the layout of `fixtures/` and, optionally, `prompts/<step>.txt` files. Within a step a set's file replaces the default file with the same path; a step or a prompt the set does not hold comes from the default set. The report names the set.

`fixtures-api-work/` is the second set: the feature's API surface declares one endpoint, so from `po-specify` on every state carries that text, and the states from `design-handoff` on hold the contract page (`agreed`, `implemented` after `dev-done`) and the requirement page that links it. Its prompts tell `po-specify` to record the endpoint, `dev-clarify` to leave the API surface alone and `dev-done` to mark the contract implemented. Start a run with it at `po-specify` or later: the earlier steps keep the default states and prompts. After `design-handoff` the journey also checks that the contract page exists at `agreed` and that the requirement page links it.

The unit tests validate both sets against the step table and the question tables. `python -B -m unittest tests.test_e2e_fixtures` (from the repository root) lints every state, previews the `design-handoff` and `dev-done` proposals against the real board service and runs the `dev-start` preflight.

## Checks

After every apply the script checks, through the board's HTTP API and the workspace files, never through what the agent said:

- the operation receipt reads `applied`;
- the feature page and its status board row show the expected stage and owner;
- `prism wiki lint` reports no error (the design handoff leaves the developer's open question as the one expected `unresolved-open-questions` error);
- step-specific facts: intake folder moved, one question added and routed to the product owner, no open question left for the owner who clarified, an agreed API contract page that the requirement page links after a `design-handoff` of a feature whose API surface declares API work, delivery evidence recorded;
- the host's records name the configured model and effort.

An agent step also fails when the host times out or exits non-zero, when no preview was produced, when the agent applied during the preview run, or when it reported no preview ID that its own calls returned.

## Report

`<out>/report.md` and `report.json` hold, per step: host, model and effort as recorded by the host (Claude Code's session file; Codex's rollout `turn_context`), preview attempts, first-attempt success, the error codes of rejected previews and of other tools, the apply result, the checks, elapsed time, and token usage and cost where the host reports it. A totals section groups by host and tier. The report also records the product version, the wheel's SHA-256, the host versions and the seeded states.

- `transcripts/`: sanitized host output (`NN-step.preview.<host>.stdout.jsonl` and `.apply.`), stderr, prompts, final messages, metadata, and `NN-step.human.json` for browser steps (preview and applied dialog text, the exact writes).
- `logs/`: setup commands (grants shown without tokens), board output and browser worker output.
- `screenshots/`: a page screenshot after a failed browser step.

## Token safety, limits and cleanup

- The human and agent grants are created in this run. Tokens live only in process memory and in the environment of the one process that needs each (`PRISM_BOARD_TOKEN`); the hosts read them through an MCP configuration that references the variable. Every saved text passes through an exact-match redaction, and before the run ends every saved file is scanned for each token. A hit fails the run and the file is redacted in place.
- The user's Claude Code and Codex configuration is not changed. Claude Code runs with `--strict-mcp-config` and no built-in tools; Codex gets its board server through `-c` overrides.
- Each host run has a timeout. On timeout, on Ctrl+C or on any failure, the board, the hosts and the browser worker are stopped and their process trees killed. The working folder is deleted unless `--keep-work` is set.

## Unit tests

The tests need no host, network or browser:

```
python -B -m unittest discover -s scripts/e2e/tests
```

They cover step selection and the seeding plan, the fixtures and the second fixture set against the step table, report building, the token scan, transcript parsing, host command lines, the prompts, the run-time answers for a recorded and for a different question set, the text decoding of `scripts/check-installed-cli.py` and process handling. `python -B -m unittest discover -s tests` does not collect them.
