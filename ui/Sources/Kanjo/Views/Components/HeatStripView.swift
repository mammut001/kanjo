import SwiftUI
import KanjoCore

/// 8 周燃烧热力条：每格一周（周一到周日）。
/// 每格按那周各 agent 的 cost 份额纵向分成最多 3 段色带（上到下按 cost 降序，份额 < 10% 的并进最大那段），
/// 段间不留缝；整格深浅按该周花费 / 8 周最大周花费分 5 档（opacity 作用在整格上），0 档是中性底。
struct HeatStripView: View {
    let weeks: [WeekCost]
    /// agent key → 显示名（tooltip 用）；查不到就显示 key。
    let agentLabels: [String: String]
    let currency: String
    var cell = CGSize(width: 8, height: 16)
    var radius: CGFloat = 2
    var spacing: CGFloat = 2

    /// 档位 1…4 的不透明度；0 档用中性 8% 底色。
    private static let opacities: [Double] = [0, 0.3, 0.52, 0.76, 1]

    /// 整条宽度（行里用来给悬停按钮留位置）。
    var width: CGFloat {
        CGFloat(weeks.count) * cell.width + CGFloat(max(weeks.count - 1, 0)) * spacing
    }

    var body: some View {
        let peak = weeks.map(\.cost).max() ?? 0
        HStack(spacing: spacing) {
            ForEach(Array(weeks.enumerated()), id: \.offset) { _, w in
                cellView(w, level: HeatStrip.level(w.cost, max: peak))
                    .frame(width: cell.width, height: cell.height)
                    .help(label(w))
            }
        }
        .fixedSize()
    }

    @ViewBuilder private func cellView(_ w: WeekCost, level: Int) -> some View {
        let shape = RoundedRectangle(cornerRadius: radius, style: .continuous)
        let segs = HeatStrip.segments(w)
        if level == 0 || segs.isEmpty {
            shape.fill(AgentPalette.heatEmpty)
        } else {
            // 从下往上叠：每段的高度 = 它和它上面各段的份额之和，顶端对齐。
            // 互相覆盖而不是并排，避免小数高度在段间漏出缝。
            let cumulative = segs.indices.map { i in segs[0...i].reduce(0) { $0 + $1.share } }
            ZStack(alignment: .top) {
                ForEach(segs.indices.reversed(), id: \.self) { i in
                    Rectangle()
                        .fill(AgentPalette.color(for: segs[i].agent))
                        .frame(height: i == segs.count - 1 ? cell.height : cell.height * cumulative[i])
                }
            }
            .frame(width: cell.width, height: cell.height, alignment: .top)
            .clipShape(shape)
            .compositingGroup()
            .opacity(Self.opacities[level])
        }
    }

    /// "Oct 13–19 · $42.10 · 1.2亿 token"，下面每个 agent 一行 "● Claude Code  $30.00 · 9000万 token"，按 cost 降序。
    private func label(_ w: WeekCost) -> String {
        TooltipBuilder.weekTooltip(
            weekLabel: HeatStrip.weekLabel(start: w.start),
            cost: w.cost,
            tokens: w.tokens,
            byAgent: w.byAgent,
            byAgentTokens: w.byAgentTokens,
            agentLabels: agentLabels,
            currency: currency
        )
    }
}

extension UsageReport {
    /// 热力条的结束日期：报告生成日（落在本地时区）；解析不了就用最后活跃日，再不行用今天。
    var heatEndDate: Date {
        ReportDates.parseTimestamp(generatedAt)
            ?? totals.lastActive.flatMap(ReportDates.parseDay)
            ?? Date()
    }
}

extension Project {
    /// 缺 by_day.by_agent 的旧数据回退到项目的主力 agent；项目没有正花费时记到 "unknown"（中性灰）。
    func heatWeeks(endingOn end: Date) -> [WeekCost] {
        HeatStrip.weekly(byDay, endingOn: end,
                         fallbackAgent: dominantAgent(byAgent)?.agent ?? byAgent.first?.agent ?? "unknown")
    }
}
