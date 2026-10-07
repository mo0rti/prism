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

    /// Whether the build may call a backend over plain `http`: a Debug build only, for the backend on this Mac.
    /// A Release build also has no App Transport Security exception (`Plists/Info.Debug.plist` is Debug only).
    static let allowsCleartext: Bool = {
        #if DEBUG
        return true
        #else
        return false
        #endif
    }()

    /// Joins `baseURL` and `path` with exactly one `/` between them, whether or not either side carries one.
    /// Returns nil when the result has no host, when its scheme is not `https`, or, where `allowsCleartext` is set,
    /// is not `http` either. The app sends a bearer token with every request, so it never sends one in clear text
    /// from a Release build.
    static func make(baseURL: String, path: String, allowsCleartext: Bool = APIURL.allowsCleartext) -> URL? {
        var base = baseURL
        while base.hasSuffix("/") {
            base.removeLast()
        }
        let relativePath = path.hasPrefix("/") ? path : "/" + path

        guard let components = URLComponents(string: base + relativePath),
              let scheme = components.scheme?.lowercased(), !scheme.isEmpty,
              let host = components.host, !host.isEmpty else {
            return nil
        }
        guard scheme == "https" || (allowsCleartext && scheme == "http") else {
            return nil
        }
        return components.url
    }
}
