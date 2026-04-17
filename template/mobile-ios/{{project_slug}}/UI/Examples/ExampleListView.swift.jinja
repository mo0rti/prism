import SwiftUI

struct ExampleListView: View {
    @Bindable var viewModel: ExampleListViewModel

    var body: some View {
        Group {
            switch viewModel.viewState {
            case .idle, .loading:
                LoadingView()
            case .error(let message):
                ErrorView(message: message) {
                    Task { await viewModel.loadExamples() }
                }
            case .success:
                listContent
            }
        }
        .navigationTitle("Examples")
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button {
                    Task { await viewModel.logout() }
                } label: {
                    Image(systemName: "rectangle.portrait.and.arrow.right")
                }
                .accessibilityIdentifier("examples.logout")
            }
        }
        .task {
            if viewModel.viewState == .idle {
                await viewModel.loadExamples()
            }
        }
    }

    private var listContent: some View {
        Group {
            if viewModel.examples.isEmpty {
                VStack {
                    ContentUnavailableView(
                        "No examples yet",
                        systemImage: "tray",
                        description: Text("Create or import an example to get started.")
                    )
                    .accessibilityIdentifier("examples.empty")
                }
            } else {
                ZStack {
                    List {
                        ForEach(viewModel.examples) { example in
                            ExampleRow(example: example)
                                .swipeActions(edge: .trailing) {
                                    Button(role: .destructive) {
                                        Task { await viewModel.deleteExample(example.id) }
                                    } label: {
                                        Label("Delete", systemImage: "trash")
                                    }
                                }
                                .onAppear {
                                    if example.id == viewModel.examples.last?.id {
                                        Task { await viewModel.loadMore() }
                                    }
                                }
                        }

                        if viewModel.isLoadingMore {
                            HStack {
                                Spacer()
                                ProgressView()
                                Spacer()
                            }
                        }
                    }
                    .listStyle(.plain)
                    .accessibilityIdentifier("examples.list")
                }
            }
        }
    }
}

private struct ExampleRow: View {
    let example: ExampleResponse

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            Text(example.title)
                .font(.headline)
                .accessibilityIdentifier("examples.row.title.\(example.id)")
            if let description = example.description {
                Text(description)
                    .font(.subheadline)
                    .foregroundColor(.secondary)
                    .lineLimit(2)
            }
            Text(example.status)
                .font(.caption)
                .padding(.horizontal, Spacing.sm)
                .padding(.vertical, Spacing.xs)
                .background(Color.appSurfaceVariant)
                .cornerRadius(CornerRadius.sm)
        }
        .padding(.vertical, Spacing.xs)
        .accessibilityIdentifier("examples.row.\(example.id)")
    }
}
