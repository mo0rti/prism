---
name: template-validator
description: Validate Jinja2 template files for common issues — broken syntax, unescaped EJS, missing conditionals, incorrect variable references. Triggers when editing .jinja files.
---

# Template Validator

When template files (`.jinja`) are created or modified, validate them for correctness.

## Checks to Perform

### Jinja2 Syntax
- All `{{` have matching `}}`
- All `{% if %}` have matching `{% endif %}`
- All `{% for %}` have matching `{% endfor %}`
- Variable names match those defined in `copier.yml`: `project_name`, `project_slug`, `package_identifier`, `description`, `platforms`, `auth_methods`, `database`, `use_docker`, `github_org`
- `cloud_provider` and `web_hosting` are hardcoded (azure and cloudflare) — no conditionals needed for these

### Platform Conditionals
- Platform checks use correct syntax: `{% if "backend" in platforms %}` (not `{% if backend %}`)
- Directory-level exclusion is handled via `_exclude` in `copier.yml`, not per-file guards
- Content inside platform conditionals references the correct platform's code/patterns

### EJS Escaping (Hygen templates)
- Files in `_templates/` that use both Jinja and EJS must escape EJS tags
- `<%= %>` becomes `{{ '<%=' }} %}` inside Jinja context
- `<%` becomes `{{ '<%' }}`

### String Quoting
- Jinja filters inside EJS template strings use single quotes: `{{ var | replace(' ', '-') }}`
- Not double quotes which would break the EJS string delimiters

### Package Path
- Kotlin/Java files use `{{package_path}}` in directory names (forward slashes, derived from package_identifier)
- Swift files don't use package_path

## When to Trigger

- User creates or edits any `.jinja` file
- User asks to validate templates
- Before running template generation tests
