import Foundation

/// The app's display name and audience, set from this app's answers when Prism generates it (Info.plist).
/// The audience is display text only: no screen, check or permission reads it, and a label never enforces authorization.
enum AppInfo {
    static var displayName: String {
        text(forKey: "CFBundleDisplayName") ?? "App"
    }

    static var audience: String? {
        text(forKey: "PrismAppAudience")
    }

    private static func text(forKey key: String) -> String? {
        guard let value = Bundle.main.object(forInfoDictionaryKey: key) as? String else {
            return nil
        }
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }
}
