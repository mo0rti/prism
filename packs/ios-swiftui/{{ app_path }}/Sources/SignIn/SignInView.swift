import SwiftUI

/// The sign-in screen. It is the backend's local development identity, labelled as such, and never presented as authentication.
struct SignInView: View {
    let viewModel: SignInViewModel
    let notice: String?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Text(AppInfo.displayName)
                    .font(.largeTitle.bold())
                    .accessibilityIdentifier("signin.app-name")

                if let audience = AppInfo.audience {
                    Text(audience)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .accessibilityIdentifier("signin.audience")
                }

                Text("Local development sign-in")
                    .font(.title2.weight(.semibold))
                    .accessibilityIdentifier("signin.title")

                Text("Signs in as a developer identity that the backend on this Mac issues. It is not complete authentication: replace it with your identity provider before anything ships.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                    .accessibilityIdentifier("signin.note")

                if let notice {
                    Text(notice)
                        .font(.callout)
                        .accessibilityIdentifier("signin.notice")
                }

                if case .failed(let message) = viewModel.state {
                    Text(message)
                        .font(.callout)
                        .foregroundStyle(.red)
                        .accessibilityIdentifier("signin.error")
                }

                Button("Sign in") {
                    Task { await viewModel.signIn() }
                }
                .buttonStyle(.borderedProminent)
                .disabled(viewModel.isSigningIn)
                .accessibilityIdentifier("signin.submit")

                if viewModel.isSigningIn {
                    ProgressView()
                        .accessibilityIdentifier("signin.progress")
                }
            }
            .padding(16)
        }
    }
}
