---
name: sync-ai-context
description: Audit that the generated-project instruction layout holds. AGENTS.md is the only source of rules, every CLAUDE.md only imports it, and the Cursor scoped rules and the dual-surface skills still agree. Use after editing AGENTS.md, CLAUDE.md, Cursor rules or project skills.
---

# Sync AI Context

Generated workspaces keep one source of agent rules. `AGENTS.md` holds the rules; each `CLAUDE.md` imports the `AGENTS.md` beside it with `@AGENTS.md`; Codex and Cursor read `AGENTS.md` directly. Three things cannot import and still need a manual check.

## Workflow

1. Check the import layout:
   - `template/CLAUDE.md.jinja` is only `@AGENTS.md`.
   - Each `template/<platform>/CLAUDE.md.jinja` starts with `@AGENTS.md` and adds only Claude Code skills and commands that no other tool shares.
   - No rule appears in both a `CLAUDE.md.jinja` and the `AGENTS.md.jinja` beside it, and no platform file restates a rule of `template/AGENTS.md.jinja`.
   - `template/CONTEXT.md.jinja` does not exist and nothing names `CONTEXT.md`.
2. Check the Cursor rules in `template/.cursor/rules/`. Cursor rule files cannot import an instruction file:
   - `project.mdc.jinja` is the one always-on rule and only references `@AGENTS.md`.
   - `backend.mdc.jinja`, `web.mdc.jinja`, `mobile-android.mdc.jinja` and `mobile-ios.mdc.jinja` carry stack facts scoped by `globs`. Each fact still matches `template/<platform>/AGENTS.md.jinja` and the platform docs.
   - `api-conventions.mdc.jinja` matches `template/docs/api/conventions.md.jinja`, and `advisory-review.mdc.jinja` matches the `board-review` skill.
3. Check the two skill packagings, which cannot import each other:
   - `.claude/skills/` against `.agents/skills/` in this repository.
   - `template/.claude/commands/` and `template/.claude/skills/` against `template/.agents/skills/`.
4. Check the root layer of this repository: `CLAUDE.md` and `AGENTS.md` describe the same template facts, with tool-specific syntax kept.
5. Report each mismatch and fix it. Run `python scripts/build-workflow-assets.py --check` after a change to a packaged skill or to the connected-workflow section of `template/AGENTS.md.jinja`.

## Output

- A concise list of mismatches found
- The files updated to restore alignment
- Any intentional differences that should remain tool-specific
