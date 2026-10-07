import Foundation

/// Builds request URLs from the configured base URL and an endpoint path.
enum APIURL {
    /// Reads `API_BASE_URL` from the bundle's Info.plist, which `project.yml` sets per build configuration.
    /// An absent or empty value stays empty, and `make` then returns nil.
    static func configuredBaseURL(bundle: Bundle = .main) -> String {
        guard let value = bundle.object(forInfoDictionaryKey: "API_BASE_URL") as? String else {
            return ""
        }
        return value.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    /// Joins `baseURL` and `path` with exactly one `/` between them, whether or not either side carries one.
    /// Returns nil when the result has no scheme or host.
    static func make(baseURL: String, path: String) -> URL? {
        var base = baseURL
        while base.hasSuffix("/") {
            base.removeLast()
        }
        let relativePath = path.hasPrefix("/") ? path : "/" + path

        guard let components = URLComponents(string: base + relativePath),
              let scheme = components.scheme, !scheme.isEmpty,
              let host = components.host, !host.isEmpty else {
            return nil
        }
        return components.url
    }
}
