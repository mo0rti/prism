---
name: compose-design-system
description: Compose UI and design-system rules for this repo. Use when building, refactoring, or reviewing screens, shared components, theme architecture, color roles, day/night theming, previews, or reusable modifiers.
user-invocable: false
---

# Compose Design System

Use this skill when Compose work should stay aligned with the app's shared UI language.

## Role boundary

- Own shared UI language, reusable Compose primitives, previews, and cross-feature visual patterns.
- Defer Route/Screen architecture, `UiState`, event-flow rules, and navigation ownership to `android-conventions`.
- Defer DTO, repository, and auth-boundary decisions to `android-contract-alignment`.
- Defer Gradle task selection to `android-build-verify`.
- The current generated scaffold remains Navigation 2-oriented. If the template later migrates the scaffold, revisit this skill's navigation-related examples rather than assuming the same model forever.

## Shared UI rules

- Use `AppTheme`, `MaterialTheme`, and shared components from `designsystem/` instead of feature-local one-offs.
- Prefer shared tokens like `Spacing` plus `MaterialTheme.colorScheme`, `typography`, and `shapes` before introducing raw `dp`, hardcoded colors, or one-off text styles.
- Put reusable components, modifiers, and drawing helpers in `designsystem/`; keep feature files focused on composition.
- Keep user-facing text in `strings.xml` and resolve it with `stringResource(...)` or `UiText`.
- Every owning activity for full-screen Compose content must call `enableEdgeToEdge()` before `setContent`. Preserve existing calls and add one when creating a new activity unless a platform-specific migration explicitly replaces that baseline.
- Keep `android:windowSoftInputMode="adjustResize"` on form activities unless the IME behavior is intentionally redesigned and revalidated.
- When using `Scaffold`, treat its `PaddingValues` as the first source of content insets. Do not stack competing inset strategies on the same container without a clear ownership reason.
- Interactive custom surfaces must expose meaningful accessibility semantics, adequate touch targets, and must not rely on color alone to convey important state.

## Existing patterns to reuse

- `LoadingIndicator`
- `ErrorView`
- `Spacing`
- `AppTheme`

## Theme structure

- `designsystem/theme/` contains Color, Type, Shape, Dimensions, and Theme definitions.
- `designsystem/text/` contains `UiText` (framework-light string wrapper).
- `designsystem/components/` contains shared composables: LoadingIndicator, ErrorView, and feature-agnostic primitives.

## Reference files

Read only the reference file the task needs:

- `references/material3-patterns.md` for theme, Material 3 component choice, surfaces, and adaptive navigation callouts
- `references/compose-components.md` for reusable state surfaces, forms, dialogs, lists, buttons, previews, and shared-component patterns
- `references/edge-to-edge-and-insets.md` for scaffold insets, IME behavior, `WindowInsetsRulers`, `fitInside(...)`, and RIGHT/WRONG inset patterns
- `references/accessibility-and-adaptive-layout.md` for semantics, touch targets, text scaling, and layout response to size changes

For Route/Screen split, `UiState`, `collectAsStateWithLifecycle()`, or event-flow questions, read `android-conventions` instead.

## Preview and composition rules

- Wrap previews in `AppTheme`.
- Keep shared components stateless and parameter-driven where possible.
- Prefer extending existing design-system primitives before creating a new shared abstraction.
- When a UI element is reusable across features, move it out of the feature package.
- Use `@PreviewParameter` or multipreview annotations such as `@PreviewScreenSizes` and `@PreviewFontScales` when a shared component has multiple meaningful UI states or layout risks.
