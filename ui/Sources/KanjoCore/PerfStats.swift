import Foundation

/// 单个时间段 / 筛选条件下的生成性能汇总（输出速度 + TTFT 中位数）。
public struct PerfSummary: Equatable, Sendable {
    public var outputTokens: Int
    public var genSeconds: Double
    public var sampleCount: Int
    public var ttftHistogram: [Int: Int]

    public init(outputTokens: Int, genSeconds: Double, sampleCount: Int, ttftHistogram: [Int: Int] = [:]) {
        self.outputTokens = outputTokens
        self.genSeconds = genSeconds
        self.sampleCount = sampleCount
        self.ttftHistogram = ttftHistogram
    }

    /// 平均输出速度（tok/s）：Σo / Σg。无有效样本时为 nil。
    public var tps: Double? {
        guard sampleCount > 0, genSeconds > 0 else { return nil }
        let v = Double(outputTokens) / genSeconds
        return v.isFinite ? v : nil
    }

    /// TTFT 直方图样本数。
    public var ttftSampleCount: Int {
        ttftHistogram.values.reduce(0, +)
    }

    /// TTFT 中位数（秒）：桶内线性插值；无 TTFT 样本时为 nil。
    public var ttftMedian: Double? {
        PerfStats.ttftMedian(histogram: ttftHistogram)
    }
}

/// 生成性能统计的纯计算逻辑（与 Tokei `_perf_ttft_bucket` / `_perf_ttft_median` 一致）。
public enum PerfStats {
    public static let ttftBase: Double = 0.05
    public static let ttftRatio: Double = 1.05

    /// 秒数 → TTFT 桶索引（第 0 桶为 [0, 0.05)，第 k ≥ 1 桶为 [0.05·1.05^(k-1), 0.05·1.05^k)）。
    public static func ttftBucket(for seconds: Double) -> Int {
        if seconds < ttftBase {
            return 0
        }
        return Int(floor(log(seconds / ttftBase) / log(ttftRatio))) + 1
    }

    /// TTFT 桶索引 → 半开区间上下界 [low, high)。
    public static func ttftBounds(for bucket: Int) -> (low: Double, high: Double) {
        if bucket <= 0 {
            return (0.0, ttftBase)
        }
        let low = ttftBase * pow(ttftRatio, Double(bucket - 1))
        let high = ttftBase * pow(ttftRatio, Double(bucket))
        return (low, high)
    }

    /// 按直方图计算 TTFT 中位数（桶内线性插值；偶数个样本取中间两个秩的均值）。
    public static func ttftMedian(histogram: [Int: Int]) -> Double? {
        let buckets = histogram
            .filter { $0.value > 0 }
            .sorted { $0.key < $1.key }
        let total = buckets.reduce(0) { $0 + $1.value }
        guard total > 0 else { return nil }

        func atRank(_ rank: Int) -> Double {
            var seen = 0
            for (bucket, count) in buckets {
                if seen + count >= rank {
                    let (low, high) = ttftBounds(for: bucket)
                    return low + (high - low) * ((Double(rank - seen) - 0.5) / Double(count))
                }
                seen += count
            }
            return 0
        }

        let lowRank = (total + 1) / 2
        let highRank = (total + 2) / 2
        return (atRank(lowRank) + atRank(highRank)) / 2.0
    }

    /// 按 RangeSpec 与可选 agent / model 过滤 `perf_by_day`。
    /// 日期按报告日历下的 `[dayStart, dayEnd)` 与对应 agent 的有效区间相交判断。
    public static func filter(
        _ rows: [PerfDay]?,
        range spec: RangeSpec,
        agent: String? = nil,
        model: String? = nil
    ) -> [PerfDay] {
        guard let rows, !rows.isEmpty else { return [] }
        return rows.filter { row in
            if let agent, row.agent != agent { return false }
            if let model, row.model != model { return false }
            if spec.isAll { return true }
            guard let d0 = HeatStrip.parseDay(row.day, calendar: spec.calendar),
                  let d1 = spec.calendar.date(byAdding: .day, value: 1, to: d0) else {
                return false
            }
            return spec.includes(dayStart: d0, dayEnd: d1, agent: row.agent)
        }
    }

    /// 将一组 `PerfDay` 合并成一个 `PerfSummary`；无有效样本时返回 nil。
    public static func merge(_ rows: [PerfDay]) -> PerfSummary? {
        var o = 0
        var g = 0.0
        var n = 0
        var hist: [Int: Int] = [:]

        for row in rows {
            guard row.n > 0 || row.o > 0 || row.g > 0 else { continue }
            o += row.o
            g += row.g
            n += row.n
            for (k, count) in row.th where count > 0 {
                if let bucket = Int(k) {
                    hist[bucket, default: 0] += count
                }
            }
        }

        guard n > 0, g > 0 else { return nil }
        return PerfSummary(outputTokens: o, genSeconds: g, sampleCount: n, ttftHistogram: hist)
    }

    /// 过滤并合并指定 range / agent / model 的性能统计。
    public static func summarize(
        _ rows: [PerfDay]?,
        range spec: RangeSpec,
        agent: String? = nil,
        model: String? = nil
    ) -> PerfSummary? {
        merge(filter(rows, range: spec, agent: agent, model: model))
    }

    /// 按模型分组汇总指定 agent 在范围内的性能统计（key 为模型 id）。
    public static func byModel(
        _ rows: [PerfDay]?,
        range spec: RangeSpec,
        agent: String
    ) -> [String: PerfSummary] {
        let filtered = filter(rows, range: spec, agent: agent)
        var grouped: [String: [PerfDay]] = [:]
        for row in filtered {
            grouped[row.model, default: []].append(row)
        }
        var out: [String: PerfSummary] = [:]
        for (model, entries) in grouped {
            if let summary = merge(entries) {
                out[model] = summary
            }
        }
        return out
    }

    /// 格式化输出速度（如 `54.2`），无值时返回 `"—"`。
    public static func formatSpeedNumber(_ tps: Double?) -> String {
        guard let tps, tps.isFinite else { return "—" }
        return String(format: "%.1f", locale: Locale(identifier: "en_US_POSIX"), tps)
    }

    /// 格式化 TTFT 中位数（`< 1s` 显示毫秒如 `420 ms`，其余显示秒如 `1.24s`），无值时返回 `"—"`。
    public static func formatTTFT(_ seconds: Double?) -> String {
        guard let seconds, seconds.isFinite, seconds >= 0 else { return "—" }
        let ms = Int((seconds * 1000).rounded())
        if ms < 1000 {
            return "\(ms) ms"
        }
        return String(format: "%.2fs", locale: Locale(identifier: "en_US_POSIX"), seconds)
    }
}
