---
description: Jinja2 template validation rules for .jinja files in the template/ and packs/ directories
paths:
  - "template/**/*.jinja"
  - "packs/**/*.jinja"
  - "copier.yml"
---

# Jinja2 Template Rules

When creating or editing `.jinja` files, validate for these common issues:

## Jinja2 Syntax
- All `{{` have matching `}}`
- All `{% if %}` have matching `{% endif %}`
- All `{% for %}` have matching `{% endfor %}`
- Variables match those in `copier.yml`: `project_name`, `project_slug`, `package_identifier`, `description`, `auth_methods`, `github_org` for both layers' answers, `stacks`, `apps` and `app_ids` (derived) for the workspace layer, and `app_id`, `app_name`, `app_path`, `app_package`, `app_package_path`, `app_module_name`, `port`, `ci_workflow_name`, `ci_paths` and `versions` for an app layer
- The template assumes PostgreSQL for a backend's local database and generates `docker-compose.yml` whenever a backend app exists; deployment is the generated `deployment` skill, not a question

## Stack And App Conditionals
- Use `{% if "spring-backend" in stacks %}` for a stack and `{% if "mobile-ios" in app_ids %}` for a full-sample app (not `{% if backend %}`); loop `apps` for per-app output
- Directory-level exclusion uses `_exclude` in `copier.yml`, not per-file guards, and every entry is guarded with `prism_layer == 'workspace'`

## EJS Escaping (Hygen templates in `_templates/`)
- `<%= %>` becomes `{{ '<%=' }} %}` inside Jinja context
- `<%` becomes `{{ '<%' }}`

## String Quoting
- Jinja filters inside EJS template strings use single quotes: `{{ var | replace(' ', '-') }}`
- Double quotes would break EJS string delimiters

## Package Path
- Kotlin/Java files of a pack use `{{ app_package_path }}` in directory names (forward slashes)
- Swift files don't use package_path

## Packs
- Every path of a pack is under `{{ app_path }}/`, except `.github/workflows/{{ app_id }}.yml`, `.cursor/rules/{{ app_id }}.mdc` and the answers file template
- Read pinned versions as `{{ versions.<name> }}`; never repeat a version that `packs/versions.yml` pins

## File Suffix
- All files containing Jinja2 expressions must have `.jinja` suffix
- The suffix is stripped after generation
