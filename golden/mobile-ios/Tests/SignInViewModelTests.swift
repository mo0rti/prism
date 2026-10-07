import XCTest
@testable import MobileIos

final class SignInViewModelTests: XCTestCase {
    @MainActor
    private func makeSUT() -> (viewModel: SignInViewModel, client: FakeAPIClient, tokenStore: InMemoryTokenStore, session: SessionModel) {
        let client = FakeAPIClient()
        let tokenStore = InMemoryTokenStore()
        let session = SessionModel()
        let viewModel = SignInViewModel(client: client, tokenStore: tokenStore, session: session)
        return (viewModel, client, tokenStore, session)
    }

    @MainActor
    func testStartsIdleAndSignedOut() {
        let (viewModel, _, _, session) = makeSUT()

        XCTAssertEqual(viewModel.state, .idle)
        XCTAssertFalse(viewModel.isSigningIn)
        XCTAssertFalse(session.isSignedIn)
    }

    @MainActor
    func testSignInStoresTheTokenAndSignsTheSessionIn() async {
        let (viewModel, client, tokenStore, session) = makeSUT()

        await viewModel.signIn()

        let stored = await tokenStore.token()
        XCTAssertEqual(stored, "dev-token")
        XCTAssertTrue(session.isSignedIn)
        XCTAssertEqual(viewModel.state, .idle)
        XCTAssertEqual(client.tokenRequests.count, 1)
    }

    @MainActor
    func testEmptyFieldsAreNotSent() async {
        let (viewModel, client, _, _) = makeSUT()
        viewModel.email = "   "
        viewModel.displayName = ""

        await viewModel.signIn()

        XCTAssertEqual(client.tokenRequests, [DevTokenRequest(email: nil, displayName: nil)])
    }

    @MainActor
    func testFilledFieldsAreTrimmedAndSent() async {
        let (viewModel, client, _, _) = makeSUT()
        viewModel.email = "  ada@example.test "
        viewModel.displayName = "Ada Lovelace"

        await viewModel.signIn()

        XCTAssertEqual(client.tokenRequests, [DevTokenRequest(email: "ada@example.test", displayName: "Ada Lovelace")])
    }

    @MainActor
    func testABackendWithoutTheDevIdentityKeepsTheSessionSignedOut() async {
        let (viewModel, client, tokenStore, session) = makeSUT()
        client.tokenResult = .failure(.devIdentityUnavailable)

        await viewModel.signIn()

        guard case .failed(let message) = viewModel.state else {
            return XCTFail("Expected a failed state, got \(viewModel.state)")
        }
        XCTAssertTrue(message.contains("local development sign-in"))
        let stored = await tokenStore.token()
        XCTAssertNil(stored)
        XCTAssertFalse(session.isSignedIn)
    }

    @MainActor
    func testARefusedRequestSaysADeviceCannotUseTheDevIdentity() async {
        let (viewModel, client, _, session) = makeSUT()
        client.tokenResult = .failure(.devIdentityRefused)

        await viewModel.signIn()

        guard case .failed(let message) = viewModel.state else {
            return XCTFail("Expected a failed state, got \(viewModel.state)")
        }
        XCTAssertTrue(message.contains("physical device"))
        XCTAssertFalse(session.isSignedIn)
    }

    @MainActor
    func testAFailedSignInCanBeRetried() async {
        let (viewModel, client, _, session) = makeSUT()
        client.tokenResult = .failure(.transport("offline"))
        await viewModel.signIn()
        XCTAssertFalse(session.isSignedIn)

        client.tokenResult = .success(DevTokenResponse(accessToken: "second-token", tokenType: "Bearer", expiresIn: 3600))
        await viewModel.signIn()

        XCTAssertTrue(session.isSignedIn)
        XCTAssertEqual(viewModel.state, .idle)
    }
}
