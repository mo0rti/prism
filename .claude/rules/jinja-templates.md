---
description: Jinja2 template validation rules for .jinja files in the template/ directory
paths:
  - "template/**/*.jinja"
  - "copier.yml"
---

# Jinja2 Template Rules

When creating or editing `.jinja` files, validate for these common issues:

## Jinja2 Syntax
- All `{{` have matching `}}`
- All `{% if %}` have matching `{% endif %}`
- All `{% for %}` have matching `{% endfor %}`
- Variables match those in `copier.yml`: `project_name`, `project_slug`, `package_identifier`, `description`, `platforms`, `auth_methods`, `database`, `use_docker`, `github_org`
- `cloud_provider` (azure) and `web_hosting` (cloudflare) are hardcoded with `when: false` - no conditionals needed

## Platform Conditionals
- Use `{% if "backend" in platforms %}` (not `{% if backend %}`)
- Directory-level exclusion uses `_exclude` in `copier.yml`, not per-file guards

## EJS Escaping (Hygen templates in `_templates/`)
- `<%= %>` becomes `{{ '<%=' }} %}` inside Jinja context
- `<%` becomes `{{ '<%' }}`

## String Quoting
- Jinja filters inside EJS template strings use single quotes: `{{ var | replace(' ', '-') }}`
- Double quotes would break EJS string delimiters

## Package Path
- Kotlin/Java files use `{{package_path}}` in directory names (forward slashes)
- Swift files don't use package_path

## File Suffix
- All files containing Jinja2 expressions must have `.jinja` suffix
- The suffix is stripped after generation
