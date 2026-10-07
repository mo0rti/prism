import Foundation
import Observation

enum SignInState: Equatable, Sendable {
    case idle
    case signingIn
    case failed(String)
}

/// The state of the "Local development sign-in" screen: it asks the backend's development identity for a token,
/// keeps the token in the token store and tells the session that a person is signed in.
@MainActor
@Observable
final class SignInViewModel {
    var email = ""
    var displayName = ""
    private(set) var state: SignInState = .idle

    private let client: any APIClient
    private let tokenStore: any TokenStore
    private let session: SessionModel

    init(client: any APIClient, tokenStore: any TokenStore, session: SessionModel) {
        self.client = client
        self.tokenStore = tokenStore
        self.session = session
    }

    var isSigningIn: Bool {
        state == .signingIn
    }

    func signIn() async {
        guard !isSigningIn else { return }
        state = .signingIn

        let request = DevTokenRequest(email: Self.optionalText(email), displayName: Self.optionalText(displayName))
        do {
            let response = try await client.createDevToken(request)
            await tokenStore.save(response.accessToken)
            state = .idle
            session.markSignedIn()
        } catch {
            state = .failed(error.localizedDescription)
        }
    }

    /// A field the person left empty is not sent, so the backend applies its default.
    private static func optionalText(_ text: String) -> String? {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }
}
