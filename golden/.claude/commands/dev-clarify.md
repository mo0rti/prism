# Dev Clarify

Use this skill to work through open dev-owned questions one feature at a time.

## Usage

`/dev-clarify`

## Workflow

Identical in structure to `/po-clarify` but filters for open questions where owner = `dev`.

1. Read `knowledge/wiki/SCHEMA.md` and `knowledge/wiki/LIFECYCLE.md`
2. Read all files in `knowledge/wiki/features/`
3. Collect all open questions where owner = `dev` and status = `open`
4. Group by feature and present them to the user one feature at a time:
   ```
   F-002 — Profile Edit
   1. Is there a limit on how long an exported comment can be?
   2. Can the export run inside the request, or must it be queued?
   ```
5. For each question the user answers:
   - Update the open questions table: change status to `resolved: [answer]`
   - If the answer reveals a new requirement, update the feature's Acceptance criteria,
     App scope or API surface section
   - If the answer changes what an app must build, update that feature's app
     requirement page (`knowledge/wiki/app-requirements/[F-XXX]-[app-id].md`):
     What to build, Technical constraints, API contract reference or Acceptance criteria
   - If the answer contradicts existing wiki content, flag the conflict and leave the question open
6. Append a single `log.md` entry in the log format that the wiki schema defines, summarizing all questions resolved

## Rules

- write-capable skill
- resolve only questions owned by `dev`; leave every other owner's questions open
- do not change a feature's status or owner, and do not change a criterion while an app it names is `ready-for-release` or `released`, the App scope from `ready-for-dev` on, or the API surface once an app has delivered (`clarify_stage_unavailable`); a new acceptance criterion takes the next number after `criteria-high-water` and raises the mark in the same proposal
- present questions one feature at a time, not as one large dump
- after each answer, confirm what you updated before moving to the next question
- every requirement-bearing section you change (in the feature or in an app requirement page) must contain the full text of at least one answer you resolve in the same proposal; a paraphrase alone is not enough
- turn a short answer into a complete sentence before it goes into a page: build the sentence from the
  question's own wording and keep the answer's words unchanged inside it, so the board can trace it. A
  bare `yes`, `no` or `30 days` is never the whole text of a bullet, cell or paragraph. Question
  "Can the export run inside the request?" answered `yes` becomes "The export can run inside the
  request: yes."; question "How long are comments kept?" answered `30 days` becomes "Comments are kept
  for 30 days." The Status cell of the question keeps the answer as the human gave it
- change nothing else on the page: copy every other line and section exactly as `read_workspace` returned it, including the file's final newline
- change only the sections named above; leave app requirement frontmatter, including `status`, unchanged
- if the user's answer introduces a new open question, add it immediately
- questions tagged "[Board: ...]" came from a board review; treat them with the same priority as other open questions
- if one feature hits a contradiction, skip that conflicting answer and leave the question open for that feature only
- do not stop the whole clarify session unless the user asks to stop
- write current-state pages: replace superseded content in place, state rationale as a current fact and keep history in `log.md` and the records; mark each claim `**Decided:**`, `**Observed:**`, `**Proposed:**` or `**Assumed:**` (gaps stay in the Open questions table) and link the evidence of every Decided and Observed claim: the processed intake item, a record or a URL (see Evidence labels in the wiki schema)

## Output behavior

Return:

- current feature being clarified
- open dev questions for that feature
- resolved answers and resulting feature and requirement updates
- any newly added open questions
- final summary of questions resolved

## Error and stop conditions

- if there are no open dev questions, return a clean empty-state response
- if a user answer conflicts with existing wiki content, report the conflict, leave that question open, and stop the conflicting update for that feature, then continue with the next feature unless the user wants to stop
