# Swift 6 Observation And Dependency Injection

Use this reference when a task touches view model structure, dependency injection, actor isolation, or Observation behavior.

## Swift 6 baseline

- Treat strict concurrency as the default mindset: `project.yml` builds in the Swift 6 language mode.
- View models that drive SwiftUI state are `@MainActor @Observable` unless there is a strong, explicit reason not to.
- A model, error or request type that crosses actor boundaries is a `Sendable` value type (`struct` or `enum`).
- A dependency injected into a `@MainActor` view model is `Sendable` too: `APIClient` and `TokenStore` are `Sendable` protocols. `URLSessionAPIClient` is a struct of value types, and `InMemoryTokenStore` is an actor, so both conform without a workaround.
- Do not rely on Swift 5-era "it usually works" UI mutation patterns.

The slice's profile view model shows the shape:

```swift
@MainActor
@Observable
final class ProfileViewModel {
    private(set) var state: ProfileState = .idle

    private let client: any APIClient
    private let tokenStore: any TokenStore
    private let session: SessionModel

    init(client: any APIClient, tokenStore: any TokenStore, session: SessionModel) { ... }

    func load() async { ... }
}
```

## Main-actor rules

- UI-driving state belongs on the main actor.
- Because the whole view model is `@MainActor`, its methods already execute on the main actor, and an `await` on a dependency hops off and back on its own.
- Use `MainActor.run` only when non-isolated code needs to publish back into main-actor-owned state. Avoid wrapping normal view model mutations in `MainActor.run`.

## Observation mental model

- `@Observable` invalidates only the views that actually read the changed property. If a view does not re-render, first check whether it reads the property you mutated.
- `private let` dependencies are not observed; only stored `var`s are.

## Dependency injection in the slice

- `RootView` is the composition root: it creates the `URLSessionAPIClient`, the `InMemoryTokenStore`, the `SessionModel` and the two view models once, in its `init`, and holds them in `@State`.
- Screens receive their view model through their initializer. Do not recreate a long-lived view model inside `body`.
- A view model takes its dependencies by initializer as protocols (`any APIClient`, `any TokenStore`), so a test passes a fake.
- Use `@Bindable` in a view that needs `$viewModel.field` bindings (a text field or a toggle bound to the view model); a view that only reads and calls its view model, as `SignInView` does, takes it as a plain `let`.
- Avoid `@EnvironmentObject` and ad hoc environment keys for new Observation-based code. Reach for `.environment(...)` only for a truly app-wide, widely read object.

## Replacing a dependency

To use a different token store (for example a Keychain-backed one for a real identity provider), add a type that conforms to `TokenStore`, create it in `RootView.init`, and pass it where `InMemoryTokenStore` is passed now. The view models and their tests do not change.
