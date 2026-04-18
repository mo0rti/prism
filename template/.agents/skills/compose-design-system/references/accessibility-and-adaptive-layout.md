# Accessibility and Adaptive Layout

Use this reference when a Compose task needs accessibility semantics, text-scale
resilience, or layout guidance for different size classes.

## Accessibility semantics

- Use `contentDescription` for simple descriptive labels on icons and images.
- Use `Modifier.semantics {}` when a composable needs richer accessibility
  meaning than a single label.
- Use `mergeDescendants = true` when a composed surface should read as one
  combined interactive region.
- Use `clearAndSetSemantics {}` when child semantics would otherwise create noisy
  or misleading output.

RIGHT:

```kotlin
Row(
    modifier = Modifier.semantics(mergeDescendants = true) {},
) {
    Icon(Icons.Default.Email, contentDescription = null)
    Text(emailAddress)
}
```

WRONG:

```kotlin
Row {
    Icon(Icons.Default.Email, contentDescription = "Email icon")
    Text(emailAddress)
}
```

## Touch targets and clarity

- Keep touch targets comfortably sized and spaced.
- Do not rely on color alone to convey important state.
- Ensure icons used as actions have meaningful labels and not just decorative
  descriptions.

## Text scaling and layout resilience

- Check that shared components still read well at larger font scales.
- Prefer flexible widths, wrapping text, and content-driven height over fixed
  sizes that break under localization or font scaling.
- Use `@PreviewFontScales` when a shared component has meaningful text-density
  risk.

## Adaptive layout response

- This skill owns how shared UI responds once size information is available.
- `android-conventions` owns where `WindowSizeClass` or similar signals are
  collected and threaded through the app.
- Keep compact layouts as the default baseline unless the screen clearly
  benefits from an expanded arrangement.
- Use larger layouts to improve hierarchy and density, not to invent a separate
  product.

## Testing workflow

- Preview shared components across light/dark, font scale, and relevant screen
  sizes when layout risk is non-trivial.
- Use Compose UI tests for important semantics or state-surface regressions when
  the behavior is hard to validate by eye alone.

