Add or extend a platform template (web, admin, backend, android, or ios).

Ask me which platform to work on if I haven't specified it.

## Steps

1. **Check current state** - Read `PLAN.md` Build Progress section to see which platforms are done vs pending.

2. **Read the plan** - Read the relevant Phase 3 section in `PLAN.md` for the target platform's full specification (directory structure, files to create, patterns).

3. **Study existing platforms** - Look at a completed platform template (e.g., `template/backend/` or `template/android/`) to match patterns:
   - How Jinja conditionals are used
   - How `copier.yml` variables are referenced
   - File naming conventions (`.jinja` suffix)
   - Platform-specific CLAUDE.md.jinja and AGENTS.md.jinja structure

4. **Implement the platform** - Create all template files under `template/{platform}/` following the PLAN.md spec. Ensure:
   - All files with Jinja expressions have `.jinja` suffix
   - Package path uses `{{package_path}}` for Kotlin/Java
   - Platform guards use `{% if "platform" in platforms %}`
   - EJS tags in Hygen templates are escaped: `{{ '<%' }}`

5. **Update supporting files**:
   - `template/Taskfile.yml.jinja` - add platform tasks
   - `template/CLAUDE.md.jinja` - add platform to architecture map and commands table
   - `template/AGENTS.md.jinja` - mirror CLAUDE.md changes
   - `template/.cursor/rules/` - add platform-specific rule if needed
   - `template/.github/workflows/` - add CI/CD workflow

6. **Update progress** - Update the Build Progress table in `PLAN.md`.

7. **Test** - Run `/test-template` to verify generation works.
