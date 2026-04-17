import SwiftUI
import UIKit

// Design tokens from shared/design-tokens/tokens.json
extension Color {
    // Primary
    static let appPrimary = Color(dynamicLight: "#6366F1", dark: "#818CF8")
    static let appPrimaryVariant = Color(dynamicLight: "#4F46E5", dark: "#6366F1")

    // Secondary
    static let appSecondary = Color(dynamicLight: "#10B981", dark: "#34D399")
    static let appSecondaryVariant = Color(dynamicLight: "#059669", dark: "#10B981")

    // Background & Surface
    static let appBackground = Color(dynamicLight: "#FFFFFF", dark: "#111827")
    static let appSurface = Color(dynamicLight: "#F9FAFB", dark: "#1F2937")
    static let appSurfaceVariant = Color(dynamicLight: "#F3F4F6", dark: "#374151")

    // Semantic
    static let appError = Color(dynamicLight: "#EF4444", dark: "#F87171")
    static let appWarning = Color(dynamicLight: "#F59E0B", dark: "#FBBF24")
    static let appSuccess = Color(dynamicLight: "#10B981", dark: "#34D399")
    static let appInfo = Color(dynamicLight: "#3B82F6", dark: "#60A5FA")

    // On colors
    static let appOnPrimary = Color(dynamicLight: "#FFFFFF", dark: "#FFFFFF")
    static let appOnBackground = Color(dynamicLight: "#111827", dark: "#F9FAFB")
    static let appOnSurface = Color(dynamicLight: "#374151", dark: "#E5E7EB")

    // Border
    static let appBorder = Color(dynamicLight: "#E5E7EB", dark: "#374151")

}

extension Color {
    init(hex: String) {
        self.init(uiColor: UIColor(hex: hex) ?? .clear)
    }

    init(dynamicLight lightHex: String, dark darkHex: String) {
        self.init(
            uiColor: UIColor { traitCollection in
                let hex = traitCollection.userInterfaceStyle == .dark ? darkHex : lightHex
                return UIColor(hex: hex) ?? .clear
            }
        )
    }
}

private extension UIColor {
    convenience init?(hex: String) {
        let trimmedHex = hex.trimmingCharacters(in: CharacterSet(charactersIn: "#"))
        let scanner = Scanner(string: trimmedHex)
        var rgbValue: UInt64 = 0

        guard scanner.scanHexInt64(&rgbValue) else { return nil }

        let r = CGFloat((rgbValue & 0xFF0000) >> 16) / 255
        let g = CGFloat((rgbValue & 0x00FF00) >> 8) / 255
        let b = CGFloat(rgbValue & 0x0000FF) / 255

        self.init(red: r, green: g, blue: b, alpha: 1)
    }
}

// Spacing constants from design tokens
enum Spacing {
    static let xs: CGFloat = 4
    static let sm: CGFloat = 8
    static let md: CGFloat = 16
    static let lg: CGFloat = 24
    static let xl: CGFloat = 32
    static let xxl: CGFloat = 48
    static let xxxl: CGFloat = 64
}

enum CornerRadius {
    static let sm: CGFloat = 4
    static let md: CGFloat = 8
    static let lg: CGFloat = 16
    static let xl: CGFloat = 24
}
