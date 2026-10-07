---
wiki-stale-after-days: 14
---

# Wiki Settings

Project-level settings for wiki read/query behavior.

- `wiki-stale-after-days`: number of days a verification stays fresh. A current-state page
  whose last `verify` entry in `log.md` is older is reported as `stale-page` by
  `prism wiki lint`; a page with no `verify` entry is `never-verified`.
