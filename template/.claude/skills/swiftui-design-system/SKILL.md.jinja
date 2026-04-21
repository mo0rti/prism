---
name: swiftui-design-system
description: SwiftUI design system rules for this generated project. Use when building, refactoring, or reviewing screens, shared components, theme primitives, spacing, color roles, or reusable view patterns in the iOS app.
user-invocable: false
---

# SwiftUI Design System

Use this skill when SwiftUI work should stay aligned with the generated app's shared UI language.

## Role boundary

- Own shared UI language, reusable SwiftUI components, and cross-feature visual patterns.
- Defer DTO, repository, auth, router ownership, and build-task decisions to the companion iOS skills.
- Defer navigation architecture and route ownership to `ios-conventions`.
- Treat iOS 17 as the baseline for generated projects. Mark iOS 18-only APIs as optional upgrades, not default patterns.

## Shared UI rules

- Use `Color.app...` theme colors from `UI/Theme/AppTheme.swift` instead of hardcoded colors where a shared token already exists.
- Custom `Color.app...` tokens must stay safe across light and dark appearance. If a token is not authored semantically for both, prefer system roles like `.primary`, `.secondary`, and `.background`.
- Use `Spacing` and `CornerRadius` constants instead of repeating raw values.
- Put reusable components in `UI/Common/`; keep feature files focused on screen composition.
- Keep screen backgrounds, badges, buttons, and shared loading or error states visually consistent across features.
- Icon-only or otherwise non-obvious actions must expose a clear `accessibilityLabel`.
- Custom tappable surfaces must expose button semantics such as `.accessibilityAddTraits(.isButton)` when SwiftUI does not infer them automatically.
- Grouped cards or composite rows should use `accessibilityElement(children: .combine)` when VoiceOver should read them as one coherent item.
- Use semantic text styles by default. If custom fonts are introduced, scale them with `relativeTo:` so Dynamic Type remains correct.
- Shared components must not rely on color alone to communicate important state.

## Existing patterns to reuse

- `PrimaryButton`
- `LoadingView`
- `ErrorView`
- `Spacing`
- `CornerRadius`

## Reference files

Read only the reference file the task needs:

- `references/hig-patterns.md` for Apple-native layout, accessibility, adaptive layout, and state-pattern guidance
- `references/swiftui-components.md` for reusable screen sections, forms, buttons, sheets, loading, and empty or error states

For route ownership, `AppRouter`, or navigation architecture questions, read `ios-conventions` and its navigation reference instead.

## Preview and composition rules

- Shared components in `UI/Common/` must include at least one `#Preview` that applies the shared theme tokens where applicable.
- Keep shared components stateless and parameter-driven where possible.
- Promote repeated view fragments out of feature screens into `UI/Common/`.
