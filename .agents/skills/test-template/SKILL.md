---
name: test-template
description: Generate a temporary sample project from this Copier template and verify rendered structure, AI context files, skill directories, and common templating mistakes. Use after changing template files, docs, tasks, workflows, or AI context.
---

# Test Template

Use this skill to validate that template changes still render a coherent generated project.

## Workflow

1. Pick a temporary output directory outside the repository.
2. Run a broad generation check, for example:
   - `copier copy --trust --defaults --data "project_name=Test App" . <tempdir>`
3. Verify the rendered output contains the expected root artifacts:
   - `AGENTS.md`
   - `CLAUDE.md`
   - `Taskfile.yml`
   - `.agents/skills/`
   - `.claude/`
   - `.cursor/`
   - `docs/`
   - `shared/`
4. Search for leftover `{{`, `{%`, or unescaped EJS markers in rendered non-template files.
5. If the change touched platform gating, generate at least one focused subset variant as well.
6. Summarize what was validated and any failures found.
7. Clean up temporary output unless the user wants to inspect it.

## Output

- The generation variants tested
- Structural or rendering issues found
- Any follow-up validation still recommended
