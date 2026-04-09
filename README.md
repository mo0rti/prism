# Prism: One spec. Every platform.

![Prism](docs/media/prism.png)

A production-grade, AI-ready multi-platform system generator with a living product wiki.
Turn an idea into a fully scaffolded monorepo, then keep every platform's AI agent in sync
as your product evolves.

A [Copier](https://copier.readthedocs.io/) template for scaffolding a multi-platform monorepo with:

- **Backend**: Spring Boot 4 (Kotlin 2.2+, Java 21)
- **User Web App**: Next.js + TypeScript
- **Admin Web Portal**: Next.js + TypeScript
- **Android**: Kotlin + Jetpack Compose (MVVM)
- **iOS**: Swift + SwiftUI (MVVM)

Every generated project includes a **living product wiki** at `knowledge/wiki/` that the AI
maintains automatically. PO notes become feature specs. Design artifacts become platform
requirements. Every platform's AI agent reads from the same source of truth before implementing.

This repository is the template itself, not a generated project.

## How the wiki works

The wiki solves the context broadcasting problem: when building a multi-platform product
with AI-assisted development, each AI agent only knows what you manually told it. The wiki
is the coordination layer that fixes this.

**Three roles, one wiki:**

1. **Product Owner** drops raw notes into `knowledge/intake/pending/` and runs `po-intake`.
   The AI structures them into feature specs with acceptance criteria, open questions, and
   an advisory-review assessment. Nothing is invented. The AI flags gaps as open questions.

2. **Designer** attaches design artifacts with `design-intake`. The AI maps design decisions
   to the feature spec and generates platform-specific requirements for each platform at handoff.

3. **Developer** reads `knowledge/wiki/platform-requirements/[F-XXX]-[platform].md` before
   implementing. All context (spec, design decisions, board review findings) is already there.

**The advisory board:**

Every project has a domain expert panel defined during setup via `/setup-project`. The panel
is a set of 4 to 6 fictional domain experts chosen specifically for this product's risk profile.
For a health app: a clinical dietitian, a behavioral psychologist, a food scientist. For a
fintech app: a risk analyst, a behavioral economist, a compliance expert.

Run `/board-review F-XXX` and each board member reviews the feature through their domain lens.
The output is a one-page review the team reads together in 15 minutes.

## Getting started

**Phase 1: Scaffold the project**

```bash
copier copy --trust . ../my-new-project
```

**Phase 2: Initialize the wiki (run once in the generated project)**

- **Claude Code:** `/setup-project`
- **Codex:** `$setup-project`
- **Cursor:** ask the agent to "run setup-project"

Phase 2 takes 15 to 20 minutes. It interviews you about your domain, proposes an advisory
board tailored to your product's risk profile, and initializes the wiki state.

## Commands reference

Claude Code slash commands (`/cmd`), Codex skills (`$cmd`), and Cursor (ask by name) all invoke the same operations.

| Role | Claude Code | Codex | Purpose |
|------|-------------|-------|---------|
| All | `/setup-project` | `$setup-project` | One-time project initialization |
| PO | `/po-intake [folder]` | `$po-intake [folder]` | Process raw notes into feature specs |
| PO | `/po-clarify` | `$po-clarify` | Answer open questions assigned to PO |
| PO | `/po-handoff [F-XXX]` | `$po-handoff [F-XXX]` | Hand off a feature to design |
| Designer | `/design-intake [F-XXX] [folder]` | `$design-intake [F-XXX] [folder]` | Attach design artifacts |
| Designer | `/design-clarify` | `$design-clarify` | Answer open design questions |
| Designer | `/design-handoff [F-XXX]` | `$design-handoff [F-XXX]` | Hand off a feature to dev |
| Dev | `/prep-sprint` | `$prep-sprint` | Show what is ready to build |
| Dev | `/dev-done [F-XXX]` | `$dev-done [F-XXX]` | Mark a feature as shipped |
| Board | `/board-review [F-XXX]` | `$board-review [F-XXX]` | Domain expert feature review |
| Shared | `/feature-status` | `$feature-status` | Full pipeline view |
| Shared | `/lint-wiki` | `$lint-wiki` | Health-check the knowledge base |
| Shared | `/ask [F-XXX] "q" --to po\|designer\|dev` | `$ask [F-XXX] "q" --to po\|designer\|dev` | Route a question |
| Shared | `/audit-feature [F-XXX]` | `$audit-feature [F-XXX]` | Cross-check spec vs. source intake |

## Current status

- Backend, Android, and iOS are the stronger paths today.
- User web app and admin web portal generate real slices and pass `npm install`, `npm run lint`, `npm run typecheck`, `npm run build`, `npm run build:cloudflare`, and `wrangler deploy --dry-run`, but still need live Cloudflare deployment validation.
- Apple Sign-In remains experimental.
- The safest workflow is explicit sample generation plus `./scripts/validate-template.ps1`.

## Quick start

1. Install `copier`.
2. Review the questionnaire and maturity notes in [docs/questionnaire.md](docs/questionnaire.md).
3. Generate a focused sample:

```bash
copier copy --trust . ../my-new-project
```

4. If you are maintaining the template, run `./scripts/validate-template.ps1` after changes.
5. Validate any generated project locally before treating it as production-ready.

## Docs

**Template and tooling:**

| Document | Purpose |
|----------|---------|
| [docs/current-status.md](docs/current-status.md) | Maturity, validated paths, and recommended evaluation paths |
| [docs/getting-started.md](docs/getting-started.md) | Prerequisites, generation commands, and first validation steps |
| [docs/questionnaire.md](docs/questionnaire.md) | Copier inputs, defaults, and option-specific notes |
| [docs/generated-projects.md](docs/generated-projects.md) | What generated repositories include |
| [docs/maintainer-workflow.md](docs/maintainer-workflow.md) | Template structure and maintainer workflow |

**Prism model and workflow:**

| Document | Purpose |
|----------|---------|
| [docs/prism-model.md](docs/prism-model.md) | What Prism is, the problems it solves, and the generated-project workflow model |
| [docs/wiki-workflow.md](docs/wiki-workflow.md) | How the product wiki works and how the read/query layer behaves |
| [docs/ai-surfaces.md](docs/ai-surfaces.md) | How Claude and Codex surfaces are packaged and which differences are intentional |
| [docs/wiki-validation.md](docs/wiki-validation.md) | How the wiki layer was validated and what confidence applies today |

## Related files

- [AGENTS.md](AGENTS.md) for Codex maintainer guidance in this repo
- [CLAUDE.md](CLAUDE.md) for Claude maintainer guidance in this repo
- [docs/README.md](docs/README.md) for the full docs index
