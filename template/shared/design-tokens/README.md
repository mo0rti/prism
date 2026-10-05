# Design Tokens

`tokens.json` is the shared reference for the visual language. No script reads it: each platform keeps its own copy of the values in its theme files, and you update them by hand when `tokens.json` changes.

## How Each Platform Uses Tokens

### Web / Admin (Tailwind CSS)
The web apps define their own theme as HSL custom properties in `app/globals.css`, which the Tailwind config references. They do not import `tokens.json`, so copy any token change into those variables:
```css
:root {
  --accent: 145 63% 42%;
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
