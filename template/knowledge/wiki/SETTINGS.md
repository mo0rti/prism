---
wiki-stale-after-days: 14
---

# Wiki Settings

Project-level settings for wiki read/query behavior and for the workflow policy.

- `wiki-stale-after-days`: number of days a verification stays fresh. A current-state page
  whose last `verify` entry in `log.md` is older is reported as `stale-page` by
  `prism wiki lint`; a page with no `verify` entry is `never-verified`.
- `qa-separate-from-dev`: `true` or `false` (absent means `false`). When `true`, the board
  refuses a QA approval from a grant that produced the delivery evidence it verifies. It
  separates grants, not proven people. Any other value is `invalid-workflow-policy`, and a
  gated action that reads the policy is refused until it is fixed. The board never writes this
  file.
- `delivery-targets`: where each app is delivered, as a mapping from app ID to
  `{ kind, target, environments }`. `kind` is `deployment`, `store`, `artifact` or `other`;
  `target` is a short name such as `production`; `environments` lists the optional staging
  environments. What an entry leaves out comes from the app's stack:

  | Stack | Kind | Target |
  |---|---|---|
  | `spring-backend`, `nextjs-web`, `python-agent-service` | `deployment` | `production` |
  | `android-compose` | `store` | `play-store` |
  | `ios-swiftui` | `store` | `app-store` |
  | `other` | declare one | declare one |

  An unknown app or a kind outside the four is `invalid-delivery-target`. Changing a target
  affects only future releases.

Both policy keys live in the front matter of this file, for example:

```yaml
qa-separate-from-dev: true
delivery-targets:
  catalog-api: { kind: deployment, target: production, environments: [staging] }
  reader-app: { kind: store, target: play-store, environments: [internal-test] }
```
