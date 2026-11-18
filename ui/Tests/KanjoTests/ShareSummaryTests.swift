import XCTest
@testable import KanjoCore

final class ShareSummaryTests: KanjoTestCase {
    func testBuild() throws {
        let bundle = Bundle(for: type(of: self))
        let path = bundle.path(forResource: "sample", ofType: "json", inDirectory: "fixtures")!
        let data = try Data(contentsOf: URL(fileURLWithPath: path))
        let report = try JSONDecoder().decode(UsageReport.self, from: data)
        let spec = RangeEngine.defaultSpec(report: report)
        let filtered = RangeEngine.filtered(report, range: spec)
        
        let summary = ShareSummary.build(report: report, rangeSpec: spec)
        
        XCTAssertEqual(summary.totals.tokens, filtered.tokens)
        XCTAssertEqual(summary.totals.cost, filtered.cost, accuracy: 0.01)
    }
}
