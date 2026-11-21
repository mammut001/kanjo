import XCTest
@testable import KanjoCore

final class DataOverrideDisplayTests: KanjoTestCase {
    private let fullPath = "/private/tmp/claude-501/-Users-dogecoin-Documents-GitHub-token-usage/ui/fixtures/sample.json"

    func testSnapshotShowsOnlyFileName() {
        XCTAssertEqual(DataOverrideDisplay.path(fullPath, snapshot: true), "sample.json")
    }

    func testNormalRunKeepsFullPath() {
        XCTAssertEqual(DataOverrideDisplay.path(fullPath, snapshot: false), fullPath)
    }
}
