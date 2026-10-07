---
name: test-template
description: Generate a temporary sample project from this Copier template and verify rendered structure, AI context files, skill directories, and common templating mistakes. Use after changing template files, docs, tasks, workflows, or AI context.
---

# Test Template

Use this skill to validate that template changes still render a coherent generated project.

## Workflow

1. Pick a temporary output directory outside the repository.
2. Run a broad generation check through the CLI, for example:
   - `prism new --preset backend-web --project-name "Test App" --dest <tempdir> --yes`
   - an answers file that lists every stack, for the full set of apps
   - an answers file with a `backend` and an `agent-service` (stack `python-agent-service`), then `uv sync --locked`, ruff, mypy, pytest and `python -m evals.run --provider fake` in the generated agent app
3. Verify the rendered output contains the expected root artifacts:
   - `AGENTS.md`
   - `CLAUDE.md`
   - `Taskfile.yml`
   - `.agents/skills/`
   - `.claude/`
   - `.cursor/`
   - `docs/`
   - `shared/`
4. Search for leftover `{{` or `{%` in rendered non-template files.
5. If the change touched stack or app gating, generate at least one focused subset variant as well (for example `prism new --preset backend-only`).
6. Run `./scripts/validate-template.ps1 -Mode contract`, which checks rendered files and workflows (it needs actionlint on PATH or `-ActionlintPath`).
7. Summarize what was validated and any failures found.
8. Clean up temporary output unless the user wants to inspect it.

## Output

- The generation variants tested
- Structural or rendering issues found
- Any follow-up validation still recommended
