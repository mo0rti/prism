# Current Status

Prism's core is the workflow and the shared board that humans and agents use together. It runs on one computer: `prism board serve` starts one local service per workspace that serves the browser board and a standard MCP endpoint. Application generation is an optional way to start a workspace. The [core plan](prism-core-workflow-plan.md) states the scope and contracts. [Shared board](shared-board.md) is the usage guide, [troubleshooting](troubleshooting.md) covers failures, and [SECURITY.md](../SECURITY.md) is the threat model.

## Core

| Area | Current state |
| --- | --- |
| Wiki, queries, lint and lifecycle preflight | Implemented with regression tests. The nine lifecycle actions keep their exact source and owner pairs and their evidence rules. `prism wiki` commands, the `prism wiki graph` dashboard and static exports are read-only and copy-only. |
| Workflow adoption | `prism workflow install` and `prism workflow upgrade` preview every file, then apply on `--apply`. They work in empty workspaces, existing repositories and generated projects, and they do not generate application code. Cloud-synced folders such as OneDrive and Dropbox Files On-Demand are rejected. |
| Shared service | The local HTTP and MCP adapters share one service with revocable participant grants, exact previews, operation receipts and recoverable writes. A workspace opens read-only until its workflow pin matches this installation. |
| Apps and repositories | `prism.workspace.yml` declares repositories and apps; each app has a stack with `has-ui` and `serves-api` capabilities. Status, wiki lint and query output, and the board report `apps`, and status also reports `repositories`. `prism app list` and `prism app add` show and register apps without generating code, and a workspace may have no apps. [workspace-model.md](workspace-model.md) describes the model. Feature scope still uses the five generated app IDs. |
| MCP tool contract 3 | Tool results are at most 32,000 characters. Long text and lists arrive in pages with opaque cursors and digests, `get_skill_reference` returns skill references, the server publishes orientation instructions, and `discover` lists the board's `apps`. A workspace pinned to an earlier workflow digest needs `prism workflow upgrade` and new grants, as [shared-board.md](shared-board.md#upgrading-a-pinned-workspace) describes. |
| Human board actions | The board performs `po-handoff`, `design-start` and `dev-start` directly. The other six actions stay with agent skills, which the board offers as a copyable MCP request. |
| Agent skills | 26 canonical skills are served through MCP. Connected writes are available for the skills that [shared-board.md](shared-board.md#work-together) lists. Custom skills keep the direct-file path. |
| `prism doctor --workspace` | A read-only "Shared board" section checks the cloud-sync location, the workflow pin, active grants, the default port and git ignore of `.prism/state`. Only `[fail]` lines change the exit code. |
| Smart template update | Needs a remote template source with a saved revision. A project generated from a local checkout records an unversioned snapshot that supplies no merge baseline, and `prism update --strategy recopy` is the explicit alternative. |
| Remote access | Not supported. The service listens on loopback only. |

## Validation

- `python -B -m unittest discover -s tests` runs the Python regression suite. The suite includes real MCP SDK transport tests, human and agent parity tests and the dashboard script harness. The POSIX terminal test is skipped on Windows, and the browser tests are skipped unless they are enabled.
- The browser suite in `tests/browser` drives the real board in Chromium through Playwright. Its scenarios cover pointer and keyboard apply, stale and lost-response handling, no-write paths, revocation and recovery, two viewers, event-stream reconnects and server restart, legacy and static copy-only views, `prism board serve` start and stop, and desktop, tablet and phone layouts with focus checks. Install the `e2e` extra (`pip install -e ".[e2e]"`), set `PRISM_BROWSER_E2E=1` and run `python -B -m unittest discover -s tests/browser -t .`. `PRISM_BROWSER_E2E_EXECUTABLE` selects an existing Chromium, and `PRISM_BROWSER_E2E_DIR` selects the folder for workspaces and screenshots. The `browser-e2e` job in `.github/workflows/cli-validation.yml` runs it and fails when every test is skipped. Visual sign-off on themes and viewports is an owner review, not an automated result.
- `scripts/check-installed-cli.py` exercises an installed CLI outside the source checkout, including generation and template updates. The `wheel` job in `cli-validation.yml` runs it.
- `./scripts/validate-template.ps1 -Mode contract` checks generated structure and workflows with actionlint, including a standalone web selection. The default `full` mode also runs backend smoke checks. Both modes call the web helper with `-RunSmoke $false`.
- `.github/workflows/template-validation.yml` has separate `backend-smoke`, `web-smoke`, `android-build` and `ios-build` jobs. A configured job is not evidence of a passing run.
- `scripts/measure-board-scale.py` measures a synthetic workspace at a chosen number of features (see below).

## Board performance

Board work grows about linearly with the number of features. On a synthetic workspace of 1,000 features, an idle change scan takes about 60 ms every 1.5 s, a preview about 1.1 s, an `apply` about 6.4 s, a blockers query about 1.9 s and a graph rebuild about 3 s. At 100 features, a preview takes about 0.3 s and an `apply` about 1.3 s. The change poller reuses file hashes for unchanged files and rehashes everything at least every 60 seconds. An edit that keeps both a file's size and modification time can go unnoticed by the poller for up to 60 seconds, while previews and applies always re-read the files they depend on. The [changelog](../CHANGELOG.md) lists the speed-ups.

**Budgets.** The board is held to these 95th-percentile budgets per workspace size. A change that exceeds one is a regression to fix, not a figure to loosen.

| Metric (p95) | 100 features | 500 features | 1,000 features |
| --- | ---: | ---: | ---: |
| Idle change scan, workspace unchanged | 0.04 s | 0.10 s | 0.20 s |
| Graph rebuild after a change | 0.6 s | 3.0 s | 5.5 s |
| `preview_transition` | 0.7 s | 2.5 s | 5.0 s |
| `query` blockers | 0.7 s | 2.5 s | 5.0 s |
| `apply` (`po-handoff`) | 1.6 s | 5.5 s | 12 s |
| Cold start to the first `/data.json` | 2.5 s | 5.0 s | 8.0 s |
| `/data.json` request | 0.05 s | 0.10 s | 0.15 s |
| CPU of one core, no viewers | 3% | 8% | 12% |
| Peak memory (RSS) | 128 MiB | 192 MiB | 256 MiB |

**Reference machine.** Windows 11 with an Intel Core i9-14900KF (32 logical cores) and CPython 3.12.7, with the board service and the measuring client in one process. A slower machine scales every row by one factor; do not loosen single rows.

**How to measure.** Run `python scripts/measure-board-scale.py --out <dir> --sizes 100,500,1000` with the interpreter that has Prism's board dependencies installed. It builds a deterministic synthetic workspace per size in a temporary folder under `--out`, measures the real service, HTTP app and MCP tools on disposable copies, and writes `scale-results.json` and `scale-results.md`. The figures are timings, so they are compared by hand against the budgets and are not asserted in unit tests.

**Guard.** `tests/test_board_hot_path_counts.py` counts the repeated work of the same paths (page parses, file opens, workspace fingerprints, graph-input validations, lint runs and graph builds) on workspaces of 24 and 48 features. The counts are exact on every machine, so a regression fails as a counted extra read, never as a flaky timing.

## Application samples

The generated samples are working starting points, not verified products.

| Platform | Verification |
| --- | --- |
| Backend | The backend tests pass on JDK 21 for each rendered variant, and the `V4` migration is checked on PostgreSQL. The `backend-smoke` CI job packages the boot jar and builds the Docker image. |
| Android | Unit tests pass, and instrumented tests and an emulator sign-in pass on a local emulator. The `android-build` CI job runs the unit tests, `assembleDebug` and lint. |
| Web (user app and admin portal) | Install, lint, typecheck, the auth check script, the Next.js build and the Cloudflare build pass locally for both apps. The `web-smoke` CI job adds a Wrangler dry run. No live Cloudflare deployment has been verified. |
| iOS | Swift compilation and tests are verified by the `ios-build` job on a macOS runner in `template-validation.yml`, which passes. There is no local iOS check on Windows or Linux. |

Sign in with Apple and the native mobile runtime remain experimental. A generated sample build is not evidence that human and agent collaboration works; core acceptance uses disposable neutral workspaces. Azure backend hosting, Cloudflare/OpenNext web hosting and PostgreSQL are the offered deployment and database choices, and Redis is an optional supporting service. No live deployment has been verified.

## Public release

Prism 0.4.0 is released under the MIT license, copyright 2026 Mortitech: `prism-kit` on [PyPI](https://pypi.org/project/prism-kit/), with the wheel, source distribution and `SHA256SUMS.txt` attached to the [GitHub release](https://github.com/mo0rti/prism/releases/tag/v0.4.0). Releases are published by `.github/workflows/release.yml` from a `v*` tag through TestPyPI to PyPI with trusted publishing. An installed CLI generates from the template tag that matches its version (`v0.4.0`). The npm launcher [`@mortitech/prism`](https://www.npmjs.com/package/@mortitech/prism) 0.4.0 is on npm and runs `prism-kit==0.4.0` through uv.

## Evaluating application generation

Choose a focused platform selection, inspect the generated files, and run that platform's own build and runtime checks. The five platform IDs are workflow scope labels, even in an adopted workspace that has no matching application directory.

Read [maintainer-workflow.md](maintainer-workflow.md) for the maintainer commands and [getting-started.md](getting-started.md) for the generation path.
