# Prism — Agent Implementation Plan

**Document purpose:** Full context and step-by-step implementation plan for refining the
`template-hub` repository. This document is intended to be handed directly to an AI coding
agent (Claude Code, Codex, Cursor, etc.) as primary context. Read it entirely before making
any changes.

**Revision history:**
- v1: Initial plan — developer-centric wiki with four commands
- v2: Team-oriented workflow — role-differentiated commands for PO, Designer, Developer;
  intake pipeline added as first-class concern; wiki made required
- v3: Advisory board system added as product-domain intelligence layer;
  `/setup-project` two-phase initialization command added; `BOARD.md` configuration
  file defined; advisory review repositioned to PO stage; pre-dev review simplified
  to four-question format; `/board-review` command added
- v4: Review findings applied — platform alias corrections throughout
  (android/ios/web/admin → mobile-android/mobile-ios/web-user-app/web-admin-portal);
  Codex/Cursor parity added to section 3, 5.7, 9, and validation checklist;
  old command retirement list corrected to actual filenames (scaffold-feature.md.jinja,
  document-feature.md.jinja); `project_description` corrected to `description`;
  `shared/openapi.yaml` corrected to `shared/api-contracts/openapi.yml`;
  setup-project Step 1 updated to read `.copier-answers.yml` not `copier.yml`;
  po-intake conflict check moved before writes; po-handoff completeness check moved
  after board review; design-handoff design-page check made conditional on UI scope;
  Rule 5 corrected from "three outcomes" to "two outcomes"
- v5: Second review round applied — root generated context files
  (template/CLAUDE.md.jinja, template/AGENTS.md.jinja) explicitly called out for update
  in sections 3, 5.7, 7, 9, and validation checklist; Codex parity expanded with
  complete skill file list and distinction between skill-file vs. AGENTS.md-documented
  commands; $setup-project added as required new skill; AGENTS.md.jinja filenames
  corrected throughout (platform files use .jinja suffix); advisory-review ownership
  rule rewritten to be unambiguous (po-intake initializes, /board-review sets done,
  /po-handoff sets skipped); po-intake quarantine contradiction fixed (no feature file
  writes during quarantine); CONTEXT.md.jinja platform list replaced with real Jinja2
  conditional block; root AGENTS.md added to section 7 and implementation order;
  validation commands updated to Windows/PowerShell syntax (C:\temp\)
- v6: Third review round applied — $scaffold-feature retired (not updated);
  $name convention tightened ($prefix only for skill files, plain names for AGENTS.md
  operations); CONTEXT.md.jinja setup section uses tool-specific invocation wording
  (Claude /setup-project, Codex $setup-project, Cursor ask-the-agent); platform wiki
  section references updated to be tool-agnostic; design-handoff advisory-review:pending
  "no" path added (skipped requires reason, mirrors po-handoff); template/docs/README.md.jinja
  explicitly created in section 7.3 and implementation order step 17; validation checklist
  gains scaffold-feature deletion check and docs/README.md existence check
- v7: Fourth review round applied — validation checklist split into source-repo
  checks (template/ paths) and generated-project checks (output paths); contradictory
  scaffold-feature/SKILL.md.jinja check removed; CONTEXT.md.jinja "Available commands"
  relabelled "Claude Code slash commands" with Codex ($skill vs plain name) and Cursor
  (ask by name) sections added; section 14 Phase 2 and README Getting Started snippet
  updated to tool-specific invocation wording matching CONTEXT.md.jinja
- v8: Final polish — v6 no longer marked "current"; last /po-intake slash-command
  reference in CONTEXT.md.jinja replaced with tool-agnostic wording; wiki.mdc renamed to
  wiki.mdc.jinja throughout for consistency with api-conventions.mdc.jinja; suffix rationale
  note added
- v9: Second /po-intake occurrence in product wiki section fixed; all command
  source files renamed to .md.jinja throughout (section headers, implementation order);
  note added in section 5.6 explaining .md.jinja source vs .md generated output distinction
- v10 (current): intake/README.md spec updated with tool-specific command syntax (Claude/
  Codex/Cursor) for po-intake and design-intake; source-repo validation checklist gains
  checks for 14 new .md.jinja command source files and deletion of scaffold-feature.md.jinja
  and document-feature.md.jinja

---

## 1. How we got here — the full conversation chain

### 1.1 Andrej Karpathy's LLM wiki idea

In April 2026, Andrej Karpathy shared a pattern for building personal knowledge bases using
LLMs. The core insight is this:

Most people use LLMs with documents in a "RAG" style — you upload files, the LLM retrieves
relevant chunks at query time, generates an answer, and forgets everything. There is no
accumulation. Every query starts from scratch.

Karpathy's alternative: instead of the LLM retrieving from raw documents every time, the LLM
**incrementally builds and maintains a persistent wiki** — a structured, interlinked collection
of markdown files. When you add a new source, the LLM reads it, extracts key information, and
integrates it into the existing wiki: updating entity pages, revising summaries, flagging
contradictions, maintaining cross-references. The synthesis happens once and compounds over time.

The three layers of his system:
- **Raw sources** — immutable input documents (articles, papers, images, data). LLM reads, never modifies.
- **The wiki** — LLM-generated, LLM-maintained markdown files. Summaries, concept pages, entity
  pages, cross-references, an index, and a log. The LLM owns this entirely.
- **The schema** — a configuration document (CLAUDE.md / AGENTS.md) that tells the LLM how the
  wiki is structured, what conventions to follow, and what workflows to execute when ingesting
  sources or answering queries.

The key operations in his system:
- **Ingest** — drop a source into raw/, tell the LLM to process it. LLM reads, writes summary
  page, updates index, updates relevant concept and entity pages, appends to log.
- **Query** — ask questions against the wiki. LLM reads index, drills into relevant pages,
  synthesizes answer with citations. Good answers get filed back into the wiki as new pages.
- **Lint** — LLM health-checks the wiki: finds contradictions, orphan pages, stale claims,
  missing cross-references, data gaps.

Why it works: the tedious part of maintaining a knowledge base is not the reading or
thinking — it's the bookkeeping. LLMs don't get bored, don't forget to update a cross-reference,
and can touch 15 files in one pass. The wiki stays maintained because the maintenance cost
is near zero. The human curates sources and asks questions; the LLM does everything else.

### 1.2 The template-hub project (current state)

`template-hub` is a Copier-based monorepo generator. You answer a short questionnaire and
it scaffolds a complete multi-platform product:

- Backend: Spring Boot 4 (Kotlin 2.2+, Java 21)
- User web app: Next.js + TypeScript
- Admin portal: Next.js + TypeScript
- Android: Kotlin + Jetpack Compose (MVVM)
- iOS: Swift 6 + SwiftUI (MVVM)

Pre-configured with: Docker, Cloudflare, Azure deployment assumptions, OpenAPI 3.1 spec in
`shared/`, design tokens, and AI context files (`.claude/`, `.agents/`, `.cursor/`) for
Claude Code, Codex, and Cursor.

The repository already has `template/docs/` with subdirectories for features, API docs, and
an advisory board concept. It already has `template/.claude/commands/` for Claude slash
commands. The scaffolding instincts are right. The gap is that these are static directories
that humans are expected to maintain — and nobody maintains static docs.

### 1.3 The three problems this plan solves

**Problem 1: The context broadcasting problem**

When building a multi-platform product with AI-assisted development, there is a context
broadcasting problem with no compounding layer.

Concretely: a new feature is spec'd. The developer must manually feed that feature context
to every AI agent working in every platform directory — the backend Claude instance, the
Android Claude instance, the iOS Claude instance, the web Claude instance. Nothing is shared.
Each AI only knows what it was manually told. Nothing accumulates between features.

The four failure modes this creates:
1. **Context loss** — each AI knows only what you told it, not what you told the others
2. **Inconsistency** — the mobile AI interprets the feature differently from the backend AI
3. **No memory** — next feature, you start from scratch feeding the same product context
4. **No compounding** — nothing accumulates. Each session is stateless.

**Problem 2: The team handoff problem**

In real product teams, there are at least three roles whose work must flow through each other:

- **Product Owner (PO)** — talks to customers and users, captures business value, defines
  what needs to be built and why. Produces raw artifacts: meeting transcripts, client feedback
  summaries, feature request notes, user research.
- **Designer** — translates PO intent into concrete UX: flows, states, interactions, error
  handling, component designs. Produces design specs, Figma annotations, interaction notes.
- **Developer** — builds the actual product across mobile, web, backend, and infra. Receives
  (ideally) fully specified, design-complete feature requirements.

The gap between "what the PO heard from the customer" and "what the developer builds" is
where most software projects fail. The gap is not laziness — it is the absence of a
structured translation layer. PO notes are written in business language. Designer specs
are written in UX language. Developers need technical language. Something has to translate.

The knowledge wiki is that translation mechanism. The LLM reads PO notes and designer specs
and produces something a developer (human or AI) can act on without ambiguity.

**Problem 3: The domain expertise gap**

The PO, Designer, and Developer handle the *how* and *when* of building. But none of them
can see the *what consequences* — the domain-specific failure modes invisible to people who
are not domain specialists.

For a recipe and nutrition app: the team decides to build a nutrition score feature. The PO
knows users want it. The Designer knows what it should look like. The Developer knows how
to build it. But none of them knows whether the scoring algorithm unfairly penalizes
culturally important foods, whether the psychological framing of "healthy/unhealthy" causes
disordered eating patterns in vulnerable users, or whether the gastroenterology implications
of flagging high-fiber foods as "unhealthy" are wrong for users with IBS. That is what a
domain expert panel catches — and hiring actual domain experts is prohibitively expensive
for small teams.

The advisory board simulated by the LLM fills this gap. It is a **product-domain intelligence
layer**: a set of expert personas, defined once per project, that reviews features through
domain-specific lenses the team cannot see from their own roles.

### 1.4 The synthesis

Applying Karpathy's wiki pattern to the multi-platform, multi-role, domain-aware product
development workflow produces a three-layer architecture:

**Layer 1 — Intake and translation:** PO drops raw notes → LLM structures into feature specs.
Designer attaches design artifacts → LLM maps to feature specs. The wiki captures what the
team knows.

**Layer 2 — Broadcast and persistence:** All platform AI agents read from the same wiki
before implementing. Developers (human or AI) consume role-appropriate, structured
requirements. The wiki compounds with every feature.

**Layer 3 — Domain intelligence:** The advisory board reviews features through expert lenses
the team cannot see. Board output feeds back into the feature spec — open questions added,
acceptance criteria updated, business rules created. The board compounds too: business rules
extracted from board reviews inform all subsequent feature reviews.

This is not documentation. It is a living coordination and intelligence substrate for the
entire product development lifecycle.

---

## 2. Proposed new identity

### 2.1 Name

**Prism**

Rationale: a prism takes a single beam of light and refracts it into its component spectrum.
This is exactly what the system does: one feature spec enters, and platform-specific
requirements emerge for each platform. The metaphor is precise and immediately intuitive.

**Tagline:** One spec. Every platform.

**Alternative names considered** (if Prism is taken or unsuitable):
- *Meridian* — the reference line all platforms align to
- *Keystone* — the central piece that holds everything together
- *Conduit* — the channel between intent and implementation

### 2.2 New repository description

```
A production-grade, AI-ready multi-platform system generator with a living product wiki.
Turn an idea into a fully scaffolded monorepo — then keep every platform's AI agent in sync
as your product evolves.
```

---

## 3. What changes — overview

The existing template structure is sound. This plan adds new required layers and expands
the command set.

**Additions:**
1. A new `knowledge/` directory added to `template/` — split into `intake/` (raw inputs)
   and `wiki/` (structured, LLM-maintained knowledge)
2. `knowledge/wiki/advisory/BOARD.md` — a project-specific configuration file defining the
   advisory board composition, generated by the AI during project setup
3. Platform-level `CLAUDE.md.jinja` files updated to reference the wiki (Claude Code)
4. Platform-level `AGENTS.md` files updated with the same wiki reference section (Codex)
5. A set of Claude command files added to `template/.claude/commands/` defining
   role-differentiated operations for PO, Designer, Developer, and shared use
6. New and updated Codex skills added to `template/.agents/skills/` for the structured
   multi-step operations: `$setup-project` (new), `$board-review` (replaces `$advisory-review`),
   `$prep-sprint` (new), `$feature-status` (new), `$lint-wiki` (new). The old `$scaffold-feature`
   is retired — see skill section for details. Simpler lifecycle operations (po-intake,
   po-handoff, design-intake, design-handoff, dev-done, etc.) are documented in
   `template/AGENTS.md.jinja` as plain command names without a `$` prefix, because they
   do not have dedicated skill files.
7. A `/setup-project` command — an interactive, two-phase initialization that runs once
   after Copier scaffolding to set up the wiki state and generate the advisory board

**Note on Cursor:** Cursor reads `.cursor/rules/` for project-level guidance. The
`template/.cursor/` directory should include a wiki-aware rule file that mirrors the
"read wiki before implementing" instruction from the CLAUDE.md and AGENTS.md additions.
This is lower priority than the Claude and Codex paths but should be included for parity.

**Changes to existing files:**
1. `copier.yml` — the wiki is required with no opt-out toggle; no `product_domain` question
   (domain is determined interactively by `/setup-project`, not statically)
2. `template/CLAUDE.md.jinja` — the root generated-project Claude context template must
   be updated to reference the wiki and new commands instead of `docs/features/`,
   `docs/advisory-board.md`, and the old `/scaffold-feature` workflow
3. `template/AGENTS.md.jinja` — the root generated-project Codex context template must
   be updated identically: replace `$scaffold-feature` and `docs/advisory-board.md`
   references with the wiki lifecycle and updated skill set
4. Platform identifiers in all Jinja2 templates must match the actual values used in
   `copier.yml` (verified against the live questionnaire before writing templates)

**One naming correction:**
Files serving as format guides inside the wiki are named `_FORMAT.md`, not `_TEMPLATE.md`,
to avoid confusion with Copier's own templating system.

---

## 4. New directory structure

After this plan is implemented, `template/` should contain the following addition:

```
template/
  knowledge/
    intake/
      pending/                        ← PO and Designer drop raw docs here
        .gitkeep
        PO_BRIEF_TEMPLATE.md          ← structured guide for PO intake
        DESIGN_HANDOFF_TEMPLATE.md    ← structured guide for design intake
      processed/                      ← items after AI has processed them
        .gitkeep
      quarantined/                    ← inputs conflicting with wiki; needs human resolution
        .gitkeep
      README.md                       ← instructions for all three roles
    wiki/
      features/
        .gitkeep
        _FORMAT.md                    ← feature page format for the LLM to follow
      personas/                       ← customer segments and user types (from PO notes)
        .gitkeep
        _FORMAT.md
      business-rules/                 ← invariants, constraints, non-negotiables
        .gitkeep
      design/                         ← component specs, interaction patterns (from Designer)
        .gitkeep
        _FORMAT.md
      platform-requirements/
        .gitkeep
        _FORMAT.md
      api-contracts/
        .gitkeep
        _FORMAT.md
      decisions/
        .gitkeep
        _FORMAT.md                    ← ADR format
      advisory/
        .gitkeep
        BOARD.md                      ← advisory board configuration (generated by /setup-project)
        _FORMAT.md                    ← pre-dev review output format
      index.md                        ← feature status board (LLM-maintained)
      log.md                          ← append-only change history (LLM-maintained)
      SCHEMA.md                       ← wiki conventions and rules for AI agents
  CONTEXT.md.jinja                    ← monorepo root context anchor (rendered at generation)
```

**Why intake/ is separate from wiki/:**
`intake/` contains raw, unprocessed human inputs. `wiki/` contains LLM-processed, structured
knowledge. Mixing them creates ambiguity about what is authoritative. The LLM never modifies
files in `intake/pending/` — it only reads them and moves them to `intake/processed/` or
`intake/quarantined/`.

**Why BOARD.md is a configuration file, not a generated output:**
`BOARD.md` defines who is on the advisory board and what they look for. It is written once
at project setup and is consulted before every board review. It is not a feature artifact
or a review result — it is the standing configuration of the domain intelligence layer.
It is generated by the AI during `/setup-project` but is confirmed by the team and then
treated as a stable reference document.

**Why personas/, business-rules/, and design/ are new:**
- `personas/` — who the users are (from customer conversations). Feature specs reference them.
- `business-rules/` — invariants that constrain all features (e.g. "payments always require 2FA").
  Extracted from PO intake and board reviews, referenced in feature specs.
- `design/` — design system knowledge extracted from designer handoffs. Platform requirements
  reference design decisions rather than restating them.

---

## 5. File specifications — what each new file must contain

### 5.1 `template/knowledge/wiki/SCHEMA.md`

This is the most important file. Every AI agent reads this first. It must contain:

#### Directory structure

An exact description of what lives in each subdirectory and what kind of content belongs
there. Include the intake/ structure and explain that the LLM treats intake/pending/ as
read-only inputs. Include advisory/ and explain BOARD.md as a configuration file.

#### Feature page format

The exact frontmatter and sections a feature page must have:

```markdown
---
id: F-XXX
title: [Feature name]
status: raw | specified | ready-for-design | in-design | ready-for-dev | in-dev | done
owner: po | designer | dev | none
introduced: YYYY-MM-DD
last-updated: YYYY-MM-DD
platforms: [list of platforms this feature affects — use actual project platform IDs]
sources: [paths to intake/processed/ items that produced this page]
advisory-review: not-needed | pending | done | skipped
---

## Summary
One paragraph. What this feature does, why it exists, and what user problem it solves.
Written in business language, not technical language.

## User story
As a [persona from personas/], I want to [action], so that [business outcome].

## Acceptance criteria
- [ ] Condition 1 (testable, unambiguous)
- [ ] Condition 2

## Open questions
| # | Question | Owner | Status |
|---|----------|-------|--------|
| 1 | What is the fallback when the user is offline? | po | open |
| 2 | What does the empty state look like? | designer | open |
| 3 | Is real-time sync feasible without WebSockets? | dev | resolved: use polling |

Owner must be one of: po | designer | dev
Status must be one of: open | resolved: [answer]

## Platform scope
- **backend**: [what backend must implement, or "not in scope"]
- **mobile-android**: [what Android must implement, or "not in scope"]
- **mobile-ios**: [what iOS must implement, or "not in scope"]
- **web-user-app**: [what user web app must implement, or "not in scope"]
- **web-admin-portal**: [what admin portal must implement, or "not in scope"]

Only list platforms included in this generated project. Use the exact IDs above —
they match the platform identifiers in copier.yml.

## Design
Link to design artifacts and key design decisions.
Format: [Description](../design/F-XXX-[slug].md) once design intake is complete.
This section is empty until /design-intake is run.

## Related features
- [F-XXX](features/F-XXX-[slug].md) — [why this relationship exists]

## API surface
High-level description of API changes required (expanded in api-contracts/).
Empty if no API changes are needed.

## Board review summary
Populated by /board-review command. Empty until then.
One paragraph summarizing the key concerns raised and what was resolved.

## Post-ship notes
Notes added after shipping. Populated by /dev-done command. Empty until then.
```

**Critical rule:** The `status` and `owner` fields together represent the feature's position
in the lifecycle. The `advisory-review` field tracks whether domain review has been done.
When a handoff command runs, status and owner are updated atomically.

**advisory-review field ownership (which command sets which value):**
- `/po-intake` initializes the field: sets `pending` (domain complexity confirmed) or
  `not-needed` (confirmed simple feature). This is the only command that sets these
  two values.
- `/board-review` sets it to `done` after a review is completed. This is the only
  command that sets `done`.
- `/po-handoff` may set it to `skipped` when the team explicitly decides to skip the
  review, with a mandatory reason recorded in `advisory-skip-reason`. This is the
  only command that sets `skipped`.
- No other command touches this field.

#### advisory-review field values — when each is used

- `not-needed` — set by PO at intake time for features with no domain complexity
  (authentication flows, settings screens, CRUD operations, admin tools, infrastructure)
- `pending` — set by PO at intake time for features with domain complexity (see section 14
  for criteria). Signals that the board review must happen before dev can start.
- `done` — set automatically by `/board-review` after a review is completed
- `skipped` — set manually when the team explicitly decides to skip a review with a reason.
  The lint command flags features in `ready-for-dev` with `advisory-review: pending` as
  incomplete. Setting `skipped` with a reason suppresses this flag.

#### Persona page format

```markdown
---
id: P-XXX
name: [Persona name, e.g. "Restaurant Manager"]
introduced: YYYY-MM-DD
sources: [intake sources that established this persona]
---

## Who they are
A paragraph describing this type of user: their role, context, and relationship to the product.

## Goals
What they are trying to accomplish. Bulleted list.

## Pain points
What currently frustrates them or slows them down.

## Features that serve this persona
Links to feature IDs tagged for this persona.
```

#### Business rule page format

```markdown
---
id: BR-XXX
title: [Rule name]
introduced: YYYY-MM-DD
source: [intake source or board review that established this rule]
---

## Rule
One unambiguous statement of the rule.
Example: "All payment operations require two-factor authentication regardless of session state."

## Rationale
Why this rule exists (legal, business, product decision, board recommendation).

## Affected features
Feature IDs that must comply with this rule.

## Exceptions
Any explicitly agreed exceptions with source reference.
```

#### Design page format

```markdown
---
feature-id: F-XXX
title: [Design title]
designer: [name, optional]
date: YYYY-MM-DD
figma: [Figma URL or "not applicable"]
---

## Summary
What this design covers and what decisions were made.

## Key design decisions
Decisions that affect implementation (not just aesthetics).
Example: "The confirmation dialog is modal and blocks all interaction — not a toast."

## States covered
List all UI states designed: empty, loading, error, success, edge cases.
Flag any states NOT designed that the developer will need to handle.

## Component references
Links to relevant entries in design/ for reused components or patterns.

## Open design questions
Questions for the Designer that affect implementation.
```

#### Platform requirements page format

```markdown
---
feature-id: F-XXX
platform: backend | mobile-android | mobile-ios | web-user-app | web-admin-portal
status: pending | in-progress | done
---

## What to build
Specific, actionable description of what this platform must implement.
Written for the AI agent working in this platform's directory.

## Technical constraints
Platform-specific constraints, existing patterns to follow, library choices.

## Design reference
Link to design/F-XXX-[slug].md for UI platforms. Not applicable for backend.

## API contract reference
Link to api-contracts/F-XXX.md. List endpoints or data shapes this platform consumes/produces.

## Acceptance criteria
Platform-specific done conditions.

## Dependencies
Other feature IDs or platform-requirement files that must complete first.
```

#### API contract page format

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
```

#### Architecture Decision Record (ADR) format

```markdown
---
id: ADR-XXX
title: [Decision title]
date: YYYY-MM-DD
status: proposed | accepted | deprecated | superseded-by ADR-XXX
---

## Context
What situation forced this decision.

## Decision
What we decided.

## Rationale
Why this option over alternatives.

## Consequences
What becomes easier, what becomes harder.
```

#### Pre-dev review format (advisory/)

This is the output format for `/board-review`. It is intentionally short — one page maximum.
The purpose is to give the team something they can read together in 15 minutes and act on.

```markdown
---
feature-id: F-XXX
reviewed: YYYY-MM-DD
board-members-consulted: [list of board member names from BOARD.md]
---

## 1. Conflicts
Does this feature conflict with anything already built or decided?
Named conflicts only — reference specific feature IDs, ADR IDs, or business rule IDs.
If none: "No conflicts identified."

## 2. Gaps
Is there anything missing from the current spec that will block development before it starts?
Examples: undefined error states, missing acceptance criteria, API shape not agreed,
edge cases not covered for vulnerable user groups.
If none: "Spec is complete."

## 3. Build order
Across platforms, what must be built first?
Example: "Backend authentication API (F-001) must be live before mobile clients can be
tested end-to-end. iOS and Android can be built in parallel once backend is ready."
If no dependencies: "No cross-platform ordering constraints."

## 4. Biggest risk
One sentence. What is most likely to cause this feature to fail, cause user harm, or
take significantly longer than expected?
Example: "The nutrition score algorithm will produce culturally biased results unless
tested against non-Western food databases — flag for board member Dr. Mitchell."

## Board perspective summaries
[One short paragraph per board member who has a relevant concern.]
[Only include members with something substantive to say — omit members with no concerns.]

## Actions required before dev starts
- [ ] [Specific action with owner — po / designer / dev]
- [ ] [Specific action with owner]

## Actions that can be deferred
- [Action that can be addressed post-ship with acceptable risk]
```

#### index.md conventions — status board format

The index is a **feature status board**, not a flat catalogue.

```markdown
# Feature Status Board

| ID | Feature | Status | Owner | Board Review | Introduced |
|----|---------|--------|-------|--------------|------------|
| F-001 | User login | in-dev | dev | not-needed | 2026-04-01 |
| F-002 | Nutrition score | ready-for-design | designer | pending | 2026-04-03 |

## Other wiki pages
| Page | Type | Summary | Date |
|------|------|---------|------|
| [SCHEMA.md](SCHEMA.md) | meta | Wiki conventions and rules | — |
| [BOARD.md](advisory/BOARD.md) | config | Advisory board composition | — |
| [ADR-001](decisions/ADR-001-auth-strategy.md) | decision | Chose JWT over sessions | 2026-04-01 |
```

The LLM must update the status board row whenever a feature's status, owner, or
advisory-review field changes.

#### log.md conventions

Append-only. Every operation appends a new entry:

```
## YYYY-MM-DD [operation] | [subject]
Brief description of what changed and why.
```

Never edit existing entries.

#### Operational rules

Tell AI agents:
- Always read `SCHEMA.md` before performing any wiki operation
- Always read `index.md` before creating a new page (check if it already exists)
- **Never modify files in `intake/pending/`** — treat them as read-only inputs
- After processing intake, move items to `intake/processed/[name]/` on success or
  `intake/quarantined/[name]/` if the content conflicts with existing wiki entries
- Always update `index.md` and append to `log.md` after any operation
- Only create platform-requirements pages for platforms included in this generated project
- Use relative markdown links between wiki pages
- Before running `/board-review`, always read `advisory/BOARD.md` in full
- **Confirm before committing:** for any intake command, show the user a summary of what
  you intend to create or modify and wait for confirmation before writing files. If the
  user corrects your interpretation, revise and confirm again before proceeding. This rule
  is not optional. Its purpose is to prevent the wiki from filling with AI-hallucinated
  requirements that no human actually specified.

---

### 5.2 `template/knowledge/intake/README.md`

Instructions for all three roles:

```markdown
# Intake — dropping raw inputs into the wiki

This is where raw, unprocessed inputs live before the AI organizes them.

## Who drops what here

**Product Owner:** meeting transcripts, client feedback summaries, user research notes,
feature request descriptions. Use PO_BRIEF_TEMPLATE.md as a guide. Raw notes are fine —
the more structured your input, the more accurate the output.

**Designer:** design spec notes, Figma annotations, interaction descriptions, component
decisions. Use DESIGN_HANDOFF_TEMPLATE.md as a guide. Attach a Figma link or exported
PNG/PDF if available.

**Developer:** technical constraints, feasibility findings, platform-specific edge cases
discovered during implementation. Drop as a markdown note referencing the feature ID.

## How to contribute

1. Create a folder: intake/pending/[descriptive-name]/
   Examples: meeting-client-2026-04-01/, feature-search-design/, f003-feasibility-notes/
2. Drop your files into that folder
3. Run the appropriate command:
   - PO: `po-intake [folder-name]`
   - Designer: `design-intake [F-XXX] [folder-name]`
   - Developer: add notes directly to the feature's open questions section

   Command syntax by tool:
   - Claude Code: `/po-intake [folder]` or `/design-intake [F-XXX] [folder]`
   - Codex: `po-intake [folder]` or `design-intake [F-XXX] [folder]`
   - Cursor: ask the agent to "run po-intake on [folder]" or "run design-intake on F-XXX [folder]"

## After processing

Processed items are moved to intake/processed/[folder-name]/ automatically with a
manifest of what was extracted.

Items that conflict with existing wiki content are moved to intake/quarantined/[folder-name]/
with a conflict explanation. A human must resolve the conflict before the item can be
processed.

## What "conflict" means

A conflict occurs when the new input directly contradicts established wiki content.
Examples:
- PO notes say "feature X requires no authentication" but BR-001 says all features require auth
- Design handoff shows a flow explicitly rejected in ADR-002
- New feature request duplicates an existing feature with different acceptance criteria

Conflicts are not errors — they are important signals. The quarantine mechanism ensures
they surface for human resolution rather than silently overwriting agreed decisions.
```

---

### 5.3 `template/knowledge/intake/pending/PO_BRIEF_TEMPLATE.md`

A structured guide for the PO. Not mandatory to fill in — raw notes work — but filling it
in reduces the AI's interpretation burden and produces more accurate feature specs.

```markdown
# PO Brief — [Feature name]

You do not need to fill in every section. Partial information is fine.
The AI will ask clarifying questions for anything missing.

## What is the feature?
One or two sentences describing what the feature does.

## Who needs it?
Which type of user/customer is asking for this?

## What problem does it solve?
What is the user currently doing instead? What frustrates them?

## Why does this matter to the business?
Revenue impact, retention, competitive pressure, legal requirement — pick one or more.

## What does "done" look like?
How will we know the feature is working?

## What must NOT happen?
Edge cases, failure modes, or business constraints the feature must respect.

## Does this feature need an advisory board review?
Yes / No / Unsure

Use "Yes" for features that: involve domain calculations (nutrition scores, financial ratings),
have behavioral implications (gamification, social comparison), touch vulnerable users,
or where getting it wrong has real-world consequences outside the app.

Use "No" for: authentication flows, settings screens, CRUD operations, admin tools,
notification preferences, infrastructure changes.

## Source
Where did this come from? Date: YYYY-MM-DD

## Raw notes
Paste any raw meeting notes, customer quotes, or feedback here.
```

---

### 5.4 `template/knowledge/intake/pending/DESIGN_HANDOFF_TEMPLATE.md`

```markdown
# Design Handoff — [Feature name / F-XXX]

## Feature ID
F-XXX (or "new feature — no ID yet")

## Figma link
[Paste Figma URL here, or "not available"]

## What this design covers
Which screens, flows, or components does this handoff address?

## Key design decisions (that affect implementation)
Decisions not obvious from visuals alone.
Examples:
- "The confirmation step is a full-screen modal, not an inline dialog"
- "Errors appear inline below the field, not in a toast"
- "This list is paginated, not infinite scroll — 20 items per page"

## States designed
- [ ] Empty state
- [ ] Loading state
- [ ] Error state (network)
- [ ] Error state (validation)
- [ ] Success state
- [ ] Edge case: [describe]

## States NOT designed (developer must decide)

## Open design questions

## Date
YYYY-MM-DD
```

---

### 5.5 `template/CONTEXT.md.jinja`

A master context anchor at the monorepo root. LLM-maintained and human-readable.
This file uses Jinja2 templating and is rendered at generation time.

**Important:** the platform conditional checks must use the exact platform identifier
values defined in `copier.yml`. Before writing this file, read `copier.yml` and confirm
the values. The current template uses `mobile-android` and `mobile-ios` (not `android`
and `ios`). Use whatever the live questionnaire actually uses.

```
# {{ project_name }} — Product context

This file is the master context anchor for all AI agents working in this repository.
Read this before working in any platform directory.

## Project identity

**Name:** {{ project_name }}
**Description:** {{ description }}

## First-time setup

If this is a newly scaffolded project, run the setup command before anything else.
It initializes the wiki, interviews you about your domain, and generates the advisory
board configuration. It takes 15–20 minutes and runs once.

- **Claude Code:** `/setup-project`
- **Codex:** `$setup-project`
- **Cursor:** ask the agent: "run setup-project" — it will follow the steps in
  `knowledge/wiki/SCHEMA.md` and `.claude/commands/setup-project.md`

## Repository structure

```
{% if "backend" in platforms %}backend/           # Spring Boot 4 (Kotlin 2.2+, Java 21)
{% endif %}{% if "web-user-app" in platforms %}web-user-app/      # Next.js + TypeScript user-facing web app
{% endif %}{% if "web-admin-portal" in platforms %}web-admin-portal/  # Next.js + TypeScript admin web portal
{% endif %}{% if "mobile-android" in platforms %}mobile-android/    # Kotlin + Jetpack Compose (MVVM)
{% endif %}{% if "mobile-ios" in platforms %}mobile-ios/        # Swift 6 + SwiftUI (MVVM)
{% endif %}shared/            # OpenAPI 3.1 spec + design tokens
knowledge/         # Living product wiki — single source of truth for all features
```

## The product wiki

All product knowledge lives in knowledge/wiki/. Before implementing any feature:

1. Read knowledge/wiki/index.md — confirm the feature is in ready-for-dev or in-dev status
2. Read knowledge/wiki/features/[feature-id]-[slug].md for full context
3. Read knowledge/wiki/platform-requirements/[feature-id]-[THIS_PLATFORM].md
4. Read knowledge/wiki/api-contracts/[feature-id].md if an API surface is involved
5. Check knowledge/wiki/business-rules/ for rules that apply to this feature
6. Check knowledge/wiki/advisory/BOARD.md to understand the domain intelligence layer

The wiki is the single source of truth. If a feature has no wiki page, do not implement
it. Ask the human to run the `po-intake` operation first
(Claude: `/po-intake [folder]`, Codex: `po-intake [folder]`,
Cursor: ask the agent to "run po-intake on [folder]").

## Available commands

**Claude Code slash commands** (use `/command` syntax):

Setup: `/setup-project`
PO: `/po-intake [folder]`, `/po-clarify`, `/po-handoff [F-XXX]`
Designer: `/design-intake [F-XXX] [folder]`, `/design-clarify`, `/design-handoff [F-XXX]`
Developer: `/prep-sprint`, `/dev-done [F-XXX]`
Board: `/board-review [F-XXX]`
Shared: `/feature-status`, `/ask [F-XXX] "question" --to po|designer|dev`,
        `/audit-feature [F-XXX]`, `/lint-wiki`

**Codex** (use `$skill` for structured skills, plain name for lifecycle operations):

Skills with dedicated files: `$setup-project`, `$board-review`, `$prep-sprint`,
`$feature-status`, `$lint-wiki`

Lifecycle operations (invoke by name): `po-intake`, `po-clarify`, `po-handoff`,
`design-intake`, `design-clarify`, `design-handoff`, `dev-done`, `ask`, `audit-feature`

**Cursor**: ask the agent by operation name, e.g. "run setup-project" or "run po-intake
on the folder meeting-notes-2026-04-07". The agent will follow the steps in
`.claude/commands/[command].md` and `knowledge/wiki/SCHEMA.md`.

## Tech stack and architectural constraints

See knowledge/wiki/decisions/ for Architecture Decision Records.
See shared/api-contracts/openapi.yml for the API contract.
See docs/architecture.md for the system overview.
```

---

### 5.6 Claude command files

These live in `template/.claude/commands/` and are available as slash commands in Claude Code
for any generated project.

**File naming:** All command source files use the `.md.jinja` suffix, consistent with
the existing command files in `template/.claude/commands/` (e.g. `scaffold-feature.md.jinja`).
Copier strips the `.jinja` suffix on generation, so the rendered files in a generated project
are plain `.md`. When the plan refers to a command file name, it means the source
`template/.claude/commands/[name].md.jinja` file, which renders to `.claude/commands/[name].md`
in the generated project.

**Critical rule embedded in every intake command:** the AI must show the user a summary of
what it intends to create or modify and wait for confirmation before writing any files.
This is non-negotiable and must be explicit in each intake command's step list.

---

#### `setup-project.md.jinja`

```markdown
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

Example member (from Ingredish, a recipe and nutrition app):

---
**Dr. Sarah Mitchell — Lead Nutrition Advisor**
Title: Senior Clinical Dietitian
Institution: Harvard School of Public Health — Nutritional Epidemiology Division
Expertise:
- Clinical nutrition and dietetics
- Macro/micro nutrient profiling
- Nutritional risk evaluation (sodium, added sugar, fiber, fats)
- Balanced dietary patterns based on global guidelines
Why on this board: The nutrition score algorithm must align with evidence-based
dietary guidelines, not just calorie counting. Dr. Mitchell catches cases where
the algorithm produces recommendations that are technically "healthy" by one metric
but harmful by another.
Typical questions:
- "Does this scoring method penalize traditionally healthy foods from non-Western diets?"
- "Is this fiber threshold appropriate for users with IBS?"
- "What happens when a user is pregnant — does the algorithm account for altered needs?"
---

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
  (see section 5.10 for the required format)
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
```

---

#### `board-review.md.jinja`

```markdown
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
substantive concerns). Only include members with real concerns — do not pad with
members who have nothing to add for this particular feature.

End with: a checklist of actions required before dev starts, and actions that can
be deferred without blocking development.

## Notes for the agent

- Specificity is the entire value of this review. "Consider security" is useless.
  "Dr. Mitchell notes that the nutrition score for a traditional Japanese bento box
  will score poorly under Western macro-first frameworks — flag for localization" is useful.
- For each concern, name the source: which board member raised it, in what domain context.
- Debates between board members are important signal. If the nutritionist and the
  behavioral psychologist disagree on whether to show a numerical score vs. a qualitative
  label, say so explicitly and let the team decide.
- A review that finds no concerns is a valid and useful output. State explicitly that
  the board reviewed the feature and found it sound. Do not invent concerns to justify
  the operation.
- The review is NOT a governance gate — the team does not need the board's "approval."
  It is an intelligence input. The team decides what to do with the findings.
```

---

#### `po-intake.md.jinja`

```markdown
# PO intake — process raw notes into feature specs

Process a raw input document from intake/pending/ into structured wiki entries.

## Usage
/po-intake [folder-name]

Example: /po-intake meeting-client-2026-04-01

## What this command does

1. Read `knowledge/wiki/SCHEMA.md` in full
2. Read `knowledge/wiki/index.md` to understand existing features
3. Read `knowledge/wiki/personas/` — understand who the current users are
4. Read `knowledge/wiki/business-rules/` — understand existing constraints
5. Read all files in `knowledge/intake/pending/[folder-name]/`
6. **STOP. Conflict check (before any writes):**
   Check whether anything in the input conflicts with existing wiki content.
   Conflicts include: a point that directly contradicts an existing feature spec,
   business rule, or ADR; a feature request that duplicates an existing feature
   with different acceptance criteria; a design or workflow explicitly rejected in
   an ADR; auth requirements that contradict existing business rules.
   - If conflicts exist: move `intake/pending/[folder-name]/` to
     `intake/quarantined/[folder-name]/`, write a `CONFLICT.md` in the quarantined
     folder explaining what the new input claims, what the existing wiki says, which
     files are in conflict, and what decision the human needs to make. Inform the user.
     **Stop — do not write or modify any wiki files.** The human resolves the conflict,
     then re-runs `/po-intake` on the corrected input.
   - If no conflicts: proceed to step 7.
7. **STOP. Show the user a summary of your interpretation:**
   - What new features does this input describe? (list by proposed title)
   - What existing features does it update or clarify?
   - What new personas or business rules does it introduce?
   - What is ambiguous or unclear that you could not resolve?
   - For each new feature: does it appear to need an advisory board review?
     (reference the criteria in /board-review.md)
   **Wait for the user to confirm, correct, or cancel before proceeding.**
8. For each new feature identified and confirmed:
   - Assign the next available feature ID
   - Create `knowledge/wiki/features/[F-XXX]-[slug].md` using the feature format from SCHEMA.md
   - Set status: `specified`, owner: `po`
   - Set `advisory-review` field based on team confirmation:
     `pending` if domain complexity confirmed, `not-needed` if confirmed simple feature
   - Populate open questions for anything missing from the input
   - Route design-related open questions to owner: `designer`
   - Route technical feasibility questions to owner: `dev`
9. For each new persona identified, create or update `knowledge/wiki/personas/[slug].md`
10. For each business rule identified, create `knowledge/wiki/business-rules/[BR-XXX]-[slug].md`
11. Update `knowledge/wiki/index.md` status board with new feature rows
12. Append to `knowledge/wiki/log.md`
13. Move `intake/pending/[folder-name]/` to `intake/processed/[folder-name]/`
    with a `MANIFEST.md` listing what was extracted

## Notes for the agent

- Do not invent requirements not present in the input. Mark gaps as open questions.
- Business language in the input should stay business language in the summary.
- If the input mentions an existing feature by name or description, check whether it
  updates that feature's spec rather than creating a duplicate.
- A single input document may produce multiple features, personas, and business rules.
- Do not set `advisory-review: not-needed` by default. Ask the user explicitly for any
  feature where domain complexity is ambiguous.
```

---

#### `po-clarify.md.jinja`

```markdown
# PO clarify — answer open questions assigned to PO

## Usage
/po-clarify

## What this command does

1. Read `knowledge/wiki/SCHEMA.md`
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
   - If the answer contradicts an existing wiki entry, flag and quarantine
6. Update `index.md` if any feature's owner or status changes
7. Append a single log entry summarizing all questions resolved

## Notes for the agent

- Present questions one feature at a time. Do not dump all questions at once.
- After each answer, confirm what you updated before moving to the next.
- If the user's answer introduces a new open question, add it immediately.
- Questions tagged "[Board: ...]" came from a board review. Treat them with the same
  priority as other open questions.
```

---

#### `po-handoff.md.jinja`

```markdown
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
  receives a brief already informed by domain expert concerns. Running it after design
  means the designer may have spent days on flows that the board would have flagged.
```

---

#### `design-intake.md.jinja`

```markdown
# Design intake — attach design artifacts to a feature

## Usage
/design-intake [F-XXX] [folder-name]

## What this command does

1. Read `knowledge/wiki/SCHEMA.md`
2. Read `knowledge/wiki/features/[F-XXX]-[slug].md`
3. Read `knowledge/wiki/business-rules/`
4. Read `knowledge/wiki/advisory/[F-XXX]-review.md` if it exists — design must not
   contradict board review findings
5. Read all files in `knowledge/intake/pending/[folder-name]/`
6. **STOP. Show the user a summary of your interpretation:**
   - Which feature flows does this design address?
   - What key design decisions does it make that affect implementation?
   - Which UI states are covered and which are missing?
   - Does any design decision conflict with the feature spec, business rules, ADRs,
     or board review findings?
   **Wait for confirmation before proceeding.**
7. Create `knowledge/wiki/design/[F-XXX]-[slug].md`
8. Update the `## Design` section of the feature file
9. For any UI states not covered, add open questions with owner = `designer`
10. Update `index.md` and append to `log.md`
11. Move intake folder to `processed/` or `quarantined/` as appropriate

## Notes for the agent

- If a board review exists for this feature, check whether the design addresses the
  board's concerns. If a board concern is unaddressed by the design, flag it as an
  open question with owner = `designer`.
- Figma links cannot be read directly. Note the URL and proceed with written descriptions.
```

---

#### `design-clarify.md.jinja`

```markdown
# Design clarify — answer open questions assigned to Designer

## Usage
/design-clarify

## What this command does

Identical in structure to /po-clarify but filters for open questions where owner = `designer`.

Present questions grouped by feature. For each answer:
- Update the open questions table in the feature file
- If the answer reveals a missing design artifact, note it in the design page
- If the answer resolves a design state gap, update the design page's "States covered" section

Append to log.md with a summary of questions resolved.
```

---

#### `design-handoff.md.jinja`

```markdown
# Design handoff — move a feature to ready-for-development

## Usage
/design-handoff [F-XXX]

## What this command does

1. Read `knowledge/wiki/features/[F-XXX]-[slug].md`
2. Read `knowledge/wiki/design/[F-XXX]-[slug].md` if it exists
3. Determine whether this feature has UI platform scope:
   - UI platforms: `mobile-android`, `mobile-ios`, `web-user-app`, `web-admin-portal`
   - Non-UI: `backend`-only features, API-only features, infra changes, internal tooling
4. Run completeness check:
   - **If UI platforms are in scope:**
     - A design page linked in the `## Design` section (or `design: not-applicable`
       with a reason if the feature genuinely needs no visual design)
     - Design coverage for all UI states implied by acceptance criteria
   - **If no UI platforms are in scope (backend/API/infra):**
     - Design page is not required — skip design coverage check
     - Set `design: not-applicable` in the feature file if it is not already set
   - For all features: no open questions with owner = `designer`
   - Status of `in-design` or `ready-for-design`
5. Check `advisory-review` field:
   - If `pending`: board review has not been run. Inform the user. Ask:
     "Do you want to run board-review F-XXX before handing to development?"
     - If yes: run board review, then re-check completeness (step 4) before continuing.
     - If no: set `advisory-review: skipped` and require a reason. Record the reason in
       the feature file frontmatter: `advisory-skip-reason: [reason]`. Do not allow
       handoff without a reason — this is the last gate before development starts.
   - If `done`: check that the board review's "Actions required before dev starts"
     checklist has been addressed. If items remain open, list them and ask how to proceed.
6. If the completeness check fails, list what is missing and stop
7. If the check passes:
   - Show the user: status → `ready-for-dev`, owner → `dev`
   - Wait for confirmation
   - Update feature file frontmatter
   - Generate platform-requirements pages for all platforms in scope, incorporating
     design decisions and any board review findings relevant to implementation
   - Update `index.md` and append to `log.md`

## Notes for the agent

- Platform-requirements pages are generated at handoff time (not at intake time) because
  the spec is now complete and can be derived accurately.
- The developer-facing requirements must be in technical language. Translate design
  language: "modal that blocks interaction" → platform-appropriate implementation pattern.
- If a board review found concerns, include relevant concerns in the platform-requirements
  pages for the affected platforms. Developers should not have to cross-reference the
  review file themselves.
```

---

#### `prep-sprint.md.jinja`

```markdown
# Prep sprint — show what is ready to build

## Usage
/prep-sprint

## What this command does

1. Read `knowledge/wiki/SCHEMA.md`
2. Read `knowledge/wiki/index.md`
3. Read all feature files with status = `ready-for-dev` or `in-dev`
4. For each feature, read its platform-requirements pages
5. Output a structured report:

   ```
   ## Ready to build

   ### F-002 — Profile Edit [ready-for-dev]
   Platforms: mobile-android, mobile-ios, backend
   Design: knowledge/wiki/design/F-002-profile-edit.md
   Board review: done
   Requirements:
   - Android: knowledge/wiki/platform-requirements/F-002-mobile-android.md
   - iOS: knowledge/wiki/platform-requirements/F-002-mobile-ios.md
   - Backend: knowledge/wiki/platform-requirements/F-002-backend.md
   Open dev questions: none
   Dependencies: none

   ### F-004 — Push Notifications [in-dev]
   ...

   ## Blocked (has dev-owned open questions)
   - F-006 — Search: "Is full-text search feasible with current DB? [dev, open]"

   ## Board review pending (not ready for dev)
   - F-007 — Nutrition Score [specified, advisory-review: pending]

   ## Not ready (in earlier lifecycle stages)
   - F-003 — Admin dashboard [in-design, owner: designer]
   ```

6. Do not modify any wiki files. Read-only command.

## Notes for the agent

- Features with `advisory-review: pending` must not appear in the "Ready to build"
  section. List them separately under "Board review pending."
- Dependencies must be checked and stated explicitly.
- If any ready-for-dev feature has no platform-requirements pages, flag it as incomplete.
```

---

#### `dev-done.md.jinja`

```markdown
# Dev done — mark a feature as shipped

## Usage
/dev-done [F-XXX]

## What this command does

1. Read `knowledge/wiki/features/[F-XXX]-[slug].md`
2. Show the user what will change and ask:
   "Any deviations from the spec to record? Any board review concerns that turned out
   differently in implementation than expected? Any lessons learned?"
3. If the user provides notes, append a `## Post-ship notes` section to the feature file
4. Update feature file: status → `done`, owner → `none`
5. Update all platform-requirements pages: status → `done`
6. Update api-contracts page if it exists: status → `implemented`
7. Update `index.md` status board
8. Append to `log.md`

## Notes for the agent

- If a board review was done for this feature, ask specifically: "Did any of the board's
  concerns materialize? Were any concerns unfounded? This helps calibrate future reviews."
- Deviations from spec are valuable wiki content. If the developer built something
  different from what was specified, that difference belongs in post-ship notes.
```

---

#### `feature-status.md.jinja`

```markdown
# Feature status — full pipeline view

## Usage
/feature-status

## What this command does

Read index.md and all feature files. Output a full pipeline view grouped by status:

```
## Pipeline

raw (1)             F-008 — [title] | owner: po

specified (2)       F-006 — [title] | owner: po | open questions: 3 | board: pending
                    F-007 — [title] | owner: po | open questions: 0 | board: not-needed

ready-for-design    F-003 — [title] | owner: designer | board: done

in-design (1)       F-005 — [title] | owner: designer | board: pending (not yet run)

ready-for-dev (2)   F-002 — [title] | owner: dev | platforms: mobile-android, mobile-ios, backend | board: done
                    F-004 — [title] | owner: dev | platforms: backend | board: not-needed

in-dev (1)          F-001 — [title] | owner: dev

done (1)            F-000 — [title]
```

After the pipeline:
- All open questions grouped by owner role
- Any intake items in quarantined/ needing human resolution
- Features with advisory-review: pending that have not had a board review run

Read-only command. Do not modify any wiki files.
```

---

#### `ask.md.jinja`

```markdown
# Ask — route a question to the right role

## Usage
/ask [F-XXX] "[question text]" --to po|designer|dev

Examples:
/ask F-003 "What is the maximum number of items a user can save?" --to po
/ask F-007 "What does the overflow state look like at 50+ items?" --to designer

## What this command does

1. Read `knowledge/wiki/features/[F-XXX]-[slug].md`
2. Add a new row to the open questions table:
   - Next question number for this feature
   - Owner = the value of --to
   - Status = `open`
3. Show the user the updated open questions table for confirmation
4. Update the feature file
5. Append to `log.md`
```

---

#### `audit-feature.md.jinja`

```markdown
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
```

---

#### `lint-wiki.md.jinja`

```markdown
# Lint wiki — health-check the knowledge base

## Usage
/lint-wiki

## What this command does

1. Read SCHEMA.md, index.md, and all files in all wiki subdirectories
2. Check for and report:
   a. **Missing platform requirements** — features in ready-for-dev or later with no
      platform-requirements page for one or more active platforms
   b. **Design gaps** — features in in-design or later with no design page
   c. **API contract gaps** — features with an API surface but no api-contracts page
   d. **Contradictions** — conflicting behaviour descriptions across platform-requirements
      pages, or specs that contradict business-rules pages
   e. **Board review pending** — features in ready-for-dev or in-dev with
      advisory-review: pending (these should have been reviewed before dev started)
   f. **Skipped board reviews** — features with advisory-review: skipped; list the
      reason given and the feature name (for team awareness, not as an error)
   g. **Orphan pages** — wiki pages not linked from any other page and not in index.md
   h. **Index drift** — pages on disk missing from index.md, or index.md entries for
      pages that don't exist
   i. **Stale status** — features in in-dev for more than 14 days (flag, do not auto-update)
   j. **Quarantine backlog** — items in intake/quarantined/ older than 7 days
   k. **Unresolved open questions** — features in ready-for-dev or in-dev with open
      questions (should have been resolved before handoff)
   l. **Missing ADRs** — significant technical choices in platform-requirements with no
      corresponding decision record
3. Output a lint report as `knowledge/wiki/lint-[YYYY-MM-DD].md`
4. Append to log.md

## Notes for the agent

- Do not auto-fix. Report and let the human decide.
- For each issue: affected file(s), description of the problem, suggested remediation.
- An empty lint report is a healthy sign. State explicitly if the wiki is consistent.
```

---

### 5.7 Platform context file additions (CLAUDE.md.jinja and AGENTS.md)

**Before modifying any platform context file:** read it and confirm the platform
identifier matches the wiki's platform-requirements filenames. Platform identifiers come from
`copier.yml` — use those exact values.

Add the following section near the top of **each platform's** AI context files.
This applies to both `CLAUDE.md.jinja` (Claude Code) and `AGENTS.md` (Codex):

```markdown
## Product knowledge wiki

This project uses a shared product wiki at `knowledge/wiki/` as the single source of
truth for what to build. Before implementing any feature:

1. Read `knowledge/wiki/index.md` — confirm the feature is in `ready-for-dev` or `in-dev`
   status and that `advisory-review` is not `pending`. If advisory-review is pending,
   stop and inform the human — a board review should happen before implementation.
2. Read `knowledge/wiki/features/[feature-id]-[slug].md` for full context
3. Read `knowledge/wiki/platform-requirements/[feature-id]-[THIS_PLATFORM].md` for your
   specific implementation requirements
4. Read `knowledge/wiki/api-contracts/[feature-id].md` if this feature has an API surface
5. Check `knowledge/wiki/business-rules/` for rules that apply to this feature
6. If you are a UI platform: read `knowledge/wiki/design/[feature-id]-[slug].md`

**Do not implement features without a wiki page.** Ask the human to run the `po-intake`
operation first (Claude: `/po-intake [folder]`, Codex: `po-intake [folder]`,
Cursor: ask the agent to "run po-intake on [folder]").

If you discover information during implementation that should update the wiki, propose
the update and ask for confirmation before writing, or route a question using the `ask`
command (Claude: `/ask F-XXX "..." --to po`, Codex: `ask F-XXX "..." --to po`).
```

**Root generated context templates (update these first — they affect all generated projects):**
- `template/CLAUDE.md.jinja` — remove `docs/features/` and `docs/advisory-board.md`
  references; add wiki reference section and updated command list
- `template/AGENTS.md.jinja` — remove `$scaffold-feature` and `docs/advisory-board.md`
  references; add wiki reference section and updated skill list

**Platform context templates (all use `.jinja` suffix — do not omit it):**
- `template/backend/CLAUDE.md.jinja` and `template/backend/AGENTS.md.jinja`
- `template/mobile-android/CLAUDE.md.jinja` and `template/mobile-android/AGENTS.md.jinja`
- `template/mobile-ios/CLAUDE.md.jinja` and `template/mobile-ios/AGENTS.md.jinja`
- `template/web-user-app/CLAUDE.md.jinja` and `template/web-user-app/AGENTS.md.jinja`
- `template/web-admin-portal/CLAUDE.md.jinja` and `template/web-admin-portal/AGENTS.md.jinja`

All of these files exist. The `.jinja` suffix is required — Copier strips it on generation.
Do not look for `AGENTS.md` (no suffix) in the template directory; that file does not exist
there and will not be found.

**Codex skills:** Update `template/.agents/skills/` as follows:

**Skills with dedicated skill files** (structured, multi-step operations that Codex
cannot reliably infer from AGENTS.md context alone):
- `$setup-project` — **new skill**; required because it is the first step before any
  other wiki operation and Codex needs an explicit execution path for it
- `$board-review` — **replaces `$advisory-review`**; rename the skill directory and
  update its SKILL.md.jinja to reference BOARD.md and the four-question review format
- `$prep-sprint` — **new skill**; reads multiple wiki files and produces a structured
  report — benefits from explicit step sequencing
- `$feature-status` — **new skill**; reads the full pipeline state
- `$lint-wiki` — **new skill**; spans all wiki directories

**`$scaffold-feature` is retired.** Do not update it in place. Delete the
`template/.agents/skills/scaffold-feature/` directory entirely. The old skill drove
a single-command "PO note to shipped code" flow — exactly the anti-pattern this system
replaces. Keeping it as a wrapper skill would encourage treating the new wiki lifecycle
as the old one-step workflow. Generated AGENTS.md.jinja must not reference it.

**Operations documented in AGENTS.md only (no skill file):**
The following operations are documented in `template/AGENTS.md.jinja` as plain command
names (without `$` prefix, since `$` implies a skill file in `.agents/skills/`).
They do not need dedicated skill files — they are already fully specified in SCHEMA.md
and their steps are simple enough for Codex to execute from context:
- `po-intake`, `po-handoff`, `po-clarify`
- `design-intake`, `design-handoff`, `design-clarify`
- `dev-done`, `ask`, `audit-feature`

**The `$` prefix rule:** Only use `$name` when a skill file exists at
`template/.agents/skills/[name]/`. If there is no skill file, document the operation
as a plain name. Mixing the two conventions in the same AGENTS.md creates false
expectations about what Codex can invoke as a structured skill.

**Cursor rules:** Add `template/.cursor/rules/wiki.mdc.jinja` with the wiki-read-before-implement
instruction. Use the `.mdc.jinja` suffix for consistency with the existing Cursor rule
`template/.cursor/rules/api-conventions.mdc.jinja` — even if this file contains no Jinja
expressions, the suffix convention is established in this repo and should not be broken
without explicit justification.

---

### 5.8 `template/knowledge/wiki/index.md` (initial state)

```markdown
# Feature Status Board

This file is maintained by the AI agent. Do not edit directly.

| ID | Feature | Status | Owner | Board Review | Introduced |
|----|---------|--------|-------|--------------|------------|

## Other wiki pages
| Page | Type | Summary | Date |
|------|------|---------|------|
| [SCHEMA.md](SCHEMA.md) | meta | Wiki conventions and operational rules | — |
| [BOARD.md](advisory/BOARD.md) | config | Advisory board composition | — |
```

---

### 5.9 `template/knowledge/wiki/log.md` (initial state)

```markdown
# Wiki log

Append-only record of all wiki operations. Most recent entry at the bottom.
Format: ## YYYY-MM-DD [operation] | [subject]

---

## [project-creation-date] init | Wiki initialized

Wiki created from Prism template. Run /setup-project to initialize the advisory board
and complete project setup.
```

---

### 5.10 `template/knowledge/wiki/advisory/BOARD.md` (format specification)

`BOARD.md` is a configuration file written during `/setup-project` and confirmed by the team.
It is not a template shipped in the Copier output — it is generated by the AI during setup.
What IS shipped in the template is a placeholder file at `advisory/BOARD.md` with instructions
for what `/setup-project` will write here.

**Placeholder content (shipped with template):**

```markdown
# Advisory Board

This file will be generated by /setup-project. Run that command first.

The advisory board is a set of domain expert personas defined specifically for this
product's risk profile. They are consulted during /board-review for features with
domain complexity.

To generate or regenerate this file, run /setup-project.
```

**Target format (written by /setup-project after team confirmation):**

```markdown
# Advisory Board — [Project Name]

Generated: YYYY-MM-DD
Board size: [N] members

This board was defined based on the following domain risks identified during project setup:
- [Risk 1 — one sentence from the domain risk interview]
- [Risk 2]
- [Risk 3]

---

## When to consult this board

**Consult for features that:**
- [Product-specific criterion 1 — derived from setup interview]
- [Product-specific criterion 2]
- Involve domain calculations: [list specific calculation types for this product]
- Touch vulnerable user groups: [list specific groups for this product]

**Do not consult for:**
- Authentication, login, password management
- Settings and preferences
- Basic CRUD operations
- Internal admin tools
- Infrastructure changes

---

## Board Members

### [Name] — [Short role title]
**Title:** [Full professional title]
**Institution:** [Named institution]
**Expertise:**
- [Area 1]
- [Area 2]
- [Area 3]

**Why on this board:** [One sentence connecting their expertise to a specific failure mode
identified during setup. This is the most important field — it explains why this person
matters for this specific product, not just generally.]

**Typical questions they ask:**
- "[Specific question in their domain language, concrete to this product]"
- "[Second question]"
- "[Third question]"

---

### [Next member...]

---

## Board revision history
| Date | Change | Reason |
|------|--------|--------|
| [date] | Board created | Initial project setup |
```

**Why "typical questions" are required for each member:**
These questions are the training signal for the AI. When `/board-review` runs, the AI
uses the typical questions as the lens through which each board member views the feature.
Generic expertise descriptions produce generic concerns. Specific questions produce
specific, actionable concerns. They must be written in the domain expert's language,
not the developer's language.

**Example — Ingredish recipe app (reference implementation):**

The Ingredish board as a reference for what a well-defined board looks like. This is
not a template — it is an example of what `/setup-project` should produce for a health
and nutrition product.

Members for Ingredish:
1. Dr. Sarah Mitchell — Clinical Dietitian (Harvard SPH) — nutrition algorithm validity
2. Chef Marcus Chen — Michelin-Star Executive Chef (Singapore) — culinary accuracy
3. Dr. Elena Rodriguez — Food Chemist (Nestlé R&D) — ingredient science
4. Dr. James Patterson — Behavioral Scientist (Stanford) — eating psychology and UX
5. Dr. Hana Mori — Sensory Scientist (Kikkoman) — flavor and cultural food experience

Typical questions for Dr. Mitchell: "Does this scoring method penalize traditionally
healthy foods from non-Western cuisines?" / "Is this threshold appropriate for users
with IBS or other digestive conditions?" / "What disclaimer is required when this
feature makes a recommendation that could be interpreted as medical advice?"

Typical questions for Dr. Patterson: "Does this feature design reward or shame users
for their food choices?" / "Does the gamification mechanic create anxiety around eating?"
/ "Is the information presented in a way that could reinforce disordered eating patterns?"

---

## 6. Changes to `copier.yml`

**The knowledge wiki is required.** Do not add an `include_knowledge_wiki` optional toggle.
The wiki is not a feature — it is the coordination substrate the project depends on.

**Do not add a `product_domain` question.** The domain is determined through the
interactive domain risk interview in `/setup-project`, not through a static dropdown.
A dropdown of domains (health, fintech, edtech, etc.) cannot capture the nuance of what
actually matters for a specific product. The interview produces better board composition.

**Confirm `description` exists (do not add a duplicate):**

`copier.yml` already has a `description` field at line 71:
```yaml
description:
  type: str
  help: "One-line project description"
  default: "A multi-platform application"
```

Use `{{ description }}` (not `{{ project_description }}`) in `CONTEXT.md.jinja` and any
other template that references the project description. Do not add a `project_description`
field — it would be a duplicate of an existing questionnaire answer.

**Verify platform identifier values:**

Before writing any Jinja2 template that uses platform conditionals, read `copier.yml` and
note the exact string values for each platform option. Use those exact values — not assumed
values like `android` — in every `{% if 'X' in platforms %}` conditional. A wrong value
silently produces empty output with no error.

---

## 7. Changes to existing files

### 7.1 Root `README.md`

Replace the current opening section with content that:
- Leads with the name **Prism** and the tagline "One spec. Every platform."
- Explains what it generates AND the knowledge layer AND the advisory board concept
- Has a "How the wiki works" section with the team workflow (PO → Designer → Developer)
- Has a "Getting started" section explaining the two-phase initialization:
  Phase 1: `copier copy` to scaffold; Phase 2: `/setup-project` to initialize
- Has a commands reference listing all commands by role
- Preserves the existing "Current Snapshot" / maturity table
- Preserves the existing "Quick Start" section

### 7.2 Root `CLAUDE.md` and root `AGENTS.md`

Both root context files must be updated. The repo's `AGENTS.md` explicitly states:
"Keep shared facts aligned across AGENTS.md, CLAUDE.md, template/AGENTS.md.jinja,
template/CLAUDE.md.jinja, and .cursor/rules/."

Add to root `CLAUDE.md` and add the equivalent section to root `AGENTS.md`:

```markdown
## Two distinct AI context layers

1. **Template repo layer** (this file, .claude/, .agents/) — context for AI working
   on the template itself: adding platforms, fixing Jinja2 templates, updating schemas.

2. **Generated project layer** (template/.claude/, template/.agents/) — context
   templates rendered into generated projects. Changes here affect every generated project.

The knowledge/ directory in template/knowledge/ is the template for the wiki system.
When working on the template, you are authoring the system, not using it. Do not run
wiki commands from a generated project against this repository.
```

Also update root `AGENTS.md` to replace references to `$scaffold-feature` and
`$advisory-review` with a note that those skills are now superseded in generated projects
by the wiki lifecycle. The template-repo skills (`$platform-builder`, `$sync-ai-context`,
`$test-template`) are unaffected — they operate on the template, not on generated projects.

### 7.3 `template/docs/README.md.jinja` (new file — does not exist yet)

`template/docs/` currently has no README or index. Create one. This file is important
because it explains to both humans and AI agents why `docs/` and `knowledge/` are different.

```markdown
# {{ project_name }} — Documentation

## Two documentation layers

**`docs/`** — Human-readable reference documentation.
For humans who need to understand, deploy, or onboard to the project.
Contents: architecture diagrams, deployment guides, API conventions, onboarding.

**`knowledge/`** — AI-facing product context. The living wiki.
For AI coding agents (and humans) who need to know *what to build next*.
Contents: feature specs, platform requirements, API contracts, design decisions,
advisory board reviews. Maintained by the AI on every lifecycle operation.

Do not put feature specs or platform requirements in `docs/`. They belong in `knowledge/wiki/`.
Do not put architecture or deployment guides in `knowledge/`. They belong in `docs/`.
```

---

## 8. Validation approach

This repo runs on Windows. Use `C:\temp\` for test output, not `/tmp/`.

```powershell
# Generate a full test project
copier copy --trust . C:\temp\test-prism-output

# Generate backend + Android only (PowerShell)
copier copy --trust `
  --data 'project_name=TestApp' `
  --data 'platforms=[backend, mobile-android]' `
  . C:\temp\test-prism-mobile
```

### Source repo checks (run against `template/` — not the generated output)

- `template/.agents/skills/scaffold-feature/` does not exist (deleted)
- `template/.agents/skills/board-review/SKILL.md.jinja` exists (renamed from advisory-review)
- `template/.agents/skills/setup-project/SKILL.md.jinja` exists (new)
- `template/.agents/skills/prep-sprint/SKILL.md.jinja` exists (new)
- `template/.agents/skills/feature-status/SKILL.md.jinja` exists (new)
- `template/.agents/skills/lint-wiki/SKILL.md.jinja` exists (new)
- `template/CLAUDE.md.jinja` contains NO references to `docs/features/` or `docs/advisory-board.md`
- `template/AGENTS.md.jinja` contains NO references to `$scaffold-feature` or `docs/advisory-board.md`
- `template/docs/README.md.jinja` exists with the docs/knowledge scope distinction
- `template/.cursor/rules/wiki.mdc.jinja` exists with the wiki-read-before-implement instruction
- `template/.claude/commands/scaffold-feature.md.jinja` does not exist (deleted)
- `template/.claude/commands/document-feature.md.jinja` does not exist (deleted)
- All 14 new command source files exist in `template/.claude/commands/` with `.md.jinja` suffix:
  `setup-project.md.jinja`, `board-review.md.jinja`,
  `po-intake.md.jinja`, `po-clarify.md.jinja`, `po-handoff.md.jinja`,
  `design-intake.md.jinja`, `design-clarify.md.jinja`, `design-handoff.md.jinja`,
  `prep-sprint.md.jinja`, `dev-done.md.jinja`,
  `feature-status.md.jinja`, `ask.md.jinja`, `audit-feature.md.jinja`, `lint-wiki.md.jinja`

### Generated project checks (run against the Copier output in `C:\temp\test-prism-output`)

- `knowledge/` directory exists with correct full structure in all variants
- `intake/pending/` contains `PO_BRIEF_TEMPLATE.md` and `DESIGN_HANDOFF_TEMPLATE.md`
- `intake/processed/` and `intake/quarantined/` exist with `.gitkeep`
- `wiki/personas/`, `wiki/business-rules/`, `wiki/design/` exist
- `wiki/advisory/BOARD.md` exists with the placeholder content
- `CONTEXT.md` renders correctly with the project's platform selections
- Platform identifier values in `CONTEXT.md` and `SCHEMA.md` match `copier.yml` values
- Root `CLAUDE.md` contains NO references to `docs/features/` or `docs/advisory-board.md`;
  setup section uses tool-specific invocation wording (Claude/Codex/Cursor)
- Root `AGENTS.md` contains NO references to `$scaffold-feature` or `docs/advisory-board.md`;
  lifecycle operations use plain names (no `$` prefix)
- Each platform's `CLAUDE.md` contains the updated wiki reference section including
  the advisory-review check
- Each platform's `AGENTS.md` contains the same wiki reference section (Codex parity)
- `.agents/skills/setup-project/SKILL.md` exists
- `.agents/skills/scaffold-feature/` does not exist
- `.cursor/rules/wiki.mdc` exists (rendered from `wiki.mdc.jinja`)
- `docs/README.md` exists with the docs/knowledge scope distinction
- All command files exist in `.claude/commands/`:
  `setup-project.md`, `board-review.md`, `po-intake.md`, `po-clarify.md`, `po-handoff.md`,
  `design-intake.md`, `design-clarify.md`, `design-handoff.md`,
  `prep-sprint.md`, `dev-done.md`,
  `feature-status.md`, `ask.md`, `audit-feature.md`, `lint-wiki.md`
- `SCHEMA.md` includes `advisory-review` field in feature frontmatter
- `SCHEMA.md` includes the pre-dev review four-question format
- `SCHEMA.md` includes the "confirm before committing" operational rule
- `index.md` has the status board format with "Board Review" column

Run the existing validation script:
```bash
./scripts/validate-template.ps1
```

---

## 9. Implementation order

Implement in this order to avoid breaking existing functionality:

1. Read `copier.yml` — note exact platform identifier values. Do this first.
2. Add `template/knowledge/` directory structure with all placeholder files and `.gitkeep`
   files (including `intake/pending/`, `intake/processed/`, `intake/quarantined/`,
   `wiki/advisory/`)
3. Write `template/knowledge/wiki/SCHEMA.md` completely — this is the most important file
   and must be complete before writing command files
4. Write `template/knowledge/wiki/advisory/BOARD.md` with the placeholder content
5. Write `template/knowledge/intake/README.md`
6. Write `template/knowledge/intake/pending/PO_BRIEF_TEMPLATE.md`
7. Write `template/knowledge/intake/pending/DESIGN_HANDOFF_TEMPLATE.md`
8. Write `template/CONTEXT.md.jinja` (use verified platform IDs from step 1)
9. Write the command source files in `template/.claude/commands/` using `.md.jinja` suffix
   (consistent with existing files in that directory). Copier strips `.jinja` on generation:
   - `setup-project.md.jinja` (must exist before any wiki state is initialized)
   - `board-review.md.jinja`
   - `po-intake.md.jinja`, `po-clarify.md.jinja`, `po-handoff.md.jinja`
   - `design-intake.md.jinja`, `design-clarify.md.jinja`, `design-handoff.md.jinja`
   - `prep-sprint.md.jinja`, `dev-done.md.jinja`
   - `feature-status.md.jinja`, `ask.md.jinja`, `audit-feature.md.jinja`, `lint-wiki.md.jinja`
   Remove existing commands that are superseded: `scaffold-feature.md.jinja` and
   `document-feature.md.jinja`. These point at the old `docs/features/` and
   `docs/advisory-board.md` system and must be deleted to avoid two competing
   feature-delivery workflows coexisting in the generated project.
10. Update `template/CLAUDE.md.jinja` and `template/AGENTS.md.jinja` (the root generated
    context templates) — remove `docs/features/`, `docs/advisory-board.md`, and
    `$scaffold-feature` references; add wiki reference section and updated command/skill list.
    This must happen before platform files so the root and platform contexts are consistent.
11. Update each platform's `CLAUDE.md.jinja` and `AGENTS.md.jinja` with the revised wiki
    reference section (includes advisory-review check). All files have `.jinja` suffix —
    search for `AGENTS.md.jinja`, not `AGENTS.md`, inside the `template/` directory.
12. Update `template/.agents/skills/`:
    - **Delete** `scaffold-feature/` directory entirely (retired — see section 5.7)
    - Create `setup-project/SKILL.md.jinja` (new required skill)
    - **Rename** `advisory-review/` to `board-review/` and update its `SKILL.md.jinja`
    - Create `prep-sprint/SKILL.md.jinja`, `feature-status/SKILL.md.jinja`,
      `lint-wiki/SKILL.md.jinja`
    Add `template/.cursor/rules/wiki.mdc.jinja` with the wiki-read-before-implement instruction.
13. Update `copier.yml` — confirm `description` exists (it does, at line 71); remove any
    wiki toggle; do not add `product_domain`
14. Update root `README.md`
15. Update root `CLAUDE.md` with the two-layer context note
16. Update root `AGENTS.md` — add the two-layer context note; note that `$scaffold-feature`
    and `$advisory-review` in generated projects are superseded by the wiki lifecycle
17. Create `template/docs/README.md.jinja` (see section 7.3 — the file does not exist yet)
18. Run validation

---

## 10. What this plan intentionally does not include

The following are out of scope for this initial implementation:

- **`/board-update` command** — a command to revise the advisory board composition after
  initial setup. The board can be edited directly in `BOARD.md`. A dedicated command
  that re-runs parts of the Step 2 interview for board revision is valuable but
  deferred to a future iteration.
- **Board review at pull request time** — a CI workflow that automatically runs a board
  review when a PR modifies platform code for a feature with `advisory-review: pending`.
  Valuable but requires external CI integration.
- **A search CLI over the wiki** — the status board index is sufficient at small scale.
  Build search when the wiki exceeds 50 pages.
- **Automatic wiki updates on git commits** — triggering wiki operations from CI.
- **Multi-agent coordination** — platform AI agents updating the wiki themselves after
  implementing. Requires conflict resolution design.
- **Obsidian or Notion integration** — the markdown structure is Obsidian-compatible but
  no specific config is added at this stage.
- **Automated meeting transcript processing** — `/po-intake` can process transcripts,
  but automated ingestion pipelines (Zoom, Teams exports) are out of scope.
- **Notification routing** — alerting PO/Designer via Slack when they have open questions.

---

## 11. The key insight to preserve in all implementation decisions

The difference between "a docs folder that gets stale" and "a living wiki" is:
- **Who maintains it**: the LLM, not humans
- **When it's updated**: automatically on every lifecycle operation via defined commands
- **How it's consumed**: AI agents and humans read it before implementing
- **How it compounds**: each feature adds to personas, business rules, design patterns,
  architectural decisions, and board-derived knowledge — so feature 11 is built on the
  context of features 1–10

Every implementation decision should preserve this distinction.

---

## 12. Team workflow — how the roles interact daily

### Typical feature lifecycle (end to end)

**Day 1 — PO captures a feature:**
1. PO meets with customer, takes notes
2. PO drops notes into `knowledge/intake/pending/client-meeting-2026-04-06/`
3. PO runs `/po-intake client-meeting-2026-04-06`
4. AI presents interpretation with proposed feature stubs and advisory-review assessment
5. PO confirms or corrects; AI creates feature files and sets advisory-review field
6. PO runs `/po-clarify` to answer any questions flagged for the PO role
7. PO runs `/po-handoff F-009`
   - If advisory-review is pending: AI prompts "Do you want to run /board-review first?"
   - PO runs `/board-review F-009`
   - AI generates domain expert review; board concerns become open questions
   - PO/Designer/Developer read the one-page review together (15 minutes)
   - Team decides whether to proceed, revise the spec, or add acceptance criteria
   - Handoff proceeds to Designer with a spec already validated by domain experts

**Why the board review happens before design, not after:**
The Designer needs to know about domain constraints before creating flows. If a board
review finds that the nutrition score algorithm needs a cultural bias check, the Designer
should design the audit/override flow upfront — not as a retrofit after the main design
is done. Board review before design means the Designer receives a brief already informed
by domain expert concerns.

**Day 2-3 — Designer picks up the feature:**
1. Designer runs `/feature-status` — sees F-009 is `ready-for-design` and board review is done
2. Designer reads the board review summary in the feature file before starting design work
3. Designer creates designs, noting key decisions
4. Designer drops `knowledge/intake/pending/f009-checkout-designs/`
5. Designer runs `/design-intake F-009 f009-checkout-designs`
   - AI checks design against board review findings — flags any unaddressed concerns
6. Designer runs `/design-clarify` to resolve any open design questions
7. Designer runs `/design-handoff F-009`
   - AI checks that board review "Actions required" checklist is addressed
   - Generates platform-requirements pages incorporating both design and board findings
   - F-009 moves to `ready-for-dev`

**Day 3-5 — Developer builds:**
1. Developer runs `/prep-sprint` — features in `ready-for-dev` with board review done
2. Reads platform-requirements (board concerns are embedded, no need to cross-reference)
3. Implements the feature
4. If a technical constraint emerges: `/ask F-009 "..." --to po`
5. When shipped: `/dev-done F-009`
   - If a board review was done: AI asks "Did any board concerns materialize? Were any
     unfounded? Record for calibration."

### Coordination (any role, any time)

- `/feature-status` — the team's shared coordination view; run at standups
- `/lint-wiki` — weekly health check; run before sprint planning
- `/audit-feature` — before a handoff, verify spec matches source documents
- `/ask` — route a question to the right person without a meeting

---

## 13. The advisory board system — complete specification

### 13.1 What the advisory board is

The advisory board is a **product-domain intelligence layer** — a set of 4–6 domain expert
personas defined once per project that review features through lenses the team cannot see
from their own roles.

It is not:
- A governance gate (the team does not need board "approval")
- A generic architecture review (that is what ADRs are for)
- A comprehensive simulation of a real boardroom discussion
- Something that runs on every feature

It is:
- A set of domain experts whose expertise directly addresses the product's specific failure modes
- Consulted for features with domain complexity, behavioral implications, or vulnerable users
- A mechanism for catching the things a small team cannot see because they are not domain specialists
- A tool that produces a one-page review the team reads together in 15 minutes

### 13.2 Why the board is defined during project setup (not at review time)

A board defined at the moment of review is a generic board. A board defined during
setup — through a domain risk interview that asks "what could go wrong and for whom?" —
is a board specific to this product's actual risk profile.

The domain risk interview produces the failure modes. The failure modes determine which
expert perspectives are needed. The board members are chosen to address those specific
failure modes, not to cover all possible domains.

**The four interview questions (and why each matters):**

1. "Who are your primary users, and what do they trust this app to get right?"
   This establishes who the board is protecting. The answer changes the board composition
   significantly. "Parents managing children's meal plans" → pediatric nutrition perspective
   needed. "Restaurant owners tracking costs" → food economics perspective needed.

2. "What is the most important decision or calculation this app makes on behalf of users?"
   This identifies the core domain function. For a recipe app it's nutrition scoring or
   recipe recommendations. For a fintech app it's risk assessment or portfolio allocation.
   The board's primary job is to make sure this function is sound.

3. "What could go wrong if the app gets that wrong? The worst realistic case?"
   This is the failure mode question. The answer is what drives board composition more than
   anything else. "The nutrition score recommends a diet that worsens an eating disorder"
   → behavioral psychologist. "The financial risk score approves a loan the user cannot
   repay" → behavioral economist and risk analyst. This question surfaces the stakes.

4. "Are there user groups who might be especially vulnerable to a mistake?"
   This adds the equity dimension. The dominant case is usually handled by the first three
   questions. This question catches the non-dominant case — the user group whose needs
   are different from the majority and for whom a mistake has greater consequences.

### 13.3 Board member format requirements

Each board member in `BOARD.md` must have:

- **Name and title** — specific and realistic (fictional person, real-sounding institution)
- **Expertise** — 3-5 specific knowledge areas
- **Why on this board** — one sentence connecting their expertise to a specific failure
  mode from the setup interview. This is the most important field. It explains why this
  person is on this product's board, not just why they are a credible expert.
- **Typical questions they ask** — 2-3 questions in their domain language, specific to
  this product. These are the training signal for the AI.

**Why "typical questions" are not optional:**

Generic expertise descriptions produce generic concerns. When `/board-review` runs,
the AI generates each board member's perspective by applying their lens to the feature.
The "typical questions" field defines what that lens actually looks at. Without it,
the AI defaults to generic concerns that could apply to any product. With it, the AI
generates concerns specific to this product's actual risks.

Example comparison:

Without typical questions:
> "Dr. Mitchell notes potential nutrition concerns. Consider health implications."

With typical questions ("Does this scoring method penalize traditionally healthy foods
from non-Western cuisines?"):
> "Dr. Mitchell flags that the scoring algorithm's reliance on Western macro frameworks
> will systematically score traditional Indian and Japanese meals as poor choices.
> A bento box of rice, fish, and pickled vegetables may score poorly despite being a
> nutritionally balanced meal by global standards. Recommend: localization test set
> covering 10+ cuisine types before shipping."

### 13.4 Board size recommendation

For small teams (2-5 people): 4-6 board members.

More than 6 produces review output too long to read in 15 minutes. The team will stop
reading it. Fewer than 4 likely misses important domain perspectives.

Choose members by: which failure modes are most likely to cause real-world harm or
significantly slow development if discovered late. Those are the perspectives that need
to be on the board. Other perspectives can be added later if a review discovers a gap.

### 13.5 When to run a board review

**Run /board-review for features that have ANY of:**
- Domain-specific calculations or scores (nutrition, financial risk, learning difficulty,
  safety classification, recommendation algorithms)
- Behavioral or psychological implications (gamification, streaks, social comparison,
  achievement systems, behavioral nudges)
- Sensitive or vulnerable user groups (health conditions, financial stress, learning
  differences, dietary restrictions, minors, elderly users)
- Cultural assumptions that may not generalize (food from non-Western cuisines, currency
  assumptions, language that assumes particular cultural norms)
- Real-world consequences outside the app (health outcomes, financial decisions, legal
  compliance, safety)
- Core differentiating features (the things the product is primarily known for)

**Do not run /board-review for:**
- Authentication flows (login, logout, password reset, 2FA)
- Settings and preference screens
- Basic CRUD operations (create/edit/delete records with no domain logic)
- Notification preference management
- Infrastructure and deployment changes
- Internal admin tools with no end-user impact
- UI polish and purely visual improvements

When in doubt: run it. The cost is one conversation. The cost of discovering a domain
failure in production is substantially higher.

### 13.6 The board as a trust-building mechanism

The board only has credibility if the team helped define it. An AI-generated board that
the team never reviewed will have its concerns dismissed — "the AI made this person up,
so the concern is probably not real."

This is why `/setup-project` Step 3 requires explicit confirmation of each board member
before writing `BOARD.md`. The team must own the board composition. When Dr. Mitchell
raises a concern in a review, the team should remember that they agreed she belongs
on the board because of exactly this kind of concern.

### 13.7 The board evolves over time

The board generated on day one is a starting point. The team will not have thought
through all their domain risks on day one. After 3-4 features are introduced, the team
will have a clearer picture of what domain complexity actually looks like in their product.

`BOARD.md` should be reviewed and updated:
- After the first sprint (are the concerns raised so far what you expected?)
- When a new product domain is entered (a recipe app adding a fitness tracking feature
  may need an exercise physiology perspective)
- When a board review missed something important that caused a real problem

Editing `BOARD.md` directly is the supported path for now. A `/board-update` command
that re-runs the setup interview for board revision is future work.

---

## 14. Two-phase project initialization

Every generated project requires two steps before first use:

**Phase 1 — Copier scaffolding (existing, unchanged):**
```bash
copier copy --trust . /path/to/new-project
```
This produces the file structure, platform code, and wiki skeleton. After this step,
the wiki exists but has no state — `BOARD.md` has placeholder content, `index.md` is
empty, `log.md` has only an init entry.

**Phase 2 — Project setup (new, required):**

Open the project in your AI agent and run the setup command:
- **Claude Code:** `/setup-project`
- **Codex:** `$setup-project`
- **Cursor:** ask the agent: "run setup-project"

This runs the four-step interactive initialization:
1. Confirms project identity from the Copier output
2. Conducts the domain risk interview (four questions, conversational)
3. Proposes and confirms the advisory board composition
4. Creates the initial wiki state (BOARD.md, initial business rules, initial personas)

After Phase 2, the project is ready for first use of the intake commands.

**Why Phase 2 cannot be part of Phase 1 (the Copier questionnaire):**
The domain risk interview is conversational. Each answer informs the next question.
The board composition requires seeing the interview answers before proposing members.
Copier is a form-filling tool, not a conversational agent. The interview cannot be
expressed as a YAML questionnaire without losing most of its value.

Additionally, the team running `/setup-project` is ideally PO + Designer + Developer
together — they discuss the domain risks and board composition as a group. Copier is
typically run by one person (the developer setting up the project). The setup step
benefits from multi-role input.

**What to document in README.md about this:**
The project README should include a clear "Getting started" section that says:

```
1. Generate the project: copier copy --trust . /your-project
2. Initialize the wiki: open the project in your AI agent and run the setup command:
   - Claude Code: /setup-project
   - Codex: $setup-project
   - Cursor: ask the agent to "run setup-project"
   This takes 15-20 minutes and sets up the advisory board.
3. Start building: run po-intake when you have the first feature.
```

---

## 15. Critical implementation rules for the coding agent

These rules must be followed precisely. Each has caused real problems in AI-maintained
knowledge systems and is not theoretical.

### Rule 1: Confirm before committing (intake commands)

Every intake command (`/po-intake`, `/design-intake`, `/setup-project` Step 3) must show
the user a plain-language summary of what it intends to create or modify and wait for
explicit confirmation before writing any files.

```
AI: "Here is what I found:
  - New feature: 'Checkout with saved address' (F-009) — advisory-review: pending
  - Update to existing: F-003 acceptance criteria item 2 will change
  - New business rule: orders under €5 cannot use installment payment
  - Open questions: 2 for PO, 1 for Designer
  Shall I proceed?"
User: confirms or corrects
AI: [writes files]
```

### Rule 2: Never silently overwrite on conflict

If new intake content contradicts existing wiki content, move to `intake/quarantined/`
with a `CONFLICT.md` explaining: what the new input claims, what the existing wiki says,
which files are involved, what decision the human needs to make.

### Rule 3: Platform identifiers must match copier.yml exactly

Read `copier.yml` before writing any Jinja2 template. A conditional like
`{% if 'android' in platforms %}` silently produces empty output if the actual value is
`mobile-android`. There is no error — the wrong output is a valid Jinja2 render.

### Rule 4: _FORMAT.md is not _TEMPLATE.md

Files serving as format guides inside the wiki are named `_FORMAT.md`. Do not name them
`_TEMPLATE.md`. Copier uses the concept of "templates" and the naming collision confuses
what gets rendered and what is a reference file.

### Rule 5: The intake pipeline has two outcomes, not three

When an intake command completes, the intake folder moves to exactly one of:
- `intake/processed/[name]/` — successful, clean processing
- `intake/quarantined/[name]/` — conflicting content requiring human resolution

There is no partial state. If a multi-document intake folder has one clean document and
one conflicting document, move the entire folder to quarantine. The human resolves the
conflict, then re-runs the intake command.

### Rule 6: index.md is a status board, not a catalogue

`index.md` must be in status board format (grouped by lifecycle stage) with a Board Review
column. It is the team's coordination artifact. A flat alphabetical list defeats its purpose.

### Rule 7: BOARD.md is written once and confirmed by the team

`BOARD.md` is not generated silently. `/setup-project` Step 3 shows the proposed board
composition to the team and waits for explicit confirmation before writing the file.
The board only has credibility if the team helped define it. Never write `BOARD.md`
without team confirmation.

### Rule 8: Board reviews happen before design, not after

The advisory-review gate in `/po-handoff` exists for a reason. Board review before design
means the Designer receives a brief already informed by domain concerns. Board review
after design means potentially days of design work that must be revised. The handoff
commands are designed to prompt the board review at the right moment — do not skip this.

### Rule 9: Board review output feeds back into the wiki

A board review that produces a file and nothing else was not worth running. Every action
item from a board review must become an open question on the feature file, assigned to the
appropriate owner. Every new business rule implied by a board review must be proposed for
`business-rules/` with the source attributed to the review. The review compounds the wiki.

### Rule 10: The advisory board is not a governance authority

The review output informs the team's decision. The team decides what to do with it.
Do not frame board review output as approvals, rejections, or requirements unless the
team explicitly elevates them to that status. The board raises concerns. The team acts.

---

*End of implementation plan. Hand this document to the coding agent along with access
to the repository. The agent should read this document entirely before making any changes,
and should execute the implementation steps in the order specified in section 9.*
