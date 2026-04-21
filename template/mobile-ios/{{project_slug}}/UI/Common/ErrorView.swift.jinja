import SwiftUI

struct ErrorView: View {
    let message: String
    var onRetry: (() -> Void)?

    var body: some View {
        VStack(spacing: Spacing.md) {
            Spacer()
            Image(systemName: "exclamationmark.triangle")
                .font(.largeTitle)
                .foregroundColor(.appError)
                .accessibilityHidden(true)
                .accessibilityIdentifier("error.icon")
            Text(message)
                .font(.body)
                .foregroundColor(.secondary)
                .multilineTextAlignment(.center)
                .accessibilityIdentifier("error.message")
            if let onRetry {
                Button("Retry", action: onRetry)
                    .buttonStyle(.borderedProminent)
                    .accessibilityIdentifier("error.retry")
            }
            Spacer()
        }
        .padding(Spacing.lg)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .accessibilityIdentifier("error.screen")
    }
}

#Preview("Retry") {
    ErrorView(message: "Something went wrong. Please try again.", onRetry: {})
        .background(Color.appBackground)
}

#Preview("Message Only") {
    ErrorView(message: "No connection available right now.", onRetry: nil)
        .background(Color.appBackground)
}
