---
name: cursor-mobile-ios
description: "iOS (Swift 6, SwiftUI) app facts: stack, structure, MVVM pattern and conventions."
layers: [cursor]
stacks: [ios-swiftui]
cursor:
  file: mobile-ios
  globs: "mobile-ios/**"
---

# iOS - Swift 6 + SwiftUI

## Stack
- Swift 6, SwiftUI, async/await
- URLSession-based APIClient (actor)
- Keychain token storage (actor)
- SwiftData for local caching
- XcodeGen for project generation (Mac only)
- Min iOS 17.0, Xcode 26

## Structure
```
{{ project_slug }}/
  DI/            -> DependencyContainer (@Observable)
  Navigation/    -> AppRouter + Route enum
  Data/Network/  -> APIClient (actor), APIEndpoint
  Data/Storage/  -> TokenStorage (Keychain), SwiftData models
  Data/Repository/ -> Protocol + Impl
  Domain/Model/  -> Codable DTOs
  UI/Theme/      -> AppTheme (design tokens)
  UI/Auth/       -> LoginView + LoginViewModel
  UI/Examples/   -> ExampleListView + ExampleListViewModel
  UI/Common/     -> LoadingView, ErrorView, PrimaryButton
```

## MVVM Pattern
- `@Observable` ViewModel with `ViewState` enum
- `enum ViewState`: idle, loading, success, error(String)
- SwiftUI `View` structs with `@Bindable` ViewModel
- DI via protocol-based `DependencyContainer`, injected with `.environment()`

## Conventions
- One ViewModel per screen
- Repositories: protocol + Impl
- APIClient is an actor for thread safety
- TokenStorage uses Keychain via Security framework
- SwiftData `@Model` classes for local caching
- NavigationStack + Route enum for navigation
- Tests use XCTest with mock repositories
- `Config/Debug.xcconfig` and `Config/Release.xcconfig` are git-ignored; `task mobile-ios:generate-project` creates a missing one from its tracked `.example` file
- Write URLs in xcconfig files as `http:/$()/host/path`, because `//` starts a comment
- Build and test tasks use `SIMULATOR_NAME` when set, otherwise the newest available iPhone simulator
