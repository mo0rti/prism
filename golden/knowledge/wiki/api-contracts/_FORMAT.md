# API contract page format

Use this format for every file in `wiki/api-contracts/`. Filename: `F-XXX.md`.

```markdown
---
feature-id: F-XXX
version: 1
status: draft | agreed | implemented
---

## Endpoints
For each endpoint: method, path, request body, response body, error codes.

## Data models
Shared data shapes that backend produces and clients consume.

## Authentication requirements
Auth method, required scopes or roles.

## Notes
Design decisions, backwards-compatibility concerns.
- **Decided:** [a decision about this contract] ([ADR-001](../decisions/ADR-001-slug.md))
```

`tech-design-done` creates this page at `status: agreed`, `version: 1` when the feature's API surface
declares API work (`design-handoff` does too when it settles the technical track with the `tech-lead` role);
no other action writes a contract body, and the human confirming the preview is the agreement. List each
endpoint as `METHOD /path` and define only data models that the API surface or an endpoint names.

## Revisions and the digest

- The contract belongs to the `technical` design track. It is writable while the feature is
  `ready-for-design` or `in-design` and locked from `ready-for-dev` on; only its `status` changes after that:
  `dev-done` moves it to `implemented`, and a return from implementation moves it down to `agreed` or `draft`.
- A revision raises `version` by one, changes the body and keeps `status: agreed`, and it happens while the
  feature is in design. A changed body without a version bump is `contract_revision_required`. It is refused with
  `shared_contract_in_use` while another feature that links the contract has an app between `ready-for-dev` and
  `ready-for-release`; that feature returns first.
- The contract has a digest, `c1:` and the SHA-256 of `[1, feature ID, version, sections]`, where the sections are
  the body's `##` sections in order, each as its heading and its text (NFC, whitespace collapsed). Front matter other
  than `version` is not part of it, so `implemented` keeps the digest. Delivery evidence cites the contract as
  `F-XXX@v<version>:c1:<digest>` (or `none` when the feature has none); the board reports that citation beside the
  contract page when it reads it. A cell that is not the current citation is `contract_binding_stale`.
