# Prism CLI Release Preparation

Prism's local release candidate is currently prepared as distribution
`prism-kit` version `0.2.0`. The user-facing command remains `prism`, and Python
imports remain under `prism_cli`. The package has not been published to PyPI;
publication is a later, explicit step.

## Local and Wheel Installs

From a clean checkout, install the editable package for development:

```bash
python -m pip install -e .
prism --version
```

The package metadata installs the generation prerequisites `copier`, `jinja2-time`,
and `PyYAML`. Generated repositories still need their platform tools, such as
Node.js, go-task, Docker, a JDK, or Xcode, depending on the selected slices.

Build a wheel and test that artifact in an isolated environment:

```bash
python -m pip install --upgrade build
python -m build --wheel
python -m venv .release-check
.release-check/bin/python -m pip install dist/prism_kit-0.2.0-py3-none-any.whl
.release-check/bin/prism --version
.release-check/bin/prism doctor
```

On Windows, use `.release-check\Scripts\python.exe` and
`.release-check\Scripts\prism.exe` in the last three commands. Remove the
temporary environment after the check.

The installed package does not depend on a template copied into `site-packages`.
When run from the Prism checkout, `prism new` defaults to that local template.
When run from an installed wheel, it uses the matching release tag at the canonical
template URL: CLI `0.2.0` requires `v0.2.0` at `https://github.com/mo0rti/prism.git`.
A missing tag fails generation; there is no fallback to a newer template.
Publish and validate that tag before publishing the matching wheel.
An explicit `--template <path-or-url>`
always takes precedence. Wheel generation therefore requires network access unless
the caller supplies a local template path.

## Validation Before Publication

Run the checks from the repository root. Install `jsonschema` for the contract
tests; Node.js is needed for the dashboard boot checks.

```bash
python -m pip install -e . jsonschema
python -m unittest tests.test_workspace_contract
python -m unittest discover -s tests
python -m pip install --upgrade build twine
python -m build --sdist --wheel
python -m twine check dist/*
```

The current handoff delivery's local checks and artifact hashes are recorded in
[board-transitions-acceptance.md](board-transitions-acceptance.md). The earlier
[CLI V2 acceptance](cli-v2-acceptance.md) remains a historical milestone record.

Run a broad Copier render outside the repository and inspect the generated
`prism.workspace.yml`. It should parse as YAML, carry `min_prism_cli_version: "0.2.0"`,
and include a timestamp and the template commit when that metadata is available.
Run a CLI generation as well; the CLI post-processing step records the actual CLI
version, source, template version or commit, and generation timestamp.

The workspace contract is intentionally conservative:

- schema 1 manifests load normally
- older readable manifests expose known fields with a warning and are not migrated
  implicitly
- newer, malformed, or unreadable manifests produce diagnostics and are never
  rewritten by read commands
- a missing manifest falls back to Copier answers and filesystem facts with degraded
  confidence
- `prism status`, `prism status --full`, `prism status --json`, and
  `prism doctor --workspace` are read-only; only explicit generation or update
  workflows refresh manifest provenance

`status --full` reports documented generation answers, effective wiki settings,
advisory review counts, and template provenance. Private Copier metadata and unknown
answer keys are omitted from human and JSON status output.

## Publication Boundary

Keep PyPI publication pending until the wheel install, canonical-template generation,
template render, CLI status/doctor, and generated-project checks have all been
reviewed. Do not infer publication readiness from a successful local build, and do
not run a publish command as part of routine CI. The current repository prepares and
validates release artifacts without publishing them.
