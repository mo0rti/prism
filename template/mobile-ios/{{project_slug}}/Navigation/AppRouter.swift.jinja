import SwiftUI

private enum AuthGateState {
    case checking
    case authenticated
    case unauthenticated
}

struct AppRouter: View {
    @Environment(DependencyContainer.self) private var container
    @State private var authState: AuthGateState = .checking

    var body: some View {
        Group {
            switch authState {
            case .checking:
                LoadingView()
            case .authenticated:
                AuthenticatedRoot(
                    exampleRepository: container.exampleRepository,
                    authRepository: container.authRepository
                )
            case .unauthenticated:
                LoginRoot(authRepository: container.authRepository)
            }
        }
        .task {
            await refreshAuthState()
        }
        .task {
            for await _ in NotificationCenter.default.notifications(named: TokenStorage.tokensDidChangeNotification) {
                await refreshAuthState()
            }
        }
    }

    @MainActor
    private func refreshAuthState() async {
        authState = await container.tokenStorage.hasToken() ? .authenticated : .unauthenticated
    }
}

private struct AuthenticatedRoot: View {
    @State private var viewModel: ExampleListViewModel

    init(exampleRepository: ExampleRepository, authRepository: AuthRepository) {
        _viewModel = State(
            wrappedValue: ExampleListViewModel(
                exampleRepository: exampleRepository,
                authRepository: authRepository
            )
        )
    }

    var body: some View {
        NavigationStack {
            ExampleListView(viewModel: viewModel)
        }
        .accessibilityIdentifier("examples.screen")
    }
}

private struct LoginRoot: View {
    @State private var viewModel: LoginViewModel

    init(authRepository: AuthRepository) {
        _viewModel = State(wrappedValue: LoginViewModel(authRepository: authRepository))
    }

    var body: some View {
        LoginView(viewModel: viewModel)
    }
}
