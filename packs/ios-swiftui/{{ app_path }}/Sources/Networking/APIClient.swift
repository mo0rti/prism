import Foundation

/// The two operations of `shared/api-contracts/openapi.yml` that the slice calls.
protocol APIClient: Sendable {
    /// `createDevToken`: `POST /api/dev-identity/token`.
    func createDevToken(_ request: DevTokenRequest) async throws -> DevTokenResponse

    /// `getMe`: `GET /api/me` with the bearer token.
    func getMe(token: String) async throws -> UserProfile
}

/// The client of the running backend, built on `URLSession`.
///
/// Building a request and reading a response are static functions with no network access, so the unit
/// tests cover them directly. The bearer token goes into the `Authorization` header and nowhere else:
/// it is never logged, never put in a URL and never part of an error message.
struct URLSessionAPIClient: APIClient {
    private let baseURL: String

    init(baseURL: String = APIURL.configuredBaseURL()) {
        self.baseURL = baseURL
    }

    func createDevToken(_ request: DevTokenRequest) async throws -> DevTokenResponse {
        let urlRequest = try Self.makeRequest(baseURL: baseURL, endpoint: .createDevToken, token: nil, body: request)
        return try await send(urlRequest, endpoint: .createDevToken)
    }

    func getMe(token: String) async throws -> UserProfile {
        let urlRequest = try Self.makeRequest(baseURL: baseURL, endpoint: .getMe, token: token)
        return try await send(urlRequest, endpoint: .getMe)
    }

    // MARK: - Requests and responses

    /// The request of an endpoint: its URL, its method, the bearer token when the endpoint needs one and the JSON body.
    static func makeRequest(
        baseURL: String,
        endpoint: APIEndpoint,
        token: String?,
        body: (any Encodable)? = nil
    ) throws -> URLRequest {
        guard let url = APIURL.make(baseURL: baseURL, path: endpoint.path) else {
            throw APIError.notConfigured
        }

        var request = URLRequest(url: url)
        request.httpMethod = endpoint.method.rawValue
        request.setValue("application/json", forHTTPHeaderField: "Accept")

        if endpoint.requiresAuth {
            guard let token, !token.isEmpty else {
                throw APIError.unauthorized
            }
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }

        if let body {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONEncoder().encode(body)
        }
        return request
    }

    /// Reads a response: the decoded body of a 2xx answer, otherwise the `APIError` of its status.
    static func decode<Response: Decodable>(
        _ type: Response.Type,
        from data: Data,
        status: Int,
        endpoint: APIEndpoint
    ) throws -> Response {
        switch status {
        case 200...299:
            do {
                return try JSONDecoder().decode(Response.self, from: data)
            } catch {
                throw APIError.decoding
            }
        case 400:
            throw APIError.badRequest(errorMessage(in: data) ?? "The backend rejected the request.")
        case 401:
            throw APIError.unauthorized
        case 403 where endpoint.path == APIEndpoint.createDevToken.path:
            throw APIError.devIdentityRefused
        case 403:
            throw APIError.forbidden
        case 404 where endpoint.path == APIEndpoint.createDevToken.path:
            throw APIError.devIdentityUnavailable
        default:
            throw APIError.server(status)
        }
    }

    private struct ErrorBody: Decodable {
        let message: String
    }

    private static func errorMessage(in data: Data) -> String? {
        (try? JSONDecoder().decode(ErrorBody.self, from: data))?.message
    }

    private func send<Response: Decodable>(_ request: URLRequest, endpoint: APIEndpoint) async throws -> Response {
        let result: (Data, URLResponse)
        do {
            result = try await URLSession.shared.data(for: request)
        } catch {
            throw APIError.transport(error.localizedDescription)
        }
        guard let http = result.1 as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }
        return try Self.decode(Response.self, from: result.0, status: http.statusCode, endpoint: endpoint)
    }
}
