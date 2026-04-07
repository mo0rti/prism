---
to: knowledge/intake/pending/feature-<%= h.changeCase.param(name) %>/intake.md
---
# Intake: <%= h.changeCase.title(name) %>

**Submitted:** <%= new Date().toISOString().slice(0,10) %>

## Description

<%= description %>

## Notes

_Add any additional context, user stories, acceptance criteria, or open questions here._

---

> **Next step:** Run `/po-intake feature-<%= h.changeCase.param(name) %>` (Claude Code) or `po-intake feature-<%= h.changeCase.param(name) %>` (Codex) to process this into a wiki feature spec.
> The PO intake command will assign a sequential ID, create the wiki page, and update the index.
