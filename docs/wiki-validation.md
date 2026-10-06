# Wiki Validation

This page summarizes how the Prism wiki usability layer is validated and what confidence
that gives you.

## What Is Validated

The wiki usability layer is validated in three ways:

- template-render validation
- runtime-style fixture validation against a seeded wiki corpus
- Python regression tests of the CLI read layer (`prism wiki lint`, `show`, `blockers`,
  `owner`, `app`, `search`, `transition-preflight` and `graph`), which the generated
  commands use as their primary path when a compatible CLI is installed

## Validation Method

The wiki operations are agent instructions, not standalone binaries.

So runtime-style validation means:

1. generate a real project from the template
2. seed a realistic wiki corpus
3. follow the generated command and skill contracts against that corpus
4. verify both:
   - output behavior
   - filesystem side effects

Where write behavior is part of the contract, the validation run also inspects the
resulting files.

## Fixture Approach

The runtime-style validation uses a reusable fixture builder:

- `scripts/build-runtime-validation-fixture.ps1`

The seeded fixture includes:

- valid features
- incomplete features
- broad search coverage
- malformed pages

This makes it possible to exercise both normal and failure/partial-state behavior.

Representative seeded scenarios included:

- a complete feature
- a feature with pending board review
- a feature missing a design page
- a feature missing app requirements for one app
- a feature with unresolved open questions plus a draft API contract
- a broad auth-heavy search corpus for refinement testing
- a malformed feature page missing required state

## What `prism wiki lint` Checks

Lint is mechanical. It checks structure (front matter, enums, duplicate IDs, the index and the status
board), links, unresolved conflicts and freshness, and never judges whether a claim is true or whether two
claims contradict each other; detecting a contradiction is the ingest skill's job.

- **Links.** `broken-link` (error) for a relative Markdown link or a `sources` entry that does not resolve,
  with the page, the link and the line; `broken-anchor` (warning) for a heading anchor that no heading
  gives; `external-repository-unresolved` (warning, once per repository) for `repo:<repository-id>/<path>`
  links into a repository with no checkout in `prism.local.yml`. URLs are never fetched, and an external
  checkout is only asked whether a path exists.
- **Conflicts.** `unresolved-conflict` (warning) and `malformed-conflict` (error) for quarantined sources.
- **Freshness.** `stale-page` (warning) when a current-state page's last `verify` entry in `log.md` is older
  than `wiki-stale-after-days`, and `never-verified` (information) when it has none. Freshness never changes
  a status and never blocks a transition.

`verify-pages` and `prism wiki verify` are covered by Python regression tests: each appends exactly one `verify`
entry in the log format, never touches a page, and refuses a path outside the wiki and an unknown page. No
agent host ran them.

## Validated Wiki Operations

### `feature-status`

Validated:

- creates `knowledge/wiki/WIKI_REPORT.md`
- writes the required summary sections
- stays within the boundary of refreshing only the generated report

Required generated sections validated:

- project summary
- features by lifecycle stage
- advisory review snapshot
- open questions by owner
- blocker snapshot
- recently changed wiki pages
- structural health pointer
- suggested next actions

### `lint-wiki`

Validated:

- reports diagnostics in the response and writes no wiki file by default
- does not rewrite `WIKI_REPORT.md`
- creates a dated lint report and appends to `knowledge/wiki/log.md` only when the user
  explicitly asks for a persisted report

### `wiki-show`

Validated for:

- complete feature case
- partial feature case
- missing feature case

That means the command was exercised against:

- fully linked feature context
- incomplete linked context
- invalid/missing feature identifiers

### `wiki-blockers`

Validated for:

- blocker category detection
- malformed-page reporting
- no-blockers behavior

### `wiki-query`

Validated for:

- cross-page matches
- no-results behavior
- broad-query refinement prompt

The refinement case was checked against a corpus broad enough to exceed the V1 compact
result threshold.

### `wiki-owner`

Validated for:

- owner grouping
- invalid-owner handling

### `wiki-app`

Validated for:

- app-specific inclusion filtering
- blocker reporting
- invalid-app handling

This included checking that only the app IDs of the workspace are treated as valid.

## What This Means

This gives the wiki usability layer stronger support than a purely theoretical spec.

The current confidence level is:

- the template renders the wiki layer correctly (`scripts/validate-template.ps1 -Mode contract` checks the rendered files)
- the command/skill contracts were exercised against a realistic seeded corpus
- write/read boundaries were inspected explicitly

## What It Does Not Mean

This is still not the same thing as a compiled automated test harness for each command.

The remaining boundary is that these operations are still prompt-driven agent behavior.
So validation shows:

- the template contract is coherent
- the outputs and side effects are well specified and were checked against the fixture

But it does not make the layer immune to future prompt drift if those command/skill files
change.

It also does not replace real user feedback about output length, pacing, or day-to-day
ergonomics.

## Remaining Open Item

One validation item remains intentionally qualitative:

- shorten output if it is too verbose for agent consumption

That is a tuning question rather than a correctness question.

## Bottom Line

The wiki usability layer has:

- command and skill support in generated projects
- template-render validation
- fixture-based runtime validation
- Python regression tests for the CLI read layer

The remaining work in this area is documentation and long-term tuning.

## Related Docs

- [wiki-workflow.md](wiki-workflow.md)
- [prism-model.md](prism-model.md)
- [generated-projects.md](generated-projects.md)
