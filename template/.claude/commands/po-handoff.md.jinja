# PO handoff — move a feature to ready-for-design

## Usage
/po-handoff [F-XXX]

## What this command does

1. Read `knowledge/wiki/features/[F-XXX]-[slug].md`
2. Check `advisory-review` field first:
   - If `pending`: inform the user that a board review is recommended before handoff.
     Show the criteria for why this feature was flagged.
     Ask: "Do you want to run /board-review F-XXX before handing off to design?"
     If yes: run board review. The review may add new open questions to the feature.
     If no: set `advisory-review: skipped` and ask the user to provide a reason.
     Record the reason in the feature file frontmatter: `advisory-skip-reason: [reason]`
3. Run completeness check (after any board review has run, so new open questions are visible).
   The feature must have:
   - A non-empty Summary
   - At least one User story
   - At least one Acceptance criterion
   - No open questions with owner = `po`
   - At least one platform listed in Platform scope
4. If the completeness check fails:
   - List exactly what is missing (including any board-review-generated open questions
     that are now blocking — these must be resolved before handoff)
   - Do not update the status
   - Stop
5. If the check passes:
   - Show the user what will change: status → `ready-for-design`, owner → `designer`
   - Wait for confirmation
   - Update feature file frontmatter
   - Update `index.md` status board
   - Append to `log.md`
   - Output a brief design brief: what the feature is, acceptance criteria,
     open questions assigned to designer, any board concerns relevant to design

## Notes for the agent

- The design brief is the handoff artifact. Make it readable for someone who has not
  seen the full spec.
- Board review is recommended at this stage (before design) for features with
  advisory-review: pending, because running it before design means the designer
  receives a brief already informed by domain expert concerns.
