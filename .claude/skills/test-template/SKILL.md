---
name: test-template
description: Test the Copier template by generating a project with all platforms enabled and verifying the output.
disable-model-invocation: true
---

# Test Template

Test the Copier template by generating a project and verifying the output.

## Steps

1. Run template generation through the CLI to a temp directory, with an app list that has every stack (an answers file):
   ```bash
   prism new --answers /tmp/all-apps.yml --dest /tmp/template-test-output --yes
   ```
   where `all-apps.yml` is `schema_version: 1`, `answers: {project_name: Test App, apps: [{id: backend, stack: spring-backend}, {id: web, stack: nextjs-web}, {id: admin, stack: nextjs-web, audience: internal}, {id: mobile-android, stack: android-compose}, {id: mobile-ios, stack: ios-swiftui}]}`.

2. Verify the output structure:
   - Check all app directories exist: `backend/` (from the pack, with its own `.copier-answers.yml`), `web/` and `admin/` (from the `nextjs-web` pack, each with its own `.copier-answers.yml`), `mobile-android/`, `mobile-ios/`
   - Check `CLAUDE.md`, `AGENTS.md`, `Taskfile.yml` were generated without Jinja artifacts
   - Check `.claude/`, `.agents/skills/`, and `.cursor/` are present
   - Check `docs/`, `shared/`, `.github/workflows/` are present

3. Scan for common template issues:
   - Search for leftover `{{` or `{%` in non-`.jinja` output files (indicates broken rendering)
   - Search for `<%= %>` or EJS tags that should have been escaped
   - Check that platform-conditional content is correctly included/excluded

4. Test with a subset of apps:
   ```bash
   prism new --preset backend-only --project-name "Backend Only" --dest /tmp/template-test-backend --yes
   ```
   - Verify excluded app directories are absent
   - Verify CLAUDE.md doesn't reference excluded platforms

5. Run the contract validation, which checks rendered files and workflows (it needs actionlint on PATH or `-ActionlintPath`):
   ```bash
   ./scripts/validate-template.ps1 -Mode contract
   ```

6. Report results: list any issues found or confirm all checks passed.

7. Clean up temp directories.
