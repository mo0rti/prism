# Audit feature — cross-check spec against source intake

## Usage
/audit-feature [F-XXX]

## What this command does

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
6. Do not auto-fix. Report only. Append to log.md.

## Notes for the agent

- "Untraced" items are the most important finding. A requirement with no source is a risk.
  Flag clearly and suggest the team confirm whether it was an agreed addition or AI invention.
- Run this before any handoff for features with complex or ambiguous source documents.
