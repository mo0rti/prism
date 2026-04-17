# SwiftUI Component Patterns

Use this reference when building or extracting reusable SwiftUI UI in the generated iOS app.

## Prism-first rules

- Reuse `PrimaryButton`, `LoadingView`, and `ErrorView` before inventing replacements.
- Promote repeated view fragments into `UI/Common/`.
- Keep shared components stateless and parameter-driven where possible.
- Route feature-specific async work and data fetching through ViewModels and repositories, not inside reusable views.

## Lists and collections

- Use `List` when platform-native list behavior, edit actions, or grouped styling are the right fit.
- Use `ScrollView` plus `LazyVStack` or `LazyVGrid` when you need more visual control than `List` provides.
- Prefer stable identifiers and predictable row composition.

Example:

```swift
ScrollView {
    LazyVStack(spacing: Spacing.md) {
        ForEach(items) { item in
            ItemCard(item: item)
        }
    }
    .padding(.horizontal, Spacing.md)
    .padding(.vertical, Spacing.lg)
}
```

## Forms and settings

- Use `Form` for settings, account, preference, and data-entry screens that should feel system-native.
- Keep validation feedback close to the field that caused it.
- Use focused state and content types where they meaningfully improve keyboard behavior.

## Buttons and actions

- Use the shared `PrimaryButton` when the generated app already has the appropriate primary call-to-action style.
- Keep button hierarchy clear: one primary action, optional secondary action, restrained destructive action.
- Use `Menu` and `confirmationDialog` for overflow or destructive actions instead of overloading the main layout.

## Sheets and modals

- Present sheets for contained tasks, settings, confirmations, or short-lived flows.
- Wrap complex sheet flows in `NavigationStack`.
- Use detents only when they improve the task, not by default.

Example:

```swift
.sheet(isPresented: $showSettings) {
    NavigationStack {
        SettingsView()
    }
}
```

## Loading, error, and empty states

- Prefer shared `LoadingView` and `ErrorView` for common app states.
- Default to `ContentUnavailableView` for iOS 17 empty states unless the feature needs a clearly differentiated branded alternative.
- Distinguish between "no data yet", "filtered to no results", and "failed to load".

## Cards and reusable surfaces

- Use token-backed color, spacing, and corner-radius values.
- Avoid stacking heavy shadows, gradients, and overlays unless they serve hierarchy.
- Prefer a small set of card patterns reused consistently across features.

## Previews

- Add previews when they materially help understand a shared or reused component.
- Preview meaningful states:
  - default
  - loading if applicable
  - error if applicable
  - long text or accessibility-sized content when layout risk is non-trivial

## Anti-patterns

- hardcoded theme colors where app tokens already exist
- network or repository work inside shared components
- one-off copies of the same badge, card, button, or state treatment across feature folders
- fixed-size layouts that break under localization or Dynamic Type
