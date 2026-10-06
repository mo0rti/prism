# SwiftData Patterns

Use this reference when a task touches SwiftData models, `ModelContext`, or persistent store behavior.

## Actor confinement

- `ModelContext` is not `Sendable`. Keep it on the actor that owns it instead of passing it across concurrency boundaries.
- `@Model` instances should stay on the same actor as their originating `ModelContext`.
- `@MainActor` ViewModels may read and write SwiftData-backed state only when the context they use is also main-actor-owned.

## Query ownership

- Keep simple UI-driven reads close to the owning `@MainActor` ViewModel.
- If a project later introduces heavier background data work, move that logic behind a dedicated actor or repository boundary instead of sharing one `ModelContext` across unrelated tasks.

## Schema evolution

- Treat changes to `@Model` shape as persistent-store changes, not just code refactors.
- When the model grows beyond the starter scaffold, plan schema versioning and migration before shipping incompatible stored-data changes.
