import Foundation

enum HTTPMethod: String, Sendable {
    case get = "GET"
    case post = "POST"
}

/// One operation of `shared/api-contracts/openapi.yml`: its path, its method and whether it needs a bearer token.
/// A path here that the contract lacks fails the contract check of the template validation.
struct APIEndpoint: Sendable {
    let path: String
    let method: HTTPMethod
    let requiresAuth: Bool

    /// `createDevToken`: the backend's local development identity. It needs no token to ask for one.
    static let createDevToken = APIEndpoint(path: "/api/dev-identity/token", method: .post, requiresAuth: false)

    /// `getMe`: the profile of the signed-in user.
    static let getMe = APIEndpoint(path: "/api/me", method: .get, requiresAuth: true)
}
