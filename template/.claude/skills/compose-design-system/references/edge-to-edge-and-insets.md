# Edge-to-Edge and Insets

Use this reference when a Compose task touches scaffolds, system bars, the
keyboard, list padding, or other inset-sensitive layout.

## Ownership

- This reference owns inset correctness and keyboard-aware container behavior.
- `compose-components.md` owns form layout and validation placement.
- Use this file when the question is "how should the container handle the
  system UI or IME?" rather than "how should the form be structured?"

## Activity and manifest baseline

- Enable edge-to-edge at the activity level.
- Keep `android:windowSoftInputMode="adjustResize"` on activities with form
  screens so the IME can resize content predictably.

## Scaffold inset ownership

- `Scaffold` gives you `PaddingValues`; it does not automatically apply them to
  your content.
- Apply scaffold padding intentionally to scrollable content and consume the
  insets where appropriate.
- Avoid stacking multiple inset strategies on the same container when
  `Scaffold` already owns the main content padding.

RIGHT:

```kotlin
Scaffold { innerPadding ->
    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .consumeWindowInsets(innerPadding),
        contentPadding = innerPadding,
    ) {
        // Content
    }
}
```

WRONG:

```kotlin
Scaffold { innerPadding ->
    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .padding(innerPadding)
            .safeDrawingPadding()
            .imePadding(),
    ) {
        // Multiple inset layers now compete and often over-pad content
    }
}
```

## Lists and scroll containers

- Prefer `contentPadding` on `LazyColumn` or `LazyVerticalGrid` over wrapping
  the entire list in parent `Modifier.padding(...)` when the goal is inset-aware
  scrolling content.
- Use `consumeWindowInsets(...)` when the container should treat already-applied
  padding as handled.

## Keyboard and IME behavior

- For form containers, decide clearly which layer owns IME behavior.
- Use `imePadding()` when it is the simplest correct container-level solution.
- When ancestor layouts already consume insets or nested inset chains become
  confusing, `WindowInsetsRulers` plus `fitInside(...)` can be a better choice
  because they avoid inset-consumption complexity.
- Note: `WindowInsetsRulers` and `fitInside(...)` require
  `androidx.activity:activity-compose:1.9.0` or later. Check
  `libs.versions.toml` before using these APIs.

RIGHT:

```kotlin
Box(
    modifier = Modifier
        .fillMaxSize()
        .fitInside(WindowInsetsRulers.SafeDrawing.current),
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .verticalScroll(rememberScrollState())
            .fitInside(WindowInsetsRulers.Ime.current),
    ) {
        // Form content
    }
}
```

WRONG:

```kotlin
Scaffold(
    contentWindowInsets = WindowInsets.safeDrawing,
) { innerPadding ->
    Column(
        modifier = Modifier
            .padding(innerPadding)
            .imePadding()
            .verticalScroll(rememberScrollState()),
    ) {
        // safeDrawing already accounts for IME here, so imePadding() double-applies it
    }
}
```

## Material 3 inset-aware components

- Many Material 3 components already expose `windowInsets` parameters or have
  inset-aware defaults.
- Before adding extra padding around app bars, navigation UI, or bottom surfaces,
  check whether the component already handles the relevant insets.

## Reference style

- Prefer small RIGHT/WRONG examples when documenting inset behavior.
- Insets bugs are usually caused by modifier placement, not by missing prose.
