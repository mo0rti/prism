import SwiftUI

/// The composition root: one API client, one in-memory token store and the view models of the two screens.
/// The session decides which screen shows.
@MainActor
struct RootView: View {
    @State private var session: SessionModel
    @State private var signInViewModel: SignInViewModel
    @State private var profileViewModel: ProfileViewModel

    init() {
        let session = SessionModel()
        let client = URLSessionAPIClient()
        let tokenStore = InMemoryTokenStore()
        _session = State(wrappedValue: session)
        _signInViewModel = State(wrappedValue: SignInViewModel(client: client, tokenStore: tokenStore, session: session))
        _profileViewModel = State(wrappedValue: ProfileViewModel(client: client, tokenStore: tokenStore, session: session))
    }

    var body: some View {
        if session.isSignedIn {
            ProfileView(viewModel: profileViewModel)
        } else {
            SignInView(viewModel: signInViewModel, notice: session.notice)
        }
    }
}
