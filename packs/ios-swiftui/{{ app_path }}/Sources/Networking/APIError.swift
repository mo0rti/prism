import Foundation

/// What can go wrong between the app and the backend. The messages are shown to the person using the app and never carry a token.
enum APIError: Error, Equatable, Sendable {
    case notConfigured
    case invalidResponse
    case badRequest(String)
    case unauthorized
    case forbidden
    /// `POST /api/dev-identity/token` answered 404: the backend does not run its `local` profile.
    case devIdentityUnavailable
    /// `POST /api/dev-identity/token` answered 403: the request did not come from the backend's own machine.
    case devIdentityRefused
    case server(Int)
    case decoding
    case transport(String)
}

extension APIError: LocalizedError {
    var errorDescription: String? {
        switch self {
        case .notConfigured:
            return "The backend address is not set. Set API_BASE_URL in project.yml and generate the Xcode project again."
        case .invalidResponse:
            return "The backend sent a response the app could not read."
        case .badRequest(let message):
            return message
        case .unauthorized:
            return "The backend did not accept the sign-in. Sign in again."
        case .forbidden:
            return "The backend refused the request."
        case .devIdentityUnavailable:
            return "The backend offers no local development sign-in. Start it with its local profile."
        case .devIdentityRefused:
            return "The backend offers the local development sign-in only to the Mac it runs on. A physical device cannot use it."
        case .server(let status):
            return "The backend answered with an error (\(status))."
        case .decoding:
            return "The backend response did not match the API contract."
        case .transport(let message):
            return "The backend could not be reached: \(message)"
        }
    }
}
