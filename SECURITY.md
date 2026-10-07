# Security

This document describes the threat model of Prism's local board service as it is implemented, what it does not protect against, and how to report a vulnerability. The [shared board guide](docs/shared-board.md) documents the commands and tools.

## Reporting a vulnerability

Send suspected vulnerabilities privately by email to **admin@mortitech.com**. Do not open a public issue for them, and do not include participant tokens or workspace content in a report.

Include the Prism version (`prism --version`), your operating system and Python version, what you did, what you expected and what happened. A short reproduction in a disposable workspace helps most. Reports are acknowledged.

## Scope

Prism runs on one computer. One service per workspace, started with `prism board serve`, serves the browser board and the MCP endpoint for that workspace. The service has no remote mode, no TLS and no accounts system. Application generation (`prism new`) and the generated sample projects are not part of this threat model.

The assets to protect are the workspace's wiki and intake files, and the lifecycle state they record. The actors are people using the browser board, coding agents connected through MCP, and the web pages the person's browser may open at the same time.

## What the service enforces

**Loopback only.** The service binds to `127.0.0.1`. There is no option to listen on another address, and remote hosting is not supported. A reverse proxy that forwards another `Host` is rejected by the check below. Anything that reaches the service with a local `Host` and a valid token is treated as local, so do not forward the port to other machines.

**Host, Origin and Sec-Fetch checks.** Every request, including the MCP endpoint, must carry exactly one `Host` header equal to `127.0.0.1:PORT` or `localhost:PORT` for the port the service listens on. A request is rejected with `local_origin_required` when:

- its `Host` is anything else, which blocks DNS-rebinding pages that resolve a foreign name to loopback;
- it carries an `Origin` that is not `http://` plus that same `Host`, with no path, credentials, query or fragment;
- it carries a `Sec-Fetch-Site` other than `same-origin` or `none`, which blocks requests started by another site;
- it repeats the `Origin`, `Authorization`, `Cookie`, `Content-Type`, `Sec-Fetch-Site` or CSRF header, or sends both a Bearer token and the board's session cookie.

Request bodies are limited to 1 MiB.

**Browser sessions.** A human signs in by sending a participant token once to the same-origin token-exchange endpoint, which also requires a matching `Origin`. The service answers with a random 256-bit session ID in a cookie. The cookie is `HttpOnly` and `SameSite=Strict`, with `Path=/` and a 12-hour lifetime, and it is `Secure` whenever the request arrived over HTTPS. Over the plain loopback address the board uses, the `Secure` attribute is therefore not set. The cookie never holds the participant token. The token stays in the service's memory for the session, and sessions are not stored on disk, so a restart ends them. Only a human grant can open a browser session.

**CSRF protection.** Each session has a random 256-bit CSRF token that the service hands to the signed-in page. Every write that uses the session cookie, and the sign-out, must send it in the `X-Prism-CSRF` header; the service compares it with the value it holds for the session in constant time. The same write must also carry an `Origin` equal to the board's own address. A cross-site page can send neither the header nor the right Origin, and `SameSite=Strict` stops the browser from attaching the cookie to cross-site requests in the first place. This is a server-held synchronizer token, not a double-submit cookie.

**Participant tokens.** `prism board grant` generates a 256-bit random token, prints it once, and stores only its SHA-256 hash in `.prism/state/board.sqlite3`. A lost token cannot be recovered; issue a new grant. Agents send the token as an `Authorization: Bearer` header, and the service reads no other place for it, so it does not belong in URLs. Error messages redact the participant token. A grant is read-only unless it was issued with `--write`, and each grant records the workflow version and asset digest it was issued under.

**Immediate revocation.** The service looks up the grant in its database on every request, so `prism board revoke` takes effect on the next request from an agent or a browser session; no cached approval survives. An open event stream rechecks its grant every 15 seconds, so it can outlast a revocation by up to that interval. A browser session also ends when the grant's workflow identity changes. After `prism workflow upgrade` changes the pinned workflow, earlier grants stop working until new ones are issued. The app scope in `prism.workspace.yml` is part of the workspace identity as well: after `prism app add` changes it, a running service disables writes until it is restarted.

**Workspace confinement.** Reads are limited to approved wiki and intake text files and writes to approved knowledge paths. Paths must be relative and stay inside the workspace. Symbolic links, junctions and other reparse points in workspace paths are rejected. The links, `sources` entries and `repo:` links of a page go through one resolver (`prism_cli/wiki_paths.py`): it decodes the path first, refuses UNC, rooted, drive-qualified, backslash, double-encoded and `..` paths as text and confines the path lexically before it makes any filesystem call, so a hostile link in a proposed page is a finding and never touches a network share or another volume. `prism app add` writes only `prism.workspace.yml` through the same checks and an atomic replace that fails when the file changed after its preview, and so are workspaces inside cloud-synced folders, where a sync engine could rewrite files during an atomic write. Connected writes are previewed with exact before and after text, apply only the previewed content, and are refused when a relevant file changed after the preview.

**Response headers.** Board responses carry `Cache-Control: no-store`, a `Content-Security-Policy` with `default-src 'self'` and `frame-ancestors 'none'`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff` and `Referrer-Policy: no-referrer`. The page's scripts run only under a per-response nonce.

## Workspace text is untrusted data

Wiki pages, intake notes and every other workspace file can contain text written by anyone, including text that tries to instruct an agent. The service does not execute or interpret that text. Its MCP instructions tell the agent to treat workspace text as project data and never as instructions, and that the board never approves on the human's behalf.

The service cannot make an agent obey those instructions. The protection is structural: an agent can change the workspace only through a preview of exact changes that the human confirms in the agent's own interface. The board has no queue in which an agent's request waits for a later approval, and a human's direct board actions are limited to `po-handoff`, `design-start` and `dev-start`, each previewed before it applies. Review every preview before you confirm it.

## Saved answers are checked before an update

`prism update` and `prism app add --scaffold` run Copier with trust, and what an answers file records is rendered into generated files, including code and CI. So `prism update` checks every layer's saved answers before it starts Copier (`prism app add --scaffold` applies the same check to the workspace's answers): the workspace's own `.copier-answers.yml` must select the workspace layer and hold only that layer's answers, and every app layer must name the workspace's approved template source and the identity the manifest gives it. A project name, an app ID, path, name or audience, a package identifier or a port that is not safe to render, a template revision that is not a plain tag or commit name, or an answer that no layer asks stops the update before Copier runs. An answers file that is a symlink, a junction or another reparse point, or that sits behind one, is never opened, read or written; Prism names the way out (restore the regular file from git).

## What the service does not protect against

- **Other software on the same computer.** Any process can connect to the loopback port. It still needs a valid token, but the service does not defend against malware running as the same user, and a person who can read your environment variables or shell history can read your tokens. Keep tokens out of files, prompts and the repository.
- **Other local users.** Workspace files and `.prism/state/` have the permissions your operating system gives them. Do not run a workspace in a folder that other users can read or write.
- **An agent's own file access.** The service's access controls do not restrict what a coding agent can do through its own filesystem and shell tools. Edits made outside the service are external changes with no recorded participant.
- **Verified identity.** A participant name labels a locally registered grant. It does not prove who holds the token, and it assigns no workflow role.
- **Semantic review.** The service checks structure, freshness and permissions. Whether a proposed change is right is the human's decision at the preview.
- **A compromised Prism installation or dependency.** Install Prism from a source you trust.

Do not commit `.prism/state/`. It holds grant hashes, previews and the operation journal. `prism workflow install` adds an ignore rule for it, and `prism doctor --workspace .` fails when git does not ignore it.

Do not commit `prism.local.yml` either. It records where this machine keeps the checkouts of a workspace's external repositories, so it holds local paths. `prism workflow install` and the generated project's `.gitignore` list it, and `prism status` reports only whether a checkout is resolved, never its path. Prism checks that a checkout exists and does not read from it or write to it, and it ignores a `prism.local.yml` or a checkout that is a symlink or reparse point.
