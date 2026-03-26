---
name: sync-ai-context
description: Audit and repair drift between Claude, Codex, and Cursor context files in this template repo and its generated-project templates. Use when AGENTS.md, CLAUDE.md, Cursor rules, or project skills have diverged.
---

# Sync AI Context

Use this skill when shared repository facts or workflows have drifted across the different AI-tool layers.

## Workflow

1. Compare the root repo guidance:
   - `CLAUDE.md`
   - `AGENTS.md`
2. Compare the generated-project guidance:
   - `template/CLAUDE.md.jinja`
   - `template/AGENTS.md.jinja`
   - `template/.cursor/rules/project.mdc.jinja`
3. Compare root skill coverage:
   - `.claude/skills/`
   - `.agents/skills/`
4. Compare generated-project skill coverage:
   - `template/.claude/skills/`
   - `template/.agents/skills/`
5. Align commands, paths, maturity language, doc references, and workflow expectations without forcing identical tool-specific syntax.
6. Report or fix any drift, and call out intentional differences explicitly.

## Output

- A concise list of mismatches found
- The files updated to restore alignment
- Any intentional differences that should remain tool-specific
