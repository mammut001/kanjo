import SwiftUI
import KanjoCore

/// 当前生效的时间范围：存储值 + 报告 → 区间、过滤结果、说明文字。
/// 「Since reset」在报告没有 quota_windows 时不可用，「Billing cycle」在没有 subscriptions 时不可用；
/// 存储值是它们也按 All 显示。
struct RangeContext {
    let report: UsageReport
    let range: TimeRange
    let spec: RangeSpec
    let resetAvailable: Bool
    let cycleAvailable: Bool

    init(report: UsageReport, raw: String, now: Date = Date()) {
        self.report = report
        let reset = !(report.quotaWindows ?? [:]).isEmpty
        let cycle = !(report.subscriptions ?? [:]).isEmpty
        let wanted = TimeRange(rawValue: raw) ?? .all
        switch wanted {
        case .sinceReset where !reset: range = .all
        case .billingCycle where !cycle: range = .all
        default: range = wanted
        }
        resetAvailable = reset
        cycleAvailable = cycle
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

    /// 范围说明结果（仅 Since reset / Billing cycle 有值；All / Today / 7d / 30d / Last week 为 nil）。
    var captionResult: RangeCaptionResult? {
        RangeCaptionBuilder.caption(
            for: range,
            spec: spec,
            agentOrder: agentOrder,
            agentLabels: report.agentLabels,
            subscriptions: report.subscriptions
        )
    }

    /// 范围说明文本（仅 Since reset / Billing cycle 有值；All / Today / 7d / 30d / Last week 为 nil）。
    /// 例：
    /// `Since Claude reset Oct 20 10:00 · Codex reset Oct 21 08:00 · 6 others have no reset info (not counted)`；
    /// `Billing cycle · Claude Max 5x since Oct 25 · ChatGPT Plus since Nov 1 · Antigravity: no subscription`。
    var caption: String? {
        captionResult?.text
    }

    /// 未计入 agent 的悬浮提示（若有）。
    var captionHelp: String? {
        captionResult?.help
    }

    /// 报告里出现的 agent（按总花费降序），后面接只在 quota_windows / subscriptions 里出现的。
    var agentOrder: [String] {
        RangeCaptionBuilder.agentOrder(report: report)
    }

    /// "Claude Code" → "Claude"；未知 agent 用 key。
    func shortName(_ agent: String) -> String {
        RangeCaptionBuilder.shortName(for: agent, labels: report.agentLabels)
    }
}

/// 紧凑的分段控件（自绘胶囊）：All · Today · 7d · 30d · Last week · Since reset · Cycle。
/// 「Since reset」不可用时画成三级色、不可点，tooltip「No reset info」；
/// 「Cycle」同理，tooltip「No subscription info」。
struct RangePicker: View {
    @Binding var raw: String
    let effective: TimeRange
    let resetAvailable: Bool
    let cycleAvailable: Bool

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

    /// 没有对应数据时的 tooltip；nil 表示这段可以点。
    private func unavailable(_ r: TimeRange) -> String? {
        if r == .sinceReset && !resetAvailable { return L10n.tr("timerange.tooltip.no_reset_info") }
        if r == .billingCycle && !cycleAvailable { return L10n.tr("timerange.tooltip.no_subscription_info") }
        return nil
    }

    @ViewBuilder private func segment(_ r: TimeRange) -> some View {
        let selected = r == effective
        let label = Text(r.shortLabel)
            .font(.system(size: 9.5, weight: selected ? .semibold : .regular))
            .lineLimit(1)
            .padding(.horizontal, 4).padding(.vertical, 2.5)
            .background(Capsule().fill(selected ? Color.primary.opacity(0.13) : Color.clear))
            .contentShape(Capsule())
        if let reason = unavailable(r) {
            // 不用 .disabled：禁用的按钮在 macOS 上不显示 tooltip。
            label.foregroundStyle(.tertiary).hoverTip(reason)
        } else {
            Button {
                withAnimation(.easeOut(duration: 0.15)) { raw = r.rawValue }
            } label: {
                label.foregroundStyle(selected ? .primary : .secondary)
            }
            .buttonStyle(.plain)
            .hoverTip(r.longLabel)
        }
    }
}

/// 范围说明行：caption 字号、次要色、可折行。
struct RangeCaption: View {
    let text: String
    var help: String? = nil

    init(text: String, help: String? = nil) {
        self.text = text
        self.help = help
    }

    init(caption: RangeCaptionResult) {
        self.text = caption.text
        self.help = caption.help
    }

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 4) {
            Image(systemName: "calendar")
            Text(text).fixedSize(horizontal: false, vertical: true)
        }
        .font(.system(size: 10.5))
        .foregroundStyle(.secondary)
        .monospacedDigit()
        .hoverTip(help)
    }
}
