---
name: swiftui-design-system
description: SwiftUI UI rules for the generated iOS apps. Use when building, refactoring or reviewing screens, shared views, spacing, color roles, accessibility or reusable view patterns in an iOS app.
---

# SwiftUI Design System

Use this skill when SwiftUI work should stay consistent and accessible. The slice has two screens (`Sources/SignIn/SignInView.swift`, `Sources/Profile/ProfileView.swift`) built from system styles, and no custom theme: they are the starting point.

## Slice files

Paths are inside the iOS app's folder (`mobile-ios/`).

- `Sources/SignIn/SignInView.swift` - the sign-in screen
- `Sources/Profile/ProfileView.swift` - the profile screen
- `Sources/RootView.swift` - chooses the screen from the session

## Role boundary

- Own screen composition, shared views, accessibility and visual patterns.
- Defer models, networking, session and build-task decisions to the companion iOS skills.
- Defer architecture and view model ownership to `$ios-conventions`.
- Treat the deployment target in `project.yml` as the baseline. Mark APIs newer than it as optional upgrades, not default patterns.

## Rules

- Use system colors (`.primary`, `.secondary`, `.background`) and semantic text styles by default. A custom color must work in light and dark appearance; map the tokens of `shared/design-tokens/` once, in one file, if the project adopts a palette.
- Keep screens in their own folder under `Sources/` with a view and a view model. The view renders state and sends intents; it holds no networking.
- Extract a shared view into its own file once two screens repeat the same fragment, and keep it stateless and parameter-driven.
- Icon-only or otherwise non-obvious actions must expose a clear `accessibilityLabel`.
- Custom tappable surfaces must expose button semantics (`.accessibilityAddTraits(.isButton)`) when SwiftUI does not infer them.
- Grouped cards or composite rows use `accessibilityElement(children: .combine)` when VoiceOver should read them as one item.
- If custom fonts are introduced, scale them with `relativeTo:` so Dynamic Type stays correct.
- Never convey important state by color alone.
- Put an accessibility identifier on each screen title and critical control, and keep it stable: the UI test depends on it.
- Design the whole state model of a screen: loading, error, success and retry, as `ProfileView` does.
- The sign-in screen says "Local development sign-in" and that it is not complete authentication. Keep that wording until the dev identity is replaced.

## Reference files

Load only the reference file the task needs:

- `references/hig-patterns.md` for Apple-native layout, accessibility, adaptive layout and state-pattern guidance

## Preview and composition rules

- Give a shared view at least one `#Preview`.
- Keep shared views stateless and parameter-driven where possible.
