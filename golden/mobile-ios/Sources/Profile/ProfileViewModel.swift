import Foundation
import Observation

enum ProfileState: Equatable, Sendable {
    case idle
    case loading
    case loaded(UserProfile)
    case failed(String)
}

/// The state of the profile screen: it reads `GET /api/me` with the stored token. A rejected token ends the session.
@MainActor
@Observable
final class ProfileViewModel {
    private(set) var state: ProfileState = .idle

    private let client: any APIClient
    private let tokenStore: any TokenStore
    private let session: SessionModel

    init(client: any APIClient, tokenStore: any TokenStore, session: SessionModel) {
        self.client = client
        self.tokenStore = tokenStore
        self.session = session
    }

    func load() async {
        guard let token = await tokenStore.token() else {
            state = .idle
            session.markSignedOut()
            return
        }

        state = .loading
        do {
            let profile = try await client.getMe(token: token)
            state = .loaded(profile)
        } catch APIError.unauthorized {
            await tokenStore.clear()
            state = .idle
            session.markSignedOut(notice: "Your session ended. Sign in again.")
        } catch {
            state = .failed(error.localizedDescription)
        }
    }

    func signOut() async {
        await tokenStore.clear()
        state = .idle
        session.markSignedOut()
    }
}
