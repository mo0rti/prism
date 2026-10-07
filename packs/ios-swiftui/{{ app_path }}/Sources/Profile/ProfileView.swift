import SwiftUI

/// The profile screen: the signed-in user as `GET /api/me` returns it.
struct ProfileView: View {
    let viewModel: ProfileViewModel

    var body: some View {
        NavigationStack {
            content
                .navigationTitle("Profile")
                .toolbar {
                    ToolbarItem(placement: .topBarTrailing) {
                        Button("Sign out") {
                            Task { await viewModel.signOut() }
                        }
                        .accessibilityIdentifier("profile.sign-out")
                    }
                }
        }
        .task {
            await viewModel.load()
        }
    }

    @ViewBuilder
    private var content: some View {
        switch viewModel.state {
        case .idle, .loading:
            ProgressView()
                .accessibilityIdentifier("profile.loading")
        case .loaded(let profile):
            List {
                LabeledContent("Name", value: profile.displayName)
                    .accessibilityIdentifier("profile.display-name")
                if let email = profile.email {
                    LabeledContent("Email", value: email)
                        .accessibilityIdentifier("profile.email")
                }
                LabeledContent("User ID", value: profile.id)
                    .accessibilityIdentifier("profile.id")
                LabeledContent("Created", value: profile.createdAt)
                    .accessibilityIdentifier("profile.created-at")
            }
        case .failed(let message):
            VStack(spacing: 16) {
                Text(message)
                    .multilineTextAlignment(.center)
                    .accessibilityIdentifier("profile.error")
                Button("Try again") {
                    Task { await viewModel.load() }
                }
                .buttonStyle(.bordered)
                .accessibilityIdentifier("profile.retry")
            }
            .padding(16)
        }
    }
}
