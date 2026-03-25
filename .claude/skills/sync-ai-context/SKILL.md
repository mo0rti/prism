---
name: sync-ai-context
description: Verify that AI context files (CLAUDE.md, AGENTS.md, Cursor rules) are consistent across all platforms.
disable-model-invocation: true
---

# Sync AI Context

Verify that AI context files are consistent across all platforms.

## Steps

1. Read these files and compare their content:
   - `template/CLAUDE.md.jinja` - Claude Code context
   - `template/AGENTS.md.jinja` - Codex/Cursor context
   - `template/.cursor/rules/project.mdc.jinja` - Cursor global rules

2. Check for drift:
   - Architecture descriptions should match across all three
   - Command/task tables should list the same commands
   - Platform lists should be consistent
   - Convention descriptions should align

3. Check platform-specific files are in sync:
   - `template/backend/CLAUDE.md.jinja` vs `template/backend/AGENTS.md.jinja` vs `template/.cursor/rules/backend.mdc.jinja`
   - Same for android, ios, web, admin

4. Check that skills cover the same capabilities:
   - `template/.claude/skills/` vs `template/.codex/skills/`

5. Report any inconsistencies found and offer to fix them.
