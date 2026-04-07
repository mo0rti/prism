# Business rule format

Use this format for business rule pages in `wiki/business-rules/`.
Filename: `BR-XXX-[slug].md`.

```markdown
---
id: BR-XXX
title: [Rule name]
introduced: YYYY-MM-DD
source: [intake source or board review that established this rule]
---

## Rule
One unambiguous statement of the rule.

## Rationale
Why this rule exists: legal, business, product decision, board recommendation, or
another named source.

## Affected features
Feature IDs that must comply with this rule.

## Exceptions
Any explicitly agreed exceptions with source reference. If none, write "No exceptions."
```
