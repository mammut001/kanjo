import Foundation

/// 范围说明结果：text 为显示的说明文字；help 为悬浮提示（当有多个未计入的 agent 时，列出其短名）。
public struct RangeCaptionResult: Equatable {
    public var text: String
    public var help: String?

    public init(text: String, help: String? = nil) {
        self.text = text
        self.help = help
    }
}

public enum RangeCaptionBuilder {
    /// 报告里出现的 agent（按总花费降序），后面接只在 quota_windows / subscriptions 里出现的（按 key 升序）。
    public static func agentOrder(report: UsageReport) -> [String] {
        var cost: [String: Double] = [:]
        for p in report.projects {
            for a in p.byAgent {
                cost[a.agent, default: 0] += a.cost
            }
        }
        let used = cost.sorted { $0.value != $1.value ? $0.value > $1.value : $0.key < $1.key }.map(\.key)
        var extraKeys = Set((report.quotaWindows ?? [:]).keys)
        extraKeys.formUnion((report.subscriptions ?? [:]).keys)
        let extra = extraKeys.filter { cost[$0] == nil }.sorted()
        return used + extra
    }

    /// "Claude Code" → "Claude"；未知 agent 用 key。
    public static func shortName(for agent: String, labels: [String: String] = [:]) -> String {
        let label = labels[agent] ?? AgentColors.defaultLabels[agent] ?? agent.capitalized
        return String(label.split(separator: " ").first ?? Substring(label))
    }

    /// 范围说明纯函数（仅 Since reset / Billing cycle 有值；All / Today / 7d / 30d / Last week 为 nil）。
    public static func caption(
        for range: TimeRange,
        spec: RangeSpec,
        agentOrder: [String],
        agentLabels: [String: String] = [:],
        subscriptions: [String: Subscription]? = nil,
        language: String? = nil
    ) -> RangeCaptionResult? {
        let cal = spec.calendar
        let lang = language ?? L10n.currentLanguage
        let mdt = templateFormatter("MMMdHHmm", cal, language: lang)

        switch range {
        case .all, .today, .days7, .days30, .lastWeek:
            return nil
        case .sinceReset:
            let withReset = agentOrder.filter { spec.agentStarts[$0] != nil }
            let without = agentOrder.filter { spec.agentStarts[$0] == nil }

            var parts = withReset.map { agent in
                L10n.tr("timerange.caption.reset", language: lang,
                        shortName(for: agent, labels: agentLabels),
                        mdt.string(from: spec.agentStarts[agent]!))
            }
            if !parts.isEmpty {
                parts[0] = L10n.tr("timerange.caption.since", language: lang,
                                   shortName(for: withReset[0], labels: agentLabels),
                                   mdt.string(from: spec.agentStarts[withReset[0]]!))
            }

            var help: String? = nil
            if without.count == 1 {
                let name = shortName(for: without[0], labels: agentLabels)
                parts.append(L10n.tr("timerange.caption.no_reset_info", language: lang, name))
            } else if without.count > 1 {
                parts.append(L10n.tr("timerange.caption.no_reset_info_others", language: lang, without.count))
                help = without.map { shortName(for: $0, labels: agentLabels) }.joined(separator: ", ")
            }

            if parts.isEmpty {
                return RangeCaptionResult(text: L10n.tr("timerange.sinceReset.long", language: lang))
            }
            return RangeCaptionResult(text: parts.joined(separator: " · "), help: help)

        case .billingCycle:
            let withCycle = agentOrder.filter { spec.agentStarts[$0] != nil }
            let without = agentOrder.filter { spec.agentStarts[$0] == nil }

            let cycleParts = withCycle.map { agent -> String in
                guard let sub = subscriptions?[agent] else {
                    return shortName(for: agent, labels: agentLabels)
                }
                return Fmt.cycleRangeCaption(sub, timezone: cal.timeZone, language: lang)
            }
            var parts = [L10n.tr("timerange.billingCycle.long", language: lang)] + cycleParts

            var help: String? = nil
            if without.count == 1 {
                let name = shortName(for: without[0], labels: agentLabels)
                parts.append(L10n.tr("timerange.caption.no_subscription", language: lang, name))
            } else if without.count > 1 {
                parts.append(L10n.tr("timerange.caption.no_subscription_others", language: lang, without.count))
                help = without.map { shortName(for: $0, labels: agentLabels) }.joined(separator: ", ")
            }

            return RangeCaptionResult(text: parts.joined(separator: " · "), help: help)
        }
    }

    public static func caption(
        for range: TimeRange,
        report: UsageReport,
        now: Date = Date(),
        language: String? = nil
    ) -> RangeCaptionResult? {
        let spec = RangeEngine.spec(range, report: report, now: now)
        return caption(
            for: range,
            spec: spec,
            agentOrder: agentOrder(report: report),
            agentLabels: report.agentLabels,
            subscriptions: report.subscriptions,
            language: language
        )
    }

    public static func templateFormatter(_ template: String, _ cal: Calendar, language: String? = nil) -> DateFormatter {
        let f = DateFormatter()
        f.locale = Locale(identifier: language ?? L10n.currentLanguage)
        f.calendar = cal
        f.timeZone = cal.timeZone
        f.setLocalizedDateFormatFromTemplate(template)
        return f
    }
}
