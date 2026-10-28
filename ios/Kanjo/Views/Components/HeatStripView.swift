import KanjoCore
import SwiftUI

/// 8 周燃烧热力条：每格一周，整格深浅按该周花费分档，格内按 agent 花费份额纵向分段。
struct ProjectHeatStrip: View {
    let weeks: [WeekCost]
    var cell = CGSize(width: 12, height: 20)
    var radius: CGFloat = 3
    var spacing: CGFloat = 2

    private static let opacities: [Double] = [0, 0.3, 0.52, 0.76, 1]

    var body: some View {
        let peak = weeks.map(\.cost).max() ?? 0
        HStack(spacing: spacing) {
            ForEach(weeks.indices, id: \.self) { index in
                cellView(weeks[index], level: HeatStrip.level(weeks[index].cost, max: peak))
                    .frame(width: cell.width, height: cell.height)
            }
        }
        .fixedSize()
    }

    @ViewBuilder
    private func cellView(_ week: WeekCost, level: Int) -> some View {
        let shape = RoundedRectangle(cornerRadius: radius, style: .continuous)
        let segments = HeatStrip.segments(week)
        if level == 0 || segments.isEmpty {
            shape.fill(IOSPalette.heatEmpty)
        } else {
            let cumulative = segments.indices.map { index in
                segments[0...index].reduce(0) { $0 + $1.share }
            }
            ZStack(alignment: .top) {
                ForEach(segments.indices.reversed(), id: \.self) { index in
                    Rectangle()
                        .fill(IOSPalette.agent(segments[index].agent))
                        .frame(height: index == segments.count - 1
                               ? cell.height
                               : cell.height * CGFloat(cumulative[index]))
                }
            }
            .frame(width: cell.width, height: cell.height, alignment: .top)
            .clipShape(shape)
            .compositingGroup()
            .opacity(Self.opacities[min(max(level, 0), Self.opacities.count - 1)])
        }
    }
}

extension UsageReport {
    /// 热力条以报告生成日结束；解析不了就用最后活跃日，再不行用今天。
    var heatEndDate: Date {
        ReportDates.parseTimestamp(generatedAt)
            ?? totals.lastActive.flatMap(ReportDates.parseDay)
            ?? Date()
    }
}

extension Project {
    func heatWeeks(endingOn end: Date) -> [WeekCost] {
        HeatStrip.weekly(byDay, endingOn: end,
                         fallbackAgent: dominantAgent(byAgent)?.agent
                            ?? byAgent.first?.agent
                            ?? "unknown")
    }
}
