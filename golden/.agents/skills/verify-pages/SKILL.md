---
name: verify-pages
description: Record that current-state wiki pages were checked against their sources. Use after reviewing pages for freshness; it appends one verify entry to log.md and never edits a page.
---

# Verify pages - record that pages were checked against their sources

## Usage

`$verify-pages <page>... [evidence link]`

## Workflow

A verification says: a person or an agent checked these current-state pages against their sources and found them current. The pages carry no date, so the verification is one `verify` entry in `knowledge/wiki/log.md`, and freshness lint (`stale-page`, `never-verified`) reads it. The skill never edits a page.

1. Read `knowledge/wiki/SCHEMA.md` (its Freshness section), `knowledge/wiki/LIFECYCLE.md` and every page to verify. A page is a current-state page, named as `knowledge/wiki/topics/pricing.md` or `topics/pricing.md`: a feature, persona, business rule, design page, app requirement, API contract, topic, research page, plan, `direction.md` or `roadmap.md`
2. For each page, compare its labeled claims with the sources it links and lists in `sources`, and with the current workspace. Check only what you can check; a claim you cannot check stays as it is and does not count against the page
3. If a page is no longer true, do not verify it. Tell the user which claims are out of date and which operation corrects them (`$ingest` or the page kind's own skill or command)
4. Show the user the pages you verified and the evidence you will link, and wait for confirmation
5. Record the verification once, for all confirmed pages:
   - **Connected board:** call `preview_skill` with `skill` set to `verify-pages`, an empty `changes` list, no `moves`, and `read_revisions` naming each verified page with the digest `read_workspace` returned for the page you read. This is the one skill that needs `read_revisions`. Then `apply` the preview after the user confirms it
   - **Prism CLI (version 0.5.0 or newer):** `prism wiki verify <page>... --evidence <link> --by <name>`
   - **Neither:** append one entry to `knowledge/wiki/log.md` by hand, in the log format of the wiki schema:

     ```text
     ## YYYY-MM-DD verify | <subject>
     - paths: <the verified pages, from the repository root, comma-separated>
     - evidence: <a link, or none>
     - by: <who verified them>
     ```

## Rules

- write-capable skill; it writes only the `log.md` entry
- do not append to `log.md` any other way when a connected board is available
- Write only the `log.md` entry. Never edit a page, an index line or a status board row, and never change a status or an owner.
- Records (ADRs, advisory reviews), `index.md`, `log.md`, `status-board.md`, `SCHEMA.md` and generated files are exempt from freshness and cannot be verified.
- Never verify a page you did not read in this session.
- Link the evidence; never copy it into the log. One entry per confirmation, never one per page.
- Return the pages verified, the pages left out and why, the entry's operation, date and evidence, and how it was recorded.

## Error and stop conditions

- if a page does not exist or is not a current-state page, say so and leave it out
- if a connected call is rejected, read the error and retry only with what it names, at most 2 more times, then stop and report it
- if the user does not confirm, stop without writing
