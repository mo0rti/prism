# @mortitech/prism

Run [Prism](https://github.com/mo0rti/prism), the shared workflow and board for humans and coding agents, without setting up Python.

```bash
npx @mortitech/prism --version
npx @mortitech/prism workflow install . --name "My workspace" --app backend
```

Or install the command once:

```bash
npm install --global @mortitech/prism
prism --version
```

The package is a thin launcher. It runs `uv tool run --from prism-kit==<version> prism <arguments>` with your terminal's input and output and returns Prism's exit code. The npm version equals the Prism version, so `@mortitech/prism@0.6.0` runs `prism-kit==0.6.0` from PyPI. [uv](https://docs.astral.sh/uv/) creates an isolated environment for it, and downloads a suitable Python when none is installed. The first run needs network access to PyPI.

For the quickstart and the full command reference, see the [Prism README](https://github.com/mo0rti/prism#readme) and the [shared board guide](https://github.com/mo0rti/prism/blob/main/docs/shared-board.md).

## Requirements

- Node.js 22 or later.
- Windows, macOS or Linux on x64 or arm64.

## How uv is found

1. The executable that `PRISM_UV` names.
2. `uv` on your `PATH`.
3. A copy this launcher downloaded earlier, kept in `%LOCALAPPDATA%\prism\uv\<uv version>` on Windows or `$XDG_CACHE_HOME/prism/uv/<uv version>` (default `~/.cache/prism/uv/<uv version>`) elsewhere.
4. Otherwise the launcher downloads one pinned uv release from `github.com/astral-sh/uv` into that cache folder. It compares the archive with the SHA-256 digest pinned in this package before unpacking anything, and stops without installing if the digest differs.

Delete the cache folder to remove the downloaded uv.

## Environment variables

| Variable | Effect |
| --- | --- |
| `PRISM_UV` | Full path of the uv executable to use. |
| `HTTPS_PROXY` | An `http://` proxy URL for the uv download. `NO_PROXY` lists hosts that skip it. uv reads `HTTPS_PROXY` itself for PyPI. |
| `PRISM_PACKAGE_SPEC` | Replaces `prism-kit==<version>`, for example with the path of a local wheel. It exists for testing. |

The launcher prints nothing of its own on a normal run. Before a download it writes one line to stderr, and it never prints environment values.

## License

MIT. See `LICENSE`.
