import XCTest
@testable import KanjoCore

final class PythonCheckTests: KanjoTestCase {
    func testMissingToolsDiagnostic() {
        XCTAssertTrue(PythonCheck.needsCommandLineTools(status: 1, stderr: "xcode-select: note: no developer tools were found"))
        XCTAssertTrue(PythonCheck.needsCommandLineTools(status: 72, stderr: "Install Command Line Tools"))
        XCTAssertTrue(PythonCheck.needsCommandLineTools(status: 1, stderr: "COMMAND LINE TOOLS missing"))
        XCTAssertFalse(PythonCheck.needsCommandLineTools(status: 0, stderr: "xcode-select"))
        XCTAssertFalse(PythonCheck.needsCommandLineTools(status: 1, stderr: "python3: command not found"))
        XCTAssertFalse(PythonCheck.needsCommandLineTools(status: 1, stderr: "Traceback: invalid data"))
        XCTAssertFalse(PythonCheck.needsCommandLineTools(status: 1, stderr: ""))
    }
}
