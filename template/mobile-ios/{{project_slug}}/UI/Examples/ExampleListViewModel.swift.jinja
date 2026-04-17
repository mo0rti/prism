import Foundation
import Observation

enum ExampleListViewState: Equatable {
    case idle
    case loading
    case success
    case error(String)
}

@MainActor
@Observable
final class ExampleListViewModel {
    var viewState: ExampleListViewState = .idle
    var examples: [ExampleResponse] = []
    var currentPage: Int = 0
    var totalPages: Int = 0
    var isLoadingMore: Bool = false

    private let exampleRepository: ExampleRepository
    private let authRepository: AuthRepository

    init(exampleRepository: ExampleRepository, authRepository: AuthRepository) {
        self.exampleRepository = exampleRepository
        self.authRepository = authRepository
    }

    private func shouldDeferToAuthGate(for error: Error) -> Bool {
        guard case APIError.unauthorized = error else { return false }
        viewState = .idle
        return true
    }

    func loadExamples() async {
        viewState = .loading
        do {
            let response = try await exampleRepository.list(page: 0, size: 20)
            examples = response.content
            currentPage = response.page
            totalPages = response.totalPages
            viewState = .success
        } catch {
            if shouldDeferToAuthGate(for: error) { return }
            viewState = .error(error.localizedDescription)
        }
    }

    func loadMore() async {
        guard !isLoadingMore, currentPage + 1 < totalPages else { return }
        isLoadingMore = true
        defer { isLoadingMore = false }
        do {
            let response = try await exampleRepository.list(page: currentPage + 1, size: 20)
            examples.append(contentsOf: response.content)
            currentPage = response.page
            totalPages = response.totalPages
        } catch {
            if shouldDeferToAuthGate(for: error) { return }
            // Silently fail on load more
        }
    }

    func deleteExample(_ id: String) async {
        do {
            try await exampleRepository.delete(id)
            examples.removeAll { $0.id == id }
        } catch {
            if shouldDeferToAuthGate(for: error) { return }
            // Show error via snackbar if needed
        }
    }

    func logout() async {
        await authRepository.logout()
        viewState = .idle
    }
}
