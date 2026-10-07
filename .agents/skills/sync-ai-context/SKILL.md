---
name: sync-ai-context
description: "Audit the parts of the AI context that have no automatic check: the Cursor stack facts against the platform guidance, and this repository's own skill pair and CLAUDE.md and AGENTS.md. Use after editing a Cursor rule, the root guidance or a repository skill."
---

# Sync AI Context

Generated workspaces keep one source of agent rules and one source of skills, and four checks cover them:

- `python scripts/build-skill-layers.py --check`: every Codex skill, Claude command, Claude skill and Cursor rule under `template/` matches its source in `template-skills/`.
- `python -B -m unittest tests.test_skill_layers`: each tool discovers the rendered skills.
- `python -B -m unittest tests.test_instruction_files`: `AGENTS.md` is the only source of rules, every `CLAUDE.md` only imports it, and no Cursor rule repeats it.
- `python scripts/build-workflow-assets.py --check`: the packaged workflow asset matches its sources.

Two things have no automatic check and need a manual one.

## Steps

1. Run the four checks. Fix what they report in `template-skills/` or in the `AGENTS.md.jinja` that owns the rule, never in a generated layer file, then run the generators again.
2. Check the Cursor stack facts in `template-skills/cursor-*/skill.md`:
   - The Cursor rule of each pack, `packs/<stack>/.cursor/rules/{{ app_id }}.mdc.jinja`, still matches the pack's `AGENTS.md.jinja` and docs.
   - `cursor-api-conventions` matches `template/docs/api/conventions.md.jinja`.
3. Check the root layer of this repository:
   - `.claude/skills/` against `.agents/skills/` (three skills, kept by hand).
   - `CLAUDE.md` against `AGENTS.md`: the same template facts, with tool-specific syntax kept.
4. Report each mismatch and fix it.

## Output

- A concise list of mismatches found
- The files updated to restore alignment
- Any intentional differences that should remain tool-specific
