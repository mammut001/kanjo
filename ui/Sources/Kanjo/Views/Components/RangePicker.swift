import SwiftUI
import KanjoCore

/// 当前生效的时间范围：存储值 + 报告 → 区间、过滤结果、说明文字。
/// 「Since reset」在报告没有 quota_windows 时不可用，存储值是它也按 All 显示。
struct RangeContext {
    let report: UsageReport
    let range: TimeRange
    let spec: RangeSpec
    let resetAvailable: Bool

    init(report: UsageReport, raw: String, now: Date = Date()) {
        self.report = report
        let available = !(report.quotaWindows ?? [:]).isEmpty
        let wanted = TimeRange(rawValue: raw) ?? .all
        range = (wanted == .sinceReset && !available) ? .all : wanted
        resetAvailable = available
        spec = RangeEngine.spec(range, report: report, now: now)
    }

    var isAll: Bool { range == .all }

    /// 缺 by_day.by_agent / by_agent_tokens 时的回退：项目级主力 agent。
    static func fallbackAgent(_ p: Project) -> String {
        dominantAgent(p.byAgent)?.agent ?? p.byAgent.first?.agent ?? "unknown"
    }

    func filtered() -> FilteredReport {
        RangeEngine.filtered(report, range: spec, fallbackAgentFor: Self.fallbackAgent)
    }

    func filter(_ p: Project) -> FilteredProject {
        RangeEngine.filter(p, range: spec, fallbackAgent: Self.fallbackAgent(p))
    }

    /// 范围说明（All 下为 nil）。
    /// 例：`Last 7 days · Oct 18 – Oct 24`；
    /// `Since Claude reset Oct 20 10:00 · Codex reset Oct 21 08:00 · Antigravity: no reset info`。
    var caption: String? {
        let cal = spec.calendar
        let md = formatter("MMM d", cal), mdt = formatter("MMM d HH:mm", cal)
        switch range {
        case .all:
            return nil
        case .days7, .days30, .lastWeek:
            guard let s = spec.start, let e = spec.end else { return range.longLabel }
            // 区间是半开的：显示的最后一天是 end 前一刻所在的那天。
            let last = e.addingTimeInterval(-1)
            return "\(range.longLabel) · \(md.string(from: s)) – \(md.string(from: last))"
        case .sinceReset:
            let withReset = agentOrder.filter { spec.agentStarts[$0] != nil }
            let without = agentOrder.filter { spec.agentStarts[$0] == nil }
            var parts = withReset.map { "\(shortName($0)) reset \(mdt.string(from: spec.agentStarts[$0]!))" }
            if !parts.isEmpty { parts[0] = "Since " + parts[0] }
            parts += without.map { "\(shortName($0)): no reset info" }
            return parts.joined(separator: " · ")
        }
    }

    /// 报告里出现的 agent（按总花费降序），后面接只在 quota_windows 里出现的。
    var agentOrder: [String] {
        var cost: [String: Double] = [:]
        for p in report.projects { for a in p.byAgent { cost[a.agent, default: 0] += a.cost } }
        let used = cost.sorted { $0.value != $1.value ? $0.value > $1.value : $0.key < $1.key }.map(\.key)
        let extra = (report.quotaWindows ?? [:]).keys.filter { cost[$0] == nil }.sorted()
        return used + extra
    }

    /// "Claude Code" → "Claude"；未知 agent 用 key。
    func shortName(_ agent: String) -> String {
        let label = report.agentLabels[agent] ?? agent.capitalized
        return String(label.split(separator: " ").first ?? Substring(label))
    }

    private func formatter(_ format: String, _ cal: Calendar) -> DateFormatter {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.calendar = cal
        f.timeZone = cal.timeZone
        f.dateFormat = format
        return f
    }
}

/// 紧凑的分段控件（自绘胶囊）：All · 7d · 30d · Last week · Since reset。
/// 「Since reset」不可用时画成三级色、不可点，tooltip「No reset info」。
struct RangePicker: View {
    @Binding var raw: String
    let effective: TimeRange
    let resetAvailable: Bool

    var body: some View {
        HStack(spacing: 0) {
            ForEach(TimeRange.allCases) { r in
                segment(r)
            }
        }
        .padding(1.5)
        .background(Capsule().fill(Color.primary.opacity(0.06)))
        .fixedSize()
    }

    @ViewBuilder private func segment(_ r: TimeRange) -> some View {
        let selected = r == effective
        let label = Text(r.shortLabel)
            .font(.system(size: 10, weight: selected ? .semibold : .regular))
            .lineLimit(1)
            .padding(.horizontal, 6).padding(.vertical, 2.5)
            .background(Capsule().fill(selected ? Color.primary.opacity(0.13) : Color.clear))
            .contentShape(Capsule())
        if r == .sinceReset && !resetAvailable {
            // 不用 .disabled：禁用的按钮在 macOS 上不显示 tooltip。
            label.foregroundStyle(.tertiary).help("No reset info")
        } else {
            Button {
                withAnimation(.easeOut(duration: 0.15)) { raw = r.rawValue }
            } label: {
                label.foregroundStyle(selected ? .primary : .secondary)
            }
            .buttonStyle(.plain)
            .help(r.longLabel)
        }
    }
}

/// 范围说明行：caption 字号、次要色、可折行。
struct RangeCaption: View {
    let text: String
    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 4) {
            Image(systemName: "calendar")
            Text(text).fixedSize(horizontal: false, vertical: true)
        }
        .font(.system(size: 10.5))
        .foregroundStyle(.secondary)
        .monospacedDigit()
    }
}
