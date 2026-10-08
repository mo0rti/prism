@AGENTS.md

## Claude Code skills

Project-specific Claude skills live in `.claude/skills/`; Claude Code loads them when the work matches. Detailed conventions are documented there.

- `ios-conventions` - the slice's Swift, SwiftUI, concurrency and structure rules, and replacing the dev identity
- `ios-build-verify` - choose the smallest sufficient `xcodebuild` or Taskfile validation
- `ios-feature-delivery` - coordinate feature work across the slice's layers
- `ios-contract-alignment` - keep models, endpoints and the API client aligned with the OpenAPI contract
- `ios-testing` - unit tests with the fake client, UI tests and the hittable wait
- `swiftui-design-system` - SwiftUI patterns for screens, accessibility and Dynamic Type
- `deployment` - worked examples for store releases; the user and their agent own signing and the release

## iOS Claude Commands

- `/generate-clients` - validate the shared contract; this app's client is hand-written and kept to it with `ios-contract-alignment`
