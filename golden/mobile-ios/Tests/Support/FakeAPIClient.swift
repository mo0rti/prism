import Foundation
@testable import MobileIos

/// An `APIClient` that answers with the results a test sets and records what the view models asked for.
@MainActor
final class FakeAPIClient: APIClient {
    var tokenResult: Result<DevTokenResponse, APIError> = .success(
        DevTokenResponse(accessToken: "dev-token", tokenType: "Bearer", expiresIn: 3600)
    )
    var profileResult: Result<UserProfile, APIError> = .success(Fixtures.profile)

    private(set) var tokenRequests: [DevTokenRequest] = []
    private(set) var profileTokens: [String] = []

    func createDevToken(_ request: DevTokenRequest) async throws -> DevTokenResponse {
        tokenRequests.append(request)
        return try tokenResult.get()
    }

    func getMe(token: String) async throws -> UserProfile {
        profileTokens.append(token)
        return try profileResult.get()
    }
}

enum Fixtures {
    static let profile = UserProfile(
        id: "7c1d2f64-0000-4000-8000-000000000001",
        displayName: "Local Developer",
        email: "developer@example.test",
        createdAt: "2026-10-07T10:15:30.123456Z"
    )
}
