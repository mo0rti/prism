# Design Tokens

Shared visual language across all platforms. Edit `tokens.json` to change the design system - all platforms should reference these values.

## How Each Platform Consumes Tokens

### Web / Admin (Tailwind CSS)
Tokens are mapped to CSS custom properties in `globals.css`:
```css
:root {
  --color-primary: #6366F1;
  --spacing-md: 16px;
}
```
Referenced in Tailwind config `extend.colors` and `extend.spacing`.

### Android (Jetpack Compose)
Tokens are mapped to Kotlin constants in `ui/theme/Color.kt` and `ui/theme/Theme.kt`:
```kotlin
val Primary = Color(0xFF6366F1)
```

### iOS (SwiftUI)
Tokens are mapped to Swift extensions in `UI/Theme/AppTheme.swift`:
```swift
extension Color {
    static let primary = Color(hex: "#6366F1")
}
```

## Updating Tokens

1. Edit `tokens.json`
2. Manually update the platform-specific theme files to match
3. (Future: automated token-to-platform script)
