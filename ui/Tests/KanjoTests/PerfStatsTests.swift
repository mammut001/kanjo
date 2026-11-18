import XCTest
@testable import KanjoCore

final class PerfStatsTests: KanjoTestCase {
    func testTTFTBucketAndBounds() {
        // 第 0 桶：[0, 0.05)
        XCTAssertEqual(PerfStats.ttftBucket(for: 0.0), 0)
        XCTAssertEqual(PerfStats.ttftBucket(for: 0.049), 0)
        let b0 = PerfStats.ttftBounds(for: 0)
        XCTAssertEqual(b0.low, 0.0, accuracy: 1e-12)
        XCTAssertEqual(b0.high, 0.05, accuracy: 1e-12)

        // 边界 0.05 落入第 1 桶：[0.05, 0.0525)
        XCTAssertEqual(PerfStats.ttftBucket(for: 0.05), 1)
        let b1 = PerfStats.ttftBounds(for: 1)
        XCTAssertEqual(b1.low, 0.05, accuracy: 1e-12)
        XCTAssertEqual(b1.high, 0.0525, accuracy: 1e-12)

        // 第 2 桶：[0.0525, 0.055125)
        XCTAssertEqual(PerfStats.ttftBucket(for: 0.053), 2)
        let b2 = PerfStats.ttftBounds(for: 2)
        XCTAssertEqual(b2.low, 0.05 * 1.05, accuracy: 1e-12)
        XCTAssertEqual(b2.high, 0.05 * 1.05 * 1.05, accuracy: 1e-12)
    }

    func testTTFTMedianEmptyReturnsNil() {
        XCTAssertNil(PerfStats.ttftMedian(histogram: [:]))
        XCTAssertNil(PerfStats.ttftMedian(histogram: [0: 0, 5: 0]))
    }

    func testTTFTMedianOddCountSingleAndMultiBucket() {
        // 单桶 3 个样本：中位秩 = 2 -> (2 - 0.5)/3 = 0.5，落在桶 0 [0, 0.05) 中点 0.025
        let m1 = PerfStats.ttftMedian(histogram: [0: 3])
        XCTAssertEqual(try! XCTUnwrap(m1), 0.025, accuracy: 1e-9)

        // 多桶 5 个样本：桶 0(2), 桶 1(2), 桶 2(1)；第 3 个样本在桶 1 的第 1 个 -> 0.05 + 0.0025 * (0.5/2)
        let m2 = PerfStats.ttftMedian(histogram: [0: 2, 1: 2, 2: 1])
        let b1 = PerfStats.ttftBounds(for: 1)
        let expected = b1.low + (b1.high - b1.low) * (0.5 / 2.0)
        XCTAssertEqual(try! XCTUnwrap(m2), expected, accuracy: 1e-9)
    }

    func testTTFTMedianEvenCountAcrossBuckets() {
        // 偶数 2 个样本分跨桶 0 和桶 1：中位秩 1 和 2
        let m = PerfStats.ttftMedian(histogram: [0: 1, 1: 1])
        let b0 = PerfStats.ttftBounds(for: 0)
        let b1 = PerfStats.ttftBounds(for: 1)
        let r1 = b0.low + (b0.high - b0.low) * 0.5
        let r2 = b1.low + (b1.high - b1.low) * 0.5
        XCTAssertEqual(try! XCTUnwrap(m), (r1 + r2) / 2.0, accuracy: 1e-9)
    }

    func testMergeAndEmpty() {
        XCTAssertNil(PerfStats.merge([]))
        XCTAssertNil(PerfStats.merge([PerfDay(day: "2026-11-17", agent: "claude", model: "opus", o: 0, g: 0, n: 0, th: [:])]))

        let r1 = PerfDay(day: "2026-11-16", agent: "claude", model: "opus", o: 1000, g: 10.0, n: 2, th: ["0": 1])
        let r2 = PerfDay(day: "2026-11-17", agent: "claude", model: "opus", o: 2000, g: 20.0, n: 3, th: ["0": 1, "1": 1])
        let merged = try! XCTUnwrap(PerfStats.merge([r1, r2]))
        XCTAssertEqual(merged.outputTokens, 3000)
        XCTAssertEqual(merged.genSeconds, 30.0, accuracy: 1e-9)
        XCTAssertEqual(merged.sampleCount, 5)
        XCTAssertEqual(try! XCTUnwrap(merged.tps), 100.0, accuracy: 1e-9)
        XCTAssertEqual(merged.ttftSampleCount, 3)
        XCTAssertEqual(merged.ttftHistogram, [0: 2, 1: 1])
    }

    func testRangeFilteringByAgentStart() {
        let tz = TimeZone(identifier: "Asia/Shanghai")!
        let cal = RangeEngine.calendar(timezone: tz)
        let claudeStart = ReportDates.parseTimestamp("2026-11-15T16:00:00Z")! // 2026-11-16 00:00 +0800
        let codexStart = ReportDates.parseTimestamp("2026-11-16T16:00:00Z")!  // 2026-11-17 00:00 +0800
        let end = ReportDates.parseTimestamp("2026-11-18T00:00:00Z")!

        let spec = RangeSpec(
            range: .sinceReset,
            calendar: cal,
            end: end,
            agentStarts: ["claude": claudeStart, "codex": codexStart]
        )

        let rows = [
            PerfDay(day: "2026-11-15", agent: "claude", model: "opus", o: 500, g: 5.0, n: 1),
            PerfDay(day: "2026-11-16", agent: "claude", model: "opus", o: 1000, g: 10.0, n: 2),
            PerfDay(day: "2026-11-16", agent: "codex", model: "gpt", o: 800, g: 8.0, n: 2),
            PerfDay(day: "2026-11-17", agent: "codex", model: "gpt", o: 1200, g: 12.0, n: 3),
            PerfDay(day: "2026-11-17", agent: "grok", model: "grok-4", o: 900, g: 9.0, n: 2),
        ]

        let claudePerf = PerfStats.summarize(rows, range: spec, agent: "claude")
        XCTAssertEqual(claudePerf?.outputTokens, 1000)
        XCTAssertEqual(claudePerf?.sampleCount, 2)

        let codexPerf = PerfStats.summarize(rows, range: spec, agent: "codex")
        XCTAssertEqual(codexPerf?.outputTokens, 1200)
        XCTAssertEqual(codexPerf?.sampleCount, 3)

        // 没有 reset 起点的 agent 在 sinceReset 下被过滤掉
        let grokPerf = PerfStats.summarize(rows, range: spec, agent: "grok")
        XCTAssertNil(grokPerf)
    }
}
