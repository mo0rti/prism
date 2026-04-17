import XCTest

final class AppFlowUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    private func element(_ identifier: String, in app: XCUIApplication) -> XCUIElement {
        app.descendants(matching: .any)[identifier]
    }

    private func launchApp(authState: String) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchEnvironment["UI_TEST_MODE"] = "1"
        app.launchEnvironment["UI_TEST_AUTH_STATE"] = authState
        app.launch()
        return app
    }

    // TODO: Restore password-form UI coverage once SwiftUI exposes the generated
    // login controls reliably enough for template-level XCUITest automation.

    func testUnauthenticatedLaunchShowsLoginScreen() {
        let app = launchApp(authState: "unauthenticated")

        XCTAssertTrue(element("login.screen", in: app).waitForExistence(timeout: 10))
    }

    func testAuthenticatedLaunchShowsExamplesAndLogoutReturnsToLogin() {
        let app = launchApp(authState: "authenticated")

        XCTAssertTrue(element("examples.screen", in: app).waitForExistence(timeout: 10))

        let logoutButton = app.buttons.matching(identifier: "examples.logout").firstMatch
        XCTAssertTrue(logoutButton.waitForExistence(timeout: 10))
        logoutButton.tap()

        XCTAssertTrue(element("login.screen", in: app).waitForExistence(timeout: 10))
    }
}
