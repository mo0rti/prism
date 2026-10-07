import XCTest

final class SignInUITests: XCTestCase {
    // Simulators on shared CI runners can take tens of seconds to settle a screen.
    private let screenTimeout: TimeInterval = 30

    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    private func element(_ identifier: String, in app: XCUIApplication) -> XCUIElement {
        app.descendants(matching: .any)[identifier]
    }

    private func waitUntilHittable(_ element: XCUIElement, timeout: TimeInterval) -> Bool {
        let hittable = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == true AND hittable == true"), object: element)
        return XCTWaiter().wait(for: [hittable], timeout: timeout) == .completed
    }

    func testLaunchShowsTheLocalDevelopmentSignIn() {
        let app = XCUIApplication()
        app.launch()

        let title = element("signin.title", in: app)
        XCTAssertTrue(title.waitForExistence(timeout: screenTimeout))
        XCTAssertEqual(title.label, "Local development sign-in")

        let submit = app.buttons["signin.submit"]
        XCTAssertTrue(waitUntilHittable(submit, timeout: screenTimeout))
        XCTAssertEqual(submit.label, "Sign in")
    }
}
