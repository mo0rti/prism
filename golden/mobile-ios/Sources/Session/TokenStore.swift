/// Where the signed-in session keeps its bearer token.
///
/// The slice keeps the token in memory only: it lives as long as the app process and is gone after a restart,
/// which suits a short-lived development token. A real identity provider's tokens belong in the Keychain;
/// add a `TokenStore` of that kind and inject it in `RootView` (see the `ios-contract-alignment` skill).
/// Nothing in the app logs, prints or persists the token.
protocol TokenStore: Sendable {
    func token() async -> String?
    func save(_ token: String) async
    func clear() async
}

actor InMemoryTokenStore: TokenStore {
    private var current: String?

    init(token: String? = nil) {
        current = token
    }

    func token() async -> String? {
        current
    }

    func save(_ token: String) async {
        current = token
    }

    func clear() async {
        current = nil
    }
}
