# Current Status

Prism's core is the workflow and the shared board that humans and agents use together. It runs on one computer: `prism board serve` starts one local service per workspace that serves the browser board and a standard MCP endpoint. Application generation is an optional way to start a workspace. The [core plan](prism-core-workflow-plan.md) states the scope and contracts. [Shared board](shared-board.md) is the usage guide, [troubleshooting](troubleshooting.md) covers failures, and [SECURITY.md](../SECURITY.md) is the threat model. [Connected-core acceptance](connected-core-acceptance.md) is the dated record of the connected service's acceptance run.

## Core

| Area | Current state |
| --- | --- |
| Wiki, queries, lint and lifecycle preflight | Implemented with regression tests. The nine lifecycle actions keep their exact source and owner pairs and their evidence rules. `prism wiki` commands, the `prism wiki graph` dashboard and static exports are read-only and copy-only. |
| Workflow adoption | `prism workflow install` and `prism workflow upgrade` preview every file, then apply on `--apply`. They work in empty workspaces, existing repositories and generated projects, and they do not generate application code. Cloud-synced folders such as OneDrive and Dropbox Files On-Demand are rejected. |
| Shared service | The local HTTP and MCP adapters share one service with revocable participant grants, exact previews, operation receipts and recoverable writes. A workspace opens read-only until its workflow pin matches this installation. |
| MCP tool contract 2 | Tool results are at most 32,000 characters. Long text and lists arrive in pages with opaque cursors and digests, `get_skill_reference` returns skill references, and the server publishes orientation instructions. A workspace pinned to an earlier contract needs `prism workflow upgrade` and new grants, as [shared-board.md](shared-board.md#upgrading-to-contract-2) describes. |
| Human board actions | The board performs `po-handoff`, `design-start` and `dev-start` directly. The other six actions stay with agent skills, which the board offers as a copyable MCP request. |
| Agent skills | 24 canonical skills are served through MCP. Connected writes are available for the skills that [shared-board.md](shared-board.md#work-together) lists. Custom skills keep the direct-file path. |
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

Board work grows about linearly with the number of features. On a synthetic workspace of 1,000 features, an idle change scan takes about 60 ms every 1.5 s, a preview about 1.1 s, an `apply` about 6.4 s, a blockers query about 1.9 s and a graph rebuild about 3 s. At 100 features, a preview takes about 0.3 s and an `apply` about 1.3 s. The change poller reuses file hashes for unchanged files and rehashes everything at least every 60 seconds. An edit that keeps both a file's size and modification time can go unnoticed by the poller for up to 60 seconds, while previews and applies always re-read the files they depend on. No response or refresh budget is agreed, so these figures describe the board and are not a guarantee. The [changelog](../CHANGELOG.md) lists the speed-ups.

## Application samples

The generated samples are working starting points, not verified products.

| Platform | Verification |
| --- | --- |
| Backend | The backend tests pass on JDK 21 for each rendered variant, and the `V4` migration is checked on PostgreSQL. The `backend-smoke` CI job packages the boot jar and builds the Docker image. |
| Android | Unit tests pass, and instrumented tests and an emulator sign-in pass on a local emulator. The `android-build` CI job runs the unit tests, `assembleDebug` and lint. |
| Web (user app and admin portal) | Install, lint, typecheck, the auth check script, the Next.js build and the Cloudflare build pass locally for both apps. The `web-smoke` CI job adds a Wrangler dry run. No live Cloudflare deployment has been verified. |
| iOS | Swift compilation and tests are verified only by the `ios-build` job on a macOS runner in `template-validation.yml`, which has not run yet. Treat the iOS sample as unverified until that job passes. |

Sign in with Apple and the native mobile runtime remain experimental. A generated sample build is not evidence that human and agent collaboration works; core acceptance uses disposable neutral workspaces. Azure backend hosting, Cloudflare/OpenNext web hosting and PostgreSQL are the offered deployment and database choices, and Redis is an optional supporting service. No live deployment has been verified.

## Public release

Local tests do not establish a public release. License terms and holder, the release version and tag, and publication are separate gates. An installed CLI generates from the template tag that matches its version, and a missing tag fails generation.

## Evaluating application generation

Choose a focused platform selection, inspect the generated files, and run that platform's own build and runtime checks. The five platform IDs are workflow scope labels, even in an adopted workspace that has no matching application directory.

Read [maintainer-workflow.md](maintainer-workflow.md) for the maintainer commands and [getting-started.md](getting-started.md) for the generation path.
