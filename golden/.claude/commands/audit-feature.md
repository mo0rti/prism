# Audit feature — cross-check spec against source intake

Use this skill to audit one feature against its source documents.

## Usage

`/audit-feature [F-XXX]`

## Workflow

1. Read `knowledge/wiki/features/[F-XXX]-[slug].md`
2. Read the `sources` field in the frontmatter
3. Read all files listed in sources (from intake/processed/ or intake/quarantined/), and the bug pages of the feature
4. Compare spec against source documents:
   - Are all requirements in the spec traceable to the sources?
   - Are there items in the sources that didn't make it into the spec?
   - Does the acceptance criteria match what was described in the source?
   - If a board review exists: do the board's findings trace back to the spec content?
   - If the feature is in or past QA: does each QA row cite the current revision of a real criterion, and does each bug of the
     feature (`knowledge/wiki/bugs/`) trace to a QA row, a report or a source in `sources`?
5. Report findings:
   - **Confirmed:** requirements with clear source traceability
   - **Untraced:** requirements in the spec with no source — possibly hallucinated by AI
   - **Missed:** items in the source not in the spec
   - **Drifted:** items appearing in both but with meaningfully different framing
6. Do not auto-fix. Report only. Append the audit result to `log.md` as an entry in the log format that the wiki schema defines.

## Rules

- write-capable skill for `log.md` only
- do not auto-fix the feature spec during the audit
- treat untraced requirements as the highest-signal risk: a requirement with no source is a risk. Flag it clearly and suggest the team confirm whether it was an agreed addition or AI invention
- if a board review exists, include traceability context where relevant
- run this before any handoff for features with complex or ambiguous source documents

## Output behavior

Return:

- confirmed requirements with source traceability
- untraced requirements
- missed source items
- drifted items
- recommended follow-up questions for the team when needed

## Error and stop conditions

- if the feature file does not exist, return a clean missing-feature response
- if the feature has no `sources` field or the listed source files cannot be found, report the traceability gap clearly
- do not rewrite the feature spec as part of the audit
