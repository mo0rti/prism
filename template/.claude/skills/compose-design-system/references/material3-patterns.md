# Material 3 Patterns

Use this reference when a task needs Android-native UI guidance beyond the repo's
top-level Compose rules.

## Prism-first rules

- Start with `AppTheme`, `MaterialTheme`, `Spacing`, `LoadingIndicator`, and
  `ErrorView` before inventing new tokens or shared components.
- Prefer shared UI in `designsystem/` and keep feature screens focused on
  composition plus feature behavior.
- Treat this as guidance for the generated Android app, not as permission to
  bypass `mobile-android/docs/`.

## Theme and token usage

- Prefer `MaterialTheme.colorScheme`, `typography`, and `shapes` over hardcoded
  colors, text styles, and corner values.
- Prefer shared spacing tokens such as `Spacing.md` over repeated raw `dp`
  values.
- If a component needs a custom visual role, add it to the shared theme or
  design-system layer rather than inventing ad hoc colors per feature.
- Keep dark and light behavior aligned with the app theme. Do not introduce
  shared colors that only read correctly in one mode.

## Surfaces and emphasis

- Use `Surface`, `Card`, and Material 3 defaults to establish hierarchy before
  reaching for custom shadows or heavy decoration.
- Reserve strong emphasis for the highest-priority action or information on the
  screen.
- Avoid stacking multiple competing emphasis cues such as high elevation,
  bright container color, and bold typography all at once.

## App bars and scaffold patterns

- Use `Scaffold` when the screen truly has top app bar, bottom bar, snackbar, or
  floating action ownership.
- Let the screen's structure explain ownership: app bars at the scaffold level,
  content in the scaffold body, feature-local actions close to the content they
  affect.
- When using `Scaffold`, treat its `PaddingValues` as the first source of inset
  information for screen content.
- For concrete inset handling patterns, read
  `references/edge-to-edge-and-insets.md`.

## Adaptive navigation

- The current generated scaffold is phone-first and Navigation 2-oriented.
- If a product grows into a true multi-destination shell, evaluate
  `NavigationSuiteScaffold` rather than hand-building separate bottom-bar and
  rail implementations.
- `NavigationSuiteScaffold` adapts navigation UI across compact and expanded
  sizes, but each inner destination still needs to handle its own insets and
  layout padding deliberately.
- Keep adaptive navigation decisions grounded in real product structure, not
  hypothetical future needs.

## Large-screen and adaptive layout

- Default to compact, phone-first composition unless the screen clearly benefits
  from a wider layout.
- Use layout changes to improve information density, not to create a separate
  product.
- Treat size signals as inputs to composition. The skill `android-conventions`
  owns where those signals come from; this skill owns how UI responds once they
  are available.

## Day/night safety

- Verify that shared surfaces, emphasis colors, and state treatments still read
  correctly in dark mode.
- When overriding Material 3 defaults, confirm that text and icons keep
  sufficient contrast in both light and dark themes.
