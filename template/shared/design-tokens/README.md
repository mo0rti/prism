# Design Tokens

`tokens.json` is the shared reference for the visual language. No script reads it: each platform keeps its own copy of the values in its theme files, and you update them by hand when `tokens.json` changes.

## How Each Platform Uses Tokens

### Web (CSS custom properties)
Each web app defines its own colors as CSS custom properties in `app/globals.css`, with a dark-mode override. They do not import `tokens.json`, so copy any token change into those variables:
```css
:root {
  --accent: #2456d6;
}
```

### Android (Jetpack Compose)
The primary and secondary colors in `designsystem/theme/Color.kt` use the token values:
```kotlin
val Primary = Color(0xFF6366F1)
```

### iOS (SwiftUI)
The same colors are Swift extensions in `UI/Theme/AppTheme.swift`:
```swift
extension Color {
    static let appPrimary = Color(dynamicLight: "#6366F1", dark: "#818CF8")
}
```

## Updating Tokens

1. Edit `tokens.json`
2. Update the platform-specific theme files to match
