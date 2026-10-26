import Foundation

/// 悬停提示文本构建器：纯逻辑，方便测试。
/// 保证所有带颜色的图块悬停时展示一致的金额与 token 信息。
public enum TooltipBuilder {
    /// 统一金额与 token 格式化，如 "$12.34 · 1.2亿 token"。
    public static func costAndTokens(cost: Double, tokens: Int, currency: String = "USD", language: String? = nil) -> String {
        Fmt.costAndTokens(cost: cost, tokens: tokens, currency: currency, language: language)
    }

    /// 单个 agent 格式化行，如 "● Claude Code  $10.00 · 9000万 token"。
    public static func agentLine(label: String, cost: Double, tokens: Int, currency: String = "USD", language: String? = nil) -> String {
        let formatted = costAndTokens(cost: cost, tokens: tokens, currency: currency, language: language)
        return "● \(label)  \(formatted)"
    }

    /// 按花费降序排列的 per-agent 行（花费相同按标签字母排序）。
    public static func agentLines(
        items: [(label: String, cost: Double, tokens: Int)],
        currency: String = "USD",
        language: String? = nil
    ) -> [String] {
        let active = items.filter { $0.cost > 0 || $0.tokens > 0 }
            .sorted { $0.cost != $1.cost ? $0.cost > $1.cost : $0.label < $1.label }
        return active.map { agentLine(label: $0.label, cost: $0.cost, tokens: $0.tokens, currency: currency, language: language) }
    }

    public static func agentLines(
        agents: [AgentCost],
        currency: String = "USD",
        language: String? = nil
    ) -> [String] {
        let items = agents.map { (label: $0.label, cost: $0.cost, tokens: $0.tokens.total) }
        return agentLines(items: items, currency: currency, language: language)
    }

    public static func agentLines(
        byAgent: [String: Double]?,
        byAgentTokens: [String: Int]?,
        agentLabels: [String: String],
        currency: String = "USD",
        language: String? = nil
    ) -> [String] {
        let keys = Set((byAgent ?? [:]).keys).union((byAgentTokens ?? [:]).keys)
        let items: [(label: String, cost: Double, tokens: Int)] = keys.map { k in
            let label = agentLabels[k] ?? AgentColors.defaultLabels[k] ?? k
            let cost = byAgent?[k] ?? 0
            let tokens = byAgentTokens?[k] ?? 0
            return (label: label, cost: cost, tokens: tokens)
        }
        return agentLines(items: items, currency: currency, language: language)
    }

    /// 马赛克项目方块 tooltip：
    /// 项目名 · $12.34 · 1.2亿 token
    /// ● Claude Code  $10.00 · 9000万 token
    public static func projectTileTooltip(
        name: String,
        cost: Double,
        tokens: Int,
        agents: [AgentCost],
        currency: String = "USD",
        language: String? = nil
    ) -> String {
        let header = "\(name) · \(costAndTokens(cost: cost, tokens: tokens, currency: currency, language: language))"
        let lines = agentLines(agents: agents, currency: currency, language: language)
        if lines.isEmpty { return header }
        return ([header] + lines).joined(separator: "\n")
    }

    /// 合并小项目的总和计算。
    public static func mergedTileSum(projects: [(cost: Double, tokens: Int)]) -> (cost: Double, tokens: Int) {
        let totalCost = projects.reduce(0.0) { $0 + $1.cost }
        let totalTokens = projects.reduce(0) { $0 + $1.tokens }
        return (totalCost, totalTokens)
    }

    public static func mergedTileSum(projects: [Project]) -> (cost: Double, tokens: Int) {
        mergedTileSum(projects: projects.map { (cost: $0.cost, tokens: $0.tokens.total) })
    }

    /// 马赛克 "+N more" 合并方块 tooltip：
    /// 5 个较小项目 · $12.34 · 1.2亿 token
    /// foo  $10.00 · 9000万 token
    /// bar  $2.34 · 3000万 token
    public static func mergedTileTooltip(
        projects: [Project],
        currency: String = "USD",
        language: String? = nil
    ) -> String {
        let lang = language ?? L10n.currentLanguage
        let (totalCost, totalTokens) = mergedTileSum(projects: projects)
        let sumStr = costAndTokens(cost: totalCost, tokens: totalTokens, currency: currency, language: lang)
        // 注意 L10n.tr("mosaic.smaller_projects") 模板自带末尾换行符 "\n"
        let header = L10n.tr("mosaic.smaller_projects", language: lang, projects.count, sumStr)
        let sorted = projects.sorted { $0.cost != $1.cost ? $0.cost > $1.cost : $0.name < $1.name }
        let projectLines = sorted.map { p in
            "\(p.name)  \(costAndTokens(cost: p.cost, tokens: p.tokens.total, currency: currency, language: lang))"
        }
        let body = projectLines.joined(separator: "\n")
        return body.isEmpty ? header.trimmingCharacters(in: .newlines) : header + body
    }

    /// 热力条周格 tooltip：
    /// Oct 13–19 · $42.10 · 1.2亿 token
    /// ● Claude Code  $30.00 · 9000万 token
    public static func weekTooltip(
        weekLabel: String,
        cost: Double,
        tokens: Int,
        byAgent: [String: Double],
        byAgentTokens: [String: Int],
        agentLabels: [String: String],
        currency: String = "USD",
        language: String? = nil
    ) -> String {
        let header = "\(weekLabel) · \(costAndTokens(cost: cost, tokens: tokens, currency: currency, language: language))"
        let lines = agentLines(byAgent: byAgent, byAgentTokens: byAgentTokens, agentLabels: agentLabels, currency: currency, language: language)
        if lines.isEmpty { return header }
        return ([header] + lines).joined(separator: "\n")
    }

    /// 日图表 tooltip：
    /// 2026年10月24日 · $12.34 · 1.2亿 token
    /// ● Claude Code  $10.00 · 9000万 token
    public static func dayTooltip(
        dayString: String,
        cost: Double,
        tokens: Int,
        byAgent: [String: Double]? = nil,
        byAgentTokens: [String: Int]? = nil,
        agentLabels: [String: String] = [:],
        currency: String = "USD",
        language: String? = nil
    ) -> String {
        let lang = language ?? L10n.currentLanguage
        let dayFormatted = Fmt.day(dayString, language: lang)
        let header = "\(dayFormatted) · \(costAndTokens(cost: cost, tokens: tokens, currency: currency, language: lang))"
        let lines = agentLines(byAgent: byAgent, byAgentTokens: byAgentTokens, agentLabels: agentLabels, currency: currency, language: lang)
        if lines.isEmpty { return header }
        return ([header] + lines).joined(separator: "\n")
    }

    /// 模型行 tooltip：
    /// claude-3-5-sonnet (claude) · $10.00 · 9000万 token
    public static func modelTooltip(
        model: String,
        agent: String,
        cost: Double,
        tokens: Int,
        currency: String = "USD",
        language: String? = nil
    ) -> String {
        let ct = costAndTokens(cost: cost, tokens: tokens, currency: currency, language: language)
        return "\(model) (\(agent)) · \(ct)"
    }
}

/// 总览摘要行构建器：Today 隐藏冗余日期，其他范围保留。
public enum OverviewSummaryText {
    public static func make(
        range: TimeRange,
        dateRange: String,
        projectsCount: Int,
        sessionsCount: Int,
        tokensCount: Int,
        hiddenCount: Int = 0,
        language: String? = nil
    ) -> String {
        let lang = language ?? L10n.currentLanguage
        let projSingular = L10n.tr("overview.count.project.singular", language: lang, projectsCount)
        let projPlural = L10n.tr("overview.count.project.plural", language: lang, projectsCount)
        let projCountStr = projectsCount == 1 ? projSingular : projPlural
        let hiddenStr = hiddenCount > 0 ? L10n.tr("overview.count.hidden", language: lang, hiddenCount) : ""
        let projects = projCountStr + hiddenStr

        let sessSingular = L10n.tr("overview.count.session.singular", language: lang, sessionsCount)
        let sessPlural = L10n.tr("overview.count.session.plural", language: lang, sessionsCount)
        let sessCountStr = sessionsCount == 1 ? sessSingular : sessPlural

        let tokensFormatted = Fmt.tokens(tokensCount, language: lang)
        let tokensStr = L10n.tr("overview.tokens_count", language: lang, tokensFormatted)

        let counts = [projects, sessCountStr, tokensStr].joined(separator: " · ")
        if range == .today {
            return counts
        }
        return "\(dateRange) · \(counts)"
    }
}

/// 项目详情副标题行：Today 隐藏冗余日期，其他范围保留。
public enum ProjectSubtitleText {
    public static func make(
        range: TimeRange,
        sessions: Int,
        usageDate: String,
        language: String? = nil
    ) -> String {
        let lang = language ?? L10n.currentLanguage
        let sessSingular = L10n.tr("overview.count.session.singular", language: lang, sessions)
        let sessPlural = L10n.tr("overview.count.session.plural", language: lang, sessions)
        let sessStr = sessions == 1 ? sessSingular : sessPlural
        if range == .today {
            return sessStr
        }
        let templateKey = sessions == 1 ? "project.subtitle.singular" : "project.subtitle.plural"
        return L10n.tr(templateKey, language: lang, sessions, usageDate)
    }
}
