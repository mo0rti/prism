# Compose Component Patterns

Use this reference when building or extracting reusable Compose UI in the
generated Android app.

## Prism-first rules

- Reuse `LoadingIndicator`, `ErrorView`, and `Spacing` before inventing
  replacements.
- Promote repeated feature UI into `designsystem/components/`.
- Keep shared components stateless and parameter-driven where possible.
- Keep repository, networking, and async business logic out of reusable
  composables.

## State surfaces

Design the full state model, not only the happy path:

- loading
- empty
- error
- success
- partial-content or retry states when the feature needs them

If a state treatment repeats across features, promote the visual surface into
`designsystem/components/` instead of re-implementing it.

RIGHT:

```kotlin
when (uiState) {
    is ExampleListUiState.Loading -> LoadingIndicator()
    is ExampleListUiState.Error -> ErrorView(
        message = uiState.message.asString(context),
        onRetry = onRetry,
    )
    is ExampleListUiState.Success -> LazyColumn {
        items(uiState.examples, key = { it.id }) { example ->
            Text(example.title)
        }
    }
    ExampleListUiState.Idle -> LoadingIndicator()
}
```

WRONG:

```kotlin
if (uiState is ExampleListUiState.Error) {
    Text("Something went wrong")
} else {
    // Every screen invents its own loading and empty UI
}
```

## Forms and validation

- This reference owns form field hierarchy, input layout, and validation
  feedback placement.
- Keep validation feedback close to the field or action that caused it.
- Use clear field labels, single-line input where appropriate, and restrained
  supporting text.
- Keep primary actions visually separate from tertiary sign-in or overflow
  actions.
- `edge-to-edge-and-insets.md` owns how form containers behave with the
  keyboard, IME insets, and double-padding avoidance.

RIGHT:

```kotlin
Column(
    verticalArrangement = Arrangement.spacedBy(Spacing.md),
) {
    OutlinedTextField(
        value = email,
        onValueChange = onEmailChange,
        label = { Text(stringResource(R.string.auth_email_label)) },
        modifier = Modifier.fillMaxWidth(),
        singleLine = true,
    )

    if (emailError != null) {
        Text(
            text = emailError,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.error,
        )
    }

    Button(
        onClick = onSubmit,
        modifier = Modifier.fillMaxWidth(),
    ) {
        Text(stringResource(R.string.auth_sign_in))
    }
}
```

WRONG:

```kotlin
Column {
    OutlinedTextField(value = email, onValueChange = onEmailChange)
    OutlinedTextField(value = password, onValueChange = onPasswordChange)
    Text("Invalid email or password")
    Text("Other generic error")
    Button(onClick = onSubmit) { Text("Go") }
}
```

## Lists, grids, and cards

- Use `LazyColumn` or `LazyVerticalGrid` for scalable collections.
- Prefer stable keys and predictable row composition.
- Apply list padding through `contentPadding` when inset-aware scrolling matters.
- Keep card patterns small in number and consistent across features.

## Buttons, menus, dialogs, and sheets

- Keep one primary action visually dominant.
- Use `OutlinedButton` or lower-emphasis actions for secondary paths.
- Use `AlertDialog`, menus, or sheets when the task is truly contextual or
  interruptive.
- Avoid turning every secondary action into a full-width primary button.

## Previews

- Wrap previews in `AppTheme`.
- Preview meaningful states, not just the default success state.
- Use `@PreviewParameter` when a component should render multiple meaningful data
  or state variants in one preview setup.
- Use multipreview annotations such as `@PreviewScreenSizes` or
  `@PreviewFontScales` when layout risk or text scaling risk is non-trivial.

## Stability and recomposition

- Prefer immutable UI models for shared components. `@Immutable` or `@Stable`
  can help when the type really satisfies those contracts.
- Use `remember` for expensive derived objects tied to stable inputs.
- Use `derivedStateOf` when a derived value should only update when its source
  state changes, not on every recomposition.
- Do not overuse these tools. Reach for them when shared UI shows real
  recomposition churn or unstable inputs, not by default everywhere.

## Anti-patterns

- feature-local copies of the same button, card, or state surface
- hardcoded colors or text styles where shared theme roles already exist
- validation messages far from the field or action that caused them
- screens that mix layout, networking, and state-surface rendering inside one
  large composable
