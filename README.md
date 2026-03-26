# Multi-Platform Project Template

A [Copier](https://copier.readthedocs.io/) template for scaffolding a multi-platform monorepo with:

- **Backend**: Spring Boot 4 (Kotlin 2.2+, Java 21)
- **User Web App**: Next.js + TypeScript
- **Admin Web Portal**: Next.js + TypeScript
- **Android**: Kotlin + Jetpack Compose (MVVM)
- **iOS**: Swift + SwiftUI (MVVM)

This repository is the template itself, not a generated project.

## Current Snapshot

- Backend, Android, and iOS are the stronger paths today.
- User web app and admin web portal now generate initial slices, but they still need broader end-to-end validation.
- Apple Sign-In remains experimental.
- The safest workflow is still explicit sample generation plus structural validation.

## Quick Start

1. Install `copier`.
2. Review the current questionnaire and maturity notes in [docs/questionnaire.md](docs/questionnaire.md).
3. Generate a focused sample variant:

```bash
copier copy --trust . ../my-new-project
```

4. Validate the generated structure before treating it as production-ready.

## Docs Map

| Document | Purpose |
|----------|---------|
| [docs/README.md](docs/README.md) | Root docs index |
| [docs/current-status.md](docs/current-status.md) | Maturity, validated paths, and recommended evaluation paths |
| [docs/getting-started.md](docs/getting-started.md) | Prerequisites, generation commands, and first validation steps |
| [docs/questionnaire.md](docs/questionnaire.md) | Copier inputs, defaults, and option-specific notes |
| [docs/generated-projects.md](docs/generated-projects.md) | What generated repositories include |
| [docs/maintainer-workflow.md](docs/maintainer-workflow.md) | Template structure and maintainer workflow |

## Related Files

- [AGENTS.md](AGENTS.md) for Codex maintainer guidance in this repo
- [CLAUDE.md](CLAUDE.md) for Claude maintainer guidance in this repo
- [PLAN.md](PLAN.md) for architecture and intended direction

## Short Version

Use this repository to generate and validate targeted sample repos.

Treat **backend + Android** as the most practical evaluation path today. Treat the web slices as real but still under active hardening, and validate any path you plan to rely on locally.
