# Swift 6 Observation And DI

Use this reference when a task touches ViewModel structure, dependency injection, actor isolation, or Observation behavior.

## Swift 6 baseline

- Treat strict concurrency as the default mindset for generated iOS projects.
- ViewModels that drive SwiftUI state should be `@MainActor @Observable` unless there is a strong, explicit reason not to.
- If a helper type, model, or closure crosses actor boundaries, prefer making the value type `Sendable` when practical.
- If a repository protocol or implementation is injected into a `@MainActor` ViewModel, make that dependency `Sendable` too.
- Actor-backed dependencies already satisfy sendability, so repository types that store actors such as `APIClient` or `TokenStorage` can usually adopt `Sendable` directly.
- Do not rely on Swift 5-era "it usually works" UI mutation patterns.

Example:

```swift
enum ProfileViewState: Equatable {
    case idle
    case loading
    case success
    case error(String)
}

protocol ProfileRepository: Sendable {
    func fetchProfile() async throws -> Profile
}

@MainActor
@Observable
final class ProfileViewModel {
    var viewState: ProfileViewState = .idle
    var profile: Profile?

    private let repository: ProfileRepository

    init(repository: ProfileRepository) {
        self.repository = repository
    }

    func load() async {
        viewState = .loading
        do {
            profile = try await repository.fetchProfile()
            viewState = .success
        } catch {
            viewState = .error(error.localizedDescription)
        }
    }
}
```

## Main-actor rules

- UI-driving state belongs on the main actor.
- Because the whole ViewModel is `@MainActor`, its methods already execute on the main actor by default.
- Use `MainActor.run` only when non-isolated code needs to publish back into main-actor-owned UI state. Avoid wrapping normal `@MainActor` ViewModel mutations in extra `MainActor.run` calls.
- Prefer isolating the whole ViewModel to `@MainActor` over scattering `MainActor.run` calls.

## Observation mental model

- `@Observable` invalidates only the views that actually read the changed property.
- This is more precise than the old `ObservableObject` mental model.
- If a view does not re-render, first check whether it reads the property you mutated.

## Dependency injection pattern in this repo

- The app creates one `DependencyContainer` near the root and injects it with `.environment(container)`.
- `@Environment(DependencyContainer.self)` depends on `DependencyContainer` being an `@Observable` type.
- `AppRouter` and other app-level coordinators read the container from SwiftUI environment.
- Feature screens usually receive a feature-specific ViewModel through their initializer.
- Do not recreate long-lived ViewModels in frequently recomputed `body` paths.

Environment access at the app or router boundary:

```swift
@Environment(DependencyContainer.self) private var container
```

Stable local ownership when a view creates its own long-lived ViewModel:

```swift
struct FeatureScreen: View {
    @State private var viewModel: FeatureViewModel

    init(repository: FeatureRepository) {
        _viewModel = State(wrappedValue: FeatureViewModel(repository: repository))
    }

    var body: some View {
        FeatureView(viewModel: viewModel)
    }
}
```

Caller-side wiring from the app or router boundary:

```swift
@Environment(DependencyContainer.self) private var container

FeatureScreen(repository: container.featureRepository)
```

## Ownership rules

- Use `@State` or another stable owner for long-lived local `@Observable` instances created by a view.
- Pass ViewModels downward through initializers.
- Avoid ad hoc `EnvironmentKey` ViewModel injection unless the ViewModel is truly app-scoped and reused broadly.
- Avoid reviving `@EnvironmentObject` patterns for new Observation-based code in this repo.
