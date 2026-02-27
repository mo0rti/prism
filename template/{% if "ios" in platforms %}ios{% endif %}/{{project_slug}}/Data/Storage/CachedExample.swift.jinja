import Foundation
import SwiftData

@Model
final class CachedExample {
    @Attribute(.unique) var id: String
    var title: String
    var descriptionText: String?
    var status: String
    var createdBy: String
    var createdAt: String
    var updatedAt: String
    var cachedAt: Date

    init(
        id: String,
        title: String,
        descriptionText: String? = nil,
        status: String,
        createdBy: String,
        createdAt: String,
        updatedAt: String,
        cachedAt: Date = .now
    ) {
        self.id = id
        self.title = title
        self.descriptionText = descriptionText
        self.status = status
        self.createdBy = createdBy
        self.createdAt = createdAt
        self.updatedAt = updatedAt
        self.cachedAt = cachedAt
    }

    /// Convert from API response
    static func from(_ response: ExampleResponse) -> CachedExample {
        CachedExample(
            id: response.id,
            title: response.title,
            descriptionText: response.description,
            status: response.status,
            createdBy: response.createdBy,
            createdAt: response.createdAt,
            updatedAt: response.updatedAt
        )
    }

    /// Convert to API response format
    func toResponse() -> ExampleResponse {
        ExampleResponse(
            id: id,
            title: title,
            description: descriptionText,
            status: status,
            createdBy: createdBy,
            createdAt: createdAt,
            updatedAt: updatedAt
        )
    }
}
