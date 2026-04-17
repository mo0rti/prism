# HIG-Aligned SwiftUI Patterns

Use this reference when a task needs Apple-native UI guidance beyond the repo's local theme primitives.

## Prism-first rules

- Start with `UI/Theme/AppTheme.swift`, `Spacing`, and `CornerRadius` before introducing new colors or sizing rules.
- Prefer `UI/Common/` for shared UI, and keep feature views focused on composition and feature behavior.
- Treat these patterns as guidance for the generated iOS app, not as permission to bypass `mobile-ios/docs/`.

## Layout and spacing

- Prefer semantic spacing constants over raw values.
- Use safe-area-aware layouts for sticky actions, bottom call-to-action bars, and overlays.
- Use flexible layouts before fixed frames. Reach for `frame(maxWidth: .infinity, alignment: ...)` and adaptive stacks before hardcoded widths.
- Design for Dynamic Type from the start. Large accessibility sizes should still preserve hierarchy and affordances.

Example:

```swift
VStack(alignment: .leading, spacing: Spacing.md) {
    Text(title)
        .font(.headline)

    Text(subtitle)
        .font(.subheadline)
        .foregroundStyle(.secondary)
}
.padding(Spacing.md)
```

## Adaptive layout

- Default to single-column `NavigationStack` flows on iPhone.
- Consider `NavigationSplitView` only for information-dense iPad experiences or regular-width contexts where a multi-column layout is clearly better.
- Use size class and content density to adapt composition, not to create separate products.

## Color and materials

- Prefer semantic app colors from `Color.app...` over raw `Color.blue`, `Color.red`, or hex literals when a token already exists.
- Custom `Color.app...` tokens are safe only if the theme authors provide light- and dark-appropriate semantics. If that is unclear, prefer system roles like `.primary`, `.secondary`, and `.background`.
- Keep `UI/Theme/AppTheme.swift` honest: if a token claims to be shared semantic color, it should not silently break in dark mode.
- Use system semantic roles like `.primary` and `.secondary` when the app theme does not need a custom role.
- Use materials and blur sparingly. They should clarify hierarchy, not create visual noise.

## Typography

- Prefer semantic text styles like `.headline`, `.body`, and `.footnote`.
- If the app adds custom fonts, ensure they scale with Dynamic Type using `relativeTo:`.
- Avoid relying on font weight alone to communicate state or priority.

## State design

Design the full state model, not just the happy path:

- loading
- empty
- error
- success
- partial-content or retry states when the feature needs them

If a state repeats across features, promote the visual treatment into `UI/Common/`.

## Accessibility

- Use VoiceOver-friendly labels and hints for non-obvious actions.
- Combine child elements into one accessibility element when the card should read as one tappable surface.
- Add button traits for custom tappable cards or surfaces that behave like buttons.
- Verify contrast, hit target size, Dynamic Type behavior, and focus order.
- Avoid conveying critical meaning through color alone.

Example:

```swift
Button {
    openDetails()
} label: {
    VStack(alignment: .leading, spacing: Spacing.sm) {
        Text(title)
            .font(.headline)
        Text(subtitle)
            .font(.subheadline)
            .foregroundStyle(.secondary)
    }
    .padding(Spacing.md)
    .frame(maxWidth: .infinity, alignment: .leading)
}
.buttonStyle(.plain)
.accessibilityElement(children: .combine)
```

## Motion and feedback

- Use motion to support hierarchy and continuity, not decoration.
- Prefer subtle, interruptible animations.
- Respect `@Environment(\.accessibilityReduceMotion)` when choosing whether to animate or simplify transitions.
- Haptics and visual confirmation should reinforce important user actions, especially destructive, successful, or mode-switching interactions.

Example:

```swift
@Environment(\.accessibilityReduceMotion) private var reduceMotion

withAnimation(reduceMotion ? nil : .easeInOut(duration: 0.2)) {
    isExpanded.toggle()
}
```

## Testing workflow

- Test representative screens with VoiceOver enabled on device or simulator.
- Use Accessibility Inspector for labels, traits, contrast, and hit targets.
- Check both standard and accessibility Dynamic Type sizes.

## Optional iOS 18 enhancements

These can improve polish when the project adopts them intentionally, but they are not the iOS 17 baseline:

- richer `Tab` APIs
- zoom navigation transitions
- tab customization patterns that depend on newer APIs

When using them, call out the deployment target impact explicitly.
