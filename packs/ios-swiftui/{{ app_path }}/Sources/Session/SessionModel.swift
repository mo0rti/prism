import Observation

/// Whether a person is signed in, and the notice the sign-in screen shows after a session ended.
/// `RootView` reads it to choose between the sign-in screen and the profile screen.
@MainActor
@Observable
final class SessionModel {
    private(set) var isSignedIn = false
    private(set) var notice: String?

    func markSignedIn() {
        isSignedIn = true
        notice = nil
    }

    func markSignedOut(notice: String? = nil) {
        isSignedIn = false
        self.notice = notice
    }
}
