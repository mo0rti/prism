# Current Status

Prism's core workflow, adoption commands and shared human/agent board are implemented in the working tree. The final r7 run passed 385 tests with one platform-specific skip and no failures, plus installed-wheel and generation checks. Actual browser acceptance and the focused review of the final corrections remain open. Application generation remains an optional entry path. The [core plan](prism-core-workflow-plan.md) records the approved scope and acceptance gates; [connected-core acceptance](connected-core-acceptance.md) records current evidence and remaining limits. Earlier [lifecycle acceptance](lifecycle-transitions-acceptance.md) covers the legacy read-only preview and agent-skill path, not the new connected write service.

## Core and sample boundaries

| Area | Current boundary |
| --- | --- |
| Wiki, queries, lint, board and lifecycle preflight | Existing core implementation with regression tests; nine named actions retain their source/owner and evidence rules. |
| Shared human/agent service | Local HTTP and standard MCP adapters share versioned skills, participant grants, previews, writes and recovery. Fable's initial implementation review found no high-severity defects and judged its snapshot implementation-ready. Its four low findings are corrected and final integrated checks pass. The focused follow-up could not start because of Claude's session limit; actual browser acceptance is blocked. Connected writes require an explicit compatible workflow installation. |
| Workflow adoption | `prism workflow install` and `upgrade` support existing repositories and empty workspaces without generating application code. Generated workspaces also explicitly activate connected writes through an upgrade preview. |
| Application generation | Existing Copier path. Custom template execution requires explicit trust; installed default generation requires the matching release tag. |
| Smart template update | Requires truthful versioned provenance. An unversioned local working snapshot cannot supply a merge baseline; explicit recopy remains a separate operation. |
| Backend, web, Android and iOS samples | Partial scaffolds. Remaining sample findings are deferred by the user's core-focus decision. Do not treat generation or a sample build as proof of workflow collaboration. |
| Apple Sign-In and native mobile runtime | Experimental or incompletely verified. Android emulator and macOS/Xcode evidence must be recorded separately. |
| Public release | Not established by local tests. License ownership/terms, canonical release tags and publication remain separate release gates. |

## What the validation commands do

- `python -B -m unittest discover -s tests` runs the Python regression suite; some tests also invoke generation or a JavaScript harness.
- `scripts/check-installed-cli.py` exercises an installed CLI outside the source checkout, including generation and template updates.
- `./scripts/validate-template.ps1 -Mode contract` checks generated structure and workflows with actionlint, including a standalone web selection.
- The script's default `full` mode also runs backend smoke checks. Both `full` and `contract` call the web helper with `-RunSmoke $false`.
- `.github/workflows/template-validation.yml` defines a separate `web-smoke` job for npm install, lint, typecheck, auth checks, Next.js/OpenNext builds and Wrangler dry runs. Its presence does not prove a current successful CI run or a live deployment.

Historical passing results describe their recorded source snapshots. The [September 22 remediation review](reviews/2026-09-22-opus5-remediation-review.md) identifies the remaining core and sample issues at its frozen snapshot. The plan records their scope and disposition; current implementation must pass its own acceptance checks.

## Evaluating application generation

Choose a focused platform selection, inspect the generated files, and run that platform's actual build/runtime checks. PostgreSQL, Azure backend hosting and Cloudflare/OpenNext web hosting are the currently offered choices; Redis is an optional supporting service. The five existing platform IDs are retained as workflow scope labels initially, even when an adopted workspace has no corresponding application directory.

Read [maintainer-workflow.md](maintainer-workflow.md) for exact maintainer commands and [getting-started.md](getting-started.md) for the generation path.
