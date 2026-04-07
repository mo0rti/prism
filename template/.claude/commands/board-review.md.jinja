# Board review — domain expert feature review

Run a structured review of a feature through the lenses of the project's advisory board.
The board is a set of domain expert personas defined in advisory/BOARD.md. Each member
reviews the feature from their domain perspective and raises concerns the team cannot see.

## Usage
/board-review [F-XXX]

Example: /board-review F-007

## When to use

Use for features that have ANY of the following characteristics:
- Involves a domain-specific calculation or score (nutrition rating, financial risk, learning
  difficulty assessment, safety classification)
- Has behavioral or psychological implications (gamification, streaks, social comparison,
  achievement systems, notifications designed to change behavior)
- Touches a sensitive or vulnerable user group (users with health conditions, financial
  stress, learning differences, dietary restrictions)
- Involves cultural assumptions that may not generalize (food from non-Western cuisines,
  currency/locale assumptions, language that assumes Western norms)
- Where getting it wrong has real-world consequences outside the app (health outcomes,
  financial decisions, legal compliance)
- Is a core differentiating feature of the product (the thing the app is known for)

Do NOT use for:
- Authentication flows (login, logout, password reset, 2FA setup)
- Settings and preference screens
- Basic CRUD operations (create/edit/delete records with no domain logic)
- Notification preference management
- Infrastructure and deployment changes
- Internal admin tools with no end-user impact
- UI polish and visual improvements

When in doubt: run `/board-review`. The cost is one conversation. The cost of missing a
domain failure is potentially much higher.

## What this command does

1. Read `knowledge/wiki/advisory/BOARD.md` in full — load the board composition
2. Read `knowledge/wiki/SCHEMA.md`
3. Read `knowledge/wiki/features/[F-XXX]-[slug].md` in full
4. Read `knowledge/wiki/personas/` — understand who uses this feature
5. Read `knowledge/wiki/business-rules/` — check for relevant constraints
6. Read `knowledge/wiki/decisions/` — check for architectural constraints
7. Read the feature pages for any related features
8. Read existing board reviews for related features (for context and consistency)
9. For each board member in BOARD.md:
   - Apply their expertise lens to the feature spec
   - Identify concerns, edge cases, and failure modes specific to their domain
   - Generate their perspective (only if they have something substantive to say —
     omit members who have no relevant concerns for this feature)
10. Identify where board members would disagree or prioritize differently. Make these
    debates explicit — they are the most useful output.
11. Generate `knowledge/wiki/advisory/[F-XXX]-review.md` using the pre-dev review
    format from SCHEMA.md (the four-section format: Conflicts, Gaps, Build order,
    Biggest risk — followed by board perspective summaries and action items)
12. **For each action required before dev:**
    - Add an open question to the feature file with the appropriate owner (po/designer/dev)
    - Tag it as coming from the board review: "[Board: Dr. Mitchell] Is the fiber threshold..."
13. **For any new business rule implied by the review:**
    - Propose creating a new business-rules/ entry
    - Show the proposed rule to the user and wait for confirmation before writing
14. Update the feature's `advisory-review` field to `done`
15. Update `knowledge/wiki/index.md`
16. Append to `knowledge/wiki/log.md`

## Output structure

The review output must follow the four-question format from SCHEMA.md.
Maximum one page. The team should be able to read it in 15 minutes.

The four questions:
1. **Conflicts** — specific named conflicts with existing features, decisions, or rules
2. **Gaps** — missing information that will block development
3. **Build order** — cross-platform dependency sequencing
4. **Biggest risk** — one sentence; the most likely cause of failure or user harm

After the four questions: board perspective summaries (one paragraph per member with
substantive concerns). Only include members with real concerns.

End with: a checklist of actions required before dev starts, and actions that can
be deferred without blocking development.

## Notes for the agent

- Specificity is the entire value of this review. "Consider security" is useless.
  "Dr. Mitchell notes that the nutrition score for a traditional Japanese bento box
  will score poorly under Western macro-first frameworks — flag for localization" is useful.
- For each concern, name the source: which board member raised it, in what domain context.
- Debates between board members are important signal. If the nutritionist and the
  behavioral psychologist disagree, say so explicitly and let the team decide.
- A review that finds no concerns is a valid and useful output. State explicitly that
  the board reviewed the feature and found it sound. Do not invent concerns.
- The review is NOT a governance gate — the team does not need the board's "approval."
  It is an intelligence input. The team decides what to do with the findings.
