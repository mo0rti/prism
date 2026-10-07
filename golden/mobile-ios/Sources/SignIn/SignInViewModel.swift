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

        // The request names no email and no display name, so the backend signs in its default developer, as the Android app does.
        let request = DevTokenRequest()
        do {
            let response = try await client.createDevToken(request)
            await tokenStore.save(response.accessToken)
            state = .idle
            session.markSignedIn()
        } catch {
            state = .failed(error.localizedDescription)
        }
    }
}
