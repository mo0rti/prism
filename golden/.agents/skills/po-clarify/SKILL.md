---
name: po-clarify
description: Resolve open questions assigned to PO across the wiki. Use when gathering answers from the product owner and updating feature specs, question tables, status, and logs accordingly.
---

# PO Clarify

Use this skill to work through open PO-owned questions one feature at a time.

## Usage
$po-clarify

## Workflow

1. Read `knowledge/wiki/SCHEMA.md` and `knowledge/wiki/LIFECYCLE.md`
2. Read all files in `knowledge/wiki/features/`
3. Collect all open questions where owner = `po` and status = `open`
4. Group by feature and present them to the user one feature at a time:
   ```
   F-002 — Profile Edit
   1. What happens when a user tries to edit their email but email is used for login?
   2. Should users be able to delete their account from this screen?
   ```
5. For each question the user answers:
   - Update the open questions table: change status to `resolved: [answer]`
   - If the answer reveals a new requirement, update the feature spec
   - If the answer contradicts existing wiki content, flag the conflict and leave the question open
6. Leave `status` and `owner` as they are; the status board row then stays as it is
7. Append a single `log.md` entry in the log format that the wiki schema defines, summarizing all questions resolved

## Rules

- write-capable skill
- answers only questions owned by `po`; leave every other owner's questions open
- a change to an acceptance criterion keeps its ID and `applies-to`; a new criterion takes the next number after `criteria-high-water` and raises the mark in the same proposal; no criterion changes while an app it names is `ready-for-release` or `released` (`clarify_stage_unavailable`), and the App scope section does not change from `ready-for-dev` on (use `$feature-scope`)
- does not change a feature's `status` or `owner` (`$po-specify` completes a `raw` feature)
- resolve a question by changing only its Status cell to `resolved: [answer]`; keep its
  number, text and owner, and add no row except a new open question
- change only the feature's Open questions, Summary, User story, Acceptance criteria,
  App scope and API surface sections; add no other section (no `## Requirements` or
  `## Answers`)
- every requirement-bearing section you change must contain the full text of at least one
  answer you resolve in the same proposal; a paraphrase alone is not enough
- turn a short answer into a complete sentence before it goes into a page: build the sentence from the
  question's own wording and keep the answer's words unchanged inside it, so the board can trace it. A
  bare `yes`, `no` or `30 days` is never the whole text of a bullet, cell or paragraph. Question
  "Can the export run inside the request?" answered `yes` becomes "The export can run inside the
  request: yes."; question "How long are comments kept?" answered `30 days` becomes "Comments are kept
  for 30 days." The Status cell of the question keeps the answer as the human gave it
- change nothing else on the page: copy every other line and section exactly as `read_workspace` returned it, including the file's final newline
- present questions one feature at a time, not as one large dump
- confirm each update before moving to the next question
- if an answer introduces a new open question, add it immediately
- treat board-generated questions with the same priority as other open questions
- if one feature hits a contradiction, skip that conflicting answer and leave the question open for that feature only
- do not stop the whole clarify session unless the user asks to stop
- write current-state pages: replace superseded content in place, state rationale as a current fact and keep history in `log.md` and the records; mark each claim `**Decided:**`, `**Observed:**`, `**Proposed:**` or `**Assumed:**` (gaps stay in the Open questions table) and link the evidence of every Decided and Observed claim: the processed intake item, a record or a URL (see Evidence labels in the wiki schema)

## Output behavior

Return:

- current feature being clarified
- open questions for that feature
- resolved answers and resulting wiki updates
- any newly added open questions
- final summary of questions resolved

## Error and stop conditions

- if there are no open PO questions, return a clean empty-state response
- if a user answer conflicts with existing wiki content, report the conflict, leave that question open, and stop the conflicting update for that feature, then continue with the next feature unless the user wants to stop
