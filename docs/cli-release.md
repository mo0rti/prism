# Prism CLI Release

Prism's release unit is distribution `prism-kit` version `0.3.0`. The user-facing command remains `prism`, and Python
imports remain under `prism_cli`. Pushing a `v*` tag runs the [release workflow](#release-workflow),
which publishes the package to PyPI and creates the GitHub release; the
[npm launcher](#npm-launcher) `@mortitech/prism` is published from the same tag.
Users install with `uv tool install prism-kit` or `pipx install prism-kit`, as the README describes.
Nothing else publishes: routine CI builds and inspects artifacts and never uploads them.

## Local and Wheel Installs

From a clean checkout, install the editable package for development:

```bash
python -m pip install -e .
prism --version
```

The package metadata installs `PyYAML` for the CLI, `copier` and `jinja2-time` for
generation, and `mcp`, `starlette` and `uvicorn` for the shared board service
(`pyproject.toml` lists the exact version ranges). The optional `e2e` extra
(`pip install -e ".[e2e]"`) adds Playwright for the browser tests. Generated
repositories still need their platform tools, such as Node.js, go-task, Docker,
a JDK, or Xcode, depending on the selected slices.

Build a wheel and test that artifact in an isolated environment:

```bash
python -m pip install --upgrade build
python -m build --wheel
python -m venv .release-check
.release-check/bin/python -m pip install dist/prism_kit-0.3.0-py3-none-any.whl
.release-check/bin/prism --version
.release-check/bin/prism doctor
```

On Windows, use `.release-check\Scripts\python.exe` and
`.release-check\Scripts\prism.exe` in the last three commands. Remove the
temporary environment after the check.

The installed package does not depend on a template copied into `site-packages`.
When run from the Prism checkout, `prism new` defaults to that local template.
When run from an installed wheel, it uses the matching release tag at the canonical
template URL: CLI `0.3.0` requires `v0.3.0` at `https://github.com/mo0rti/prism.git`.
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
python -m pip install --upgrade build twine "readme-renderer[md]"
python -m build --sdist --wheel
python -m twine check --strict dist/*
```

The package declares its license as the SPDX expression `MIT` (setuptools 77 or newer) and ships `LICENSE`, `THIRD_PARTY_NOTICES.md` and the vendored force-graph license in both the wheel and the source archive. `readme-renderer[md]` makes `twine check` render the README, which must keep absolute links and images so it displays on a package index.

The browser tests under `tests/browser` are skipped unless the `e2e` extra is
installed and `PRISM_BROWSER_E2E=1` is set; [current-status.md](current-status.md#validation)
describes how to run them.

The connected core's acceptance run, artifact hashes and remaining limits are recorded in
[connected-core-acceptance.md](connected-core-acceptance.md). Those hashes describe the
snapshot they name; build and hash the wheel again for every release candidate.
[Board handoff acceptance](board-transitions-acceptance.md) and
[CLI V2 acceptance](cli-v2-acceptance.md) are dated milestone records.

Run a broad Copier render outside the repository and inspect the generated
`prism.workspace.yml`. It should parse as YAML, carry `min_prism_cli_version: "0.3.0"`,
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

## Release Workflow

`.github/workflows/release.yml` runs when a tag matching `v*` is pushed. Its jobs run in this order, and each needs the one before it:

1. **verify-tag** fails unless the tag equals `v` plus the version in `pyproject.toml`, `prism_cli/__init__.py` and `npm/package.json`, and `CHANGELOG.md` has a section for that version.
2. **build** builds the source archive and the wheel from the tagged commit, runs `twine check --strict` with `readme-renderer[md]`, requires exactly the two expected file names, and uploads them as one artifact. Every later job publishes those same files.
3. **publish-testpypi** uploads them to TestPyPI with `pypa/gh-action-pypi-publish` and trusted publishing, in the GitHub environment `testpypi`. A file that is already on TestPyPI is skipped, so a rerun does not fail.
4. **smoke-test** installs `prism-kit==<version>` from TestPyPI (`--index-url https://test.pypi.org/simple/` with `--extra-index-url https://pypi.org/simple/` for the dependencies) into a fresh environment, retrying up to 12 times, 20 seconds apart, while the index catches up. It then runs `prism --version`, `prism workflow install . --platform backend --apply --yes` and `prism doctor --workspace .` in a temporary folder.
5. **publish-pypi** uploads the same files to PyPI with trusted publishing, in the GitHub environment `pypi`. A required reviewer on that environment turns this job into a manual approval.
6. **github-release** creates the GitHub release for the tag with the source archive, the wheel and a `SHA256SUMS.txt`. The release notes are the matching `CHANGELOG.md` section. A version with an `a`, `b`, `rc` or `dev` suffix is marked as a pre-release.

`.github/workflows/npm-release.yml` starts when the Release workflow completes successfully for a tag and publishes the npm launcher, as the [npm launcher](#npm-launcher) section describes.

Neither workflow stores a token. PyPI, TestPyPI and npm accept the workflow's short-lived OIDC identity instead, so each registry must trust this repository, workflow file and environment.

### One-time owner setup

Do these once, before the first tag.

1. **GitHub environments.** In the repository, open Settings, Environments, and create `testpypi`, `pypi` and `npm`. Add yourself as a required reviewer on `pypi`, and on `npm` if you want a second approval before the launcher is published.
2. **TestPyPI trusted publisher.** Sign in at <https://test.pypi.org>, open Your account, Publishing, and add a pending publisher with these values:
   - PyPI project name: `prism-kit`
   - Owner: `mo0rti`
   - Repository name: `prism`
   - Workflow name: `release.yml`
   - Environment name: `testpypi`
3. **PyPI trusted publisher.** Sign in at <https://pypi.org>, open Your account, Publishing, and add a pending publisher with the same values, except Environment name: `pypi`.
4. **npm organization.** Create the organization `mortitech` on <https://www.npmjs.com>, so the scope `@mortitech` exists and you can publish under it.

A pending publisher creates the project on its first upload and then becomes the project's trusted publisher. The npm trusted publisher is added after the first npm publish, as described under [Publishing the launcher](#publishing-the-launcher).

### Releasing a version

1. Set the version in `pyproject.toml`, `prism_cli/__init__.py` and `npm/package.json`, set the release date in the changelog section, and make sure CI is green on the commit to tag.
2. Create and push the tag: `git tag -a v<version> -m "Prism <version>"`, then `git push origin v<version>`.
3. Watch the Release workflow and approve the `pypi` environment when it asks. After it succeeds, the npm release workflow runs.

A tag that does not equal the versions fails in the first job, before anything is published. Do not move or reuse a tag after PyPI has accepted the files; PyPI never accepts the same version twice, so a fix needs a new version.

## npm Launcher

`@mortitech/prism` (the `npm/` folder) is a small Node package without runtime dependencies. Its `prism` command runs `uv tool run --from prism-kit==<version> prism <arguments>` with inherited streams and passes uv's exit code through, so `npx @mortitech/prism <command>` works without a Python setup. The npm version equals the Prism version, a release bumps both together, and the launcher always runs the `prism-kit` version equal to its own. It needs Node.js 22 or later.

It finds uv in this order:

1. the file named by `PRISM_UV`;
2. `uv` on the `PATH`;
3. the cached download at `%LOCALAPPDATA%\prism\uv\<uv version>` on Windows, or `$XDG_CACHE_HOME/prism/uv/<uv version>` (default `~/.cache/prism/uv/<uv version>`) elsewhere;
4. a one-time download of the pinned uv release for Windows, macOS or Linux on x64 or arm64 from `https://github.com/astral-sh/uv/releases`. The archive is unpacked only after its SHA-256 equals the digest pinned in `npm/lib/platform.js`; a mismatch discards the download and stops with the expected and the actual value.

Two more variables matter. `HTTPS_PROXY` (an `http://` proxy URL; `NO_PROXY` exempts hosts) applies to the uv download, and uv itself reads it for PyPI. `PRISM_PACKAGE_SPEC` replaces the `prism-kit==<version>` that uv runs, for example with a local wheel path; it exists for tests. On a normal run the launcher prints nothing of its own. Before a download it writes one `Prism: downloading uv ...` line to stderr, and it never prints environment values.

### Moving to a newer uv

The uv version and the digests of its eight downloads (macOS, Windows and Linux on gnu and musl) are constants in `npm/lib/platform.js`. To move to another uv release, read `https://github.com/astral-sh/uv/releases/download/<version>/sha256.sum`, replace `UV_VERSION` and every digest from that file, and run `npm test` in `npm/`. The tests check the mapping, the file names and the digest format, and `PRISM_LAUNCHER_NETWORK_TEST=1 npm test` downloads the real release and runs it.

### Checking the launcher locally

From `npm/`, `npm test` runs the Node tests offline. Then build a wheel and run the packed launcher against it, which needs no PyPI release:

```bash
python -m build --wheel --outdir ../dist-launcher-check ..
npm pack --pack-destination ../dist-launcher-check
npm install --global ../dist-launcher-check/mortitech-prism-0.3.0.tgz
PRISM_PACKAGE_SPEC=../dist-launcher-check/prism_kit-0.3.0-py3-none-any.whl prism --version
npm uninstall --global @mortitech/prism
```

CI does the same on Ubuntu, macOS and Windows (job `npm-launcher` in `cli-validation.yml`) and also runs the Node tests with the real uv download.

### Publishing the launcher

`npm-release.yml` runs after the Release workflow succeeded for a tag. It checks that the tag points at the built commit and equals the npm version, runs `npm test`, and publishes with `npm publish --provenance --access public` using npm trusted publishing, in the GitHub environment `npm`. It publishes nothing when that version is already on npm.

npm accepts a trusted publisher only for a package that exists, so **the owner publishes the first version by hand**:

1. After the Release workflow has put `prism-kit==<version>` on PyPI, run `npm login`, then `npm publish --access public` in `npm/`. npm asks for the one-time code from your authenticator.
2. On <https://www.npmjs.com/package/@mortitech/prism>, open Settings, Trusted Publisher, choose GitHub Actions and enter: organization or user `mo0rti`, repository `prism`, workflow filename `npm-release.yml`, environment name `npm`.
3. Optionally set the package's publishing access to require two-factor authentication and disallow tokens.

Until the package exists, the npm release workflow ends with a warning and publishes nothing. Between the first publish and step 2, a new version fails at the publish step. Afterwards every tag publishes through the workflow.
