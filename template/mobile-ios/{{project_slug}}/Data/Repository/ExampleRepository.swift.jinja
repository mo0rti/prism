import Foundation

protocol ExampleRepository: Sendable {
    func list(page: Int, size: Int) async throws -> ExampleListResponse
    func getById(_ id: String) async throws -> ExampleResponse
    func create(title: String, description: String?) async throws -> ExampleResponse
    func update(id: String, title: String?, description: String?, status: String?) async throws -> ExampleResponse
    func delete(_ id: String) async throws
}

final class ExampleRepositoryImpl: ExampleRepository, Sendable {
    private let apiClient: APIClient

    init(apiClient: APIClient) {
        self.apiClient = apiClient
    }

    func list(page: Int = 0, size: Int = 20) async throws -> ExampleListResponse {
        try await apiClient.request(.listExamples(page: page, size: size))
    }

    func getById(_ id: String) async throws -> ExampleResponse {
        try await apiClient.request(.getExample(id: id))
    }

    func create(title: String, description: String?) async throws -> ExampleResponse {
        let body = CreateExampleRequest(title: title, description: description)
        return try await apiClient.request(.createExample(), body: body)
    }

    func update(id: String, title: String?, description: String?, status: String?) async throws -> ExampleResponse {
        let body = UpdateExampleRequest(title: title, description: description, status: status)
        return try await apiClient.request(.updateExample(id: id), body: body)
    }

    func delete(_ id: String) async throws {
        try await apiClient.requestVoid(.deleteExample(id: id))
    }
}
