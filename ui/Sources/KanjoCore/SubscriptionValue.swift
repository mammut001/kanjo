import Foundation

// 订阅价值（CONTRACT.md 7.4.1）：纯函数。账期用量走 RangeEngine，和「Billing cycle」范围同一套口径。
// 视图只负责把这些数字画出来。

/// 契约要求卡片底部固定的一句，不可隐藏。
public var subscriptionValueExplanation: String {
    L10n.tr("overview.subscription_value.explanation")
}

public enum SubscriptionValue {
    public static var assumedDayHelp: String {
        L10n.tr("overview.renewal_day_unknown_help")
    }

    public static func needsRenewalDay(_ sub: Subscription) -> Bool {
        sub.cycleSource == "rolling_30d"
    }

    public static func billingPage(for agent: String) -> URL? {
        switch agent {
        case "claude": return URL(string: "https://claude.ai/settings/billing")
        case "codex": return URL(string: "https://chatgpt.com/settings/billing")
        case "antigravity": return URL(string: "https://one.google.com/subscriptions")
        case "copilot": return URL(string: "https://github.com/settings/copilot")
        case "grok": return URL(string: "https://x.com/settings/premium")
        case "minimax": return URL(string: "https://platform.minimax.io")
        case "qwen": return URL(string: "https://dashscope.console.aliyun.com")
        case "commandcode": return URL(string: "https://commandcode.ai")
        case "opencode": return URL(string: "https://opencode.ai")
        default: return nil
        }
    }

    /// cycle_source 优先：手填档位也可能仍然不知道续费日。
    public static func anchorSource(_ sub: Subscription) -> String {
        switch sub.cycleSource {
        case "rolling_30d": return L10n.tr("settings.source.not_set")
        case "manual": return L10n.tr("settings.source.manual")
        case "subscription_date": return L10n.tr("settings.source.detected")
        default: return sub.source == "manual" ? L10n.tr("settings.source.manual") : L10n.tr("settings.source.detected")
        }
    }

    /// 用量 ÷ 月费。月费为空或不是正数时为 nil（界面显示「—」，不显示倍数）。
    public static func multiplier(usage: Double, monthlyPriceUsd: Double?) -> Double? {
        guard let price = monthlyPriceUsd, price > 0, usage.isFinite else { return nil }
        let m = usage / price
        return m.isFinite ? m : nil
    }

    /// 本项目账期用量 ÷ 该 agent 全部账期用量。总量为 0 时没有占比（调用方跳过这一行）。
    public static func share(part: Double, total: Double) -> Double? {
        guard total > 0, part.isFinite, total.isFinite else { return nil }
        return part / total
    }

    /// 每个有订阅的 agent 一行，按账期用量降序。用量是该 agent 从自己的 cycle_start 到 now，
    /// 全部项目加上 unattributed / excluded 的 API 等价金额。
    public static func rows(of report: UsageReport, now: Date = Date()) -> [SubscriptionRow] {
        let subs = report.subscriptions ?? [:]
        guard !subs.isEmpty else { return [] }
        let usage = cycleUsage(of: report, now: now)
        return subs.map { agent, sub in
            let cost = usage.total(for: agent)
            return SubscriptionRow(
                agent: agent, planLabel: sub.planLabel, monthlyPriceUsd: sub.monthlyPriceUsd,
                usage: cost, multiplier: multiplier(usage: cost, monthlyPriceUsd: sub.monthlyPriceUsd),
                extraUsageEnabled: sub.extraUsageEnabled)
        }.sorted { a, b in
            a.usage != b.usage ? a.usage > b.usage : a.agent < b.agent
        }
    }

    /// 这个项目里、有订阅且账期总量 > 0 的 agent。占比 = 本项目账期 cost ÷ 该 agent 全部账期 cost。
    /// 按占比降序。总量为 0 的 agent 跳过。
    public static func shares(project id: String, report: UsageReport, now: Date = Date()) -> [CycleShare] {
        let subs = report.subscriptions ?? [:]
        guard !subs.isEmpty else { return [] }
        let usage = cycleUsage(of: report, now: now)
        var out: [CycleShare] = []
        for (agent, sub) in subs {
            let total = usage.total(for: agent)
            let part = usage.cost(project: id, agent: agent)
            guard let share = share(part: part, total: total) else { continue }
            out.append(CycleShare(agent: agent, planLabel: sub.planLabel, share: share, projectCost: part))
        }
        return out.sorted { a, b in
            a.share != b.share ? a.share > b.share : a.agent < b.agent
        }
    }

    /// 按各 agent 自己的 cycle_start 过滤后的金额。项目走 by_day，两个桶走 sessions_detail。
    public static func cycleUsage(of report: UsageReport, now: Date = Date()) -> CycleUsage {
        let spec = RangeEngine.spec(.billingCycle, report: report, now: now)
        let filtered = RangeEngine.filtered(report, range: spec, fallbackAgentFor: fallbackAgent)
        var totals: [String: Double] = [:]
        var byProject: [String: [String: Double]] = [:]
        for p in filtered.projects {
            var costs: [String: Double] = [:]
            for a in p.byAgent where a.cost != 0 {
                costs[a.agent] = a.cost
                totals[a.agent, default: 0] += a.cost
            }
            if !costs.isEmpty { byProject[p.id] = costs }
        }
        for s in filtered.unattributed.sessionsDetail + filtered.excluded.sessionsDetail {
            totals[s.agent, default: 0] += s.cost
        }
        return CycleUsage(totalByAgent: totals, projectAgentCost: byProject)
    }

    /// 和总览 RangeContext 一样：缺 by_agent 时记到项目的主力 agent。
    private static func fallbackAgent(_ p: Project) -> String {
        dominantAgent(p.byAgent)?.agent ?? p.byAgent.first?.agent ?? "unknown"
    }
}

/// 提醒按 agent 记住关闭状态；新出现的未知续费日仍会提醒。
public enum RenewalNudge {
    public static func parseDismissed(_ raw: String) -> Set<String> {
        Set(raw.split(separator: ",").map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty })
    }

    public static func serializeDismissed(_ agents: Set<String>) -> String {
        agents.sorted().joined(separator: ",")
    }

    public static func pendingAgents(subscriptions: [String: Subscription], dismissed: Set<String>) -> [String] {
        subscriptions.filter { SubscriptionValue.needsRenewalDay($0.value) && !dismissed.contains($0.key) }
            .map(\.key).sorted()
    }
}

/// 设置行的导航字符串同时作为 ScrollViewReader 的 anchor，不依赖报告是否加载。
public enum SubscriptionSettingsRoute {
    public static func anchor(for agent: String) -> String { "settings:subscriptions:\(agent)" }

    public static func agent(from raw: String) -> String? {
        let parts = raw.split(separator: ":", omittingEmptySubsequences: false)
        guard parts.count == 3, parts[0] == "settings", parts[1] == "subscriptions", !parts[2].isEmpty else { return nil }
        return String(parts[2])
    }

    public static func editAgent(from raw: String) -> String? {
        let parts = raw.split(separator: ":", omittingEmptySubsequences: false)
        guard parts.count == 4, parts[0] == "settings", parts[1] == "subscriptions", !parts[2].isEmpty, parts[3] == "edit" else { return nil }
        return String(parts[2])
    }
}

public struct SubscriptionRow: Equatable, Identifiable {
    public var agent: String
    public var planLabel: String
    public var monthlyPriceUsd: Double?
    public var usage: Double
    public var multiplier: Double?
    public var extraUsageEnabled: Bool
    public var id: String { agent }
}

public struct CycleShare: Equatable, Identifiable {
    public var agent: String
    public var planLabel: String
    public var share: Double
    public var projectCost: Double
    public var id: String { agent }
}

public struct CycleUsage: Equatable {
    public var totalByAgent: [String: Double]
    public var projectAgentCost: [String: [String: Double]]

    public func total(for agent: String) -> Double { totalByAgent[agent] ?? 0 }

    public func cost(project id: String, agent: String) -> Double {
        projectAgentCost[id]?[agent] ?? 0
    }
}
