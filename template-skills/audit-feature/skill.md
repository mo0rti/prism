---
name: audit-feature
description: "Cross-check a feature spec against its recorded source intake. Use when validating traceability and looking for missing, drifted, or AI-invented requirements."
layers: [codex, command]
codex:
  display_name: "Audit Feature"
  short_description: "Cross-check a feature spec against its source intake"
  default_prompt: "Use @@invoke:audit-feature@@ F-XXX to verify source traceability and find missed, drifted, or untraced requirements."
  implicit: false
---

# Audit feature — cross-check spec against source intake

Use this skill to audit one feature against its source documents.

## Usage

`@@invoke:audit-feature@@ [F-XXX]`

## Workflow

1. Read `knowledge/wiki/features/[F-XXX]-[slug].md`
2. Read the `sources` field in the frontmatter
3. Read all files listed in sources (from intake/processed/ or intake/quarantined/)
4. Compare spec against source documents:
   - Are all requirements in the spec traceable to the sources?
   - Are there items in the sources that didn't make it into the spec?
   - Does the acceptance criteria match what was described in the source?
   - If a board review exists: do the board's findings trace back to the spec content?
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
