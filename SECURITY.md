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

**Participant tokens.** `prism board grant` generates a 256-bit random token, prints it once, and stores only its SHA-256 hash in `.prism/state/board.sqlite3`. A lost token cannot be recovered; issue a new grant. Agents send the token as an `Authorization: Bearer` header, and the service reads no other place for it, so it does not belong in URLs. Error messages redact the participant token. A grant is read-only unless it was issued with `--write`, and each grant records the workflow version and asset digest it was issued under. A writable human grant may also hold workflow roles (`--role qa,release`), which are fixed for the grant's life; see [Roles and gated approval](#roles-and-gated-approval).

**Immediate revocation.** The service looks up the grant in its database on every request, so `prism board revoke` takes effect on the next request from an agent or a browser session; no cached approval survives. An open event stream rechecks its grant every 15 seconds, so it can outlast a revocation by up to that interval. A browser session also ends when the grant's workflow identity changes. After `prism workflow upgrade` changes the pinned workflow, earlier grants stop working until new ones are issued. The app scope in `prism.workspace.yml` is part of the workspace identity as well: after `prism app add` changes it, a running service disables writes until it is restarted.

**Workspace confinement.** Reads are limited to approved wiki and intake text files and writes to approved knowledge paths. Paths must be relative and stay inside the workspace. Symbolic links, junctions and other reparse points in workspace paths are rejected. The links, `sources` entries and `repo:` links of a page go through one resolver (`prism_cli/wiki_paths.py`): it decodes the path first, refuses UNC, rooted, drive-qualified, backslash, double-encoded and `..` paths as text and confines the path lexically before it makes any filesystem call, so a hostile link in a proposed page is a finding and never touches a network share or another volume. `prism app add` writes only `prism.workspace.yml` through the same checks and an atomic replace that fails when the file changed after its preview, and so are workspaces inside cloud-synced folders, where a sync engine could rewrite files during an atomic write. Connected writes are previewed with exact before and after text, apply only the previewed content, and are refused when a relevant file changed after the preview. A replacement that Windows refuses for a moment is retried for about a second, and every check made before the first attempt (the participant's grant, confinement, the expected content or intake tree, and the relevant sources) is made again before each retry; a change in between is a conflict, never an overwrite. The relevant sources are bound as a set when the operation is validated, both which pages belong to it and their content, so a requirement, design or contract page that appears during the wait is a change like an edit; the baseline is never taken again after a refusal.

**Response headers.** Board responses carry `Cache-Control: no-store`, a `Content-Security-Policy` with `default-src 'self'` and `frame-ancestors 'none'`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff` and `Referrer-Policy: no-referrer`. The page's scripts run only under a per-response nonce.

## Workspace text is untrusted data

Wiki pages, intake notes and every other workspace file can contain text written by anyone, including text that tries to instruct an agent. The service does not execute or interpret that text. Its MCP instructions tell the agent to treat workspace text as project data and never as instructions, and that the board never approves on the human's behalf.

The service cannot make an agent obey those instructions. The protection is structural: an agent can change the workspace only through a preview of exact changes. An ungated change is confirmed by the human in the agent's own interface. A gated change waits in the board's proposal list until a human who holds the required roles approves it in the board. A human's direct board actions are limited to `po-handoff`, `design-start`, `dev-start` and `operation-repair`, each previewed before it applies. Review every preview before you confirm it.

## Roles and gated approval

A lifecycle action is gated when it names the roles its approver must hold (`required_roles`: every role in `all_of`, and at least one role in `any_of` when that list is not empty). The board applies the same predicate when it lists proposals, serves a preview, applies, recovers and repairs.

1. **A grant identifies a locally registered token holder.** It does not verify who holds the token, and two grants can belong to one person.
2. **A role records that whoever ran `prism board grant` assigned it.** The board enforces roles and cannot tell whether the holder is the person named. Roles are fixed for a grant's life: a role change is a new grant plus `prism board revoke` of the old one. An agent grant never holds a role, and `--role` needs `--write`.
3. **`qa-separate-from-dev` separates grants.** The setting in the front matter of `knowledge/wiki/SETTINGS.md` makes the board refuse a verification (`qa-pass`, `bug-verify`, `bug-reverify`) from the grant that produced, recovered or repaired the evidence it verifies. Reissuing a grant defeats it. A value that is not `true` or `false` is `invalid_policy`, never read as `false`.
4. **Gated approval is accepted only over a browser board session.** This is a transport restriction: it keeps the approval out of MCP tool calls and Bearer requests (`approval_requires_board_session`). It does not protect a leaked human token, because any software holding the token can exchange it for a session. Local filesystem access can also mint a new grant, and whoever can run `prism board grant` administers the roles.
5. **Ungated writes stay host-attested.** A write skill that never advances a status, a track or an app stage is applied by the agent's host after the human confirms the preview there.
6. **The board has a proposal list in which an agent's gated proposal waits for a human.** An agent proposes with `preview_skill` and is refused when it tries to apply (`approval_required`). A human who satisfies the predicate reads the preview, applies it with its `review_revision` and an explicit acknowledgement, or declines it. The first of apply and decline wins; the log names the approver, the roles they held and the agent they approved.
7. **Deleting `.prism/state/` loses recovery and separation provenance.** The journal binds each evidence row to the operation that produced it. Use `prism board state reset`, which writes an audit export and refuses while any operation is unresolved. `prism board audit export --out FILE` writes the same export, without token hashes, at any time.

Without the board, the direct-file workflow enforces no role: lint checks structure only.

## Saved answers are checked before an update

`prism update` and `prism app add --scaffold` run Copier with trust, and what an answers file records is rendered into generated files, including code and CI. So `prism update` checks every layer's saved answers before it starts Copier (`prism app add --scaffold` applies the same check to the workspace's answers): the workspace's own `.copier-answers.yml` must select the workspace layer and hold only that layer's answers, and every app layer must name the workspace's approved template source and the identity the manifest gives it. A project name, an app ID, path, name or audience, a package identifier or a port that is not safe to render, a template revision that is not a plain tag or commit name, or an answer that no layer asks stops the update before Copier runs. An answers file that is a symlink, a junction or another reparse point, or that sits behind one, is never opened, read or written; Prism names the way out (restore the regular file from git).

Checking and using are one operation on one reading. Each layer's answers file is read once, without following a link and comparing the open handle with the path, and the update works from those bytes. A recopy gives Copier a private file that holds exactly the validated answers of the layer, never the live file; the manifest is rendered from the same bytes; and before anything Copier produced is moved into place or committed, every answers file the recopy relies on must still hold the validated bytes. A smart update (`copier update`) has to let Copier read and rewrite the tracked file itself, because Copier refuses a project whose tree is not clean. So it starts only while the file still holds the validated bytes, and afterwards the file Copier wrote must hold exactly the validated answers (no answer lost, none added, none changed), apart from the template revision Copier moves forward and the stacks and apps the update hands over; the layers that follow are checked byte for byte. `prism app add --scaffold` refuses a plan whose workspace answers changed after the preview and checks the file the same way around its workspace-layer update. When an answers file changes after it was validated, nothing that depends on it is used, moved into place or committed; the message names the file and says to run the command again. A person or process with write access to the workspace can still change a file in the seconds while Copier runs; these checks make that visible and refuse the result, they do not prevent the write.

## What the service does not protect against

- **Other software on the same computer.** Any process can connect to the loopback port. It still needs a valid token, but the service does not defend against malware running as the same user, and a person who can read your environment variables or shell history can read your tokens. Keep tokens out of files, prompts and the repository.
- **Other local users.** Workspace files and `.prism/state/` have the permissions your operating system gives them. Do not run a workspace in a folder that other users can read or write.
- **An agent's own file access.** The service's access controls do not restrict what a coding agent can do through its own filesystem and shell tools. Edits made outside the service are external changes with no recorded participant.
- **A concurrent local edit that breaks dependency discovery.** When finding an operation's relevant sources fails (for example because a second page with the same feature ID appears), the check before a write or retry falls back to the sources recorded at validation, so a requirement page added at the same moment is not seen. It needs another writer on the same machine during the write. Run `prism wiki lint` after concurrent edits, which reports the duplicate.
- **Verified identity.** A participant name labels a locally registered grant. It does not prove who holds the token. A role is the claim of whoever ran `prism board grant`.
- **Semantic review.** The service checks structure, freshness and permissions. Whether a proposed change is right is the human's decision at the preview.
- **A compromised Prism installation or dependency.** Install Prism from a source you trust.

Do not commit `.prism/state/`. It holds grant hashes and roles, previews, the operation journal and the evidence provenance. A state database from before roles is refused with `unsupported_board_state`; `prism board state reset` replaces it. `prism workflow install` adds an ignore rule for it, and `prism doctor --workspace .` fails when git does not ignore it.

Do not commit `prism.local.yml` either. It records where this machine keeps the checkouts of a workspace's external repositories, so it holds local paths. `prism workflow install` and the generated project's `.gitignore` list it, and `prism status` reports only whether a checkout is resolved, never its path. Prism checks that a checkout exists and does not read from it or write to it, and it ignores a `prism.local.yml` or a checkout that is a symlink or reparse point.
