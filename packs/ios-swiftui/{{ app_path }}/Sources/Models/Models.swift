import Foundation

/// `DevTokenRequest` of the contract: who the development identity signs in as. Both fields are optional,
/// and a nil field is left out of the JSON body.
struct DevTokenRequest: Encodable, Equatable, Sendable {
    let email: String?
    let displayName: String?

    init(email: String? = nil, displayName: String? = nil) {
        self.email = email
        self.displayName = displayName
    }
}

/// `DevTokenResponse` of the contract.
struct DevTokenResponse: Decodable, Equatable, Sendable {
    let accessToken: String
    let tokenType: String
    let expiresIn: Int
}

/// `UserProfile` of the contract. `createdAt` is an RFC 3339 date-time kept as the backend wrote it,
/// so that any fractional-second precision decodes.
struct UserProfile: Decodable, Equatable, Sendable {
    let id: String
    let displayName: String
    let email: String?
    let createdAt: String
}
