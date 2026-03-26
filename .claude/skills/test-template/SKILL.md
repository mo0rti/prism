---
name: test-template
description: Test the Copier template by generating a project with all platforms enabled and verifying the output.
disable-model-invocation: true
---

# Test Template

Test the Copier template by generating a project and verifying the output.

## Steps

1. Run template generation to a temp directory:
   ```bash
   copier copy --trust --defaults --data 'project_name=Test App' . /tmp/template-test-output
   ```

2. Verify the output structure:
   - Check all platform directories exist: `backend/`, `web-user-app/`, `web-admin-portal/`, `mobile-android/`, `mobile-ios/`
   - Check `CLAUDE.md`, `AGENTS.md`, `Taskfile.yml` were generated without Jinja artifacts
   - Check `.claude/`, `.codex/`, `.cursor/` directories are present
   - Check `docs/`, `shared/`, `.github/workflows/` are present

3. Scan for common template issues:
   - Search for leftover `{{` or `{%` in non-`.jinja` output files (indicates broken rendering)
   - Search for `<%= %>` or EJS tags that should have been escaped
   - Check that platform-conditional content is correctly included/excluded

4. Test with a subset of platforms:
   ```bash
   copier copy --trust --defaults --data 'project_name=Backend Only' --data 'platforms=[backend]' . /tmp/template-test-backend
   ```
   - Verify excluded platform directories are absent
   - Verify CLAUDE.md doesn't reference excluded platforms

5. Report results: list any issues found or confirm all checks passed.

6. Clean up temp directories.
