import XCTest
@testable import KanjoCore

final class FirstScanHintTests: KanjoTestCase {
    func testNoReportUnderThresholdReturnsFalse() {
        XCTAssertFalse(FirstScanHint.shouldShow(hasReport: false, elapsed: 0.0))
        XCTAssertFalse(FirstScanHint.shouldShow(hasReport: false, elapsed: 1.0))
        XCTAssertFalse(FirstScanHint.shouldShow(hasReport: false, elapsed: 2.5))
        XCTAssertFalse(FirstScanHint.shouldShow(hasReport: false, elapsed: 2.999))
        XCTAssertFalse(FirstScanHint.shouldShow(report: nil, elapsed: 2.999))
    }

    func testNoReportAtOrAboveThresholdReturnsTrue() {
        XCTAssertTrue(FirstScanHint.shouldShow(hasReport: false, elapsed: 3.0))
        XCTAssertTrue(FirstScanHint.shouldShow(hasReport: false, elapsed: 3.001))
        XCTAssertTrue(FirstScanHint.shouldShow(hasReport: false, elapsed: 5.0))
        XCTAssertTrue(FirstScanHint.shouldShow(hasReport: false, elapsed: 12.0))
        XCTAssertTrue(FirstScanHint.shouldShow(hasReport: false, elapsed: 30.0))
        XCTAssertTrue(FirstScanHint.shouldShow(report: nil, elapsed: 3.0))
        XCTAssertTrue(FirstScanHint.shouldShow(report: nil, elapsed: 12.0))
    }

    func testReportPresentReturnsFalseRegardlessOfElapsed() {
        XCTAssertFalse(FirstScanHint.shouldShow(hasReport: true, elapsed: 0.0))
        XCTAssertFalse(FirstScanHint.shouldShow(hasReport: true, elapsed: 2.9))
        XCTAssertFalse(FirstScanHint.shouldShow(hasReport: true, elapsed: 3.0))
        XCTAssertFalse(FirstScanHint.shouldShow(hasReport: true, elapsed: 12.0))
        XCTAssertFalse(FirstScanHint.shouldShow(hasReport: true, elapsed: 30.0))
        XCTAssertFalse(FirstScanHint.shouldShow(hasReport: true, elapsed: 100.0))
    }

    func testReportOptionalOverload() throws {
        let reportData = try Data(contentsOf: DefaultPaths.sampleFixture)
        let report = try ReportDecoder.decode(reportData)

        XCTAssertTrue(FirstScanHint.shouldShow(report: nil, elapsed: 3.0))
        XCTAssertFalse(FirstScanHint.shouldShow(report: nil, elapsed: 2.9))
        XCTAssertFalse(FirstScanHint.shouldShow(report: report, elapsed: 3.0))
        XCTAssertFalse(FirstScanHint.shouldShow(report: report, elapsed: 30.0))
    }

    func testNegativeElapsedReturnsFalse() {
        XCTAssertFalse(FirstScanHint.shouldShow(hasReport: false, elapsed: -0.5))
        XCTAssertFalse(FirstScanHint.shouldShow(hasReport: false, elapsed: -5.0))
    }

    func testAliasesAndAlternativeSignatures() {
        XCTAssertTrue(FirstRunHint.shouldShow(hasReport: false, elapsed: 3.0))
        XCTAssertFalse(FirstRunHint.shouldShow(hasReport: true, elapsed: 3.0))
        XCTAssertTrue(FirstRunHint.shouldShowHint(hasReport: false, elapsed: 3.0))
        XCTAssertFalse(FirstRunHint.shouldShowHint(hasReport: true, elapsed: 3.0))
        XCTAssertTrue(FirstScanHint.shouldShowHint(hasReport: false, elapsed: 3.0))
        XCTAssertFalse(FirstScanHint.shouldShowHint(hasReport: true, elapsed: 3.0))
        XCTAssertTrue(FirstScanHint.shouldShow(hasReport: false, elapsedSeconds: 3.0))
        XCTAssertFalse(FirstScanHint.shouldShow(hasReport: true, elapsedSeconds: 3.0))

        XCTAssertTrue(shouldShowFirstScanHint(hasReport: false, elapsed: 3.0))
        XCTAssertFalse(shouldShowFirstScanHint(hasReport: true, elapsed: 3.0))
        XCTAssertTrue(shouldShowFirstRunHint(hasReport: false, elapsed: 3.0))
        XCTAssertFalse(shouldShowFirstRunHint(hasReport: true, elapsed: 3.0))
    }

    func testExplanationLocalization() {
        XCTAssertEqual(
            FirstScanHint.explanation(language: "zh-Hans"),
            "首次运行要读取所有 AI 工具的日志，大约需要半分钟；之后每次刷新只要几秒。"
        )
        XCTAssertEqual(
            FirstScanHint.explanation(language: "en"),
            "First run reads every AI tool's logs and takes about half a minute; later refreshes take a few seconds."
        )
        XCTAssertEqual(
            FirstScanHint.explanation(language: "fr"),
            "Le premier lancement lit les journaux de tous les outils IA (environ 30 s) ; ensuite, quelques secondes."
        )
    }

    func testElapsedFormatting() {
        XCTAssertEqual(FirstScanHint.elapsedText(seconds: 12, language: "zh-Hans"), "已用 12 秒")
        XCTAssertEqual(FirstScanHint.elapsedText(seconds: 12, language: "en"), "12 s elapsed")
        XCTAssertEqual(FirstScanHint.elapsedText(seconds: 12, language: "fr"), "12 s écoulées")

        XCTAssertEqual(FirstScanHint.elapsedText(seconds: 3, language: "zh-Hans"), "已用 3 秒")
        XCTAssertEqual(FirstScanHint.elapsedText(seconds: 3, language: "en"), "3 s elapsed")
        XCTAssertEqual(FirstScanHint.elapsedText(seconds: 3, language: "fr"), "3 s écoulées")

        XCTAssertEqual(FirstScanHint.elapsedText(elapsed: 12.8, language: "en"), "12 s elapsed")
        XCTAssertEqual(FirstScanHint.elapsedText(elapsed: 12.8, language: "zh-Hans"), "已用 12 秒")
        XCTAssertEqual(FirstScanHint.elapsedText(elapsed: 12.8, language: "fr"), "12 s écoulées")
    }
}
