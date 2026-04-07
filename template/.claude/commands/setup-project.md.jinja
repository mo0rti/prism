# Setup project — interactive project initialization

Run this once, immediately after scaffolding a new project with Copier.
This command initializes the wiki state and generates the advisory board configuration
through a structured conversation with the team.

## Usage
/setup-project

## When to run
Immediately after `copier copy` produces the project structure. Run before any other
wiki command. If the wiki already has feature entries, this command will warn and ask
for confirmation before proceeding.

## What this command does

This command has four checkpointed steps. Complete each step fully before proceeding
to the next. If something needs adjustment at any step, fix it before moving on.

### Step 1: Project identity confirmation

Read the following files:
- CONTEXT.md (the rendered monorepo root context file)
- `.copier-answers.yml` if present (Copier writes this file to the generated project
  root with the answers the user gave during scaffolding — this is NOT the template
  repo's `copier.yml`, which is not present in the generated project)
- Any existing docs/ or README files

Present a confirmation summary:
- Project name and description
- Platforms included
- Any pre-existing structure the AI discovered

Ask: "Is this correct? Is there anything important about this project not captured above?"

Wait for confirmation or corrections before proceeding to Step 2.

### Step 2: Domain risk interview

Ask the following four questions. Ask them one at a time, not all at once.
Wait for the answer to each before asking the next.

**Question 1:** "Who are your primary users, and what do they trust this app to get right?
Be specific — not 'general public' but 'parents managing their children's meal plans' or
'small restaurant owners tracking inventory.'"

**Question 2:** "What is the most important decision or calculation this app makes on behalf
of users? What is the thing the app does that users rely on most?"

**Question 3:** "What could go wrong if the app gets that wrong? Think about the worst
realistic case — not catastrophizing, but honest. What would a news headline say?"

**Question 4:** "Are there any user groups who might be especially vulnerable to a mistake?
For example: people with health conditions, financial stress, learning differences,
dietary restrictions, or cultural backgrounds where the dominant assumptions don't apply."

After all four answers are received, summarize what you heard and what domain expertise
gaps they imply. For example:

"Based on what you've described:
- You serve users managing dietary restrictions → need a medical/nutritional perspective
- A wrong recommendation could reinforce disordered eating → need behavioral psychology
- The scoring system uses nutritional data → food science needed to validate accuracy
- Traditional foods from non-Western cuisines may be penalized → cultural sensitivity
  and epidemiological perspective needed
Does this match how you see the risks?"

Wait for confirmation or additions before proceeding to Step 3.

### Step 3: Advisory board generation and confirmation

Based on the domain risk interview answers, propose a board of 4–6 members.

For each proposed member, provide:
- **Name:** a realistic fictional person (first and last name)
- **Title:** specific professional title
- **Institution:** a realistic, named institution or company (can be fictional but plausible)
- **Expertise:** 3–5 bullet points of specific knowledge areas
- **Why on this board:** one sentence connecting their expertise to a specific failure
  mode identified in Step 2
- **Typical questions they ask:** 2–3 example questions this person would raise during
  a feature review (concrete, domain-specific, not generic)

Present all proposed board members and ask:
- "Does this board composition look right for your product's risk profile?"
- "Is there a perspective that's missing?"
- "Is there anyone here who doesn't seem relevant to your specific product?"

Allow additions, removals, and modifications. Revise until the team confirms.

**Only write BOARD.md after explicit confirmation.** Do not write the file speculatively
and ask for approval after — show the content and confirm first.

### Step 4: Initial wiki scaffolding

Create the initial wiki state:
- Write `knowledge/wiki/advisory/BOARD.md` using the confirmed board composition
  (see `knowledge/wiki/advisory/_FORMAT.md` for the required format and the board
  member format in `knowledge/wiki/SCHEMA.md` section 5.10)
- Write initial `knowledge/wiki/index.md` with empty status board
- Write initial `knowledge/wiki/log.md` with initialization entry
- If the domain risk interview revealed clear business rules (e.g. "all recommendations
  must include a medical disclaimer"), create the first business rule entries in
  `knowledge/wiki/business-rules/`
- If the project description revealed clear user personas, create initial persona stubs
  in `knowledge/wiki/personas/`

Show the user a summary of everything created. State explicitly: "The advisory board
can be revised at any time by editing BOARD.md directly or by asking me to regenerate
a specific board member. The board composition is a living document."

Append to `knowledge/wiki/log.md`:
`## [today's date] setup-project | Wiki initialized`
Followed by: project name, platforms, board member count, any business rules and
personas created.

## Notes for the agent

- Step 2 questions must be asked one at a time in conversation. Do not present them
  as a form to fill in. The conversational format produces better answers because
  each answer informs how to ask the next question.
- The board should have 4–6 members for small teams. More than 6 produces review
  output that is too long to read in 15 minutes. Fewer than 4 likely misses important
  domain perspectives.
- The "typical questions" for each board member are not decoration — they are the
  most important part of the board definition. They train the AI on what concerns
  this board member raises. Write them from the board member's perspective, in their
  domain language, and make them specific to this product's actual risks.
- The board has credibility only if the team helped define it. Never skip Step 3 or
  rush through confirmation. A board the team doesn't believe in will have its concerns
  dismissed.
- The board is a starting point, not a final answer. The team will not have thought
  through all their domain risks on day one. Say this explicitly at the end of Step 4.
