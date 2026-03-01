---
to: docs/features/<%= name %>.md
---
# Feature: <%= h.changeCase.title(name) %>

<%= description %>

## Board Review

- **Product**: _[pending review]_
- **Architecture**: _[pending review]_
- **Security**: _[pending review]_
- **Business**: _[pending review]_
- **Decision**: _[pending]_

> Run `/advisory-review` (Claude), `$advisory-review` (Codex), or ask in Cursor to get board feedback.

## Business Logic

_Describe the core business rules, workflows, and edge cases._

- TODO: Define business rules

## Entities

<% if (entity) { %>
- **<%= h.changeCase.pascal(entity) %>**: See `docs/entities/<%= h.changeCase.param(entity) %>.md`
<% } else { %>
- _TODO: Define entities for this feature_
<% } %>

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
<% if (entity) { %>
| GET | `/<%= h.changeCase.param(h.inflection.pluralize(entity)) %>` | List all (paginated) |
| GET | `/<%= h.changeCase.param(h.inflection.pluralize(entity)) %>/:id` | Get by ID |
| POST | `/<%= h.changeCase.param(h.inflection.pluralize(entity)) %>` | Create |
| PUT | `/<%= h.changeCase.param(h.inflection.pluralize(entity)) %>/:id` | Update |
| DELETE | `/<%= h.changeCase.param(h.inflection.pluralize(entity)) %>/:id` | Delete |
<% } else { %>
| | | _TODO: Define endpoints_ |
<% } %>

## Platform Implementation Status

- [ ] Feature documented
- [ ] API contract defined in `shared/api-contracts/openapi.yml`
- [ ] API clients generated (`task generate-clients`)
- [ ] Backend implemented
- [ ] Web client implemented
- [ ] Admin portal implemented
- [ ] Android implemented
- [ ] iOS implemented
- [ ] Tests passing on all platforms
