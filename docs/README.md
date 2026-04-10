# Documentation Index

This folder holds repository-level documentation for the template itself and for the Prism
workflow embedded in generated projects.

If you are not sure where to start, pick the path that matches your goal.

## Start Here By Role

### I want to generate a project and explore it

Read these first:

1. [getting-started.md](getting-started.md)
2. [questionnaire.md](questionnaire.md)
3. [generated-projects.md](generated-projects.md)

Then continue with:

4. [prism-model.md](prism-model.md)
5. [wiki-workflow.md](wiki-workflow.md)

### I am a PO, designer, or developer using Prism in a generated project

Read these first:

1. [generated-projects.md](generated-projects.md)
2. [prism-model.md](prism-model.md)
3. [wiki-workflow.md](wiki-workflow.md)

Use these when you need deeper confidence or implementation context:

4. [ai-surfaces.md](ai-surfaces.md)
5. [wiki-validation.md](wiki-validation.md)

### I am maintaining the template repo

Read these first:

1. [maintainer-workflow.md](maintainer-workflow.md)
2. [current-status.md](current-status.md)
3. [questionnaire.md](questionnaire.md)
4. [generated-projects.md](generated-projects.md)

## Core Journey Docs

These are the best pages for understanding what Prism is and how to use it step by step.

| Document | Best for | Purpose |
|----------|----------|---------|
| [getting-started.md](getting-started.md) | Builders | Prerequisites, generation commands, sample variants, and first validation steps |
| [generated-projects.md](generated-projects.md) | Builders and users | What generated repositories include, how commands are surfaced, and what is safe to run first |
| [prism-model.md](prism-model.md) | PO, design, dev, and evaluators | What Prism is, the problems it solves, and the generated-project workflow model |
| [wiki-workflow.md](wiki-workflow.md) | PO, design, dev | How the wiki works, what `WIKI_REPORT.md` and `SETTINGS.md` do, and how the read/query layer behaves |

## Supporting Reference Docs

These are the main supporting pages once you already understand the core flow.

| Document | Best for | Purpose |
|----------|----------|---------|
| [questionnaire.md](questionnaire.md) | Builders and maintainers | Copier questionnaire inputs, defaults, and option-specific maturity notes |
| [ai-surfaces.md](ai-surfaces.md) | Users choosing between Claude and Codex | How Claude and Codex surfaces are packaged and which differences are intentional |
| [wiki-validation.md](wiki-validation.md) | Evaluators and maintainers | How the wiki usability layer was validated and what confidence boundaries apply today |
| [current-status.md](current-status.md) | Maintainers and evaluators | Current maturity, validated paths, and recommended evaluation paths |

## Maintainer Docs

These pages are mainly about the template repository itself rather than day-to-day use in a
generated project.

| Document | Purpose |
|----------|---------|
| [maintainer-workflow.md](maintainer-workflow.md) | Template structure, maintainer workflow, and recommended validation variants |
| [current-status.md](current-status.md) | Maturity, validation coverage, and current safest evaluation paths |

## Related Root Files

- [`README.md`](../README.md) for the short repository overview and fastest entry path
- [`AGENTS.md`](../AGENTS.md) for Codex maintainer guidance in this repo
- [`CLAUDE.md`](../CLAUDE.md) for Claude maintainer guidance in this repo
