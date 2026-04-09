# Wiki show - focused feature context bundle

## Usage
/wiki-show F-XXX

## Purpose

Assemble a focused feature context bundle for one feature.

## Read-only rules

- read-only command
- do not write any wiki files
- do not refresh `WIKI_REPORT.md`
- if `WIKI_REPORT.md` is missing, tell the user to run `/feature-status` for an updated orientation summary

## Files to read

- `knowledge/wiki/index.md`
- `knowledge/wiki/features/[F-XXX]-[slug].md`
- `knowledge/wiki/design/[F-XXX]-[slug].md` if present
- `knowledge/wiki/api-contracts/[F-XXX].md` if present
- all matching `knowledge/wiki/platform-requirements/[F-XXX]-*.md`
- any files in `knowledge/wiki/business-rules/` that reference the feature ID
- `knowledge/wiki/advisory/[F-XXX]-review.md` if present

## Assembly rules

- Resolve the feature slug from the feature file name, not from guesswork
- Use the feature file frontmatter as the authority for `status`, `owner`, and `advisory-review`
- Treat missing optional linked files as informative absence, not as an error
- Compute blockers from current wiki state instead of relying on a handwritten summary field

## Recommended output shape

```text
Feature: F-012 - Saved Checkout
Status: ready-for-dev
Owner: dev
Advisory review: done

Summary:
Customers can reuse a saved shipping address and payment preference during checkout.

Open questions:
- Designer: What does the invalid saved address state look like? [open]
- Dev: Should guest checkout support saved addresses later? [resolved: no, account only]

Linked context:
- Design: knowledge/wiki/design/F-012-saved-checkout.md
- API contract: knowledge/wiki/api-contracts/F-012.md
- Board review: knowledge/wiki/advisory/F-012-review.md
- Business rules:
  - BR-004-checkout-address-validation.md
  - BR-011-payment-method-eligibility.md

Platform requirements:
- backend: in-progress
- mobile-ios: pending
- mobile-android: pending
- web-user-app: pending

Current blockers:
- api-contract-not-ready: mobile-ios platform requirements depend on the API contract status changing from draft to agreed
- missing-design: design page does not define the expired payment-method state

Suggested next action:
Run design-clarify or update the design page before active implementation begins.
```

## Partial/error-state examples

```text
Feature: F-099
Status: error

Problem:
No feature file matching F-099 was found in knowledge/wiki/features/.

Next step:
Check the feature ID or run /feature-status to inspect the current board.
```

```text
Feature: F-012 - Saved Checkout
Status: partial
Owner: dev
Advisory review: done

Summary:
Feature file found, but linked implementation context is incomplete.

Missing linked context:
- No design page found
- No platform requirements found for mobile-ios

Next step:
Create the missing linked files before treating this feature as fully implementation-ready.
```
